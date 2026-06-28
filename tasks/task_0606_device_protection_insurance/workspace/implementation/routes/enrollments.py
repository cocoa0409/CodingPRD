"""Enrollments and Premium Invoices."""
from datetime import timedelta

from flask import Blueprint

import errors
from calculations import luhn_valid
from clock import clock, parse_iso
from db import db, new_id
from helpers import (serialize, base_system_fields, touch, get_or_404,
                     parse_pagination, paginate, sorted_by_created,
                     body, require_str, require_int)
from middleware import require_auth, require_role
from response import ok, ok_list

bp = Blueprint("enrollments", __name__)


def _imei_in_use(imei, exclude_id=None):
    for e in db.enrollments.values():
        if e["id"] == exclude_id:
            continue
        if e["imei"] == imei and e["status"] != "CANCELLED":
            return True
    return False


def _owner_check(role, user_id, enrollment):
    if role == "Subscriber" and enrollment["customer_id"] != user_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Subscriber does not own this enrollment")


# ---------------- Enrollments ----------------
@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    user_id, role = require_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    b = body()
    customer_id = require_str(b, "customer_id")
    plan_id = require_str(b, "plan_id")
    imei = require_str(b, "imei")
    device_model = require_str(b, "device_model")
    device_purchase_date_raw = require_str(b, "device_purchase_date")
    replacement_sku_id = require_str(b, "replacement_sku_id")

    # left-to-right existence (after required-field presence)
    get_or_404(db.customers, customer_id)
    get_or_404(db.plans, plan_id)
    get_or_404(db.replacement_skus, replacement_sku_id)

    # ownership: subscriber may only create for their own customer
    if role == "Subscriber" and customer_id != user_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Subscriber does not own this customer")

    try:
        dpd = parse_iso(device_purchase_date_raw)
    except ValueError:
        errors.fail(errors.ERR_VALIDATION, "device_purchase_date invalid")

    # IMEI Luhn (priority 7) then uniqueness (priority 8)
    if not luhn_valid(imei):
        errors.fail(errors.ERR_INVALID_IMEI, "IMEI must be 15 digits and pass Luhn")
    if _imei_in_use(imei):
        errors.fail(errors.ERR_DUPLICATE_IMEI, "IMEI already in use by a non-CANCELLED enrollment")

    eid = new_id()
    enr = {
        "id": eid,
        "customer_id": customer_id,
        "plan_id": plan_id,
        "imei": imei,
        "device_model": device_model,
        "device_purchase_date": dpd,
        "replacement_sku_id": replacement_sku_id,
        "status": "PENDING_ELIGIBILITY",
        "enrolled_at": None,
        "premium_paid_through_cycle": -1,
        "open_claim_id": None,
        "_seq": db.next_seq(),
    }
    enr.update(base_system_fields(versioned=True))
    db.enrollments[eid] = enr
    return ok(serialize(enr), 201)


@bp.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    user_id, role = require_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "ClaimsAdjuster"})
    enr = get_or_404(db.enrollments, eid)
    _owner_check(role, user_id, enr)
    return ok(serialize(enr), 200)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    user_id, role = require_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "ClaimsAdjuster"})
    from flask import request
    limit, offset = parse_pagination()
    vals = list(db.enrollments.values())
    if role == "Subscriber":
        vals = [e for e in vals if e["customer_id"] == user_id]
    cust_f = request.args.get("customer_id")
    plan_f = request.args.get("plan_id")
    sku_f = request.args.get("replacement_sku_id")
    if cust_f is not None:
        vals = [e for e in vals if e["customer_id"] == cust_f]
    if plan_f is not None:
        vals = [e for e in vals if e["plan_id"] == plan_f]
    if sku_f is not None:
        vals = [e for e in vals if e["replacement_sku_id"] == sku_f]
    vals = sorted_by_created(vals)
    total = len(vals)
    page = paginate(vals, limit, offset)
    return ok_list([serialize(e) for e in page], limit, offset, total)


@bp.route("/enrollments/<eid>/activate", methods=["POST"])
def activate_enrollment(eid):
    _, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    enr = get_or_404(db.enrollments, eid)
    if enr["status"] not in ("PENDING_ELIGIBILITY", "SUSPENDED"):
        errors.fail(errors.ERR_INVALID_STATE, "Cannot activate from current status")

    if enr["status"] == "PENDING_ELIGIBILITY":
        # referenced plan and SKU exist
        get_or_404(db.plans, enr["plan_id"])
        get_or_404(db.replacement_skus, enr["replacement_sku_id"])
        if _imei_in_use(enr["imei"], exclude_id=enr["id"]):
            errors.fail(errors.ERR_DUPLICATE_IMEI, "IMEI used by another non-CANCELLED enrollment")
        enr["status"] = "ACTIVE"
        enr["enrolled_at"] = clock.now()
        touch(enr)
    else:  # SUSPENDED -> ACTIVE reinstatement
        current_cycle = _current_cycle(enr)
        if enr["premium_paid_through_cycle"] < current_cycle:
            errors.fail(errors.ERR_INVALID_STATE, "Reinstatement requires current cycle paid")
        enr["status"] = "ACTIVE"
        touch(enr)
    return ok(serialize(enr), 200)


def _current_cycle(enr):
    """Cycle index of the current logical clock since activation (0-based, floor by 30 days)."""
    if enr.get("enrolled_at") is None:
        return 0
    days = (clock.now() - enr["enrolled_at"]).total_seconds() / 86400.0
    import math
    return max(0, int(math.floor(days / 30.0)))


@bp.route("/enrollments/<eid>/suspend", methods=["POST"])
def suspend_enrollment(eid):
    _, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    enr = get_or_404(db.enrollments, eid)
    if enr["status"] != "ACTIVE":
        errors.fail(errors.ERR_INVALID_STATE, "Can only suspend an ACTIVE enrollment")
    if enr["open_claim_id"] is not None:
        errors.fail(errors.ERR_INVALID_STATE, "Cannot suspend with an open claim")
    enr["status"] = "SUSPENDED"
    touch(enr)
    return ok(serialize(enr), 200)


@bp.route("/enrollments/<eid>/cancel", methods=["POST"])
def cancel_enrollment(eid):
    user_id, role = require_auth()
    require_role(role, {"Subscriber", "PlatformAdmin"})
    enr = get_or_404(db.enrollments, eid)
    _owner_check(role, user_id, enr)
    if enr["status"] not in ("ACTIVE", "SUSPENDED"):
        errors.fail(errors.ERR_INVALID_STATE, "Cannot cancel from current status")
    if enr["open_claim_id"] is not None:
        errors.fail(errors.ERR_INVALID_STATE, "Cannot cancel with an open claim")
    enr["status"] = "CANCELLED"
    # cascade: VOID all ISSUED invoices for this enrollment
    for inv in db.premium_invoices.values():
        if inv["enrollment_id"] == enr["id"] and inv["status"] == "ISSUED":
            inv["status"] = "VOID"
            touch(inv)
    touch(enr)
    return ok(serialize(enr), 200)


# ---------------- Premium Invoices ----------------
@bp.route("/premium-invoices", methods=["POST"])
def create_invoice():
    _, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    b = body()
    enrollment_id = require_str(b, "enrollment_id")
    cycle_index = require_int(b, "cycle_index")
    if cycle_index < 0:
        errors.fail(errors.ERR_VALIDATION, "cycle_index must be >= 0")
    enr = get_or_404(db.enrollments, enrollment_id)
    plan = db.plans[enr["plan_id"]]
    iid = new_id()
    inv = {
        "id": iid,
        "enrollment_id": enrollment_id,
        "cycle_index": cycle_index,
        "amount_cents": plan["monthly_premium_cents"],
        "status": "ISSUED",
        "_seq": db.next_seq(),
    }
    inv.update(base_system_fields(versioned=True))
    db.premium_invoices[iid] = inv
    return ok(serialize(inv), 201)


@bp.route("/premium-invoices", methods=["GET"])
def list_invoices():
    user_id, role = require_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    from flask import request
    limit, offset = parse_pagination()
    vals = list(db.premium_invoices.values())
    if role == "Subscriber":
        owned = {e["id"] for e in db.enrollments.values() if e["customer_id"] == user_id}
        vals = [i for i in vals if i["enrollment_id"] in owned]
    enr_f = request.args.get("enrollment_id")
    if enr_f is not None:
        vals = [i for i in vals if i["enrollment_id"] == enr_f]
    vals = sorted_by_created(vals)
    total = len(vals)
    page = paginate(vals, limit, offset)
    return ok_list([serialize(i) for i in page], limit, offset, total)


@bp.route("/premium-invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    user_id, role = require_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    inv = get_or_404(db.premium_invoices, iid)
    if role == "Subscriber":
        enr = db.enrollments.get(inv["enrollment_id"])
        if enr is None or enr["customer_id"] != user_id:
            errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of this invoice")
    return ok(serialize(inv), 200)


@bp.route("/premium-invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    user_id, role = require_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    inv = get_or_404(db.premium_invoices, iid)
    enr = db.enrollments.get(inv["enrollment_id"])
    if role == "Subscriber" and (enr is None or enr["customer_id"] != user_id):
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Not owner of this invoice")
    if inv["status"] != "ISSUED":
        errors.fail(errors.ERR_INVALID_STATE, "Only ISSUED invoices can be paid")
    b = body()
    expected = require_int(b, "expected_enrollment_version")
    if expected != enr["version"]:
        errors.fail(errors.ERR_STALE_ENROLLMENT_VERSION, "Stale enrollment version")
    inv["status"] = "PAID"
    touch(inv)
    # recompute premium_paid_through_cycle = highest PAID cycle index
    paid_cycles = [i["cycle_index"] for i in db.premium_invoices.values()
                   if i["enrollment_id"] == enr["id"] and i["status"] == "PAID"]
    enr["premium_paid_through_cycle"] = max(paid_cycles) if paid_cycles else -1
    touch(enr)
    return ok(serialize(inv), 200)

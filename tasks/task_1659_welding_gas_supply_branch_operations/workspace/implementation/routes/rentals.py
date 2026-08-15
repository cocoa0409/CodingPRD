"""Rental agreements: open, suspend/resume, close, goodwill waivers."""
from datetime import timedelta
from flask import Blueprint

import db
from db import store, new_common, new_id, touch, is_int, parse_date
from errors import ApiError
from middleware import require_roles, body
from response import ok, created, list_response, filter_param
from services import accrual, exposure

bp = Blueprint("rentals", __name__)

_ROLES = ("CounterRep", "BranchManager")
_MACHINE_PLANS = ("DAILY", "WEEKLY", "MONTHLY")


def get_agreement(rid):
    ag = store.rental_agreements.get(rid)
    if ag is None:
        raise ApiError("ERR_NOT_FOUND", 404, "RentalAgreement not found")
    return ag


@bp.route("/rental-agreements", methods=["POST"])
@require_roles(*_ROLES)
def create_agreement():
    b = body()
    # Priority 3: body-referenced ids must exist.
    cust_id = b.get("customer_id")
    cyl_id = b.get("cylinder_asset_id")
    mach_id = b.get("machine_id")
    if cust_id is not None and cust_id not in store.customers:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer not found")
    if cyl_id is not None and cyl_id not in store.cylinder_assets:
        raise ApiError("ERR_NOT_FOUND", 404, "CylinderAsset not found")
    if mach_id is not None and mach_id not in store.machines:
        raise ApiError("ERR_NOT_FOUND", 404, "Machine not found")
    # Priority 4: shape — polymorphic item/plan pairing.
    item_type = b.get("item_type")
    rate_plan = b.get("rate_plan")
    if not isinstance(cust_id, str) or not cust_id:
        raise ApiError("ERR_VALIDATION", 400, "customer_id is required")
    if item_type not in ("CYLINDER", "MACHINE"):
        raise ApiError("ERR_VALIDATION", 400, "item_type must be CYLINDER or MACHINE")
    if rate_plan not in ("DEMURRAGE",) + _MACHINE_PLANS:
        raise ApiError("ERR_VALIDATION", 400, "rate_plan is invalid")
    # ERR_RENTAL_ITEM_MISMATCH is the dedicated shape error for the polymorphic
    # item/plan combination.
    if item_type == "CYLINDER":
        if not cyl_id or mach_id is not None or rate_plan != "DEMURRAGE":
            raise ApiError("ERR_RENTAL_ITEM_MISMATCH", 400,
                           "CYLINDER rentals need cylinder_asset_id, no machine_id, "
                           "and rate_plan DEMURRAGE")
    else:
        if not mach_id or cyl_id is not None or rate_plan not in _MACHINE_PLANS:
            raise ApiError("ERR_RENTAL_ITEM_MISMATCH", 400,
                           "MACHINE rentals need machine_id, no cylinder_asset_id, "
                           "and rate_plan DAILY/WEEKLY/MONTHLY")
    try:
        start = parse_date(b.get("start_date"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "start_date must be a YYYY-MM-DD date")
    sched_end = b.get("scheduled_end_date")
    if sched_end is not None:
        try:
            parse_date(sched_end)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400,
                           "scheduled_end_date must be a YYYY-MM-DD date")
    grace = b.get("grace_days")
    if grace is None:
        grace = db.DEFAULT_CYLINDER_GRACE_DAYS if rate_plan == "DEMURRAGE" else 0
    if not is_int(grace) or grace < 0:
        raise ApiError("ERR_VALIDATION", 400, "grace_days must be an integer >= 0")
    # Priority 7: pressure-vessel safety — a RETIRED cylinder may not go on rent.
    if item_type == "CYLINDER":
        asset = store.cylinder_assets[cyl_id]
        if asset["status"] == "RETIRED":
            raise ApiError("ERR_CYLINDER_CONDEMNED", 409,
                           "A RETIRED cylinder may not be put on rent")
    # Priority 8: customer must be ACTIVE.
    cust = store.customers[cust_id]
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_ON_HOLD", 409,
                       "Customer is %s" % cust["status"])
    # Priority 9: machine turnaround buffer — start_date must be strictly later
    # than (greatest prior CLOSED rental's close date + 1 day) for this machine.
    if item_type == "MACHINE":
        closed_dates = [a["_closed_date"] for a in store.rental_agreements.values()
                        if a.get("machine_id") == mach_id and a["status"] == "CLOSED"]
        if closed_dates:
            earliest_ok = max(closed_dates) + timedelta(
                days=db.MACHINE_TURNAROUND_BUFFER_DAYS + 1)
            if start < earliest_ok:
                raise ApiError("ERR_RENTAL_OVERLAP", 409,
                               "start_date falls within the machine's turnaround buffer")
    # Priority 10: the asset must be free to rent.
    if item_type == "CYLINDER":
        asset = store.cylinder_assets[cyl_id]
        if asset["status"] != "FULL":
            raise ApiError("ERR_ASSET_NOT_AVAILABLE", 409,
                           "Cylinder is not FULL")
    else:
        machine = store.machines[mach_id]
        if machine["status"] != "AVAILABLE":
            raise ApiError("ERR_ASSET_NOT_AVAILABLE", 409,
                           "Machine is not AVAILABLE")
    ag = {
        "id": new_id(),
        "customer_id": cust_id,
        "item_type": item_type,
        "cylinder_asset_id": cyl_id,
        "machine_id": mach_id,
        "rate_plan": rate_plan,
        "start_date": b.get("start_date"),
        "scheduled_end_date": sched_end,
        "grace_days": grace,
        "status": "ACTIVE",
        "billed_through_date": None,
        "lifetime_billed_cents": 0,
        "waived_cents": 0,
        "closed_at": None,
        "_start": start,
        "_closed_date": None,
    }
    new_common(ag)
    store.rental_agreements[ag["id"]] = ag
    # Asset flip.
    if item_type == "CYLINDER":
        asset["status"] = "OUT"
        asset["holder_customer_id"] = cust_id
        asset["rental_agreement_id"] = ag["id"]
        touch(asset)
    else:
        machine["status"] = "RENTED"
        touch(machine)
    return created(accrual.agreement_view(ag))


@bp.route("/rental-agreements", methods=["GET"])
@require_roles(*_ROLES)
def list_agreements():
    rows = list(store.rental_agreements.values())
    rows = filter_param(rows, "customer_id")
    rows = filter_param(rows, "machine_id")
    rows = filter_param(rows, "cylinder_asset_id")
    rows = filter_param(rows, "status")
    return list_response([accrual.agreement_view(a) for a in rows])


@bp.route("/rental-agreements/<rid>", methods=["GET"])
@require_roles(*_ROLES)
def get_one_agreement(rid):
    return ok(accrual.agreement_view(get_agreement(rid)))


@bp.route("/rental-agreements/<rid>/suspend", methods=["POST"])
@require_roles(*_ROLES)
def suspend_agreement(rid):
    ag = get_agreement(rid)
    if ag["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE agreement can be suspended")
    ag["status"] = "SUSPENDED"
    touch(ag)
    return ok(accrual.agreement_view(ag))


@bp.route("/rental-agreements/<rid>/resume", methods=["POST"])
@require_roles(*_ROLES)
def resume_agreement(rid):
    ag = get_agreement(rid)
    if ag["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SUSPENDED agreement can be resumed")
    ag["status"] = "ACTIVE"
    touch(ag)
    return ok(accrual.agreement_view(ag))


@bp.route("/rental-agreements/<rid>/close", methods=["POST"])
@require_roles(*_ROLES)
def close_agreement(rid):
    ag = get_agreement(rid)
    if ag["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACTIVE or SUSPENDED agreement can be closed")
    now = db.clock_now()
    close_date = now.date()
    ag["closed_at"] = db.iso_logical(now)
    ag["_closed_date"] = close_date
    ag["billed_through_date"] = close_date.isoformat()
    # Final settle-up: provisional (ceil) value minus billed and waived.
    final = max(0, accrual.value_ceil(ag, close_date)
                - ag["lifetime_billed_cents"] - ag["waived_cents"])
    cust = store.customers[ag["customer_id"]]
    if final > 0:
        exposure.create_invoice(cust, "RENTAL_CLOSE", final, order_id=None)
        ag["lifetime_billed_cents"] += final
    # Asset release.
    if ag["item_type"] == "CYLINDER":
        asset = store.cylinder_assets.get(ag["cylinder_asset_id"])
        if asset is not None:
            asset["status"] = "EMPTY"
            asset["holder_customer_id"] = None
            asset["rental_agreement_id"] = None
            touch(asset)
    else:
        machine = store.machines.get(ag["machine_id"])
        if machine is not None:
            machine["status"] = "AVAILABLE"
            touch(machine)
    ag["status"] = "CLOSED"
    touch(ag)
    if final > 0:
        # Invoice creation recomputes exposure and may auto-place CREDIT_HOLD.
        exposure.on_invoice_created(cust)
    return ok(accrual.agreement_view(ag))


@bp.route("/rental-agreements/<rid>/waive", methods=["POST"])
@require_roles("BranchManager")
def waive_agreement(rid):
    ag = get_agreement(rid)
    b = body()
    # Priority 4: shape — all three inputs are non-optional.
    amount = b.get("waive_amount_cents")
    reason = b.get("reason")
    expected = b.get("expected_rental_agreement_version")
    if not is_int(amount) or amount <= 0:
        raise ApiError("ERR_VALIDATION", 400, "waive_amount_cents must be a positive integer")
    if not isinstance(reason, str) or not reason:
        raise ApiError("ERR_VALIDATION", 400, "reason is required")
    if not is_int(expected):
        raise ApiError("ERR_VALIDATION", 400,
                       "expected_rental_agreement_version is required")
    # Priority 5: optimistic concurrency on RentalAgreement.version.
    if expected != ag["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_rental_agreement_version does not match the agreement's "
                       "current version")
    # Priority 11: the waiver may not exceed the accrued amount (equality allowed).
    accrued = accrual.accrued_unbilled(ag)
    if amount > accrued:
        raise ApiError("ERR_WAIVER_EXCEEDS_ACCRUED", 409,
                       "waive_amount_cents exceeds accrued_unbilled_cents")
    ag["waived_cents"] += amount
    touch(ag)
    return ok(accrual.agreement_view(ag))

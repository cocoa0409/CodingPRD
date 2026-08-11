"""Carrier endpoints: registration lifecycle, payments, invoices."""

from flask import Blueprint, request

import calc
import errors
import serializers
from db import (
    add_years,
    months_late,
    stamp_new,
    store,
    sweep,
    touch,
)
from envelope import ok
from listing import page_out
from validators import (
    CATEGORIES,
    as_bool,
    as_enum_list,
    as_int,
    as_str,
    body,
    endpoint,
    get_or_404,
    opt,
    req,
)

bp = Blueprint("carriers", __name__)

ALL_ROLES = ["CarrierAdmin", "ShipperComplianceOfficer", "Regulator"]


def _carrier_or_404(cid):
    return get_or_404(store.carriers, cid, errors.ERR_CARRIER_NOT_FOUND, "Carrier")


@bp.route("/hazmat/carriers", methods=["POST"])
@endpoint(["CarrierAdmin"])
def create_carrier(uid, role):
    b = body()
    legal_name = as_str(req(b, "legal_name"), "legal_name")
    usdot = as_str(req(b, "usdot_number"), "usdot_number")
    fleet = as_int(req(b, "fleet_size_declared"), "fleet_size_declared")
    if fleet < 0:
        raise errors.invalid("fleet_size_declared must be >= 0")
    cats = as_enum_list(req(b, "hazmat_categories"), "hazmat_categories", CATEGORIES)
    accepts = as_bool(opt(b, "accepts_dangerous_placard_substitution", False),
                      "accepts_dangerous_placard_substitution")
    for c in store.carriers.values():
        if c["usdot_number"] == usdot:
            raise errors.conflict(errors.ERR_DUPLICATE_USDOT,
                                  "usdot_number already registered")
    carrier = {
        "legal_name": legal_name,
        "usdot_number": usdot,
        "fleet_size_declared": fleet,
        "verified_fleet_size": None,
        "hazmat_categories": cats,
        "accepts_dangerous_placard_substitution": accepts,
        "registration_status": "DRAFT",
        "registration_tier": None,
        "registration_expires_at": None,
        "credit_balance_cents": 0,
        "safety_rating": 100,
    }
    stamp_new(carrier)
    store.carriers[carrier["id"]] = carrier
    return ok(serializers.carrier(carrier), 201)


@bp.route("/hazmat/carriers", methods=["GET"])
@endpoint(ALL_ROLES)
def list_carriers(uid, role):
    rows = list(store.carriers.values())
    status = request.args.get("registration_status")
    if status is not None:
        rows = [c for c in rows if c["registration_status"] == status]
    return page_out(rows, serializers.carrier)


@bp.route("/hazmat/carriers/<carrierId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_carrier(uid, role, carrierId):
    return ok(serializers.carrier(_carrier_or_404(carrierId)), 200)


@bp.route("/hazmat/carriers/<carrierId>/registration/submit", methods=["POST"])
@endpoint(["CarrierAdmin"])
def submit_registration(uid, role, carrierId):
    carrier = _carrier_or_404(carrierId)
    b = body()
    expected = as_int(req(b, "expected_carrier_version"), "expected_carrier_version")
    # OCC (priority 6) precedes the from-state gate (priority 8) per §2.8.
    if expected != carrier["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_carrier_version does not match the current version")
    status = carrier["registration_status"]
    submittable = status in ("DRAFT", "EXPIRED")
    if status == "APPROVED_ACTIVE":
        exp = carrier["registration_expires_at"]
        window_start = exp - calc.EARLY_RENEWAL_DAYS
        submittable = window_start <= store.clock <= exp
    if not submittable:
        raise errors.conflict(
            errors.ERR_CARRIER_NOT_SUBMITTABLE,
            "Registration submit requires DRAFT, EXPIRED, or APPROVED_ACTIVE "
            "inside the early-renewal window",
        )
    kind = "INITIAL" if status == "DRAFT" else "RENEWAL"
    spr = calc.carrier_security_plan_required(carrier)
    late = months_late(carrier["registration_expires_at"], store.clock) if kind == "RENEWAL" else 0
    tier, total = calc.registration_fee(
        carrier["fleet_size_declared"], spr, kind, late,
        carrier["safety_rating"], "provisional",
    )
    carrier["registration_tier"] = tier
    carrier["registration_status"] = "SUBMITTED"
    touch(carrier)
    invoice = {
        "carrier_id": carrier["id"],
        "kind": kind,
        "assessment_year": store.clock.year,
        "provisional_total_cents": total,
        "final_total_cents": None,
        "total_due_cents": total,
        "paid_cents": 0,
        "status": "OPEN",
    }
    stamp_new(invoice)
    store.invoices[invoice["id"]] = invoice
    return ok(serializers.invoice(invoice), 201)


@bp.route("/hazmat/carriers/<carrierId>/registration/approve", methods=["POST"])
@endpoint(["Regulator"])
def approve_registration(uid, role, carrierId):
    carrier = _carrier_or_404(carrierId)
    b = body()
    verified = as_int(req(b, "verified_fleet_size"), "verified_fleet_size")
    if verified < 0:
        raise errors.invalid("verified_fleet_size must be >= 0")
    if carrier["registration_status"] != "SUBMITTED":
        raise errors.conflict(errors.ERR_CARRIER_NOT_SUBMITTED,
                              "Registration approve requires SUBMITTED")
    carrier["verified_fleet_size"] = verified
    spr = calc.carrier_security_plan_required(carrier)
    open_invoices = [
        inv for inv in store.invoices.values()
        if inv["carrier_id"] == carrier["id"]
        and inv["status"] == "OPEN"
        and inv["kind"] in ("INITIAL", "RENEWAL")
    ]
    open_invoices.sort(key=lambda i: (i["created_at"], i["_seq"]))
    inv = open_invoices[-1] if open_invoices else None
    kind = inv["kind"] if inv else "INITIAL"
    late = (
        months_late(carrier["registration_expires_at"], store.clock)
        if kind == "RENEWAL" else 0
    )
    tier, total = calc.registration_fee(
        verified, spr, kind, late, carrier["safety_rating"], "final"
    )
    carrier["registration_tier"] = tier
    if inv is not None:
        inv["final_total_cents"] = total
        inv["total_due_cents"] = total
        touch(inv)
    carrier["registration_expires_at"] = add_years(store.clock, 1)
    carrier["registration_status"] = "APPROVED_ACTIVE"
    touch(carrier)
    return ok(serializers.carrier(carrier), 200)


@bp.route("/hazmat/carriers/<carrierId>/suspend", methods=["POST"])
@endpoint(["Regulator"])
def suspend_carrier(uid, role, carrierId):
    carrier = _carrier_or_404(carrierId)
    if carrier["registration_status"] != "APPROVED_ACTIVE":
        raise errors.conflict(errors.ERR_CARRIER_NOT_ACTIVE,
                              "Suspend requires APPROVED_ACTIVE")
    carrier["registration_status"] = "SUSPENDED"
    touch(carrier)
    # Link 1: drivers ACTIVE -> SUSPENDED (plans are NOT state-changed).
    for d in store.drivers.values():
        if d["carrier_id"] == carrier["id"] and d["status"] == "ACTIVE":
            d["status"] = "SUSPENDED"
            touch(d)
    # Link 2: TENDERED shipments -> DOCUMENTED, pin cleared, driver kept.
    reverted = [
        s for s in store.shipments.values()
        if s["carrier_id"] == carrier["id"] and s["status"] == "TENDERED"
    ]
    for s in reverted:
        s["status"] = "DOCUMENTED"
        s["pinned_security_plan_id"] = None
        s["pinned_security_plan_version"] = None
        touch(s)
    # Link 3: pull reverted shipments' items off STAGING/SEALED loads.
    reverted_ids = {s["id"] for s in reverted}
    affected_loads = {}
    for item in list(store.load_items.values()):
        if item["shipment_id"] not in reverted_ids:
            continue
        load = store.loads.get(item["load_id"])
        if load is None or load["status"] not in ("STAGING", "SEALED"):
            continue
        del store.load_items[item["id"]]
        affected_loads[load["id"]] = load
    for load in affected_loads.values():
        load["total_table2_weight_kg"] = calc.total_table2_weight(load["id"])
        if load["status"] == "SEALED":
            load["status"] = "STAGING"
            load["required_placards"] = []
            load["handling_fee_cents"] = 0
        touch(load)
    return ok(serializers.carrier(carrier), 200)


@bp.route("/hazmat/carriers/<carrierId>/reinstate", methods=["POST"])
@endpoint(["Regulator"])
def reinstate_carrier(uid, role, carrierId):
    carrier = _carrier_or_404(carrierId)
    if carrier["registration_status"] != "SUSPENDED":
        raise errors.conflict(errors.ERR_CARRIER_NOT_SUSPENDED,
                              "Reinstate requires SUSPENDED")
    invoice = {
        "carrier_id": carrier["id"],
        "kind": "REINSTATEMENT",
        "assessment_year": store.clock.year,
        "provisional_total_cents": None,
        "final_total_cents": calc.REINSTATEMENT_FLAT,
        "total_due_cents": calc.REINSTATEMENT_FLAT,
        "paid_cents": 0,
        "status": "OPEN",
    }
    stamp_new(invoice)
    store.invoices[invoice["id"]] = invoice
    for d in store.drivers.values():
        if d["carrier_id"] == carrier["id"] and d["status"] == "SUSPENDED":
            d["status"] = "ACTIVE"
            touch(d)
    carrier["registration_status"] = "APPROVED_ACTIVE"
    touch(carrier)
    return ok(serializers.carrier(carrier), 200)


@bp.route("/hazmat/carriers/<carrierId>/payments", methods=["POST"])
@endpoint(["CarrierAdmin"])
def make_payment(uid, role, carrierId):
    carrier = _carrier_or_404(carrierId)
    b = body()
    amount = as_int(req(b, "amount_cents"), "amount_cents")
    if amount <= 0:
        raise errors.invalid("amount_cents must be > 0")
    calc.payment_waterfall(carrier, amount)
    return ok(serializers.carrier(carrier), 200)


@bp.route("/hazmat/carriers/<carrierId>/registration-invoices", methods=["GET"])
@endpoint(ALL_ROLES)
def list_carrier_invoices(uid, role, carrierId):
    carrier = _carrier_or_404(carrierId)
    rows = [i for i in store.invoices.values() if i["carrier_id"] == carrier["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    return page_out(rows, serializers.invoice)

"""Agreement routes: draft, fetch, list, activate, default, expire."""

from flask import Blueprint, request

import db
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from routes.helpers import lookup, paginate
from services import domain
from services import calc
import validation as V

bp = Blueprint("agreements", __name__)


# ---------------------------------------------------------------------------
# Draft
# ---------------------------------------------------------------------------
@bp.post("/agreements")
def create_agreement():
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    body = V.get_body()

    property_id = V.require_str(body, "property_id")
    tenant_id = V.require_str(body, "tenant_id")
    locked_price_cents = V.require_int(body, "locked_price_cents", gt=0)
    option_fee_cents = V.require_int(body, "option_fee_cents", minimum=0)
    option_fee_creditable = V.optional_bool(body, "option_fee_creditable", True)
    monthly_payment_cents = V.require_int(body, "monthly_payment_cents", gt=0)
    credit_pct = V.require_number(body, "credit_pct", lo=0, hi=1)
    max_credit_pct = V.optional_number(body, "max_credit_pct", 0.20, gt=0, hi=1)
    grace_days = V.optional_int(body, "grace_days", 5, minimum=0)
    maintenance_threshold_cents = V.optional_int(
        body, "maintenance_threshold_cents", 50000, minimum=0)
    lease_start = V.parse_dt(V.require(body, "lease_start"), "lease_start")
    option_term_months = V.require_int(body, "option_term_months", minimum=1)

    # Existence (priority 3): property and tenant must exist (left-to-right).
    prop = lookup(db.properties, property_id)
    lookup(db.tenants, tenant_id)

    # Referential consistency (priority 5): property's landlord must match the
    # acting landlord (issuing landlord must own the property).
    if prop["landlord_id"] != user_id:
        raise err("ERR_REFERENCE_MISMATCH",
                  "Property landlord does not match the acting landlord")

    landlord_id = prop["landlord_id"]
    option_deadline = domain.add_months(lease_start, option_term_months)

    rec = {
        "id": db.new_id(),
        "property_id": property_id,
        "tenant_id": tenant_id,
        "landlord_id": landlord_id,
        "locked_price_cents": locked_price_cents,
        "option_fee_cents": option_fee_cents,
        "option_fee_creditable": option_fee_creditable,
        "monthly_payment_cents": monthly_payment_cents,
        "credit_pct": credit_pct,
        "max_credit_pct": max_credit_pct,
        "grace_days": grace_days,
        "maintenance_threshold_cents": maintenance_threshold_cents,
        "lease_start": db.iso_millis(lease_start),
        "option_term_months": option_term_months,
        "status": "DRAFT",
        "missed_payment_count": 0,
        "gross_credit_accrued_cents": 0,
        "available_credit_cents": 0,
        "option_deadline": db.iso_millis(option_deadline),
    }
    domain._stamp_new(rec)
    db.agreements[rec["id"]] = rec
    return object_response(domain.serialize_agreement(rec), 201)


# ---------------------------------------------------------------------------
# Fetch / list
# ---------------------------------------------------------------------------
@bp.get("/agreements/<rid>")
def get_agreement(rid):
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    rec = lookup(db.agreements, rid)
    return object_response(domain.serialize_agreement(rec), 200)


@bp.get("/agreements")
def list_agreements():
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    items = list(db.agreements.values())
    for field in ("property_id", "tenant_id", "landlord_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a.get(field) == val]
    page, limit, offset, total = paginate(items)
    return array_response([domain.serialize_agreement(a) for a in page],
                          limit, offset, total)


# ---------------------------------------------------------------------------
# Activate (OCC on Property.version)
# ---------------------------------------------------------------------------
@bp.post("/agreements/<rid>/activate")
def activate_agreement(rid):
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    agreement = lookup(db.agreements, rid)
    # Ownership: landlord must own the agreement.
    if agreement["landlord_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Landlord does not own this agreement")

    body = V.get_body()
    expected_version = V.require_int(body, "expected_property_version")

    prop = lookup(db.properties, agreement["property_id"])

    # OCC (priority 6) — evaluated BEFORE state and property-availability.
    if expected_version != prop["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_property_version does not match current property version")

    # State (priority 7): agreement must be DRAFT.
    if agreement["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Agreement is not in DRAFT state")

    # Property availability (priority 8) — after OCC.
    if prop["status"] != "AVAILABLE":
        raise err("ERR_PROPERTY_NOT_AVAILABLE", "Property is not AVAILABLE")

    # Transition + cascade.
    agreement["status"] = "ACTIVE"
    # option_deadline already computed at draft; settle/reaffirm it.
    domain.touch(agreement)

    prop["status"] = "UNDER_AGREEMENT"
    domain.touch(prop)

    return object_response(domain.serialize_agreement(agreement), 200)


# ---------------------------------------------------------------------------
# Default
# ---------------------------------------------------------------------------
@bp.post("/agreements/<rid>/default")
def default_agreement(rid):
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    agreement = lookup(db.agreements, rid)
    if agreement["landlord_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Landlord does not own this agreement")

    # State (priority 7): must be ACTIVE.
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement is not ACTIVE")

    # Safety gate (priority 12): missed_payment_count >= MAX_MISSED_PAYMENTS.
    domain.recompute_accruals(agreement)
    if agreement["missed_payment_count"] < calc.MAX_MISSED_PAYMENTS:
        raise err("ERR_DEFAULT_THRESHOLD_NOT_MET",
                  "Missed payment count below default threshold")

    _collapse(agreement, terminal_status="DEFAULTED", void_pending_exercise=True,
              forfeit_all_credit=True)
    return object_response(domain.serialize_agreement(agreement), 200)


# ---------------------------------------------------------------------------
# Expire
# ---------------------------------------------------------------------------
@bp.post("/agreements/<rid>/expire")
def expire_agreement(rid):
    user_id, role = get_auth()
    require_role(role, {"Landlord"})
    agreement = lookup(db.agreements, rid)
    if agreement["landlord_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Landlord does not own this agreement")

    # State (priority 7): must be ACTIVE.
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement is not ACTIVE")

    # Temporal gate (priority 10): current clock strictly past option_deadline.
    deadline = V.parse_dt(agreement["option_deadline"], "option_deadline")
    if not (db.current_clock() > deadline):
        raise err("ERR_OPTION_NOT_YET_EXPIRED",
                  "Current clock is not past the option deadline")

    _collapse(agreement, terminal_status="EXPIRED", void_pending_exercise=False,
              forfeit_all_credit=False)
    return object_response(domain.serialize_agreement(agreement), 200)


# ---------------------------------------------------------------------------
# Shared collapse cascade for default / expire
# ---------------------------------------------------------------------------
def _collapse(agreement, terminal_status, void_pending_exercise, forfeit_all_credit):
    # Force every non-terminal payment row (PENDING/LATE) to FORFEITED.
    for p in domain.agreement_payments(agreement["id"]):
        if p["status"] in ("PENDING", "LATE"):
            p["status"] = "FORFEITED"
            domain.touch(p)

    if forfeit_all_credit:
        # All earned credit evaporates on default.
        agreement["_credit_forfeited"] = True

    # Void any PENDING option exercise (default branch only per spec).
    if void_pending_exercise:
        for ex in db.option_exercises.values():
            if ex["agreement_id"] == agreement["id"] and ex["status"] == "PENDING":
                ex["status"] = "VOIDED"
                domain.touch(ex)

    agreement["status"] = terminal_status
    domain.recompute_accruals(agreement)
    domain.touch(agreement)

    # Cascade property UNDER_AGREEMENT -> AVAILABLE.
    prop = db.properties.get(agreement["property_id"])
    if prop is not None and prop["status"] == "UNDER_AGREEMENT":
        prop["status"] = "AVAILABLE"
        domain.touch(prop)

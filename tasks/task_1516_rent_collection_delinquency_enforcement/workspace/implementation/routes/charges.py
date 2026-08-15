"""Ledger charge endpoints (PRD 3.2, 3.5): manual creation (RENT/DAMAGE_FEE
only), listing under the lease, and the waiver action with its state,
segregation-of-duties, and fiscal guards."""

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import validators as V
from services import calc, workflows
from routes.leases import get_lease_or_404

bp = Blueprint("charges", __name__)

ALL_KINDS = {"RENT", "LATE_FEE", "NSF_FEE", "PLAN_SETUP_FEE", "DAMAGE_FEE"}
MANUAL_KINDS = {"RENT", "DAMAGE_FEE"}


def get_charge_or_404(charge_id):
    charge = db.charges.get(charge_id)
    if charge is None:
        errors.fail(errors.ERR_NOT_FOUND, "Charge %s does not exist." % charge_id)
    return charge


@bp.post("/leases/<lease_id>/charges")
def create_charge(lease_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, {"LeasingAgent", "PropertyManager"})
    lease = get_lease_or_404(lease_id)
    data = V.json_body()
    V.check_unknown(
        data, {"kind", "period_start_date", "period_end_date", "due_date", "amount_cents"}
    )
    # Tier 6: never permitted once the lease has ended.
    if lease["status"] == "ENDED":
        errors.fail(
            errors.ERR_LEASE_ALREADY_ENDED,
            "Charges cannot be created on an ENDED lease.",
        )
    kind = V.req_enum(data, "kind", ALL_KINDS)
    # Tier 13: manual creation is restricted to RENT and DAMAGE_FEE.
    if kind not in MANUAL_KINDS:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "Manual charge creation is restricted to kinds RENT and DAMAGE_FEE.",
        )
    period_start = V.req_date(data, "period_start_date")
    period_end = V.req_date(data, "period_end_date")
    due_date = V.req_date(data, "due_date")
    amount_cents = V.req_int(data, "amount_cents")
    # Tier 10: date coherence.
    if period_end < period_start:
        errors.fail(
            errors.ERR_INVALID_REQUEST,
            "period_end_date must be on or after period_start_date.",
        )
    charge = workflows.new_charge(
        lease, kind, "MANUAL",
        period_start.isoformat(), period_end.isoformat(), due_date.isoformat(),
        amount_cents, uid,
    )
    return response.success_object(serializers.charge_view(charge), 201)


@bp.get("/leases/<lease_id>/charges")
def list_charges(lease_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    lease = get_lease_or_404(lease_id)
    if role == "Tenant":
        middleware.require_owns_lease(uid, lease)
    rows = [c for c in db.charges.values() if c["lease_id"] == lease["id"]]
    page, limit, offset, total = V.sorted_page(rows, [
        ("status", V.query_filter("status")),
        ("kind", V.query_filter("kind")),
    ])
    return response.success_list(
        [serializers.charge_view(c) for c in page], limit, offset, total
    )


@bp.post("/charges/<charge_id>/waive")
def waive_charge(charge_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.PM)
    charge = get_charge_or_404(charge_id)
    data = V.json_body()
    V.check_unknown(data, {"amount_cents", "reason"})
    amount = V.req_int(data, "amount_cents")
    V.req_str(data, "reason")
    # Tier 7: the target must be OPEN or PARTIALLY_PAID.
    if charge["status"] not in workflows.OPEN_CHARGE_STATES:
        errors.fail(
            errors.ERR_CHARGE_NOT_WAIVABLE,
            "A charge in status %s accepts no waiver." % charge["status"],
        )
    # Tier 8: segregation of duties — no self-forgiveness. System-created
    # charges (creator 'system') may be waived by any property manager.
    if uid == charge["created_by_user_id"]:
        errors.fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The waiver caller must differ from the charge's creator.",
        )
    lease = db.leases[charge["lease_id"]]
    prop = calc.property_of(lease)
    # Tier 16, in order: outstanding bound, then the property monthly cap.
    if amount > charge["outstanding_cents"]:
        errors.fail(
            errors.ERR_WAIVER_EXCEEDS_OUTSTANDING,
            "Waiver amount %d exceeds outstanding %d." % (amount, charge["outstanding_cents"]),
        )
    month = calc.month_key(db.clock_date())
    month_total = calc.property_month_waived_cents(prop["id"], month)
    if month_total + amount > prop["monthly_waiver_cap_cents"]:
        errors.fail(
            errors.ERR_WAIVER_CAP_EXCEEDED,
            "Waiver would push the property's calendar-month waived total above the cap.",
        )
    charge["waived_cents"] += amount
    charge["outstanding_cents"] -= amount
    if charge["outstanding_cents"] == 0:
        # A full waiver moves the charge to WAIVED from OPEN or PARTIALLY_PAID.
        charge["status"] = "WAIVED"
    db.touch(charge)
    db.waiver_events.append({
        "property_id": prop["id"],
        "month": month,
        "amount_cents": amount,
    })
    workflows.cascade_charge_changed(charge)
    return response.success_object(serializers.charge_view(charge))

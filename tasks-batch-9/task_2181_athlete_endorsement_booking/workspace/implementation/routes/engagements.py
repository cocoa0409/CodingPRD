"""Engagement reads, countersignature and the termination unwind."""

from flask import Blueprint, request

import calc
import domain
import validation as V
from auth import ALL_ROLES, require
from envelope import ok, paginated, read_pagination
from errors import ApiError
from store import db, stamp, touch

bp = Blueprint("engagements", __name__)


@bp.get("/engagements/<engagement_id>")
def get_engagement(engagement_id):
    require(ALL_ROLES)
    return ok(domain.must_get("engagements", engagement_id))


@bp.get("/engagements")
def list_engagements():
    require(ALL_ROLES)
    limit, offset = read_pagination()
    rows = list(db.engagements.values())
    for field in ("athlete_id", "brand_id", "term_sheet_id", "opportunity_id",
                  "contract_status", "settlement_status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paginated(rows, limit, offset)


@bp.post("/engagements/<engagement_id>/countersign")
def countersign(engagement_id):
    caller = require("FinanceManager")
    engagement = domain.must_get("engagements", engagement_id)
    payload = V.body()
    V.str_field(payload, "signed_by_reference")

    if engagement["contract_status"] != "PENDING_COUNTERSIGN":
        raise ApiError("ERR_ENGAGEMENT_ALREADY_TERMINAL",
                       "engagement has already left PENDING_COUNTERSIGN")

    brand = db.brands.get(engagement["brand_id"])
    if brand is not None and brand.get("sanctioned"):
        raise ApiError("ERR_BRAND_SANCTIONED", "the brand is sanctioned")

    athlete = db.athletes[engagement["athlete_id"]]
    qualifying = [b for b in domain.engagement_bookings(engagement["id"])
                  if b["status"] in ("CONFIRMED", "COMPLETED")]
    travel_component = calc.binding_travel_component(
        qualifying, athlete["base_appearance_rate_cents"])

    engagement["binding_fee_cents"] = calc.fee_engine(
        engagement["base_fee_cents"], engagement["usage_rights_tier"],
        engagement["morals_clause_tier"], engagement["territory"],
        athlete["base_appearance_rate_cents"], engagement["exclusivity_months"],
        travel_component,
    )
    engagement["contract_status"] = "ACTIVE"
    engagement["countersigned_by_user_id"] = caller.user_id
    engagement["countersigned_at"] = stamp()
    touch(engagement)

    for grant in domain.engagement_grants(engagement["id"]):
        if grant["status"] == "PENDING":
            grant["status"] = "ACTIVE"
            touch(grant)

    domain.sync_athlete_after_contract_change(engagement)
    return ok(engagement)


@bp.post("/engagements/<engagement_id>/terminate")
def terminate(engagement_id):
    require("ComplianceOfficer")
    engagement = domain.must_get("engagements", engagement_id)
    payload = V.body()
    reason_code = V.str_field(payload, "reason_code")

    if engagement["contract_status"] not in ("PENDING_COUNTERSIGN", "ACTIVE"):
        raise ApiError("ERR_ENGAGEMENT_ALREADY_TERMINAL",
                       "engagement is already COMPLETED or TERMINATED")

    engagement["contract_status"] = "TERMINATED"
    engagement["terminated_reason_code"] = reason_code

    # 1. exclusivity released
    released_stamp = stamp()
    for grant in domain.engagement_grants(engagement["id"]):
        if grant["status"] in ("PENDING", "ACTIVE"):
            grant["status"] = "RELEASED"
            grant["released_at"] = released_stamp
            touch(grant)

    # 2. calendar released
    for booking in domain.engagement_bookings(engagement["id"]):
        if booking["status"] not in ("HOLD", "CONFIRMED"):
            continue
        was_confirmed = booking["status"] == "CONFIRMED"
        booking["status"] = "CANCELLED"
        booking["cancel_reason_code"] = "AUTO_TERMINATION"
        touch(booking)
        if was_confirmed:
            domain.append_ledger(
                engagement, "REVERSAL", -booking["travel_cost_cents"],
                "Travel accrual reversed by engagement termination",
                "AppearanceBooking", booking["id"],
            )

    # 3. outstanding work voided
    for deliverable in domain.engagement_deliverables(engagement["id"]):
        domain.void_deliverable(deliverable)

    # 4. settlement opened
    domain.open_settlement(engagement)

    domain.refresh_approved_deliverable_count(engagement)
    domain.refresh_accrued(engagement)
    touch(engagement)
    domain.sync_athlete_after_contract_change(engagement)
    return ok(engagement)


@bp.get("/engagements/<engagement_id>/ledger-entries")
def list_ledger(engagement_id):
    require(ALL_ROLES)
    engagement = domain.must_get("engagements", engagement_id)
    limit, offset = read_pagination()
    rows = domain.engagement_ledger(engagement["id"])
    entry_type = request.args.get("entry_type")
    if entry_type:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    return paginated(rows, limit, offset)


@bp.get("/engagements/<engagement_id>/exclusivity-grants")
def list_engagement_grants(engagement_id):
    require(ALL_ROLES)
    engagement = domain.must_get("engagements", engagement_id)
    limit, offset = read_pagination()
    rows = domain.engagement_grants(engagement["id"])
    status = request.args.get("status")
    if status:
        rows = [g for g in rows if g["status"] == status]
    return paginated(rows, limit, offset)


@bp.get("/engagements/<engagement_id>/payout-statements")
def list_engagement_statements(engagement_id):
    require("TalentAgent", "ComplianceOfficer", "FinanceManager", "Athlete")
    engagement = domain.must_get("engagements", engagement_id)
    limit, offset = read_pagination()
    rows = domain.engagement_statements(engagement["id"])
    status = request.args.get("status")
    if status:
        rows = [p for p in rows if p["status"] == status]
    return paginated(rows, limit, offset)


@bp.get("/engagements/<engagement_id>/renewal-options")
def list_engagement_options(engagement_id):
    require("TalentAgent", "BrandRep", "ComplianceOfficer", "FinanceManager")
    engagement = domain.must_get("engagements", engagement_id)
    limit, offset = read_pagination()
    rows = domain.engagement_options(engagement["id"])
    status = request.args.get("status")
    if status:
        rows = [o for o in rows if o["status"] == status]
    return paginated(rows, limit, offset)

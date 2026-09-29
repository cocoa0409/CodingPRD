"""Severance offers: pricing, issuance, the release cycle and both ledgers."""
from datetime import timedelta

from flask import Blueprint, g

from calc import (OWBPA_PROTECTED_AGE, REVOCATION_DAYS, consideration_days_for,
                  outplacement_tier_for_months, price_offer)
from core import (ApiError, base_record, db, iso_ms, num, ok, ok_list,
                  parse_instant, touch)
from domain import (current_disclosure, latest_analysis, offer_window_conflict,
                    recompute_plan)
from serialize import offer_out
from validation import (READER_ROLES, body, endpoint, must_exist, paginate,
                        pagination, query_enum, query_str, req_enum, req_int,
                        req_str)

bp = Blueprint("offers", __name__)

VARIANTS = ("STANDARD", "ENHANCED_RELEASE")
OFFER_STATUSES = ("DRAFT", "ISSUED", "SIGNED", "REVOKED", "EFFECTIVE", "EXPIRED")


def _offer_context(offer):
    selection = db.selections.get(offer["selection_id"])
    employee = db.employees.get(selection["employee_id"]) if selection else None
    plan = db.plans.get(offer["plan_id"])
    return selection, employee, plan


@bp.route("/severance-offers", methods=["POST"])
@endpoint(["BenefitsAdministrator"])
def create_offer():
    payload = body()
    selection_id = req_str(payload, "selection_id")
    variant = req_enum(payload, "variant", VARIANTS)
    expected_selection_version = req_int(payload, "expected_selection_version")

    selection = db.selections.get(selection_id)
    if selection is None:
        raise ApiError("ERR_SELECTION_NOT_FOUND", 404)

    if selection["status"] != "SELECTED":
        raise ApiError("ERR_INVALID_SELECTION_STATE", 409)
    if expected_selection_version != selection["version"]:
        raise ApiError("ERR_STALE_SELECTION_VERSION", 412)

    plan = db.plans[selection["plan_id"]]
    employee = db.employees[selection["employee_id"]]
    site = db.sites.get(employee["site_id"])

    analysis = latest_analysis(plan["id"])
    if analysis is None or analysis["status"] != "CLEARED":
        raise ApiError("ERR_IMPACT_ANALYSIS_NOT_CLEARED", 422)

    pinned_disclosure_id = None
    age = employee["age_at_separation"]
    if age is not None and age >= OWBPA_PROTECTED_AGE:
        disclosure = current_disclosure(plan["id"])
        if disclosure is None:
            raise ApiError("ERR_OWBPA_DISCLOSURE_MISSING", 422)
        if (disclosure["status"] != "ATTACHED"
                or disclosure["snapshot_selected_count"] != plan["selected_count"]
                or disclosure["snapshot_pool_count"] != plan["pool_count"]):
            raise ApiError("ERR_OWBPA_DISCLOSURE_STALE", 422)
        pinned_disclosure_id = disclosure["id"]

    if selection["notice_status"] != "DELIVERED":
        raise ApiError("ERR_NOTICE_NOT_DELIVERED", 422)

    if offer_window_conflict(employee["id"]):
        raise ApiError("ERR_OFFER_WINDOW_CONFLICT", 409)

    priced = price_offer(
        employee,
        variant,
        site["required_notice_days"] if site is not None else 0,
        selection["notice_days_before_separation"],
    )

    record = base_record()
    record.update({
        "selection_id": selection["id"],
        "plan_id": plan["id"],
        "owbpa_disclosure_id": pinned_disclosure_id,
        "variant": variant,
        "weekly_rate_cents": priced["weekly_rate_cents"],
        "weeks_awarded": num(priced["weeks_awarded"]),
        "base_severance_cents": priced["base_severance_cents"],
        "notice_shortfall_days": priced["notice_shortfall_days"],
        "notice_pay_offset_cents": priced["notice_pay_offset_cents"],
        "benefit_subsidy_months": priced["benefit_subsidy_months"],
        "benefit_subsidy_cents": priced["benefit_subsidy_cents"],
        "outplacement_fee_cents": priced["outplacement_fee_cents"],
        "total_separation_cost_cents": priced["total_separation_cost_cents"],
        "consideration_days_applied": 0,
        "status": "DRAFT",
        "issue_count": 0,
        "issued_utc": None,
        "signed_utc": None,
        "revoked_utc": None,
        "consideration_deadline_utc": None,
        "revocation_deadline_utc": None,
        "_outplacement_tier": priced["outplacement_tier"],
    })
    db.offers[record["id"]] = record
    touch(selection)
    return ok(offer_out(record), 201)


@bp.route("/severance-offers/<offer_id>", methods=["GET"])
@endpoint(READER_ROLES + ["SeparatingEmployee"])
def get_offer(offer_id):
    return ok(offer_out(must_exist("offers", offer_id)))


@bp.route("/severance-offers", methods=["GET"])
@endpoint(READER_ROLES)
def list_offers():
    limit, offset = pagination()
    selection_id = query_str("selection_id")
    plan_id = query_str("plan_id")
    disclosure_id = query_str("owbpa_disclosure_id")
    status = query_enum("status", OFFER_STATUSES)

    rows = sorted(db.offers.values(), key=lambda r: r["_seq"])
    if selection_id is not None:
        rows = [r for r in rows if r["selection_id"] == selection_id]
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if disclosure_id is not None:
        rows = [r for r in rows if r["owbpa_disclosure_id"] == disclosure_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, total = paginate(rows, limit, offset)
    return ok_list([offer_out(r) for r in page], limit, offset, total)


@bp.route("/severance-offers/<offer_id>/issue", methods=["POST"])
@endpoint(["BenefitsAdministrator"])
def issue_offer(offer_id):
    offer = must_exist("offers", offer_id)
    selection, employee, plan = _offer_context(offer)

    if offer["status"] not in ("DRAFT", "REVOKED"):
        raise ApiError("ERR_INVALID_OFFER_STATE", 409)
    if selection is None or selection["status"] != "SELECTED":
        raise ApiError("ERR_INVALID_SELECTION_STATE", 409)
    if offer_window_conflict(employee["id"]):
        raise ApiError("ERR_OFFER_WINDOW_CONFLICT", 409)
    if offer["issue_count"] >= 3:
        raise ApiError("ERR_OFFER_REISSUE_LIMIT", 422)
    if plan["severance_reserve_cents"] + offer["total_separation_cost_cents"] > \
            plan["severance_budget_cents"]:
        raise ApiError("ERR_SEVERANCE_BUDGET_EXCEEDED", 422)

    days = consideration_days_for(employee["age_at_separation"], plan["selected_count"])
    issued_at = db.clock
    offer["status"] = "ISSUED"
    offer["issued_utc"] = iso_ms(issued_at)
    offer["consideration_days_applied"] = days
    offer["consideration_deadline_utc"] = iso_ms(issued_at + timedelta(days=days))
    offer["signed_utc"] = None
    offer["revoked_utc"] = None
    offer["revocation_deadline_utc"] = None
    offer["issue_count"] += 1
    touch(offer)

    recompute_plan(plan)
    return ok(offer_out(offer))


@bp.route("/severance-offers/<offer_id>/sign", methods=["POST"])
@endpoint(["SeparatingEmployee"])
def sign_offer(offer_id):
    offer = must_exist("offers", offer_id)
    selection, employee, plan = _offer_context(offer)

    if selection is None or g.user_id != selection["employee_id"]:
        raise ApiError("ERR_NOT_OFFER_RECIPIENT", 403)
    if offer["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_OFFER_STATE", 409)

    deadline = parse_instant(offer["consideration_deadline_utc"])
    if deadline is not None and db.clock > deadline:
        offer["status"] = "EXPIRED"
        touch(offer)
        recompute_plan(plan)
        raise ApiError("ERR_CONSIDERATION_PERIOD_EXPIRED", 422)

    signed_at = db.clock
    age = employee["age_at_separation"]
    revocation_days = REVOCATION_DAYS if (age is not None and age >= OWBPA_PROTECTED_AGE) else 0
    offer["status"] = "SIGNED"
    offer["signed_utc"] = iso_ms(signed_at)
    offer["revocation_deadline_utc"] = iso_ms(signed_at + timedelta(days=revocation_days))
    touch(offer)

    employee["release_signed"] = True
    employee["benefit_continuation_status"] = "ACTIVE"
    employee["benefit_subsidy_months"] = offer["benefit_subsidy_months"]
    employee["benefit_subsidy_cents"] = offer["benefit_subsidy_cents"]
    employee["outplacement_tier"] = outplacement_tier_for_months(offer["benefit_subsidy_months"])
    touch(employee)

    recompute_plan(plan)
    return ok(offer_out(offer))


@bp.route("/severance-offers/<offer_id>/revoke", methods=["POST"])
@endpoint(["SeparatingEmployee"])
def revoke_offer(offer_id):
    payload = body()
    req_str(payload, "revocation_reason")

    offer = must_exist("offers", offer_id)
    selection, employee, plan = _offer_context(offer)

    if selection is None or g.user_id != selection["employee_id"]:
        raise ApiError("ERR_NOT_OFFER_RECIPIENT", 403)
    if offer["status"] != "SIGNED":
        raise ApiError("ERR_INVALID_OFFER_STATE", 409)

    deadline = parse_instant(offer["revocation_deadline_utc"])
    if deadline is not None and db.clock > deadline:
        raise ApiError("ERR_REVOCATION_WINDOW_CLOSED", 422)

    offer["status"] = "REVOKED"
    offer["revoked_utc"] = iso_ms(db.clock)
    touch(offer)

    employee["release_signed"] = False
    employee["benefit_continuation_status"] = "TERMINATED"
    employee["benefit_subsidy_months"] = 0
    employee["benefit_subsidy_cents"] = 0
    employee["outplacement_tier"] = "NONE"
    touch(employee)

    recompute_plan(plan)
    return ok(offer_out(offer))

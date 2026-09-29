"""ParticipantAward routes: the manager allocation surface and the payout preview."""

from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import (BUSINESS_UNIT_MANAGER, COMPENSATION_COMMITTEE, EMPLOYEE,
                        FINANCE_CONTROLLER, HR_BUSINESS_PARTNER, PLAN_ADMIN,
                        authenticate, get_body, opt_string, query_param,
                        req_int, req_string)
from response import object_response
from routes.common import paginated
from serialize import award_out
from services import calc, lookup, payout, rollup

bp = Blueprint("awards", __name__)

DETAIL_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, BUSINESS_UNIT_MANAGER,
                HR_BUSINESS_PARTNER, FINANCE_CONTROLLER, EMPLOYEE]
LIST_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, BUSINESS_UNIT_MANAGER,
              HR_BUSINESS_PARTNER, FINANCE_CONTROLLER]
PREVIEW_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, FINANCE_CONTROLLER,
                 HR_BUSINESS_PARTNER]

ELIGIBLE_FOR_MONEY = ("ELIGIBLE", "GOOD_LEAVER")


def _allocated_contribution(award):
    if award["allocation_status"] in calc.ALLOCATED_STATUSES:
        return award["proposed_allocation_cents"] + award["adjustment_total_cents"]
    return 0


@bp.route("/participant-awards/<award_id>/propose-allocation", methods=["POST"])
def propose_allocation(award_id):
    caller = authenticate([BUSINESS_UNIT_MANAGER])
    award = lookup.award(award_id)
    body = get_body()
    amount = req_int(body, "proposed_allocation_cents")
    rationale = req_string(body, "allocation_rationale")
    expected_pool_version = req_int(body, "expected_pool_version")

    if caller.user_id != award["business_unit_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNERSHIP",
                       "This manager does not own the award's business unit")

    plan = lookup.plan(award["plan_id"])
    pool = lookup.pool(award["bu_pool_id"])

    if plan["status"] != "ALLOCATION_OPEN":
        raise ApiError("ERR_PLAN_NOT_IN_ALLOCATION")
    if pool["calibration_status"] not in ("FUNDED", "ALLOCATING"):
        raise ApiError("ERR_POOL_NOT_ALLOCATING")
    if award["allocation_status"] not in ("UNALLOCATED", "PROPOSED"):
        raise ApiError("ERR_AWARD_STATE_INVALID",
                       "Allocation requires an award in UNALLOCATED or PROPOSED")
    if expected_pool_version != pool["version"]:
        raise ApiError("ERR_STALE_POOL_VERSION")
    if award["eligibility_status"] not in ELIGIBLE_FOR_MONEY:
        raise ApiError("ERR_AWARD_NOT_ELIGIBLE")

    # ladder 13: guideline band on the exact unrounded ratio (zero always allowed)
    if amount != 0:
        target = db.target_for_level(plan["id"], award.get("_job_level"))
        if target is None or award["prorated_target_cents"] <= 0:
            raise ApiError("ERR_GUIDELINE_RATIO_BREACH")
        ratio = calc.dec(amount) / calc.dec(award["prorated_target_cents"])
        if not (calc.dec(target["guideline_min_ratio"]) <= ratio
                <= calc.dec(target["guideline_max_ratio"])):
            raise ApiError("ERR_GUIDELINE_RATIO_BREACH")

    # ladder 14: pool capacity, with this award's previous amount removed first
    projected = (pool["allocated_cents"] - _allocated_contribution(award)
                 + amount + award["adjustment_total_cents"])
    if projected > pool["funded_cents"]:
        raise ApiError("ERR_POOL_FUNDS_EXCEEDED")

    award["proposed_allocation_cents"] = amount
    award["allocation_rationale"] = rationale
    award["allocation_status"] = "PROPOSED"
    rollup.refresh_award_money(award)
    db.touch(award)

    if pool["calibration_status"] == "FUNDED":
        pool["calibration_status"] = "ALLOCATING"
    rollup.recompute_pool(pool, bump=False)
    db.touch(pool)
    rollup.recompute_plan_governance(plan)

    return object_response(award_out(award))


@bp.route("/participant-awards/<award_id>/retract-allocation", methods=["POST"])
def retract_allocation(award_id):
    caller = authenticate([BUSINESS_UNIT_MANAGER])
    award = lookup.award(award_id)
    body = get_body()
    expected_pool_version = req_int(body, "expected_pool_version")
    reason = opt_string(body, "retraction_reason")

    if caller.user_id != award["business_unit_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNERSHIP",
                       "This manager does not own the award's business unit")

    plan = lookup.plan(award["plan_id"])
    pool = lookup.pool(award["bu_pool_id"])

    if plan["status"] != "ALLOCATION_OPEN":
        raise ApiError("ERR_PLAN_NOT_IN_ALLOCATION")
    if pool["calibration_status"] not in ("FUNDED", "ALLOCATING"):
        raise ApiError("ERR_POOL_NOT_ALLOCATING")
    if award["allocation_status"] != "PROPOSED":
        raise ApiError("ERR_AWARD_STATE_INVALID",
                       "Retraction requires an award in PROPOSED")
    if expected_pool_version != pool["version"]:
        raise ApiError("ERR_STALE_POOL_VERSION")
    if award["adjustment_total_cents"] != 0:
        raise ApiError("ERR_AWARD_HAS_APPROVED_ADJUSTMENT")

    award["proposed_allocation_cents"] = 0
    award["allocation_ratio"] = Decimal("0.0000")
    award["final_award_cents"] = 0
    award["retraction_count"] += 1
    award["allocation_rationale"] = reason if reason is not None else ""
    award["allocation_status"] = "UNALLOCATED"
    db.touch(award)

    rollup.recompute_pool(pool, bump=False)
    db.touch(pool)
    rollup.recompute_plan_governance(plan)

    return object_response(award_out(award))


@bp.route("/participant-awards/<award_id>", methods=["GET"])
def get_award(award_id):
    authenticate(DETAIL_ROLES)
    return object_response(award_out(lookup.award(award_id)))


@bp.route("/participant-awards", methods=["GET"])
def list_awards():
    authenticate(LIST_ROLES)
    filters = (
        ("plan_id", "plan_id"),
        ("participant_id", "participant_id"),
        ("business_unit_id", "business_unit_id"),
        ("bu_pool_id", "bu_pool_id"),
        ("allocation_status", "allocation_status"),
        ("payment_status", "payment_status"),
        ("eligibility_status", "eligibility_status"),
    )
    records = db.ordered(db.participant_awards)
    for param, field in filters:
        value = query_param(param)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return paginated(records, award_out)


@bp.route("/participant-awards/<award_id>/payout-preview", methods=["GET"])
def payout_preview(award_id):
    authenticate(PREVIEW_ROLES)
    award = lookup.award(award_id)
    plan = lookup.plan(award["plan_id"])
    participant = lookup.participant(award["participant_id"])

    status, amount = payout.payment_outcome(plan, participant, award)
    projection = award_out(award)
    projection["payment_status"] = status
    projection["payout_amount_cents"] = amount
    projection["previewed_payment_status"] = status
    projection["previewed_payout_amount_cents"] = amount
    projection["termination_treatment_policy"] = plan["termination_treatment_policy"]
    projection["employed_on_payment_date"] = payout.employed_on_payment_date(
        plan, participant)
    return object_response(projection)

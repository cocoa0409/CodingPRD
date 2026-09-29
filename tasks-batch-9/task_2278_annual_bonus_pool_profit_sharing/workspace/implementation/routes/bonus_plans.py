"""BonusPlan routes and the plan-level workflow transitions (PRD 3.1, 3.3-3.7)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import (BUSINESS_UNIT_MANAGER, COMPENSATION_COMMITTEE, EMPLOYEE,
                        FINANCE_CONTROLLER, HR_BUSINESS_PARTNER, PLAN_ADMIN,
                        authenticate, get_body, opt_enum, opt_percent,
                        opt_string, query_int, query_param, req_date, req_enum,
                        req_int, req_number, req_percent, req_string)
from response import object_response
from routes.common import paginated
from serialize import plan_out
from services import calc, lookup, proration, rollup

bp = Blueprint("bonus_plans", __name__)

ALL_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, BUSINESS_UNIT_MANAGER,
             HR_BUSINESS_PARTNER, FINANCE_CONTROLLER, EMPLOYEE]

TERMINATION_POLICIES = {"STRICT_PAYMENT_DATE", "GOOD_LEAVER_PRORATION"}
DECISIONS = {"CERTIFY", "RETURN"}

PLAN_STATUSES = {"DRAFT", "TARGETS_SET", "PENDING_CERTIFICATION", "CERTIFIED",
                 "ALLOCATION_OPEN", "CALIBRATION_REVIEW", "LOCKED", "PAID_OUT",
                 "SETTLED"}


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@bp.route("/bonus-plans", methods=["POST"])
def create_bonus_plan():
    authenticate([PLAN_ADMIN])
    body = get_body()

    plan_year = req_int(body, "plan_year", minimum=1900, maximum=2999)
    plan_name = req_string(body, "plan_name")
    period_start = req_date(body, "plan_period_start")
    period_end = req_date(body, "plan_period_end")
    payment_date = req_date(body, "payment_date")
    company_weight = req_percent(body, "company_weight_pct")
    bu_weight = req_percent(body, "business_unit_weight_pct")
    individual_weight = req_percent(body, "individual_weight_pct")
    discretionary_pct = opt_percent(body, "discretionary_budget_pct",
                                   default=Decimal("10.00"),
                                   minimum=0, maximum=25)
    policy = opt_enum(body, "termination_treatment_policy", TERMINATION_POLICIES,
                      default="STRICT_PAYMENT_DATE")

    # ladder 6: field relationships, then uniqueness
    if company_weight + bu_weight + individual_weight != Decimal("100.00"):
        raise ApiError("ERR_PLAN_WEIGHTS_INVALID")
    if period_end != period_start + timedelta(days=365) or payment_date < period_end:
        raise ApiError("ERR_PLAN_PERIOD_INVALID")
    for existing in db.ordered(db.bonus_plans):
        if existing["plan_year"] == plan_year and existing["plan_name"] == plan_name:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A plan already exists for this year and name")

    plan = db.base_record()
    plan.update({
        "plan_year": plan_year,
        "plan_name": plan_name,
        "plan_period_start": period_start.isoformat(),
        "plan_period_end": period_end.isoformat(),
        "payment_date": payment_date.isoformat(),
        "company_weight_pct": company_weight,
        "business_unit_weight_pct": bu_weight,
        "individual_weight_pct": individual_weight,
        "discretionary_budget_pct": discretionary_pct,
        "termination_treatment_policy": policy,
        "status": "DRAFT",
        "company_achievement_pct": Decimal("0.00"),
        "bu_weighted_achievement_pct": Decimal("0.00"),
        "blended_achievement_pct": Decimal("0.00"),
        "funding_multiplier": Decimal("0.0000"),
        "total_target_cents": 0,
        "funded_pool_cents": 0,
        "aggregate_rounding_delta_cents": 0,
        "discretionary_budget_cents": 0,
        "discretionary_used_cents": 0,
        "accrued_base_cents": 0,
        "accrued_total_cents": 0,
        "locked_total_cents": 0,
        "paid_total_cents": 0,
        "forfeited_total_cents": 0,
        "dispute_adjustment_cents": 0,
        "settlement_burden_cents": 0,
        "true_up_cents": 0,
        "over_allocated_pool_count": 0,
        "under_utilized_pool_count": 0,
        "governance_posture": "COMPLIANT",
        "certified_by_user_id": None,
        "locked_by_user_id": None,
    })
    db.bonus_plans[plan["id"]] = plan
    return object_response(plan_out(plan), 201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.route("/bonus-plans", methods=["GET"])
def list_bonus_plans():
    authenticate(ALL_ROLES)
    plan_year = query_int("plan_year")
    status = query_param("status")
    records = db.ordered(db.bonus_plans)
    if plan_year is not None:
        records = [r for r in records if r["plan_year"] == plan_year]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginated(records, plan_out)


@bp.route("/bonus-plans/<plan_id>", methods=["GET"])
def get_bonus_plan(plan_id):
    authenticate(ALL_ROLES)
    return object_response(plan_out(lookup.plan(plan_id)))


@bp.route("/bonus-plans/<plan_id>/funding-summary", methods=["GET"])
def funding_summary(plan_id):
    authenticate([PLAN_ADMIN, COMPENSATION_COMMITTEE, FINANCE_CONTROLLER])
    return object_response(plan_out(lookup.plan(plan_id)))


# ---------------------------------------------------------------------------
# target-assignments (DRAFT -> TARGETS_SET, TARGETS_SET self-transition)
# ---------------------------------------------------------------------------
@bp.route("/bonus-plans/<plan_id>/target-assignments", methods=["POST"])
def target_assignments(plan_id):
    authenticate([PLAN_ADMIN])
    plan = lookup.plan(plan_id)
    get_body()

    if plan["status"] not in ("DRAFT", "TARGETS_SET"):
        raise ApiError("ERR_PLAN_STATE_INVALID",
                       "Target assignments require a plan in DRAFT or TARGETS_SET")

    participants = db.plan_participants(plan_id)

    # Atomic: resolve every participant's proration (ERR_JOB_LEVEL_TARGET_MISSING)
    # before resolving any pool (ERR_POOL_MISSING_FOR_UNIT) — ladder 12 order.
    computed = []
    for participant in participants:
        computed.append((participant,
                         proration.compute_award_targets(plan, participant,
                                                         strict=True)))
    for participant, fields in computed:
        if fields["bu_pool_id"] is None:
            raise ApiError("ERR_POOL_MISSING_FOR_UNIT",
                           "No pool exists for business unit '%s' in this plan"
                           % fields["business_unit_id"])

    plan_before = db.snapshot(plan)

    for participant, fields in computed:
        award = db.award_for_participant(participant["id"])
        if award is None:
            award = db.base_record()
            award.update({
                "plan_id": plan_id,
                "participant_id": participant["id"],
                "business_unit_id": fields["business_unit_id"],
                "bu_pool_id": fields["bu_pool_id"],
                "target_bonus_pct": fields["target_bonus_pct"],
                "credited_days": fields["credited_days"],
                "excluded_leave_days": fields["excluded_leave_days"],
                "segment_count": fields["segment_count"],
                "prorated_target_cents": fields["prorated_target_cents"],
                "eligibility_status": fields["eligibility_status"],
                "allocation_status": "UNALLOCATED",
                "payment_status": "PENDING",
                "proposed_allocation_cents": 0,
                "allocation_ratio": Decimal("0.0000"),
                "adjustment_total_cents": 0,
                "final_award_cents": 0,
                "payout_amount_cents": 0,
                "allocation_rationale": "",
                "retraction_count": 0,
                "_job_level": fields["_job_level"],
            })
            db.participant_awards[award["id"]] = award
        else:
            award_before = db.snapshot(award)
            award.update({
                "business_unit_id": fields["business_unit_id"],
                "bu_pool_id": fields["bu_pool_id"],
                "target_bonus_pct": fields["target_bonus_pct"],
                "credited_days": fields["credited_days"],
                "excluded_leave_days": fields["excluded_leave_days"],
                "segment_count": fields["segment_count"],
                "prorated_target_cents": fields["prorated_target_cents"],
                "eligibility_status": fields["eligibility_status"],
                "_job_level": fields["_job_level"],
            })
            rollup.refresh_award_money(award)
            db.bump_if_changed(award, award_before)

    rollup.recompute_pools(plan)
    plan["total_target_cents"] = sum(p["eligible_target_cents"]
                                     for p in db.plan_pools(plan_id))
    rollup.apply_plan_governance(plan)
    plan["status"] = "TARGETS_SET"
    if not db.bump_if_changed(plan, plan_before):
        db.touch(plan)
    return object_response(plan_out(plan))


# ---------------------------------------------------------------------------
# submit-for-certification (TARGETS_SET -> PENDING_CERTIFICATION)
# ---------------------------------------------------------------------------
@bp.route("/bonus-plans/<plan_id>/submit-for-certification", methods=["POST"])
def submit_for_certification(plan_id):
    authenticate([PLAN_ADMIN])
    plan = lookup.plan(plan_id)
    get_body()

    if plan["status"] != "TARGETS_SET":
        raise ApiError("ERR_PLAN_STATE_INVALID",
                       "Submission requires a plan in TARGETS_SET")

    metrics = db.plan_metrics(plan_id)
    weight_total = sum((Decimal(str(m["weight_pct"])) for m in metrics),
                       Decimal("0"))
    if not metrics or weight_total != Decimal("100.00"):
        raise ApiError("ERR_METRIC_WEIGHTS_INVALID")
    if any(m["status"] != "ACTUAL_ENTERED" for m in metrics):
        raise ApiError("ERR_METRICS_NOT_ALL_ACTUALIZED")
    if any(p["calibration_status"] != "SCORECARD_CERTIFIED"
           for p in db.plan_pools(plan_id)):
        raise ApiError("ERR_SCORECARDS_NOT_ALL_CERTIFIED")
    if plan["total_target_cents"] <= 0:
        raise ApiError("ERR_NO_ELIGIBLE_PARTICIPANTS")

    plan["status"] = "PENDING_CERTIFICATION"
    db.touch(plan)
    return object_response(plan_out(plan))


# ---------------------------------------------------------------------------
# certification-decision (PENDING_CERTIFICATION -> CERTIFIED | TARGETS_SET)
# ---------------------------------------------------------------------------
@bp.route("/bonus-plans/<plan_id>/certification-decision", methods=["POST"])
def certification_decision(plan_id):
    authenticate([COMPENSATION_COMMITTEE])
    plan = lookup.plan(plan_id)
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    opt_string(body, "decision_note")
    caller = authenticate([COMPENSATION_COMMITTEE])

    if plan["status"] != "PENDING_CERTIFICATION":
        raise ApiError("ERR_PLAN_STATE_INVALID",
                       "Certification decision requires a plan in PENDING_CERTIFICATION")

    if decision == "CERTIFY":
        plan["company_achievement_pct"] = calc.company_achievement(
            db.plan_metrics(plan_id))
        plan["bu_weighted_achievement_pct"] = calc.bu_weighted_achievement(
            db.plan_pools(plan_id), plan["total_target_cents"])
        plan["blended_achievement_pct"] = calc.blended_achievement(
            plan["company_weight_pct"], plan["business_unit_weight_pct"],
            plan["individual_weight_pct"], plan["company_achievement_pct"],
            plan["bu_weighted_achievement_pct"])
        plan["funding_multiplier"] = calc.funding_curve_multiplier(
            plan["blended_achievement_pct"])
        plan["certified_by_user_id"] = caller.user_id
        plan["status"] = "CERTIFIED"
    else:
        for pool in db.plan_pools(plan_id):
            if pool["calibration_status"] == "SCORECARD_CERTIFIED":
                pool["calibration_status"] = "DRAFT"
                pool["scorecard_certified_by_user_id"] = None
                db.touch(pool)
        plan["bu_weighted_achievement_pct"] = Decimal("0.00")
        plan["blended_achievement_pct"] = Decimal("0.00")
        plan["funding_multiplier"] = Decimal("0.0000")
        plan["certified_by_user_id"] = None
        plan["status"] = "TARGETS_SET"

    db.touch(plan)
    return object_response(plan_out(plan))


# ---------------------------------------------------------------------------
# fund-pool (CERTIFIED -> ALLOCATION_OPEN)
# ---------------------------------------------------------------------------
@bp.route("/bonus-plans/<plan_id>/fund-pool", methods=["POST"])
def fund_pool(plan_id):
    authenticate([COMPENSATION_COMMITTEE])
    plan = lookup.plan(plan_id)
    get_body()

    if plan["status"] != "CERTIFIED":
        raise ApiError("ERR_PLAN_STATE_INVALID",
                       "Funding requires a plan in CERTIFIED")
    if Decimal(str(plan["funding_multiplier"])) <= Decimal("0.0000"):
        raise ApiError("ERR_FUNDING_MULTIPLIER_ZERO")

    multiplier = plan["funding_multiplier"]
    funded_total = 0
    for pool in db.plan_pools(plan_id):
        pool_before = db.snapshot(pool)
        pool["funded_cents"] = calc.pool_funded_cents(
            pool["eligible_target_cents"], multiplier)
        pool["min_utilization_cents"] = calc.min_utilization_cents(
            pool["funded_cents"])
        if pool["calibration_status"] == "SCORECARD_CERTIFIED":
            pool["calibration_status"] = "FUNDED"
        rollup.recompute_pool(pool, bump=False)
        funded_total += pool["funded_cents"]
        db.bump_if_changed(pool, pool_before)

    plan["funded_pool_cents"] = funded_total
    plan["aggregate_rounding_delta_cents"] = (
        calc.cents(calc.dec(plan["total_target_cents"]) * calc.dec(multiplier))
        - funded_total)
    plan["discretionary_budget_cents"] = calc.discretionary_budget_cents(
        funded_total, plan["discretionary_budget_pct"])
    rollup.apply_plan_governance(plan)
    plan["status"] = "ALLOCATION_OPEN"
    db.touch(plan)
    return object_response(plan_out(plan))


# ---------------------------------------------------------------------------
# open-calibration (ALLOCATION_OPEN -> CALIBRATION_REVIEW)
# ---------------------------------------------------------------------------
@bp.route("/bonus-plans/<plan_id>/open-calibration", methods=["POST"])
def open_calibration(plan_id):
    authenticate([PLAN_ADMIN])
    plan = lookup.plan(plan_id)
    get_body()

    if plan["status"] != "ALLOCATION_OPEN":
        raise ApiError("ERR_PLAN_STATE_INVALID",
                       "Opening calibration requires a plan in ALLOCATION_OPEN")
    for pool in db.plan_pools(plan_id):
        if pool["calibration_status"] not in ("CALIBRATION_SUBMITTED", "CALIBRATED"):
            raise ApiError("ERR_POOL_CALIBRATION_PENDING")

    plan["status"] = "CALIBRATION_REVIEW"
    db.touch(plan)
    return object_response(plan_out(plan))


# ---------------------------------------------------------------------------
# lock (CALIBRATION_REVIEW -> LOCKED)
# ---------------------------------------------------------------------------
@bp.route("/bonus-plans/<plan_id>/lock", methods=["POST"])
def lock_plan(plan_id):
    caller = authenticate([COMPENSATION_COMMITTEE])
    plan = lookup.plan(plan_id)
    get_body()

    if plan["status"] != "CALIBRATION_REVIEW":
        raise ApiError("ERR_PLAN_STATE_INVALID",
                       "Locking requires a plan in CALIBRATION_REVIEW")
    if plan["certified_by_user_id"] is not None \
            and caller.user_id == plan["certified_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The certifying member may not lock the plan")
    if plan["governance_posture"] != "COMPLIANT":
        raise ApiError("ERR_GOVERNANCE_POSTURE_BREACHED")
    pools = db.plan_pools(plan_id)
    for pool in pools:
        if pool["calibration_status"] != "CALIBRATED":
            raise ApiError("ERR_POOL_CALIBRATION_PENDING")

    for pool in pools:
        pool["calibration_status"] = "LOCKED"
        db.touch(pool)
        for award in db.pool_awards(pool["id"]):
            if award["allocation_status"] == "CALIBRATED":
                award["allocation_status"] = "LOCKED"
                db.touch(award)

    plan["locked_total_cents"] = sum(
        a["final_award_cents"] for a in db.plan_awards(plan_id)
        if a["allocation_status"] == "LOCKED")
    plan["locked_by_user_id"] = caller.user_id
    plan["status"] = "LOCKED"
    db.touch(plan)
    return object_response(plan_out(plan))

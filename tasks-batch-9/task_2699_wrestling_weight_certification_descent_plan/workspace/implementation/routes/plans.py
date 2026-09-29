"""Descent plans, the weekly progression schedule and revision."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import lookups
import serialize
import validate as V
from auth import endpoint, require_team_owner
from envelope import ok, ok_list
from errors import ApiError
from routes.core import require_open
from store import DB, fmt_date, new_row, parse_date, touch

bp = Blueprint("plans", __name__)

PLAN_VARIANTS = ("WEEKLY_STEP", "LINEAR_RATE")
PLAN_STATUSES = ("DRAFT", "CERTIFIED", "BREACHED", "COMPLETED", "CANCELLED")
MILESTONE_STATUSES = ("SCHEDULED", "MET", "MISSED", "WAIVED")


def _pin_wrestler(body, wrestler):
    expected = V.req_int(body, "expected_wrestler_version")
    if expected != int(wrestler.get("version") or 0):
        raise ApiError(
            "ERR_STALE_WRESTLER_VERSION",
            "expected_wrestler_version %s does not match the wrestler's stored version %s."
            % (expected, wrestler.get("version")),
        )


def _rate_gate(alpha, target, requested_weeks, rate):
    if requested_weeks is None:
        return
    if not calc.rate_admissible(alpha, target, requested_weeks, rate):
        raise ApiError("ERR_DESCENT_RATE_EXCEEDED",
                       "The requested_weeks figure implies a weekly delta above the "
                       "permitted maximum.")


@bp.post("/wrestlers/<wrestler_id>/descent-plans")
@endpoint("TeamCoach")
def create_plan(wrestler_id):
    wrestler = lookups.wrestler(wrestler_id)
    body = V.get_body()
    source = lookups.assessment(V.req_id_ref(body, "source_assessment_id"))
    require_team_owner(wrestler.get("team_id"))

    season = lookups.season_of_wrestler(wrestler)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")

    variant = V.req_enum(body, "plan_variant", PLAN_VARIANTS)
    target = V.weight_class(body, "target_class_lbs", season)
    start_date = V.req_date(body, "plan_start_date")
    _pin_wrestler(body, wrestler)
    requested_weeks = V.opt_int(body, "requested_weeks", minimum=1)

    if wrestler.get("certification_status") == "DISQUALIFIED":
        raise ApiError("ERR_WRESTLER_DISQUALIFIED",
                       "A disqualified wrestler cannot open a descent plan.")
    require_open(season)

    if wrestler.get("certification_status") in ("UNCERTIFIED", "SUSPENDED"):
        raise ApiError("ERR_WRESTLER_NOT_CERTIFIED",
                       "The wrestler has no validated source assessment on file.")
    if serialize.team_posture(wrestler.get("team_id")) == "PROBATION":
        raise ApiError("ERR_TEAM_ON_PROBATION",
                       "A team on PROBATION may not open new descent plans.")
    if (source.get("status") != "VALIDATED"
            or source.get("wrestler_id") != wrestler["id"]):
        raise ApiError("ERR_ASSESSMENT_WRESTLER_MISMATCH",
                       "source_assessment_id must be a VALIDATED assessment of this wrestler.")
    floor = wrestler.get("min_weight_class_lbs")
    if floor is not None and int(target) < int(floor):
        raise ApiError("ERR_TARGET_BELOW_MINIMUM",
                       "target_class_lbs is below the wrestler's min_weight_class_lbs.")

    rate = season.get("max_weekly_descent_pct")
    _rate_gate(wrestler.get("alpha_weight_lbs"), target, requested_weeks, rate)

    # supersede the wrestler's prior non-terminal plan
    prior = [
        p for p in lookups.plans_of_wrestler(wrestler["id"])
        if p.get("status") in ("DRAFT", "CERTIFIED", "BREACHED")
    ]
    prior.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    supersedes_plan_id = None
    superseded_status = None
    if prior:
        victim = prior[-1]
        superseded_status = victim.get("status")
        for row in prior:
            row["status"] = "CANCELLED"
            row["cancel_reason"] = "SUPERSEDED"
            touch(row)
        supersedes_plan_id = victim["id"]

    if superseded_status == "CERTIFIED":
        wrestler["certification_status"] = "PROVISIONAL"
        wrestler["eligibility_status"] = "INELIGIBLE"
    touch(wrestler)

    row = new_row()
    row.update({
        "wrestler_id": wrestler["id"],
        "source_assessment_id": source["id"],
        "supersedes_plan_id": supersedes_plan_id,
        "plan_variant": variant,
        "target_class_lbs": target,
        "plan_start_date": fmt_date(start_date),
        "weekly_rate_pct": rate,
        "weekly_delta_lbs": None,
        "status": "DRAFT",
        "total_weeks": None,
        "projected_certification_date": None,
        "breach_count": 0,
        "revision_count": 0,
        "cancel_reason": None,
    })
    DB.plans[row["id"]] = row
    return ok(serialize.plan(row), 201)


@bp.get("/descent-plans/<plan_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach", "MedicalReviewer")
def read_plan(plan_id):
    return ok(serialize.plan(lookups.plan(plan_id)))


@bp.get("/descent-plans")
@endpoint("StateOffice", "Assessor", "TeamCoach", "MedicalReviewer")
def list_plans():
    wrestler_id = V.q_str("wrestler_id")
    source_assessment_id = V.q_str("source_assessment_id")
    supersedes_plan_id = V.q_str("supersedes_plan_id")
    status = V.q_enum("status", PLAN_STATUSES)
    limit, offset = V.pagination()
    rows = list(DB.plans.values())
    if wrestler_id is not None:
        rows = [r for r in rows if r.get("wrestler_id") == wrestler_id]
    if source_assessment_id is not None:
        rows = [r for r in rows if r.get("source_assessment_id") == source_assessment_id]
    if supersedes_plan_id is not None:
        rows = [r for r in rows if r.get("supersedes_plan_id") == supersedes_plan_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.plan(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)


@bp.post("/descent-plans/<plan_id>/certify")
@endpoint("StateOffice")
def certify_plan(plan_id):
    plan = lookups.plan(plan_id)
    wrestler = DB.wrestlers.get(plan.get("wrestler_id"))
    if wrestler is None:
        raise ApiError("ERR_WRESTLER_NOT_FOUND")
    season = lookups.season_of_wrestler(wrestler)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")

    if wrestler.get("certification_status") == "DISQUALIFIED":
        raise ApiError("ERR_WRESTLER_DISQUALIFIED",
                       "A disqualified wrestler's plan cannot be certified.")
    require_open(season)
    if plan.get("status") != "DRAFT":
        raise ApiError("ERR_PLAN_INVALID_STATE",
                       "Only a DRAFT plan may be certified.")

    source = DB.assessments.get(plan.get("source_assessment_id"))
    if source is None or source.get("status") != "VALIDATED":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE",
                       "The plan's source assessment is no longer VALIDATED.")
    floor = wrestler.get("min_weight_class_lbs")
    if floor is not None and int(plan.get("target_class_lbs")) < int(floor):
        raise ApiError("ERR_TARGET_BELOW_MINIMUM",
                       "target_class_lbs now sits below the wrestler's min_weight_class_lbs.")
    if wrestler.get("certification_status") not in ("PROVISIONAL", "CERTIFIED"):
        raise ApiError("ERR_WRESTLER_NOT_CERTIFIED",
                       "The wrestler has no validated source assessment on file.")

    start_date = parse_date(plan.get("plan_start_date"))
    weights, total_weeks, delta = calc.descent_schedule_projection(
        plan.get("plan_variant"), wrestler.get("alpha_weight_lbs"),
        plan.get("weekly_rate_pct"), plan.get("target_class_lbs"))

    plan["total_weeks"] = total_weeks
    plan["weekly_delta_lbs"] = delta
    plan["projected_certification_date"] = fmt_date(
        start_date + timedelta(days=7 * total_weeks))
    plan["status"] = "CERTIFIED"
    touch(plan)

    cascade.generate_milestones(plan, wrestler, season, weights, start_date)

    wrestler["certification_status"] = "CERTIFIED"
    posture = serialize.team_posture(wrestler.get("team_id"))
    wrestler["eligibility_status"] = "RESTRICTED" if posture == "PROBATION" else "ELIGIBLE"
    touch(wrestler)
    return ok(serialize.plan(plan))


@bp.post("/descent-plans/<plan_id>/revise")
@endpoint("TeamCoach")
def revise_plan(plan_id):
    plan = lookups.plan(plan_id)
    wrestler = DB.wrestlers.get(plan.get("wrestler_id"))
    if wrestler is None:
        raise ApiError("ERR_WRESTLER_NOT_FOUND")
    require_team_owner(wrestler.get("team_id"))
    season = lookups.season_of_wrestler(wrestler)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")

    body = V.get_body()
    start_date = V.req_date(body, "plan_start_date")
    target = V.weight_class(body, "target_class_lbs", season, required=False,
                            default=plan.get("target_class_lbs"))
    variant = V.opt_enum(body, "plan_variant", PLAN_VARIANTS,
                         default=plan.get("plan_variant"))
    requested_weeks = V.opt_int(body, "requested_weeks", minimum=1)

    if wrestler.get("certification_status") == "DISQUALIFIED":
        raise ApiError("ERR_WRESTLER_DISQUALIFIED",
                       "A disqualified wrestler's plan cannot be revised.")
    require_open(season)
    if plan.get("status") != "BREACHED":
        raise ApiError("ERR_PLAN_INVALID_STATE",
                       "Only a BREACHED plan may be revised.")

    floor = wrestler.get("min_weight_class_lbs")
    if floor is not None and int(target) < int(floor):
        raise ApiError("ERR_TARGET_BELOW_MINIMUM",
                       "target_class_lbs is below the wrestler's min_weight_class_lbs.")
    _rate_gate(wrestler.get("alpha_weight_lbs"), target, requested_weeks,
               plan.get("weekly_rate_pct"))

    # waive the scheduled rows that predate the new start date, delete the rest
    kept_indices = []
    for milestone in sorted(lookups.milestones_of_plan(plan["id"]),
                            key=lambda m: int(m.get("week_index") or 0)):
        if milestone.get("status") != "SCHEDULED":
            kept_indices.append(int(milestone.get("week_index") or 0))
            continue
        effective = parse_date(milestone.get("effective_date"))
        if effective is not None and effective < start_date:
            milestone["status"] = "WAIVED"
            touch(milestone)
            kept_indices.append(int(milestone.get("week_index") or 0))
        else:
            DB.milestones.pop(milestone["id"], None)

    base_index = (max(kept_indices) + 1) if kept_indices else 0

    weights, total_weeks, delta = calc.descent_schedule_projection(
        variant, wrestler.get("alpha_weight_lbs"),
        plan.get("weekly_rate_pct"), target)

    plan["plan_variant"] = variant
    plan["target_class_lbs"] = target
    plan["plan_start_date"] = fmt_date(start_date)
    plan["total_weeks"] = total_weeks
    plan["weekly_delta_lbs"] = delta
    plan["projected_certification_date"] = fmt_date(
        start_date + timedelta(days=7 * total_weeks))
    plan["revision_count"] = int(plan.get("revision_count") or 0) + 1
    plan["status"] = "CERTIFIED"
    touch(plan)

    cascade.generate_milestones(plan, wrestler, season, weights, start_date,
                                base_index=base_index)
    return ok(serialize.plan(plan))


@bp.get("/descent-plans/<plan_id>/milestones")
@endpoint("StateOffice", "Assessor", "TeamCoach", "MedicalReviewer")
def list_milestones(plan_id):
    plan = lookups.plan(plan_id)
    status = V.q_enum("status", MILESTONE_STATUSES)
    limit, offset = V.pagination()
    rows = lookups.milestones_of_plan(plan["id"])
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: (int(r.get("week_index") or 0), r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.milestone(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)

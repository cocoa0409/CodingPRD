"""Timecard endpoints: create, flag, revise, approve, and reads."""

from flask import Blueprint, request

import db
from calculations import (
    find_tier, compute_worked_minutes, compute_overtime_minutes,
    provisional_penalty_cents, daily_gross_cents, final_penalty_assessment,
    create_penalty_assessments, recompute_engagement_accrued_penalty,
)
from errors import (
    ApiError, ERR_TIMECARD_INVALID_STATE, ERR_ENGAGEMENT_NOT_ACTIVE,
    ERR_DUPLICATE_WORK_DATE, ERR_VALIDATION,
)
from helpers import (
    new_id, now_timestamp, parse_date, parse_timestamp, require_field,
    require_number, require_string, err_validation, temporal_error,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, list_response
from serializers import serialize, get_or_404, bump_version

bp = Blueprint("timecards", __name__)


def _read_timecard_payload(body, for_revise=False):
    """Extract and shape-check timecard fields. Returns a dict of raw values
    plus parsed datetimes/dates. ERR_VALIDATION on bad shapes."""
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")

    out = {}
    if not for_revise:
        out["engagement_id"] = require_string(body, "engagement_id")
        out["work_date_raw"] = require_string(body, "work_date")
        out["jurisdiction_code"] = require_string(body, "jurisdiction_code")
    out["call_time_raw"] = require_string(body, "call_time")
    out["first_meal_out_raw"] = require_string(body, "first_meal_out")
    out["first_meal_in_raw"] = require_string(body, "first_meal_in")
    out["wrap_time_raw"] = require_string(body, "wrap_time")
    out["scheduled_hours"] = require_number(body, "scheduled_hours", minimum=0)

    # Parse timestamps/dates (shape only at this stage)
    out["call_time"] = parse_timestamp(out["call_time_raw"], "call_time")
    out["first_meal_out"] = parse_timestamp(out["first_meal_out_raw"], "first_meal_out")
    out["first_meal_in"] = parse_timestamp(out["first_meal_in_raw"], "first_meal_in")
    out["wrap_time"] = parse_timestamp(out["wrap_time_raw"], "wrap_time")
    return out


def _check_temporal_ordering(payload):
    """first_meal_in > first_meal_out and wrap_time > first_meal_in."""
    if payload["first_meal_in"] <= payload["first_meal_out"]:
        raise temporal_error("first_meal_in must be strictly after first_meal_out")
    if payload["wrap_time"] <= payload["first_meal_in"]:
        raise temporal_error("wrap_time must be strictly after first_meal_in")


def _check_work_date_and_jurisdiction(engagement, production, work_date, jurisdiction_code):
    """work_date inside engagement window; jurisdiction valid at work_date."""
    start = parse_date(engagement["start_date"], "start_date")
    end = parse_date(engagement["end_date"], "end_date")
    if work_date < start or work_date > end:
        raise temporal_error("work_date must fall inside the engagement window")

    matched = None
    for jrow in production.get("jurisdictions", []):
        if jrow.get("jurisdiction_code") != jurisdiction_code:
            continue
        valid_from = parse_date(jrow.get("valid_from"), "valid_from")
        valid_to = parse_date(jrow.get("valid_to"), "valid_to")
        if valid_from <= work_date < valid_to:
            matched = jrow
            break
    if matched is None:
        raise temporal_error(
            "jurisdiction_code has no validity window covering work_date"
        )


def _compute_derived(record, engagement, agreement):
    """Recompute worked_minutes, overtime_minutes, provisional_penalty_cents."""
    tier = find_tier(agreement, engagement["tier_code"])
    record["worked_minutes"] = compute_worked_minutes(
        record["_call_time"], record["_first_meal_out"],
        record["_first_meal_in"], record["_wrap_time"],
    )
    record["overtime_minutes"] = compute_overtime_minutes(record["worked_minutes"], tier)
    record["provisional_penalty_cents"] = provisional_penalty_cents(
        record["scheduled_hours"], agreement
    )


@bp.post("/payroll/timecards")
def create_timecard():
    require_roles({"ProductionAccountant"})
    body = request.get_json(silent=True)
    payload = _read_timecard_payload(body, for_revise=False)

    # ---- priority 3: FK existence ----
    engagement = get_or_404(db.engagements, payload["engagement_id"], "Engagement")

    # ---- priority 12: engagement ACTIVE + production SHOOTING ----
    if engagement["status"] != "ACTIVE":
        raise ApiError(
            ERR_ENGAGEMENT_NOT_ACTIVE,
            "Timecard create requires the engagement to be ACTIVE",
            409,
        )
    production = get_or_404(db.productions, engagement["production_id"], "Production")
    if production["status"] != "SHOOTING":
        raise ApiError(
            ERR_ENGAGEMENT_NOT_ACTIVE,
            "Timecard create requires the production to be SHOOTING",
            409,
        )

    # ---- priority 15: temporal shape and containment ----
    _check_temporal_ordering(payload)
    work_date = parse_date(payload["work_date_raw"], "work_date")
    _check_work_date_and_jurisdiction(
        engagement, production, work_date, payload["jurisdiction_code"]
    )

    # ---- priority 19: one timecard per engagement per work_date ----
    for existing in db.timecards.values():
        if (
            existing["engagement_id"] == engagement["id"]
            and existing["work_date"] == payload["work_date_raw"]
        ):
            raise ApiError(
                ERR_DUPLICATE_WORK_DATE,
                "A timecard already exists for this engagement + work_date",
                409,
            )

    agreement = get_or_404(
        db.union_agreements, engagement["union_agreement_id"], "UnionAgreement"
    )

    now = now_timestamp()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "engagement_id": engagement["id"],
        "work_date": payload["work_date_raw"],
        "jurisdiction_code": payload["jurisdiction_code"],
        "call_time": payload["call_time_raw"],
        "first_meal_out": payload["first_meal_out_raw"],
        "first_meal_in": payload["first_meal_in_raw"],
        "wrap_time": payload["wrap_time_raw"],
        "scheduled_hours": payload["scheduled_hours"],
        "worked_minutes": 0,
        "overtime_minutes": 0,
        "provisional_penalty_cents": 0,
        "final_penalty_cents": 0,
        "day_gross_cents": 0,
        "review_status": "SUBMITTED",
        "payment_status": "UNBATCHED",
        # Internal parsed timestamps (never serialized)
        "_call_time": payload["call_time"],
        "_first_meal_out": payload["first_meal_out"],
        "_first_meal_in": payload["first_meal_in"],
        "_wrap_time": payload["wrap_time"],
    }
    _compute_derived(record, engagement, agreement)
    db.timecards[record["id"]] = record
    return success_object(serialize(record), 201)


@bp.get("/payroll/timecards")
def list_timecards():
    require_roles(ALL_ROLES)
    items = list(db.timecards.values())
    engagement_id = request.args.get("engagement_id")
    if engagement_id is not None:
        items = [t for t in items if t["engagement_id"] == engagement_id]
    review_status = request.args.get("review_status")
    if review_status is not None:
        items = [t for t in items if t["review_status"] == review_status]
    payment_status = request.args.get("payment_status")
    if payment_status is not None:
        items = [t for t in items if t["payment_status"] == payment_status]
    return list_response([serialize(t) for t in items], request.args)


@bp.get("/payroll/timecards/<timecard_id>")
def get_timecard(timecard_id):
    require_roles(ALL_ROLES)
    timecard = get_or_404(db.timecards, timecard_id, "Timecard")
    return success_object(serialize(timecard), 200)


@bp.post("/payroll/timecards/<timecard_id>/flag")
def flag_timecard(timecard_id):
    require_roles({"PayrollClerk"})
    timecard = get_or_404(db.timecards, timecard_id, "Timecard")

    if timecard["review_status"] != "SUBMITTED":
        raise ApiError(
            ERR_TIMECARD_INVALID_STATE,
            "Flag requires review_status SUBMITTED",
            409,
        )

    body = request.get_json(silent=True)
    flag_reason = None
    if isinstance(body, dict):
        flag_reason = body.get("flag_reason")
    if not isinstance(flag_reason, str) or flag_reason == "":
        raise ApiError(ERR_VALIDATION, "flag_reason is required", 400)

    timecard["review_status"] = "FLAGGED"
    bump_version(timecard)
    return success_object(serialize(timecard), 200)


@bp.post("/payroll/timecards/<timecard_id>/revise")
def revise_timecard(timecard_id):
    require_roles({"ProductionAccountant"})
    timecard = get_or_404(db.timecards, timecard_id, "Timecard")

    if timecard["review_status"] != "FLAGGED":
        raise ApiError(
            ERR_TIMECARD_INVALID_STATE,
            "Revise requires review_status FLAGGED",
            409,
        )

    body = request.get_json(silent=True)
    payload = _read_timecard_payload(body, for_revise=True)

    # Temporal ordering on the revised timestamps
    _check_temporal_ordering(payload)

    engagement = get_or_404(db.engagements, timecard["engagement_id"], "Engagement")
    agreement = get_or_404(
        db.union_agreements, engagement["union_agreement_id"], "UnionAgreement"
    )

    timecard["call_time"] = payload["call_time_raw"]
    timecard["first_meal_out"] = payload["first_meal_out_raw"]
    timecard["first_meal_in"] = payload["first_meal_in_raw"]
    timecard["wrap_time"] = payload["wrap_time_raw"]
    timecard["scheduled_hours"] = payload["scheduled_hours"]
    timecard["_call_time"] = payload["call_time"]
    timecard["_first_meal_out"] = payload["first_meal_out"]
    timecard["_first_meal_in"] = payload["first_meal_in"]
    timecard["_wrap_time"] = payload["wrap_time"]
    timecard["review_status"] = "SUBMITTED"
    _compute_derived(timecard, engagement, agreement)
    bump_version(timecard)
    return success_object(serialize(timecard), 200)


@bp.post("/payroll/timecards/<timecard_id>/approve")
def approve_timecard(timecard_id):
    require_roles({"PayrollClerk"})
    timecard = get_or_404(db.timecards, timecard_id, "Timecard")

    # Review gates: SUBMITTED and payment UNBATCHED
    if timecard["review_status"] != "SUBMITTED":
        raise ApiError(
            ERR_TIMECARD_INVALID_STATE,
            "Approve requires review_status SUBMITTED",
            409,
        )
    if timecard["payment_status"] != "UNBATCHED":
        raise ApiError(
            ERR_TIMECARD_INVALID_STATE,
            "Approve requires payment_status UNBATCHED",
            409,
        )

    # Cross-entity gate: engagement must still be ACTIVE
    engagement = get_or_404(db.engagements, timecard["engagement_id"], "Engagement")
    if engagement["status"] != "ACTIVE":
        raise ApiError(
            ERR_ENGAGEMENT_NOT_ACTIVE,
            "Timecard approve requires the engagement to be ACTIVE",
            409,
        )
    agreement = get_or_404(
        db.union_agreements, engagement["union_agreement_id"], "UnionAgreement"
    )
    tier = find_tier(agreement, engagement["tier_code"])

    # Final computations
    timecard["day_gross_cents"] = daily_gross_cents(timecard["worked_minutes"], tier)
    final_total, violations = final_penalty_assessment(timecard, engagement, agreement)
    timecard["final_penalty_cents"] = final_total

    timecard["review_status"] = "APPROVED"
    bump_version(timecard)

    create_penalty_assessments(timecard, violations)
    recompute_engagement_accrued_penalty(engagement)

    return success_object(serialize(timecard), 200)

"""CoachingReferral endpoints (PRD §3.6)."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import current_identity, require_roles
from response import success
from services import serializers
from services.cascade import recompute_projected_award_for_enrollment
from services.common import (
    check_employee_scope, get_enrollment_or_404, get_referral_or_404,
    parse_body, require_fields, stamp_new, touch,
)

bp = Blueprint("referrals", __name__)

_REASONS = {"HIGH_RISK", "TOBACCO_CESSATION", "RA_REQUEST"}
_OUTCOMES = {"GOALS_MET", "GOALS_NOT_MET"}


@bp.post("/wellness/coaching-referrals")
@require_roles("BenefitsAdmin")
def create_referral():
    body = parse_body()
    vals = require_fields(body, [
        ("enrollment_id", "string", True),
        ("reason", "enum", True, _REASONS),
    ])
    get_enrollment_or_404(vals["enrollment_id"])
    rec = stamp_new({
        "enrollment_id": vals["enrollment_id"],
        "reason": vals["reason"],
        "source": "MANUAL",
        "assigned_coach_id": None,
        "sessions_completed": 0,
        "session_dates": [],
        "referral_round": 1,
        "outcome": None,
        "status": "REFERRED",
    })
    DB.referrals[rec["id"]] = rec
    return success(serializers.referral(rec), status=201)


@bp.post("/wellness/coaching-referrals/<rid>/engage")
@require_roles("Coach")
def engage_referral(rid):
    ref = get_referral_or_404(rid)
    if ref["status"] != "REFERRED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a REFERRED referral may be engaged"
        )
    user_id, _ = current_identity()
    ref["assigned_coach_id"] = user_id
    ref["status"] = "ENGAGED"
    touch(ref)
    return success(serializers.referral(ref))


def _require_assigned_coach(ref):
    user_id, _ = current_identity()
    if ref["assigned_coach_id"] != user_id:
        raise ApiError(
            "ERR_OWNERSHIP_MISMATCH",
            "Only the assigned coach may perform this action",
        )
    return user_id


@bp.post("/wellness/coaching-referrals/<rid>/sessions")
@require_roles("Coach")
def log_session(rid):
    ref = get_referral_or_404(rid)
    body = parse_body()
    vals = require_fields(body, [
        ("session_date", "date", True),
        ("duration_minutes", "int", True),
    ])
    _require_assigned_coach(ref)  # identity scope (stage 5) before state (stage 6)
    if ref["status"] != "ENGAGED":
        raise ApiError(
            "ERR_INVALID_STATE", "Sessions may only be logged while ENGAGED"
        )
    ref["sessions_completed"] += 1
    ref["session_dates"].append(vals["session_date"].isoformat())
    touch(ref)
    return success(serializers.referral(ref), status=201)


@bp.post("/wellness/coaching-referrals/<rid>/discharge")
@require_roles("Coach")
def discharge_referral(rid):
    ref = get_referral_or_404(rid)
    body = parse_body()
    vals = require_fields(body, [("outcome", "enum", True, _OUTCOMES)])
    _require_assigned_coach(ref)  # identity scope (stage 5) before state (stage 6)
    if ref["status"] != "ENGAGED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an ENGAGED referral may be discharged"
        )
    enr = DB.enrollments[ref["enrollment_id"]]
    program = DB.programs[enr["program_id"]]
    if ref["sessions_completed"] < program["coaching_required_sessions"]:
        raise ApiError(
            "ERR_REFERRAL_SESSIONS_INSUFFICIENT",
            "sessions_completed is below the program's coaching_required_sessions",
        )
    ref["outcome"] = vals["outcome"]
    ref["status"] = "DISCHARGED"
    touch(ref)
    # RA award recompute cascade (PRD §3.6): the referral now stands
    # DISCHARGED with its outcome, so the variant rule reads the true state
    if enr["ra_eligible"] and vals["outcome"] == "GOALS_MET":
        recompute_projected_award_for_enrollment(program, enr)
    return success(serializers.referral(ref))


@bp.post("/wellness/coaching-referrals/<rid>/decline")
@require_roles("Employee")
def decline_referral(rid):
    ref = get_referral_or_404(rid)
    enr = DB.enrollments[ref["enrollment_id"]]
    check_employee_scope(enr)  # identity scope (stage 5) before state (stage 6)
    if ref["status"] != "REFERRED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a REFERRED referral may be declined"
        )
    ref["status"] = "DECLINED"
    touch(ref)
    # declined-then-referred round still blocks RA recompute on later discharge
    ref["_ever_declined"] = True
    return success(serializers.referral(ref))


@bp.post("/wellness/coaching-referrals/<rid>/rerefer")
@require_roles("BenefitsAdmin")
def rerefer_referral(rid):
    ref = get_referral_or_404(rid)
    if ref["status"] not in ("DISCHARGED", "DECLINED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DISCHARGED or DECLINED referral may be re-referred",
        )
    ref["referral_round"] += 1
    ref["sessions_completed"] = 0
    ref["outcome"] = None
    ref["assigned_coach_id"] = None
    ref["status"] = "REFERRED"
    touch(ref)
    return success(serializers.referral(ref))

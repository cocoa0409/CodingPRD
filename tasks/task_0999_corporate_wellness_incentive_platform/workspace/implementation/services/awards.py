"""IncentiveAward endpoints (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint

from db import DB
from errors import ApiError, invalid
from middleware import current_identity, require_roles
from response import success
from services import serializers
from services.cascade import apply_award_amounts, compute_award_amounts
from services.common import (
    get_award_or_404, get_program_or_404, parse_body, require_fields,
    stamp_new, touch,
)
from clock import CLOCK, now_iso

bp = Blueprint("awards", __name__)


@bp.post("/wellness/incentive-awards/compute")
@require_roles("BenefitsAdmin")
def compute_awards():
    body = parse_body()
    vals = require_fields(body, [("program_id", "string", True)])
    program = get_program_or_404(vals["program_id"])
    if program["status"] == "DRAFT":
        raise ApiError(
            "ERR_PROGRAM_NOT_ACTIVE", "Award computation requires ACTIVE or CLOSED"
        )
    if program["status"] == "SETTLED":
        raise ApiError(
            "ERR_PROGRAM_ALREADY_SETTLED",
            "No award computations against a SETTLED program",
        )
    computed_seq = DB.next_seq()
    created = 0
    updated = 0
    for enr in sorted(
        (e for e in DB.enrollments.values() if e["program_id"] == program["id"]),
        key=lambda e: e["created_at"],
    ):
        if enr["participation_status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        existing = next(
            (a for a in DB.awards.values() if a["enrollment_id"] == enr["id"]),
            None,
        )
        amounts = compute_award_amounts(program, enr)
        if existing is None:
            award = stamp_new({
                "enrollment_id": enr["id"],
                "program_id": program["id"],
                **amounts,
                "status": "PROJECTED",
                "confirmed_at": None,
                "dispute_reason": None,
                "_computed_seq": computed_seq,
            })
            DB.awards[award["id"]] = award
            created += 1
        elif existing["status"] == "PROJECTED":
            apply_award_amounts(existing, amounts)
            updated += 1
        # CONFIRMED / APPLIED / DISPUTED awards are left untouched
    return success({"created_count": created, "updated_count": updated})


@bp.post("/wellness/incentive-awards/<aid>/confirm")
@require_roles("BenefitsAdmin")
def confirm_award(aid):
    award = get_award_or_404(aid)
    program = DB.programs[award["program_id"]]
    if program["status"] != "CLOSED":
        raise ApiError(
            "ERR_PROGRAM_NOT_CLOSED", "Confirmation requires program status CLOSED"
        )
    if award["status"] != "PROJECTED":
        raise ApiError(
            "ERR_AWARD_NOT_CONFIRMABLE", "Only a PROJECTED award may be confirmed"
        )
    if award.get("_computed_seq") is None or award["_computed_seq"] < program["_closed_seq"]:
        raise ApiError(
            "ERR_AWARD_NOT_CONFIRMABLE",
            "Award amounts were computed before the latest program close",
        )
    award["status"] = "CONFIRMED"
    award["confirmed_at"] = now_iso()
    award["_confirmed_dt"] = CLOCK.now()
    touch(award)
    return success(serializers.award(award))


@bp.post("/wellness/incentive-awards/<aid>/apply")
@require_roles("BenefitsAdmin")
def apply_award(aid):
    award = get_award_or_404(aid)
    if award["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a CONFIRMED award may be applied"
        )
    award["status"] = "APPLIED"
    touch(award)
    return success(serializers.award(award))


@bp.post("/wellness/incentive-awards/<aid>/dispute")
@require_roles("Employee")
def dispute_award(aid):
    award = get_award_or_404(aid)
    body = parse_body()
    vals = require_fields(body, [("dispute_reason", "string", True)])
    # identity scope (stage 5) precedes state legality (stage 6)
    user_id, _ = current_identity()
    enr = DB.enrollments[award["enrollment_id"]]
    if enr["employee_id"] != user_id:
        raise ApiError(
            "ERR_OWNERSHIP_MISMATCH",
            "Only the award's member may dispute it",
        )
    if award["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a CONFIRMED award may be disputed"
        )
    deadline = award["_confirmed_dt"] + timedelta(days=30)
    if CLOCK.now() > deadline:
        raise ApiError(
            "ERR_APPEAL_WINDOW_CLOSED",
            "Dispute arrived later than confirmed_at + 30 days",
        )
    award["dispute_reason"] = vals["dispute_reason"]
    award["status"] = "DISPUTED"
    touch(award)
    return success(serializers.award(award))


@bp.post("/wellness/incentive-awards/<aid>/resolve")
@require_roles("BenefitsAdmin")
def resolve_award(aid):
    award = get_award_or_404(aid)
    body = parse_body()
    vals = require_fields(body, [
        ("outcome", "enum", True, {"UPHELD", "ADJUSTED"}),
        ("adjusted_award_cents", "int", False),
    ])
    if vals["outcome"] == "ADJUSTED" and "adjusted_award_cents" not in vals:
        raise invalid("adjusted_award_cents is required when outcome is ADJUSTED")
    if award["status"] != "DISPUTED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a DISPUTED award may be resolved"
        )
    if vals["outcome"] == "ADJUSTED":
        award["award_cents"] = vals["adjusted_award_cents"]
        award["net_annual_differential_cents"] = (
            award["surcharge_cents"] - award["award_cents"]
        )
    award["status"] = "CONFIRMED"
    award["confirmed_at"] = now_iso()
    award["_confirmed_dt"] = CLOCK.now()
    touch(award)
    return success(serializers.award(award))

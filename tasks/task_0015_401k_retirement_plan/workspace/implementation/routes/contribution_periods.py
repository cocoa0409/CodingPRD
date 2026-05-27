"""ContributionPeriod resource — create, get, list, close, reverse."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_DEFERRAL_LIMIT_EXCEEDED,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import auth_required
from response import success_array, success_object
from services.calculations import employer_match
from services.clock_and_age import parse_iso
from services.entities import (
    recompute_vested_balance,
    serialize_contribution_period,
    stamp_create,
    stamp_update,
)
from services.validators import require_dict, require_enum, require_int, require_str


bp = Blueprint("contribution_periods", __name__)

CP_STATUSES = {"OPEN", "CLOSED", "REVERSED"}


def _get_cp_or_404(cp_id: str) -> dict:
    cp = db.contribution_periods.get(cp_id)
    if not cp:
        raise APIError(ERR_NOT_FOUND, 404, f"ContributionPeriod '{cp_id}' not found")
    return cp


@bp.post("/contribution-periods")
@auth_required("PlanAdmin")
def create_period():
    body = require_dict(request.get_json(silent=True))
    participant_id = require_str(body, "participant_id")
    period_end_date = require_str(body, "period_end_date")
    gross = require_int(body, "gross_compensation_cents", strictly_positive=True)

    try:
        parse_iso(period_end_date)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "period_end_date must be ISO 8601")

    with db.LOCK:
        if participant_id not in db.participants:
            raise APIError(ERR_NOT_FOUND, 404, f"Participant '{participant_id}' not found")
        cp = stamp_create(
            {
                "participant_id": participant_id,
                "period_end_date": period_end_date,
                "gross_compensation_cents": gross,
                "employee_contribution_cents": 0,
                "employer_match_cents": 0,
                "status": "OPEN",
            }
        )
        db.contribution_periods[cp["id"]] = cp
    return success_object(serialize_contribution_period(cp), status=201)


@bp.get("/contribution-periods/<cp_id>")
@auth_required("PlanAdmin", "Custodian", "Participant")
def get_period(cp_id: str):
    cp = _get_cp_or_404(cp_id)
    if g.user_role == "Participant" and g.user_id != cp["participant_id"]:
        raise APIError(ERR_FORBIDDEN, 403, "Participant may only read own contribution periods")
    return success_object(serialize_contribution_period(cp))


@bp.get("/contribution-periods")
@auth_required("PlanAdmin", "Custodian", "Participant")
def list_periods():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset out of range")
    participant_filter = request.args.get("participant_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in CP_STATUSES:
        raise APIError(ERR_INVALID_REQUEST, 400, "invalid status filter")

    with db.LOCK:
        items = list(db.contribution_periods.values())
    if participant_filter is not None:
        items = [cp for cp in items if cp["participant_id"] == participant_filter]
    if status_filter is not None:
        items = [cp for cp in items if cp["status"] == status_filter]

    # Participant role can only see their own.
    if g.user_role == "Participant":
        items = [cp for cp in items if cp["participant_id"] == g.user_id]

    items.sort(key=lambda cp: cp["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_array(
        [serialize_contribution_period(cp) for cp in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )


# -----------------------------------------------------------------------------
# Close / reverse
# -----------------------------------------------------------------------------


def _ytd_employee_contribs(participant_id: str, plan_year: int, exclude_cp_id: str | None = None) -> int:
    """Sum CLOSED period employee_contribution_cents for this participant in plan_year."""
    total = 0
    for cp in db.contribution_periods.values():
        if cp["participant_id"] != participant_id:
            continue
        if cp["status"] != "CLOSED":
            continue
        if exclude_cp_id is not None and cp["id"] == exclude_cp_id:
            continue
        # period_end_date is a date string; use its year for plan-year alignment.
        try:
            dt = parse_iso(cp["period_end_date"])
            if dt.year != plan_year:
                continue
        except Exception:
            continue
        total += cp["employee_contribution_cents"]
    return total


@bp.post("/contribution-periods/<cp_id>/close")
@auth_required("PlanAdmin")
def close_period(cp_id: str):
    with db.LOCK:
        cp = _get_cp_or_404(cp_id)
        if cp["status"] != "OPEN":
            raise APIError(ERR_INVALID_STATE, 409, "Period is not OPEN")
        participant = db.participants.get(cp["participant_id"])
        if not participant:
            raise APIError(ERR_NOT_FOUND, 404, "Participant referenced by period not found")
        plan = db.plans.get(participant["plan_id"])
        if not plan:
            raise APIError(ERR_NOT_FOUND, 404, "Plan referenced by participant not found")
        if plan["status"] != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409, "Plan must be ACTIVE to close period")
        if participant["enrollment_status"] != "ENROLLED":
            raise APIError(ERR_INVALID_STATE, 409, "Participant must be ENROLLED to close period")

        # Compute match.
        deferral_amt, match_amt = employer_match(
            gross_compensation_cents=cp["gross_compensation_cents"],
            deferral_rate_bps=participant["deferral_rate_bps"],
            annual_compensation_limit_cents=plan["annual_compensation_limit_cents"],
            match_formula=plan["match_formula"],
        )

        # §402(g) cap: cumulative employee contributions in plan_year must not
        # exceed annual_deferral_limit_cents. We compare YTD-already-closed +
        # this period's amount against the cap.
        plan_year = plan["plan_year"]
        ytd = _ytd_employee_contribs(participant["id"], plan_year)
        if (ytd + deferral_amt) > plan["annual_deferral_limit_cents"]:
            raise APIError(
                ERR_DEFERRAL_LIMIT_EXCEEDED,
                422,
                "Closing would exceed §402(g) elective deferral cap",
            )

        cp["employee_contribution_cents"] = deferral_amt
        cp["employer_match_cents"] = match_amt
        cp["status"] = "CLOSED"
        stamp_update(cp)

        # Depth 2 cascades on participant.
        participant["employee_balance_cents"] += deferral_amt
        participant["employer_balance_cents"] += match_amt
        stamp_update(participant)
        # Depth 3 reconciliation.
        recompute_vested_balance(participant)
    return success_object(serialize_contribution_period(cp))


@bp.post("/contribution-periods/<cp_id>/reverse")
@auth_required("PlanAdmin")
def reverse_period(cp_id: str):
    with db.LOCK:
        cp = _get_cp_or_404(cp_id)
        if cp["status"] != "CLOSED":
            raise APIError(ERR_INVALID_STATE, 409, "Period is not CLOSED")
        participant = db.participants.get(cp["participant_id"])
        if not participant:
            raise APIError(ERR_NOT_FOUND, 404, "Participant referenced by period not found")
        plan = db.plans.get(participant["plan_id"])
        if not plan:
            raise APIError(ERR_NOT_FOUND, 404, "Plan referenced by participant not found")
        if plan["status"] != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409, "Plan must be ACTIVE to reverse period")

        deferral_amt = cp["employee_contribution_cents"]
        match_amt = cp["employer_match_cents"]
        cp["status"] = "REVERSED"
        stamp_update(cp)

        participant["employee_balance_cents"] -= deferral_amt
        participant["employer_balance_cents"] -= match_amt
        stamp_update(participant)
        recompute_vested_balance(participant)
    return success_object(serialize_contribution_period(cp))

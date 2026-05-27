"""RMDDistribution resource — create, get, list, pay, mark-missed."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_DUPLICATE_RMD_YEAR,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_JOINT_LIFE_INELIGIBLE,
    ERR_NOT_FOUND,
    ERR_RMD_NOT_REQUIRED,
)
from middleware import auth_required
from response import success_array, success_object
from services.calculations import (
    AGE_RMD_TRIGGER,
    JOINT_LIFE_TABLE,
    UNIFORM_LIFETIME_TABLE,
    _joint_factor,
    joint_life_eligible,
    rmd_required_amount,
)
from services.clock_and_age import age_at_year_end, age_today_years, parse_iso
from services.entities import (
    recompute_vested_balance,
    serialize_rmd,
    stamp_create,
    stamp_update,
)
from services.validators import require_dict, require_enum, require_int, require_str


bp = Blueprint("rmd_distributions", __name__)


RMD_VARIANTS = {"UNIFORM_LIFETIME", "JOINT_LIFE"}
RMD_STATUSES = {"PENDING", "PAID", "MISSED"}


def _get_rmd_or_404(rid: str) -> dict:
    r = db.rmd_distributions.get(rid)
    if not r:
        raise APIError(ERR_NOT_FOUND, 404, f"RMDDistribution '{rid}' not found")
    return r


def _uniform_factor(age: int) -> float | None:
    if age in UNIFORM_LIFETIME_TABLE:
        return UNIFORM_LIFETIME_TABLE[age]
    # If the requested age is beyond the largest tabulated entry, use the
    # smallest factor (oldest entry). For ages between sparse entries that
    # we have not tabulated, fall back to a linear interpolation between
    # the two nearest entries to keep this deterministic.
    sorted_ages = sorted(UNIFORM_LIFETIME_TABLE)
    if age < sorted_ages[0]:
        return None
    if age > sorted_ages[-1]:
        return UNIFORM_LIFETIME_TABLE[sorted_ages[-1]]
    # interpolate
    lower = max(a for a in sorted_ages if a <= age)
    upper = min(a for a in sorted_ages if a >= age)
    if lower == upper:
        return UNIFORM_LIFETIME_TABLE[lower]
    flow = UNIFORM_LIFETIME_TABLE[lower]
    fhigh = UNIFORM_LIFETIME_TABLE[upper]
    return flow + (fhigh - flow) * (age - lower) / (upper - lower)


@bp.post("/rmd-distributions")
@auth_required("PlanAdmin")
def create_rmd():
    body = require_dict(request.get_json(silent=True))
    participant_id = require_str(body, "participant_id")
    distribution_year = require_int(body, "distribution_year", minimum=1900, maximum=2999)
    prior_balance = require_int(body, "prior_year_end_balance_cents", strictly_positive=True)
    variant = require_enum(body, "rmd_variant", RMD_VARIANTS)
    spouse_dob = body.get("spouse_date_of_birth")

    if variant == "JOINT_LIFE":
        if not spouse_dob:
            raise APIError(ERR_INVALID_REQUEST, 400, "spouse_date_of_birth required for JOINT_LIFE")
        try:
            parse_iso(spouse_dob)
        except Exception:
            raise APIError(ERR_INVALID_REQUEST, 400, "spouse_date_of_birth must be ISO 8601")
    else:
        # UNIFORM_LIFETIME — spouse_dob must be null/absent.
        spouse_dob = None

    with db.LOCK:
        if participant_id not in db.participants:
            raise APIError(ERR_NOT_FOUND, 404, f"Participant '{participant_id}' not found")
        participant = db.participants[participant_id]

        # Age gate per §1.4 priority 6.
        participant_age = age_at_year_end(participant["date_of_birth"], distribution_year)
        if participant_age < AGE_RMD_TRIGGER:
            raise APIError(
                ERR_RMD_NOT_REQUIRED,
                422,
                f"Participant age {participant_age} at year-end is below {AGE_RMD_TRIGGER}",
            )

        # Joint-life eligibility (strict > 10 year gap).
        if variant == "JOINT_LIFE":
            spouse_age = age_at_year_end(spouse_dob, distribution_year)
            if not joint_life_eligible(participant_age, spouse_age):
                raise APIError(
                    ERR_JOINT_LIFE_INELIGIBLE,
                    422,
                    "JOINT_LIFE requires spouse more than 10 years younger",
                )
            factor = _joint_factor(participant_age, spouse_age)
        else:
            factor = _uniform_factor(participant_age)
            if factor is None:
                # Age too low for the table — but we've already gated >= 73.
                raise APIError(
                    ERR_RMD_NOT_REQUIRED,
                    422,
                    f"No life expectancy factor for age {participant_age}",
                )

        # Uniqueness on (participant_id, distribution_year).
        for existing in db.rmd_distributions.values():
            if (
                existing["participant_id"] == participant_id
                and existing["distribution_year"] == distribution_year
            ):
                raise APIError(
                    ERR_DUPLICATE_RMD_YEAR,
                    409,
                    f"RMD already exists for ({participant_id}, {distribution_year})",
                )

        required = rmd_required_amount(
            prior_year_end_balance_cents=prior_balance,
            factor=factor,
        )

        r = stamp_create(
            {
                "participant_id": participant_id,
                "distribution_year": distribution_year,
                "prior_year_end_balance_cents": prior_balance,
                "rmd_variant": variant,
                "spouse_date_of_birth": spouse_dob,
                "required_amount_cents": required,
                "distributed_amount_cents": 0,
                "status": "PENDING",
            }
        )
        db.rmd_distributions[r["id"]] = r
    return success_object(serialize_rmd(r), status=201)


@bp.get("/rmd-distributions/<rid>")
@auth_required("PlanAdmin", "Custodian", "Participant")
def get_rmd(rid: str):
    r = _get_rmd_or_404(rid)
    if g.user_role == "Participant" and g.user_id != r["participant_id"]:
        raise APIError(ERR_FORBIDDEN, 403, "Participant may only read own RMD")
    return success_object(serialize_rmd(r))


@bp.get("/rmd-distributions")
@auth_required("PlanAdmin", "Custodian", "Participant")
def list_rmds():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset out of range")
    participant_filter = request.args.get("participant_id")
    status_filter = request.args.get("status")
    year_filter = request.args.get("distribution_year")
    if status_filter is not None and status_filter not in RMD_STATUSES:
        raise APIError(ERR_INVALID_REQUEST, 400, "invalid status filter")
    if year_filter is not None:
        try:
            year_filter = int(year_filter)
        except ValueError:
            raise APIError(ERR_INVALID_REQUEST, 400, "distribution_year filter must be int")

    with db.LOCK:
        items = list(db.rmd_distributions.values())
    if participant_filter is not None:
        items = [r for r in items if r["participant_id"] == participant_filter]
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    if year_filter is not None:
        items = [r for r in items if r["distribution_year"] == year_filter]
    if g.user_role == "Participant":
        items = [r for r in items if r["participant_id"] == g.user_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_array(
        [serialize_rmd(r) for r in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )


@bp.post("/rmd-distributions/<rid>/pay")
@auth_required("PlanAdmin")
def pay_rmd(rid: str):
    body = require_dict(request.get_json(silent=True))
    distributed = require_int(body, "distributed_amount_cents", minimum=0)
    with db.LOCK:
        r = _get_rmd_or_404(rid)
        if r["status"] != "PENDING":
            raise APIError(ERR_INVALID_STATE, 409, "RMD is not PENDING")
        participant = db.participants.get(r["participant_id"])
        if not participant:
            raise APIError(ERR_NOT_FOUND, 404, "Participant not found")
        # Participant age (system clock) >= 73.
        current_age = age_today_years(participant["date_of_birth"])
        if current_age < AGE_RMD_TRIGGER:
            raise APIError(ERR_INVALID_STATE, 409, "Participant is no longer >= 73 by clock")
        if distributed != r["required_amount_cents"]:
            raise APIError(
                ERR_INVALID_STATE,
                409,
                f"distributed_amount_cents ({distributed}) must equal required ({r['required_amount_cents']})",
            )

        r["distributed_amount_cents"] = distributed
        r["status"] = "PAID"
        stamp_update(r)

        # Pro-rata deduction from employee and employer balances.
        ee = participant["employee_balance_cents"]
        er = participant["employer_balance_cents"]
        total_bal = ee + er
        if total_bal > 0:
            # Floor each share; assign any remainder to employer side to keep
            # employee_balance from going negative on the rounding edge.
            ee_share = (distributed * ee) // total_bal
            er_share = distributed - ee_share
        else:
            ee_share = 0
            er_share = 0
        participant["employee_balance_cents"] = ee - ee_share
        participant["employer_balance_cents"] = er - er_share
        stamp_update(participant)
        recompute_vested_balance(participant)
    return success_object(serialize_rmd(r))


@bp.post("/rmd-distributions/<rid>/mark-missed")
@auth_required("PlanAdmin")
def mark_missed_rmd(rid: str):
    with db.LOCK:
        r = _get_rmd_or_404(rid)
        if r["status"] != "PENDING":
            raise APIError(ERR_INVALID_STATE, 409, "RMD is not PENDING")
        r["status"] = "MISSED"
        stamp_update(r)
    return success_object(serialize_rmd(r))

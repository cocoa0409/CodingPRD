"""RMDSchedule service: schedule, fulfill, list."""

import db
from config import (
    PLAN_ACTIVE,
    RMD_SCHEDULED, RMD_FULFILLED,
    UNIFORM_LIFETIME_TABLE,
)
from errors import (
    AppError,
    ERR_INVALID_REQUEST,
    ERR_PLAN_NOT_ACTIVE,
    ERR_RMD_NOT_YET_REQUIRED,
    ERR_DUPLICATE_RMD_YEAR,
    ERR_RMD_NOT_SCHEDULED,
    ERR_RMD_UNDERPAID,
    ERR_RMD_PAST_DUE,
)
from utils import stamp_create, bump_version, parse_date
from services.occ import check_version
from services.calculations import rmd_required_amount_cents
from services.vesting import get_current_date_for_plan


def _ensure_plan_active(plan: dict) -> None:
    if plan["status"] != PLAN_ACTIVE:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE.", 409)


def schedule_rmd(plan: dict, participant: dict, payload: dict) -> dict:
    _ensure_plan_active(plan)
    if not isinstance(payload, dict):
        raise AppError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    rmd_year = payload.get("rmd_year")
    if not isinstance(rmd_year, int) or isinstance(rmd_year, bool):
        raise AppError(ERR_INVALID_REQUEST, "rmd_year must be an integer.", 400)

    dob = parse_date(participant.get("date_of_birth", ""))
    if dob is None:
        raise AppError(ERR_INVALID_REQUEST, "Participant has invalid date_of_birth.", 400)
    age_attained = rmd_year - dob.year
    if age_attained < int(plan.get("rmd_age", 73)):
        raise AppError(ERR_RMD_NOT_YET_REQUIRED,
                       "Participant has not yet reached the plan's RMD age.", 422)

    # Uniqueness
    existing_for_year = [r for r in db.rmd_schedules.values()
                         if r.get("plan_id") == plan["id"]
                         and r.get("participant_id") == participant["id"]
                         and r.get("rmd_year") == rmd_year]
    if existing_for_year:
        raise AppError(ERR_DUPLICATE_RMD_YEAR,
                       "An RMD schedule already exists for this rmd_year.", 409)

    prior_balance = int(participant.get("total_account_balance_cents", 0))
    factor = UNIFORM_LIFETIME_TABLE.get(int(age_attained))
    if factor is None:
        # For ages beyond the table top, clamp to the deepest entry; for ages below,
        # the RMD_NOT_YET_REQUIRED branch above will have caught it.
        if age_attained > max(UNIFORM_LIFETIME_TABLE.keys()):
            factor = UNIFORM_LIFETIME_TABLE[max(UNIFORM_LIFETIME_TABLE.keys())]
        else:
            factor = UNIFORM_LIFETIME_TABLE[min(UNIFORM_LIFETIME_TABLE.keys())]
    required = rmd_required_amount_cents(prior_balance, age_attained)

    # First-year RMD logic
    has_prior = any(
        r.get("plan_id") == plan["id"] and r.get("participant_id") == participant["id"]
        for r in db.rmd_schedules.values()
    )
    is_first_year = (age_attained == int(plan.get("rmd_age", 73)) and not has_prior)
    if is_first_year:
        due_date = f"{rmd_year + 1:04d}-04-01"
    else:
        due_date = f"{rmd_year:04d}-12-31"

    r = {
        "plan_id": plan["id"],
        "participant_id": participant["id"],
        "rmd_year": int(rmd_year),
        "prior_year_end_balance_cents": prior_balance,
        "distribution_period_factor": float(factor),
        "required_amount_cents": int(required),
        "due_date": due_date,
        "distributed_amount_cents": 0,
        "status": RMD_SCHEDULED,
    }
    stamp_create(r)
    db.rmd_schedules[r["id"]] = r
    return r


def fulfill_rmd(plan: dict, participant: dict, r: dict, body: dict | None) -> dict:
    _ensure_plan_active(plan)
    if r["status"] != RMD_SCHEDULED:
        raise AppError(ERR_RMD_NOT_SCHEDULED,
                       "RMD is not in SCHEDULED status.", 409)
    if not isinstance(body, dict):
        raise AppError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    distributed = body.get("distributed_amount_cents")
    if not isinstance(distributed, int) or isinstance(distributed, bool) or distributed < 0:
        raise AppError(ERR_INVALID_REQUEST,
                       "distributed_amount_cents must be a non-negative integer.", 400)
    if distributed < int(r["required_amount_cents"]):
        raise AppError(ERR_RMD_UNDERPAID,
                       "Distributed amount is less than required_amount_cents.", 422)

    current_date = get_current_date_for_plan(plan)
    if current_date is None:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan clock not initialized.", 409)
    if current_date > r["due_date"]:
        raise AppError(ERR_RMD_PAST_DUE,
                       "RMD due_date has passed.", 422)

    check_version(body, r)

    r["distributed_amount_cents"] = int(distributed)
    r["status"] = RMD_FULFILLED
    bump_version(r)

    participant["total_account_balance_cents"] = \
        int(participant.get("total_account_balance_cents", 0)) - int(distributed)
    bump_version(participant)
    return r


def list_rmds(plan: dict, participant: dict, limit: int, offset: int):
    items = [r for r in db.rmd_schedules.values()
             if r.get("plan_id") == plan["id"] and r.get("participant_id") == participant["id"]]
    items.sort(key=lambda r: r.get("created_at", ""))
    total = len(items)
    return items[offset:offset + limit], total

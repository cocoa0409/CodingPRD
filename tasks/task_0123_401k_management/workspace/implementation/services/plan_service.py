"""Plan-level CRUD and lifecycle: create/list/get/activate/freeze/advance-vesting-epoch/_clock/advance."""

from copy import deepcopy

import db
from config import (
    PLAN_DRAFT, PLAN_ACTIVE, PLAN_FROZEN,
    MATCH_SAFE_HARBOR, MATCH_TIERED,
    VESTING_CLIFF, VESTING_GRADED,
    DEFAULT_RMD_AGE, INDEFINITE_SUSPEND_DATE,
    PARTICIPANT_ENROLLED, PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED,
    LOAN_ACTIVE, LOAN_DEFAULTED, LOAN_SATISFIED, LOAN_REQUESTED,
    HARDSHIP_REQUESTED,
    RMD_SCHEDULED, RMD_MISSED,
    LOAN_DEFAULT_GRACE_DAYS,
)
from errors import (
    AppError,
    ERR_INVALID_PLAN_CONFIG, ERR_INVALID_REQUEST,
    ERR_PLAN_NOT_DRAFT, ERR_PLAN_NOT_ACTIVE,
    ERR_FREEZE_PRECONDITION_VIOLATED,
    ERR_CLOCK_NOT_MONOTONIC,
)
from utils import (
    new_id, today_utc_str, stamp_create, stamp_ledger_create, bump_version,
    parse_date, add_days,
)
from services.occ import check_version


# ---------------------------------------------------------------------------
# Validation of plan-config consistency
# ---------------------------------------------------------------------------
def _validate_plan_config(payload: dict) -> None:
    """Per §2.11 / §3.1 — config must be internally consistent.

    Raises ERR_INVALID_PLAN_CONFIG (400) on mismatch.
    """
    mft = payload.get("match_formula_type")
    if mft == MATCH_TIERED:
        brackets = payload.get("tiered_brackets")
        if not isinstance(brackets, list) or len(brackets) == 0:
            raise AppError(ERR_INVALID_PLAN_CONFIG,
                           "tiered_brackets must be a non-empty array when TIERED.", 400)
        # validate ordering and shape
        prev = -1.0
        for b in brackets:
            if not isinstance(b, dict):
                raise AppError(ERR_INVALID_PLAN_CONFIG,
                               "tiered_brackets entries must be objects.", 400)
            up_to = b.get("employee_deferral_pct_up_to")
            rate = b.get("match_rate_pct")
            if up_to is None or rate is None:
                raise AppError(ERR_INVALID_PLAN_CONFIG,
                               "tiered_brackets entries need employee_deferral_pct_up_to and match_rate_pct.", 400)
            try:
                up_to_f = float(up_to)
                float(rate)
            except (TypeError, ValueError):
                raise AppError(ERR_INVALID_PLAN_CONFIG,
                               "tiered_brackets numeric fields must be numbers.", 400)
            if up_to_f <= prev:
                raise AppError(ERR_INVALID_PLAN_CONFIG,
                               "tiered_brackets must be strictly ascending by employee_deferral_pct_up_to.", 400)
            prev = up_to_f

    vst = payload.get("vesting_schedule_type")
    if vst == VESTING_CLIFF:
        cliff = payload.get("cliff_years")
        if not isinstance(cliff, int) or isinstance(cliff, bool) or cliff < 1:
            raise AppError(ERR_INVALID_PLAN_CONFIG,
                           "cliff_years must be an integer ≥ 1 when CLIFF.", 400)
    elif vst == VESTING_GRADED:
        graded = payload.get("graded_percentages")
        if not isinstance(graded, list) or len(graded) != 7:
            raise AppError(ERR_INVALID_PLAN_CONFIG,
                           "graded_percentages must be an array of length 7 when GRADED.", 400)
        prev = -1
        for i, v in enumerate(graded):
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 100:
                raise AppError(ERR_INVALID_PLAN_CONFIG,
                               "graded_percentages entries must be integers in [0..100].", 400)
            if v < prev:
                raise AppError(ERR_INVALID_PLAN_CONFIG,
                               "graded_percentages must be non-decreasing.", 400)
            prev = v
        if graded[6] != 100:
            raise AppError(ERR_INVALID_PLAN_CONFIG,
                           "graded_percentages[6] must equal 100.", 400)


def _basic_payload_validation(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise AppError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    required = ["plan_name", "plan_year", "match_formula_type", "vesting_schedule_type"]
    for r in required:
        if r not in payload or payload.get(r) in (None, ""):
            raise AppError(ERR_INVALID_REQUEST, f"Missing required field: {r}.", 400)
    if not isinstance(payload.get("plan_name"), str):
        raise AppError(ERR_INVALID_REQUEST, "plan_name must be a string.", 400)
    if not isinstance(payload.get("plan_year"), int) or isinstance(payload.get("plan_year"), bool):
        raise AppError(ERR_INVALID_REQUEST, "plan_year must be an integer.", 400)
    if payload["match_formula_type"] not in (MATCH_SAFE_HARBOR, MATCH_TIERED):
        raise AppError(ERR_INVALID_REQUEST, "match_formula_type must be SAFE_HARBOR_BASIC or TIERED.", 400)
    if payload["vesting_schedule_type"] not in (VESTING_CLIFF, VESTING_GRADED):
        raise AppError(ERR_INVALID_REQUEST, "vesting_schedule_type must be CLIFF or GRADED.", 400)
    rmd_age = payload.get("rmd_age")
    if rmd_age is not None and (not isinstance(rmd_age, int) or isinstance(rmd_age, bool) or rmd_age < 1):
        raise AppError(ERR_INVALID_REQUEST, "rmd_age must be a positive integer.", 400)


# ---------------------------------------------------------------------------
# Create plan
# ---------------------------------------------------------------------------
def create_plan(payload: dict) -> dict:
    _basic_payload_validation(payload)
    _validate_plan_config(payload)

    plan = {
        "plan_name": payload["plan_name"],
        "plan_year": int(payload["plan_year"]),
        "match_formula_type": payload["match_formula_type"],
        "tiered_brackets": deepcopy(payload.get("tiered_brackets")) if payload["match_formula_type"] == MATCH_TIERED else None,
        "vesting_schedule_type": payload["vesting_schedule_type"],
        "cliff_years": int(payload["cliff_years"]) if payload["vesting_schedule_type"] == VESTING_CLIFF else None,
        "graded_percentages": list(payload["graded_percentages"]) if payload["vesting_schedule_type"] == VESTING_GRADED else None,
        "rmd_age": int(payload["rmd_age"]) if payload.get("rmd_age") is not None else DEFAULT_RMD_AGE,
        "current_vesting_epoch": 0,
        "status": PLAN_DRAFT,
    }
    stamp_create(plan)
    db.plans[plan["id"]] = plan
    return plan


# ---------------------------------------------------------------------------
# List plans
# ---------------------------------------------------------------------------
def list_plans(limit: int, offset: int):
    items = sorted(db.plans.values(), key=lambda p: p.get("created_at", ""))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Activate plan: DRAFT -> ACTIVE
# ---------------------------------------------------------------------------
def activate_plan(plan: dict, body: dict | None) -> dict:
    if plan["status"] != PLAN_DRAFT:
        raise AppError(ERR_PLAN_NOT_DRAFT, "Plan is not in DRAFT.", 409)
    # Re-validate config at activation time
    _validate_plan_config(plan)
    check_version(body or {}, plan)

    plan["status"] = PLAN_ACTIVE
    bump_version(plan)

    # Side effect: create PlanClock with current_date = today's UTC date
    clock = {
        "plan_id": plan["id"],
        "current_date": today_utc_str(),
    }
    stamp_ledger_create(clock)
    db.plan_clocks[plan["id"]] = clock
    return plan


# ---------------------------------------------------------------------------
# Freeze plan: ACTIVE -> FROZEN
# ---------------------------------------------------------------------------
def freeze_plan(plan: dict, body: dict | None) -> dict:
    if plan["status"] != PLAN_ACTIVE:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan is not in ACTIVE.", 409)
    check_version(body or {}, plan)

    clock = db.plan_clocks.get(plan["id"])
    current_date = clock["current_date"] if clock else today_utc_str()

    # Preconditions:
    # 1) No ACTIVE Loan with outstanding>0
    for loan in db.loans.values():
        if loan.get("plan_id") == plan["id"] and loan.get("status") == LOAN_ACTIVE \
           and int(loan.get("outstanding_principal_cents", 0)) > 0:
            raise AppError(ERR_FREEZE_PRECONDITION_VIOLATED,
                           "Outstanding active loans prevent freeze.", 409)
    # 2) No HardshipWithdrawal in REQUESTED
    for h in db.hardship_withdrawals.values():
        if h.get("plan_id") == plan["id"] and h.get("status") == HARDSHIP_REQUESTED:
            raise AppError(ERR_FREEZE_PRECONDITION_VIOLATED,
                           "Pending hardship requests prevent freeze.", 409)
    # 3) No RMDSchedule SCHEDULED with due_date < current_date
    for r in db.rmd_schedules.values():
        if r.get("plan_id") == plan["id"] and r.get("status") == RMD_SCHEDULED \
           and r.get("due_date", "") < current_date:
            raise AppError(ERR_FREEZE_PRECONDITION_VIOLATED,
                           "Overdue scheduled RMDs prevent freeze.", 409)

    plan["status"] = PLAN_FROZEN
    bump_version(plan)

    # Side effect: flip every ENROLLED|ACTIVE participant to SUSPENDED + indefinite suspension
    for p in db.participants.values():
        if p.get("plan_id") != plan["id"]:
            continue
        if p.get("status") in (PARTICIPANT_ENROLLED, PARTICIPANT_ACTIVE):
            p["status"] = PARTICIPANT_SUSPENDED
            p["deferral_suspended_until"] = INDEFINITE_SUSPEND_DATE
            bump_version(p)
    return plan


# ---------------------------------------------------------------------------
# advance-vesting-epoch
# ---------------------------------------------------------------------------
def advance_vesting_epoch(plan: dict, body: dict | None) -> dict:
    check_version(body or {}, plan)
    plan["current_vesting_epoch"] = int(plan.get("current_vesting_epoch", 0)) + 1
    bump_version(plan)
    return plan


# ---------------------------------------------------------------------------
# _clock/advance
# ---------------------------------------------------------------------------
def advance_clock(plan: dict, body: dict | None) -> dict:
    if plan["status"] != PLAN_ACTIVE:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan is not ACTIVE.", 409)
    if not isinstance(body, dict):
        raise AppError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    new_date = body.get("new_date")
    if not isinstance(new_date, str) or parse_date(new_date) is None:
        raise AppError(ERR_INVALID_REQUEST, "new_date must be YYYY-MM-DD.", 400)

    clock = db.plan_clocks.get(plan["id"])
    if clock is None:
        # Shouldn't happen for ACTIVE plans, but be defensive
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan clock not initialized.", 409)

    # OCC on Plan (clock has no version, but PRD allows version on advance per scaffold)
    check_version(body, plan)

    current_date = clock["current_date"]
    if not (new_date > current_date):
        raise AppError(ERR_CLOCK_NOT_MONOTONIC,
                       "new_date must be strictly greater than current_date.", 422)

    # Apply the advance
    clock["current_date"] = new_date

    # 1) Walk loans: ACTIVE && next_due_date + 90 < new_date && outstanding>0 → DEFAULTED
    for loan in list(db.loans.values()):
        if loan.get("plan_id") != plan["id"]:
            continue
        if loan.get("status") != LOAN_ACTIVE:
            continue
        if int(loan.get("outstanding_principal_cents", 0)) <= 0:
            continue
        nd = loan.get("next_due_date")
        if not nd:
            continue
        threshold = add_days(nd, LOAN_DEFAULT_GRACE_DAYS)
        # condition is "+90 days < new_date" → threshold < new_date
        if threshold < new_date:
            _default_loan(loan)

    # 2) Walk RMDSchedules: SCHEDULED && due_date < new_date → MISSED
    for r in list(db.rmd_schedules.values()):
        if r.get("plan_id") != plan["id"]:
            continue
        if r.get("status") != RMD_SCHEDULED:
            continue
        if r.get("due_date", "") < new_date:
            r["status"] = RMD_MISSED
            bump_version(r)

    # 3) Walk Participants: SUSPENDED && deferral_suspended_until < new_date → ACTIVE
    for p in list(db.participants.values()):
        if p.get("plan_id") != plan["id"]:
            continue
        if p.get("status") != PARTICIPANT_SUSPENDED:
            continue
        dsu = p.get("deferral_suspended_until")
        if dsu and dsu < new_date:
            p["status"] = PARTICIPANT_ACTIVE
            p["deferral_suspended_until"] = None
            bump_version(p)
    return clock


def _default_loan(loan: dict) -> None:
    """Cascade: ACTIVE → DEFAULTED."""
    participant_id = loan["participant_id"]
    participant = db.participants.get(participant_id)
    outstanding = int(loan.get("outstanding_principal_cents", 0))

    loan["status"] = LOAN_DEFAULTED
    if participant is not None:
        new_bal = int(participant.get("total_account_balance_cents", 0)) - outstanding
        participant["total_account_balance_cents"] = new_bal
        # Mark snapshot stale per §2.12: vesting_epoch_at_snapshot = -1
        participant["vesting_epoch_at_snapshot"] = -1
        bump_version(participant)
    loan["outstanding_principal_cents"] = 0
    bump_version(loan)

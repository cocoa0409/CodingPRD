"""Participant CRUD + lifecycle + deferral update."""

from decimal import Decimal, InvalidOperation

import db
from config import (
    PARTICIPANT_ENROLLED, PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED, PARTICIPANT_TERMINATED,
    PLAN_ACTIVE, LOAN_ACTIVE,
    RMD_SCHEDULED, RMD_MISSED,
)
from errors import (
    AppError,
    ERR_INVALID_REQUEST,
    ERR_PLAN_NOT_ACTIVE,
    ERR_PLAN_FROZEN,
    ERR_PARTICIPANT_NOT_IN_VALID_STATE,
)
from utils import stamp_create, bump_version, parse_date
from services.occ import check_version


def _ensure_plan_active(plan: dict) -> None:
    """Guard for any participant-side mutation; FROZEN is also rejected."""
    if plan["status"] != PLAN_ACTIVE:
        # Frozen plan → ERR_PLAN_NOT_ACTIVE per §2.6 priority 4
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE.", 409)


def _validate_enroll_payload(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise AppError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    required = ["employee_external_id", "date_of_birth", "hire_date",
                "annual_compensation_cents", "elected_deferral_pct"]
    for r in required:
        if r not in payload or payload.get(r) is None:
            raise AppError(ERR_INVALID_REQUEST, f"Missing required field: {r}.", 400)
    if not isinstance(payload["employee_external_id"], str) or not payload["employee_external_id"]:
        raise AppError(ERR_INVALID_REQUEST, "employee_external_id must be non-empty string.", 400)
    if parse_date(payload["date_of_birth"]) is None:
        raise AppError(ERR_INVALID_REQUEST, "date_of_birth must be YYYY-MM-DD.", 400)
    if parse_date(payload["hire_date"]) is None:
        raise AppError(ERR_INVALID_REQUEST, "hire_date must be YYYY-MM-DD.", 400)
    if not isinstance(payload["annual_compensation_cents"], int) \
            or isinstance(payload["annual_compensation_cents"], bool) \
            or payload["annual_compensation_cents"] < 0:
        raise AppError(ERR_INVALID_REQUEST, "annual_compensation_cents must be a non-negative integer.", 400)
    pct = payload["elected_deferral_pct"]
    if isinstance(pct, bool):
        raise AppError(ERR_INVALID_REQUEST, "elected_deferral_pct must be numeric.", 400)
    if not isinstance(pct, (int, float)):
        raise AppError(ERR_INVALID_REQUEST, "elected_deferral_pct must be numeric.", 400)
    if pct < 0 or pct > 100:
        raise AppError(ERR_INVALID_REQUEST, "elected_deferral_pct must be in [0, 100].", 400)


def enroll(plan: dict, payload: dict) -> dict:
    _ensure_plan_active(plan)
    _validate_enroll_payload(payload)

    # Uniqueness of employee_external_id within plan
    ext_id = payload["employee_external_id"]
    for p in db.participants.values():
        if p.get("plan_id") == plan["id"] and p.get("employee_external_id") == ext_id:
            raise AppError(ERR_INVALID_REQUEST,
                           "employee_external_id is not unique within plan.", 400)

    participant = {
        "plan_id": plan["id"],
        "employee_external_id": ext_id,
        "date_of_birth": payload["date_of_birth"],
        "hire_date": payload["hire_date"],
        "annual_compensation_cents": int(payload["annual_compensation_cents"]),
        "elected_deferral_pct": float(payload["elected_deferral_pct"]),
        "deferral_suspended_until": None,
        "vested_pct_snapshot": 0.0,
        "vesting_epoch_at_snapshot": 0,
        "cumulative_employee_contribution_cents": 0,
        "cumulative_employer_match_cents": 0,
        "total_account_balance_cents": 0,
        "status": PARTICIPANT_ENROLLED,
    }
    stamp_create(participant)
    db.participants[participant["id"]] = participant
    return participant


def list_participants(plan: dict, limit: int, offset: int, status_filter: str | None):
    items = [p for p in db.participants.values() if p.get("plan_id") == plan["id"]]
    if status_filter:
        items = [p for p in items if p.get("status") == status_filter]
    items.sort(key=lambda p: p.get("created_at", ""))
    total = len(items)
    return items[offset:offset + limit], total


def activate_participant(plan: dict, participant: dict, body: dict | None) -> dict:
    _ensure_plan_active(plan)
    if participant["status"] != PARTICIPANT_ENROLLED:
        raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                       "Participant must be ENROLLED to activate.", 409)
    check_version(body or {}, participant)
    participant["status"] = PARTICIPANT_ACTIVE
    bump_version(participant)
    return participant


def terminate_participant(plan: dict, participant: dict, body: dict | None) -> dict:
    _ensure_plan_active(plan)
    if participant["status"] not in (PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED):
        raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                       "Participant cannot be terminated from current state.", 409)
    # Must have no ACTIVE loan
    for loan in db.loans.values():
        if loan.get("plan_id") == plan["id"] and loan.get("participant_id") == participant["id"] \
                and loan.get("status") == LOAN_ACTIVE:
            raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                           "Participant has an outstanding ACTIVE loan.", 409)
    check_version(body or {}, participant)

    source = participant["status"]
    participant["status"] = PARTICIPANT_TERMINATED
    bump_version(participant)

    if source == PARTICIPANT_ACTIVE:
        # Cascade: flip overdue SCHEDULED RMDs → MISSED
        clock = db.plan_clocks.get(plan["id"])
        current_date = clock["current_date"] if clock else None
        if current_date is not None:
            for r in db.rmd_schedules.values():
                if r.get("plan_id") != plan["id"]:
                    continue
                if r.get("participant_id") != participant["id"]:
                    continue
                if r.get("status") != RMD_SCHEDULED:
                    continue
                if r.get("due_date", "") < current_date:
                    r["status"] = RMD_MISSED
                    bump_version(r)
    return participant


def update_deferral(plan: dict, participant: dict, body: dict) -> dict:
    _ensure_plan_active(plan)
    if not isinstance(body, dict):
        raise AppError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    if "elected_deferral_pct" not in body or body["elected_deferral_pct"] is None:
        raise AppError(ERR_INVALID_REQUEST, "elected_deferral_pct required.", 400)
    pct = body["elected_deferral_pct"]
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise AppError(ERR_INVALID_REQUEST, "elected_deferral_pct must be numeric.", 400)
    if pct < 0 or pct > 100:
        raise AppError(ERR_INVALID_REQUEST, "elected_deferral_pct must be in [0, 100].", 400)
    check_version(body, participant)

    # Deferral update doesn't have a strong participant-state precondition in the PRD, but
    # PRD §2.6 priority 5 says the participant must be in a valid state for the operation.
    # Updating deferral on a TERMINATED participant is nonsensical.
    if participant["status"] == PARTICIPANT_TERMINATED:
        raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                       "Cannot update deferral on a TERMINATED participant.", 409)

    participant["elected_deferral_pct"] = float(pct)
    bump_version(participant)
    return participant

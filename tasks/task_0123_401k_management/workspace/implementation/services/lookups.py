"""Left-to-right path-resource lookups (PRD §2.5)."""

import db
from errors import (
    AppError,
    ERR_PLAN_NOT_FOUND,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_LOAN_NOT_FOUND,
    ERR_HARDSHIP_NOT_FOUND,
    ERR_RMD_NOT_FOUND,
)


def get_plan(plan_id: str) -> dict:
    plan = db.plans.get(plan_id)
    if plan is None:
        raise AppError(ERR_PLAN_NOT_FOUND, "Plan not found.", 404)
    return plan


def get_participant(plan_id: str, participant_id: str) -> dict:
    # plan must be looked up first (caller does this) to satisfy left-to-right
    p = db.participants.get(participant_id)
    if p is None or p.get("plan_id") != plan_id:
        raise AppError(ERR_PARTICIPANT_NOT_FOUND, "Participant not found.", 404)
    return p


def get_loan(plan_id: str, participant_id: str, loan_id: str) -> dict:
    loan = db.loans.get(loan_id)
    if loan is None or loan.get("plan_id") != plan_id or loan.get("participant_id") != participant_id:
        raise AppError(ERR_LOAN_NOT_FOUND, "Loan not found.", 404)
    return loan


def get_hardship(plan_id: str, participant_id: str, withdrawal_id: str) -> dict:
    h = db.hardship_withdrawals.get(withdrawal_id)
    if h is None or h.get("plan_id") != plan_id or h.get("participant_id") != participant_id:
        raise AppError(ERR_HARDSHIP_NOT_FOUND, "Hardship withdrawal not found.", 404)
    return h


def get_rmd(plan_id: str, participant_id: str, schedule_id: str) -> dict:
    r = db.rmd_schedules.get(schedule_id)
    if r is None or r.get("plan_id") != plan_id or r.get("participant_id") != participant_id:
        raise AppError(ERR_RMD_NOT_FOUND, "RMD schedule not found.", 404)
    return r


def resolve_plan_path(plan_id: str) -> dict:
    return get_plan(plan_id)


def resolve_participant_path(plan_id: str, participant_id: str):
    plan = get_plan(plan_id)
    participant = get_participant(plan_id, participant_id)
    return plan, participant


def resolve_loan_path(plan_id: str, participant_id: str, loan_id: str):
    plan = get_plan(plan_id)
    participant = get_participant(plan_id, participant_id)
    loan = get_loan(plan_id, participant_id, loan_id)
    return plan, participant, loan


def resolve_hardship_path(plan_id: str, participant_id: str, withdrawal_id: str):
    plan = get_plan(plan_id)
    participant = get_participant(plan_id, participant_id)
    h = get_hardship(plan_id, participant_id, withdrawal_id)
    return plan, participant, h


def resolve_rmd_path(plan_id: str, participant_id: str, schedule_id: str):
    plan = get_plan(plan_id)
    participant = get_participant(plan_id, participant_id)
    r = get_rmd(plan_id, participant_id, schedule_id)
    return plan, participant, r

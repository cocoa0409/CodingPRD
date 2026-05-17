"""HardshipWithdrawal service: request, approve, deny, list."""

import db
from config import (
    PLAN_ACTIVE,
    PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED,
    HARDSHIP_REQUESTED, HARDSHIP_APPROVED, HARDSHIP_DENIED,
    HARDSHIP_REASONS, HARDSHIP_SUSPENSION_DAYS,
    LOAN_REQUESTED,
)
from errors import (
    AppError,
    ERR_INVALID_REQUEST,
    ERR_PLAN_NOT_ACTIVE,
    ERR_PARTICIPANT_NOT_IN_VALID_STATE,
    ERR_HARDSHIP_NOT_REQUESTED,
    ERR_INSUFFICIENT_VESTED_BALANCE,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from utils import stamp_create, bump_version, add_days
from services.occ import check_version
from services.calculations import vested_percent, vested_balance_cents
from services.vesting import get_current_date_for_plan
from services import sod


def _ensure_plan_active(plan: dict) -> None:
    if plan["status"] != PLAN_ACTIVE:
        raise AppError(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE.", 409)


def request_hardship(plan: dict, participant: dict, payload: dict,
                     actor_user_id: str) -> dict:
    _ensure_plan_active(plan)
    if participant["status"] not in (PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED):
        raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                       "Participant must be ACTIVE or SUSPENDED.", 409)
    if not isinstance(payload, dict):
        raise AppError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    requested = payload.get("requested_amount_cents")
    reason = payload.get("hardship_reason_code")
    if not isinstance(requested, int) or isinstance(requested, bool) or requested <= 0:
        raise AppError(ERR_INSUFFICIENT_VESTED_BALANCE,
                       "requested_amount_cents must be positive.", 422)
    if reason not in HARDSHIP_REASONS:
        raise AppError(ERR_INVALID_REQUEST,
                       "hardship_reason_code must be one of MEDICAL/EDUCATION/PRIMARY_RESIDENCE/FUNERAL/EVICTION.", 400)

    current_date = get_current_date_for_plan(plan)
    pct = vested_percent(plan, participant, current_date) if current_date else 0.0
    vested_at = vested_balance_cents(int(participant.get("total_account_balance_cents", 0)), pct)
    if vested_at <= 0:
        raise AppError(ERR_INSUFFICIENT_VESTED_BALANCE,
                       "Vested balance is zero.", 422)

    h = {
        "plan_id": plan["id"],
        "participant_id": participant["id"],
        "requested_amount_cents": int(requested),
        "hardship_reason_code": reason,
        "approved_amount_cents": None,
        "vested_balance_cents_at_request": int(vested_at),
        "status": HARDSHIP_REQUESTED,
    }
    stamp_create(h)
    db.hardship_withdrawals[h["id"]] = h

    sod.record_hardship_request(actor_user_id, plan["id"], h["id"], participant["id"])
    return h


def approve_hardship(plan: dict, participant: dict, h: dict, body: dict | None,
                     actor_user_id: str) -> dict:
    _ensure_plan_active(plan)
    if participant["status"] not in (PARTICIPANT_ACTIVE, PARTICIPANT_SUSPENDED):
        raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                       "Participant must be ACTIVE or SUSPENDED.", 409)
    if h["status"] != HARDSHIP_REQUESTED:
        raise AppError(ERR_HARDSHIP_NOT_REQUESTED,
                       "Hardship is not in REQUESTED status.", 409)

    # SoD: requester may not approve
    if sod.has_user_requested_hardship(actor_user_id, plan["id"], h["id"]):
        raise AppError(ERR_INSUFFICIENT_PERMISSIONS,
                       "Segregation-of-duties: requester may not approve their own hardship.", 403)

    # Precondition: participant has no Loan in REQUESTED status
    for l in db.loans.values():
        if l.get("plan_id") == plan["id"] and l.get("participant_id") == participant["id"] \
                and l.get("status") == LOAN_REQUESTED:
            raise AppError(ERR_PARTICIPANT_NOT_IN_VALID_STATE,
                           "Participant has an outstanding loan request.", 409)

    if int(h.get("vested_balance_cents_at_request", 0)) <= 0:
        raise AppError(ERR_INSUFFICIENT_VESTED_BALANCE,
                       "Vested balance at request is zero.", 422)

    check_version(body or {}, h)

    approved = min(int(h["requested_amount_cents"]),
                   int(h["vested_balance_cents_at_request"]))
    h["approved_amount_cents"] = approved
    h["status"] = HARDSHIP_APPROVED
    bump_version(h)

    # Cascade hop 1 — debit participant balance
    participant["total_account_balance_cents"] = \
        int(participant.get("total_account_balance_cents", 0)) - approved

    # Cascade hop 2 — Participant ACTIVE → SUSPENDED with 180-day suspension
    current_date = get_current_date_for_plan(plan)
    if current_date is not None:
        participant["deferral_suspended_until"] = add_days(current_date, HARDSHIP_SUSPENSION_DAYS)
    participant["status"] = PARTICIPANT_SUSPENDED
    bump_version(participant)
    return h


def deny_hardship(plan: dict, participant: dict, h: dict, body: dict | None) -> dict:
    _ensure_plan_active(plan)
    if h["status"] != HARDSHIP_REQUESTED:
        raise AppError(ERR_HARDSHIP_NOT_REQUESTED,
                       "Hardship is not in REQUESTED status.", 409)
    check_version(body or {}, h)
    h["approved_amount_cents"] = 0
    h["status"] = HARDSHIP_DENIED
    bump_version(h)
    return h


def list_hardships(plan: dict, participant: dict, limit: int, offset: int,
                   status_filter: str | None):
    items = [x for x in db.hardship_withdrawals.values()
             if x.get("plan_id") == plan["id"] and x.get("participant_id") == participant["id"]]
    if status_filter:
        items = [x for x in items if x.get("status") == status_filter]
    items.sort(key=lambda x: x.get("created_at", ""))
    total = len(items)
    return items[offset:offset + limit], total

"""HardshipWithdrawal resource — create, get, list, approve, deny, pay."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_HARDSHIP_HEADROOM,
    ERR_NOT_FOUND,
)
from middleware import auth_required
from response import success_array, success_object
from services.calculations import max_hardship_amount
from services.clock_and_age import age_today_years
from services.entities import (
    recompute_vested_balance,
    serialize_hardship,
    stamp_create,
    stamp_update,
)
from services.validators import require_dict, require_enum, require_int, require_str


bp = Blueprint("hardships", __name__)


HARDSHIP_CATEGORIES = {
    "MEDICAL_EXPENSES",
    "PRIMARY_RESIDENCE_PURCHASE",
    "TUITION_PAYMENT",
    "EVICTION_PREVENTION",
    "FUNERAL_EXPENSES",
}
HARDSHIP_STATUSES = {"REQUESTED", "APPROVED", "DENIED", "PAID"}


def _get_hw_or_404(hid: str) -> dict:
    h = db.hardship_withdrawals.get(hid)
    if not h:
        raise APIError(ERR_NOT_FOUND, 404, f"HardshipWithdrawal '{hid}' not found")
    return h


@bp.post("/hardship-withdrawals")
@auth_required("PlanAdmin", "Participant")
def create_hardship():
    body = require_dict(request.get_json(silent=True))
    participant_id = require_str(body, "participant_id")
    requested = require_int(body, "requested_amount_cents", strictly_positive=True)
    category = require_enum(body, "hardship_category", HARDSHIP_CATEGORIES)

    with db.LOCK:
        if participant_id not in db.participants:
            raise APIError(ERR_NOT_FOUND, 404, f"Participant '{participant_id}' not found")
        if g.user_role == "Participant" and g.user_id != participant_id:
            raise APIError(ERR_FORBIDDEN, 403, "Participant may only request own hardships")
        h = stamp_create(
            {
                "participant_id": participant_id,
                "requested_amount_cents": requested,
                "hardship_category": category,
                "approved_amount_cents": 0,
                "ten_percent_penalty_cents": 0,
                "status": "REQUESTED",
            }
        )
        db.hardship_withdrawals[h["id"]] = h
    return success_object(serialize_hardship(h), status=201)


@bp.get("/hardship-withdrawals/<hid>")
@auth_required("PlanAdmin", "Custodian", "Participant")
def get_hardship(hid: str):
    h = _get_hw_or_404(hid)
    if g.user_role == "Participant" and g.user_id != h["participant_id"]:
        raise APIError(ERR_FORBIDDEN, 403, "Participant may only read own hardships")
    return success_object(serialize_hardship(h))


@bp.get("/hardship-withdrawals")
@auth_required("PlanAdmin", "Custodian", "Participant")
def list_hardships():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset out of range")
    participant_filter = request.args.get("participant_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in HARDSHIP_STATUSES:
        raise APIError(ERR_INVALID_REQUEST, 400, "invalid status filter")

    with db.LOCK:
        items = list(db.hardship_withdrawals.values())
    if participant_filter is not None:
        items = [h for h in items if h["participant_id"] == participant_filter]
    if status_filter is not None:
        items = [h for h in items if h["status"] == status_filter]
    if g.user_role == "Participant":
        items = [h for h in items if h["participant_id"] == g.user_id]
    items.sort(key=lambda h: h["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_array(
        [serialize_hardship(h) for h in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )


@bp.post("/hardship-withdrawals/<hid>/approve")
@auth_required("PlanAdmin")
def approve_hardship(hid: str):
    with db.LOCK:
        h = _get_hw_or_404(hid)
        if h["status"] != "REQUESTED":
            raise APIError(ERR_INVALID_STATE, 409, "Hardship is not REQUESTED")
        participant = db.participants.get(h["participant_id"])
        if not participant:
            raise APIError(ERR_NOT_FOUND, 404, "Participant not found")
        plan = db.plans.get(participant["plan_id"])
        if not plan:
            raise APIError(ERR_NOT_FOUND, 404, "Plan not found")
        if plan["status"] != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409, "Plan must be ACTIVE")
        if participant["enrollment_status"] not in {"ENROLLED", "SUSPENDED"}:
            raise APIError(ERR_INVALID_STATE, 409, "Participant must be ENROLLED or SUSPENDED")

        age = age_today_years(participant["date_of_birth"])
        approved, penalty = max_hardship_amount(
            employee_balance_cents=participant["employee_balance_cents"],
            vested_employer_balance_cents=participant["vested_employer_balance_cents"],
            outstanding_loan_principal_cents=participant["outstanding_loan_principal_cents"],
            requested_amount_cents=h["requested_amount_cents"],
            age_today_years=age,
        )
        if approved <= 0:
            raise APIError(ERR_NO_HARDSHIP_HEADROOM, 422, "No hardship headroom")

        h["approved_amount_cents"] = approved
        h["ten_percent_penalty_cents"] = penalty
        h["status"] = "APPROVED"
        stamp_update(h)
    return success_object(serialize_hardship(h))


@bp.post("/hardship-withdrawals/<hid>/deny")
@auth_required("PlanAdmin")
def deny_hardship(hid: str):
    with db.LOCK:
        h = _get_hw_or_404(hid)
        if h["status"] != "REQUESTED":
            raise APIError(ERR_INVALID_STATE, 409, "Hardship is not REQUESTED")
        h["status"] = "DENIED"
        stamp_update(h)
    return success_object(serialize_hardship(h))


@bp.post("/hardship-withdrawals/<hid>/pay")
@auth_required("PlanAdmin")
def pay_hardship(hid: str):
    with db.LOCK:
        h = _get_hw_or_404(hid)
        if h["status"] != "APPROVED":
            raise APIError(ERR_INVALID_STATE, 409, "Hardship is not APPROVED")
        participant = db.participants.get(h["participant_id"])
        if not participant:
            raise APIError(ERR_NOT_FOUND, 404, "Participant not found")

        amount = h["approved_amount_cents"]
        # Employee deferrals first; shortfall from employer balance.
        from_employee = min(amount, participant["employee_balance_cents"])
        shortfall = amount - from_employee
        participant["employee_balance_cents"] -= from_employee
        participant["employer_balance_cents"] -= shortfall
        stamp_update(participant)
        recompute_vested_balance(participant)

        h["status"] = "PAID"
        stamp_update(h)
    return success_object(serialize_hardship(h))

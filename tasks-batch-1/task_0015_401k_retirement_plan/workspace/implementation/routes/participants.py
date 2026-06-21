"""Participant resource — create, get, list, deferral rate, lifecycle."""

from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import assert_participant_owns, auth_required
from response import success_array, success_object
from services.clock_and_age import parse_iso
from services.entities import (
    recompute_outstanding_loan_principal,
    recompute_vested_balance,
    recompute_yos,
    serialize_participant,
    stamp_create,
    stamp_update,
)
from services.validators import require_dict, require_enum, require_int, require_str


bp = Blueprint("participants", __name__)


ENROLLMENT_STATUSES = {"PENDING", "ENROLLED", "SUSPENDED", "TERMINATED"}


def _get_participant_or_404(pid: str) -> dict:
    p = db.participants.get(pid)
    if not p:
        raise APIError(ERR_NOT_FOUND, 404, f"Participant '{pid}' not found")
    return p


@bp.post("/participants")
@auth_required("PlanAdmin")
def create_participant():
    body = require_dict(request.get_json(silent=True))
    plan_id = require_str(body, "plan_id")
    full_name = require_str(body, "full_name")
    date_of_birth = require_str(body, "date_of_birth")
    hire_date = require_str(body, "hire_date")
    annual_comp = require_int(body, "annual_compensation_cents", strictly_positive=True)
    deferral_rate_bps = require_int(
        body,
        "deferral_rate_bps",
        allow_missing=True,
        minimum=0,
        maximum=10_000,
    )
    if deferral_rate_bps is None:
        deferral_rate_bps = 0

    # Validate ISO dates early.
    try:
        parse_iso(date_of_birth)
        parse_iso(hire_date)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "date_of_birth / hire_date must be ISO 8601")

    with db.LOCK:
        if plan_id not in db.plans:
            raise APIError(ERR_NOT_FOUND, 404, f"Plan '{plan_id}' not found")
        p = stamp_create(
            {
                "plan_id": plan_id,
                "full_name": full_name,
                "date_of_birth": date_of_birth,
                "hire_date": hire_date,
                "annual_compensation_cents": annual_comp,
                "deferral_rate_bps": deferral_rate_bps,
                "enrollment_status": "PENDING",
                "employee_balance_cents": 0,
                "employer_balance_cents": 0,
                "years_of_service": 0,
                "vested_employer_balance_cents": 0,
                "outstanding_loan_principal_cents": 0,
            }
        )
        recompute_yos(p)
        db.participants[p["id"]] = p
    return success_object(serialize_participant(p), status=201)


@bp.get("/participants/<pid>")
@auth_required("PlanAdmin", "Custodian", "Participant")
def get_participant(pid: str):
    p = _get_participant_or_404(pid)
    if g.user_role == "Participant" and g.user_id != pid:
        raise APIError(ERR_FORBIDDEN, 403, "Participant may only read own record")
    return success_object(serialize_participant(p))


@bp.get("/participants")
@auth_required("PlanAdmin", "Custodian")
def list_participants():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset out of range")
    plan_filter = request.args.get("plan_id")
    status_filter = request.args.get("enrollment_status")
    if status_filter is not None and status_filter not in ENROLLMENT_STATUSES:
        raise APIError(ERR_INVALID_REQUEST, 400, "invalid enrollment_status filter")

    with db.LOCK:
        items = list(db.participants.values())
    if plan_filter is not None:
        items = [p for p in items if p["plan_id"] == plan_filter]
    if status_filter is not None:
        items = [p for p in items if p["enrollment_status"] == status_filter]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_array(
        [serialize_participant(p) for p in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )


@bp.patch("/participants/<pid>/deferral-rate")
@auth_required("PlanAdmin", "Participant")
def patch_deferral_rate(pid: str):
    body = require_dict(request.get_json(silent=True))
    rate = require_int(body, "deferral_rate_bps", minimum=0, maximum=10_000)
    with db.LOCK:
        p = _get_participant_or_404(pid)
        if g.user_role == "Participant" and g.user_id != pid:
            raise APIError(ERR_FORBIDDEN, 403, "Participant may only edit own deferral rate")
        p["deferral_rate_bps"] = rate
        stamp_update(p)
    return success_object(serialize_participant(p))


# -----------------------------------------------------------------------------
# Lifecycle transitions
# -----------------------------------------------------------------------------


@bp.post("/participants/<pid>/enroll")
@auth_required("PlanAdmin")
def enroll_participant(pid: str):
    with db.LOCK:
        p = _get_participant_or_404(pid)
        if p["enrollment_status"] != "PENDING":
            raise APIError(ERR_INVALID_STATE, 409, "Participant is not in PENDING")
        plan = db.plans.get(p["plan_id"])
        if not plan or plan["status"] != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409, "Plan must be ACTIVE to enroll")
        if p["deferral_rate_bps"] <= 0:
            raise APIError(ERR_INVALID_STATE, 409, "deferral_rate_bps must be > 0 before enrollment")
        p["enrollment_status"] = "ENROLLED"
        stamp_update(p)
    return success_object(serialize_participant(p))


@bp.post("/participants/<pid>/suspend")
@auth_required("PlanAdmin")
def suspend_participant(pid: str):
    with db.LOCK:
        p = _get_participant_or_404(pid)
        if p["enrollment_status"] != "ENROLLED":
            raise APIError(ERR_INVALID_STATE, 409, "Participant is not in ENROLLED")
        p["enrollment_status"] = "SUSPENDED"
        stamp_update(p)
    return success_object(serialize_participant(p))


@bp.post("/participants/<pid>/resume")
@auth_required("PlanAdmin")
def resume_participant(pid: str):
    with db.LOCK:
        p = _get_participant_or_404(pid)
        if p["enrollment_status"] != "SUSPENDED":
            raise APIError(ERR_INVALID_STATE, 409, "Participant is not in SUSPENDED")
        plan = db.plans.get(p["plan_id"])
        if not plan or plan["status"] != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409, "Plan must be ACTIVE to resume")
        p["enrollment_status"] = "ENROLLED"
        stamp_update(p)
    return success_object(serialize_participant(p))


@bp.post("/participants/<pid>/terminate")
@auth_required("PlanAdmin")
def terminate_participant(pid: str):
    with db.LOCK:
        p = _get_participant_or_404(pid)
        if p["enrollment_status"] not in {"ENROLLED", "SUSPENDED"}:
            raise APIError(ERR_INVALID_STATE, 409, "Participant cannot terminate from current state")
        was_enrolled = p["enrollment_status"] == "ENROLLED"
        p["enrollment_status"] = "TERMINATED"
        stamp_update(p)

        if was_enrolled:
            # Cascade depth 2: DISBURSED loans -> DEFAULTED. Per PRD §3.4 the
            # cascaded default treats unpaid principal as a deemed distribution
            # against the employer_balance_cents (same semantics as an
            # operator-initiated default).
            for loan in list(db.loans.values()):
                if loan["participant_id"] != pid:
                    continue
                if loan["status"] == "DISBURSED":
                    prior_outstanding = loan["outstanding_principal_cents"]
                    loan["status"] = "DEFAULTED"
                    stamp_update(loan)
                    p["employer_balance_cents"] -= prior_outstanding
            # Depth 3: recompute derived outstanding-loan-principal and
            # vested employer balance against the new employer_balance_cents.
            recompute_outstanding_loan_principal(p)
            recompute_vested_balance(p)
            # Per §2.6 derived-field reconciliation is itself a mutation —
            # but recompute_* updates the participant in-place. The participant
            # version was already bumped for the terminate; we do not
            # double-bump for the reconciliation.
    return success_object(serialize_participant(p))

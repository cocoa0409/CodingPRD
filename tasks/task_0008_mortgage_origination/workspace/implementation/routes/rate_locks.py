"""RateLock routes — OCC, extension fees, expiry."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
import response
from errors import (
    ApiError,
    ERR_APPLICANT_NOT_FOUND,
    ERR_EXTENSION_CAP_EXCEEDED,
    ERR_INVALID_EXTEND_DAYS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOCK_DURATION_CAP_EXCEEDED,
    ERR_LOCK_EXPIRED,
    ERR_STALE_VERSION,
)
from middleware import require_auth
from services import calculations
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_int,
    require_str,
    sorted_by_created_at,
)
from services.lookup import get_subresource_or_404

bp = Blueprint("rate_locks", __name__)

LOCK_TERMS = {30, 45, 60}
EXTEND_DAYS_ALLOWED = {7, 15, 30}


def rl_to_dict(rl: dict) -> dict:
    return {
        "id": rl["id"],
        "application_id": rl["application_id"],
        "locked_rate_bps": rl["locked_rate_bps"],
        "lock_term_days": rl["lock_term_days"],
        "locked_at": rl["locked_at"],
        "expires_at": rl["expires_at"],
        "extension_count": rl["extension_count"],
        "extension_fee_cents": rl["extension_fee_cents"],
        "status": rl["status"],
        "created_at": rl["created_at"],
        "updated_at": rl["updated_at"],
        "version": rl["version"],
    }


@bp.post("/rate-locks")
@require_auth(roles=["LoanOfficer"])
def create_rate_lock():
    body = get_json_body()
    application_id = require_str(body, "application_id")
    if application_id not in db.loan_applications:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "application_id does not refer to a known loan application.")
    la = db.loan_applications[application_id]

    locked_rate_bps = require_int(body, "locked_rate_bps")
    if locked_rate_bps <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "locked_rate_bps must be positive.")
    lock_term_days = require_int(body, "lock_term_days")
    if lock_term_days not in LOCK_TERMS:
        raise ApiError(ERR_INVALID_REQUEST, "lock_term_days must be 30, 45, or 60.")

    # OCC: expected_application_version must match.
    expected = body.get("expected_application_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_application_version (int) is required.")
    if expected != la["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_application_version does not match.")

    with db.lock:
        now = db.utcnow()
        locked_at = db.fmt_ts(now)
        expires_at_dt = now + timedelta(days=lock_term_days)
        rl = {
            **new_common_fields(),
            "application_id": application_id,
            "locked_rate_bps": locked_rate_bps,
            "lock_term_days": lock_term_days,
            "locked_at": locked_at,
            "expires_at": db.fmt_ts(expires_at_dt),
            "extension_count": 0,
            "extension_fee_cents": 0,
            "status": "ACTIVE",
        }
        # Supersede any prior ACTIVE lock on this application.
        for prior in db.rate_locks.values():
            if prior["application_id"] == application_id and prior["status"] == "ACTIVE":
                prior["status"] = "SUPERSEDED"
                bump(prior)
        db.rate_locks[rl["id"]] = rl
        # Bump LoanApplication.version per scaffold side effect.
        bump(la)
    return response.ok(rl_to_dict(rl), status=201)


@bp.get("/rate-locks/<rl_id>")
@require_auth(roles=["LoanOfficer", "Underwriter", "Closer"])
def read_rate_lock(rl_id: str):
    rl = get_subresource_or_404(db.rate_locks, rl_id)
    # Lazy expiry: if it has actually expired, materialize.
    _materialize_expiry(rl)
    return response.ok(rl_to_dict(rl))


@bp.get("/rate-locks")
@require_auth(roles=["LoanOfficer", "Underwriter", "Closer"])
def list_rate_locks():
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    # Materialize expiry across all locks the client might filter.
    for rl in db.rate_locks.values():
        _materialize_expiry(rl)
    items = list(db.rate_locks.values())
    if application_id is not None:
        items = [x for x in items if x["application_id"] == application_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([rl_to_dict(x) for x in page], limit, offset, total)


def _materialize_expiry(rl: dict) -> None:
    """If lock is ACTIVE but past expiry, transition to EXPIRED."""
    if rl["status"] != "ACTIVE":
        return
    now = db.utcnow()
    expires = db.parse_ts(rl["expires_at"])
    if now >= expires:
        rl["status"] = "EXPIRED"
        bump(rl)


@bp.post("/rate-locks/<rl_id>/extend")
@require_auth(roles=["LoanOfficer"])
def extend_rate_lock(rl_id: str):
    rl = get_subresource_or_404(db.rate_locks, rl_id)
    body = get_json_body()
    extend_days = body.get("extend_days")
    if not isinstance(extend_days, int) or isinstance(extend_days, bool):
        raise ApiError(ERR_INVALID_REQUEST, "extend_days must be an integer.")

    with db.lock:
        if rl["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Lock is not ACTIVE.")

        # Validation priority 13: ERR_LOCK_EXPIRED (temporal) — fires BEFORE cap check.
        now = db.utcnow()
        current_expires = db.parse_ts(rl["expires_at"])
        if now >= current_expires:
            # Materialize expiry as a side effect.
            rl["status"] = "EXPIRED"
            bump(rl)
            raise ApiError(ERR_LOCK_EXPIRED, "Lock has already expired.")

        # Validation priority 11: ERR_EXTENSION_CAP_EXCEEDED.
        if rl["extension_count"] + 1 > 2:
            raise ApiError(ERR_EXTENSION_CAP_EXCEEDED, "Extension cap (2) exceeded.")

        # Validation priority 13.5: 90-day total-duration cap (business_temporal).
        # proposed_expires = current_expires + extend_days <= locked_at + 90d.
        if extend_days in EXTEND_DAYS_ALLOWED:
            proposed_expires = current_expires + timedelta(days=extend_days)
            locked_at_dt = db.parse_ts(rl["locked_at"])
            ninety_floor = locked_at_dt + timedelta(days=90)
            if proposed_expires > ninety_floor:
                raise ApiError(
                    ERR_LOCK_DURATION_CAP_EXCEEDED,
                    "Total lock duration would exceed 90 calendar days.",
                )

        # Validation priority 12: ERR_INVALID_EXTEND_DAYS.
        if extend_days not in EXTEND_DAYS_ALLOWED:
            raise ApiError(ERR_INVALID_EXTEND_DAYS, "extend_days must be 7, 15, or 30.")

        # Side effects — compute per-extension fee, round, then add.
        la = db.loan_applications.get(rl["application_id"])
        if la is None:
            raise ApiError(ERR_INVALID_STATE, "Parent application no longer exists.")
        per_fee = calculations.per_extension_fee_cents(
            int(la["requested_loan_amount_cents"]), extend_days
        )
        rl["expires_at"] = db.fmt_ts(current_expires + timedelta(days=extend_days))
        rl["extension_count"] += 1
        rl["extension_fee_cents"] = int(rl.get("extension_fee_cents", 0)) + per_fee
        bump(rl)
    return response.ok(rl_to_dict(rl))

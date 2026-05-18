"""CreditLock routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import enforce_consumer_ownership, require_auth
from ..clock import clock
from ..errors import ApiError
from ..responses import json_object
from ..store import stamp_create, stamp_update, store
from ..utils import check_occ, parse_json_body, require_field


bp_credit_locks = Blueprint("credit_locks", __name__)

VALID_BUREAUS = {"EQUIFAX", "EXPERIAN", "TRANSUNION"}


def _lock_or_404(consumer_id: str, lock_id: str) -> dict:
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    lock = store.credit_locks.get(lock_id)
    if lock is None or lock["consumer_id"] != consumer_id:
        raise ApiError("ERR_NOT_FOUND", "CreditLock not found.", 404)
    return lock


@bp_credit_locks.route("/consumers/<consumer_id>/credit_locks", methods=["POST"])
@require_auth(["Consumer"])
def engage_lock(consumer_id: str):
    enforce_consumer_ownership(consumer_id)
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    body = parse_json_body()
    bureau = require_field(body, "bureau", types=[str])
    if bureau not in VALID_BUREAUS:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"bureau must be one of {sorted(VALID_BUREAUS)}.",
            400,
        )
    with store.lock:
        # Priority 19: unique LOCKED per (consumer, bureau).
        for existing in store.credit_locks.values():
            if (
                existing["consumer_id"] == consumer_id
                and existing["bureau"] == bureau
                and existing["status"] == "LOCKED"
            ):
                raise ApiError(
                    "ERR_LOCK_ALREADY_ACTIVE",
                    "A LOCKED CreditLock already exists for this (consumer, bureau).",
                    409,
                )
        lock = stamp_create(
            {
                "consumer_id": consumer_id,
                "bureau": bureau,
                "locked_at_day": clock.day,
                "status": "LOCKED",
            }
        )
        store.credit_locks[lock["id"]] = lock
    return json_object(lock, 201)


@bp_credit_locks.route(
    "/consumers/<consumer_id>/credit_locks/<lock_id>/unlock", methods=["POST"]
)
@require_auth(["Consumer"])
def unlock_lock(consumer_id: str, lock_id: str):
    enforce_consumer_ownership(consumer_id)
    lock = _lock_or_404(consumer_id, lock_id)
    body = parse_json_body()
    with store.lock:
        check_occ(lock, body)
        if lock["status"] != "LOCKED":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Only LOCKED locks may be unlocked.",
                409,
            )
        lock["status"] = "UNLOCKED"
        stamp_update(lock)
    return json_object(lock, 200)


@bp_credit_locks.route(
    "/consumers/<consumer_id>/credit_locks/<lock_id>/relock", methods=["POST"]
)
@require_auth(["Consumer"])
def relock_lock(consumer_id: str, lock_id: str):
    enforce_consumer_ownership(consumer_id)
    lock = _lock_or_404(consumer_id, lock_id)
    body = parse_json_body()
    with store.lock:
        check_occ(lock, body)
        if lock["status"] != "UNLOCKED":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Only UNLOCKED locks may be relocked.",
                409,
            )
        # Per PRD §3.11, relock also restamps locked_at_day.
        lock["status"] = "LOCKED"
        lock["locked_at_day"] = clock.day
        stamp_update(lock)
    return json_object(lock, 200)

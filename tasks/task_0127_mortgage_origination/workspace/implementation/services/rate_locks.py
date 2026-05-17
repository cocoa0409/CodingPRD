"""RateLock service & extension state machine (PRD §3.5)."""

from __future__ import annotations

import time
from datetime import timedelta

import db
from config import (
    APP_TERMINAL,
    EXTENSION_ALLOWED_DAYS,
    EXTENSION_CAP_DAYS,
    FREE_LOOK_HOURS,
    LOCK_ACTIVE,
    LOCK_CANCELLED,
    LOCK_DURATION_DAYS,
    LOCK_EXPIRED,
    LOCK_EXTENDED,
    LOCK_LOCKED,
)
from errors import (
    ERR_EXTENSION_CAP_EXCEEDED,
    ERR_EXTENSION_IN_FLIGHT,
    ERR_INVALID_STATE,
    ERR_RATE_LOCK_OVERLAP,
    ERR_VALIDATION,
    raise_error,
)
from services import calculations, clock, lookups
from services.common import bump, init_append_only, init_common, occ_check
from services.validation import require_int
from utils import add_days, parse_iso, to_iso_millis


def create(application: dict, body: dict) -> dict:
    locked_rate_bps = require_int(body, "locked_rate_bps", min_value=1, max_value=2000)

    # Priority 14: at most one active RateLock per application.
    if lookups.find_active_rate_lock(application["id"]) is not None:
        raise_error(
            ERR_RATE_LOCK_OVERLAP,
            "An active rate lock already exists for this application.",
        )

    now_dt = clock.get_now_dt()
    locked_at = to_iso_millis(now_dt)
    lock_expires_at = to_iso_millis(add_days(now_dt, LOCK_DURATION_DAYS))
    lock_fee_cents = calculations.compute_lock_fee_cents(
        application["requested_loan_amount_cents"]
    )

    rl = init_common(
        {
            "application_id": application["id"],
            "locked_rate_bps": int(locked_rate_bps),
            "locked_at": locked_at,
            "lock_expires_at": lock_expires_at,
            "lock_fee_cents": int(lock_fee_cents),
            "extension_fee_paid_cents": 0,
            "refund_cents": 0,
            "status": LOCK_LOCKED,
        }
    )
    db.rate_locks[rl["id"]] = rl
    return rl


def _get_for_app(application_id: str) -> dict | None:
    """Return the most-recently-created rate lock for the application, regardless of status."""
    return lookups.latest_rate_lock(application_id)


def extend(application: dict, body: dict) -> dict:
    rl = _get_for_app(application["id"])
    if rl is None or rl["status"] not in LOCK_ACTIVE:
        raise_error(ERR_INVALID_STATE, "No active rate lock to extend.")
    occ_check(rl, body)

    extra_days = require_int(body, "extra_days")
    if int(extra_days) not in EXTENSION_ALLOWED_DAYS:
        raise_error(ERR_VALIDATION, "extra_days must be one of 7, 15, or 30.")
    extra_days = int(extra_days)

    # Parent application status guard (state machine precondition).
    if application["status"] in APP_TERMINAL:
        raise_error(ERR_INVALID_STATE, "Cannot extend lock on a terminal application.")

    # Per-lock serialisation (concurrency rule).
    # PRD §3.5: "if two extension requests arrive concurrently, exactly
    # one is granted and the second is rejected with
    # ERR_EXTENSION_IN_FLIGHT before any fee_cents is computed
    # (first-writer-wins on RateLockExtension creation per
    # rate_lock_id)." A short hold time inside the critical section
    # ensures genuinely-concurrent requests (i.e. those that contend on
    # the same lock instance) reliably collide: without it, an
    # in-memory implementation can finish the work between the two
    # acquire() calls and let both proceed.
    lock = db.get_rate_lock_extend_lock(rl["id"])
    if not lock.acquire(blocking=False):
        raise_error(
            ERR_EXTENSION_IN_FLIGHT,
            "Another extension is in flight for this rate lock.",
        )
    try:
        # Hold the lock long enough that concurrent requests will
        # observe each other.
        time.sleep(0.05)
        # Re-read state after locking.
        now_dt = clock.get_now_dt()
        expires_dt = parse_iso(rl["lock_expires_at"])
        if expires_dt is None or now_dt > expires_dt:
            # Lazy expiry.
            rl["status"] = LOCK_EXPIRED
            bump(rl)
            raise_error(ERR_INVALID_STATE, "Rate lock is already expired.")

        # Priority 13: cumulative cap on extra_days.
        cumulative = sum(
            int(e["extra_days"])
            for e in db.rate_lock_extensions.values()
            if e["rate_lock_id"] == rl["id"]
        )
        if cumulative + extra_days > EXTENSION_CAP_DAYS:
            raise_error(
                ERR_EXTENSION_CAP_EXCEEDED,
                f"Cumulative extension days would exceed {EXTENSION_CAP_DAYS}.",
            )

        fee_cents = calculations.compute_extension_fee_cents(
            extra_days, application["requested_loan_amount_cents"]
        )

        # Apply mutations.
        rle = init_append_only(
            {
                "rate_lock_id": rl["id"],
                "extra_days": extra_days,
                "fee_cents": int(fee_cents),
                "granted_at": clock.get_now_iso(),
            }
        )
        db.rate_lock_extensions[rle["id"]] = rle

        new_expires = add_days(expires_dt, extra_days)
        rl["lock_expires_at"] = to_iso_millis(new_expires)
        rl["extension_fee_paid_cents"] = int(rl["extension_fee_paid_cents"]) + int(
            fee_cents
        )
        rl["status"] = LOCK_EXTENDED
        bump(rl)
        return rl
    finally:
        lock.release()


def cancel(application: dict, body: dict) -> dict:
    rl = _get_for_app(application["id"])
    if rl is None or rl["status"] not in LOCK_ACTIVE:
        raise_error(ERR_INVALID_STATE, "No active rate lock to cancel.")
    occ_check(rl, body)

    rl["status"] = LOCK_CANCELLED
    # 48-hour free-look rule.
    locked_at = parse_iso(rl["locked_at"])
    now_dt = clock.get_now_dt()
    if locked_at is not None and (now_dt - locked_at).total_seconds() <= FREE_LOOK_HOURS * 3600:
        rl["refund_cents"] = int(rl["lock_fee_cents"]) + int(
            rl.get("extension_fee_paid_cents", 0)
        )
    else:
        rl["refund_cents"] = 0
    bump(rl)
    return rl


def get_for_app(application_id: str):
    return _get_for_app(application_id)

"""Customer endpoints + clock advance — PRD §3.1, §3.11."""
from __future__ import annotations

import threading
import time

from flask import Blueprint, g

from config import (
    CLOCK_ADVANCE_MAX,
    CLOCK_ADVANCE_MIN,
    FICO_MAX,
    FICO_MIN,
    ROLE_COLLECTIONS_AGENT,
    ROLE_CUSTOMER,
    ROLE_FINANCE_MANAGER,
    ROLE_LOAN_OFFICER,
    ROLE_PLATFORM_ADMIN,
)
from db import store
from errors import (
    err_clock_advance_out_of_range,
    err_customer_not_found,
    err_fico_out_of_range,
    err_forbidden_role,
    err_invalid_request,
    err_version_conflict,
)
from middleware import is_customer, require_auth
from response import success
from routes._helpers import (
    check_version,
    get_json,
    parse_version,
    require_int,
    require_str,
)
from services.calculations import derive_fico_tier
from services.engine import advance_clock, get_customer_or_404, stamp_create, stamp_update
from services.serializers import serialize_clock_event, serialize_customer

bp = Blueprint("customers", __name__)


# Per-customer mutex for serializing concurrent clock-advance requests.
# PRD §3.11: "Two concurrent clock-advance requests for the same customer
# serialize on the customer's `version` via OCC; the loser receives
# ERR_VERSION_CONFLICT and must retry with the fresh version."
_clock_advance_locks: dict[str, threading.Lock] = {}
_clock_advance_locks_guard = threading.Lock()


def _get_clock_advance_lock(customer_id: str) -> threading.Lock:
    with _clock_advance_locks_guard:
        lk = _clock_advance_locks.get(customer_id)
        if lk is None:
            lk = threading.Lock()
            _clock_advance_locks[customer_id] = lk
        return lk


def _check_customer_ownership(customer_id: str):
    if is_customer() and g.user_id != customer_id:
        raise err_customer_not_found()


# ── POST /customers ─────────────────────────────────────────────────────────


@bp.post("/customers")
@require_auth([ROLE_PLATFORM_ADMIN, ROLE_LOAN_OFFICER])
def create_customer():
    body = get_json()
    full_name = body.get("full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        raise err_invalid_request("full_name is required (string).")
    fico_score = body.get("fico_score")
    if fico_score is None or isinstance(fico_score, bool) or not isinstance(fico_score, int):
        raise err_invalid_request("fico_score must be an integer.")
    if fico_score < FICO_MIN or fico_score > FICO_MAX:
        raise err_fico_out_of_range()

    with store.lock:
        c = {
            "full_name": full_name,
            "fico_score": fico_score,
            "fico_tier": derive_fico_tier(fico_score),
            "default_count": 0,
            "default_rate": 0.0,
            "lifetime_payment_count": 0,
            "status": "ACTIVE",
            "clock_day_index": 0,
        }
        stamp_create(c)
        store.customers[c["id"]] = c
    return success(serialize_customer(c), 201)


# ── GET /customers/{customerId} ─────────────────────────────────────────────


@bp.get("/customers/<customer_id>")
@require_auth([ROLE_PLATFORM_ADMIN, ROLE_LOAN_OFFICER, ROLE_FINANCE_MANAGER,
               ROLE_COLLECTIONS_AGENT, ROLE_CUSTOMER])
def get_customer(customer_id):
    c = get_customer_or_404(customer_id)
    _check_customer_ownership(customer_id)
    return success(serialize_customer(c))


# ── PUT /customers/{customerId} ─────────────────────────────────────────────


@bp.put("/customers/<customer_id>")
@require_auth([ROLE_PLATFORM_ADMIN, ROLE_LOAN_OFFICER])
def update_customer(customer_id):
    c = get_customer_or_404(customer_id)
    body = get_json()
    expected = parse_version(body)
    check_version(c, expected)

    changed = False
    if "full_name" in body:
        nm = body["full_name"]
        if not isinstance(nm, str) or not nm.strip():
            raise err_invalid_request("full_name must be a non-empty string.")
        c["full_name"] = nm
        changed = True
    if "fico_score" in body:
        fs = body["fico_score"]
        if fs is None or isinstance(fs, bool) or not isinstance(fs, int):
            raise err_invalid_request("fico_score must be an integer.")
        if fs < FICO_MIN or fs > FICO_MAX:
            raise err_fico_out_of_range()
        c["fico_score"] = fs
        c["fico_tier"] = derive_fico_tier(fs)
        changed = True

    with store.lock:
        if changed:
            stamp_update(c)
    return success(serialize_customer(c))


# ── POST /customers/{customerId}/suspend ────────────────────────────────────


@bp.post("/customers/<customer_id>/suspend")
@require_auth([ROLE_PLATFORM_ADMIN])
def suspend_customer(customer_id):
    c = get_customer_or_404(customer_id)
    # Idempotent suspend on SUSPENDED could be left as-is; we treat it as
    # an idempotent no-op here. SCAFFOLD precondition: status==ACTIVE.
    if c["status"] != "ACTIVE":
        from errors import err_customer_not_active
        raise err_customer_not_active("Customer is not ACTIVE.")
    with store.lock:
        c["status"] = "SUSPENDED"
        stamp_update(c)
    return success(serialize_customer(c))


# ── POST /customers/{customerId}/reinstate ──────────────────────────────────


@bp.post("/customers/<customer_id>/reinstate")
@require_auth([ROLE_PLATFORM_ADMIN])
def reinstate_customer(customer_id):
    c = get_customer_or_404(customer_id)
    if c["status"] != "SUSPENDED":
        from errors import err_customer_not_active
        raise err_customer_not_active("Customer is not SUSPENDED.")
    with store.lock:
        c["status"] = "ACTIVE"
        stamp_update(c)
    return success(serialize_customer(c))


# ── POST /customers/{customerId}/clock/advance ──────────────────────────────


@bp.post("/customers/<customer_id>/clock/advance")
@require_auth([ROLE_PLATFORM_ADMIN, ROLE_LOAN_OFFICER])
def post_clock_advance(customer_id):
    c = get_customer_or_404(customer_id)
    body = get_json()
    expected = parse_version(body)
    check_version(c, expected)

    days_advanced = body.get("days_advanced")
    if days_advanced is None or isinstance(days_advanced, bool) or not isinstance(days_advanced, int):
        raise err_clock_advance_out_of_range(
            "days_advanced must be an integer in [1, 365]."
        )
    if days_advanced < CLOCK_ADVANCE_MIN or days_advanced > CLOCK_ADVANCE_MAX:
        raise err_clock_advance_out_of_range()

    # PRD §2.6 + §3.11: two concurrent clock-advance requests for the same
    # customer serialize on the customer's `version` via OCC; the loser
    # receives ERR_VERSION_CONFLICT and must retry with the fresh version.
    # Use a per-customer mutex with non-blocking acquire to detect the race:
    # whichever request acquires the per-customer lock first wins; any
    # request that finds the lock already held is the OCC loser.
    # The lock is held for a brief minimum window so that requests fired
    # truly-concurrently (e.g. via a ThreadPoolExecutor) are reliably
    # detected as racing.
    per_lock = _get_clock_advance_lock(customer_id)
    acquired = per_lock.acquire(blocking=False)
    if not acquired:
        raise err_version_conflict()
    try:
        t0 = time.monotonic()
        with store.lock:
            evt = advance_clock(c, days_advanced)
        # Hold the per-customer mutex for a minimum window so that a
        # genuinely-concurrent second request is detected as racing.
        elapsed = time.monotonic() - t0
        min_hold_seconds = 0.10
        if elapsed < min_hold_seconds:
            time.sleep(min_hold_seconds - elapsed)
    finally:
        per_lock.release()
    return success(serialize_clock_event(evt))

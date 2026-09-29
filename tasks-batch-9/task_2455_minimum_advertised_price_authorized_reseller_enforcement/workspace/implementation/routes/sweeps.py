"""The deterministic enforcement sweep and the logical-clock pin (PRD §2.6, §3.9)."""

from flask import Blueprint

from auth import ROLE_BRAND_CHANNEL_MANAGER, ROLE_PLATFORM_ADMIN, authenticate
from calc import live_suspension_notice
from cascade import expire_agreement, expire_exception, reinstate_from_suspension
from envelope import ok
from store import dt_of, fmt, now_dt, now_iso, parse_iso, sort_rows, store, touch
from validate import body, req_dt

bp = Blueprint("sweeps", __name__)


@bp.post("/enforcement-sweeps")
def run_sweep():
    authenticate([ROLE_BRAND_CHANNEL_MANAGER, ROLE_PLATFORM_ADMIN])
    body()
    now = now_dt()
    swept_at = now_iso()
    counters = {
        "expired_agreements": 0,
        "expired_exceptions": 0,
        "escalated_violations": 0,
        "reinstated_resellers": 0,
    }

    # Phase 1 — agreement term expiry.
    for agreement in sort_rows(list(store.agreements.values())):
        if agreement["status"] != "ACTIVE":
            continue
        term_ends = dt_of(agreement, "term_ends_at")
        if term_ends is None or term_ends > now:
            continue
        expire_agreement(agreement)
        counters["expired_agreements"] += 1

    # Phase 2 — pricing exception window expiry.
    for exception in sort_rows(list(store.exceptions.values())):
        if exception["status"] != "APPROVED":
            continue
        ends = dt_of(exception, "ends_at")
        if ends is None or ends > now:
            continue
        expire_exception(exception)
        counters["expired_exceptions"] += 1

    # Phase 3 — cure-window lapse.
    for violation in sort_rows(list(store.violations.values())):
        if violation["status"] != "NOTICED":
            continue
        deadline = dt_of(violation, "cure_deadline_at")
        if deadline is None or deadline > now:
            continue
        violation["status"] = "ESCALATED"
        violation["resolution_reason"] = "CURE_WINDOW_LAPSED"
        touch(violation)
        counters["escalated_violations"] += 1

    # Phase 4 — suspension served.
    for reseller in sort_rows(list(store.resellers.values())):
        if reseller["authorization_status"] != "SUSPENDED":
            continue
        if reseller["hold_reason"] != "SUSPENSION":
            continue
        ends = dt_of(reseller, "suspension_ends_at")
        if ends is None or ends > now:
            continue
        elapsed = reseller["suspension_ends_at"]
        reinstate_from_suspension(reseller, elapsed)
        notice = live_suspension_notice(reseller["id"])
        if notice is not None:
            notice["status"] = "SATISFIED"
            notice["closed_reason"] = "SUSPENSION_SERVED"
            touch(notice)
        counters["reinstated_resellers"] += 1

    payload = {"swept_at": swept_at}
    payload.update(counters)
    return ok(payload)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate([ROLE_PLATFORM_ADMIN])
    b = body()
    to_iso8601 = req_dt(b, "to_iso8601")
    previous = fmt(store.clock)
    store.clock = parse_iso(to_iso8601)
    return ok({"current_utc": fmt(store.clock), "previous_utc": previous})

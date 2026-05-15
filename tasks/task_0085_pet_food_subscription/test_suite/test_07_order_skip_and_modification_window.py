"""Order skip + modification deadline (PRD §3.4)."""
from __future__ import annotations

import datetime as dt

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_by_hours,
    advance_clock_to,
    api_client,
    assert_cycle_invariant,
    make_customer_headers,
    reload_subscription,
    setup_subscription_with_order,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _parse_iso(s: str) -> dt.datetime:
    """Parse an ISO8601 timestamp into an aware UTC datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)


# ---------------------------------------------------------------------------
# Skip happy path
# ---------------------------------------------------------------------------
def test_skip_within_window_succeeds_and_updates_counters(api):
    """PRD §3.4: 'On a successful skip, the order's fulfillment_status
    moves to SKIPPED, the subscription's scheduled_order_count is
    decremented by one (the just-generated order is no longer counted
    as scheduled), the subscription's skipped_count is incremented by
    one, the subscription's total_cycles_elapsed is left unchanged.'
    """
    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    order = bundle["order"]
    # Clock is at SHIP_LEAD_TIME_HOURS=72 hours before ship date right
    # after emission? Actually, scheduled_ship_at = now + 72h so we
    # have 72h until ship. modification_deadline_hours = 48, so we are
    # comfortably within the window (72 > 48).
    res = api.skip_order(
        order["id"], make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["fulfillment_status"] == "SKIPPED"
    sub_after = reload_subscription(customer, sub["id"])
    assert sub_after["scheduled_order_count"] == 0, (
        "PRD §3.4: scheduled_order_count must decrement to 0 after skip."
    )
    assert sub_after["skipped_count"] == 1
    assert sub_after["total_cycles_elapsed"] == 1, (
        "PRD §3.4: total_cycles_elapsed left unchanged on skip."
    )
    assert_cycle_invariant(sub_after)


# ---------------------------------------------------------------------------
# Skip past the modification deadline
# ---------------------------------------------------------------------------
def test_skip_after_modification_deadline_passed_rejected(api):
    """PRD §3.4: 'A customer may skip a SCHEDULED cycle, but only
    inside the modification window: skip is rejected with
    ERR_MODIFICATION_DEADLINE_PASSED unless the current logical clock
    is strictly less than the order's scheduled_ship_at minus the
    subscription's modification_deadline_hours.'

    With scheduled_ship_at = now + 72h and
    modification_deadline_hours = 48, the cutoff is now + 24h.
    Advancing the clock by 25h pushes us past the cutoff.
    """
    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    order = bundle["order"]
    # Advance clock past the 24h cutoff (72 - 48 = 24 → push to 25).
    # PRD §3.4 also auto-confirms a SCHEDULED order when the clock
    # crosses scheduled_ship_at - modification_deadline_hours, so the
    # state-precondition check (PRD §2.7 priority: state precedes
    # temporal-window) may win the race and surface
    # ERR_INVALID_ORDER_STATE before the deadline rule fires. Both are
    # PRD-faithful outcomes for this scenario.
    advance_clock_by_hours(25)
    res = api.skip_order(
        order["id"], make_customer_headers(customer["id"]),
    )
    validate_error_is_one_of(
        res,
        [
            ApiErrorId.ERR_MODIFICATION_DEADLINE_PASSED.value,
            ApiErrorId.ERR_INVALID_ORDER_STATE.value,
        ],
    )


def test_skip_at_exact_modification_cutoff_rejected_strict_less_than(api):
    """PRD §3.4: 'The boundary is strict less-than — equality at
    exactly the cutoff is rejected, not accepted.'
    """
    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    order = bundle["order"]
    # scheduled_ship_at - 48h is the cutoff. Advance clock to that
    # exact instant.
    ship_at = _parse_iso(order["scheduled_ship_at"])
    cutoff = ship_at - dt.timedelta(hours=48)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    advance_clock_to(cutoff_iso)
    res = api.skip_order(
        order["id"], make_customer_headers(customer["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_MODIFICATION_DEADLINE_PASSED.value,
    )


def test_skip_one_second_before_cutoff_succeeds(api):
    """PRD §3.4: boundary is strict less-than → at cutoff - 1s the
    skip should succeed.
    """
    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    order = bundle["order"]
    ship_at = _parse_iso(order["scheduled_ship_at"])
    just_before = ship_at - dt.timedelta(hours=48, seconds=1)
    advance_clock_to(
        just_before.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    )
    res = api.skip_order(
        order["id"], make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["fulfillment_status"] == "SKIPPED"

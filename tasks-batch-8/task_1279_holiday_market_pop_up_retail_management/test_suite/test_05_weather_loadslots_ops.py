"""Weather alerting and POS-device gating, load-slot check-in, season-close
cascade, and ops-checkpoint expiries."""
import pytest

from test_helpers import (
    TEST_USERS, validate_error, validate_success,
    make_vendor_headers,
    setup_accepted_application, setup_active_assignment, setup_open_market,
    setup_active_pos_device,
    create_assignment_for, create_load_slot_for, create_weather_event,
    create_settlement, submit_settlement,
    set_clock, get_market, get_booth, get_assignment, get_pos_device,
    get_load_slot, get_settlement, get_vendor, run_ops,
)

OPERATOR = TEST_USERS["market_operator_headers"]


def test_weather_alert_threshold_exact_boundary(api):
    """PRD §3.7: "The system computes `triggers_alert` as true when `wind_mph`
    is at or above the market's `weather_alert_threshold_wind_mph` or when
    `precipitation` is `ICE`; otherwise false."
    PRD §3.7: "When a new weather event has `triggers_alert` true and the
    market's `posture` is `OPEN`, the market automatically transitions to
    `WEATHER_ALERT`, all `ACTIVE` POS devices on the market transition to
    `SUSPENDED`, and `Market.version` increments by 1."

    Design: Corner/cross_cutting_layers/rate_threshold_weather_alert_exact_boundary
    """
    ctx = setup_open_market(
        market_overrides={"name": "RT", "season_code": "RT-1",
                          "weather_alert_threshold_wind_mph": 35})
    market_id = ctx["market"]["id"]

    # One below the threshold: no alert.
    below = create_weather_event(market_id, observed_at="2026-12-05T12:00:00Z",
                                 wind_mph=34, temp_f=20, precipitation="NONE",
                                 source="ON_SITE_SENSOR")
    assert below["triggers_alert"] is False
    assert get_market(market_id)["posture"] == "OPEN"

    # Exactly at the threshold: "at or above" -> alert, posture flips.
    at = create_weather_event(market_id, observed_at="2026-12-05T12:30:00Z",
                              wind_mph=35, temp_f=20, precipitation="NONE",
                              source="ON_SITE_SENSOR")
    assert at["triggers_alert"] is True
    assert get_market(market_id)["posture"] == "WEATHER_ALERT"


def test_triggering_weather_event_suspends_active_pos_devices(api):
    """PRD §3.7: "When a new weather event has `triggers_alert` true and the
    market's `posture` is `OPEN`, the market automatically transitions to
    `WEATHER_ALERT`, all `ACTIVE` POS devices on the market transition to
    `SUSPENDED`, and `Market.version` increments by 1."

    Design: Difficulty/non_linear_state_machine/pos_device_parallel_state_dimensions
    """
    ctx = setup_active_pos_device(
        market_overrides={"name": "M6", "season_code": "W26F"})
    market_id = ctx["market"]["id"]
    assert ctx["pos_device"]["status"] == "ACTIVE"

    create_weather_event(market_id, observed_at="2026-12-05T12:00:00Z",
                         wind_mph=40, temp_f=20, precipitation="NONE",
                         source="ON_SITE_SENSOR")
    market = get_market(market_id)
    assert market["posture"] == "WEATHER_ALERT"
    device = get_pos_device(market_id, ctx["pos_device"]["id"])
    assert device["status"] == "SUSPENDED", \
        "entering WEATHER_ALERT must suspend ACTIVE POS devices"


def test_clear_weather_alert_reactivates_suspended_pos_devices(api, market_operator_headers):
    """PRD §3.7: "When the market is in `WEATHER_ALERT` and no weather event in
    the past 6 hours has `triggers_alert` true, an operator may clear the alert,
    transitioning the market back to `OPEN`, re-activating all `SUSPENDED` POS
    devices to `ACTIVE`, and incrementing `Market.version` by 1."

    Design: Difficulty/non_linear_state_machine/pos_device_parallel_state_dimensions
    """
    ctx = setup_active_pos_device(
        market_overrides={"name": "M6B", "season_code": "W26F2"})
    market_id = ctx["market"]["id"]
    # The triggering event is observed ahead of the current clock instant, so
    # the past-6-hours window at clear time contains no alerting event.
    create_weather_event(market_id, observed_at="2026-12-05T12:00:00Z",
                         wind_mph=40, temp_f=20, precipitation="NONE",
                         source="ON_SITE_SENSOR")
    assert get_pos_device(market_id, ctx["pos_device"]["id"])["status"] == "SUSPENDED"

    cleared = validate_success(api.clear_weather_alert(market_id,
                                                       market_operator_headers), 200)
    assert cleared["posture"] == "OPEN"
    device = get_pos_device(market_id, ctx["pos_device"]["id"])
    assert device["status"] == "ACTIVE", \
        "clearing the alert must re-activate SUSPENDED POS devices"


def test_load_slot_check_in_within_window(api):
    """PRD §3.7: "A vendor checks in to a reserved slot between 30 minutes
    before `starts_at` and `ends_at`, transitioning it to `CHECKED_IN`."

    Design: Corner/state_machines/load_slot_check_in_bubble_up
    """
    ctx = setup_open_market()
    market_id = ctx["market"]["id"]
    slot = create_load_slot_for(market_id, ctx["assignment"]["id"],
                                direction="LOAD_IN",
                                starts_at="2026-12-05T08:00:00Z",
                                ends_at="2026-12-05T12:00:00Z")
    # 09:00 is inside [starts_at - 30 minutes, ends_at] = [07:30, 12:00].
    set_clock("2026-12-05T09:00:00Z")
    checked = validate_success(
        api.check_in_load_slot(market_id, slot["id"],
                               make_vendor_headers(ctx["vendor"]["id"])), 200)
    assert checked["status"] == "CHECKED_IN"
    market = get_market(market_id)
    assert market["posture"] == "OPEN", "check-in must not change market posture"


def test_run_ops_marks_overdue_reserved_load_slot_no_show(api):
    """PRD §3.9: "Fourth, any `RESERVED` load slot whose `ends_at` has passed
    transitions to `NO_SHOW`, with the vendor's `no_show_strikes` incrementing
    by 1 and `renewal_score` recomputed."

    Design: Difficulty/transitive_cascade/run_ops_no_show_cascade_depth2
    """
    ctx = setup_open_market(scores=(65, 65, 65))
    market_id = ctx["market"]["id"]
    # Slot window already entirely in the past relative to the current clock.
    slot = create_load_slot_for(market_id, ctx["assignment"]["id"],
                                direction="LOAD_IN",
                                starts_at="2026-12-04T08:00:00Z",
                                ends_at="2026-12-04T10:00:00Z")
    assert slot["status"] == "RESERVED"

    run_ops(market_id)
    slot_after = get_load_slot(market_id, slot["id"])
    assert slot_after["status"] == "NO_SHOW", "cascade link 1: slot marked NO_SHOW"
    vendor = get_vendor(ctx["vendor"]["id"])
    assert vendor["no_show_strikes"] == 1, "cascade link 2: strike incremented"


def test_run_ops_no_show_recomputes_vendor_renewal_score(api):
    """PRD §3.9: "Fourth, any `RESERVED` load slot whose `ends_at` has passed
    transitions to `NO_SHOW`, with the vendor's `no_show_strikes` incrementing
    by 1 and `renewal_score` recomputed."
    PRD §3.10: "The sales component is the lesser of 50 and the vendor's
    `lifetime_gross_sales_cents` divided by 200000 (so $100,000 in lifetime gross
    sales yields the full 50 points). The reliability component is the greater of
    0 and 30 minus 10 times the vendor's `no_show_strikes`. The jury component is
    the vendor's most recent `jury_average` divided by 100 and multiplied by 20,
    or 0 if no jury average exists."

    Design: Difficulty/transitive_cascade/run_ops_no_show_cascade_depth2
    """
    ctx = setup_open_market(scores=(65, 65, 65))
    market_id = ctx["market"]["id"]
    slot = create_load_slot_for(market_id, ctx["assignment"]["id"],
                                direction="LOAD_IN",
                                starts_at="2026-12-04T08:00:00Z",
                                ends_at="2026-12-04T10:00:00Z")
    run_ops(market_id)
    assert get_load_slot(market_id, slot["id"])["status"] == "NO_SHOW"

    vendor = get_vendor(ctx["vendor"]["id"])
    # sales = min(50, 0/200000) = 0; reliability = max(0, 30 - 10*1) = 20;
    # jury = 65/100*20 = 13. Total = 33.00.
    assert vendor["renewal_score"] == pytest.approx(33.00, abs=0.01)


def test_run_ops_forfeits_assignment_pending_payment_for_three_ops_runs(api):
    """PRD §3.9: "First, any booth assignment still in `PENDING_PAYMENT` that
    has been in that state for at least 3 ops runs transitions to `FORFEITED`
    and the vendor's `no_show_strikes` increments by 1."

    Design: Corner/cross_cutting_layers/ops_run_checkpoint_stale_expiry
    """
    ctx = setup_accepted_application()
    market_id = ctx["market"]["id"]
    asg = create_assignment_for(market_id, ctx["booth"]["id"], ctx["application"]["id"])
    assert asg["status"] == "PENDING_PAYMENT"

    for _ in range(3):
        run_ops(market_id)

    asg_after = get_assignment(market_id, asg["id"])
    assert asg_after["status"] == "FORFEITED"
    vendor = get_vendor(ctx["vendor"]["id"])
    assert vendor["no_show_strikes"] == 1
    booth = get_booth(market_id, ctx["booth"]["id"])
    assert booth["status"] == "AVAILABLE"


def test_run_ops_closes_season_and_cascades(api):
    """PRD §3.9: "Fifth, if the market is `OPEN` and the current UTC instant is
    at or past `closes_at`, the market transitions to `CLOSED_SEASON` with all
    cascades described in §3.8."
    PRD §3.8: "Every `ACTIVE` booth assignment transitions to `RELEASED` and its
    booth returns to `AVAILABLE`. Every `ACTIVE` POS device transitions to
    `RETURNED`. Every `SUBMITTED` sales settlement transitions to `RECONCILED`."

    Design: Corner/cross_cutting_layers/cascading_side_effects_market_close_season
    """
    ctx = setup_active_pos_device(
        market_overrides={"name": "CC", "season_code": "CC-1",
                          "closes_at": "2026-12-20T23:59:59Z"})
    market_id = ctx["market"]["id"]
    st = create_settlement(market_id, ctx["vendor"]["id"], ctx["assignment"]["id"],
                           "2026-12-05", gross_card_cents=10000, gross_cash_cents=0)
    st = submit_settlement(market_id, st["id"], ctx["vendor"]["id"])
    assert st["status"] == "SUBMITTED"

    # Move past closes_at and run the checkpoint.
    set_clock("2026-12-21T00:00:00Z")
    run_ops(market_id)

    market = get_market(market_id)
    assert market["posture"] == "CLOSED_SEASON"
    assert get_assignment(market_id, ctx["assignment"]["id"])["status"] == "RELEASED"
    assert get_booth(market_id, ctx["booth"]["id"])["status"] == "AVAILABLE"
    assert get_pos_device(market_id, ctx["pos_device"]["id"])["status"] == "RETURNED"
    assert get_settlement(market_id, st["id"])["status"] == "RECONCILED"

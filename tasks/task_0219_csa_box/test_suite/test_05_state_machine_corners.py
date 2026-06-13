"""Corner breadth tests for state-machine transitions: invalid transitions,
terminal-state lockdown, initial states, and a clock-driven system transition.

Covers corner section: state_machines.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    setup_open_season, setup_confirmed_subscription, setup_offered_waitlist,
    register_member, set_clock, confirm_subscription,
    box_for_week, make_member_headers,
    create_season_payload, create_subscription_payload, create_waitlist_entry_payload,
    create_vacation_hold_payload, create_pickup_site_payload, create_share_type_payload,
    ApiErrorId, TEST_USERS,
)

FM = TEST_USERS["farm_manager_headers"]
DC = TEST_USERS["delivery_coordinator_headers"]


def test_pack_box_from_held_returns_invalid_state(api):
    """PRD §3.6: "Packing a box advances it from `SCHEDULED` to `PACKED`; this is permitted only when the box is `SCHEDULED` and when the routing site's `active_subscription_count` does not exceed its `weekly_capacity`."
    PRD §2.7: "An attempt to transition a resource from a state that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/pack_box_from_held_returns_invalid_state
    """
    # Clock strictly before week-1 delivery (default first_delivery_date
    # 2026-07-01) so the hold-window check (priority 8) passes and the box can
    # be placed into HELD; only then is the pack-from-HELD state check exercised.
    ctx = setup_confirmed_subscription(tier="BASELINE", base_price_cents=50000,
                                       week_count=10, clock="2026-06-15T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    box_w1 = box_for_week(sub_id, mh, 1)
    # Place a REFUND hold so the box is HELD, not SCHEDULED.
    get_success_data(api_client.create_vacation_hold(
        create_vacation_hold_payload(sub_id, box_w1["id"]), mh))

    res = api_client.pack_weekly_box(box_w1["id"], FM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    box = validate_success(api_client.get_weekly_box(box_w1["id"], mh), 200)
    assert box["status"] == "HELD", f"box should stay HELD, got {box['status']}"


def test_reopen_closed_season_returns_invalid_state(api):
    """PRD §3.1: "Later, a `FarmManager` may close the season, moving it from `OPEN` to `CLOSED` — permitted only from the `OPEN` state, again surfacing `ERR_INVALID_STATE` otherwise."
    PRD §3.1: "After closing, no new confirmed subscriptions are accepted and further signups are routed to the waitlist; `CLOSED` is terminal."

    Design: Corner/state_machines/open_already_closed_season_returns_invalid_state
    """
    base = setup_open_season(week_count=10, base_price_cents=50000)
    season_id = base["season"]["id"]
    validate_success(api_client.close_season(season_id, FM), 200)

    res = api_client.open_season(season_id, FM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_new_subscription_initial_states(api):
    """PRD §3.3: "A new subscription begins with its billing axis in `PENDING_PAYMENT` and its fulfillment axis in `NOT_STARTED`; its `season_price_cents` and `outstanding_balance_cents` both start at 0."

    Design: Corner/state_machines/new_subscription_initial_states_pending_and_not_started
    """
    base = setup_open_season(week_count=10, base_price_cents=50000,
                             signup_close_date="2026-12-25T00:00:00Z")
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    res = api_client.create_subscription(
        create_subscription_payload(base["season"]["id"], member["id"],
                                    base["share"]["id"], base["site"]["id"]), mh)
    sub = validate_success(res, 201)
    assert sub["billing_status"] == "PENDING_PAYMENT"
    assert sub["fulfillment_status"] == "NOT_STARTED"


def test_clock_past_offer_expiry_fires_expired_transition(api):
    """PRD §3.11: "any `OFFERED` waitlist entry whose `offer_expires_at` has now passed is moved to `EXPIRED`."
    PRD §3.8: "when the clock passes `offer_expires_at` while the entry is still `OFFERED`, the system moves it from `OFFERED` to `EXPIRED`, again leaving the slot open."

    Design: Corner/state_machines/clock_expires_offer_to_expired_system_transition
    """
    # Promote at clock 2026-06-01 → offer_expires_at 2026-06-03; advance past it.
    ctx = setup_offered_waitlist(clock="2026-06-01T00:00:00Z", total_share_capacity=5,
                                 site_weekly_capacity=5, base_price_cents=50000)
    wl_id = ctx["waitlist_entry"]["id"]
    set_clock("2026-06-03T00:00:01Z")
    wl = validate_success(api_client.get_waitlist_entry(wl_id, DC), 200)
    assert wl["status"] == "EXPIRED", (
        f"offer past expiry expected EXPIRED, got {wl['status']}")


def test_accept_waiting_entry_returns_invalid_state(api):
    """PRD §3.8: "The member may accept, which is permitted only while the entry is `OFFERED` and the current clock is at or before `offer_expires_at`; accepting moves the entry from `OFFERED` to `CONVERTED`".
    PRD §2.7: "An attempt to transition a resource from a state that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/accept_waitlist_when_waiting_not_offered_returns_invalid_state
    """
    base = setup_open_season(week_count=10, total_share_capacity=5,
                             site_weekly_capacity=5, base_price_cents=50000,
                             signup_close_date="2026-12-25T00:00:00Z")
    season_id = base["season"]["id"]
    member = register_member(tier="BASELINE")
    mh = make_member_headers(member["id"])
    wl = get_success_data(api_client.create_waitlist_entry(
        create_waitlist_entry_payload(season_id, member["id"],
                                      base["share"]["id"], base["site"]["id"])))
    # Entry is WAITING (never promoted to OFFERED) — accept must be rejected.
    res = api_client.accept_waitlist_entry(wl["id"], mh)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

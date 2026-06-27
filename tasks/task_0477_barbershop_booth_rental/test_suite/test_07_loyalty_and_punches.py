"""Loyalty punches, rewards, and memberships (PRD §3.7).

Covers the checkout -> punch -> reward cascade, the divergent customer counters
(reward vs strike), and the redeem-without-credits guard.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_shop_with_barber_chair_shift,
    setup_shop_with_active_barber,
    checked_in_ticket,
    served_walkin_ticket,
    paid_appointment,
    book_appointment,
    set_lines,
    checkout,
    set_clock,
    TEST_USERS,
)

OWNER = TEST_USERS["shop_owner_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]


def test_checkout_grants_reward_at_threshold(api):
    """PRD §3.7: "If that new count reaches or exceeds the shop's
    `punch_reward_threshold`, the customer earns one reward: `reward_credits` is
    increased by one and `punch_count` is reduced by the threshold amount,
    carrying any surplus forward."

    Design: Difficulty/transitive_cascade/checkout_punch_reward_grant_depth2
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Reward Shop", "tax_rate_pct": 0, "punch_reward_threshold": 1},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    paid_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OWNER), 200)
    assert cust["reward_credits"] == 1, cust
    assert cust["punch_count"] == 0, cust


def test_checkout_punch_below_threshold_no_reward(api):
    """PRD §3.7: "If the new count is still below the threshold, it simply stands
    as the customer's new `punch_count`." "a count one short does not."

    Design: Difficulty/transitive_cascade/checkout_punch_reward_grant_depth2
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Reward Shop", "tax_rate_pct": 0, "punch_reward_threshold": 10},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    paid_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OWNER), 200)
    assert cust["punch_count"] == 1, cust
    assert cust["reward_credits"] == 0, cust


def test_reward_and_strike_counters_diverge(api):
    """PRD §3.7: "On every checkout — after pricing is complete — the customer's
    `punch_count` is incremented by one. If that new count reaches or exceeds the
    shop's `punch_reward_threshold`, the customer earns one reward".
    PRD §3.8: "Marking the no-show moves the appointment `BOOKED → NO_SHOW` and
    always adds one to the customer's `no_show_strikes`."

    Design: Difficulty/dual_variant_calc/customer_punch_reward_vs_no_show_strike_divergent_counters
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "Punch Shop", "tax_rate_pct": 0, "punch_reward_threshold": 1,
            "no_show_strike_limit": 2, "no_show_fee_cents": 2500, "late_grace_minutes": 10,
        },
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    # One prior PAID checkout -> reward_credits=1, punch_count=0.
    paid_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    # Now a no-show on a later appointment drives strikes, not rewards.
    appt2 = book_appointment(ctx, start_utc="2026-06-10T11:00:00Z")
    set_clock("2026-06-10T11:30:00Z")
    validate_success(api.no_show_appointment(appt2["id"], RECEPTION), 200)
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OWNER), 200)
    assert cust["reward_credits"] == 1, cust
    assert cust["punch_count"] == 0, cust
    assert cust["no_show_strikes"] == 1, cust
    assert cust["status"] == "ACTIVE", cust  # 1 < limit 2


def test_strike_counter_unchanged_by_checkout(api):
    """PRD §3.7: "On every checkout — after pricing is complete — the customer's
    `punch_count` is incremented by one."

    Design: Difficulty/dual_variant_calc/customer_punch_reward_vs_no_show_strike_divergent_counters
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Punch Shop", "tax_rate_pct": 0, "punch_reward_threshold": 1},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    paid_appointment(ctx, start_utc="2026-06-10T10:00:00Z")
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OWNER), 200)
    # A checkout drives reward/punch but never touches the no-show strike counter.
    assert cust["no_show_strikes"] == 0, cust
    assert cust["reward_credits"] == 1, cust


def test_redeem_without_credits_rejected(api):
    """PRD §3.6: "if `redeem_reward` is set, the customer's `reward_credits` must
    be at least 1 (`ERR_NO_REWARD_CREDITS`)".

    Design: Corner/validations/redeem_without_credits_returns_no_reward_credits
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "S", "tax_rate_pct": 0,
            "punch_reward_threshold": 10, "punch_reward_value_cents": 3000,
        },
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    _, ticket = checked_in_ticket(ctx, start_utc="2026-06-10T10:00:00Z")
    set_lines(ticket["id"], service_line_ids=[ctx["service"]["id"]], redeem_reward=True)
    res = api.checkout_ticket(ticket["id"], RECEPTION)
    validate_error(res, "ERR_NO_REWARD_CREDITS")

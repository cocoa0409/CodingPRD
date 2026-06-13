"""Pricing engine: forward-looking quote vs chronological settlement.

Covers the dual-variant calculation (quote vs settlement; quote vs strike-count
risk domain), the combinatorial per-participant pipeline (peak then large-group,
round-then-multiply), and the large-group threshold boundary on the quote.
"""
from test_helpers import (
    validate_success,
    setup_confirmed_booking,
    setup_draft_booking,
    mark_present,
    check_in,
    complete,
    confirm_booking,
    no_show,
    make_customer_headers,
)

# Canonical peak window: Wednesdays (bit2 -> mask 4), 12:00-18:00 UTC.
PEAK_MASK_WED = 4
PEAK_START = 720
PEAK_END = 1080
PEAK_SLOT_WED = "2026-07-01T14:00:00Z"   # Wed 2026-07-01 14:00 UTC (inside peak)
OFFPEAK_SLOT = "2026-07-01T09:00:00Z"    # Wed 09:00 UTC (before peak window)


# ─── dual_variant_calc ────────────────────────────────
def test_settlement_diverges_from_quote_on_partial_checkin(api):
    """PRD §3.7: "the large-group step, which here fires only when the *settled count*
    is at least `large_group_threshold` (so a group that booked large but checked in
    small loses the large-group multiplier), multiplying by `large_group_multiplier_bps`,
    dividing by 10000, and flooring."
    PRD §3.7: "when some did not, the settled count is lower and the figure may diverge
    from the quote."

    group_size=4 (>= threshold) quotes with the large-group multiplier (2000 ->x1.5
    ->3000 ->x1.2 ->3600, *4 = 14400); only 3 check in (< threshold) so the settled
    per-participant stays 3000 (2000 ->x1.5 only), *3 = 9000.

    Design: Difficulty/dual_variant_calc/settlement_diverges_from_quote_on_partial_checkin
    """
    ctx = setup_confirmed_booking(
        start_utc=PEAK_SLOT_WED,
        group_size=4,
        num_participants=4,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 5000},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": PEAK_START,
                           "peak_end_minute_of_day": PEAK_END, "large_group_threshold": 4,
                           "peak_multiplier_bps": 15000, "large_group_multiplier_bps": 12000},
    )
    booking, gm, participants = ctx["booking"], ctx["game_masters"][0], ctx["participants"]
    assert booking["quoted_charge_cents"] == 14400

    # Only 3 of 4 present.
    for p in participants[:3]:
        mark_present(p, gm)
    checked = check_in(booking, gm)
    completed = complete(checked, gm)

    assert completed["quoted_charge_cents"] == 14400
    assert completed["final_charge_cents"] == 9000
    assert completed["lifecycle_status"] == "COMPLETED"
    assert completed["payment_status"] == "CAPTURED"


def test_full_group_settlement_equals_quote(api):
    """PRD §3.7: "When every booked participant checked in, the settled count equals
    `group_size` and `final_charge_cents` equals `quoted_charge_cents`."

    The complement of partial divergence: with all 4 present, the settled count keeps
    the large-group multiplier so final_charge_cents == quoted_charge_cents == 14400.

    Design: Difficulty/dual_variant_calc/settlement_diverges_from_quote_on_partial_checkin
    """
    ctx = setup_confirmed_booking(
        start_utc=PEAK_SLOT_WED,
        group_size=4,
        num_participants=4,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 5000},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": PEAK_START,
                           "peak_end_minute_of_day": PEAK_END, "large_group_threshold": 4,
                           "peak_multiplier_bps": 15000, "large_group_multiplier_bps": 12000},
    )
    booking, gm, participants = ctx["booking"], ctx["game_masters"][0], ctx["participants"]
    assert booking["quoted_charge_cents"] == 14400

    for p in participants:
        mark_present(p, gm)
    checked = check_in(booking, gm)
    completed = complete(checked, gm)

    assert completed["final_charge_cents"] == 14400
    assert completed["quoted_charge_cents"] == 14400
    assert completed["lifecycle_status"] == "COMPLETED"


def test_no_show_raises_customer_strike_count(api):
    """PRD §3.8: "The owning customer's `no_show_strike_count` is then recomputed,
    rising by one."
    PRD §2.6: "A customer's `no_show_strike_count` always equals the number of that
    customer's bookings currently in `NO_SHOW`."

    The strike count is a chronological risk-domain aggregate distinct from the cents
    calculation: one NO_SHOW raises the count from 0 to 1.

    Design: Difficulty/dual_variant_calc/customer_strike_count_is_distinct_risk_domain
    """
    ctx = setup_confirmed_booking(
        start_utc=PEAK_SLOT_WED,
        group_size=4,
        num_participants=1,
        venue_overrides={"no_show_fee_pct": 0.5, "no_show_strike_limit": 3},
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 5000},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": PEAK_START,
                           "peak_end_minute_of_day": PEAK_END, "large_group_threshold": 4,
                           "peak_multiplier_bps": 15000, "large_group_multiplier_bps": 12000},
    )
    booking, gm, customer = ctx["booking"], ctx["game_masters"][0], ctx["customer"]
    assert booking["quoted_charge_cents"] == 14400

    no_showed = no_show(booking, gm)
    assert no_showed["lifecycle_status"] == "NO_SHOW"
    assert no_showed["no_show_fee_cents"] == 7200

    cust_after = validate_success(api.get_customer(customer["id"], make_customer_headers(customer["id"])), 200)
    assert cust_after["no_show_strike_count"] == 1


def test_no_show_strike_count_starts_zero_before_any_no_show(api):
    """PRD §3.8: "The owning customer's `no_show_strike_count` is then recomputed,
    rising by one."
    PRD §3.3: "A new customer's `no_show_strike_count` starts at 0."

    Distinguishes the risk domain from the cents domain: with the booking merely
    CONFIRMED (no no-show yet), the strike count remains 0; only the NO_SHOW
    transition increments it.

    Design: Difficulty/dual_variant_calc/customer_strike_count_is_distinct_risk_domain
    """
    ctx = setup_confirmed_booking(
        start_utc=PEAK_SLOT_WED,
        group_size=4,
        num_participants=1,
        venue_overrides={"no_show_fee_pct": 0.5, "no_show_strike_limit": 3},
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 5000},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": PEAK_START,
                           "peak_end_minute_of_day": PEAK_END, "large_group_threshold": 4,
                           "peak_multiplier_bps": 15000, "large_group_multiplier_bps": 12000},
    )
    customer = ctx["customer"]
    cust = validate_success(api.get_customer(customer["id"], make_customer_headers(customer["id"])), 200)
    assert cust["no_show_strike_count"] == 0

    booking, gm = ctx["booking"], ctx["game_masters"][0]
    no_show(booking, gm)
    cust_after = validate_success(api.get_customer(customer["id"], make_customer_headers(customer["id"])), 200)
    assert cust_after["no_show_strike_count"] == 1


# ─── combinatorial_formula ────────────────────────────
def test_quote_chains_peak_then_large_multiplier(api):
    """PRD §3.5: "Only after both per-participant multiplier steps have been floored is
    the per-participant amount multiplied by the `group_size` to form the line total."
    PRD §3.5: "multiply the per-participant amount by `peak_multiplier_bps`, divide by
    10000, and take the floor."

    Pinned chain: 2000 ->(x1.5 floor)3000 ->(x1.2 floor)3600 ->(x4 group)14400.

    Design: Difficulty/combinatorial_formula/price_quote_nested_peak_then_large_multiplier_chain
    """
    ctx = setup_draft_booking(
        start_utc=PEAK_SLOT_WED,
        group_size=4,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 5000},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": PEAK_START,
                           "peak_end_minute_of_day": PEAK_END, "large_group_threshold": 4,
                           "peak_multiplier_bps": 15000, "large_group_multiplier_bps": 12000},
    )
    confirmed = confirm_booking(ctx["booking"], ctx["customer"])
    assert confirmed["quoted_charge_cents"] == 14400
    assert confirmed["lifecycle_status"] == "CONFIRMED"


def test_quote_applies_only_large_multiplier_off_peak(api):
    """PRD §3.5: "Next, if the slot falls in a peak window — meaning there is a pricing
    rule for the booking's `room_id`, the slot's `start_utc` UTC weekday bit is set in
    that rule's `peak_dow_mask`, and the slot's UTC minute-of-day is at least
    `peak_start_minute_of_day` and strictly less than `peak_end_minute_of_day` — multiply
    the per-participant amount by `peak_multiplier_bps`, divide by 10000, and take the
    floor."
    PRD §3.5: "Then, if the intended `group_size` is at least `large_group_threshold`,
    multiply the per-participant amount by `large_group_multiplier_bps`, divide by 10000,
    and take the floor again."

    The peak step is conditional within the pinned chain: off-peak (Wednesday-only mask
    but a 09:00 slot before the peak window) the peak multiplier is skipped and only the
    large-group step fires: 2000 ->(x1.2 floor)2400 ->(x4)9600.

    Design: Difficulty/combinatorial_formula/price_quote_nested_peak_then_large_multiplier_chain
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=4,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 5000},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": PEAK_START,
                           "peak_end_minute_of_day": PEAK_END, "large_group_threshold": 4,
                           "peak_multiplier_bps": 15000, "large_group_multiplier_bps": 12000},
    )
    confirmed = confirm_booking(ctx["booking"], ctx["customer"])
    assert confirmed["quoted_charge_cents"] == 9600
    assert confirmed["lifecycle_status"] == "CONFIRMED"


def test_quote_floors_per_participant_before_multiplying_by_group(api):
    """PRD §3.5: "multiply the per-participant amount by `peak_multiplier_bps`, divide by
    10000, and take the floor."
    PRD §3.5: "Only after both per-participant multiplier steps have been floored is the
    per-participant amount multiplied by the `group_size` to form the line total."

    Round-then-multiply is pinned: floor(2000*13333/10000)=2666, *4 = 10664 — NOT
    multiply-then-floor (floor(8000*1.3333)=10666). Large multiplier disabled
    (threshold 99).

    Design: Difficulty/combinatorial_formula/per_participant_rounding_order_pinned_round_then_multiply
    """
    ctx = setup_draft_booking(
        start_utc=PEAK_SLOT_WED,
        group_size=4,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 0},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": PEAK_START,
                           "peak_end_minute_of_day": PEAK_END, "large_group_threshold": 99,
                           "peak_multiplier_bps": 13333, "large_group_multiplier_bps": 10000},
    )
    confirmed = confirm_booking(ctx["booking"], ctx["customer"])
    assert confirmed["quoted_charge_cents"] == 10664


def test_quote_round_then_multiply_diverges_from_multiply_then_round(api):
    """PRD §3.5: "multiply the per-participant amount by `peak_multiplier_bps`, divide by
    10000, and take the floor."
    PRD §3.5: "Only after both per-participant multiplier steps have been floored is the
    per-participant amount multiplied by the `group_size` to form the line total."

    A second value set where the pinned order is observable: base=1000, peak_bps=15999,
    group=3. Round-then-multiply: floor(1000*15999/10000)=1599, *3 = 4797 — NOT
    multiply-then-floor (floor(3000*1.5999)=4799). Large multiplier disabled.

    Design: Difficulty/combinatorial_formula/per_participant_rounding_order_pinned_round_then_multiply
    """
    ctx = setup_draft_booking(
        start_utc=PEAK_SLOT_WED,
        group_size=3,
        room_overrides={"base_price_cents": 1000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 0},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": PEAK_START,
                           "peak_end_minute_of_day": PEAK_END, "large_group_threshold": 99,
                           "peak_multiplier_bps": 15999, "large_group_multiplier_bps": 10000},
    )
    confirmed = confirm_booking(ctx["booking"], ctx["customer"])
    assert confirmed["quoted_charge_cents"] == 4797


# ─── boundary_precision_check (large-group threshold) ──
def test_large_group_multiplier_applies_at_threshold(api):
    """PRD §3.5: "if the intended `group_size` is at least `large_group_threshold`,
    multiply the per-participant amount by `large_group_multiplier_bps`, divide by
    10000, and take the floor again."

    group_size=4 exactly at large_group_threshold=4 triggers the 1.5x large multiplier:
    base 1000 -> per-participant 1500 -> *4 = 6000.

    Design: Difficulty/boundary_precision_check/large_group_threshold_ge_boundary_on_quote
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=4,
        room_overrides={"base_price_cents": 1000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 0},
        pricing_overrides={"peak_dow_mask": 0, "peak_start_minute_of_day": PEAK_START,
                           "peak_end_minute_of_day": PEAK_END, "large_group_threshold": 4,
                           "peak_multiplier_bps": 10000, "large_group_multiplier_bps": 15000},
    )
    confirmed = confirm_booking(ctx["booking"], ctx["customer"])
    assert confirmed["quoted_charge_cents"] == 6000


def test_large_group_multiplier_not_applied_below_threshold(api):
    """PRD §3.5: "if the intended `group_size` is at least `large_group_threshold`,
    multiply the per-participant amount by `large_group_multiplier_bps`, divide by
    10000, and take the floor again."

    Boundary below: group_size=3 is < large_group_threshold=4, so the large multiplier
    does NOT fire: base 1000 stays per-participant -> *3 = 3000 (not 1500*3=4500).

    Design: Difficulty/boundary_precision_check/large_group_threshold_ge_boundary_on_quote
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=3,
        room_overrides={"base_price_cents": 1000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 0},
        pricing_overrides={"peak_dow_mask": 0, "peak_start_minute_of_day": PEAK_START,
                           "peak_end_minute_of_day": PEAK_END, "large_group_threshold": 4,
                           "peak_multiplier_bps": 10000, "large_group_multiplier_bps": 15000},
    )
    confirmed = confirm_booking(ctx["booking"], ctx["customer"])
    assert confirmed["quoted_charge_cents"] == 3000

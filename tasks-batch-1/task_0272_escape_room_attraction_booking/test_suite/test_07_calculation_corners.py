"""Calculation corners: no-show rounding, private surcharge placement, off-peak
day-of-week predicate, and gift-card balance aggregation.

Corner coverage over the calculations section.
"""
from test_helpers import (
    validate_success,
    setup_confirmed_booking,
    setup_draft_booking,
    create_venue,
    create_gift_card,
    confirm_booking,
    no_show,
    TEST_USERS,
)

MANAGER = TEST_USERS["venue_manager_headers"]

PEAK_MASK_WED = 4
PEAK_SLOT_WED = "2026-07-01T14:00:00Z"   # Wednesday inside 12:00-18:00 peak
THU_SLOT = "2026-07-02T14:00:00Z"        # Thursday (not in a Wed-only mask)
OFFPEAK_SLOT = "2026-07-01T09:00:00Z"


def test_no_show_fee_rounds_half_up(api):
    """PRD §3.8: "The retained fee is computed as the booking's `quoted_charge_cents`
    multiplied by the venue's `no_show_fee_pct`, rounded half up to a whole cent, and
    stored in `no_show_fee_cents`; `final_charge_cents` is set equal to that fee."

    no_show_fee_pct=0.5 on quoted_charge_cents=6001 -> round_half_up(3000.5)=3001
    (the half rounds up, not down).

    Design: Corner/calculations/no_show_fee_round_half_up_boundary
    """
    ctx = setup_confirmed_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=1,
        num_game_masters=1,
        venue_overrides={"no_show_fee_pct": 0.5},
        room_overrides={"base_price_cents": 6001, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    booking, gm = ctx["booking"], ctx["game_masters"][0]
    assert booking["quoted_charge_cents"] == 6001

    no_showed = no_show(booking, gm)
    assert no_showed["no_show_fee_cents"] == 3001
    assert no_showed["final_charge_cents"] == 3001


def test_private_surcharge_added_after_per_participant_multipliers(api):
    """PRD §3.5: "Finally, if `is_private` is true, add the room's
    `private_surcharge_cents` to the line total."
    PRD §3.5: "Only after both per-participant multiplier steps have been floored is the
    per-participant amount multiplied by the `group_size` to form the line total."

    is_private adds private_surcharge_cents=5000 once, AFTER the per-participant peak and
    large steps and the group multiply: 2000 ->3000 ->3600, *4 = 14400, +5000 = 19400.

    Design: Corner/calculations/private_surcharge_added_after_per_participant_multipliers
    """
    ctx = setup_draft_booking(
        start_utc=PEAK_SLOT_WED,
        group_size=4,
        is_private=True,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 5000},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": 720,
                           "peak_end_minute_of_day": 1080, "large_group_threshold": 4,
                           "peak_multiplier_bps": 15000, "large_group_multiplier_bps": 12000},
    )
    confirmed = confirm_booking(ctx["booking"], ctx["customer"])
    assert confirmed["quoted_charge_cents"] == 19400


def test_off_peak_day_not_in_mask_uses_base_rate(api):
    """PRD §3.5: "if the slot falls in a peak window — meaning there is a pricing rule for
    the booking's `room_id`, the slot's `start_utc` UTC weekday bit is set in that rule's
    `peak_dow_mask`, and the slot's UTC minute-of-day is at least `peak_start_minute_of_day`
    and strictly less than `peak_end_minute_of_day` — multiply the per-participant amount
    by `peak_multiplier_bps`."

    A Thursday slot against a Wednesday-only mask (4) fails the weekday predicate, so the
    peak multiplier is skipped: group 2 at base 2000 -> quote 4000.

    Design: Corner/calculations/off_peak_dow_not_in_mask_uses_base_rate
    """
    ctx = setup_draft_booking(
        start_utc=THU_SLOT,
        group_size=2,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
        pricing_overrides={"peak_dow_mask": PEAK_MASK_WED, "peak_start_minute_of_day": 720,
                           "peak_end_minute_of_day": 1080, "large_group_threshold": 99,
                           "peak_multiplier_bps": 15000, "large_group_multiplier_bps": 10000},
    )
    confirmed = confirm_booking(ctx["booking"], ctx["customer"])
    assert confirmed["quoted_charge_cents"] == 4000


def test_gift_card_balance_aggregates_topup(api):
    """PRD §3.9: "A manager may manually top up a card by submitting an `amount_cents`,
    which appends a `TOPUP` entry and recomputes `balance_cents`."
    PRD §3.9: "its `balance_cents` is the running total of `initial_balance_cents` plus
    the signed sum of every ledger entry written against it — across all entries, with no
    status filter."

    A +1500 TOPUP on a 5000 card aggregates to balance_cents == 6500.

    Design: Corner/calculations/giftcard_balance_aggregates_topup_entry
    """
    venue = create_venue()
    gc = create_gift_card(venue["id"], initial_balance_cents=5000)
    topped = validate_success(api.top_up_gift_card(
        gc["id"], {"amount_cents": 1500, "expected_gift_card_version": gc["version"]}, MANAGER), 200)
    assert topped["balance_cents"] == 6500

"""Lane/bay pricing, party-package, food, deposit, and refund calculations.

Covers Difficulty queue: dual_variant_calc, combinatorial_formula,
boundary_precision_check (pricing + cancellation), and Corner calculation
instances (deposit precision, refund tiers, peak multiplier).
"""

from test_helpers import (
    validate_success,
    validate_error,
    create_rate_card_payload,
    create_lane_payload,
    create_customer_payload,
    create_party_package_payload,
    create_food_item_payload,
    create_reservation_payload,
    create_food_line_payload,
    create_league_payload,
    create_league_night_payload,
    set_clock,
    CM, FD, LA,
)


# =============================================================================
# Difficulty / dual_variant_calc
# =============================================================================
def test_per_game_and_per_hour_lane_charge_diverge(api):
    """PRD §3.3: "Under `PER_GAME` pricing, the lane charge is `per_game_cents`
    multiplied by `game_count` multiplied by `bowler_count`; the duration and any
    peak surcharge are ignored entirely."
    PRD §3.3: "The per-hour lane charge is the block count multiplied by that
    hourly rate, rounded half-up to whole cents; `game_count` plays no part in
    per-hour pricing."

    Design: Difficulty/dual_variant_calc/reservation_per_game_vs_per_hour_diverge
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Std", per_game_cents=800, per_hour_cents=3000, block_minutes=60,
        peak_multiplier_bps=12000, peak_start_hour=18, peak_end_hour=23,
        deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(max_bowlers=6), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)

    res_game = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-07-01T18:00:00.000Z", end_at="2026-07-01T19:30:00.000Z",
        bowler_count=4, game_count=3), FD), 201)
    res_hour = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_HOUR",
        start_at="2026-07-01T20:00:00.000Z", end_at="2026-07-01T21:30:00.000Z",
        bowler_count=4, game_count=3), FD), 201)

    held_game = validate_success(api.hold_reservation(res_game["id"], FD), 200)
    held_hour = validate_success(api.hold_reservation(res_hour["id"], FD), 200)

    assert held_game["lane_subtotal_cents"] == 9600
    assert held_hour["lane_subtotal_cents"] == 7200
    assert held_game["lane_subtotal_cents"] != held_hour["lane_subtotal_cents"]


def test_league_season_quote_diverges_from_chronological_accrual(api):
    """PRD §3.8: "On activation the system computes the forward-looking quote:
    `season_fee_quote_cents` is `weekly_fee_cents` multiplied by
    `season_night_count`, the projection that assumes every planned night will
    accrue its fee regardless of per-night outcome."
    PRD §3.8: "Closing finalizes `season_fee_accrued_cents` as the chronological
    sum of `night_fee_cents` over every night that actually resolved as `PLAYED`
    or `FORFEITED`; rained-out nights contribute zero."

    Design: Difficulty/dual_variant_calc/league_season_quote_vs_accrual_diverge
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Lg", per_game_cents=500, per_hour_cents=2000), CM), 201)
    lanes = [validate_success(api.create_lane(create_lane_payload(), CM), 201) for _ in range(4)]
    assert len(lanes) == 4
    league = validate_success(api.create_league(create_league_payload(
        rc["id"], season_night_count=4, lanes_per_night=1, weekly_fee_cents=5000), LA), 201)
    windows = [
        ("2026-07-02T18:00:00.000Z", "2026-07-02T20:00:00.000Z"),
        ("2026-07-09T18:00:00.000Z", "2026-07-09T20:00:00.000Z"),
        ("2026-07-16T18:00:00.000Z", "2026-07-16T20:00:00.000Z"),
        ("2026-07-23T18:00:00.000Z", "2026-07-23T20:00:00.000Z"),
    ]
    nights = []
    for i, (s, e) in enumerate(windows):
        n = validate_success(api.create_league_night(create_league_night_payload(
            league["id"], night_index=i + 1, start_at=s, end_at=e), LA), 201)
        nights.append(n)

    activated = validate_success(api.activate_league(league["id"], LA), 200)
    assert activated["season_fee_quote_cents"] == 20000

    set_clock("2026-07-24T00:00:00.000Z")
    validate_success(api.mark_played_league_night(nights[0]["id"], LA), 200)
    validate_success(api.mark_played_league_night(nights[1]["id"], LA), 200)
    validate_success(api.forfeit_league_night(nights[2]["id"], LA), 200)
    validate_success(api.rain_out_league_night(nights[3]["id"], LA), 200)

    closed = validate_success(api.close_league(league["id"], LA), 200)
    assert closed["season_fee_quote_cents"] == 20000
    assert closed["season_fee_accrued_cents"] == 15000
    assert closed["season_fee_quote_cents"] != closed["season_fee_accrued_cents"]


# =============================================================================
# Difficulty / combinatorial_formula
# =============================================================================
def test_party_package_tiered_guest_charge(api):
    """PRD §3.4: "The billable guests are computed by first clamping `guest_count`
    to the package's `max_guests` — taking the smaller of the two — and then
    subtracting `included_guests`, with the result floored at zero so a small
    party never produces a negative count. The package charge is the package's
    `base_cents` plus those billable guests multiplied by `extra_guest_cents`."

    Design: Difficulty/combinatorial_formula/party_package_tiered_guest_charge_mode_a
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Party", per_game_cents=0, per_hour_cents=0, block_minutes=60,
        deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(max_bowlers=6), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    pp = validate_success(api.create_party_package(create_party_package_payload(
        name="Birthday Bash", base_cents=15000, included_guests=8,
        extra_guest_cents=1200, max_guests=20, included_lane_hours=2), CM), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        party_package_id=pp["id"], pricing_mode="PER_GAME",
        start_at="2026-07-05T14:00:00.000Z", end_at="2026-07-05T16:00:00.000Z",
        bowler_count=6, game_count=0, guest_count=12), FD), 201)

    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    # base 15000 + max(0, min(12,20)-8) * 1200 = 15000 + 4*1200 = 19800
    assert held["package_subtotal_cents"] == 19800


def test_food_total_rounds_per_line_then_sums(api):
    """PRD §3.4: "tax is computed and rounded per line, and only then are the
    lines summed — rounding per line before summing, never summing first and
    rounding once."
    PRD §3.4: "the tax is that gross multiplied by 825 basis points, divided by
    ten thousand, and rounded half-up to whole cents, and if it is not taxable
    the tax is zero; the line's `line_total_cents` is gross plus that rounded tax."

    Design: Difficulty/combinatorial_formula/food_total_round_per_line_then_sum_mode_b
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Food", per_game_cents=0, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    fi1 = validate_success(api.create_food_item(create_food_item_payload(
        name="Nachos", unit_cents=199, taxable=True), CM), 201)
    fi2 = validate_success(api.create_food_item(create_food_item_payload(
        name="Soda", unit_cents=199, taxable=True), CM), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-07-06T12:00:00.000Z", end_at="2026-07-06T13:00:00.000Z",
        bowler_count=2, game_count=0), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)

    line1 = validate_success(api.create_food_line(
        create_food_line_payload(res["id"], fi1["id"], 3), FD), 201)
    line2 = validate_success(api.create_food_line(
        create_food_line_payload(res["id"], fi2["id"], 3), FD), 201)
    # gross 597, tax round_half_up(597*825/10000=49.25)=49 -> line 646 each
    assert line1["line_total_cents"] == 646
    assert line2["line_total_cents"] == 646

    fetched = validate_success(api.get_reservation(res["id"], FD), 200)
    assert fetched["food_subtotal_cents"] == 1292  # round-per-line-then-sum, not 1293


# =============================================================================
# Difficulty / boundary_precision_check
# =============================================================================
def test_per_hour_block_boundary_60_vs_61_minutes(api):
    """PRD §3.3: "the duration is divided by the rate card's `block_minutes` and
    rounded up to the next whole block — so a duration equal to one block bills as
    one block, and a duration one minute over a whole number of blocks bills as
    one more block."

    Design: Difficulty/boundary_precision_check/per_hour_block_boundary_60_vs_61_minutes
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Block", per_game_cents=0, per_hour_cents=3000, block_minutes=60,
        peak_multiplier_bps=10000, peak_start_hour=18, peak_end_hour=23,
        deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)

    r60 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_HOUR",
        start_at="2026-08-05T12:00:00.000Z", end_at="2026-08-05T13:00:00.000Z",
        bowler_count=2), FD), 201)
    r61 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_HOUR",
        start_at="2026-08-05T14:00:00.000Z", end_at="2026-08-05T15:01:00.000Z",
        bowler_count=2), FD), 201)

    held60 = validate_success(api.hold_reservation(r60["id"], FD), 200)
    held61 = validate_success(api.hold_reservation(r61["id"], FD), 200)
    assert held60["lane_subtotal_cents"] == 3000   # 1 block
    assert held61["lane_subtotal_cents"] == 6000   # 2 blocks


def test_cancellation_notice_24h_boundary_full_refund(api):
    """PRD §3.6: "The refund tiers are pinned at their boundaries with at-least
    comparisons: when the notice is at least 1440 minutes (a full 24 hours), the
    refund credited to `refund_cents` is the entire `held_deposit_cents`".

    Design: Difficulty/boundary_precision_check/cancellation_notice_window_24h_boundary_ge
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Cxl", per_game_cents=800, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-10T18:00:00.000Z", end_at="2026-08-10T19:00:00.000Z",
        bowler_count=4, game_count=3), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    assert held["held_deposit_cents"] == 1920  # 9600 * 20%

    # cancelled_at exactly 1440 minutes (24h) before start -> full refund
    set_clock("2026-08-09T18:00:00.000Z")
    cancelled = validate_success(api.cancel_reservation(res["id"], FD), 200)
    assert cancelled["refund_cents"] == 1920


# =============================================================================
# Corner / calculations
# =============================================================================
def test_deposit_rounds_half_up(api):
    """PRD §3.4: "The **deposit** captured at hold, `held_deposit_cents`, is the
    quoted total multiplied by the pinned rate card's `deposit_pct_bps`, divided
    by ten thousand, and rounded half-up to whole cents."

    Design: Corner/calculations/deposit_rounds_half_up
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="C1", per_game_cents=1921, per_hour_cents=0, deposit_pct_bps=2500), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-13T18:00:00.000Z", end_at="2026-09-13T19:00:00.000Z",
        bowler_count=1, game_count=5), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    assert held["quoted_total_cents"] == 9605
    # 9605 * 2500 / 10000 = 2401.25 -> round_half_up -> 2401
    assert held["held_deposit_cents"] == 2401


def test_cancellation_partial_refund_tier_50pct(api):
    """PRD §3.6: "otherwise, when the notice is at least 120 minutes (2 hours), the
    refund is half the held deposit — `held_deposit_cents` multiplied by 5000
    basis points, divided by ten thousand, rounded half-up to whole cents".

    Design: Corner/calculations/cancellation_partial_refund_tier_50pct
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="C2", per_game_cents=800, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-14T18:00:00.000Z", end_at="2026-09-14T19:00:00.000Z",
        bowler_count=4, game_count=3), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    # 200 minutes notice -> 50% tier; deposit 1920 -> refund 960
    set_clock("2026-09-14T14:40:00.000Z")
    cancelled = validate_success(api.cancel_reservation(res["id"], FD), 200)
    assert cancelled["refund_cents"] == 960


def test_cancellation_forfeit_tier_zero_refund(api):
    """PRD §3.6: "and with less than 120 minutes of notice the refund is zero and
    the deposit is forfeited."

    Design: Corner/calculations/cancellation_forfeit_tier_zero_refund
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="C3", per_game_cents=800, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-15T18:00:00.000Z", end_at="2026-09-15T19:00:00.000Z",
        bowler_count=4, game_count=3), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    # 60 minutes notice -> forfeit tier -> refund 0
    set_clock("2026-09-15T17:00:00.000Z")
    cancelled = validate_success(api.cancel_reservation(res["id"], FD), 200)
    assert cancelled["refund_cents"] == 0


def test_per_hour_peak_multiplier_applied(api):
    """PRD §3.3: "during peak it is `per_hour_cents` scaled by `peak_multiplier_bps`
    divided by ten thousand. The per-hour lane charge is the block count
    multiplied by that hourly rate, rounded half-up to whole cents".

    Design: Corner/calculations/per_hour_peak_multiplier_applied
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="C4", per_game_cents=0, per_hour_cents=3000, block_minutes=60,
        peak_multiplier_bps=12000, peak_start_hour=18, peak_end_hour=23,
        deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_HOUR",
        start_at="2026-09-16T18:00:00.000Z", end_at="2026-09-16T19:30:00.000Z",
        bowler_count=2), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    # 90 min -> 2 blocks; peak 18:00 in [18,23) -> 3000*1.2=3600; 2*3600=7200
    assert held["lane_subtotal_cents"] == 7200


def test_party_guest_count_above_max_rejected(api):
    """PRD §3.3: "A party that overruns the resource cap, or whose `guest_count`
    exceeds the chosen package's `max_guests`, is rejected with
    `ERR_CAPACITY_EXCEEDED`; the specific case of a party `guest_count` above the
    package's `max_guests` is reported as `ERR_PARTY_GUESTS_EXCEED_MAX`."

    Design: Corner/calculations/party_guest_count_above_max_rejected
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="C5", per_game_cents=0, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(max_bowlers=6), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    pp = validate_success(api.create_party_package(create_party_package_payload(
        name="Big Bash", base_cents=10000, included_guests=8, extra_guest_cents=1000,
        max_guests=20, included_lane_hours=2), CM), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        party_package_id=pp["id"], pricing_mode="PER_GAME",
        start_at="2026-09-17T14:00:00.000Z", end_at="2026-09-17T16:00:00.000Z",
        bowler_count=6, game_count=0, guest_count=25), FD), 201)
    res2 = api.hold_reservation(res["id"], FD)
    validate_error(res2, "ERR_PARTY_GUESTS_EXCEED_MAX", expected_status=409)


# =============================================================================
# Difficulty — second tests (distinct PRD-derivable facet per instance)
# =============================================================================
def test_per_game_lane_subtotal_flows_into_quoted_total(api):
    """PRD §3.3: "Under `PER_GAME` pricing, the lane charge is `per_game_cents`
    multiplied by `game_count` multiplied by `bowler_count`".
    PRD §3.4: "The reservation's **quoted total**, in `quoted_total_cents`, is
    simply the sum of the four subtotals — `lane_subtotal_cents` plus
    `package_subtotal_cents` plus `food_subtotal_cents` plus
    `rental_subtotal_cents`".

    Design: Difficulty/dual_variant_calc/reservation_per_game_vs_per_hour_diverge
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Std", per_game_cents=800, per_hour_cents=3000, block_minutes=60,
        peak_multiplier_bps=12000, peak_start_hour=18, peak_end_hour=23,
        deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(max_bowlers=6), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res_game = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-07-01T18:00:00.000Z", end_at="2026-07-01T19:30:00.000Z",
        bowler_count=4, game_count=3), FD), 201)
    held = validate_success(api.hold_reservation(res_game["id"], FD), 200)
    assert held["lane_subtotal_cents"] == 9600
    # no package/food/rental -> quoted equals the lane subtotal
    assert held["quoted_total_cents"] == 9600


def test_league_forward_quote_computed_at_activation(api):
    """PRD §3.8: "On activation the system computes the forward-looking quote:
    `season_fee_quote_cents` is `weekly_fee_cents` multiplied by
    `season_night_count`, the projection that assumes every planned night will
    accrue its fee regardless of per-night outcome."

    Design: Difficulty/dual_variant_calc/league_season_quote_vs_accrual_diverge
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Lg2", per_game_cents=0, per_hour_cents=0), CM), 201)
    validate_success(api.create_lane(create_lane_payload(), CM), 201)
    league = validate_success(api.create_league(create_league_payload(
        rc["id"], season_night_count=4, lanes_per_night=1, weekly_fee_cents=5000), LA), 201)
    validate_success(api.create_league_night(create_league_night_payload(
        league["id"], night_index=1,
        start_at="2026-07-02T18:00:00.000Z", end_at="2026-07-02T20:00:00.000Z"), LA), 201)
    activated = validate_success(api.activate_league(league["id"], LA), 200)
    # forward-looking projection: 5000 * 4 = 20000, regardless of per-night outcome
    assert activated["season_fee_quote_cents"] == 20000
    assert activated["status"] == "ACTIVE"


def test_party_package_billable_floored_at_zero_for_small_party(api):
    """PRD §3.4: "subtracting `included_guests`, with the result floored at zero so
    a small party never produces a negative count. The package charge is the
    package's `base_cents` plus those billable guests multiplied by
    `extra_guest_cents`."

    Design: Difficulty/combinatorial_formula/party_package_tiered_guest_charge_mode_a
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Party2", per_game_cents=0, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(max_bowlers=6), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    pp = validate_success(api.create_party_package(create_party_package_payload(
        name="Small Bash", base_cents=15000, included_guests=8,
        extra_guest_cents=1200, max_guests=20, included_lane_hours=2), CM), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        party_package_id=pp["id"], pricing_mode="PER_GAME",
        start_at="2026-07-05T14:00:00.000Z", end_at="2026-07-05T16:00:00.000Z",
        bowler_count=6, game_count=0, guest_count=5), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    # max(0, min(5,20)-8) = 0 billable -> base only
    assert held["package_subtotal_cents"] == 15000


def test_food_single_taxable_line_total(api):
    """PRD §3.4: "For each food line, the gross is `unit_cents_snapshot` multiplied
    by `quantity`; if the line is taxable per its `taxable_snapshot`, the tax is
    that gross multiplied by 825 basis points, divided by ten thousand, and
    rounded half-up to whole cents ... the line's `line_total_cents` is gross plus
    that rounded tax."

    Design: Difficulty/combinatorial_formula/food_total_round_per_line_then_sum_mode_b
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Food2", per_game_cents=0, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    fi = validate_success(api.create_food_item(create_food_item_payload(
        name="Nachos", unit_cents=199, taxable=True), CM), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-07-06T12:00:00.000Z", end_at="2026-07-06T13:00:00.000Z",
        bowler_count=2, game_count=0), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    line = validate_success(api.create_food_line(
        create_food_line_payload(res["id"], fi["id"], 3), FD), 201)
    # gross 597, tax round_half_up(597*825/10000=49.25)=49 -> 646
    assert line["line_total_cents"] == 646


def test_per_hour_block_boundary_120_vs_121_minutes(api):
    """PRD §3.3: "the duration is divided by the rate card's `block_minutes` and
    rounded up to the next whole block — so a duration equal to one block bills as
    one block, and a duration one minute over a whole number of blocks bills as
    one more block."

    Design: Difficulty/boundary_precision_check/per_hour_block_boundary_60_vs_61_minutes
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Block2", per_game_cents=0, per_hour_cents=3000, block_minutes=60,
        peak_multiplier_bps=10000, peak_start_hour=18, peak_end_hour=23,
        deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    r120 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_HOUR",
        start_at="2026-08-05T12:00:00.000Z", end_at="2026-08-05T14:00:00.000Z",
        bowler_count=2), FD), 201)
    r121 = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_HOUR",
        start_at="2026-08-05T15:00:00.000Z", end_at="2026-08-05T17:01:00.000Z",
        bowler_count=2), FD), 201)
    held120 = validate_success(api.hold_reservation(r120["id"], FD), 200)
    held121 = validate_success(api.hold_reservation(r121["id"], FD), 200)
    assert held120["lane_subtotal_cents"] == 6000   # exactly 2 blocks
    assert held121["lane_subtotal_cents"] == 9000   # 3 blocks


def test_cancellation_notice_1439_minutes_drops_to_partial_tier(api):
    """PRD §3.6: "when the notice is at least 1440 minutes (a full 24 hours), the
    refund credited to `refund_cents` is the entire `held_deposit_cents`;
    otherwise, when the notice is at least 120 minutes (2 hours), the refund is
    half the held deposit".

    Just below the 1440-minute boundary (1439 min) the full-refund tier no longer
    applies and the 50% tier governs, proving the boundary is `>=`.

    Design: Difficulty/boundary_precision_check/cancellation_notice_window_24h_boundary_ge
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="Cxl2", per_game_cents=800, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-08-10T18:00:00.000Z", end_at="2026-08-10T19:00:00.000Z",
        bowler_count=4, game_count=3), FD), 201)
    held = validate_success(api.hold_reservation(res["id"], FD), 200)
    assert held["held_deposit_cents"] == 1920
    # 1439 minutes before start (start - 1439 min = 2026-08-09T18:01:00Z)
    set_clock("2026-08-09T18:01:00.000Z")
    cancelled = validate_success(api.cancel_reservation(res["id"], FD), 200)
    # below 1440 but >= 120 -> 50% tier -> 960
    assert cancelled["refund_cents"] == 960

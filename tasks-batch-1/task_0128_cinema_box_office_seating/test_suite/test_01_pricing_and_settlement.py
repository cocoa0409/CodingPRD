"""Ticket pricing variants and distributor settlement splits.

Covers the dual-variant calculation rule (provisional vs final ticket price;
first-window vs aged distributor split) and the combinatorial formula rule
(minimum-guarantee floor via max(); round-per-combo-then-sum).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    make_member_headers,
    validate_success,
)
from test_helpers import fixtures as fx

MANAGER = TEST_USERS["manager_headers"]
AGENT = TEST_USERS["agent_headers"]


# ===========================================================================
# Difficulty/dual_variant_calc/ticket_provisional_vs_final_diverge_on_reprice
# ===========================================================================

def test_provisional_locked_at_hold_under_standard_profile(api):
    """PRD §3.4: "Each ticket is quoted a provisional price at this moment,
    stored on provisional_price_cents: the showtime's current base fare is
    multiplied by the profile multiplier for its current pricing profile and
    the product is rounded half up to whole cents, after which the seat-class
    surcharge is added as an integer (multiply and round first, then add the
    surcharge)."

    Design: Difficulty/dual_variant_calc/ticket_provisional_vs_final_diverge_on_reprice
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000, pricing_profile="STANDARD")
    member = fx.make_member()
    order = fx.create_held_order(ctx["showtime"], member, ctx["seat_ids"][:1])

    tickets = get_success_data(api.list_order_tickets(order["id"], MANAGER))
    assert len(tickets) == 1
    # STANDARD multiplier 1.00 on base 1000, STANDARD seat surcharge 0.
    assert tickets[0]["provisional_price_cents"] == 1000


def test_final_price_relocks_after_reprice_to_peak(api):
    """PRD §3.5: "the current base fare times the current profile multiplier,
    rounded half up to whole cents, plus the seat-class surcharge as an integer."
    PRD §3.2: "Re-pricing updates the stored profile and base fare and increments
    the showtime's version. Because final ticket prices are read from the showtime
    at payment time (Section 3.5), a re-price between hold and payment changes what
    a customer ultimately pays."

    Design: Difficulty/dual_variant_calc/ticket_provisional_vs_final_diverge_on_reprice
    """
    ctx = fx.setup_on_sale_showtime(base_price_cents=1000, pricing_profile="STANDARD")
    member = fx.make_member()
    order = fx.create_held_order(ctx["showtime"], member, ctx["seat_ids"][:1])

    # Manager re-prices to PEAK before payment.
    get_success_data(api.reprice_showtime(ctx["showtime"]["id"], {"pricing_profile": "PEAK"}, MANAGER))

    paid = get_success_data(api.pay_order(order["id"], AGENT))

    tickets = get_success_data(api.list_order_tickets(order["id"], MANAGER))
    assert len(tickets) == 1
    # Provisional was quoted under STANDARD (1000); final re-read under PEAK (round(1000*1.30)=1300).
    assert tickets[0]["provisional_price_cents"] == 1000
    assert tickets[0]["final_price_cents"] == 1300
    assert paid["tickets_subtotal_cents"] == 1300


# ===========================================================================
# Difficulty/dual_variant_calc/distributor_split_first_window_vs_aged
# ===========================================================================

def _close_at_gross(*, base_price_cents, num_seats, starts_at, close_at, split_schedule):
    return fx.setup_closed_box_office_showtime(
        base_price_cents=base_price_cents,
        num_seats=num_seats,
        starts_at=starts_at,
        close_at=close_at,
        split_schedule=split_schedule,
    )


def test_first_window_settlement_uses_week0_high_pct(api):
    """PRD §3.9: "From the film's split_schedule, the system selects the
    applied_distributor_pct as the percentage attached to the term with the
    greatest week_index that is still less than or equal to the screening's week
    index — so the distributor's share slides downward as the film ages."
    PRD §3.9: "The sliding distributor amount is the gross receipts multiplied by
    that selected percentage, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/distributor_split_first_window_vs_aged
    """
    schedule = [{"week_index": 0, "distributor_pct": 0.70}, {"week_index": 3, "distributor_pct": 0.35}]
    # release 2026-06-01, starts 2026-06-04 -> week 0. Base 3000 x 2 seats = 6000 gross.
    ctx = _close_at_gross(
        base_price_cents=3000, num_seats=2,
        starts_at="2026-06-04T13:00:00.000Z", close_at="2026-06-04T16:00:00.000Z",
        split_schedule=schedule,
    )
    s = ctx["settlement"]
    assert s["gross_receipts_cents"] == 6000
    assert s["applied_distributor_pct"] == 0.70
    assert s["distributor_share_cents"] == 4200
    assert s["house_share_cents"] == 1800


def test_aged_settlement_uses_later_low_pct(api):
    """PRD §3.9: "From the film's split_schedule, the system selects the
    applied_distributor_pct as the percentage attached to the term with the
    greatest week_index that is still less than or equal to the screening's week
    index — so the distributor's share slides downward as the film ages."
    PRD §3.9: "The house_share_cents is the gross receipts minus the distributor
    share, which may be negative if the minimum guarantee exceeds the gross."

    Design: Difficulty/dual_variant_calc/distributor_split_first_window_vs_aged
    """
    schedule = [{"week_index": 0, "distributor_pct": 0.70}, {"week_index": 3, "distributor_pct": 0.35}]
    # release 2026-06-01, starts 2026-06-25 -> week 3 (24 days // 7 = 3). 6000 gross.
    ctx = _close_at_gross(
        base_price_cents=3000, num_seats=2,
        starts_at="2026-06-25T13:00:00.000Z", close_at="2026-06-25T16:00:00.000Z",
        split_schedule=schedule,
    )
    s = ctx["settlement"]
    assert s["gross_receipts_cents"] == 6000
    assert s["applied_distributor_pct"] == 0.35
    assert s["distributor_share_cents"] == 2100
    assert s["house_share_cents"] == 3900


# ===========================================================================
# Difficulty/combinatorial_formula/distributor_share_min_max_mg_floor
# ===========================================================================

def test_minimum_guarantee_floors_distributor_share(api):
    """PRD §3.9: "The settlement's distributor_share_cents is then the larger of
    that sliding amount and the distributor's minimum_guarantee_cents floor."

    Design: Difficulty/combinatorial_formula/distributor_share_min_max_mg_floor
    """
    schedule = [{"week_index": 0, "distributor_pct": 0.70}, {"week_index": 3, "distributor_pct": 0.35}]
    # week 3 pct 0.35; base 2000 x 2 = 4000 gross; sliding = 1400 < MG 2000.
    ctx = fx.setup_closed_box_office_showtime(
        base_price_cents=2000, num_seats=2,
        starts_at="2026-06-25T13:00:00.000Z", close_at="2026-06-25T16:00:00.000Z",
        split_schedule=schedule, minimum_guarantee_cents=2000,
    )
    s = ctx["settlement"]
    assert s["gross_receipts_cents"] == 4000
    assert s["applied_distributor_pct"] == 0.35
    assert s["distributor_share_cents"] == 2000  # MG floor wins over sliding 1400
    assert s["house_share_cents"] == 2000


def test_sliding_share_wins_when_above_minimum_guarantee(api):
    """PRD §3.9: "The settlement's distributor_share_cents is then the larger of
    that sliding amount and the distributor's minimum_guarantee_cents floor."

    Design: Difficulty/combinatorial_formula/distributor_share_min_max_mg_floor
    """
    schedule = [{"week_index": 0, "distributor_pct": 0.70}]
    # week 0 pct 0.70; base 3000 x 2 = 6000 gross; sliding = 4200 > MG 2000.
    ctx = fx.setup_closed_box_office_showtime(
        base_price_cents=3000, num_seats=2,
        starts_at="2026-06-04T13:00:00.000Z", close_at="2026-06-04T16:00:00.000Z",
        split_schedule=schedule, minimum_guarantee_cents=2000,
    )
    s = ctx["settlement"]
    assert s["gross_receipts_cents"] == 6000
    assert s["distributor_share_cents"] == 4200  # sliding wins over MG 2000
    assert s["house_share_cents"] == 1800


# ===========================================================================
# Difficulty/combinatorial_formula/combo_discount_round_then_sum
# ===========================================================================

def test_combo_discount_rounded_per_combo_then_summed(api):
    """PRD §3.5: "combos_subtotal_cents is computed combo by combo: for a member
    whose tier is SILVER or GOLD, each combo's charge is its price_cents minus the
    combo's member_discount_pct of that price rounded half up to whole cents, and
    these per-combo discounted prices are summed; the per-combo discount is rounded
    before the sum, never the other way around."

    Design: Difficulty/combinatorial_formula/combo_discount_round_then_sum
    """
    base = fx.setup_base(seat_count=8)
    aud_id = base["auditorium"]["id"]
    film_id = base["film"]["id"]
    c1 = fx.make_combo(name="Combo C1", price_cents=995, member_discount_pct=0.125)
    c2 = fx.make_combo(name="Combo C2", price_cents=995, member_discount_pct=0.125)

    member = fx.make_silver_member(aud_id, film_id)
    assert member["tier"] == "SILVER"
    assert member["loyalty_points"] == 50

    # Target showtime in a non-overlapping window.
    target_st = fx.schedule_showtime(
        aud_id, film_id, starts_at="2026-06-06T20:00:00.000Z",
        pricing_profile="STANDARD", base_price_cents=1000,
    )
    opened = fx.open_showtime(target_st["id"])
    seat0 = fx.get_seat_ids(target_st["id"], count=1)

    # combos_subtotal_cents is computed at payment (PRD §3.5: "The order total is
    # then computed..." under "At payment"), so pay before reading it.
    order = fx.create_paid_order(opened, member, seat0, combo_ids=[c1["id"], c2["id"]])

    # round(995 * 0.125) = round(124.375) = 124; 995 - 124 = 871 per combo; 871 + 871 = 1742.
    assert order["combos_subtotal_cents"] == 1742
    assert order["tickets_subtotal_cents"] == 1000


def test_silver_member_combo_discount_applied(api):
    """PRD §3.3: "an optional member_discount_pct, a fraction between 0 and 1
    inclusive (defaulting to 0) that applies only to members of tier SILVER or GOLD."
    PRD §3.5: "each combo's charge is its price_cents minus the combo's
    member_discount_pct of that price rounded half up to whole cents, and these
    per-combo discounted prices are summed; the per-combo discount is rounded
    before the sum, never the other way around."

    Design: Difficulty/combinatorial_formula/combo_discount_round_then_sum
    """
    base = fx.setup_base(seat_count=8)
    aud_id = base["auditorium"]["id"]
    film_id = base["film"]["id"]
    combo = fx.make_combo(name="Single", price_cents=995, member_discount_pct=0.125)

    member = fx.make_silver_member(aud_id, film_id)
    assert member["tier"] == "SILVER"

    target_st = fx.schedule_showtime(
        aud_id, film_id, starts_at="2026-06-06T20:00:00.000Z",
        pricing_profile="STANDARD", base_price_cents=1000,
    )
    opened = fx.open_showtime(target_st["id"])
    seat0 = fx.get_seat_ids(target_st["id"], count=1)

    # combos_subtotal_cents is computed at payment (PRD §3.5), so pay before reading it.
    order = fx.create_paid_order(opened, member, seat0, combo_ids=[combo["id"]])
    # Single SILVER combo: 995 - round(124.375)=124 -> 871.
    assert order["combos_subtotal_cents"] == 871

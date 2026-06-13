"""Pricing engine: labor surcharge, tiered grocery markup, per-line round-then-sum
actual grocery, estimated-vs-actual divergence, deposit freezing, and payment mismatches.

Queue A / Difficulty: dual_variant_calc (booking ingredient), combinatorial_formula.
Queue B / Corner: calculations, validations.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    make_chef_headers, make_client_headers,
    setup_confirmed_booking, setup_confirmed_with_finalized_grocery,
    setup_confirmed_with_deposit_paid,
    open_grocery_run, finalize_grocery_run, pay_deposit,
)


# ─── Difficulty / dual_variant_calc: booking ingredient estimated vs actual ──

def test_booking_estimated_and_actual_grocery_diverge_and_move_quote(api):
    """PRD §3.4: "`estimated_grocery_total_cents` is the estimated ingredient subtotal
    (the same `estimated_ingredient_per_guest_cents` times `party_size`) multiplied by one
    plus the locked markup rate, with half-up rounding applied once to the whole marked-up
    subtotal." PRD §3.5: "the `actual_grocery_total_cents` written to the parent booking is
    computed by a **per-line round-then-sum** method ...". PRD §3.5: "The booking's
    `quote_total_cents` is re-pinned with the actual grocery basis now superseding the
    estimate ...".

    Design: Difficulty/dual_variant_calc/booking_ingredient_estimated_vs_actual_divergence
    """
    chef, menu, zone, client, booking, run = setup_confirmed_with_finalized_grocery(
        line_items=[
            {"label": "produce", "actual_cost_cents": 10000},
            {"label": "protein", "actual_cost_cents": 10000},
            {"label": "dairy", "actual_cost_cents": 5000},
        ]
    )
    assert booking["estimated_grocery_total_cents"] == 28320
    assert booking["actual_grocery_total_cents"] == 29500
    assert booking["quote_total_cents"] == 88500


def test_actual_grocery_supersedes_estimate_as_distinct_value(api):
    """PRD §3.4: "This estimated figure is the provisional ingredient basis ...".
    PRD §3.5: "The booking's `quote_total_cents` is re-pinned with the actual grocery
    basis now superseding the estimate in `quote_total`, and `balance_due_cents` is
    recomputed from the new quote."

    Design: Difficulty/dual_variant_calc/booking_ingredient_estimated_vs_actual_divergence
    """
    chef, menu, zone, client, booking, run = setup_confirmed_with_finalized_grocery(
        line_items=[
            {"label": "produce", "actual_cost_cents": 10000},
            {"label": "protein", "actual_cost_cents": 10000},
            {"label": "dairy", "actual_cost_cents": 5000},
        ]
    )
    # estimated (28320) and actual (29500) coexist as distinct fields on the same booking.
    assert booking["actual_grocery_total_cents"] != booking["estimated_grocery_total_cents"]
    assert booking["estimated_grocery_total_cents"] == 28320
    assert booking["actual_grocery_total_cents"] == 29500


# ─── Difficulty / combinatorial_formula: tiered markup (mode a) ──────────────

def test_grocery_markup_mid_tier_selected_for_party6_menuA(api):
    """PRD §3.4: "if the subtotal is below 20000 cents the rate is 0.25; if the subtotal is
    at least 20000 but below 50000 cents the rate is 0.18; if the subtotal is 50000 cents
    or more the rate is 0.12." PRD §3.4: "`labor_total_cents` is the rounded per-guest rate
    times `party_size`." PRD §3.4: "`quote_total_cents` is the sum of `labor_total_cents`,
    the current grocery basis, and `travel_fee_cents`, with no rounding ...".

    Design: Difficulty/combinatorial_formula/grocery_markup_tier_selection_mode_a
    """
    # party 6 * est 4000 = 24000 -> MID tier 0.18.
    chef, menu, zone, client, booking = setup_confirmed_booking(
        booking_overrides={"event_start_utc": "2026-08-20T18:00:00Z",
                           "event_end_utc": "2026-08-20T22:00:00Z", "service_zip": "94115"}
    )
    assert booking["locked_markup_rate"] == 0.18
    assert booking["labor_total_cents"] == 54000
    assert booking["estimated_grocery_total_cents"] == 28320
    assert booking["quote_total_cents"] == 87320


def test_grocery_markup_tier_boundary_20000_selects_mid(api):
    """PRD §3.4: "A subtotal of exactly 20000 selects 0.18, and 19999 selects 0.25; a
    subtotal of exactly 50000 selects 0.12."

    Design: Difficulty/combinatorial_formula/grocery_markup_tier_selection_mode_a
    """
    # est per-guest 4000, party 5 -> subtotal exactly 20000 -> MID tier 0.18.
    chef, menu, zone, client, booking = setup_confirmed_booking(
        booking_overrides={"party_size": 5, "event_start_utc": "2026-08-20T18:00:00Z",
                           "event_end_utc": "2026-08-20T22:00:00Z", "service_zip": "94115"}
    )
    assert booking["locked_markup_rate"] == 0.18


# ─── Difficulty / combinatorial_formula: per-line round-then-sum (mode b) ────

def test_actual_grocery_per_line_round_then_sum(api):
    """PRD §3.5: "the `actual_grocery_total_cents` written to the parent booking is computed
    by a **per-line round-then-sum** method: for each line, in the order the line items were
    submitted, multiply that line's `actual_cost_cents` by one plus the booking's
    `locked_markup_rate` and round half up to whole cents; then sum those per-line rounded
    amounts." PRD §3.5: "the system computes its `raw_actual_subtotal_cents` (the sum of the
    line items' `actual_cost_cents`) ...".

    Design: Difficulty/combinatorial_formula/actual_grocery_per_line_round_then_sum_mode_b
    """
    # Low-volume menu (est 2000), party 5 -> subtotal 10000 -> rate 0.25.
    # lines 1010,2030,3050 per-line round-then-sum = 1263+2538+3813 = 7614 (NOT 7613).
    chef, menu, zone, client, booking, run = setup_confirmed_with_finalized_grocery(
        menu_overrides={"title": "Small Plates", "base_price_per_guest_cents": 8000,
                        "estimated_ingredient_per_guest_cents": 2000},
        zone_overrides={"travel_fee_cents": 4000},
        booking_overrides={"party_size": 5, "service_zip": "94117",
                           "event_start_utc": "2026-08-22T18:00:00Z",
                           "event_end_utc": "2026-08-22T22:00:00Z"},
        line_items=[
            {"label": "l1", "actual_cost_cents": 1010},
            {"label": "l2", "actual_cost_cents": 2030},
            {"label": "l3", "actual_cost_cents": 3050},
        ],
    )
    assert booking["locked_markup_rate"] == 0.25
    assert run["raw_actual_subtotal_cents"] == 6090
    assert booking["actual_grocery_total_cents"] == 7614


def test_per_line_round_then_sum_repins_quote(api):
    """PRD §3.5: "The booking's `quote_total_cents` is re-pinned with the actual grocery
    basis now superseding the estimate in `quote_total`, and `balance_due_cents` is
    recomputed from the new quote." PRD §3.4: "`quote_total_cents` is the sum of
    `labor_total_cents`, the current grocery basis, and `travel_fee_cents`, with no rounding".

    Design: Difficulty/combinatorial_formula/actual_grocery_per_line_round_then_sum_mode_b
    """
    # labor: party 5 (>=4) no surcharge -> 8000*5 = 40000; travel 4000; actual grocery 7614.
    # quote = 40000 + 7614 + 4000 = 51614.
    chef, menu, zone, client, booking, run = setup_confirmed_with_finalized_grocery(
        menu_overrides={"title": "Small Plates", "base_price_per_guest_cents": 8000,
                        "estimated_ingredient_per_guest_cents": 2000},
        zone_overrides={"travel_fee_cents": 4000},
        booking_overrides={"party_size": 5, "service_zip": "94117",
                           "event_start_utc": "2026-08-22T18:00:00Z",
                           "event_end_utc": "2026-08-22T22:00:00Z"},
        line_items=[
            {"label": "l1", "actual_cost_cents": 1010},
            {"label": "l2", "actual_cost_cents": 2030},
            {"label": "l3", "actual_cost_cents": 3050},
        ],
    )
    assert booking["quote_total_cents"] == 51614


# ─── Corner / calculations ───────────────────────────────────────────────────

def test_small_party_surcharge_labor_below_threshold(api):
    """PRD §3.4: "when `party_size` is strictly less than 4, the per-guest rate is the
    menu's base price multiplied by 1.20 and then rounded half up to whole cents ...".
    PRD §3.4: "The surcharge is applied to the per-guest rate and rounded **before**
    multiplying by the party size — that is, `labor_total_cents` is the rounded per-guest
    rate times `party_size`." PRD §3.4: "if the subtotal is below 20000 cents the rate is
    0.25 ...". PRD §3.4: "`deposit_due_cents` is the confirmation-time quote (computed on
    the estimated grocery basis) multiplied by 0.30 and rounded half up to whole cents."

    Design: Corner/calculations/small_party_surcharge_labor_below_threshold
    """
    # party 3 (<4): per_guest = round(9000*1.2)=10800, labor 32400.
    # est subtotal 4000*3=12000 -> rate 0.25; est grocery round(12000*1.25)=15000.
    # quote 32400+15000+5000=52400; deposit round(52400*0.30)=15720.
    chef, menu, zone, client, booking = setup_confirmed_booking(
        booking_overrides={"party_size": 3, "event_start_utc": "2026-08-23T18:00:00Z",
                           "event_end_utc": "2026-08-23T22:00:00Z"}
    )
    assert booking["labor_total_cents"] == 32400
    assert booking["locked_markup_rate"] == 0.25
    assert booking["estimated_grocery_total_cents"] == 15000
    assert booking["quote_total_cents"] == 52400
    assert booking["deposit_due_cents"] == 15720


def test_deposit_frozen_at_estimate_unaffected_by_actuals(api):
    """PRD §3.4: "The deposit is pinned once at confirmation and is never re-derived
    afterward, even when actual ingredient costs later change the quote; only
    `balance_due_cents` tracks the actual-cost quote." PRD §3.5: "The booking's
    `quote_total_cents` is re-pinned with the actual grocery basis now superseding the
    estimate ...".

    Design: Corner/calculations/deposit_frozen_at_estimate_unaffected_by_actuals
    """
    chef, menu, zone, client, booking, run = setup_confirmed_with_finalized_grocery(
        booking_overrides={"event_start_utc": "2026-08-24T18:00:00Z",
                           "event_end_utc": "2026-08-24T22:00:00Z"},
        line_items=[
            {"label": "a", "actual_cost_cents": 10000},
            {"label": "b", "actual_cost_cents": 10000},
            {"label": "c", "actual_cost_cents": 5000},
        ],
    )
    # deposit frozen at the estimate-basis quote (26196) despite quote now 88500.
    assert booking["deposit_due_cents"] == 26196
    assert booking["quote_total_cents"] == 88500
    assert booking["balance_due_cents"] == 88500


def test_balance_payment_amount_mismatch_rejected(api):
    """PRD §3.6: "A balance payment is the second step: it requires that a finalized
    grocery run exists for the booking ... and that `amount_cents` exactly equals the
    current `balance_due_cents` (`ERR_BALANCE_AMOUNT_MISMATCH`)."

    Design: Corner/calculations/balance_payment_amount_mismatch_rejected
    """
    # quote 87320 (estimate basis lines summing 24000 raw), balance after 26196 = 61124.
    chef, menu, zone, client, booking, run = setup_confirmed_with_finalized_grocery(
        booking_overrides={"event_start_utc": "2026-08-26T18:00:00Z",
                           "event_end_utc": "2026-08-26T22:00:00Z"},
        line_items=[
            {"label": "a", "actual_cost_cents": 8001},
            {"label": "b", "actual_cost_cents": 8001},
            {"label": "c", "actual_cost_cents": 7998},
        ],
    )
    pay_deposit(client["id"], booking["id"], 26196)
    res = api.create_payment(
        {"booking_id": booking["id"], "kind": "BALANCE", "amount_cents": 60000},
        make_client_headers(client["id"]),
    )
    validate_error(res, "ERR_BALANCE_AMOUNT_MISMATCH", expected_status=402)


def test_deposit_payment_amount_mismatch_rejected(api):
    """PRD §3.6: "A deposit payment is the first step. It requires that the booking's
    lifecycle is `CONFIRMED` (`ERR_BOOKING_NOT_CONFIRMED`) and that the `amount_cents`
    exactly equals the booking's `deposit_due_cents` (`ERR_DEPOSIT_AMOUNT_MISMATCH`)."

    Design: Corner/validations/deposit_payment_amount_mismatch_rejected
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(
        booking_overrides={"event_start_utc": "2026-08-29T18:00:00Z",
                           "event_end_utc": "2026-08-29T22:00:00Z"}
    )
    res = api.create_payment(
        {"booking_id": booking["id"], "kind": "DEPOSIT", "amount_cents": 20000},
        make_client_headers(client["id"]),
    )
    validate_error(res, "ERR_DEPOSIT_AMOUNT_MISMATCH", expected_status=402)

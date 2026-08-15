"""Invoice pricing variants and the ISSUED/DISPUTED/PAID state machine."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_aircraft,
    create_peak_window,
    fly_trip,
    get_trip_invoice,
    make_member_headers,
    setup_active_card,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]


def _midsize_program_overrides(code):
    return {
        "program_code": code,
        "aircraft_category": "MIDSIZE",
        "hours_purchased": 25,
        "purchase_price_cents": 15_000_000,
        "swap_ratio_to_lower": 0.85,
        "swap_ratio_to_higher": 1.30,
        "expiry_months": 24,
    }


def test_invoice_one_way_off_peak_bills_exact_subtotal(api):
    """PRD §3.8: "The implied hourly rate of the program is its `purchase_price_cents`
    divided by its `hours_purchased`. The invoice's `subtotal_cents` is the sum of the
    trip's per-leg `debited_hours` multiplied by that implied rate, rounded to whole
    cents."
    PRD §3.8: "an off-peak one-way trip bills exactly its subtotal".

    Design: Difficulty/dual_variant_calc/invoice_total_one_way_vs_round_trip
    """
    _, member, card = setup_active_card(
        program_overrides=_midsize_program_overrides("MID_25B_OW"),
        clock="2026-08-01T00:00:00Z",
    )
    aircraft = create_aircraft(tail_number="N100MU", category="MIDSIZE", seats=8)
    trip, _ = fly_trip(card["id"], member["id"], aircraft["id"], block_minutes=120,
                       trip_overrides={
                           "trip_kind": "ONE_WAY",
                           "requested_category": "MIDSIZE",
                           "requested_departure_utc": "2026-08-10T15:00:00Z",
                       })
    invoice = get_trip_invoice(trip["id"])
    # 120+12=132 min -> 2.20 h debited; implied rate = 15000000/25 = 600000 cents/h.
    assert invoice["subtotal_cents"] == 1_320_000
    assert invoice["peak_surcharge_cents"] == 0, "off-peak trips carry a surcharge of zero"
    assert invoice["round_trip_discount_cents"] == 0, "one-way trips carry a discount of zero"
    assert invoice["total_cents"] == 1_320_000


def test_invoice_round_trip_discount_applies_to_identical_route(api):
    """PRD §3.8: "when `trip_kind` is `ROUND_TRIP`, `round_trip_discount_cents` is the sum
    of `subtotal_cents` and `peak_surcharge_cents`, multiplied by
    `round_trip_discount_pct`, rounded to whole cents; one-way trips carry a discount of
    zero. The invoice's `total_cents` is the subtotal plus the surcharge minus the
    discount."
    PRD §3.8: "an off-peak round-trip bills the subtotal reduced by the discount
    percentage".

    Design: Difficulty/dual_variant_calc/invoice_total_one_way_vs_round_trip
    """
    _, member, card = setup_active_card(
        program_overrides=_midsize_program_overrides("MID_25B_RT"),
        clock="2026-08-01T00:00:00Z",
    )
    aircraft = create_aircraft(tail_number="N101MU", category="MIDSIZE", seats=8)
    ow_trip, _ = fly_trip(card["id"], member["id"], aircraft["id"], block_minutes=120,
                          trip_overrides={
                              "trip_kind": "ONE_WAY",
                              "requested_category": "MIDSIZE",
                              "requested_departure_utc": "2026-08-10T15:00:00Z",
                          })
    rt_trip, _ = fly_trip(card["id"], member["id"], aircraft["id"],
                          block_minutes=[120, 120],
                          trip_overrides={
                              "trip_kind": "ROUND_TRIP",
                              "requested_category": "MIDSIZE",
                              "requested_departure_utc": "2026-08-10T15:00:00Z",
                              "requested_return_utc": "2026-08-12T15:00:00Z",
                          })
    ow_invoice = get_trip_invoice(ow_trip["id"])
    rt_invoice = get_trip_invoice(rt_trip["id"])
    assert rt_invoice["subtotal_cents"] == 2 * ow_invoice["subtotal_cents"]
    assert rt_invoice["round_trip_discount_cents"] == round(
        (rt_invoice["subtotal_cents"] + rt_invoice["peak_surcharge_cents"]) * 0.10
    )
    assert rt_invoice["total_cents"] == (
        rt_invoice["subtotal_cents"]
        + rt_invoice["peak_surcharge_cents"]
        - rt_invoice["round_trip_discount_cents"]
    )
    assert rt_invoice["total_cents"] == 2_376_000
    assert rt_invoice["total_cents"] != ow_invoice["total_cents"]
    assert rt_invoice["total_cents"] < 2 * ow_invoice["total_cents"]


def _peak_upgrade_swap_invoice(api, code):
    """ROUND_TRIP peak trip with an upgrade swap (MIDSIZE request, SUPER_MID dispatch).
    Per leg: 100 block + 12 taxi = 112 min -> 1.87 billable h -> x1.30 = 2.43 debited h.
    Returns the invoice dict."""
    _, member, card = setup_active_card(
        program_overrides=_midsize_program_overrides(code),
        clock="2026-11-15T00:00:00Z",
    )
    create_peak_window(
        card["program_id"],
        window_start_utc="2026-12-01T00:00:00Z",
        window_end_utc="2026-12-08T00:00:00Z",
        label="July4",
    )
    aircraft = create_aircraft(tail_number="N200SM", category="SUPER_MID", seats=9)
    trip, _ = fly_trip(card["id"], member["id"], aircraft["id"],
                       block_minutes=[100, 100],
                       trip_overrides={
                           "trip_kind": "ROUND_TRIP",
                           "requested_category": "MIDSIZE",
                           "pax_count": 6,
                           "requested_departure_utc": "2026-12-04T15:00:00Z",
                           "requested_return_utc": "2026-12-06T15:00:00Z",
                       })
    return trip, get_trip_invoice(trip["id"])


def test_invoice_peak_surcharge_on_upgrade_swap_subtotal(api):
    """PRD §3.8: "when the trip's `is_peak_period` is true, `peak_surcharge_cents` is the
    subtotal multiplied by the program's `peak_surcharge_pct`, rounded to whole cents;
    off-peak trips carry a surcharge of zero."
    PRD §3.4: "`is_peak_period` is true exactly when `requested_departure_utc` falls
    inside one of the program's `PeakCalendar` windows (start inclusive, end exclusive)."
    PRD §3.7: "When the dispatched category is a higher tier — an upgrade swap — the
    multiplier is `swap_ratio_to_higher`, above 1.0, and the member is debited more
    hours."

    Design: Difficulty/combinatorial_formula/invoice_total_nested_min_max_mode_a
    """
    trip, invoice = _peak_upgrade_swap_invoice(api, "MID_PEAK_A")
    assert trip["is_peak_period"] is True
    assert trip["swap_applied"] is True
    # Per leg 2.43 debited h; final 4.86; subtotal = 4.86 * 600000 = 2,916,000.
    assert invoice["subtotal_cents"] == 2_916_000
    assert invoice["peak_surcharge_cents"] == round(invoice["subtotal_cents"] * 0.15)
    assert invoice["peak_surcharge_cents"] == 437_400


def test_invoice_round_trip_discount_on_combined_base(api):
    """PRD §3.8: "when `trip_kind` is `ROUND_TRIP`, `round_trip_discount_cents` is the sum
    of `subtotal_cents` and `peak_surcharge_cents`, multiplied by
    `round_trip_discount_pct`, rounded to whole cents".
    PRD §3.8: "a peak round-trip bills subtotal plus surcharge, then reduced by the
    discount percentage applied to that combined figure."

    Design: Difficulty/combinatorial_formula/invoice_total_nested_min_max_mode_a
    """
    _, invoice = _peak_upgrade_swap_invoice(api, "MID_PEAK_B")
    sub = invoice["subtotal_cents"]
    peak = invoice["peak_surcharge_cents"]
    discount = invoice["round_trip_discount_cents"]
    assert discount == round((sub + peak) * 0.10) == 335_340
    assert invoice["total_cents"] == sub + peak - discount == 3_018_060


def _issued_invoice(api, code):
    """Completed one-way trip; returns (member, invoice) with invoice ISSUED."""
    _, member, card = setup_active_card(program_overrides={"program_code": code})
    aircraft = create_aircraft(tail_number="N300LT")
    trip, _ = fly_trip(card["id"], member["id"], aircraft["id"], block_minutes=90)
    return member, get_trip_invoice(trip["id"])


def test_invoice_dispute_then_paid_reaches_paid(api):
    """PRD §3.8: "From `ISSUED`, two member- and ops-facing paths exist: the member may
    dispute the invoice, moving it to `DISPUTED`; an `Ops` operator may mark it paid —
    from either `ISSUED` or `DISPUTED` — moving it to `PAID`, or write it off from either
    of those states, moving it to `WRITTEN_OFF`. Every transition increments the invoice's
    `version`."

    Design: Difficulty/non_linear_state_machine/invoice_issued_disputed_paid_branching
    """
    member, invoice = _issued_invoice(api, "INV_CYC")
    assert invoice["invoice_status"] == "ISSUED"
    mh = make_member_headers(member["id"])
    disputed = validate_success(api.dispute_invoice(invoice["id"], mh), expected_status=200)
    assert disputed["invoice_status"] == "DISPUTED"
    paid = validate_success(api.mark_invoice_paid(invoice["id"], OPS), expected_status=200)
    assert paid["invoice_status"] == "PAID"
    # create(1) -> issued(2) -> disputed(3) -> paid(4)
    assert paid["version"] >= 3, (
        f"DISPUTED->PAID path must carry version >= 3, got {paid['version']}"
    )


def test_invoice_direct_mark_paid_from_issued(api):
    """PRD §3.8: "an `Ops` operator may mark it paid — from either `ISSUED` or `DISPUTED`
    — moving it to `PAID`".

    Design: Difficulty/non_linear_state_machine/invoice_issued_disputed_paid_branching
    """
    _, invoice = _issued_invoice(api, "INV_DIR")
    assert invoice["invoice_status"] == "ISSUED"
    paid = validate_success(api.mark_invoice_paid(invoice["id"], OPS), expected_status=200)
    assert paid["invoice_status"] == "PAID"

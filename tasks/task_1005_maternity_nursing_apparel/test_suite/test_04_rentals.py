"""Rental lifecycle: provisional vs final settlement, the convert/return branch,
the on-time boundary, buffered pool-overlap availability, the order-cancel
cascade, and the rental-unit conservation invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_shopper_headers,
    set_clock,
    setup_rentable,
    setup_reserved_rental,
    setup_active_rental,
    place_order,
    rental_for_order,
    activate_rental,
    return_rental,
    convert_rental,
    cancel_order,
    new_customer,
    new_product,
    new_variant,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["fulfillment_agent_headers"]


def _read_variant(api, variant_id):
    return validate_success(api.get_variant(variant_id, ADMIN), 200)


# ---- dual_variant_calc: rental_provisional_vs_final_settlement ----

def test_rental_early_return_final_diverges_from_provisional(api):
    """PRD §3.6: "The forward-looking `provisional_charge_cents`, set at
    reservation, is simply the `weekly_rate_cents` times the `planned_weeks`."
    PRD §3.6: "then the final charge is the weekly rate times the smaller of the
    actual weeks and the planned weeks (an early return is billed only for the
    weeks actually used), and the late fee is 0."

    Design: Difficulty/dual_variant_calc/rental_provisional_vs_final_settlement
    """
    base = setup_active_rental(api, weekly_cents=2000, deposit_cents=12000, units=2,
                               rental_weeks=4, rental_start="2026-07-01T00:00:00Z",
                               clock="2026-07-01T00:00:00Z")
    assert base["rental"]["provisional_charge_cents"] == 8000
    set_clock(api, "2026-07-15T00:00:00Z")  # 14 days -> 2 actual weeks, on time
    settled = return_rental(api, base["rental"]["id"])
    assert settled["status"] == "RETURNED"
    assert settled["final_charge_cents"] == 4000
    assert settled["late_fee_cents"] == 0


def test_rental_early_return_three_week_plan_divergence(api):
    """PRD §3.6: "the number of days used is the span from `rental_start` to
    `returned_at`, rounded up to whole days; the actual weeks used is that day
    count divided by seven and rounded up, but never fewer than one week."
    PRD §3.6: "The forward-looking `provisional_charge_cents`, set at
    reservation, is simply the `weekly_rate_cents` times the `planned_weeks`."

    Design: Difficulty/dual_variant_calc/rental_provisional_vs_final_settlement
    """
    base = setup_active_rental(api, weekly_cents=2000, deposit_cents=12000, units=1,
                               rental_weeks=3, rental_start="2026-07-01T00:00:00Z",
                               clock="2026-07-01T00:00:00Z")
    assert base["rental"]["provisional_charge_cents"] == 6000  # 2000 * 3
    set_clock(api, "2026-07-09T00:00:00Z")  # 8 days -> ceil = 2 weeks
    settled = return_rental(api, base["rental"]["id"])
    assert settled["final_charge_cents"] == 4000  # 2000 * min(2,3)
    assert settled["late_fee_cents"] == 0


# ---- non_linear_state_machine: rental_branching_convert_vs_return ----

def test_rental_convert_to_buy_removes_unit_from_pool(api):
    """PRD §3.6: "the `final_charge_cents` becomes the deposit minus the smaller
    of the provisional charge and the deposit."
    PRD §3.6: "Because the unit is now sold, both `reserved_rental_units` and
    `rental_units_total` are lowered by one — it leaves the rental pool
    permanently as a sale."

    Design: Difficulty/non_linear_state_machine/rental_branching_convert_vs_return
    """
    base = setup_active_rental(api, weekly_cents=2000, deposit_cents=12000, units=1,
                               rental_weeks=4)
    converted = convert_rental(api, base["rental"]["id"], base["customer"]["id"])
    assert converted["status"] == "CONVERTED_TO_BUY"
    assert converted["final_charge_cents"] == 4000  # 12000 - min(8000, 12000)
    variant = _read_variant(api, base["variant"]["id"])
    assert variant["rental_units_total"] == 0


def test_rental_return_keeps_unit_in_pool(api):
    """PRD §3.6: "Returning stamps `returned_at` with the current clock instant,
    computes the final settlement described below, and releases the unit —
    `reserved_rental_units` drops by one as the garment re-enters the pool after
    its cleaning buffer."

    Design: Difficulty/non_linear_state_machine/rental_branching_convert_vs_return
    """
    base = setup_active_rental(api, weekly_cents=2000, deposit_cents=12000, units=1,
                               rental_weeks=4)
    set_clock(api, "2026-07-15T00:00:00Z")
    settled = return_rental(api, base["rental"]["id"])
    assert settled["status"] == "RETURNED"
    variant = _read_variant(api, base["variant"]["id"])
    assert variant["rental_units_total"] == 1  # unit stays in pool
    assert variant["reserved_rental_units"] == 0  # but released


# ---- boundary_precision_check: rental_return_equal_end_not_late ----

def test_return_exactly_at_rental_end_not_late(api):
    """PRD §3.6: "If the garment came back on time — that is, `returned_at` is on
    or before `rental_end`, with equality counting as on time, not late — then
    the final charge is the weekly rate times the smaller of the actual weeks and
    the planned weeks ..., and the late fee is 0."

    Design: Difficulty/boundary_precision_check/rental_return_equal_end_not_late
    """
    base = setup_active_rental(api, weekly_cents=2000, deposit_cents=12000, units=1,
                               rental_weeks=4, rental_start="2026-07-01T00:00:00Z",
                               clock="2026-07-01T00:00:00Z")
    set_clock(api, "2026-07-29T00:00:00Z")  # exactly rental_end
    settled = return_rental(api, base["rental"]["id"])
    assert settled["late_fee_cents"] == 0
    assert settled["final_charge_cents"] == 8000
    assert settled["status"] == "RETURNED"


def test_return_one_day_after_end_is_late(api):
    """PRD §3.6: "If instead the garment came back after `rental_end`, the number
    of late days is the span from `rental_end` to `returned_at` rounded up to
    whole days; the `late_fee_cents` is 500 cents per late day, capped so it
    never exceeds `deposit_cents`; and the final charge is the weekly rate times
    the full planned weeks plus that late fee."

    Design: Difficulty/boundary_precision_check/rental_return_equal_end_not_late
    """
    base = setup_active_rental(api, weekly_cents=2000, deposit_cents=12000, units=1,
                               rental_weeks=4, rental_start="2026-07-01T00:00:00Z",
                               clock="2026-07-01T00:00:00Z")
    set_clock(api, "2026-07-30T00:00:00Z")  # one day past rental_end
    settled = return_rental(api, base["rental"]["id"])
    assert settled["late_fee_cents"] == 500        # 1 late day * 500
    assert settled["final_charge_cents"] == 8500   # 2000*4 + 500


# ---- resource_temporal_overlap: rental_pool_overlap_with_cleaning_buffer ----

def test_rental_overlap_inside_cleaning_buffer_rejected(api):
    """PRD §3.3: "take its occupation window from its start through its end, then
    extend the end by a two-day cleaning buffer, and treat the interval as closed
    on both ends."
    PRD §3.3: "If the available units come out at zero or fewer, the order is
    rejected with `ERR_NO_RENTAL_UNITS`."

    Design: Difficulty/resource_temporal_overlap/rental_pool_overlap_with_cleaning_buffer
    """
    base = setup_reserved_rental(api, weekly_cents=1800, deposit_cents=10000, units=1,
                                 rental_weeks=4, rental_start="2026-07-01T00:00:00Z",
                                 clock="2026-07-01T00:00:00Z")
    # Rental A occupies [07-01, 07-29]; buffered end 07-31. B start 07-30 overlaps.
    hdr = make_shopper_headers(base["customer"]["id"])
    v = _read_variant(api, base["variant"]["id"])
    resp = api.create_order(
        {"customer_id": base["customer"]["id"], "variant_id": base["variant"]["id"],
         "order_type": "RENTAL", "expected_variant_version": v["version"],
         "rental_weeks": 2, "rental_start": "2026-07-30T00:00:00Z"},
        hdr,
    )
    validate_error(resp, ApiErrorId.ERR_NO_RENTAL_UNITS.value)


def test_rental_just_past_cleaning_buffer_succeeds(api):
    """PRD §3.3: "The number of available units is `rental_units_total` minus
    that overlap count."
    PRD §3.3: "then extend the end by a two-day cleaning buffer, and treat the
    interval as closed on both ends."

    Design: Difficulty/resource_temporal_overlap/rental_pool_overlap_with_cleaning_buffer
    """
    base = setup_reserved_rental(api, weekly_cents=1800, deposit_cents=10000, units=1,
                                 rental_weeks=4, rental_start="2026-07-01T00:00:00Z",
                                 clock="2026-07-01T00:00:00Z")
    # Buffered end of A is 07-31; B starting 08-01 no longer overlaps.
    hdr = make_shopper_headers(base["customer"]["id"])
    v = _read_variant(api, base["variant"]["id"])
    resp = api.create_order(
        {"customer_id": base["customer"]["id"], "variant_id": base["variant"]["id"],
         "order_type": "RENTAL", "expected_variant_version": v["version"],
         "rental_weeks": 2, "rental_start": "2026-08-01T00:00:00Z"},
        hdr,
    )
    data = validate_success(resp, 201)
    assert data["order_type"] == "RENTAL"


# ---- transitive_cascade: order_cancel_releases_rental_unit_depth3 ----

def test_cancel_reserved_rental_order_releases_unit(api):
    """PRD §3.5: "if the order was a rental, its linked `Rental` — the one whose
    `order_id` points back to this order and which is currently `RESERVED` or
    `ACTIVE` — is transitioned to `CANCELLED`, and that rental cancellation in
    turn releases its held unit by lowering the variant's `reserved_rental_units`
    by one."

    Design: Difficulty/transitive_cascade/order_cancel_releases_rental_unit_depth3
    """
    base = setup_reserved_rental(api, units=2, rental_weeks=3)
    cancelled = cancel_order(api, base["order"]["id"], base["customer"]["id"])
    assert cancelled["fulfillment_status"] == "CANCELLED"
    rental = validate_success(api.get_rental(base["rental"]["id"], AGENT), 200)
    assert rental["status"] == "CANCELLED"
    variant = _read_variant(api, base["variant"]["id"])
    assert variant["reserved_rental_units"] == 0


def test_cancel_active_rental_order_releases_unit(api):
    """PRD §3.5: "its linked `Rental` — the one whose `order_id` points back to
    this order and which is currently `RESERVED` or `ACTIVE` — is transitioned to
    `CANCELLED`, and that rental cancellation in turn releases its held unit by
    lowering the variant's `reserved_rental_units` by one."

    Design: Difficulty/transitive_cascade/order_cancel_releases_rental_unit_depth3
    """
    base = setup_active_rental(api, units=2, rental_weeks=3)
    cancelled = cancel_order(api, base["order"]["id"], base["customer"]["id"])
    assert cancelled["fulfillment_status"] == "CANCELLED"
    rental = validate_success(api.get_rental(base["rental"]["id"], AGENT), 200)
    assert rental["status"] == "CANCELLED"
    variant = _read_variant(api, base["variant"]["id"])
    assert variant["reserved_rental_units"] == 0


# ---- compensating_invariant: rental_unit_count_conserved_reserve_then_cancel ----

def test_rental_unit_count_conserved_after_cancel(api):
    """PRD §2.9: "The pool obeys a standing invariant: `rental_units_total`
    always equals the number of currently available units plus
    `reserved_rental_units`."
    PRD §3.5: "that rental cancellation in turn releases its held unit by
    lowering the variant's `reserved_rental_units` by one."

    Design: Difficulty/compensating_invariant/rental_unit_count_conserved_reserve_then_cancel
    """
    base = setup_reserved_rental(api, units=3, rental_weeks=2)
    reserved_state = _read_variant(api, base["variant"]["id"])
    assert reserved_state["reserved_rental_units"] == 1
    cancel_order(api, base["order"]["id"], base["customer"]["id"])
    after = _read_variant(api, base["variant"]["id"])
    assert after["reserved_rental_units"] == 0
    assert after["rental_units_total"] == 3


def test_rental_unit_count_conserved_after_return(api):
    """PRD §2.9: "Reserving a unit raises `reserved_rental_units` by one;
    releasing a unit lowers it by one."
    PRD §3.6: "releases the unit — `reserved_rental_units` drops by one as the
    garment re-enters the pool after its cleaning buffer."

    Design: Difficulty/compensating_invariant/rental_unit_count_conserved_reserve_then_cancel
    """
    base = setup_active_rental(api, units=3, rental_weeks=2)
    set_clock(api, "2026-07-10T00:00:00Z")
    return_rental(api, base["rental"]["id"])
    after = _read_variant(api, base["variant"]["id"])
    assert after["reserved_rental_units"] == 0
    assert after["rental_units_total"] == 3  # returned unit stays in the pool


# ---- Corner: convert_reserved_rental_rejected ----

def test_convert_reserved_rental_rejected(api):
    """PRD §3.6: "a shopper may keep the garment by converting an `ACTIVE` rental
    into a purchase, moving it to `CONVERTED_TO_BUY` (allowed only from `ACTIVE`,
    otherwise `ERR_RENTAL_NOT_ACTIVE`)."

    Design: Corner/state_machines/convert_reserved_rental_rejected
    """
    base = setup_reserved_rental(api, units=1, rental_weeks=2)  # never activated
    resp = api.convert_rental_to_buy(base["rental"]["id"],
                                     make_shopper_headers(base["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_RENTAL_NOT_ACTIVE.value)

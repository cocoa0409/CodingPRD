"""Shared-POS fee computation, settlement validation, and vendor lifetime
gross-sales accounting."""
import pytest

from test_helpers import (
    TEST_USERS, validate_error, validate_success,
    make_vendor_headers,
    assert_assignment_fee_invariants,
    setup_accepted_application, setup_open_market, setup_active_pos_device,
    create_assignment_for, create_settlement, submit_settlement,
    reconcile_settlement, get_vendor, get_settlement,
)

OPERATOR = TEST_USERS["market_operator_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def test_pos_fee_floor_at_250_bps_boundary(api):
    """PRD §3.6: "The POS fee is computed as follows: when the market's
    `shared_pos_enabled` is true and an `ACTIVE` POS device exists for the
    assignment, `pos_fee_cents` is the floor of `gross_card_cents` multiplied by
    `shared_pos_fee_bps` divided by 10000; otherwise `pos_fee_cents` is 0."
    PRD §2.5: "The sole exception is the shared-POS fee, which uses floor (round
    down) semantics, also to whole cents, with no float rounding."

    Design: Corner/calculations/pos_fee_threshold_boundary_250_bps
    """
    ctx = setup_active_pos_device(
        market_overrides={"name": "CM3", "season_code": "CM3-1",
                          "shared_pos_enabled": True, "shared_pos_fee_bps": 250})
    market_id, vendor_id, asg_id = (ctx["market"]["id"], ctx["vendor"]["id"],
                                    ctx["assignment"]["id"])

    # Exact multiple: floor(10000 * 250 / 10000) = 250.
    s1 = create_settlement(market_id, vendor_id, asg_id, "2026-12-05",
                           gross_card_cents=10000, gross_cash_cents=0)
    assert s1["pos_fee_cents"] == 250
    assert s1["net_payable_cents"] == 10000 - 250

    # One cent below the next fee step: floor(9999 * 250 / 10000) = floor(249.975) = 249.
    s2 = create_settlement(market_id, vendor_id, asg_id, "2026-12-06",
                           gross_card_cents=9999, gross_cash_cents=0)
    assert s2["pos_fee_cents"] == 249


def test_pos_fee_floored_per_settlement_row(api):
    """PRD §3.6: "The POS fee is computed as follows: when the market's
    `shared_pos_enabled` is true and an `ACTIVE` POS device exists for the
    assignment, `pos_fee_cents` is the floor of `gross_card_cents` multiplied by
    `shared_pos_fee_bps` divided by 10000; otherwise `pos_fee_cents` is 0."
    PRD §3.6: "The per-row floor is authoritative for the `DRAFT` and
    `SUBMITTED` settlement rows themselves."

    Design: Difficulty/dual_variant_calc/pos_fee_line_item_vs_aggregate
    """
    ctx = setup_active_pos_device(
        market_overrides={"name": "M1", "season_code": "W26",
                          "shared_pos_enabled": True, "shared_pos_fee_bps": 250})
    market_id, vendor_id, asg_id = (ctx["market"]["id"], ctx["vendor"]["id"],
                                    ctx["assignment"]["id"])

    # floor(999 * 250 / 10000) = floor(24.975) = 24, applied per row.
    s1 = create_settlement(market_id, vendor_id, asg_id, "2026-12-05",
                           gross_card_cents=999, gross_cash_cents=0)
    s2 = create_settlement(market_id, vendor_id, asg_id, "2026-12-05",
                           gross_card_cents=999, gross_cash_cents=0)
    assert s1["pos_fee_cents"] == 24, "per-row floor of 24.975 must be 24"
    assert s2["pos_fee_cents"] == 24
    assert s1["pos_fee_cents"] + s2["pos_fee_cents"] == 48


def test_pos_fee_uses_floor_not_round_half_up(api):
    """PRD §2.5: "Calculations that produce fractional cents round half-up to
    whole cents, applied once at the end of the calculation — never
    per-component. The sole exception is the shared-POS fee, which uses floor
    (round down) semantics, also to whole cents, with no float rounding."
    PRD §3.6: "The POS fee is computed as follows: when the market's
    `shared_pos_enabled` is true and an `ACTIVE` POS device exists for the
    assignment, `pos_fee_cents` is the floor of `gross_card_cents` multiplied by
    `shared_pos_fee_bps` divided by 10000; otherwise `pos_fee_cents` is 0."

    Design: Difficulty/dual_variant_calc/pos_fee_line_item_vs_aggregate
    """
    ctx = setup_active_pos_device(
        market_overrides={"name": "M1B", "season_code": "W26B2",
                          "shared_pos_enabled": True, "shared_pos_fee_bps": 250})
    # 24.975 rounds half-up to 25; the POS-fee floor yields 24.
    st = create_settlement(ctx["market"]["id"], ctx["vendor"]["id"],
                           ctx["assignment"]["id"], "2026-12-05",
                           gross_card_cents=999, gross_cash_cents=0)
    assert st["pos_fee_cents"] == 24, "POS fee must floor, not round half-up to 25"


def test_heating_surcharge_applied_for_chalet_with_heating(api):
    """PRD §3.4: "`heating_surcharge_cents` is 45000 (a $450.00 flat charge)
    when the application has `heating_requested` true and the booth is a
    `CHALET`; otherwise it is 0."
    PRD §3.4: "`total_fee_cents` is the sum of `base_rent_cents` and
    `heating_surcharge_cents`, exact in whole cents with no additional rounding
    step."

    Design: Corner/calculations/assignment_total_fee_constants_applied
    """
    ctx = setup_accepted_application(
        app_overrides={"requested_booth_type": "CHALET", "heating_requested": True},
        booth_overrides={"booth_code": "CH-4", "booth_type": "CHALET", "zone": "EAST",
                         "square_feet": 100},
        vendor_overrides={"category": "FOOD_BEVERAGE"})
    asg = create_assignment_for(ctx["market"]["id"], ctx["booth"]["id"],
                                ctx["application"]["id"])
    assert asg["heating_surcharge_cents"] == 45000
    assert asg["total_fee_cents"] == asg["base_rent_cents"] + 45000
    assert_assignment_fee_invariants(asg)


def test_settlement_rejected_when_refund_exceeds_gross(api):
    """PRD §3.6: "The system validates that `gross_card_cents` and
    `gross_cash_cents` are non-negative, that `refund_cents` does not exceed the
    sum of the two gross fields, and that all amounts are integer cents;
    violations are rejected with `ERR_INVALID_SETTLEMENT_AMOUNTS` (HTTP 422)."

    Design: Corner/validations/settlement_amounts_invalid_refund_exceeds_gross
    """
    ctx = setup_open_market()
    res = api.create_settlement(
        ctx["market"]["id"],
        {"assignment_id": ctx["assignment"]["id"], "business_date": "2026-12-05",
         "gross_card_cents": 1000, "gross_cash_cents": 500, "refund_cents": 2000},
        make_vendor_headers(ctx["vendor"]["id"]))
    validate_error(res, "ERR_INVALID_SETTLEMENT_AMOUNTS", expected_status=422)


def test_settlement_submit_updates_vendor_lifetime_gross_immediately(api):
    """PRD §3.6: "On submission, the vendor's `lifetime_gross_sales_cents`
    increases by `gross_card_cents` plus `gross_cash_cents` minus
    `refund_cents`."

    Design: Corner/consistency_model/immediate_consistency_settlement_submit
    """
    ctx = setup_open_market()
    before = get_vendor(ctx["vendor"]["id"])
    assert before["lifetime_gross_sales_cents"] == 0

    st = create_settlement(ctx["market"]["id"], ctx["vendor"]["id"],
                           ctx["assignment"]["id"], "2026-12-05",
                           gross_card_cents=50000, gross_cash_cents=10000)
    submit_settlement(ctx["market"]["id"], st["id"], ctx["vendor"]["id"])

    after = get_vendor(ctx["vendor"]["id"])
    assert after["lifetime_gross_sales_cents"] == 60000, \
        "submit must increase lifetime gross by 50000 + 10000 - 0 immediately"


def _setup_two_settlements_one_disputed(api):
    """Open market + ACTIVE assignment; settlement A submitted + reconciled +
    paid; settlement B submitted then disputed."""
    ctx = setup_open_market()
    market_id, vendor_id, asg_id = (ctx["market"]["id"], ctx["vendor"]["id"],
                                    ctx["assignment"]["id"])
    s_a = create_settlement(market_id, vendor_id, asg_id, "2026-12-05",
                            gross_card_cents=10000, gross_cash_cents=5000)
    s_a = submit_settlement(market_id, s_a["id"], vendor_id)
    s_a = reconcile_settlement(market_id, s_a["id"])
    s_a = validate_success(api.pay_settlement(market_id, s_a["id"], FINANCE), 200)
    assert s_a["status"] == "PAID"

    s_b = create_settlement(market_id, vendor_id, asg_id, "2026-12-06",
                            gross_card_cents=20000, gross_cash_cents=0)
    s_b = submit_settlement(market_id, s_b["id"], vendor_id)
    s_b = validate_success(api.dispute_settlement(market_id, s_b["id"], FINANCE), 200)
    assert s_b["status"] == "DISPUTED"
    return ctx, s_a, s_b


def test_lifetime_gross_accumulates_on_submit_not_on_reconcile_or_pay(api):
    """PRD §3.6: "On submission, the vendor's `lifetime_gross_sales_cents`
    increases by `gross_card_cents` plus `gross_cash_cents` minus
    `refund_cents`."
    PRD §3.6: "A `FinanceOfficer` may also dispute a `SUBMITTED` settlement
    (transitioning it to `DISPUTED`) or pay a `RECONCILED` settlement
    (transitioning it to `PAID`)."

    Design: Difficulty/compensating_invariant/vendor_lifetime_gross_sales_invariant
    """
    ctx = setup_open_market()
    market_id, vendor_id, asg_id = (ctx["market"]["id"], ctx["vendor"]["id"],
                                    ctx["assignment"]["id"])
    st = create_settlement(market_id, vendor_id, asg_id, "2026-12-05",
                           gross_card_cents=10000, gross_cash_cents=5000)
    submit_settlement(market_id, st["id"], vendor_id)
    assert get_vendor(vendor_id)["lifetime_gross_sales_cents"] == 15000

    reconcile_settlement(market_id, st["id"])
    assert get_vendor(vendor_id)["lifetime_gross_sales_cents"] == 15000, \
        "reconcile must not change lifetime gross"

    paid = validate_success(api.pay_settlement(market_id, st["id"], FINANCE), 200)
    assert paid["status"] == "PAID"
    assert get_vendor(vendor_id)["lifetime_gross_sales_cents"] == 15000, \
        "pay must not double-count lifetime gross"


def test_lifetime_gross_not_subtracted_by_dispute(api):
    """PRD §3.6: "On submission, the vendor's `lifetime_gross_sales_cents`
    increases by `gross_card_cents` plus `gross_cash_cents` minus
    `refund_cents`."
    PRD §3.6: "A `FinanceOfficer` may also dispute a `SUBMITTED` settlement
    (transitioning it to `DISPUTED`) or pay a `RECONCILED` settlement
    (transitioning it to `PAID`)."

    Design: Difficulty/compensating_invariant/vendor_lifetime_gross_sales_invariant
    """
    ctx, s_a, s_b = _setup_two_settlements_one_disputed(api)
    vendor = get_vendor(ctx["vendor"]["id"])
    # Submit of A adds 10000+5000-0 = 15000; submit of B adds 20000; the
    # dispute has no documented lifetime-gross effect, so it must not subtract.
    assert vendor["lifetime_gross_sales_cents"] == 35000
    final_b = get_settlement(ctx["market"]["id"], s_b["id"])
    assert final_b["status"] == "DISPUTED"

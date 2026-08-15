"""Settlement economics: dual-variant bases, pool price evaluation order, and the
pinned per-lot round-then-sum rounding order (PRD §3.9)."""
import pytest

from test_helpers import (
    validate_success, get_success_data, ApiErrorId,
    setup_grower_shed_bin_lot, setup_grower_with_closed_lot,
    create_grower, create_shed, create_bin, create_lot, create_binned_lot, bin_lot, assess_lot,
    apply_inhibitor, hold_and_condemn_lot, create_contract, create_order,
    allocate_order, create_allocated_order, record_pass_wash, ship_order,
    set_clock, create_settlement, refresh_grower, refresh_lot, make_draw,
    create_scheduled_run, complete_run,
    TEST_USERS, make_clerk_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_headers"]
QA = TEST_USERS["qa_headers"]
STORAGE = TEST_USERS["storage_headers"]


def _finalize(settlement_id, clerk_id="clerk_one"):
    resp = api_finalize(settlement_id, clerk_id)
    return resp


def api_finalize(settlement_id, clerk_id):
    from test_helpers import api_client
    return api_client.finalize_settlement(settlement_id, make_clerk_headers(clerk_id))


class TestDualVariantSettlement:
    def test_provisional_variant_uses_assessment_estimates_and_contract_blend(self, api):
        """PRD §3.9: "The provisional variant — computed at create — sums, over every lot the grower has in any storage state, a per-lot term: for a lot not yet closed, the term is its actual `packed_total_cwt` plus the estimated packout of the remainder (the lot's `available_cwt` multiplied by its latest-assessment packout fraction, defaulting to 0.75 when the lot has no assessment)".
        PRD §3.9: "When no shipped order exists at all, the fallback is the contract blend: the sum over every `ACTIVE` contract of its `committed_volume_cwt` times `price_cents_per_cwt` divided by the total committed volume across those contracts, again rounded half-up to two decimals."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_packout_basis
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower One", grower_code="G-ONE", shed_name="Shed A",
            lot_weight_cwt=1000.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        g, s, b, l = ctx["grower"], ctx["shed"], ctx["bin"], ctx["lot"]
        assess_lot(l["id"], l["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=20.00, assessment_date="2026-08-02")
        apply_inhibitor(l["id"], "2026-08-02T00:00:00Z")
        create_contract(committed_volume_cwt=500.00, price_cents_per_cwt=2000,
                        grade_min_us1_pct=80.0, buyer_name="Buyer A")
        set_clock("2026-08-30T00:00:00Z")

        st = create_settlement(g["id"], g["version"])

        assert abs(st["packed_cwt_basis"] - 882.00) <= 0.005
        assert abs(st["pool_price_cents"] - 2000.00) <= 0.005
        assert abs(st["gross_cents"] - 1764000.00) <= 0.005
        assert abs(st["storage_fees_cents"] - 50000.00) <= 0.005
        assert abs(st["inhibitor_fees_cents"] - 8000.00) <= 0.005
        assert abs(st["net_payable_cents"] - 1706000.00) <= 0.005

    def test_final_variant_uses_actuals_and_realized_pool(self, api):
        """PRD §3.9: "The final variant — computed at finalize — requires every lot to be `CLOSED` and uses only actual packed totals."
        PRD §3.9: "First, the pool aggregate is built from shipped orders only: the sum, over every `SHIPPED` contract order, of its `packed_to_date_cwt` multiplied by its contract's `price_cents_per_cwt`... divided by the total `packed_to_date_cwt` across all shipped orders, rounded half-up to two decimals."
        PRD §3.9: "for the final variant it is the whole weeks between `binned_at` and `closed_at`."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_packout_basis
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower One", grower_code="G-ONE", shed_name="Shed A",
            lot_weight_cwt=1000.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        g, s, b, l = ctx["grower"], ctx["shed"], ctx["bin"], ctx["lot"]
        assess_lot(l["id"], l["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=20.00, assessment_date="2026-08-02")
        apply_inhibitor(l["id"], "2026-08-02T00:00:00Z")
        contract = create_contract(committed_volume_cwt=500.00, price_cents_per_cwt=2000,
                                   grade_min_us1_pct=80.0, buyer_name="Buyer A")
        set_clock("2026-08-30T00:00:00Z")
        st = create_settlement(g["id"], g["version"])
        order = create_order(s["id"], contract_id=contract["id"],
                             requested_packed_cwt=200.00, grade_min_us1_pct=80.0)
        allocate_order(order["id"])
        record_pass_wash(s["id"], "2026-08-30T00:00:00Z")
        ship_order(order["id"], l["id"], 222.22, 200.00, 170.00, 30.00, 22.22,
                   "2026-08-30T08:00:00Z", "2026-08-30T10:00:00Z")
        hold_and_condemn_lot(l["id"], "WASTE")  # closes the lot; clock still 08-30
        set_clock("2026-09-13T00:00:00Z")

        resp = api_finalize(st["id"], "clerk_one")
        fin = validate_success(resp, expected_status=200)

        assert fin["status"] == "FINALIZED"
        assert abs(fin["packed_cwt_basis"] - 200.00) <= 0.005
        assert abs(fin["pool_price_cents"] - 2000.00) <= 0.005
        assert abs(fin["gross_cents"] - 400000.00) <= 0.005
        assert abs(fin["storage_fees_cents"] - 50000.00) <= 0.005
        # net = 400000 - 50000 (storage) - 8000 (inhibitor: 8 x 1000.00 x 1) + 0 = 342000
        assert abs(fin["net_payable_cents"] - 342000.00) <= 0.005
        # The two variants price the same history differently.
        assert abs(st["net_payable_cents"] - fin["net_payable_cents"]) > 0.01


class TestPerLotRoundThenSum:
    def test_storage_fees_rounded_per_lot_then_summed(self, api):
        """PRD §3.9: "`storage_fees_cents` is the sum over the grower's lots of a per-lot storage fee: the fee per lot is 12.5 cents times the lot's `original_weight_cwt` times the number of completed whole weeks in storage, rounded half-up to two decimals per lot before summing."
        PRD §3.9: "The per-lot-then-sum rounding order is pinned — summing first and rounding once is forbidden, because at this rate the two orders diverge by at least a cent whenever an odd number of lots lands on a fractional-cent product."

        Design: Difficulty/combinatorial_formula/settlement_fee_per_lot_round_then_sum
        """
        set_clock("2026-08-05T00:00:00Z")
        grower = create_grower("Grower Four", "G-FOUR")
        shed = create_shed("Shed D")
        bin_ = create_bin(shed["id"])
        for _ in range(2):
            lot = create_binned_lot(grower["id"], bin_["id"], harvest_date="2026-07-28",
                                    original_weight_cwt=100.01)
            apply_inhibitor(lot["id"], "2026-08-05T00:00:00Z")
        set_clock("2026-08-12T00:00:00Z")
        for lot_data in api.list_field_lots(STORAGE, params={"grower_id": grower["id"]}).json()["data"]:
            hold_and_condemn_lot(lot_data["id"], "WASTE")
        st = create_settlement(grower["id"], grower["version"])

        resp = api_finalize(st["id"], "clerk_one")
        fin = validate_success(resp, expected_status=200)

        # per-lot round_half_up(12.5 * 100.01 * 1) = 1250.13; summed twice = 2500.26
        assert abs(fin["storage_fees_cents"] - 2500.26) <= 0.005

    def test_negative_net_payable_allowed_when_fees_exceed_gross(self, api):
        """PRD §3.9: "The `net_payable_cents` is the gross less storage fees less inhibitor fees plus processing credits; no floor is applied, so a negative net means the grower owes the shed."
        PRD §3.9: "`inhibitor_fees_cents` is the sum over the grower's lots of 8 cents times the lot's `original_weight_cwt` times its `inhibitor_application_count`, again rounded per lot before summing."

        Design: Difficulty/combinatorial_formula/settlement_fee_per_lot_round_then_sum
        """
        set_clock("2026-08-05T00:00:00Z")
        grower = create_grower("Grower Four", "G-FOUR")
        shed = create_shed("Shed D")
        bin_ = create_bin(shed["id"])
        for _ in range(2):
            lot = create_binned_lot(grower["id"], bin_["id"], harvest_date="2026-07-28",
                                    original_weight_cwt=100.01)
            apply_inhibitor(lot["id"], "2026-08-05T00:00:00Z")
        set_clock("2026-08-12T00:00:00Z")
        for lot_data in api.list_field_lots(STORAGE, params={"grower_id": grower["id"]}).json()["data"]:
            hold_and_condemn_lot(lot_data["id"], "WASTE")
        st = create_settlement(grower["id"], grower["version"])

        fin = validate_success(api_finalize(st["id"], "clerk_one"), expected_status=200)

        # inhibitor: round_half_up(8 * 100.01 * 1) = 800.08 per lot, twice = 1600.16
        assert abs(fin["inhibitor_fees_cents"] - 1600.16) <= 0.005
        assert abs(fin["gross_cents"] - 0.00) <= 0.005  # zero packed basis
        # net = 0 - 2500.26 - 1600.16 + 0 = -4100.42 (negative allowed)
        assert abs(fin["net_payable_cents"] - (-4100.42)) <= 0.005


class TestPoolPriceEvaluationOrder:
    def test_pool_prices_grower_with_own_shipment_included(self, api):
        """PRD §3.9: "It is computed in two steps to resolve an apparent circularity. First, the pool aggregate is built from shipped orders only: the sum, over every `SHIPPED` contract order, of its `packed_to_date_cwt` multiplied by its contract's `price_cents_per_cwt`, plus the corresponding sum over `SHIPPED` open-market orders using each order's `market_price_cents_per_cwt`, divided by the total `packed_to_date_cwt` across all shipped orders, rounded half-up to two decimals."
        PRD §3.9: "A grower's own shipped orders do contribute to the pool that prices that grower's settlement, and provisional settlements never feed the pool."

        Design: Difficulty/combinatorial_formula/pool_price_evaluation_order_pinning
        """
        set_clock("2026-08-02T00:00:00Z")
        g1 = create_grower("Grower Five", "G-FIVE")
        g2 = create_grower("Grower Six", "G-SIX")
        shed = create_shed("Shed E")
        bin_ = create_bin(shed["id"], capacity_cwt=5000.00)
        l1 = create_binned_lot(g1["id"], bin_["id"], original_weight_cwt=500.00)
        create_binned_lot(g2["id"], bin_["id"], harvest_date="2026-07-21",
                          original_weight_cwt=500.00)
        contract = create_contract(committed_volume_cwt=100.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer D")
        o1 = create_order(shed["id"], contract_id=contract["id"], requested_packed_cwt=100.00,
                          allocation_policy="SHED_BLEND")
        allocate_order(o1["id"])
        set_clock("2026-08-10T00:00:00Z")
        record_pass_wash(shed["id"], "2026-08-10T00:00:00Z")
        # Reservation per PRD §3.4 is rhu(100 / 0.75) = 133.33; the draw may not exceed it.
        ship_order(o1["id"], l1["id"], 133.33, 100.00, 90.00, 10.00, 33.33,
                   "2026-08-10T08:00:00Z", "2026-08-10T09:00:00Z")
        o2 = create_order(shed["id"], order_type="OPEN_MARKET", requested_packed_cwt=100.00,
                          allocation_policy="SHED_BLEND", market_price_cents_per_cwt=3000)
        allocate_order(o2["id"])
        ship_order(o2["id"], l1["id"], 133.33, 100.00, 90.00, 10.00, 33.33,
                   "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z")
        set_clock("2026-08-16T00:00:00Z")
        hold_and_condemn_lot(l1["id"], "WASTE")  # L1 remnant closes the lot
        st = create_settlement(g1["id"], g1["version"])

        fin = validate_success(api_finalize(st["id"], "clerk_one"), expected_status=200)

        # pool = (100x2000 + 100x3000) / 200 = 2500.00 — not G1's contract price 2000
        assert abs(fin["pool_price_cents"] - 2500.00) <= 0.005
        # Both ships drew on G1's L1: packed_total 200.00 -> basis 200.00, gross 200 x 2500.
        assert abs(fin["packed_cwt_basis"] - 200.00) <= 0.005
        assert abs(fin["gross_cents"] - 500000.00) <= 0.005

    def test_final_variant_storage_weeks_and_net(self, api):
        """PRD §3.9: "for the final variant it is the whole weeks between `binned_at` and `closed_at`."
        PRD §3.9: "The `net_payable_cents` is the gross less storage fees less inhibitor fees plus processing credits".

        Design: Difficulty/combinatorial_formula/pool_price_evaluation_order_pinning
        """
        set_clock("2026-08-02T00:00:00Z")
        g1 = create_grower("Grower Five", "G-FIVE")
        g2 = create_grower("Grower Six", "G-SIX")
        shed = create_shed("Shed E")
        bin_ = create_bin(shed["id"], capacity_cwt=5000.00)
        l1 = create_binned_lot(g1["id"], bin_["id"], original_weight_cwt=500.00)
        create_binned_lot(g2["id"], bin_["id"], harvest_date="2026-07-21",
                          original_weight_cwt=500.00)
        contract = create_contract(committed_volume_cwt=100.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer D")
        o1 = create_order(shed["id"], contract_id=contract["id"], requested_packed_cwt=100.00,
                          allocation_policy="SHED_BLEND")
        allocate_order(o1["id"])
        set_clock("2026-08-10T00:00:00Z")
        record_pass_wash(shed["id"], "2026-08-10T00:00:00Z")
        # Reservation per PRD §3.4 is rhu(100 / 0.75) = 133.33; the draw may not exceed it.
        ship_order(o1["id"], l1["id"], 133.33, 100.00, 90.00, 10.00, 33.33,
                   "2026-08-10T08:00:00Z", "2026-08-10T09:00:00Z")
        o2 = create_order(shed["id"], order_type="OPEN_MARKET", requested_packed_cwt=100.00,
                          allocation_policy="SHED_BLEND", market_price_cents_per_cwt=3000)
        allocate_order(o2["id"])
        ship_order(o2["id"], l1["id"], 133.33, 100.00, 90.00, 10.00, 33.33,
                   "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z")
        set_clock("2026-08-16T00:00:00Z")
        hold_and_condemn_lot(l1["id"], "WASTE")  # closed exactly 14 days after binning
        st = create_settlement(g1["id"], g1["version"])

        fin = validate_success(api_finalize(st["id"], "clerk_one"), expected_status=200)

        # fee = 12.5 x 500.00 x 2 weeks = 12500.00; gross = 200.00 basis x 2500 pool = 500000;
        # net = 500000 - 12500 - 0 + 0 = 487500
        assert abs(fin["storage_fees_cents"] - 12500.00) <= 0.005
        assert abs(fin["net_payable_cents"] - 487500.00) <= 0.005

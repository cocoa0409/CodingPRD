"""Allocation: dual packout variants, the open-market cap combinatorial, waterfall
ranking, fiscal boundaries, and pool-sufficiency atomicity (PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data, ApiErrorId,
    setup_grower_shed_bin_lot, create_grower, create_shed, create_bin, create_lot,
    create_binned_lot, bin_lot, assess_lot, create_contract, create_order, allocate_order,
    refresh_lot, refresh_order, refresh_contract,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_headers"]
STORAGE = TEST_USERS["storage_headers"]


class TestAllocationPolicyVariants:
    @staticmethod
    def _setup_two_lot_pool():
        """Shed with lot A (200.00, fraction 0.80) and lot B (300.00, fraction 0.60),
        plus a 1000.00 @ 2500 contract. No completed run exists, so SHED_BLEND uses 0.75."""
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Two", grower_code="G-TWO", shed_name="Shed B",
            lot_weight_cwt=200.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        g, s, b = ctx["grower"], ctx["shed"], ctx["bin"]
        la = ctx["lot"]
        assess_lot(la["id"], la["version"], us1_pct=60.0, us2_pct=20.0, cull_pct=20.0,
                   cumulative_shrink_cwt=0.00)
        lb = create_binned_lot(g["id"], b["id"], harvest_date="2026-07-25",
                               original_weight_cwt=300.00)
        assess_lot(lb["id"], lb["version"], us1_pct=40.0, us2_pct=20.0, cull_pct=40.0,
                   cumulative_shrink_cwt=0.00)
        contract = create_contract(committed_volume_cwt=1000.00, price_cents_per_cwt=2500,
                                   buyer_name="Buyer B")
        return {"grower": g, "shed": s, "bin": b, "lot_a": la, "lot_b": lb,
                "contract": contract}

    def test_lot_assessment_policy_sizes_draw_from_lot_fraction(self, api):
        """PRD §3.4: "Under `LOT_ASSESSMENT`, each lot's fraction is its latest assessment's `packable_fraction`; a lot with no assessment uses the default blend fraction of 0.75."
        PRD §3.4: "The raw reservation written for the lot is the taken amount divided by the fraction, rounded half-up to two decimal places, but capped at the lot's allocatable weight".

        Design: Difficulty/dual_variant_calc/raw_draw_lot_assessment_vs_shed_blend
        """
        ctx = self._setup_two_lot_pool()
        o1 = create_order(ctx["shed"]["id"], contract_id=ctx["contract"]["id"],
                          requested_packed_cwt=100.00, allocation_policy="LOT_ASSESSMENT")
        o1 = validate_success(api.allocate_order(o1["id"], SALES), expected_status=200)

        # 100 / 0.80 = 125.00 raw on the earliest-harvest lot; single-lot cover
        assert o1["status"] == "ALLOCATED"
        assert len(o1["reservations"]) == 1
        res = o1["reservations"][0]
        assert res["field_lot_id"] == ctx["lot_a"]["id"]
        assert abs(res["raw_cwt"] - 125.00) <= 0.005
        assert abs(res["packed_equiv_cwt"] - 100.00) <= 0.005

    def test_shed_blend_policy_sizes_draw_from_default_blend(self, api):
        """PRD §3.4: "Under `SHED_BLEND`, a single realized fraction is computed across every lot in the shed — the total `packed_cwt` over all draws from `COMPLETED` runs in the shed divided by the total `raw_drawn_cwt` over the same draws (`ABORTED` runs are excluded) — and applied uniformly; if the shed has no completed run yet, the same 0.75 default applies."
        PRD §3.4: "Within the pool, lots are ranked by `harvest_date` ascending with ties broken by `created_at` ascending (never by `id`)."

        Design: Difficulty/dual_variant_calc/raw_draw_lot_assessment_vs_shed_blend
        """
        ctx = self._setup_two_lot_pool()
        # Deplete lot A first so the blend order must continue onto lot B.
        o1 = create_order(ctx["shed"]["id"], contract_id=ctx["contract"]["id"],
                          requested_packed_cwt=100.00, allocation_policy="LOT_ASSESSMENT")
        allocate_order(o1["id"])

        o2 = create_order(ctx["shed"]["id"], contract_id=ctx["contract"]["id"],
                          requested_packed_cwt=100.00, allocation_policy="SHED_BLEND")
        o2 = validate_success(api.allocate_order(o2["id"], SALES), expected_status=200)

        # blend 0.75 over lot A's remaining 75.00 allocatable, then lot B
        assert o2["status"] == "ALLOCATED"
        assert len(o2["reservations"]) == 2
        res_a, res_b = o2["reservations"]
        assert res_a["field_lot_id"] == ctx["lot_a"]["id"]
        assert abs(res_a["raw_cwt"] - 75.00) <= 0.005
        assert abs(res_a["packed_equiv_cwt"] - 56.25) <= 0.005
        assert res_b["field_lot_id"] == ctx["lot_b"]["id"]
        assert abs(res_b["raw_cwt"] - 58.33) <= 0.005
        assert abs(res_b["packed_equiv_cwt"] - 43.75) <= 0.005

        # Reserved weight reconciles across both orders.
        lot_a = refresh_lot(ctx["lot_a"]["id"])
        lot_b = refresh_lot(ctx["lot_b"]["id"])
        assert abs(lot_a["reserved_cwt"] - 200.00) <= 0.005
        assert abs(lot_b["reserved_cwt"] - 58.33) <= 0.005


class TestOpenMarketCap:
    @staticmethod
    def _setup_cap_scenario():
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Three", grower_code="G-THREE", shed_name="Shed C",
            lot_weight_cwt=400.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        g, s, b = ctx["grower"], ctx["shed"], ctx["bin"]
        l1 = ctx["lot"]
        assess_lot(l1["id"], l1["version"], us1_pct=60.0, us2_pct=20.0, cull_pct=20.0,
                   cumulative_shrink_cwt=0.00)
        l2 = create_binned_lot(g["id"], b["id"], harvest_date="2026-07-22",
                               original_weight_cwt=100.00)
        assess_lot(l2["id"], l2["version"], us1_pct=40.0, us2_pct=20.0, cull_pct=40.0,
                   cumulative_shrink_cwt=0.00)
        create_contract(committed_volume_cwt=200.00, price_cents_per_cwt=2000,
                        buyer_name="Buyer C1", priority_rank=1)
        create_contract(committed_volume_cwt=100.00, price_cents_per_cwt=3000,
                        buyer_name="Buyer C2", priority_rank=2)
        return {"grower": g, "shed": s, "bin": b, "lot1": l1, "lot2": l2}

    def test_open_market_cap_equality_allocates(self, api):
        """PRD §3.4: "For an `OPEN_MARKET` order, the requested volume must not exceed the open-market cap for the order's variety and shed; exceeding it is `ERR_OPEN_MARKET_CAP_EXCEEDED`, with equality allowed."
        PRD §3.4: "The cap is computed by taking, for every lot in the same eligible pool, the lot's allocatable weight multiplied by its lot-assessment fraction — the cap always uses the lot-assessment basis regardless of the order's `allocation_policy` — rounding each per-lot product half-up to two decimals, summing, and then subtracting the total `remaining_committed_cwt` over every `ACTIVE` contract of the same variety".

        Design: Difficulty/combinatorial_formula/open_market_cap_net_of_contract_commitments
        """
        ctx = self._setup_cap_scenario()
        # cap = max(0, 400x0.8 + 100x0.6 - (200 + 100)) = 80.00
        o1 = create_order(ctx["shed"]["id"], order_type="OPEN_MARKET",
                          requested_packed_cwt=80.00, market_price_cents_per_cwt=2800)
        o1 = validate_success(api.allocate_order(o1["id"], SALES), expected_status=200)

        assert o1["status"] == "ALLOCATED"
        assert len(o1["reservations"]) == 1
        res = o1["reservations"][0]
        assert res["field_lot_id"] == ctx["lot1"]["id"]
        assert abs(res["raw_cwt"] - 100.00) <= 0.005  # 80 / 0.80
        assert abs(res["packed_equiv_cwt"] - 80.00) <= 0.005

    def test_open_market_cap_exceeded_after_reservation_shrinks_cap(self, api):
        """PRD §3.4: "For an `OPEN_MARKET` order, the requested volume must not exceed the open-market cap for the order's variety and shed; exceeding it is `ERR_OPEN_MARKET_CAP_EXCEEDED`, with equality allowed."
        PRD §3.4: "The cap is floored at zero."

        Design: Difficulty/combinatorial_formula/open_market_cap_net_of_contract_commitments
        """
        ctx = self._setup_cap_scenario()
        o1 = create_order(ctx["shed"]["id"], order_type="OPEN_MARKET",
                          requested_packed_cwt=80.00, market_price_cents_per_cwt=2800)
        allocate_order(o1["id"])

        # After o1 reserved 100.00 raw from lot1, cap recomputes to 0.00; 0.01 > 0.00.
        o2 = create_order(ctx["shed"]["id"], order_type="OPEN_MARKET",
                          requested_packed_cwt=0.01, market_price_cents_per_cwt=2800)
        resp = api.allocate_order(o2["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_OPEN_MARKET_CAP_EXCEEDED)


class TestCommitmentBoundary:
    @staticmethod
    def _setup_commitment_scenario():
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Twelve", grower_code="G-TWELVE", shed_name="Shed L",
            lot_weight_cwt=1000.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        l = ctx["lot"]
        assess_lot(l["id"], l["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=0.00)
        contract = create_contract(committed_volume_cwt=300.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer J")
        return {**ctx, "contract": contract}

    def test_commitment_equality_allowed(self, api):
        """PRD §3.4: "For a `CONTRACT` order, the requested volume must not exceed the contract's `remaining_committed_cwt` (equality is allowed); exceeding it is `ERR_COMMITMENT_EXCEEDED`".

        Design: Difficulty/boundary_precision_check/commitment_equality_allowed_overage_rejected
        """
        ctx = self._setup_commitment_scenario()
        o1 = create_order(ctx["shed"]["id"], contract_id=ctx["contract"]["id"],
                          requested_packed_cwt=300.00)
        o1 = validate_success(api.allocate_order(o1["id"], SALES), expected_status=200)

        assert o1["status"] == "ALLOCATED"
        assert len(o1["reservations"]) == 1
        assert abs(o1["reservations"][0]["raw_cwt"] - 333.33) <= 0.005  # 300 / 0.9
        contract = refresh_contract(ctx["contract"]["id"])
        assert abs(contract["remaining_committed_cwt"] - 0.00) <= 0.005

    def test_commitment_overage_rejected(self, api):
        """PRD §3.4: "For a `CONTRACT` order, the requested volume must not exceed the contract's `remaining_committed_cwt` (equality is allowed); exceeding it is `ERR_COMMITMENT_EXCEEDED`".

        Design: Difficulty/boundary_precision_check/commitment_equality_allowed_overage_rejected
        """
        ctx = self._setup_commitment_scenario()
        o1 = create_order(ctx["shed"]["id"], contract_id=ctx["contract"]["id"],
                          requested_packed_cwt=300.00)
        allocate_order(o1["id"])

        o2 = create_order(ctx["shed"]["id"], contract_id=ctx["contract"]["id"],
                          requested_packed_cwt=0.01)
        resp = api.allocate_order(o2["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXCEEDED)


class TestWaterfallRanking:
    def test_earlier_harvest_lot_drained_first(self, api):
        """PRD §3.4: "Within the pool, lots are ranked by `harvest_date` ascending with ties broken by `created_at` ascending (never by `id`)."

        Design: Corner/calculations/c_allocation_ranking_harvest_then_created
        """
        from test_helpers import set_clock
        set_clock("2026-08-02T00:00:00Z")
        grower = create_grower("Grower T", "G-T")
        shed = create_shed("Shed DE")
        bin_ = create_bin(shed["id"])
        # NEW lot created first but harvested later; OLD harvested earlier but intaked second.
        l_new = create_binned_lot(grower["id"], bin_["id"], harvest_date="2026-07-25",
                                  original_weight_cwt=100.00)
        l_old = create_binned_lot(grower["id"], bin_["id"], harvest_date="2026-07-15",
                                  original_weight_cwt=100.00)
        contract = create_contract(committed_volume_cwt=500.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer U")
        order = create_order(shed["id"], contract_id=contract["id"],
                             requested_packed_cwt=75.00)
        order = validate_success(api.allocate_order(order["id"], SALES), expected_status=200)

        assert len(order["reservations"]) == 1
        res = order["reservations"][0]
        assert res["field_lot_id"] == l_old["id"]  # earlier harvest wins despite later intake
        assert abs(res["raw_cwt"] - 100.00) <= 0.005  # 75 / 0.75 capped at allocatable
        assert abs(res["packed_equiv_cwt"] - 75.00) <= 0.005


class TestPoolSufficiencyAtomicity:
    def test_insufficient_pool_rejected_atomically(self, api):
        """PRD §3.4: "Before any reservation is written, the server checks that the coverage summed across the entire eligible pool meets the need — where need is the requested volume less what has already been packed less the packed-equivalent already covered by existing reservations. If the pool's total coverage falls short, or the pool is empty, the request is rejected with `ERR_INSUFFICIENT_ALLOCATION_POOL` and no reservations are created."

        Design: Corner/validations/c_allocate_pool_insufficient_returns_422_atomic
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower AE", grower_code="G-AE", shed_name="Shed DP",
            lot_weight_cwt=100.00, harvest_date="2026-07-20",
        )
        contract = create_contract(committed_volume_cwt=500.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer Y")
        order = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                             requested_packed_cwt=76.00)  # cover 75.00 < 76.00
        resp = api.allocate_order(order["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ALLOCATION_POOL)

        order = refresh_order(order["id"])
        assert order["status"] == "REQUESTED"
        assert order["reservations"] == []
        lot = refresh_lot(ctx["lot"]["id"])
        assert abs(lot["reserved_cwt"] - 0.00) <= 0.005
        contract = refresh_contract(contract["id"])
        assert abs(contract["remaining_committed_cwt"] - 500.00) <= 0.005


class TestContractStateGateOnAllocate:
    def test_allocation_succeeds_while_contract_active(self, api):
        """PRD §3.4: "For a `CONTRACT` order, the requested volume must not exceed the contract's `remaining_committed_cwt` (equality is allowed); exceeding it is `ERR_COMMITMENT_EXCEEDED`, and a contract that is no longer `ACTIVE` rejects the allocation with `ERR_CONTRACT_INVALID_STATE`."
        PRD §3.4: "A successful first allocation from `REQUESTED` transitions the order to `ALLOCATED` and bumps its `version`."

        Design: Difficulty/cross_entity_state_dependency/allocate_requires_contract_active
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Fifteen", grower_code="G-15", shed_name="Shed O",
            lot_weight_cwt=500.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        contract = create_contract(committed_volume_cwt=100.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer K",
                                   delivery_window_end="2026-08-20T00:00:00Z")
        order = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                             requested_packed_cwt=50.00)

        # Allocate BEFORE the window closes: the ACTIVE gate passes.
        resp = api.allocate_order(order["id"], SALES)
        allocated = validate_success(resp, expected_status=200)
        assert allocated["status"] == "ALLOCATED"
        assert len(allocated["reservations"]) == 1
        assert allocated["version"] == 2

    def test_allocate_against_settled_contract_rejected(self, api):
        """PRD §3.4: "a contract that is no longer `ACTIVE` rejects the allocation with `ERR_CONTRACT_INVALID_STATE`."
        PRD §2.5: "the season-settle sweep runs on every clock advance: any `ACTIVE` contract whose `delivery_window_end` is now in the past is settled. When a contract's packed actuals have reached at least its committed volume the contract is marked `FULFILLED`; otherwise it is marked `SHORTFALLED`."

        Design: Difficulty/cross_entity_state_dependency/allocate_requires_contract_active
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Fifteen", grower_code="G-15", shed_name="Shed O",
            lot_weight_cwt=500.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        contract = create_contract(committed_volume_cwt=100.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer K",
                                   delivery_window_end="2026-08-20T00:00:00Z")
        order = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                             requested_packed_cwt=50.00)
        from test_helpers import set_clock
        set_clock("2026-08-21T00:00:00Z")

        contract = refresh_contract(contract["id"])
        assert contract["status"] == "SHORTFALLED"  # packed 0 < committed 100

        resp = api.allocate_order(order["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_INVALID_STATE)
        order = refresh_order(order["id"])
        assert order["status"] == "REQUESTED"
        assert order["reservations"] == []

    def test_auto_settle_fulfilled_when_packed_reaches_commitment(self, api):
        """PRD §2.5: "the season-settle sweep runs on every clock advance: any `ACTIVE` contract whose `delivery_window_end` is now in the past is settled. When a contract's packed actuals have reached at least its committed volume the contract is marked `FULFILLED`; otherwise it is marked `SHORTFALLED`."

        Design: Corner/state_machines/c_contract_auto_settle_fulfilled
        """
        from test_helpers import set_clock, record_pass_wash, ship_order
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower N", grower_code="G-N", shed_name="Shed CI",
            lot_weight_cwt=500.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        contract = create_contract(committed_volume_cwt=100.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer S",
                                   delivery_window_end="2026-08-20T00:00:00Z")
        order = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                             requested_packed_cwt=100.00, allocation_policy="SHED_BLEND")
        allocate_order(order["id"])
        record_pass_wash(ctx["shed"]["id"], "2026-08-10T00:00:00Z")
        set_clock("2026-08-10T00:00:00Z")
        # Reservation per PRD §3.4 is rhu(100 / 0.75) = 133.33; the draw may not exceed it.
        ship_order(order["id"], ctx["lot"]["id"], 133.33, 100.00, 90.00, 10.00, 33.33,
                   "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")

        set_clock("2026-08-21T00:00:00Z")
        contract = refresh_contract(contract["id"])
        assert contract["status"] == "FULFILLED"  # packed 100.00 >= committed 100.00

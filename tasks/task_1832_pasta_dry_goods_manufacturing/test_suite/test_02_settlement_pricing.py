"""Settlement pricing: index-linked variants, volume tiers, ratio fallbacks,
and lot receipt computed fields."""
from test_helpers import (
    add_index_reading,
    api_client,
    assert_lot_mass_invariant,
    assert_semolina_lot,
    create_active_contract,
    create_contract_draft,
    get_success_data,
    receive_lot,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PROC = TEST_USERS["procurement_manager_headers"]


def _contract_with_readings(code, pricing_method, ingredient_type, readings,
                            base_price_cents_per_kg=500):
    """DRAFT -> readings -> ACTIVE. Readings attach in DRAFT or ACTIVE."""
    contract = create_contract_draft(
        contract_code=code, pricing_method=pricing_method,
        ingredient_type=ingredient_type,
        base_price_cents_per_kg=base_price_cents_per_kg,
    )
    for effective_date, index_value in readings:
        add_index_reading(contract["id"], effective_date, index_value)
    return get_success_data(api_client.activate_contract(contract["id"], PM))


def _receive(contract_id, weight, delivery_date):
    return receive_lot(contract_id, weight, delivery_date=delivery_date)


def test_lot_receipt_computed_fields_and_defaults(api):
    """PRD: "if no such reading exists, the ratio is 1.0000"
    PRD: "The new lot starts `QUARANTINED`, with `remaining_weight_kg`
    initialized to the received weight and `consumed_kg` at zero"
    PRD: "store it as `lab_grade_score` and `lab_grade` (both null until lab
    results exist)"

    Design: Corner/entities/lot_receipt_computed_fields_and_defaults
    """
    contract = create_active_contract(contract_code="C-CMP")
    lot = _receive(contract["id"], 100.0, "2026-08-01")

    assert_semolina_lot(lot)
    assert lot["unit_price_cents"] == 500, "ratio fallback 1.0000, tier 1"
    assert lot["total_price_cents"] == 50000
    assert lot["remaining_weight_kg"] == 100.0
    assert lot["consumed_kg"] == 0
    assert lot["status"] == "QUARANTINED"
    assert lot["lab_grade_score"] is None and lot["lab_grade"] is None
    assert_lot_mass_invariant(lot)


def test_spot_blend_empty_window_fallbacks(api):
    """PRD: "if that window contains no reading, the ratio falls back to the
    reading with the greatest `effective_date` before the window, and if there
    is none, the ratio is 1.0000"

    Design: Corner/calculations/spot_blend_empty_window_fallbacks
    """
    contract_d = _contract_with_readings("C-SBD", "SPOT_BLEND", "SEMOLINA",
                                         [("2026-06-01", 80.0)])
    contract_e = _contract_with_readings("C-SBE", "SPOT_BLEND", "RICE_FLOUR", [])

    lot_d = _receive(contract_d["id"], 100.0, "2026-08-15")
    assert lot_d["unit_price_cents"] == 400, "fallback to pre-window 80.0 reading: ratio 0.8"
    assert lot_d["total_price_cents"] == 40000

    lot_e = _receive(contract_e["id"], 100.0, "2026-08-15")
    assert lot_e["unit_price_cents"] == 500, "no readings at all: ratio 1.0000"


def _divergence_world():
    """Contract A SEMOLINA INDEX_LAGGED (07-31=90, 08-01=120) and contract B
    DURUM_SEMOLINA SPOT_BLEND (07-20=100, 08-10=110); one 100 kg receipt each
    delivered 2026-08-15."""
    contract_a = _contract_with_readings("C-PRC-A", "INDEX_LAGGED", "SEMOLINA",
                                         [("2026-07-31", 90.0), ("2026-08-01", 120.0)])
    contract_b = _contract_with_readings("C-PRC-B", "SPOT_BLEND", "DURUM_SEMOLINA",
                                         [("2026-07-20", 100.0), ("2026-08-10", 110.0)])
    lot_a = _receive(contract_a["id"], 100.0, "2026-08-15")
    lot_b = _receive(contract_b["id"], 100.0, "2026-08-15")
    return lot_a, lot_b


class TestSettlementVariantDivergence:
    def test_index_lagged_prices_off_month_start_reading(self, api):
        """PRD: "Under `INDEX_LAGGED`, the ratio is the `index_value` of the
        reading with the greatest `effective_date` on or before the first day of
        the delivery month, divided by the contract's `reference_index_value`"
        PRD: "Third, `unit_price_cents` is the contract's
        `base_price_cents_per_kg` multiplied by the ratio and by one minus the
        tier discount, rounded half-up to integer cents."

        Design: Difficulty/dual_variant_calc/settlement_price_index_lagged_vs_spot_blend_divergence
        """
        lot_a, lot_b = _divergence_world()
        assert lot_a["unit_price_cents"] == 600, "120.0/100.0 = 1.2; 500 * 1.2 = 600"
        assert lot_a["total_price_cents"] == 60000
        assert lot_a["unit_price_cents"] != lot_b["unit_price_cents"], (
            "the two pricing variants diverge on identical base/reference/weight"
        )

    def test_spot_blend_averages_thirty_day_window(self, api):
        """PRD: "Under `SPOT_BLEND`, the ratio is the mean of `index_value`
        across readings whose `effective_date` falls inside the window from
        thirty days before the `delivery_date` through the `delivery_date`
        itself, both days inclusive, divided by `reference_index_value`"

        Design: Difficulty/dual_variant_calc/settlement_price_index_lagged_vs_spot_blend_divergence
        """
        _, lot_b = _divergence_world()
        assert lot_b["unit_price_cents"] == 525, "mean(100, 110) = 105; ratio 1.05; 525"
        assert lot_b["total_price_cents"] == 52500


def _tier_contract_with_first_receipt(first_weight, code="C-TIER"):
    contract = create_active_contract(contract_code=code, base_price_cents_per_kg=400)
    lot1 = _receive(contract["id"], first_weight, "2026-08-01")
    return contract, lot1


class TestSettlementTierEvaluationOrder:
    def test_tier_read_before_current_delivery_added(self, api):
        """PRD: "Second, the volume tier is read from the contract's
        `cumulative_delivered_kg` as it stood before this delivery"
        PRD: "below twenty thousand kilograms is tier 1 with no discount"

        Design: Difficulty/combinatorial_formula/settlement_tier_evaluation_order_pre_delivery_cumulative
        """
        contract, lot1 = _tier_contract_with_first_receipt(19900.0)
        assert lot1["unit_price_cents"] == 400, "tier 1 at cumulative 0"

        lot2 = _receive(contract["id"], 500.0, "2026-08-02")
        assert lot2["unit_price_cents"] == 400, (
            "cumulative was 19900 < 20000 when read, so the crossing receipt "
            "still prices at tier 1"
        )
        assert lot2["total_price_cents"] == 200000

    def test_next_receipt_after_crossing_sees_tier2(self, api):
        """PRD: "from twenty thousand up to but not including fifty thousand
        kilograms is tier 2 with a 0.02 discount"
        PRD: "Only after pricing does the contract's `cumulative_delivered_kg`
        increase by the delivered weight."

        Design: Difficulty/combinatorial_formula/settlement_tier_evaluation_order_pre_delivery_cumulative
        """
        contract, _ = _tier_contract_with_first_receipt(19900.0)
        _receive(contract["id"], 500.0, "2026-08-02")
        lot3 = _receive(contract["id"], 100.0, "2026-08-03")

        assert lot3["unit_price_cents"] == 392, "tier 2 at cumulative 20400: 400 * 0.98"
        assert lot3["total_price_cents"] == 39200
        contract_after = validate_success(api.get_contract(contract["id"], PROC))
        assert contract_after["cumulative_delivered_kg"] == 20500.0


class TestContractTierBoundaryExact20000:
    def test_cumulative_exactly_20000_prices_next_receipt_tier2(self, api):
        """PRD: "a cumulative figure of exactly twenty thousand kilograms lands
        in tier 2, because the boundary is inclusive"
        PRD: "Second, the volume tier is read from the contract's
        `cumulative_delivered_kg` as it stood before this delivery"

        Design: Difficulty/boundary_precision_check/contract_tier_boundary_exact_20000_kg
        """
        contract, lot1 = _tier_contract_with_first_receipt(20000.0, code="C-TB")
        assert lot1["unit_price_cents"] == 400, "tier 1 while cumulative 0"

        lot2 = _receive(contract["id"], 500.0, "2026-08-02")
        assert lot2["unit_price_cents"] == 392, (
            "cumulative was exactly 20000, and the boundary is inclusive"
        )
        assert lot2["total_price_cents"] == 196000

    def test_tier2_persists_below_50000_and_cumulative_tracks(self, api):
        """PRD: "from twenty thousand up to but not including fifty thousand
        kilograms is tier 2 with a 0.02 discount"
        PRD: "Only after pricing does the contract's `cumulative_delivered_kg`
        increase by the delivered weight."

        Design: Difficulty/boundary_precision_check/contract_tier_boundary_exact_20000_kg
        """
        contract, _ = _tier_contract_with_first_receipt(20000.0, code="C-TB2")
        _receive(contract["id"], 500.0, "2026-08-02")
        lot3 = _receive(contract["id"], 100.0, "2026-08-03")

        assert lot3["unit_price_cents"] == 392, "20500 is still tier 2"
        contract_after = validate_success(api.get_contract(contract["id"], PROC))
        assert contract_after["cumulative_delivered_kg"] == 20600.0, (
            "20000 + 500 + 100: cumulative increases by the delivered weight "
            "after each pricing"
        )

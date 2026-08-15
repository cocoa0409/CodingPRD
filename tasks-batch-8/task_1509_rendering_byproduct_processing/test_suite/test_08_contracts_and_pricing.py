"""Customer contracts, price index entries, and order pricing (PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_contract,
    create_order,
    create_plant,
    create_priced_order,
    publish_index_entry,
    read_contract_version,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
SM = TEST_USERS["sales_manager_headers"]
FA = TEST_USERS["finance_analyst_headers"]
ANY = TEST_USERS["any_headers"]

TIERS = [
    {"threshold_lbs": 50000, "discount_pct": 0.02},
    {"threshold_lbs": 100000, "discount_pct": 0.04},
]


def _index_linked_contract(plant_id, basis=4, tiers=None, margin_floor_pct=15.0,
                           volume_commitment_lbs=200000):
    return create_active_contract(
        plant_id,
        pricing_mode="INDEX_LINKED",
        index_product="TALLOW",
        index_basis_adjustment_cents=basis,
        volume_commitment_lbs=volume_commitment_lbs,
        tier_discounts=TIERS if tiers is None else tiers,
        margin_floor_pct=margin_floor_pct,
        base_price_cents_per_lb=None,
    )


class TestContractCreation:
    def test_fixed_contract_requires_base_price(self, api):
        """PRD §3.8: "Supplying a `FIXED` contract without a base price, or an
        `INDEX_LINKED` contract without its index fields, is a schema violation rejected
        with `ERR_INVALID_REQUEST`; the base price is ignored on index-linked contracts."

        Design: Corner/validations/fixed_contract_requires_base_price
        """
        plant = create_plant()
        base = {
            "plant_id": plant["id"],
            "product_type": "TALLOW",
            "spec_max_moisture_pct": 0.5,
            "spec_max_ffa_pct": 4.0,
            "spec_min_protein_pct": 0,
            "volume_commitment_lbs": 1000,
            "tier_discounts": [],
            "margin_floor_pct": 15.0,
            "effective_from": "2026-08-01",
            "effective_to": "2026-12-31",
        }
        # FIXED without base_price_cents_per_lb.
        res1 = api.create_customer_contract(
            {**base, "customer_name": "C1", "pricing_mode": "FIXED"}, SM
        )
        validate_error(res1, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        # INDEX_LINKED without index_product / index_basis_adjustment_cents.
        res2 = api.create_customer_contract(
            {**base, "customer_name": "C2", "pricing_mode": "INDEX_LINKED"}, SM
        )
        validate_error(res2, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestPriceIndexEntries:
    def test_duplicate_index_entry_rejected(self, api):
        """PRD §3.8: "Entries are unique per plant, product, and effective date — a
        duplicate returns `ERR_DUPLICATE_INDEX_ENTRY` — and, being append-only records, they
        carry no `updated_at` or `version` (§2.4)."

        Design: Corner/validations/duplicate_index_entry_rejected
        """
        plant = create_plant()
        publish_index_entry(plant["id"], index_product="TALLOW",
                            effective_date="2026-08-01", price_cents_per_lb=40,
                            source="JACOBSEN")

        res = api.create_price_index_entry(
            {
                "plant_id": plant["id"],
                "index_product": "TALLOW",
                "effective_date": "2026-08-01",
                "price_cents_per_lb": 42,
                "source": "USDA_AMS",
            },
            FA,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_INDEX_ENTRY, expected_status=409)

        # A different product on the same date is a distinct (plant, product, date) key.
        ok = publish_index_entry(plant["id"], index_product="MEAL",
                                 effective_date="2026-08-01", price_cents_per_lb=30,
                                 source="USDA_AMS")
        assert ok["index_product"] == "MEAL"


class TestIndexLinkedPricing:
    def test_price_without_index_coverage_rejected(self, api):
        """PRD §3.8: "on an `INDEX_LINKED` contract the server selects the plant's index
        entry whose `index_product` matches the contract's and whose `effective_date` is on
        or before the order's `requested_ship_date`, choosing the latest such date — ties
        cannot exist because entries are unique per plant, product, and date — and when no
        such entry exists pricing fails with `ERR_NO_INDEX_FOR_DATE`."
        PRD §3.8: "Until priced, the order's `unit_price_cents`, `applied_index_price_cents`,
        `applied_discount_pct`, `gross_amount_cents`, `discount_amount_cents`,
        `freight_surcharge_cents`, `net_amount_cents`, and `margin_pct` are all null."

        Design: Corner/validations/price_without_index_coverage_rejected
        """
        plant = create_plant()
        contract = _index_linked_contract(plant["id"], basis=2, tiers=[],
                                          margin_floor_pct=0.0,
                                          volume_commitment_lbs=1000)
        # The only entry is effective after the ship date, so nothing qualifies.
        publish_index_entry(plant["id"], effective_date="2026-09-01",
                            price_cents_per_lb=40)
        order = create_order(contract["id"], plant["id"],
                             requested_ship_date="2026-08-20")

        res = api.price_order(order["id"], {"expected_grade": "STANDARD"}, SM)
        validate_error(res, ApiErrorId.ERR_NO_INDEX_FOR_DATE, expected_status=422)

        order_after = validate_success(api.get_sales_order(order["id"], ANY), 200)
        assert order_after["status"] == "DRAFT"
        assert order_after["unit_price_cents"] is None

    def test_index_entry_exact_effective_date_selected(self, api):
        """PRD §3.8: "on an `INDEX_LINKED` contract the server selects the plant's index
        entry whose `index_product` matches the contract's and whose `effective_date` is on
        or before the order's `requested_ship_date`, choosing the latest such date — ties
        cannot exist because entries are unique per plant, product, and date — and when no
        such entry exists pricing fails with `ERR_NO_INDEX_FOR_DATE`."
        PRD §3.8: "The index-linked base is the entry's `price_cents_per_lb` plus the
        contract's `index_basis_adjustment_cents`, and `applied_index_price_cents` records
        the entry's price."

        Design: Corner/calculations/index_entry_exact_effective_date_selected
        """
        plant = create_plant()
        contract = _index_linked_contract(plant["id"], basis=2, tiers=[],
                                          margin_floor_pct=0.0,
                                          volume_commitment_lbs=1000)
        publish_index_entry(plant["id"], effective_date="2026-08-01",
                            price_cents_per_lb=40, source="JACOBSEN")
        publish_index_entry(plant["id"], effective_date="2026-08-10",
                            price_cents_per_lb=44, source="USDA_AMS")
        # Ship date exactly equal to the second entry's effective_date qualifies it.
        order = create_order(contract["id"], plant["id"], quantity_lbs=100,
                             requested_ship_date="2026-08-10")
        priced = validate_success(
            api.price_order(order["id"], {"expected_grade": "STANDARD"}, SM), 200
        )
        assert priced["applied_index_price_cents"] == 44
        # round_half_up((44 + 2) * 1.00) = 46
        assert priced["unit_price_cents"] == 46

    def test_fixed_pricing_ignores_index(self, api):
        """PRD §3.8: "on a `FIXED` contract the base is `base_price_cents_per_lb` and
        `applied_index_price_cents` stays null; ..."

        Design: Corner/calculations/fixed_pricing_ignores_index
        """
        plant = create_plant()
        contract = create_active_contract(plant["id"], base_price_cents_per_lb=50,
                                          margin_floor_pct=0.0)
        # An index entry exists but must not be consulted for a FIXED contract.
        publish_index_entry(plant["id"], effective_date="2026-08-01",
                            price_cents_per_lb=40)
        order = create_order(contract["id"], plant["id"], quantity_lbs=100,
                             requested_ship_date="2026-08-20")
        priced = validate_success(
            api.price_order(order["id"], {"expected_grade": "STANDARD"}, SM), 200
        )
        assert priced["unit_price_cents"] == 50
        assert priced["applied_index_price_cents"] is None


class TestIndexPriceMultiInput:
    def _setup_index_contract_with_entries(self, api):
        plant = create_plant()
        contract = _index_linked_contract(plant["id"], basis=4)
        publish_index_entry(plant["id"], effective_date="2026-08-01",
                            price_cents_per_lb=40, source="JACOBSEN")
        publish_index_entry(plant["id"], effective_date="2026-08-10",
                            price_cents_per_lb=44, source="JACOBSEN")
        return plant, contract

    def test_index_price_selects_latest_entry_before_ship_date(self, api):
        """PRD §3.8: "on an `INDEX_LINKED` contract the server selects the plant's index
        entry whose `index_product` matches the contract's and whose `effective_date` is on
        or before the order's `requested_ship_date`, choosing the latest such date — ..."
        PRD §3.8: "The unit price applies a grade multiplier to the base — 1.05 for
        `PREMIUM`, 1.00 for `STANDARD`, 0.85 for `FEED_GRADE` — rounded half-up to whole
        cents in exactly one rounding step, producing `unit_price_cents`."

        Design: Difficulty/combinatorial_formula/index_price_multi_input_interaction
        """
        plant, contract = self._setup_index_contract_with_entries(api)
        order = create_order(contract["id"], plant["id"], quantity_lbs=48000,
                             requested_ship_date="2026-08-05")
        priced = validate_success(
            api.price_order(order["id"], {"expected_grade": "PREMIUM"}, SM), 200
        )
        # Ship date 2026-08-05 selects the 2026-08-01 entry (40), not the 2026-08-10 (44).
        assert priced["applied_index_price_cents"] == 40
        # base 40 + 4 = 44; unit = round_half_up(44 * 1.05) = round_half_up(46.2) = 46.
        assert priced["unit_price_cents"] == 46

    def test_index_price_composes_amounts_and_margin(self, api):
        """PRD §3.8: "`gross_amount_cents` is the order's `quantity_lbs` times the
        already-rounded `unit_price_cents` — an exact integer, never the rounding of a
        quantity-times-unrounded-price product."
        PRD §3.8: "That fraction becomes `applied_discount_pct`, and `discount_amount_cents`
        is the gross times that fraction, rounded half-up to whole cents. A flat freight
        surcharge of 12500 cents per order is then added as `freight_surcharge_cents`, and
        `net_amount_cents` is the gross minus the discount plus the freight. Finally
        `margin_pct` is one hundred times the amount by which `unit_price_cents` exceeds the
        plant's `standard_cost_cents_per_lb`, divided by `unit_price_cents`, rounded half-up
        to two decimal places."

        Design: Difficulty/combinatorial_formula/index_price_multi_input_interaction
        """
        plant, contract = self._setup_index_contract_with_entries(api)
        order = create_order(contract["id"], plant["id"], quantity_lbs=48000,
                             requested_ship_date="2026-08-05")
        priced = validate_success(
            api.price_order(order["id"], {"expected_grade": "PREMIUM"}, SM), 200
        )
        assert priced["status"] == "PRICED"
        # Projected volume 48000 < 50000: no tier qualifies.
        assert priced["applied_discount_pct"] == pytest.approx(0.0, abs=1e-9)
        assert priced["discount_amount_cents"] == 0
        assert priced["gross_amount_cents"] == 2208000  # 48000 * 46
        assert priced["freight_surcharge_cents"] == 12500
        assert priced["net_amount_cents"] == 2220500  # 2208000 - 0 + 12500
        # margin = round_half_up((46 - 38) / 46 * 100, 2) = 17.39 >= floor 15.0.
        assert priced["margin_pct"] == pytest.approx(17.39, abs=1e-9)


class TestPerUnitRoundingOrder:
    def _setup_single_entry_contract(self, api):
        plant = create_plant()
        contract = _index_linked_contract(plant["id"], basis=4)
        publish_index_entry(plant["id"], effective_date="2026-08-01",
                            price_cents_per_lb=40, source="USDA_AMS")
        return plant, contract

    def test_unit_price_rounded_before_extension(self, api):
        """PRD §3.8: "The unit price applies a grade multiplier to the base — 1.05 for
        `PREMIUM`, 1.00 for `STANDARD`, 0.85 for `FEED_GRADE` — rounded half-up to whole
        cents in exactly one rounding step, producing `unit_price_cents`."
        PRD §3.8: "`gross_amount_cents` is the order's `quantity_lbs` times the
        already-rounded `unit_price_cents` — an exact integer, never the rounding of a
        quantity-times-unrounded-price product."

        Design: Difficulty/combinatorial_formula/order_amount_per_unit_rounding
        """
        plant, contract = self._setup_single_entry_contract(api)
        order = create_order(contract["id"], plant["id"], quantity_lbs=333,
                             requested_ship_date="2026-08-05")
        priced = validate_success(
            api.price_order(order["id"], {"expected_grade": "PREMIUM"}, SM), 200
        )
        # Unit rounding happens first: round_half_up(44 * 1.05) = 46 (not 46.2 carried).
        assert priced["unit_price_cents"] == 46
        # Gross extends the ROUNDED unit: 333 * 46 = 15318 (round(333 * 46.2) = 15385
        # would indicate extension before rounding).
        assert priced["gross_amount_cents"] == 15318

    def test_order_amount_composition_sequence(self, api):
        """PRD §3.8: "That fraction becomes `applied_discount_pct`, and
        `discount_amount_cents` is the gross times that fraction, rounded half-up to whole
        cents. A flat freight surcharge of 12500 cents per order is then added as
        `freight_surcharge_cents`, and `net_amount_cents` is the gross minus the discount
        plus the freight."

        Design: Difficulty/combinatorial_formula/order_amount_per_unit_rounding
        """
        plant, contract = self._setup_single_entry_contract(api)
        order = create_order(contract["id"], plant["id"], quantity_lbs=333,
                             requested_ship_date="2026-08-05")
        priced = validate_success(
            api.price_order(order["id"], {"expected_grade": "PREMIUM"}, SM), 200
        )
        assert priced["discount_amount_cents"] == 0
        assert priced["freight_surcharge_cents"] == 12500
        assert priced["net_amount_cents"] == 27818  # 15318 - 0 + 12500
        assert priced["status"] == "PRICED"


class TestTierProjectionSelfInclusion:
    def _setup(self, api):
        plant = create_plant()
        contract = _index_linked_contract(plant["id"], basis=4,
                                          volume_commitment_lbs=300000)
        publish_index_entry(plant["id"], effective_date="2026-08-01",
                            price_cents_per_lb=44, source="INTERNAL")
        return plant, contract

    def test_tier_projection_below_threshold(self, api):
        """PRD §3.8: "The tier discount is selected on projected volume: the contract's
        `delivered_volume_lbs` plus this order's own `quantity_lbs`, so an order contributes
        to its own tier evaluation while orders not yet shipped do not; scanning
        `tier_discounts` in ascending order, the selected tier is the last one whose
        `threshold_lbs` the projected volume reaches or exceeds, and when no tier qualifies
        the discount fraction is zero."

        Design: Difficulty/combinatorial_formula/tier_projection_self_inclusion
        """
        plant, contract = self._setup(api)
        # delivered 0 + this order 99999: reaches 50000 but not 100000 -> 2% tier.
        order = create_order(contract["id"], plant["id"], quantity_lbs=99999,
                             requested_ship_date="2026-08-12")
        priced = validate_success(
            api.price_order(order["id"], {"expected_grade": "PREMIUM"}, SM), 200
        )
        assert priced["applied_discount_pct"] == pytest.approx(0.02, abs=1e-9)
        # base 44 + 4 = 48; unit = round_half_up(48 * 1.05) = round_half_up(50.4) = 50.
        assert priced["unit_price_cents"] == 50
        assert priced["gross_amount_cents"] == 4999950  # 99999 * 50
        # discount = round_half_up(4999950 * 0.02) = 99999.
        assert priced["discount_amount_cents"] == 99999
        assert priced["net_amount_cents"] == 4912451  # 4999950 - 99999 + 12500

    def test_tier_projection_at_threshold_inclusive(self, api):
        """PRD §3.8: "The tier discount is selected on projected volume: the contract's
        `delivered_volume_lbs` plus this order's own `quantity_lbs`, so an order contributes
        to its own tier evaluation while orders not yet shipped do not; scanning
        `tier_discounts` in ascending order, the selected tier is the last one whose
        `threshold_lbs` the projected volume reaches or exceeds, and when no tier qualifies
        the discount fraction is zero."

        Design: Difficulty/combinatorial_formula/tier_projection_self_inclusion
        """
        plant, contract = self._setup(api)
        # delivered 0 + this order 100000: reaches 100000 exactly (inclusive) -> 4% tier.
        order = create_order(contract["id"], plant["id"], quantity_lbs=100000,
                             requested_ship_date="2026-08-12")
        priced = validate_success(
            api.price_order(order["id"], {"expected_grade": "PREMIUM"}, SM), 200
        )
        assert priced["applied_discount_pct"] == pytest.approx(0.04, abs=1e-9)
        assert priced["gross_amount_cents"] == 5000000  # 100000 * 50
        assert priced["discount_amount_cents"] == 200000  # round_half_up(5000000 * 0.04)
        assert priced["net_amount_cents"] == 4812500  # 5000000 - 200000 + 12500


class TestOrderCreationWindow:
    def test_order_outside_contract_window_rejected(self, api):
        """PRD §3.8: "A `SalesManager` creates an order against a contract by supplying the
        `contract_id`, a `plant_id` equal to the contract's plant, a `quantity_lbs` of at
        least 1, a `requested_ship_date` that must lie within the contract's effective
        window (`ERR_CONTRACT_NOT_IN_EFFECT`), and the `expected_contract_version` guard of
        §2.8; the contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`)."

        Design: Corner/validations/order_outside_contract_window_rejected
        """
        plant = create_plant()
        contract = create_active_contract(plant["id"])  # window 2026-08-01..2026-12-31
        res = api.create_sales_order(
            {
                "contract_id": contract["id"],
                "plant_id": plant["id"],
                "quantity_lbs": 100,
                "requested_ship_date": "2027-01-15",
                "expected_contract_version": contract["version"],
            },
            SM,
        )
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_IN_EFFECT, expected_status=422)

        orders, meta = validate_paginated(
            api.list_sales_orders(ANY, params={"contract_id": contract["id"]})
        )
        assert orders == []
        assert meta["total_count"] == 0

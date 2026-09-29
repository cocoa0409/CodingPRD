"""Pricing a certified trade: the minimum floor and the community development premium."""

from test_helpers import (
    assert_money,
    assert_node_position,
    assert_volume,
    expected_mass_balance_premium_cents,
    expected_physical_premium_cents,
    factories as f,
    make_brand_licensee_headers,
    make_producer_representative_headers,
    validate_success,
)


def _dual_mode_world(api):
    """One producer owning a PHYSICAL and a MASS_BALANCE cooperative, each with a brand node."""
    producer = f.register_holder(
        api, legal_name="Kilimo Coop", holder_type="PRODUCER_ORG",
        country_code="KE", product_code="COFFEE_ARABICA",
    )
    brand = f.register_holder(
        api, legal_name="Nordic Roasters", holder_type="BRAND",
        country_code="SE", product_code="COFFEE_ARABICA",
    )
    producer_headers = make_producer_representative_headers(producer["id"])
    brand_headers = make_brand_licensee_headers(brand["id"])

    physical_seller = f.register_node(
        api, producer_headers, holder_id=producer["id"],
        node_role="COOPERATIVE", traceability_mode="PHYSICAL",
    )
    mass_balance_seller = f.register_node(
        api, producer_headers, holder_id=producer["id"],
        node_role="COOPERATIVE", traceability_mode="MASS_BALANCE",
    )
    physical_buyer = f.register_node(
        api, brand_headers, holder_id=brand["id"], node_role="BRAND_NODE",
        traceability_mode="PHYSICAL", upstream_node_id=physical_seller["id"],
    )
    mass_balance_buyer = f.register_node(
        api, brand_headers, holder_id=brand["id"], node_role="BRAND_NODE",
        traceability_mode="MASS_BALANCE", upstream_node_id=mass_balance_seller["id"],
    )
    f.certify(api, producer["id"])
    f.certify(api, brand["id"])
    for node in (physical_seller, mass_balance_seller):
        validate_success(
            api.declare_harvest(node["id"], f.harvest_payload(50000, "2026"), producer_headers), 201
        )
    return {
        "producer_id": producer["id"],
        "brand_id": brand["id"],
        "producer_headers": producer_headers,
        "physical_seller_id": physical_seller["id"],
        "mass_balance_seller_id": mass_balance_seller["id"],
        "physical_buyer_id": physical_buyer["id"],
        "mass_balance_buyer_id": mass_balance_buyer["id"],
    }


def _record_identical_shipment(api, world, seller_key, buyer_key):
    seller_id = world[seller_key]
    version = f.read_node(api, seller_id)["version"]
    return validate_success(
        api.create_trade(
            f.trade_payload(
                seller_id, world[buyer_key], version, 12000,
                declared_unit_price_cents_per_kg=300, product_code="COFFEE_ARABICA",
                quality_grade="SPECIALTY", contract_date="2026-08-01", is_organic=True,
            ),
            world["producer_headers"],
        ),
        201,
    )


class TestPremiumBasisDualVariant:
    """"Which of two accounting variants prices the premium is a structural decision, not a
    client choice. It is read off the seller node's traceability_mode at recording time.\""""

    def test_identical_shipments_diverge_by_thirty_three_thousand_cents(self, api, clock):
        """A 12000 kg organic SPECIALTY lot prices at 1200000 cents out of the PHYSICAL node
        and 1167000 cents out of the MASS_BALANCE node, a 33000 cent divergence.

        Design: Difficulty/dual_variant_calc/premium_basis_physical_versus_mass_balance_diverges_on_identical_shipment
        """
        world = _dual_mode_world(api)

        physical_trade = _record_identical_shipment(
            api, world, "physical_seller_id", "physical_buyer_id"
        )
        mass_balance_trade = _record_identical_shipment(
            api, world, "mass_balance_seller_id", "mass_balance_buyer_id"
        )

        assert physical_trade["premium_basis"] == "PHYSICAL_TRACEABILITY"
        assert_money(physical_trade["premium_cents"], 1200000, "premium_cents")
        assert mass_balance_trade["premium_basis"] == "MASS_BALANCE"
        assert_money(mass_balance_trade["premium_cents"], 1167000, "premium_cents")
        divergence = int(physical_trade["premium_cents"]) - int(mass_balance_trade["premium_cents"])
        assert divergence == 33000, f"expected a 33000 cent divergence, got {divergence}"
        assert_money(
            physical_trade["premium_cents"],
            expected_physical_premium_cents("COFFEE_ARABICA", 12000, True),
            "premium_cents",
        )
        assert_money(
            mass_balance_trade["premium_cents"],
            expected_mass_balance_premium_cents("COFFEE_ARABICA", 12000, True),
            "premium_cents",
        )

    def test_both_variants_share_the_floor_the_gross_value_and_the_premium_volume(self, api, clock):
        """The two variants differ only in premium_cents: the floor pricing, the contract total
        and the assessed premium volume are identical on both shipments.

        Design: Difficulty/dual_variant_calc/premium_basis_physical_versus_mass_balance_diverges_on_identical_shipment
        """
        world = _dual_mode_world(api)

        physical_trade = _record_identical_shipment(
            api, world, "physical_seller_id", "physical_buyer_id"
        )
        mass_balance_trade = _record_identical_shipment(
            api, world, "mass_balance_seller_id", "mass_balance_buyer_id"
        )

        for trade in (physical_trade, mass_balance_trade):
            assert_money(trade["applied_floor_cents_per_kg"], 440, "applied_floor_cents_per_kg")
            assert_money(trade["gross_value_cents"], 5280000, "gross_value_cents")
            assert_volume(trade["premium_volume_kg"], 12000, "premium_volume_kg")
        assert int(mass_balance_trade["premium_cents"]) < int(physical_trade["premium_cents"]), (
            "for identical inputs this variant always yields a strictly smaller premium"
        )


class TestFloorPriceComposition:
    """The floor combines the product base, the organic differential and the grade
    differential, and only then meets the declared price."""

    def test_declared_price_below_the_combined_floor_is_lifted_and_topped_up(self, api, clock):
        """8000 kg of organic SPECIALTY coffee declared at 300 settles at the 440 floor
        (320 + 80 + 40) with a 1120000 cent top-up and a 3520000 cent contract value.

        Design: Difficulty/combinatorial_formula/floor_price_combines_product_organic_and_grade_differentials_mode_a
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)

        lifted = f.record_trade(
            api, chain, 8000, declared_unit_price_cents_per_kg=300,
            product_code="COFFEE_ARABICA", quality_grade="SPECIALTY", is_organic=True,
        )

        assert_money(lifted["applied_floor_cents_per_kg"], 440, "applied_floor_cents_per_kg")
        assert_money(
            lifted["settled_unit_price_cents_per_kg"], 440, "settled_unit_price_cents_per_kg"
        )
        assert_money(lifted["floor_topup_cents"], 1120000, "floor_topup_cents")
        assert_money(lifted["gross_value_cents"], 3520000, "gross_value_cents")
        assert_money(lifted["premium_cents"], 800000, "premium_cents")

    def test_declared_price_above_the_plain_floor_is_kept_with_no_top_up(self, api, clock):
        """1000 kg of non-organic STANDARD coffee declared at 500 keeps 500 against the bare
        320 floor with no top-up, while the organic SPECIALTY lot on the same node floors at 440.

        Design: Difficulty/combinatorial_formula/floor_price_combines_product_organic_and_grade_differentials_mode_a
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)

        lifted = f.record_trade(
            api, chain, 8000, declared_unit_price_cents_per_kg=300,
            product_code="COFFEE_ARABICA", quality_grade="SPECIALTY", is_organic=True,
        )
        kept = f.record_trade(
            api, chain, 1000, declared_unit_price_cents_per_kg=500,
            product_code="COFFEE_ARABICA", quality_grade="STANDARD",
        )

        assert_money(kept["applied_floor_cents_per_kg"], 320, "applied_floor_cents_per_kg")
        assert_money(
            kept["settled_unit_price_cents_per_kg"], 500, "settled_unit_price_cents_per_kg"
        )
        assert_money(kept["floor_topup_cents"], 0, "floor_topup_cents")
        assert_money(kept["gross_value_cents"], 500000, "gross_value_cents")
        assert_money(kept["premium_cents"], 80000, "premium_cents")
        assert int(lifted["applied_floor_cents_per_kg"]) == 440, (
            "the same node prices two different floors from the grade and organic inputs"
        )


def _cocoa_mass_balance_chain(api):
    return f.build_certified_chain(
        api, product_code="COCOA", seller_mode="MASS_BALANCE", harvest_kg=5000,
        producer_name="Cocoa Union", brand_name="Alpine Chocolate",
        producer_country="GH", brand_country="CH",
    )


def _cocoa_mass_balance_trade(api, chain):
    return f.record_trade(
        api, chain, 3500, declared_unit_price_cents_per_kg=400,
        product_code="COCOA", quality_grade="STANDARD", is_organic=True,
    )


class TestMassBalancePremiumRoundingOrder:
    """A mass balance premium is rounded lot by lot and only then summed."""

    def test_per_lot_rounding_yields_two_cents_more_than_a_single_final_rounding(
        self, api, clock
    ):
        """3500 kg of organic cocoa accrues 255283 cents: three 1000 kg lots at 72938 plus a
        500 kg remainder at 36469, not the 255281 a single closing rounding would give.

        Design: Difficulty/combinatorial_formula/mass_balance_premium_rounds_per_lot_before_summing_mode_b
        """
        chain = _cocoa_mass_balance_chain(api)

        trade = _cocoa_mass_balance_trade(api, chain)

        assert trade["premium_basis"] == "MASS_BALANCE"
        assert_money(trade["premium_cents"], 255283, "premium_cents")
        assert int(trade["premium_cents"]) != 255281, (
            "rounding the exact product once would give 255281, which is not the pinned order"
        )
        assert_money(
            trade["premium_cents"],
            expected_mass_balance_premium_cents("COCOA", 3500, True),
            "premium_cents",
        )

    def test_the_rounding_order_leaves_floor_pricing_and_the_credit_position_intact(
        self, api, clock
    ):
        """The same shipment floors at 340, keeps its declared 400, grosses 1400000 and
        reserves 3500.000 kg, leaving 1500.000 kg of credit on the mass balance node.

        Design: Difficulty/combinatorial_formula/mass_balance_premium_rounds_per_lot_before_summing_mode_b
        """
        chain = _cocoa_mass_balance_chain(api)

        trade = _cocoa_mass_balance_trade(api, chain)

        assert_money(trade["applied_floor_cents_per_kg"], 340, "applied_floor_cents_per_kg")
        assert_money(
            trade["settled_unit_price_cents_per_kg"], 400, "settled_unit_price_cents_per_kg"
        )
        assert_money(trade["floor_topup_cents"], 0, "floor_topup_cents")
        assert_money(trade["gross_value_cents"], 1400000, "gross_value_cents")
        seller_node = f.read_node(api, chain["seller_node_id"])
        assert_node_position(
            seller_node, certified_input_kg=5000, reserved_output_kg=3500,
            claimed_output_kg=0, available_credit_kg=1500,
        )

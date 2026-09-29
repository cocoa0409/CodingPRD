"""Two endpoints where a hair's breadth changes the answer: the licence tier breakpoint and
the mass balance credit gate."""

from test_helpers import (
    api_errors as E,
    assert_money,
    assert_node_position,
    assert_volume,
    expected_license_fee,
    factories as f,
    make_brand_licensee_headers,
    validate_error,
    validate_success,
)


def _certified_brand(api, legal_name, country_code, product_code):
    """A CERTIFIED brand holding one chain-origin brand node and no licence yet."""
    holder = f.register_holder(
        api, legal_name=legal_name, holder_type="BRAND",
        country_code=country_code, product_code=product_code,
    )
    headers = make_brand_licensee_headers(holder["id"])
    f.register_node(
        api, headers, holder_id=holder["id"], node_role="BRAND_NODE",
        traceability_mode="PHYSICAL",
    )
    f.certify(api, holder["id"])
    return holder["id"]


class TestLicenseTierBreakpoint:
    """The first tier cap is inclusive, so the very next gram is priced in the second tier."""

    def test_the_gram_past_the_cap_moves_the_tier_and_costs_exactly_one_cent(self, api, clock):
        """A licence for exactly 100000 kg prices at 382950 in the first tier, while 100000.625 kg
        prices at 382951 in the second.

        Design: Difficulty/boundary_precision_check/license_fee_tier_boundary_at_100000_kg_flips_tier_and_fee_by_one_cent
        """
        at_the_cap = _certified_brand(api, "Nordic Roasters", "SE", "COFFEE_ARABICA")
        past_the_cap = _certified_brand(api, "Alpine Chocolate", "CH", "COCOA")

        first = f.issue_license(api, at_the_cap, 100000)
        second = f.issue_license(api, past_the_cap, 100000.625)

        assert first["license_tier"] == "TIER_1"
        assert_money(first["license_fee_cents"], 382950, "license_fee_cents")
        assert second["license_tier"] == "TIER_2"
        assert_money(second["license_fee_cents"], 382951, "license_fee_cents")
        delta = int(second["license_fee_cents"]) - int(first["license_fee_cents"])
        assert delta == 1, (
            f"the marginal 0.625 kg costs half a cent, which rounds half up to 1, not {delta}"
        )
        assert_money(
            first["license_fee_cents"],
            expected_license_fee(100000)["license_fee_cents"],
            "license_fee_cents",
        )
        assert_money(
            second["license_fee_cents"],
            expected_license_fee("100000.625")["license_fee_cents"],
            "license_fee_cents",
        )

    def test_one_kilogram_below_the_cap_is_one_cent_cheaper_in_the_same_tier(self, api, clock):
        """A licence for 99999 kg stays in the first tier at 382949, one cent under the figure at
        the cap itself.

        Design: Difficulty/boundary_precision_check/license_fee_tier_boundary_at_100000_kg_flips_tier_and_fee_by_one_cent
        """
        below_the_cap = _certified_brand(api, "Nordic Roasters", "SE", "COFFEE_ARABICA")

        priced = f.issue_license(api, below_the_cap, 99999)

        assert priced["license_tier"] == "TIER_1"
        assert_money(priced["license_fee_cents"], 382949, "license_fee_cents")

    def test_pricing_a_licence_leaves_it_active_and_wholly_unpaid(self, api, clock):
        """Both licences open ACTIVE with nothing paid against them and settlement still false.

        Design: Difficulty/boundary_precision_check/license_fee_tier_boundary_at_100000_kg_flips_tier_and_fee_by_one_cent
        """
        at_the_cap = _certified_brand(api, "Nordic Roasters", "SE", "COFFEE_ARABICA")
        past_the_cap = _certified_brand(api, "Alpine Chocolate", "CH", "COCOA")

        first = f.issue_license(api, at_the_cap, 100000)
        second = f.issue_license(api, past_the_cap, 100000.625)

        for holder in (first, second):
            assert holder["label_license_status"] == "ACTIVE"
            assert_money(holder["license_fee_paid_cents"], 0, "license_fee_paid_cents")
            assert holder["license_fee_settled"] is False


def _cocoa_credit_world(api):
    """A mass balance cocoa cooperative holding exactly 1000.000 kg of credit."""
    return f.build_certified_chain(
        api, product_code="COCOA", seller_mode="MASS_BALANCE", harvest_kg=1000,
        producer_name="Cocoa Union", brand_name="Alpine Chocolate",
        producer_country="GH", brand_country="CH",
    )


def _cocoa_trade_payload(chain, volume_kg, seller_node_version):
    return f.trade_payload(
        chain["seller_node_id"], chain["buyer_node_id"], seller_node_version, volume_kg,
        declared_unit_price_cents_per_kg=400, product_code="COCOA", quality_grade="STANDARD",
        contract_date="2026-08-01",
    )


class TestMassBalanceCreditGate:
    """Spending the whole credit is allowed; spending one gram more is not."""

    def test_a_shipment_equal_to_the_credit_is_accepted_and_empties_it(self, api, clock):
        """A 1000 kg shipment against exactly 1000.000 kg of credit is recorded, accrues 58350
        cents of premium and leaves the node with no credit at all.

        Design: Difficulty/boundary_precision_check/mass_balance_credit_gate_accepts_exact_equality_and_rejects_one_gram_more
        """
        chain = _cocoa_credit_world(api)

        trade = f.record_trade(
            api, chain, 1000, declared_unit_price_cents_per_kg=400,
            product_code="COCOA", quality_grade="STANDARD",
        )

        assert trade["premium_basis"] == "MASS_BALANCE"
        assert_money(trade["premium_cents"], 58350, "premium_cents")
        assert_volume(trade["premium_volume_kg"], 1000, "premium_volume_kg")
        assert_node_position(
            f.read_node(api, chain["seller_node_id"]),
            reserved_output_kg=1000, available_credit_kg=0,
        )

    def test_one_further_gram_over_an_empty_credit_is_refused_and_writes_nothing(
        self, api, clock
    ):
        """With the credit spent, a 0.001 kg shipment is refused for the credit and the node's
        reservation and version are left exactly where they were.

        Design: Difficulty/boundary_precision_check/mass_balance_credit_gate_accepts_exact_equality_and_rejects_one_gram_more
        """
        chain = _cocoa_credit_world(api)
        f.record_trade(
            api, chain, 1000, declared_unit_price_cents_per_kg=400,
            product_code="COCOA", quality_grade="STANDARD",
        )
        before = f.read_node(api, chain["seller_node_id"])

        response = api.create_trade(
            _cocoa_trade_payload(chain, 0.001, before["version"]), chain["producer_headers"]
        )

        validate_error(response, E.ERR_MASS_BALANCE_CREDIT_EXCEEDED, 422)
        after = f.read_node(api, chain["seller_node_id"])
        assert_volume(after["reserved_output_kg"], 1000, "reserved_output_kg")
        assert after["version"] == before["version"], (
            "a refused create leaves the seller node's version untouched"
        )

    def test_the_same_gram_is_accepted_once_a_gram_of_credit_exists(self, api, clock):
        """Declaring 0.001 kg more harvest makes the identical 0.001 kg shipment legal, so the
        refusal was about the credit balance and not about the size of the shipment.

        Design: Difficulty/boundary_precision_check/mass_balance_credit_gate_accepts_exact_equality_and_rejects_one_gram_more
        """
        chain = _cocoa_credit_world(api)
        f.record_trade(
            api, chain, 1000, declared_unit_price_cents_per_kg=400,
            product_code="COCOA", quality_grade="STANDARD",
        )
        validate_success(
            api.declare_harvest(
                chain["seller_node_id"], f.harvest_payload(0.001, "2026"),
                chain["producer_headers"],
            ),
            201,
        )
        version = f.read_node(api, chain["seller_node_id"])["version"]

        accepted = validate_success(
            api.create_trade(
                _cocoa_trade_payload(chain, 0.001, version), chain["producer_headers"]
            ),
            201,
        )

        assert_volume(accepted["volume_kg"], "0.001", "volume_kg")
        assert_node_position(
            f.read_node(api, chain["seller_node_id"]),
            reserved_output_kg="1000.001", available_credit_kg=0,
        )

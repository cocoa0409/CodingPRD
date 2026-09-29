"""Decisions that turn on the state of entities the request never names."""

from test_helpers import (
    OFFICER,
    api_errors as E,
    assert_clock_stamp,
    assert_money,
    assert_node_position,
    factories as f,
    make_brand_licensee_headers,
    validate_error,
    validate_success,
)


def _cocoa_mass_balance_brand(api):
    """A licensed cocoa brand whose only chain runs through a mass balance cooperative."""
    chain = f.build_certified_chain(
        api, product_code="COCOA", seller_mode="MASS_BALANCE", harvest_kg=None,
        producer_name="Cocoa Union", brand_name="Alpine Chocolate",
        producer_country="GH", brand_country="CH",
    )
    holder = f.issue_license(api, chain["brand_id"], 100000)
    chain["license_fee_cents"] = int(holder["license_fee_cents"])
    chain["mass_balance_request_id"] = f.file_mark_usage_request(
        api, chain["brand_id"], claim_type="FT_INGREDIENT_MASS_BALANCE",
        sku_code="ALP-DARK-70", artwork_ref="ART-2026-001", requested_volume_kg=20000,
    )["id"]
    chain["full_claim_request_id"] = f.file_mark_usage_request(
        api, chain["brand_id"], claim_type="FT_CERTIFIED_100",
        sku_code="ALP-PURE-100", artwork_ref="ART-2026-002", requested_volume_kg=5000,
    )["id"]
    return chain


def _approve(api, request_id):
    return api.decide_mark_usage_request(
        request_id, f.decision_payload("APPROVE", "Artwork conforms"), OFFICER
    )


def _settle_the_licence(api, chain):
    return validate_success(
        api.pay_license_fee(
            chain["brand_id"], f.payment_payload(chain["license_fee_cents"]),
            make_brand_licensee_headers(chain["brand_id"]),
        ),
        201,
    )


class TestMarkUsageDependsOnLicenceAndChain:
    """A mark usage decision reads the licence ledger and the upstream chain, not the request."""

    def test_an_unpaid_licence_blocks_the_decision_without_touching_the_request(self, api, clock):
        """While the 382950 cent fee is outstanding the decision is refused for the unpaid
        licence and the request stays SUBMITTED.

        Design: Difficulty/cross_entity_state_dependency/mark_usage_approval_depends_on_license_settlement_and_upstream_chain_mode
        """
        chain = _cocoa_mass_balance_brand(api)
        assert_money(chain["license_fee_cents"], 382950, "license_fee_cents")

        response = _approve(api, chain["mass_balance_request_id"])

        validate_error(response, E.ERR_LICENSE_FEE_UNPAID, 402)
        request = validate_success(
            api.get_mark_usage_request(chain["mass_balance_request_id"], OFFICER), 200
        )
        assert request["status"] == "SUBMITTED"

    def test_paying_the_fee_is_all_that_changes_before_the_same_decision_succeeds(
        self, api, clock
    ):
        """Once the fee is settled the identical decision approves the request, stamping the
        deciding officer and the clock instant.

        Design: Difficulty/cross_entity_state_dependency/mark_usage_approval_depends_on_license_settlement_and_upstream_chain_mode
        """
        chain = _cocoa_mass_balance_brand(api)
        _approve(api, chain["mass_balance_request_id"])

        paid = _settle_the_licence(api, chain)
        assert_money(paid["license_fee_paid_cents"], 382950, "license_fee_paid_cents")
        assert paid["license_fee_settled"] is True

        approved = validate_success(_approve(api, chain["mass_balance_request_id"]), 200)
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == OFFICER["X-User-ID"]
        assert_clock_stamp(approved["decided_at"], clock, "decided_at")

    def test_the_stronger_claim_stays_refused_because_of_the_chain_behind_it(self, api, clock):
        """With the fee settled the full certification claim is still refused, because the brand's
        chain contains a mass balance node.

        Design: Difficulty/cross_entity_state_dependency/mark_usage_approval_depends_on_license_settlement_and_upstream_chain_mode
        """
        chain = _cocoa_mass_balance_brand(api)
        _settle_the_licence(api, chain)
        validate_success(_approve(api, chain["mass_balance_request_id"]), 200)

        response = _approve(api, chain["full_claim_request_id"])

        validate_error(response, E.ERR_TRACEABILITY_MODE_MISMATCH, 422)
        request = validate_success(
            api.get_mark_usage_request(chain["full_claim_request_id"], OFFICER), 200
        )
        assert request["status"] == "SUBMITTED"
        summary = validate_success(
            api.get_traceability_summary(chain["brand_id"], OFFICER), 200
        )
        assert summary["chain_mode"] == "CONTAINS_MASS_BALANCE"
        assert summary["chain_node_count"] == 2
        assert summary["brand_node_count"] == 1
        assert summary["physical_node_count"] == 0
        assert summary["mass_balance_node_count"] == 2


def _suspended_seller_chain(api):
    """A mapped chain whose cooperative was suspended along with its holder."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    validate_success(
        api.suspend_holder(chain["producer_id"], f.reason_payload("MANUAL"), OFFICER), 200
    )
    chain["suspended_node_version"] = f.read_node(api, chain["seller_node_id"])["version"]
    return chain


def _eight_tonne_payload(chain, seller_node_version):
    return f.trade_payload(
        chain["seller_node_id"], chain["buyer_node_id"], seller_node_version, 8000,
        declared_unit_price_cents_per_kg=500, product_code="COFFEE_ARABICA",
        quality_grade="STANDARD", contract_date="2026-08-01",
    )


class TestTradeDependsOnSellerNodeStatus:
    """A trade names only nodes, but the seller node's availability is set by its holder."""

    def test_a_shipment_out_of_a_suspended_node_is_refused_and_reserves_nothing(
        self, api, clock
    ):
        """The suspended cooperative cannot sell: the create is refused as an inactive node and
        the node keeps a zero reservation at the version it already had.

        Design: Difficulty/cross_entity_state_dependency/trade_creation_rejected_when_seller_node_suspended_by_its_holder
        """
        chain = _suspended_seller_chain(api)

        response = api.create_trade(
            _eight_tonne_payload(chain, chain["suspended_node_version"]),
            chain["producer_headers"],
        )

        validate_error(response, E.ERR_NODE_NOT_ACTIVE, 409)
        node = f.read_node(api, chain["seller_node_id"])
        assert_node_position(node, reserved_output_kg=0)
        assert node["version"] == chain["suspended_node_version"], (
            "a refused create leaves the seller node exactly as it was"
        )

    def test_reinstating_the_holder_makes_the_identical_payload_succeed(self, api, clock):
        """Reinstatement returns the holder and its node to service, and the same 8000 kg payload
        is then recorded with a 640000 cent premium and its reservation held.

        Design: Difficulty/cross_entity_state_dependency/trade_creation_rejected_when_seller_node_suspended_by_its_holder
        """
        chain = _suspended_seller_chain(api)
        api.create_trade(
            _eight_tonne_payload(chain, chain["suspended_node_version"]),
            chain["producer_headers"],
        )

        holder = validate_success(api.reinstate_holder(chain["producer_id"], OFFICER), 200)
        assert holder["certificate_status"] == "CERTIFIED"
        assert holder["suspension_reason"] == "NONE"
        reinstated_node = f.read_node(api, chain["seller_node_id"])
        assert reinstated_node["status"] == "ACTIVE"
        assert reinstated_node["version"] > chain["suspended_node_version"]

        trade = validate_success(
            api.create_trade(
                _eight_tonne_payload(chain, reinstated_node["version"]),
                chain["producer_headers"],
            ),
            201,
        )

        assert_money(trade["premium_cents"], 640000, "premium_cents")
        assert_node_position(
            f.read_node(api, chain["seller_node_id"]), reserved_output_kg=8000
        )

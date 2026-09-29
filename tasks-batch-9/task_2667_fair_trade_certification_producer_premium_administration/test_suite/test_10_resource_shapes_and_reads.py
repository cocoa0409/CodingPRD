"""How each resource is born, what it stores, and what a read of it looks like."""

from test_helpers import (
    AUDITOR,
    OFFICER,
    OFFICER_7,
    OFFICER_7_ID,
    api_errors as E,
    assert_append_only_event,
    assert_clock_stamp,
    assert_common_fields,
    assert_created_at_ascending,
    assert_ledger_entry,
    assert_money,
    assert_new_holder_defaults,
    assert_node_position,
    assert_version_bumped_by,
    assert_zeroed_fund,
    factories as f,
    make_brand_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_NODE_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_HOLDER_ID = "00000000-0000-4000-8000-000000000002"


class TestCertificateHolderBirthAndReads:
    """Registration, the fund it mints, and the two read shapes."""

    def test_registering_a_producer_org_also_mints_its_zeroed_premium_fund(self, api, clock):
        """A new producer opens at PENDING with a perfect score and no licence, and its
        community development fund is created empty in the same request.

        Design: Corner/entities/producer_holder_creation_mints_pending_holder_and_zeroed_premium_fund
        """
        holder = validate_success(api.create_holder(f.holder_payload(), OFFICER), 201)

        assert_common_fields(holder, expected_version=1)
        assert holder["legal_name"] == "Kilimo Coop"
        assert holder["holder_type"] == "PRODUCER_ORG"
        assert_new_holder_defaults(holder)

        funds, meta = validate_paginated(api.list_holder_funds(holder["id"], OFFICER))
        assert meta["total_count"] == 1, "a producer organization gets exactly one fund"
        assert_zeroed_fund(funds[0], holder["id"], 2026)

    def test_reading_a_holder_returns_the_stored_row_inside_the_standard_envelope(
        self, api, clock
    ):
        """A brand reads its own registration back unchanged, and the envelope carries the
        request identifiers every response must expose.

        Design: Corner/entities/get_certificate_holder_returns_the_stored_row
        """
        brand = f.register_holder(
            api, legal_name="Nordic Roasters", holder_type="BRAND", country_code="SE"
        )

        response = api.get_holder(brand["id"], make_brand_licensee_headers(brand["id"]))

        holder = validate_success(response, 200)
        assert holder["id"] == brand["id"]
        assert holder["legal_name"] == "Nordic Roasters"
        assert holder["holder_type"] == "BRAND"
        assert holder["country_code"] == "SE"
        assert holder["product_code"] == "COFFEE_ARABICA"
        assert holder["certificate_status"] == "PENDING", "a read changes nothing"
        envelope = response.json()
        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"].startswith("req_")
        assert envelope["meta"]["api_request_timestamp"]

    def test_the_holder_list_filters_on_status_and_pages_through_the_matches(self, api, clock):
        """Filtering on CERTIFIED returns only the two certified cooperatives, oldest first,
        and a page of one reports that more remain.

        Design: Corner/entities/list_certificate_holders_filters_by_certificate_status_and_paginates
        """
        first = f.build_certified_producer(api, legal_name="Kilimo Coop")
        second = f.build_certified_producer(
            api, legal_name="Cocoa Union", country_code="GH", product_code="COCOA"
        )
        brand = f.register_holder(
            api, legal_name="Nordic Roasters", holder_type="BRAND", country_code="SE"
        )

        rows, meta = validate_paginated(
            api.list_holders(OFFICER, {"certificate_status": "CERTIFIED"})
        )

        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [first["holder_id"], second["holder_id"]]
        assert brand["id"] not in [row["id"] for row in rows]
        assert_created_at_ascending(rows)

        page, page_meta = validate_paginated(
            api.list_holders(OFFICER, {"certificate_status": "CERTIFIED", "limit": 1, "offset": 0})
        )
        assert [row["id"] for row in page] == [first["holder_id"]]
        assert page_meta["total_count"] == 2
        assert page_meta["has_more"] is True

    def test_registering_with_an_unknown_product_or_a_three_letter_country_is_refused(
        self, api, clock
    ):
        """TEA is not a certified product scope and a country code must be exactly two
        uppercase letters, and neither refusal leaves a holder behind.

        Design: Corner/entities/create_holder_with_unknown_product_code_returns_invalid_enum
        """
        unknown_product = api.create_holder(
            f.holder_payload("Assam Growers", country_code="IN", product_code="TEA"), OFFICER
        )
        validate_error(unknown_product, E.ERR_INVALID_REQUEST, 422)

        long_country = api.create_holder(
            f.holder_payload("Assam Growers", country_code="IND", product_code="COCOA"), OFFICER
        )
        validate_error(long_country, E.ERR_INVALID_REQUEST, 422)

        rows, meta = validate_paginated(api.list_holders(OFFICER))
        assert meta["total_count"] == 0 and rows == [], (
            "a refused registration mints neither a holder nor a fund"
        )


class TestSupplyChainNodeBirthAndReads:
    """Node registration resolves its holder first and reads back its own position."""

    def test_reading_a_node_id_that_belongs_to_nobody_is_a_node_not_found(self, api, clock):
        """The 404 names the node type and carries nothing but the error id and message.

        Design: Corner/entities/get_unknown_supply_chain_node_returns_not_found
        """
        holder = f.register_holder(api)

        response = api.get_node(UNKNOWN_NODE_ID, OFFICER)

        error = validate_error(response, E.ERR_NODE_NOT_FOUND, 404)
        assert set(error.keys()) == {"error_id", "message"}
        assert response.json()["response_type"] == "error"
        rows, meta = validate_paginated(api.list_nodes(OFFICER, {"holder_id": holder["id"]}))
        assert meta["total_count"] == 0 and rows == []

    def test_registering_a_node_under_an_unknown_holder_is_a_holder_not_found(self, api, clock):
        """The body's holder reference is resolved before anything else is written, and the
        same call against a real certified holder mints an active chain-origin node.

        Design: Corner/entities/create_supply_chain_node_for_unknown_holder_returns_not_found
        """
        producer = f.build_certified_producer(api)

        missing = api.create_node(f.node_payload(UNKNOWN_HOLDER_ID), OFFICER)
        validate_error(missing, E.ERR_HOLDER_NOT_FOUND, 404)

        created = validate_success(
            api.create_node(f.node_payload(producer["holder_id"]), OFFICER), 201
        )
        assert created["status"] == "ACTIVE", "a certified holder's new node may trade at once"
        assert created["chain_depth"] == 0
        rows, meta = validate_paginated(
            api.list_nodes(OFFICER, {"holder_id": producer["holder_id"]})
        )
        assert created["id"] in [row["id"] for row in rows]
        assert meta["total_count"] == len(rows)


class TestTradeTransactionInputHandling:
    """What the recording endpoint requires, defaults and computes for itself."""

    def test_a_trade_without_a_volume_is_refused_and_reserves_nothing(self, api, clock):
        """Volume is a required input, and the refusal leaves the seller node's position and
        its concurrency version exactly as they were.

        Design: Corner/entities/create_trade_transaction_missing_volume_kg_returns_invalid_request
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)
        version = chain["seller_node_version"]
        payload = f.trade_payload(
            chain["seller_node_id"], chain["buyer_node_id"], version, volume_kg=10000
        )
        payload.pop("volume_kg")

        response = api.create_trade(payload, chain["producer_headers"])

        validate_error(response, E.ERR_INVALID_REQUEST, 422)
        seller = f.read_node(api, chain["seller_node_id"])
        assert_node_position(
            seller, reserved_output_kg="0.000", available_credit_kg="50000.000"
        )
        assert seller["version"] == version, "a refused create does not bump the parent version"
        rows, meta = validate_paginated(
            api.list_trades(OFFICER, {"seller_node_id": chain["seller_node_id"]})
        )
        assert meta["total_count"] == 0 and rows == []

    def test_omitted_quorum_and_organic_flag_fall_back_to_their_declared_defaults(
        self, api, clock
    ):
        """A committee constituted without a quorum takes 60.00 percent, and a shipment
        recorded without an organic flag is priced as conventional coffee.

        Design: Corner/entities/committee_quorum_and_trade_organic_flag_defaults_applied_when_omitted
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)

        committee = f.constitute_committee(api, chain["producer_id"])
        trade = f.record_trade(api, chain, 10000)

        assert float(committee["quorum_pct"]) == 60.00
        assert committee["status"] == "FORMING"
        assert committee["open_proposal_count"] == 0
        assert trade["is_organic"] is False
        assert_money(trade["premium_cents"], 800000, "premium_cents")
        assert_money(
            trade["applied_floor_cents_per_kg"], 320, "applied_floor_cents_per_kg"
        )
        for node_id in (chain["seller_node_id"], chain["buyer_node_id"]):
            node = f.read_node(api, node_id)
            assert float(node["conversion_ratio"]) == 1.0

    def test_the_settled_price_comes_from_the_floor_schedule_not_from_the_declared_price(
        self, api, clock
    ):
        """A cocoa contract declared at 200 cents is lifted to the 260 cent floor, and the
        declared figure survives alongside the computed one.

        Design: Corner/entities/trade_money_fields_are_computed_from_the_floor_schedule_not_from_input
        """
        chain = f.build_certified_chain(
            api, product_code="COCOA", harvest_kg=50000,
            producer_name="Cocoa Union", producer_country="GH",
            brand_name="Alpine Chocolate", brand_country="CH",
        )

        trade = f.record_trade(
            api, chain, 5000, declared_unit_price_cents_per_kg=200, product_code="COCOA"
        )

        assert_money(trade["applied_floor_cents_per_kg"], 260, "applied_floor_cents_per_kg")
        assert_money(
            trade["settled_unit_price_cents_per_kg"], 260, "settled_unit_price_cents_per_kg"
        )
        assert_money(trade["floor_topup_cents"], 300000, "floor_topup_cents")
        assert_money(trade["gross_value_cents"], 1300000, "gross_value_cents")
        assert_money(trade["premium_cents"], 300000, "premium_cents")
        assert trade["premium_basis"] == "PHYSICAL_TRACEABILITY"
        assert_money(
            trade["declared_unit_price_cents_per_kg"], 200, "declared_unit_price_cents_per_kg"
        )


class TestServerStampedAndAppendOnlyRecords:
    """Decision provenance and the ledger row are written by the server alone."""

    def test_the_decision_fields_of_a_mark_usage_request_come_from_the_deciding_officer(
        self, api, clock
    ):
        """A filed request carries no decision at all; the officer who decides it is recorded
        from the acting identity and the decision is stamped with the logical clock.

        Design: Corner/entities/mark_usage_request_system_fields_are_server_stamped_only
        """
        chain = f.build_certified_chain(
            api, product_code="COCOA", seller_mode="MASS_BALANCE", harvest_kg=None,
            producer_name="Cocoa Union", producer_country="GH",
            brand_name="Alpine Chocolate", brand_country="CH",
        )
        f.build_settled_license(api, chain["brand_id"], 100000)
        request = f.file_mark_usage_request(
            api, chain["brand_id"], claim_type="FT_INGREDIENT_MASS_BALANCE",
            sku_code="ALP-DARK-70", artwork_ref="ART-2026-001", requested_volume_kg=20000,
        )

        assert request["status"] == "SUBMITTED"
        assert request["decided_by_user_id"] is None
        assert request["decided_at"] is None
        assert request["decision_reason"] is None

        decided = validate_success(
            api.decide_mark_usage_request(
                request["id"], f.decision_payload("APPROVE", "Artwork conforms"), OFFICER_7
            ),
            200,
        )

        assert decided["decided_by_user_id"] == OFFICER_7_ID
        assert_clock_stamp(decided["decided_at"], clock, "decided_at")
        assert decided["decision_reason"] == "Artwork conforms"
        assert decided["status"] == "APPROVED"
        assert_common_fields(decided)
        assert_version_bumped_by(request, decided, 1)

    def test_a_ledger_entry_is_an_event_with_no_version_and_no_updated_at(self, api, clock):
        """The accrual written by settlement carries only an identity and a creation stamp,
        alongside the trade that produced it.

        Design: Corner/entities/premium_ledger_entry_is_immutable_with_no_version_field
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)
        trade = f.record_settled_trade(api, chain, 10000)

        rows, meta = validate_paginated(
            api.list_ledger_entries(OFFICER, {"trade_transaction_id": trade["id"]})
        )

        assert meta["total_count"] == 1
        entry = validate_success(api.get_ledger_entry(rows[0]["id"], AUDITOR), 200)
        assert_ledger_entry(
            entry, "ACCRUAL", 800000, balance_after_cents=800000,
            trade_transaction_id=trade["id"],
        )
        assert_append_only_event(entry)
        assert entry["trade_transaction_id"] == trade["id"]
        assert entry["proposal_id"] is None

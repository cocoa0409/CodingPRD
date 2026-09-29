"""Entity shapes: declared initial values, defaults, derived figures and identity."""

from __future__ import annotations

from test_helpers import (
    ADMIN_PAT,
    ADMIN_ZOE,
    COMPLIANCE_CARL,
    NON_EXISTENT_UUID,
    OPS_ALICE,
    OPS_DANA,
    REVIEWER_BOB,
    USER_IDS,
    ApiErrorId,
    approx_money,
    factories as f,
    fixtures as fx,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ZERO_MONEY_FIELDS = (
    "ordered_goods_value_usd",
    "shipped_goods_value_usd",
    "provisional_seller_cost_usd",
    "provisional_buyer_cost_usd",
    "final_seller_cost_usd",
    "final_buyer_cost_usd",
    "cost_allocation_variance_usd",
    "outstanding_receivable_usd",
    "licensed_value_allocated_usd",
    "insured_exposure_usd",
    "short_shipped_value_usd",
)


class TestExportOrderCreation:
    def test_new_order_starts_on_both_axes_with_every_money_figure_at_zero(self, api):
        """PRD §3.2: "A new order is born with `fulfillment_status` `DRAFT` and
        `settlement_status` `UNSECURED`, and with every derived money figure at
        0.00: `ordered_goods_value_usd`, `shipped_goods_value_usd`,
        `provisional_seller_cost_usd`, `provisional_buyer_cost_usd`,
        `final_seller_cost_usd`, `final_buyer_cost_usd`,
        `cost_allocation_variance_usd`, `outstanding_receivable_usd`,
        `licensed_value_allocated_usd`, `insured_exposure_usd` and
        `short_shipped_value_usd`."

        Design: Corner/entities/corner_export_order_created_in_draft_unsecured_with_system_fields
        """
        buyer = fx.create_buyer(api)
        response = api.create_order(f.order_payload(buyer["id"]), OPS_ALICE)
        order = validate_success(response, 201)

        assert is_valid_uuid(order["id"])
        assert order["fulfillment_status"] == "DRAFT"
        assert order["settlement_status"] == "UNSECURED"
        for field in ZERO_MONEY_FIELDS:
            assert order[field] == approx_money(0.00), field

        reread = fx.data(api.get_buyer(buyer["id"], COMPLIANCE_CARL))
        assert reread["open_order_count"] == 1
        assert reread["aggregate_exposure_usd"] == approx_money(0.00)


class TestLetterOfCreditDefaults:
    def test_omitted_optional_terms_fall_back_and_collapse_the_drawing_bounds(self, api):
        """PRD §3.4: "Five further fields are optional and carry defaults:
        `tolerance_pct` defaults to 0.00 and must lie between 0.00 and 10.00
        inclusive at 2 decimal places; `usance_days` defaults to 0;
        `presentation_period_days` defaults to 21 and must lie between 1 and 60
        inclusive; `partial_shipment_allowed` defaults to false; and
        `transshipment_allowed` defaults to false."

        Design: Corner/entities/corner_letter_of_credit_optional_inputs_fall_back_to_declared_defaults
        """
        ctx = fx.order_with_lines(api)
        response = api.capture_credit(
            {
                "export_order_id": ctx["order_id"],
                "lc_number": "LC-2026-0001",
                "issuing_bank_swift": "HVBKKRSE",
                "amount_usd": 25000.00,
                "availability": "SIGHT",
                "expiry_date": "2026-11-30T00:00:00Z",
                "latest_shipment_date": "2026-09-15T00:00:00Z",
                "required_document_types": ["COMMERCIAL_INVOICE"],
            },
            OPS_ALICE,
        )
        credit = validate_success(response, 201)

        assert credit["tolerance_pct"] == approx_money(0.00)
        assert credit["usance_days"] == 0
        assert credit["presentation_period_days"] == 21
        assert credit["partial_shipment_allowed"] is False
        assert credit["transshipment_allowed"] is False
        assert credit["max_drawable_usd"] == approx_money(25000.00)
        assert credit["min_drawable_usd"] == approx_money(25000.00)
        assert credit["status"] == "RECEIVED"
        assert credit["amendment_round"] == 0
        assert credit["drawn_amount_usd"] == approx_money(0.00)


class TestForeignBuyerDefaults:
    def test_buyer_onboarded_without_compliance_fields_lands_on_none_and_false(self, api):
        """PRD §3.1: "Two further compliance fields may be supplied at
        registration and both carry defaults: `sanctions_tier`, one of `NONE`,
        `WATCHLIST` or `EMBARGOED`, defaults to `NONE`; and
        `restricted_party_flag`, a boolean, defaults to false."

        Design: Corner/entities/corner_foreign_buyer_sanctions_defaults_none_and_flag_false
        """
        response = api.create_buyer(
            {
                "legal_name": "Hanwha Trading Co",
                "country_code": "KR",
                "credit_rating": "BBB",
            },
            ADMIN_ZOE,
        )
        buyer = validate_success(response, 201)

        assert buyer["sanctions_tier"] == "NONE"
        assert buyer["restricted_party_flag"] is False
        assert buyer["restricted_party_reason"] is None
        assert buyer["aggregate_exposure_usd"] == approx_money(0.00)
        assert buyer["open_order_count"] == 0


class TestExportOrderReads:
    def test_get_order_echoes_the_incoterm_profile_and_exposes_its_version(self, api):
        """PRD §3.2: "The order's `ordered_goods_value_usd` is the sum of
        `line_extended_usd` over all its lines, and its `shipped_goods_value_usd`
        is the sum, over all lines, of each line's `shipped_quantity` multiplied
        by its `unit_price_usd` and rounded to two decimal places per line before
        summing."

        Design: Corner/entities/corner_get_export_order_returns_every_stored_and_computed_field
        """
        ctx = fx.order_with_lines(api)
        order = validate_success(api.get_order(ctx["order_id"], REVIEWER_BOB), 200)

        assert order["id"] == ctx["order_id"]
        assert order["incoterm"] == "FOB"
        assert order["incoterm_named_place"] == "FOB Busan"
        assert order["destination_zone"] == "ZONE_2"
        assert order["ordered_goods_value_usd"] == approx_money(25000.00)
        assert isinstance(order["version"], int)
        assert order["version"] >= 1

    def test_order_listing_paginates_and_counts_only_matching_rows(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope, where
        `total_count` is the number of rows matching the filters before pagination
        is applied and `has_more` indicates whether rows remain beyond the current
        window."

        Design: Corner/entities/corner_list_export_orders_pagination_and_status_filter
        """
        buyer = fx.create_buyer(api)
        fx.create_order(api, buyer["id"])
        fx.create_order(api, buyer["id"], OPS_ALICE, incoterm="CIF", incoterm_named_place="CIF Busan")

        response = api.list_orders(
            ADMIN_ZOE,
            {
                "buyer_id": buyer["id"],
                "fulfillment_status": "DRAFT",
                "limit": 1,
                "offset": 0,
            },
        )
        rows, meta = validate_paginated(response)

        assert len(rows) == 1
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

    def test_unknown_order_id_resolves_to_the_path_existence_error(self, api):
        """PRD §2.11: "Every path parameter resolves to an existing row, validated
        left to right, on every endpoint that has path parameters — otherwise the
        matching 404 from the family listed in §2.4."

        Design: Corner/entities/corner_get_unknown_export_order_id_not_found
        """
        response = api.get_order(NON_EXISTENT_UUID, OPS_ALICE)
        validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)


class TestShipmentLineBodyValidation:
    def test_line_without_a_quantity_is_refused_and_writes_no_partial_row(self, api):
        """PRD §2.11: "Body field types, enum membership, decimal scale and
        numeric ranges match the field constraints described in §3, on every
        endpoint — otherwise `ERR_VALIDATION` (422)."

        Design: Corner/entities/corner_shipment_line_missing_required_quantity_rejected
        """
        buyer = fx.create_buyer(api)
        order = fx.create_order(api, buyer["id"])
        response = api.add_shipment_line(
            order["id"],
            {
                "line_no": 1,
                "goods_description": "Industrial valve assembly",
                "hs_code": "848180",
                "uom": "EA",
                "unit_price_usd": 250.0000,
                "net_weight_kg": 1000.000,
                "gross_weight_kg": 1200.000,
                "package_count": 20,
            },
            OPS_ALICE,
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)

        _, meta = validate_paginated(
            api.list_order_shipment_lines(order["id"], OPS_ALICE, {"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0
        assert fx.read_order(api, order["id"])["ordered_goods_value_usd"] == approx_money(0.00)


class TestPerLineRoundingBeforeSummation:
    def test_two_lines_are_each_rounded_before_the_order_total_is_summed(self, api):
        """PRD §3.2: "`line_extended_usd` is the quantity multiplied by the unit
        price, rounded to two decimal places — and this per-line rounding is
        pinned to happen **before** any summation, which is why summing raw
        products and rounding once produces the wrong invoice."

        Design: Corner/entities/corner_ordered_goods_value_recomputed_per_line_rounding_first
        """
        buyer = fx.create_buyer(api)
        order = fx.create_order(api, buyer["id"])
        line_one = fx.add_line(
            api,
            order["id"],
            OPS_ALICE,
            line_no=1,
            goods_description="Valve seat ring",
            quantity=12.345,
            uom="KG",
            unit_price_usd=10.1111,
            net_weight_kg=12.000,
            gross_weight_kg=13.000,
            package_count=1,
        )
        response = api.add_shipment_line(
            order["id"],
            f.shipment_line_payload(
                line_no=2,
                goods_description="Gasket set",
                hs_code="848490",
                quantity=7.777,
                uom="SET",
                unit_price_usd=3.3333,
                net_weight_kg=4.000,
                gross_weight_kg=5.000,
                package_count=1,
            ),
            OPS_ALICE,
        )
        line_two = validate_success(response, 201)

        assert line_two["line_extended_usd"] == approx_money(25.93)
        assert line_two["line_net_usd"] == approx_money(25.93)

        reread = fx.data(api.get_shipment_line(line_one["id"], OPS_ALICE))
        assert reread["line_extended_usd"] == approx_money(124.82)

        order_after = fx.read_order(api, order["id"])
        assert order_after["ordered_goods_value_usd"] == approx_money(150.75)


class TestServerOwnedSystemFields:
    def test_document_stamps_its_own_generator_revision_and_pinned_order_version(
        self, api
    ):
        """PRD §3.5: "The document is created in `status` `DRAFT` with `revision`
        1, `supersedes_document_id` null, `void_reason` null,
        `generated_by_user_id` taken from `X-User-ID`, and `pinned_order_version`
        set to the order's current `version`."

        Design: Corner/entities/corner_system_fields_owned_by_server_on_order_and_document_create
        """
        ctx = fx.order_with_lines(api)
        order_version = fx.order_version(api, ctx["order_id"])

        response = api.generate_document(
            f.document_payload(ctx["order_id"], "COMMERCIAL_INVOICE"), OPS_DANA
        )
        document = validate_success(response, 201)

        assert document["generated_by_user_id"] == USER_IDS["ops_dana"]
        assert document["revision"] == 1
        assert document["status"] == "DRAFT"
        assert document["pinned_order_version"] == order_version
        assert document["origin_country_code"] == "US"
        assert document["supersedes_document_id"] is None

        order = fx.read_order(api, ctx["order_id"])
        assert order["prepared_by_user_id"] == USER_IDS["ops_alice"]


class TestIncotermEnumMembership:
    def test_incoterm_outside_the_declared_enum_is_refused_with_no_side_effect(self, api):
        """PRD §3.2: "The commercial terms are the `incoterm`, one of `EXW`,
        `FCA`, `FOB`, `CFR`, `CIF`, `DAP` or `DDP`, together with a free-text
        `incoterm_named_place` qualifying it, such as the port named in "FOB
        Busan"."

        Design: Corner/entities/corner_invalid_incoterm_enum_value_rejected_with_validation
        """
        buyer = fx.create_buyer(api)
        response = api.create_order(
            f.order_payload(buyer["id"], incoterm="FOBX"), OPS_ALICE
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 422)

        _, meta = validate_paginated(
            api.list_orders(ADMIN_ZOE, {"buyer_id": buyer["id"], "limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0
        assert fx.data(api.get_buyer(buyer["id"], COMPLIANCE_CARL))["open_order_count"] == 0


class TestPresentationDocumentLinkJunction:
    def test_link_carries_only_id_and_created_at_and_is_read_only(self, api):
        """PRD §2.4: "Because a link is written once and thereafter only
        re-statused by the system, it carries only `id` and `created_at`: it has
        **no** `updated_at` field and **no** `version` field, and neither may be
        synthesised for it."

        Design: Corner/entities/corner_presentation_document_link_is_immutable_read_only_junction
        """
        ctx = fx.full_tender(api)
        ctx = fx.lodged_presentation(api, ctx)

        listed, _ = validate_paginated(
            api.list_presentation_links(
                ADMIN_PAT, {"link_status": "ACTIVE", "limit": 10, "offset": 0}
            )
        )
        assert listed
        link = validate_success(
            api.get_presentation_link(listed[0]["id"], REVIEWER_BOB), 200
        )

        assert link["link_status"] == "ACTIVE"
        assert link["pinned_document_revision"] == 1
        assert link["linked_in_round"] == 1
        assert "version" not in link
        assert "updated_at" not in link
        assert is_valid_uuid(link["id"])
        assert isinstance(link["created_at"], str)


class TestIdentityResolutionOrder:
    def test_line_against_an_unresolvable_parent_order_reports_the_order_404(self, api):
        """PRD §2.4: "A shipment line is read by its own id and reports
        `ERR_ORDER_NOT_FOUND` for an unresolvable order, and a presentation
        document link is read by `link_id`."

        Design: Corner/entities/corner_shipment_line_requires_existing_parent_order
        """
        response = api.add_shipment_line(
            NON_EXISTENT_UUID, f.shipment_line_payload(), OPS_ALICE
        )
        validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)

    def test_unresolvable_body_foreign_key_reports_the_buyer_404(self, api):
        """PRD §2.11: "Every foreign-key id in the request body resolves to an
        existing row, validated in the order the endpoint declares its input
        fields, on every endpoint that carries foreign keys in its body —
        otherwise the matching 404 from the same family."

        Design: Corner/entities/corner_buyer_body_fk_unresolvable_returns_buyer_not_found
        """
        response = api.create_order(f.order_payload(NON_EXISTENT_UUID), OPS_ALICE)
        validate_error(response, ApiErrorId.ERR_BUYER_NOT_FOUND.value, 404)


class TestOpenOrderCountIsDerived:
    def test_cancelling_the_only_order_takes_the_count_back_to_zero(self, api):
        """PRD §3.1: "`open_order_count` starts at 0 and always equals the count
        of that buyer's orders whose `fulfillment_status` is neither `CLOSED` nor
        `CANCELLED`; it rises by one when an order is created and falls by one
        every time an order closes or is cancelled."

        Design: Corner/entities/corner_open_order_count_falls_back_when_order_cancelled
        """
        buyer = fx.create_buyer(api)
        order = fx.create_order(api, buyer["id"])
        assert fx.data(api.get_buyer(buyer["id"], OPS_ALICE))["open_order_count"] == 1

        cancelled = validate_success(
            api.cancel_order(
                order["id"], {"reason": "Buyer withdrew the enquiry"}, OPS_ALICE
            ),
            200,
        )
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["settlement_status"] == "UNSECURED"
        assert fx.data(api.get_buyer(buyer["id"], OPS_ALICE))["open_order_count"] == 0


class TestReplacementAndRevisionChains:
    def test_replacement_credit_chain_is_walkable_by_the_supersedes_filter(self, api):
        """PRD §3.4: "A `supersedes_lc_id` may be supplied to point at an earlier
        credit whose `status` is `REJECTED` or `EXPIRED`, forming a replacement
        chain; it is null for an original credit."

        Design: Corner/entities/corner_graph_topology_supersedes_lc_chain_is_walkable_by_filter
        """
        ctx = fx.order_with_lines(api)
        ctx = fx.captured_credit(api, ctx, lc_number="LC-2026-0001")
        ctx = fx.opened_terms_review(api, ctx)
        fx.data(
            api.raise_terms_finding(
                ctx["review_id"],
                f.terms_finding_payload(
                    code="AMOUNT_MISMATCH", severity="CRITICAL", clause_ref="AMOUNT"
                ),
                REVIEWER_BOB,
            )
        )
        fx.data(
            api.submit_terms_review(
                ctx["review_id"], {"recommendation": "REJECT"}, REVIEWER_BOB
            )
        )

        response = api.capture_credit(
            f.credit_payload(
                ctx["order_id"],
                lc_number="LC-2026-0002",
                supersedes_lc_id=ctx["lc_id"],
            ),
            OPS_ALICE,
        )
        replacement = validate_success(response, 201)

        assert replacement["supersedes_lc_id"] == ctx["lc_id"]
        assert replacement["status"] == "RECEIVED"
        assert replacement["amendment_round"] == 0

        chain, meta = validate_paginated(
            api.list_credits(
                OPS_ALICE, {"supersedes_lc_id": ctx["lc_id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1
        assert chain[0]["id"] == replacement["id"]
        assert fx.read_credit(api, ctx["lc_id"])["status"] == "REJECTED"

    def test_regeneration_mints_the_next_revision_and_supersedes_its_predecessor(
        self, api
    ):
        """PRD §3.5: "The predecessor moves to `SUPERSEDED` and a new row of the
        same `doc_type` is created with `revision` incremented by one, `status`
        `DRAFT`, `supersedes_document_id` pointing at the predecessor, and
        `pinned_order_version` set to the order's **current** `version`; the new
        revision's money and weight figures are recomputed through the full chain
        above."

        Design: Corner/entities/corner_graph_topology_document_revision_chain_via_supersedes_document_id
        """
        ctx = fx.order_with_lines(api)
        first = fx.data(
            api.generate_document(
                f.document_payload(ctx["order_id"], "COMMERCIAL_INVOICE"), OPS_ALICE
            )
        )
        response = api.regenerate_document(
            first["id"], {"reason": "Goods description corrected"}, OPS_ALICE
        )
        second = validate_success(response, 201)

        assert second["revision"] == 2
        assert second["status"] == "DRAFT"
        assert second["supersedes_document_id"] == first["id"]
        assert second["declared_total_usd"] == approx_money(25000.00)

        predecessor = fx.data(api.get_document(first["id"], OPS_ALICE))
        assert predecessor["status"] == "SUPERSEDED"
        assert predecessor["revision"] == 1

        chain, meta = validate_paginated(
            api.list_documents(
                OPS_ALICE,
                {"supersedes_document_id": first["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert chain[0]["id"] == second["id"]

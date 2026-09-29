"""
Entity surface: creation, retrieval, listing, defaults, computed fields,
server-stamped system fields, type constraints, immutability and parent links.
"""

from test_helpers import (
    MISSING_UUID_FF,
    ApiErrorId,
    assert_cash_buyer,
    assert_disclosure_acknowledgement,
    assert_earnest_money_deposit,
    assert_escrow_conserved,
    assert_fields,
    assert_identity,
    assert_pagination_meta,
    assert_seller_lead,
    assert_wholesaler,
    build_draft_contract,
    build_signed_contract,
    factories,
    make_compliance_officer_headers,
    make_seller_headers,
    make_wholesaler_headers,
    record_lead,
    register_wholesaler,
    screen_lead,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    PLATFORM_ADMIN,
    TITLE_AGENT_1,
)


class TestWholesalerRegistration:
    """POST /wholesalers and the shape of a freshly registered desk."""

    def test_creation_persists_every_declared_field(self, api):
        """
        "A platform administrator brings a wholesaling entity onto the desk by
        registering it with its `legal_name`, the two-uppercase-letter
        `state_code` of its home state, and the `disclosure_template_version`
        tag identifying the intent-to-assign disclosure packet it serves to
        sellers."

        "A freshly registered wholesaler starts clean: `adverse_finding_count`
        at 0, `compliance_hold` false, and `executed_assignment_count` at 0."

        Design: Corner/entities/wholesaler_creation_persists_declared_fields_and_returns_201
        """
        set_clock(api, "2026-08-01T00:00:00Z")

        response = api.create_wholesaler(
            factories.wholesaler_payload(
                legal_name="Brazos Bend Acquisitions LLC",
                state_code="TX",
                disclosure_template_version="DISC-2026.1",
                licensure_status="LICENSED_BROKER",
                funding_window_capacity=2,
            ),
            PLATFORM_ADMIN,
        )
        wholesaler = validate_success(response, 201)

        assert_wholesaler(
            wholesaler,
            legal_name="Brazos Bend Acquisitions LLC",
            state_code="TX",
            disclosure_template_version="DISC-2026.1",
            licensure_status="LICENSED_BROKER",
            funding_window_capacity=2,
            adverse_finding_count=0,
            compliance_hold=False,
            executed_assignment_count=0,
            version=1,
            created_at="2026-08-01T00:00:00Z",
            updated_at="2026-08-01T00:00:00Z",
        )
        assert_identity(wholesaler, "wholesaler")

    def test_optional_inputs_fall_back_to_declared_defaults(self, api):
        """
        "`licensure_status` declares the entity's real-estate licensure posture
        and must be one of `UNLICENSED`, `LICENSED_AGENT` or
        `LICENSED_BROKER`, defaulting to `UNLICENSED` — the posture that
        triggers the strictest disclosure and brokerage-boundary rules.
        `funding_window_capacity` declares how many buffered double-close
        funding windows the entity's transactional-lender line can support at
        once; it must be at least 1 and defaults to 1."

        Design: Corner/entities/wholesaler_defaults_applied_when_optional_inputs_omitted
        """
        set_clock(api, "2026-08-01T00:00:00Z")

        response = api.create_wholesaler(
            factories.wholesaler_payload(
                legal_name="Keystone Property Partners LLC",
                state_code="TX",
                disclosure_template_version="DISC-2026.1",
            ),
            PLATFORM_ADMIN,
        )
        wholesaler = validate_success(response, 201)

        assert_wholesaler(
            wholesaler,
            licensure_status="UNLICENSED",
            funding_window_capacity=1,
            adverse_finding_count=0,
            compliance_hold=False,
            executed_assignment_count=0,
        )


class TestSellerLeadRepresentation:
    """The stored representation of a lead before and after the screen."""

    def test_retrieval_returns_the_stored_row_with_pre_screen_defaults(self, api):
        """
        "A new lead enters status `PROSPECT` with every equity field null —
        `screening_variant`, `net_equity_cents`, `equity_pct`,
        `protection_tier` and `screened_at` all begin unset."

        "`junior_lien_cents` and `delinquent_property_tax_cents` each default
        to 0 and each must be at least 0, capturing unrecorded junior debt and
        delinquent property tax respectively."

        Design: Corner/entities/seller_lead_retrieval_returns_stored_representation
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        wholesaler = register_wholesaler(api)
        lead = record_lead(
            api,
            wholesaler["id"],
            junior_lien_cents=1500000,
            delinquent_property_tax_cents=400000,
            distress_flags=["FORECLOSURE_NOTICE", "PROBATE"],
        )

        response = api.get_seller_lead(lead["id"], make_compliance_officer_headers())
        fetched = validate_success(response, 200)

        assert_seller_lead(
            fetched,
            id=lead["id"],
            wholesaler_id=wholesaler["id"],
            owner_name=factories.LEAD_OWNER_NAME,
            property_address=factories.LEAD_PROPERTY_ADDRESS,
            state_code="TX",
            estimated_market_value_cents=30000000,
            recorded_senior_lien_cents=10000000,
            junior_lien_cents=1500000,
            delinquent_property_tax_cents=400000,
            distress_flags=["FORECLOSURE_NOTICE", "PROBATE"],
            marketing_campaign_id=None,
            status="PROSPECT",
            lead_gen_blocked=False,
            screening_variant=None,
            protection_tier=None,
            net_equity_cents=None,
            equity_pct=None,
            screened_at=None,
            version=1,
        )

    def test_listing_filters_by_status_and_honours_the_offset_window(self, api):
        """
        "Leads may be read individually by `seller_lead_id` and listed with
        filters on `wholesaler_id`, `marketing_campaign_id`, `status` and
        `protection_tier`."

        "The `meta` block of every list response carries `limit`, `offset`,
        `total_count` (the count of records matching the filters before the
        window is applied) and `has_more` (true when records remain beyond the
        current window)."

        Design: Corner/entities/seller_lead_listing_filters_by_status_with_pagination
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        wholesaler = register_wholesaler(api)
        w_id = wholesaler["id"]

        first = record_lead(api, w_id)
        screen_lead(api, first["id"], w_id, "STATUTORY")
        second = record_lead(
            api,
            w_id,
            owner_name=factories.SECOND_LEAD_OWNER_NAME,
            property_address=factories.SECOND_LEAD_PROPERTY_ADDRESS,
            estimated_market_value_cents=28000000,
            recorded_senior_lien_cents=9000000,
        )
        screen_lead(api, second["id"], w_id, "STATUTORY")
        third = record_lead(
            api,
            w_id,
            owner_name=factories.THIRD_LEAD_OWNER_NAME,
            property_address=factories.THIRD_LEAD_PROPERTY_ADDRESS,
            estimated_market_value_cents=26000000,
            recorded_senior_lien_cents=8000000,
        )

        response = api.list_seller_leads(
            make_wholesaler_headers(w_id),
            {"wholesaler_id": w_id, "status": "SCREENED", "limit": 1, "offset": 1},
        )
        leads, meta = validate_paginated(response)

        assert_pagination_meta(meta, limit=1, offset=1, total_count=2, has_more=False)
        assert len(leads) == 1, f"expected exactly one row in the window, got {leads}"
        assert leads[0]["id"] in (first["id"], second["id"])
        assert leads[0]["id"] != third["id"]
        assert leads[0]["status"] == "SCREENED"


class TestUnknownIdentifiersAndMalformedBodies:
    """Rank 3 body validation and rank 5 path resolution."""

    def test_purchase_contract_get_with_unknown_id_is_not_found(self, api):
        """
        "Path identifiers are resolved strictly left to right." "Each aggregate
        has its own not-found code — ... `ERR_PURCHASE_CONTRACT_NOT_FOUND` ...
        each carrying HTTP 404."

        Design: Corner/entities/purchase_contract_get_with_unknown_id_returns_not_found
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        wholesaler = register_wholesaler(api)

        response = api.get_purchase_contract(
            MISSING_UUID_FF, make_wholesaler_headers(wholesaler["id"])
        )
        error = validate_error(response, ApiErrorId.PURCHASE_CONTRACT_NOT_FOUND, 404)
        assert isinstance(error.get("message"), str) and error["message"], (
            "the error envelope must carry a non-empty message"
        )

        listed, meta = validate_paginated(
            api.list_purchase_contracts(make_wholesaler_headers(wholesaler["id"]))
        )
        assert_pagination_meta(meta, total_count=0)
        assert listed == []

    def test_seller_lead_create_without_property_address_is_invalid_request(self, api):
        """
        "**`ERR_INVALID_REQUEST`** (400) — malformed body: a value of the wrong
        type, a missing required field, an enum value outside its declared set,
        an integer outside its declared range, a datetime that is not ISO 8601
        UTC".

        Design: Corner/entities/seller_lead_create_missing_required_property_address_returns_invalid_request
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        wholesaler = register_wholesaler(api)
        w_id = wholesaler["id"]

        response = api.create_seller_lead(
            {
                "wholesaler_id": w_id,
                "owner_name": factories.LEAD_OWNER_NAME,
                "state_code": "TX",
                "estimated_market_value_cents": 30000000,
                "recorded_senior_lien_cents": 10000000,
            },
            make_wholesaler_headers(w_id),
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

        _, meta = validate_paginated(
            api.list_seller_leads(make_wholesaler_headers(w_id), {"wholesaler_id": w_id})
        )
        assert_pagination_meta(meta, total_count=0)

        unchanged = validate_success(api.get_wholesaler(w_id, PLATFORM_ADMIN), 200)
        assert_fields(unchanged, "wholesaler", version=1)

    def test_campaign_channel_outside_the_declared_set_is_rejected(self, api):
        """
        "A wholesaler drafts one by naming its own `wholesaler_id`, the
        outbound `channel` — one of `DIRECT_MAIL`, `SMS`, `COLD_CALL`,
        `BANDIT_SIGN` or `ONLINE_AD`".

        "**`ERR_INVALID_REQUEST`** (400) — malformed body: ... an enum value
        outside its declared set".

        Design: Corner/entities/marketing_campaign_create_with_invalid_enum_channel_rejected
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        wholesaler = register_wholesaler(api)
        w_id = wholesaler["id"]

        response = api.create_marketing_campaign(
            factories.marketing_campaign_payload(
                w_id,
                channel="POSTCARD",
                discloses_intent_to_assign=True,
                discloses_unlicensed_status=True,
            ),
            make_wholesaler_headers(w_id),
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

        _, meta = validate_paginated(
            api.list_marketing_campaigns(
                make_wholesaler_headers(w_id), {"wholesaler_id": w_id}
            )
        )
        assert_pagination_meta(meta, total_count=0)


class TestServerComputedAndServerStampedFields:
    """Fields the server derives or stamps, never accepts from the body."""

    def test_new_cash_buyer_starts_with_zero_capacity_and_suspended_tier(self, api):
        """
        "A new buyer starts with `verified_funds_cents` at 0,
        `committed_deposit_cents` at 0, `available_funds_cents` at 0,
        `active_offer_count` at 0 and `buyer_tier` at `SUSPENDED` — no verified
        liquidity means no bidding capacity."

        Design: Corner/entities/cash_buyer_computed_capital_fields_initialised_by_system
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        wholesaler = register_wholesaler(api)
        w_id = wholesaler["id"]

        response = api.create_cash_buyer(
            factories.cash_buyer_payload(w_id), make_wholesaler_headers(w_id)
        )
        buyer = validate_success(response, 201)

        assert_cash_buyer(
            buyer,
            wholesaler_id=w_id,
            legal_name=factories.CASH_BUYER_LEGAL_NAME,
            contact_email=factories.CASH_BUYER_CONTACT_EMAIL,
            verified_funds_cents=0,
            committed_deposit_cents=0,
            available_funds_cents=0,
            active_offer_count=0,
            buyer_tier="SUSPENDED",
            version=1,
        )

    def test_acknowledgement_identity_and_instants_come_from_the_server(self, api):
        """
        "The acknowledgement names the `purchase_contract_id` it attaches to,
        the `disclosure_template_version` the seller is acknowledging, the two
        booleans `acknowledged_intent_to_assign` and
        `acknowledged_unlicensed_status`, and a `signature_ref` — an opaque
        reference to the stored signature artefact, non-empty and at most 120
        characters. ... the record's `acknowledged_at` is stamped from the
        logical clock."

        "Every record's `id` is a server-minted UUID with no type prefix;
        clients never supply it."

        Design: Corner/entities/disclosure_acknowledgement_system_fields_are_server_generated
        """
        scenario = build_draft_contract(api, clock="2026-08-05T00:00:00Z")

        response = api.create_disclosure_acknowledgement(
            factories.disclosure_acknowledgement_payload(scenario.pc_id),
            make_seller_headers(scenario.lead_id),
        )
        acknowledgement = validate_success(response, 201)

        assert_disclosure_acknowledgement(
            acknowledgement,
            purchase_contract_id=scenario.pc_id,
            disclosure_template_version=factories.DEFAULT_DISCLOSURE_TEMPLATE_VERSION,
            acknowledged_intent_to_assign=True,
            acknowledged_unlicensed_status=True,
            signature_ref="esig-dana-001",
            acknowledged_at="2026-08-05T00:00:00Z",
            created_at="2026-08-05T00:00:00Z",
        )


class TestDisclosureAcknowledgementImmutability:
    """The one entity declared without updated_at or version."""

    def test_representation_omits_version_and_survives_the_signing_cascade(self, api):
        """
        "There is exactly one exception. `DisclosureAcknowledgement` is an
        immutable legal artefact: it carries only `id` and `created_at`, and
        both `updated_at` and `version` are absent from it entirely. There is
        no endpoint that updates or deletes an acknowledgement — a seller who
        wishes to acknowledge a revised disclosure packet records a second
        acknowledgement."

        Design: Corner/entities/disclosure_acknowledgement_is_immutable_with_no_version_field
        """
        scenario = build_draft_contract(api, clock="2026-08-05T00:00:00Z")
        created = validate_success(
            api.create_disclosure_acknowledgement(
                factories.disclosure_acknowledgement_payload(scenario.pc_id),
                make_seller_headers(scenario.lead_id),
            ),
            201,
        )

        before = validate_success(
            api.get_disclosure_acknowledgement(
                created["id"], make_compliance_officer_headers()
            ),
            200,
        )
        assert_disclosure_acknowledgement(before, id=created["id"])

        validate_success(
            api.sign_purchase_contract(
                scenario.pc_id, make_seller_headers(scenario.lead_id)
            ),
            200,
        )

        after = validate_success(
            api.get_disclosure_acknowledgement(
                created["id"], make_compliance_officer_headers()
            ),
            200,
        )
        assert after == before, (
            "no declared endpoint mutates an acknowledgement, so the signing "
            f"cascade must leave it untouched: {before} became {after}"
        )


class TestEarnestMoneyDepositParentLink:
    """A child record discovered only through its parent's identifier."""

    def test_deposit_is_found_by_filtering_on_its_purchase_contract(self, api):
        """
        "Because the topology is flat, child records are discovered through
        their parent's identifier on a filtered list rather than through nested
        URLs. The earnest money deposit created by the signing cascade, for
        instance, is never returned by the signing call itself; it is found by
        listing deposits filtered on `purchase_contract_id`."

        "... it creates the contract's earnest money deposit, whose
        `purchase_contract_id` points back at the contract, whose
        `amount_cents` is copied from the contract's `earnest_money_cents` and
        never afterwards mutated, whose `status` is `HELD`, whose `held_cents`
        equals `amount_cents` with the other three buckets at zero, and whose
        `disposition_event_count` is 0."

        Design: Corner/entities/earnest_money_deposit_parent_link_resolves_to_purchase_contract
        """
        scenario = build_signed_contract(
            api,
            clock="2026-08-05T00:00:00Z",
            contract_kwargs={"earnest_money_cents": 500000},
        )

        response = api.list_earnest_money_deposits(
            TITLE_AGENT_1, {"purchase_contract_id": scenario.pc_id}
        )
        deposits, meta = validate_paginated(response)

        assert_pagination_meta(meta, total_count=1, has_more=False)
        assert len(deposits) == 1
        assert_earnest_money_deposit(
            deposits[0],
            purchase_contract_id=scenario.pc_id,
            amount_cents=500000,
            held_cents=500000,
            status="HELD",
            refunded_to_wholesaler_cents=0,
            forfeited_to_seller_cents=0,
            applied_at_closing_cents=0,
            disposition_event_count=0,
        )
        assert_escrow_conserved(deposits[0])

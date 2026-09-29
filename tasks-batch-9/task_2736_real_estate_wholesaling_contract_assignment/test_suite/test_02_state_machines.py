"""
Lifecycle transitions: legal edges and their side effects, precondition
enforcement, initial states, replayed triggers and terminal-state lockdown.
"""

from test_helpers import (
    ApiErrorId,
    assert_deal_analysis,
    assert_earnest_money_deposit,
    assert_escrow_conserved,
    assert_marketing_campaign,
    assert_nulls,
    assert_pagination_meta,
    assert_purchase_contract,
    assert_seller_lead,
    build_desk,
    build_draft_contract,
    build_screened_lead,
    draft_campaign,
    factories,
    make_seller_headers,
    make_wholesaler_headers,
    read_campaign,
    read_lead,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TITLE_AGENT_1,
)


class TestCampaignPublication:
    """The DRAFT to PUBLISHED edge and the gates in front of it."""

    def test_publish_moves_draft_to_published_and_stamps_published_at(self, api):
        """
        "Driving a campaign from `DRAFT` to `PUBLISHED` requires four conditions
        beyond ownership: the owning wholesaler's `compliance_hold` must be
        false, `discloses_intent_to_assign` must be true, an `UNLICENSED`
        wholesaler must additionally have `discloses_unlicensed_status` true,
        and a campaign on the `SMS` or `COLD_CALL` channel must additionally
        have `dnc_scrubbed` true. ... On success the campaign's `published_at`
        is stamped with the current logical instant."

        Design: Corner/state_machines/campaign_publish_transitions_draft_to_published_and_stamps_published_at
        """
        scenario = build_desk(api, clock="2026-08-02T00:00:00Z")
        campaign = draft_campaign(
            api,
            scenario.w_id,
            discloses_intent_to_assign=True,
            discloses_unlicensed_status=True,
        )
        assert_marketing_campaign(campaign, status="DRAFT", published_at=None, version=1)

        response = api.publish_marketing_campaign(
            campaign["id"], make_wholesaler_headers(scenario.w_id)
        )
        published = validate_success(response, 200)

        assert_marketing_campaign(
            published,
            status="PUBLISHED",
            published_at="2026-08-02T00:00:00Z",
            suspension_count=0,
            version=2,
        )

    def test_publish_without_the_intent_to_assign_disclosure_is_refused(self, api):
        """
        "Three boolean flags describe the creative's compliance content and all
        three default to false: `discloses_intent_to_assign` states that the
        advertiser intends to assign the resulting purchase contract rather than
        close on it".

        "Those four are reported, in that order, as
        `ERR_WHOLESALER_COMPLIANCE_HOLD`,
        `ERR_INTENT_TO_ASSIGN_NOT_DISCLOSED`,
        `ERR_LICENSURE_DISCLOSURE_MISSING` and `ERR_DNC_SCRUB_REQUIRED`."

        Design: Corner/state_machines/campaign_publish_without_intent_to_assign_disclosure_is_rejected
        """
        scenario = build_desk(api, clock="2026-08-02T00:00:00Z")
        campaign = draft_campaign(
            api, scenario.w_id, discloses_unlicensed_status=True
        )
        assert_marketing_campaign(campaign, discloses_intent_to_assign=False)

        response = api.publish_marketing_campaign(
            campaign["id"], make_wholesaler_headers(scenario.w_id)
        )
        validate_error(response, ApiErrorId.INTENT_TO_ASSIGN_NOT_DISCLOSED, 422)

        unchanged = read_campaign(api, campaign["id"], scenario.w_id)
        assert_marketing_campaign(
            unchanged, status="DRAFT", published_at=None, version=1
        )

    def test_replaying_publish_neither_advances_nor_restamps(self, api):
        """
        "A campaign already in `PUBLISHED` cannot be published again; that
        attempt is the residual state guard and returns `ERR_INVALID_STATE`."

        Design: Corner/state_machines/campaign_publish_twice_returns_invalid_state_on_second_attempt
        """
        scenario = build_desk(api, clock="2026-08-02T00:00:00Z")
        campaign = draft_campaign(
            api,
            scenario.w_id,
            discloses_intent_to_assign=True,
            discloses_unlicensed_status=True,
        )
        first = validate_success(
            api.publish_marketing_campaign(
                campaign["id"], make_wholesaler_headers(scenario.w_id)
            ),
            200,
        )
        set_clock(api, "2026-08-03T00:00:00Z")

        response = api.publish_marketing_campaign(
            campaign["id"], make_wholesaler_headers(scenario.w_id)
        )
        validate_error(response, ApiErrorId.INVALID_STATE, 409)

        after = read_campaign(api, campaign["id"], scenario.w_id)
        assert_marketing_campaign(
            after,
            status="PUBLISHED",
            published_at="2026-08-02T00:00:00Z",
            version=first["version"],
        )


class TestCampaignArchival:
    """ARCHIVED is terminal, and the archive trigger is not a no-op."""

    def test_archiving_an_archived_campaign_is_an_invalid_state(self, api):
        """
        "Archival is the terminal exit and is reachable from all three live
        statuses — `DRAFT → ARCHIVED`, `PUBLISHED → ARCHIVED` and `SUSPENDED →
        ARCHIVED` — with the single precondition that the campaign is not
        already `ARCHIVED`, and with no side effects at all."

        Design: Corner/state_machines/campaign_archive_twice_from_archived_returns_invalid_state
        """
        scenario = build_desk(api, clock="2026-08-02T00:00:00Z")
        campaign = draft_campaign(
            api,
            scenario.w_id,
            discloses_intent_to_assign=True,
            discloses_unlicensed_status=True,
        )
        archived = validate_success(
            api.archive_marketing_campaign(
                campaign["id"], make_wholesaler_headers(scenario.w_id)
            ),
            200,
        )
        assert_marketing_campaign(archived, status="ARCHIVED")

        response = api.archive_marketing_campaign(
            campaign["id"], make_wholesaler_headers(scenario.w_id)
        )
        validate_error(response, ApiErrorId.INVALID_STATE, 409)

        after = read_campaign(api, campaign["id"], scenario.w_id)
        assert_marketing_campaign(
            after, status="ARCHIVED", version=archived["version"]
        )

    def test_publishing_out_of_the_terminal_archived_state_is_refused(self, api):
        """
        "Archival is the terminal exit and is reachable from all three live
        statuses — `DRAFT → ARCHIVED`, `PUBLISHED → ARCHIVED` and `SUSPENDED →
        ARCHIVED`".

        "**`ERR_INVALID_STATE`** (409) — the residual state-machine guard: the
        target entity is in no state from which the requested trigger has an
        outgoing transition".

        Design: Corner/state_machines/campaign_publish_from_archived_terminal_state_returns_invalid_state
        """
        scenario = build_desk(api, clock="2026-08-02T00:00:00Z")
        campaign = draft_campaign(
            api,
            scenario.w_id,
            discloses_intent_to_assign=True,
            discloses_unlicensed_status=True,
        )
        validate_success(
            api.archive_marketing_campaign(
                campaign["id"], make_wholesaler_headers(scenario.w_id)
            ),
            200,
        )

        response = api.publish_marketing_campaign(
            campaign["id"], make_wholesaler_headers(scenario.w_id)
        )
        validate_error(response, ApiErrorId.INVALID_STATE, 409)

        after = read_campaign(api, campaign["id"], scenario.w_id)
        assert_marketing_campaign(after, status="ARCHIVED", published_at=None)


class TestDealAnalysisInitialState:
    """A newly created analysis holds one computed field and nothing else."""

    def test_new_analysis_is_draft_with_only_the_comp_count_computed(self, api):
        """
        "A new analysis enters status `DRAFT` with `valuation_variant`,
        `arv_cents`, `repair_estimate_cents`, `max_allowable_offer_cents` and
        `finalized_at` all null. One thing is computed at creation time:
        `qualifying_comp_count`."

        "`qualifying_comp_count` is the number of comparables passing all
        three, and it is recomputed whenever the analysis is created."

        Design: Corner/state_machines/deal_analysis_initial_state_is_draft_with_null_valuation_outputs
        """
        scenario = build_screened_lead(api, clock="2026-08-05T00:00:00Z")

        response = api.create_deal_analysis(
            factories.deal_analysis_payload(
                scenario.lead_id, scenario.lead["version"]
            ),
            make_wholesaler_headers(scenario.w_id),
        )
        analysis = validate_success(response, 201)

        assert_deal_analysis(
            analysis,
            seller_lead_id=scenario.lead_id,
            status="DRAFT",
            qualifying_comp_count=3,
            version=1,
        )
        assert_nulls(
            analysis,
            "valuation_variant",
            "arv_cents",
            "repair_estimate_cents",
            "max_allowable_offer_cents",
            "finalized_at",
            label="deal_analysis",
        )


class TestContractSigningSideEffects:
    """Every declared effect of DRAFT to SIGNED, observed in one request."""

    def test_signing_stamps_the_deadline_and_funds_escrow(self, api):
        """
        "Signing does three things beyond the status change. It stamps
        `signed_at` with the current logical instant. It derives
        `inspection_deadline_at` as `signed_at` plus `inspection_period_days`
        twenty-four-hour days ... And it creates the contract's earnest money
        deposit, whose `purchase_contract_id` points back at the contract, whose
        `amount_cents` is copied from the contract's `earnest_money_cents` and
        never afterwards mutated, whose `status` is `HELD`, whose `held_cents`
        equals `amount_cents` with the other three buckets at zero, and whose
        `disposition_event_count` is 0."

        Design: Corner/state_machines/contract_sign_side_effect_creates_held_earnest_money_deposit
        """
        scenario = build_draft_contract(
            api,
            clock="2026-08-05T00:00:00Z",
            contract_kwargs={
                "purchase_price_cents": 18000000,
                "earnest_money_cents": 500000,
                "inspection_period_days": 7,
            },
        )
        validate_success(
            api.create_disclosure_acknowledgement(
                factories.disclosure_acknowledgement_payload(scenario.pc_id),
                make_seller_headers(scenario.lead_id),
            ),
            201,
        )

        response = api.sign_purchase_contract(
            scenario.pc_id, make_seller_headers(scenario.lead_id)
        )
        signed = validate_success(response, 200)

        assert_purchase_contract(
            signed,
            contract_status="SIGNED",
            signed_at="2026-08-05T00:00:00Z",
            inspection_deadline_at="2026-08-12T00:00:00Z",
            assignment_status="NOT_MARKETED",
            structure_election="UNDECIDED",
        )

        deposits, meta = validate_paginated(
            api.list_earnest_money_deposits(
                TITLE_AGENT_1, {"purchase_contract_id": scenario.pc_id}
            )
        )
        assert_pagination_meta(meta, total_count=1)
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

        assert_seller_lead(
            read_lead(api, scenario.lead_id, scenario.w_id), status="UNDER_CONTRACT"
        )

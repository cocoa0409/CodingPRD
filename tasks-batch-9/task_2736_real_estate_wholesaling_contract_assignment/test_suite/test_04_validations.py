"""
Business-rule validation: the seller-protection equity floor, its inclusive
boundary, its precedence over the underwriting ceiling, and the conditional
do-not-call scrub demanded of two outbound channels only.
"""

from test_helpers import (
    ApiErrorId,
    assert_marketing_campaign,
    assert_pagination_meta,
    assert_purchase_contract,
    assert_seller_lead,
    build_desk,
    build_underwritten_lead,
    comparable,
    draft_campaign,
    factories,
    make_wholesaler_headers,
    read_campaign,
    read_lead,
    repair_item,
    validate_error,
    validate_paginated,
    validate_success,
)

PROTECTED_LEAD_KWARGS = {
    "estimated_market_value_cents": 30000000,
    "recorded_senior_lien_cents": 500000,
    "distress_flags": ["FORECLOSURE_NOTICE", "PROBATE"],
}


class TestEquityFloor:
    """The statutory equity floor beneath a protected seller's price."""

    def test_price_one_cent_below_the_floor_is_equity_skimming(self, api):
        """
        "**The equity floor.** Where the lead's `protection_tier` is `ELEVATED`
        or `PROTECTED`, the seller must be left with at least sixty percent of
        their statutory equity above the recorded senior lien. Concretely:
        subtract `recorded_senior_lien_cents` from
        `estimated_market_value_cents`, multiply that statutory equity by 0.60,
        take the floor, and add `recorded_senior_lien_cents` back; a
        `purchase_price_cents` strictly below that figure is rejected with
        `ERR_EQUITY_SKIMMING_PROHIBITED`."

        Design: Corner/validations/equity_skimming_price_floor_violation_is_rejected
        """
        scenario = build_underwritten_lead(
            api, clock="2026-08-06T00:00:00Z", lead_kwargs=dict(PROTECTED_LEAD_KWARGS)
        )
        assert_seller_lead(scenario.lead, protection_tier="PROTECTED")

        response = api.create_purchase_contract(
            factories.purchase_contract_payload(
                scenario.lead_id,
                scenario.analysis_id,
                purchase_price_cents=18199999,
                earnest_money_cents=500000,
                option_start_at="2026-08-06T00:00:00Z",
            ),
            make_wholesaler_headers(scenario.w_id),
        )
        validate_error(response, ApiErrorId.EQUITY_SKIMMING_PROHIBITED, 422)

        _, meta = validate_paginated(
            api.list_purchase_contracts(
                make_wholesaler_headers(scenario.w_id),
                {"seller_lead_id": scenario.lead_id},
            )
        )
        assert_pagination_meta(meta, total_count=0)
        assert_seller_lead(
            read_lead(api, scenario.lead_id, scenario.w_id), status="SCREENED"
        )

    def test_price_landing_exactly_on_the_floor_is_contracted(self, api):
        """
        "... a `purchase_price_cents` strictly below that figure is rejected
        with `ERR_EQUITY_SKIMMING_PROHIBITED`."

        "The assignment cutoff, `assignment_deadline_at`, is the earliest
        permitted close minus forty-eight hours."

        Design: Corner/validations/purchase_price_exactly_at_equity_floor_is_accepted
        """
        scenario = build_underwritten_lead(
            api, clock="2026-08-06T00:00:00Z", lead_kwargs=dict(PROTECTED_LEAD_KWARGS)
        )

        response = api.create_purchase_contract(
            factories.purchase_contract_payload(
                scenario.lead_id,
                scenario.analysis_id,
                purchase_price_cents=18200000,
                earnest_money_cents=500000,
                option_start_at="2026-08-06T00:00:00Z",
                closing_window_start_at="2026-09-15T00:00:00Z",
                closing_window_end_at="2026-09-30T00:00:00Z",
            ),
            make_wholesaler_headers(scenario.w_id),
        )
        contract = validate_success(response, 201)

        assert_purchase_contract(
            contract,
            purchase_price_cents=18200000,
            contract_status="DRAFT",
            assignment_status="NOT_MARKETED",
            structure_election="UNDECIDED",
            assignment_deadline_at="2026-09-13T00:00:00Z",
        )
        assert_seller_lead(
            read_lead(api, scenario.lead_id, scenario.w_id), status="UNDER_CONTRACT"
        )

    def test_equity_skimming_is_reported_ahead_of_the_price_ceiling(self, api):
        """
        "**`ERR_EQUITY_SKIMMING_PROHIBITED`** (422) — contracting an `ELEVATED`
        or `PROTECTED` lead below the statutory equity floor. Conditional:
        `STANDARD`-tier leads are exempt. This safety rule deliberately
        outranks the fiscal offer ceiling at rank 40."

        "Rules are evaluated in strictly ascending rank; the first violation
        found is the one reported, and evaluation stops there."

        Design: Corner/validations/equity_skimming_outranks_mao_exceeded_on_contract_create
        """
        scenario = build_underwritten_lead(
            api,
            clock="2026-08-06T00:00:00Z",
            lead_kwargs=dict(PROTECTED_LEAD_KWARGS),
            analysis_kwargs={
                "comparables": [
                    comparable(10000000, 0.10, 10, 1800, 0),
                    comparable(10000000, 0.20, 10, 1800, 0),
                    comparable(10000000, 0.30, 10, 1800, 0),
                ],
                "repair_scope_items": [repair_item("ROOF", 1500000, 1800000)],
            },
        )
        # floor(10000000 * 0.75) - 1500000 - 1000000 == 5000000, so a price of
        # 6000000 also busts the underwriting ceiling.
        assert scenario.analysis["max_allowable_offer_cents"] == 5000000

        response = api.create_purchase_contract(
            factories.purchase_contract_payload(
                scenario.lead_id,
                scenario.analysis_id,
                purchase_price_cents=6000000,
                earnest_money_cents=200000,
                option_start_at="2026-08-06T00:00:00Z",
            ),
            make_wholesaler_headers(scenario.w_id),
        )
        error = validate_error(response, ApiErrorId.EQUITY_SKIMMING_PROHIBITED, 422)
        assert error["error_id"] != ApiErrorId.MAO_EXCEEDED
        assert isinstance(error["error_id"], str), (
            "exactly one error_id is reported, not a list of violations"
        )

        _, meta = validate_paginated(
            api.list_purchase_contracts(
                make_wholesaler_headers(scenario.w_id),
                {"seller_lead_id": scenario.lead_id},
            )
        )
        assert_pagination_meta(meta, total_count=0)


class TestConditionalDoNotCallScrub:
    """The scrub is demanded of two channels and of no others."""

    def test_sms_needs_the_scrub_where_direct_mail_does_not(self, api):
        """
        "... and a campaign on the `SMS` or `COLD_CALL` channel must
        additionally have `dnc_scrubbed` true. Those four are reported, in that
        order, as `ERR_WHOLESALER_COMPLIANCE_HOLD`,
        `ERR_INTENT_TO_ASSIGN_NOT_DISCLOSED`,
        `ERR_LICENSURE_DISCLOSURE_MISSING` and `ERR_DNC_SCRUB_REQUIRED`."

        "`dnc_scrubbed` records that the target list was scrubbed against the
        do-not-call registry."

        Design: Corner/validations/sms_campaign_publish_without_dnc_scrub_is_rejected
        """
        scenario = build_desk(api, clock="2026-08-02T00:00:00Z")
        headers = make_wholesaler_headers(scenario.w_id)

        sms = draft_campaign(
            api,
            scenario.w_id,
            channel="SMS",
            headline="Cash offer in 24 hours",
            discloses_intent_to_assign=True,
            discloses_unlicensed_status=True,
        )
        assert_marketing_campaign(sms, dnc_scrubbed=False)

        mail = draft_campaign(
            api,
            scenario.w_id,
            channel="DIRECT_MAIL",
            headline="Cash offer in 24 hours",
            discloses_intent_to_assign=True,
            discloses_unlicensed_status=True,
        )
        published_mail = validate_success(
            api.publish_marketing_campaign(mail["id"], headers), 200
        )
        assert_marketing_campaign(published_mail, status="PUBLISHED")

        response = api.publish_marketing_campaign(sms["id"], headers)
        validate_error(response, ApiErrorId.DNC_SCRUB_REQUIRED, 422)

        assert_marketing_campaign(
            read_campaign(api, sms["id"], scenario.w_id),
            status="DRAFT",
            published_at=None,
        )

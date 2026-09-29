"""
Cascades whose later hops are caused by earlier hops: contract cancellation
walking the live offer out to the buyer's capital, and an adverse adjudication
walking the hold flag out to campaigns and their leads.
"""

from test_helpers import (
    assert_assignment_offer,
    assert_cash_buyer,
    assert_compliance_review,
    assert_earnest_money_deposit,
    assert_escrow_conserved,
    assert_marketing_campaign,
    assert_purchase_contract,
    assert_seller_lead,
    assert_wholesaler,
    adjudicate_review,
    build_accepted_offer,
    build_published_campaign,
    factories,
    find_deposit,
    make_wholesaler_headers,
    open_review,
    read_buyer,
    read_campaign,
    read_contract,
    read_lead,
    read_offer,
    read_review,
    read_wholesaler,
    record_lead,
    validate_success,
    COMPLIANCE_HOLD_THRESHOLD,
    COMPLIANCE_OFFICER_1,
    COMPLIANCE_OFFICER_2,
)

CANCELLATION_REASON = "Title defect discovered during the option period"


def _accepted_deal(api):
    """A signed contract whose single live offer has been accepted."""
    return build_accepted_offer(
        api,
        clock="2026-08-10T00:00:00Z",
        buyer_price_cents=20160000,
        buyer_deposit_cents=1000000,
        structure_election="ASSIGNMENT_ELECTED",
        contract_kwargs={
            "purchase_price_cents": 18000000,
            "earnest_money_cents": 500000,
            "inspection_period_days": 7,
        },
    )


def _cancel(api, scenario):
    return validate_success(
        api.cancel_purchase_contract(
            scenario.pc_id,
            factories.cancel_payload(CANCELLATION_REASON),
            make_wholesaler_headers(scenario.w_id),
        ),
        200,
    )


class TestCancellationCascadesThroughTheLiveMarket:
    """Level two lapses the accepted offer; level four then frees the capital."""

    def test_cancel_lapses_the_accepted_offer_and_releases_its_deposit(self, api):
        """
        "Cancelling a `SIGNED` or `PENDING_CLOSE` contract runs a four-level
        cascade, and both edges run exactly the same one. Level one is the
        contract itself. Level two lapses the market: every offer on this
        contract in `SUBMITTED`, `COUNTERED_BY_WHOLESALER`, `REVISED_BY_BUYER` or
        `ACCEPTED` status is driven to `LAPSED`."

        "Level four restores buyer capital: `committed_deposit_cents`,
        `available_funds_cents`, `buyer_tier` and `active_offer_count` are
        recomputed on every affected cash buyer, since the lapsed offers no
        longer encumber anyone's funds."

        "The live statuses are `SUBMITTED`, `COUNTERED_BY_WHOLESALER`,
        `REVISED_BY_BUYER` and `ACCEPTED`; an offer that reaches `CONSUMED`,
        `WITHDRAWN` or `LAPSED` releases its deposit."

        Design: Difficulty/transitive_cascade/contract_cancel_cascades_offer_agreement_buyer_tier
        """
        scenario = _accepted_deal(api)
        assert_assignment_offer(scenario.offer, status="ACCEPTED")
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            committed_deposit_cents=1000000,
            available_funds_cents=24500000,
            active_offer_count=1,
            buyer_tier="STANDARD",
        )

        cancelled = _cancel(api, scenario)

        assert_purchase_contract(
            cancelled,
            contract_status="CANCELLED",
            cancellation_reason=CANCELLATION_REASON,
            cancelled_at="2026-08-10T00:00:00Z",
        )
        assert_assignment_offer(
            read_offer(api, scenario.offer_id, scenario.w_id), status="LAPSED"
        )
        # The buyer was not touched by the cancel call; the offer leaving the
        # live set is what freed the encumbrance.
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            committed_deposit_cents=0,
            available_funds_cents=25500000,
            active_offer_count=0,
            buyer_tier="PRIORITY",
        )

    def test_cancel_refunds_escrow_and_hands_the_property_back(self, api):
        """
        "The earnest money deposit moves from `HELD` to
        `REFUNDED_TO_WHOLESALER`, transferring the whole of `held_cents` into
        `refunded_to_wholesaler_cents` and incrementing `disposition_event_count`
        by one — a wholesaler who cancels inside its inspection period gets its
        money back."

        "Finally, the owning lead returns from `UNDER_CONTRACT` to `SCREENED`
        when the cancelled contract was the lead's only non-terminal contract;
        where a non-overlapping backup contract remains live, the lead stays
        `UNDER_CONTRACT`."

        "These three dimensions advance independently of one another and none of
        them constrains another's transitions except where a precondition
        explicitly says so."

        Design: Difficulty/transitive_cascade/contract_cancel_cascades_offer_agreement_buyer_tier
        """
        scenario = _accepted_deal(api)
        assert_earnest_money_deposit(
            find_deposit(api, scenario.pc_id, scenario.w_id),
            status="HELD",
            held_cents=500000,
            disposition_event_count=0,
        )
        assert_seller_lead(
            read_lead(api, scenario.lead_id, scenario.w_id), status="UNDER_CONTRACT"
        )

        _cancel(api, scenario)

        deposit = find_deposit(api, scenario.pc_id, scenario.w_id)
        assert_earnest_money_deposit(
            deposit,
            status="REFUNDED_TO_WHOLESALER",
            amount_cents=500000,
            held_cents=0,
            refunded_to_wholesaler_cents=500000,
            forfeited_to_seller_cents=0,
            applied_at_closing_cents=0,
            disposition_event_count=1,
        )
        assert_escrow_conserved(deposit)
        assert_seller_lead(
            read_lead(api, scenario.lead_id, scenario.w_id), status="SCREENED"
        )
        # Only the contract_status dimension moved.
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            contract_status="CANCELLED",
            assignment_status="MARKETED",
            structure_election="ASSIGNMENT_ELECTED",
        )


class TestAdverseFindingCascadesOutToTheLeads:
    """The second finding flips the hold, and the hold does the rest."""

    def test_first_adverse_finding_stops_short_of_the_hold_threshold(self, api):
        """
        "`adverse_finding_count` is the number of that wholesaler's compliance
        reviews whose status is `ADJUDICATED_ADVERSE`. `compliance_hold` becomes
        true once `adverse_finding_count` reaches two, and while it is true the
        wholesaler may not originate new business or execute assignments."

        "A lead's `lead_gen_blocked` is true whenever the owning wholesaler's
        `compliance_hold` is true, or the lead names a `marketing_campaign_id`
        whose campaign status is `SUSPENDED`."

        Design: Difficulty/transitive_cascade/adverse_compliance_finding_cascades_hold_and_campaign_suspension
        """
        scenario = build_published_campaign(api, clock="2026-08-10T00:00:00Z")
        lead = record_lead(
            api, scenario.w_id, marketing_campaign_id=scenario.campaign["id"]
        )

        first = open_review(
            api,
            scenario.w_id,
            COMPLIANCE_OFFICER_1,
            review_type="MARKETING_COMPLIANCE",
        )
        adjudicated = adjudicate_review(
            api, first["id"], "ADVERSE", "DISCLOSURE_FAILURE", COMPLIANCE_OFFICER_2
        )
        assert_compliance_review(
            adjudicated,
            status="ADJUDICATED_ADVERSE",
            finding="DISCLOSURE_FAILURE",
            adjudicated_by_user_id="co-2",
        )

        assert_wholesaler(
            read_wholesaler(api, scenario.w_id),
            adverse_finding_count=1,
            compliance_hold=False,
        )
        assert 1 < COMPLIANCE_HOLD_THRESHOLD, (
            "one finding must sit strictly below the two-finding threshold"
        )
        assert_marketing_campaign(
            read_campaign(api, scenario.campaign["id"], scenario.w_id),
            status="PUBLISHED",
            suspension_count=0,
        )
        assert_seller_lead(
            read_lead(api, lead["id"], scenario.w_id), lead_gen_blocked=False
        )

    def test_second_finding_flips_the_hold_which_suspends_and_blocks(self, api):
        """
        "When an adverse adjudication drives `compliance_hold` from false to true
        within a single request, four levels of effect are applied in that same
        request: the review itself is finalised; the wholesaler's adverse count
        is incremented and the hold flag set; every one of that wholesaler's
        campaigns then in `PUBLISHED` status is driven to `SUSPENDED` with its
        `suspension_count` incremented by one; and `lead_gen_blocked` is set true
        on every seller lead of that wholesaler, including every lead attached to
        a campaign that was just suspended."

        "Suspension itself is never client-driven. The `PUBLISHED → SUSPENDED`
        edge fires only as part of the compliance-hold cascade, when an adverse
        adjudication moves the owning wholesaler's `compliance_hold` from false to
        true inside the same request."

        "Both adjudicated statuses are terminal, and re-adjudicating is
        `ERR_INVALID_STATE`."

        Design: Difficulty/transitive_cascade/adverse_compliance_finding_cascades_hold_and_campaign_suspension
        """
        scenario = build_published_campaign(api, clock="2026-08-10T00:00:00Z")
        campaign_id = scenario.campaign["id"]
        lead = record_lead(api, scenario.w_id, marketing_campaign_id=campaign_id)

        first = open_review(
            api,
            scenario.w_id,
            COMPLIANCE_OFFICER_1,
            review_type="MARKETING_COMPLIANCE",
        )
        adjudicate_review(
            api, first["id"], "ADVERSE", "DISCLOSURE_FAILURE", COMPLIANCE_OFFICER_2
        )
        second = open_review(
            api,
            scenario.w_id,
            COMPLIANCE_OFFICER_1,
            review_type="LICENSURE_BOUNDARY",
            subject_seller_lead_id=lead["id"],
        )

        ruling = adjudicate_review(
            api,
            second["id"],
            "ADVERSE",
            "UNLICENSED_BROKERAGE_ACTIVITY",
            COMPLIANCE_OFFICER_2,
        )

        assert_compliance_review(
            ruling,
            status="ADJUDICATED_ADVERSE",
            finding="UNLICENSED_BROKERAGE_ACTIVITY",
            adjudicated_by_user_id="co-2",
            adjudicated_at="2026-08-10T00:00:00Z",
        )
        assert_wholesaler(
            read_wholesaler(api, scenario.w_id),
            adverse_finding_count=COMPLIANCE_HOLD_THRESHOLD,
            compliance_hold=True,
        )
        assert_marketing_campaign(
            read_campaign(api, campaign_id, scenario.w_id),
            status="SUSPENDED",
            suspension_count=1,
        )
        assert_seller_lead(
            read_lead(api, lead["id"], scenario.w_id), lead_gen_blocked=True
        )
        # The earlier ruling is not re-touched by the second adjudication.
        assert_compliance_review(
            read_review(api, first["id"], scenario.w_id),
            status="ADJUDICATED_ADVERSE",
            finding="DISCLOSURE_FAILURE",
        )

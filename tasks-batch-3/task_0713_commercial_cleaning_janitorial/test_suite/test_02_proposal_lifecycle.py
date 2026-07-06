"""Proposal lifecycle: send/revise/accept cycle, margin floor, state precedence."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_proposal_payload, create_bid_estimate_payload,
    setup_sent_proposal, setup_draft_proposal, setup_priced_bid,
    create_account, create_rfp, add_service_areas,
    STANDARD_AREAS, SINGLE_LIGHT_AREA, TEST_USERS,
)

_BID = TEST_USERS["bid_estimator_headers"]
_SALES = TEST_USERS["sales_rep_headers"]

# An 8000sqft MEDIUM @5/wk area set is used where a margin-15.0 boundary is wanted.
MEDIUM_8000 = [{"label": "F1", "sqft": 8000, "soil_level": "MEDIUM", "frequency_per_week": 5}]


class TestProposalRevisionCycle:
    """Difficulty rule: non_linear_state_machine / proposal_revision_cycle_sent_back_to_draft."""

    def test_revise_sent_proposal_returns_to_draft(self, api):
        """PRD §3.5: "Revising a SENT proposal returns it from SENT to DRAFT,
        increments its revision_round by one, and returns the parent opportunity from
        PROPOSED back to BIDDING for re-pricing and re-sending."

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_sent_back_to_draft
        """
        acct, rfp, bid, prop = setup_sent_proposal(areas=MEDIUM_8000, legal_name="Rev Co",
                                                   with_walkthrough=True)
        revised = validate_success(
            api.revise_proposal(acct["id"], rfp["id"], prop["id"], _SALES), 200)
        assert revised["status"] == "DRAFT"
        assert revised["revision_round"] == 2

    def test_revise_bounces_parent_rfp_to_bidding(self, api):
        """PRD §3.5: "Revising a SENT proposal returns it from SENT to DRAFT,
        increments its revision_round by one, and returns the parent opportunity from
        PROPOSED back to BIDDING for re-pricing and re-sending."

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_sent_back_to_draft
        """
        acct, rfp, bid, prop = setup_sent_proposal(areas=MEDIUM_8000, legal_name="Rev Co 2",
                                                   with_walkthrough=True)
        validate_success(api.revise_proposal(acct["id"], rfp["id"], prop["id"], _SALES), 200)
        rfp_after = validate_success(api.get_rfp(acct["id"], rfp["id"], _SALES), 200)
        assert rfp_after["status"] == "BIDDING"


class TestMarginFloorBoundary:
    """Difficulty rule: boundary_precision_check / margin_floor_exact_15pct_passes_on_send."""

    def test_send_passes_at_exactly_15pct_margin(self, api):
        """PRD §3.5: "the proposal's achieved_margin_pct multiplied by 100 must be at
        least 15.0, the minimum margin percent; if it falls below 15.0 the send is
        rejected with ERR_MARGIN_BELOW_FLOOR."
        PRD §3.5: "Sending a proposal advances it from DRAFT to SENT and advances the
        parent opportunity from BIDDING to PROPOSED."

        Design: Difficulty/boundary_precision_check/margin_floor_exact_15pct_passes_on_send
        """
        # target_margin 0.15 on a small bid (no volume discount) yields an achieved
        # margin at the 15.0 floor, so the send succeeds (>= boundary).
        acct = create_account(legal_name="Bound Co")
        rfp = create_rfp(acct["id"], estimated_total_sqft=8000)
        # Reach BIDDING via a walkthrough.
        from test_helpers import create_site_contact_payload, create_walkthrough_payload
        sc = validate_success(api.create_site_contact(acct["id"], create_site_contact_payload(), _SALES), 201)
        wt = validate_success(api.create_walkthrough(acct["id"], rfp["id"], create_walkthrough_payload(sc["id"]), _SALES), 201)
        validate_success(api.complete_walkthrough(acct["id"], rfp["id"], wt["id"], _SALES), 200)
        add_service_areas(acct["id"], rfp["id"], MEDIUM_8000)
        bid = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"],
            create_bid_estimate_payload(target_margin_pct=0.15, loading_method="LOADED"), _BID), 201)
        validate_success(api.price_bid_estimate(acct["id"], rfp["id"], bid["id"], _BID), 200)
        prop = validate_success(api.create_proposal(
            acct["id"], rfp["id"], create_proposal_payload(bid["id"]), _SALES), 201)
        sent = validate_success(api.send_proposal(acct["id"], rfp["id"], prop["id"], _SALES), 200)
        assert sent["status"] == "SENT"

    def test_send_rejected_below_margin_floor(self, api):
        """PRD §3.5: "if it falls below 15.0 the send is rejected with
        ERR_MARGIN_BELOW_FLOOR."

        Design: Difficulty/boundary_precision_check/margin_floor_exact_15pct_passes_on_send
        """
        # target_margin 0.10 drives the achieved margin below the 15.0 floor.
        acct = create_account(legal_name="LowMargin Co")
        rfp = create_rfp(acct["id"], estimated_total_sqft=8000)
        from test_helpers import create_site_contact_payload, create_walkthrough_payload
        sc = validate_success(api.create_site_contact(acct["id"], create_site_contact_payload(), _SALES), 201)
        wt = validate_success(api.create_walkthrough(acct["id"], rfp["id"], create_walkthrough_payload(sc["id"]), _SALES), 201)
        validate_success(api.complete_walkthrough(acct["id"], rfp["id"], wt["id"], _SALES), 200)
        add_service_areas(acct["id"], rfp["id"], MEDIUM_8000)
        bid = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"],
            create_bid_estimate_payload(target_margin_pct=0.10, loading_method="LOADED"), _BID), 201)
        validate_success(api.price_bid_estimate(acct["id"], rfp["id"], bid["id"], _BID), 200)
        prop = validate_success(api.create_proposal(
            acct["id"], rfp["id"], create_proposal_payload(bid["id"]), _SALES), 201)
        validate_error(api.send_proposal(acct["id"], rfp["id"], prop["id"], _SALES),
                       "ERR_MARGIN_BELOW_FLOOR")


class TestStateBeforeMarginPrecedence:
    """Difficulty rule: priority_pair_validation_conflict /
    state_vs_fiscal_send_on_nonbidding_with_low_margin."""

    def test_state_check_wins_over_margin_floor(self, api):
        """PRD §2.7: "then target-state correctness for the transition
        (ERR_INVALID_STATE), then cross-entity state preconditions, then the
        domain-specific temporal, safety, capacity, fiscal, and concurrency checks
        described below."
        PRD §3.5: "The proposal must currently be DRAFT and its parent opportunity must
        be in BIDDING, otherwise ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_send_on_nonbidding_with_low_margin
        """
        # Build an RFP already PROPOSED via a sibling proposal, plus a low-margin DRAFT
        # proposal. Sending the low-margin DRAFT fails the state check (RFP not BIDDING)
        # before the margin floor would ever be evaluated.
        acct = create_account(legal_name="Prio Co")
        rfp = create_rfp(acct["id"], estimated_total_sqft=8000)
        from test_helpers import create_site_contact_payload, create_walkthrough_payload
        sc = validate_success(api.create_site_contact(acct["id"], create_site_contact_payload(), _SALES), 201)
        wt = validate_success(api.create_walkthrough(acct["id"], rfp["id"], create_walkthrough_payload(sc["id"]), _SALES), 201)
        validate_success(api.complete_walkthrough(acct["id"], rfp["id"], wt["id"], _SALES), 200)
        add_service_areas(acct["id"], rfp["id"], MEDIUM_8000)
        bid_ok = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"], create_bid_estimate_payload(target_margin_pct=0.20, loading_method="LOADED"), _BID), 201)
        validate_success(api.price_bid_estimate(acct["id"], rfp["id"], bid_ok["id"], _BID), 200)
        bid_low = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"], create_bid_estimate_payload(target_margin_pct=0.10, loading_method="LOADED"), _BID), 201)
        validate_success(api.price_bid_estimate(acct["id"], rfp["id"], bid_low["id"], _BID), 200)
        prop_low = validate_success(api.create_proposal(
            acct["id"], rfp["id"], create_proposal_payload(bid_low["id"]), _SALES), 201)
        prop_ok = validate_success(api.create_proposal(
            acct["id"], rfp["id"], create_proposal_payload(bid_ok["id"]), _SALES), 201)
        # Send the OK proposal first -> RFP advances to PROPOSED.
        validate_success(api.send_proposal(acct["id"], rfp["id"], prop_ok["id"], _SALES), 200)
        # Now the low-margin DRAFT proposal's send fails on state, not margin.
        validate_error(api.send_proposal(acct["id"], rfp["id"], prop_low["id"], _SALES),
                       "ERR_INVALID_STATE")

    def test_low_margin_proposal_stays_draft_after_state_rejection(self, api):
        """PRD §3.5: "The proposal must currently be DRAFT and its parent opportunity
        must be in BIDDING, otherwise ERR_INVALID_STATE."
        PRD §3.5: "The new Proposal records its rfp_id, starts in status DRAFT".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_send_on_nonbidding_with_low_margin
        """
        acct = create_account(legal_name="Prio Co 2")
        rfp = create_rfp(acct["id"], estimated_total_sqft=8000)
        from test_helpers import create_site_contact_payload, create_walkthrough_payload
        sc = validate_success(api.create_site_contact(acct["id"], create_site_contact_payload(), _SALES), 201)
        wt = validate_success(api.create_walkthrough(acct["id"], rfp["id"], create_walkthrough_payload(sc["id"]), _SALES), 201)
        validate_success(api.complete_walkthrough(acct["id"], rfp["id"], wt["id"], _SALES), 200)
        add_service_areas(acct["id"], rfp["id"], MEDIUM_8000)
        bid_ok = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"], create_bid_estimate_payload(target_margin_pct=0.20, loading_method="LOADED"), _BID), 201)
        validate_success(api.price_bid_estimate(acct["id"], rfp["id"], bid_ok["id"], _BID), 200)
        bid_low = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"], create_bid_estimate_payload(target_margin_pct=0.10, loading_method="LOADED"), _BID), 201)
        validate_success(api.price_bid_estimate(acct["id"], rfp["id"], bid_low["id"], _BID), 200)
        prop_low = validate_success(api.create_proposal(
            acct["id"], rfp["id"], create_proposal_payload(bid_low["id"]), _SALES), 201)
        prop_ok = validate_success(api.create_proposal(
            acct["id"], rfp["id"], create_proposal_payload(bid_ok["id"]), _SALES), 201)
        validate_success(api.send_proposal(acct["id"], rfp["id"], prop_ok["id"], _SALES), 200)
        validate_error(api.send_proposal(acct["id"], rfp["id"], prop_low["id"], _SALES),
                       "ERR_INVALID_STATE")
        low_after = validate_success(api.get_proposal(acct["id"], rfp["id"], prop_low["id"], _SALES), 200)
        assert low_after["status"] == "DRAFT"


class TestProposalCornerClaims:
    """Corner section: state_machines / validations."""

    def test_accept_draft_proposal_rejected(self, api):
        """PRD §3.5: "Accepting a SENT proposal moves it to ACCEPTED and the
        opportunity from PROPOSED to WON."
        PRD §3.5: "Both require the proposal to be SENT, otherwise ERR_INVALID_STATE."

        Design: Corner/state_machines/accept_proposal_from_draft_returns_invalid_state
        """
        acct, rfp, bid, prop = setup_draft_proposal(areas=MEDIUM_8000, legal_name="PState Co")
        validate_error(api.accept_proposal(acct["id"], rfp["id"], prop["id"], _SALES),
                       "ERR_INVALID_STATE")

    def test_create_proposal_from_unpriced_bid_rejected(self, api):
        """PRD §3.5: "The create takes a bid_estimate_id, which must reference a
        BidEstimate that is in status PRICED; if the referenced estimate is not PRICED,
        the create is rejected with ERR_BID_NOT_PRICED."

        Design: Corner/validations/bid_not_priced_proposal_create_returns_error
        """
        acct = create_account(legal_name="NP Co")
        rfp = create_rfp(acct["id"], estimated_total_sqft=8000)
        add_service_areas(acct["id"], rfp["id"], MEDIUM_8000)
        bid = validate_success(api.create_bid_estimate(
            acct["id"], rfp["id"], create_bid_estimate_payload(loading_method="LOADED"), _BID), 201)
        # bid stays DRAFT (never priced)
        validate_error(api.create_proposal(acct["id"], rfp["id"], create_proposal_payload(bid["id"]), _SALES),
                       "ERR_BID_NOT_PRICED")

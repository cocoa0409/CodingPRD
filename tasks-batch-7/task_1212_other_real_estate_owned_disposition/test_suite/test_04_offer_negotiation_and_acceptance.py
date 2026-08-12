"""Offer lifecycle: negotiation cycle, invalid transitions, acceptance gates,
approval-authority tiers, and supersede cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_property,
    create_property_with_certified_appraisal,
    create_marketed_property,
    create_offer,
    create_offer_under_review,
    submit_offer_review,
    get_offer,
    get_property,
    get_listing,
    setup_approval_tiers,
    setup_property_with_accepted_offer,
    setup_settled_sale,
    create_issue_payload,
    create_appraiser,
    create_draft_appraisal,
    submit_appraisal,
    certify_appraisal,
    set_clock,
    list_write_downs,
)

ADMIN = TEST_USERS["oreo_admin_headers"]
SPEC = TEST_USERS["oreo_specialist_headers"]
CO = TEST_USERS["credit_officer_headers"]
PM = TEST_USERS["property_manager_headers"]
COMMITTEE = TEST_USERS["oreo_committee_headers"]


class TestOfferNegotiationCycle:
    def test_counter_then_resume_reopens_review(self, api):
        """PRD §3.5: "From UNDER_REVIEW the specialist may counter, supplying a
        counter_price strictly greater than zero; the offer moves to COUNTERED,
        current_price becomes the counter price, and counter_round increments by
        one. When the buyer responds, the specialist resumes the offer, moving
        COUNTERED back to UNDER_REVIEW for another cycle; the resume carries no
        payload."

        Design: Difficulty/non_linear_state_machine/offer_counter_cycle_reopens_review
        """
        setup_approval_tiers()
        ctx = create_marketed_property()
        offer = create_offer_under_review(
            ctx["property"]["id"],
            ctx["property"]["version"],
            offer_price=440000.00,
            listing_agreement_id=ctx["listing"]["id"],
        )
        # First loop
        c1 = validate_success(
            api.counter_offer(offer["id"], {"counter_price": 445000.00}, SPEC)
        )
        assert c1["status"] == "COUNTERED"
        assert c1["current_price"] == 445000.00
        assert c1["counter_round"] == 1
        r1 = validate_success(api.resume_offer(offer["id"], SPEC))
        assert r1["status"] == "UNDER_REVIEW"

        # Second loop
        c2 = validate_success(
            api.counter_offer(offer["id"], {"counter_price": 448000.00}, SPEC)
        )
        assert c2["counter_round"] == 2
        r2 = validate_success(api.resume_offer(offer["id"], SPEC))
        assert r2["status"] == "UNDER_REVIEW"

        final = get_offer(offer["id"])
        assert final["counter_round"] == 2
        assert final["current_price"] == 448000.00
        assert final["offer_price"] == 440000.00

    def test_accept_succeeds_from_under_review_after_counter_cycles(self, api):
        """PRD §3.6: "The offer itself must be in UNDER_REVIEW or COUNTERED"
        (for acceptance).

        Design: Difficulty/non_linear_state_machine/offer_counter_cycle_reopens_review
        """
        setup_approval_tiers()
        ctx = create_marketed_property()
        offer = create_offer_under_review(
            ctx["property"]["id"],
            ctx["property"]["version"],
            offer_price=440000.00,
            listing_agreement_id=ctx["listing"]["id"],
        )
        api.counter_offer(offer["id"], {"counter_price": 445000.00}, SPEC)
        api.resume_offer(offer["id"], SPEC)
        api.counter_offer(offer["id"], {"counter_price": 448000.00}, SPEC)
        api.resume_offer(offer["id"], SPEC)
        # accept after two cycles
        accept_resp = api.accept_offer(offer["id"], CO)
        accepted = validate_success(accept_resp)
        assert accepted["status"] == "ACCEPTED"
        prop = get_property(ctx["property"]["id"])
        assert prop["lifecycle_status"] == "UNDER_CONTRACT"


class TestOfferInvalidTransitions:
    def test_withdraw_accepted_offer_returns_invalid_state(self, api):
        """PRD §3.5: "A specialist may also withdraw a pending offer from
        RECEIVED, UNDER_REVIEW, or COUNTERED, moving it to WITHDRAWN"; and "Any
        submit-review, counter, resume, accept, reject, or withdraw attempted on
        an offer not in a legal from-state for that action is rejected with
        ERR_OFFER_NOT_REVIEWABLE (HTTP 409)."

        Design: Corner/state_machines/withdraw_accepted_offer_returns_invalid_state
        """
        ctx = setup_property_with_accepted_offer()
        offer = ctx["offer"]
        prop = ctx["property"]
        resp = api.withdraw_offer(offer["id"], SPEC)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_REVIEWABLE)
        assert get_offer(offer["id"])["status"] == "ACCEPTED"
        assert get_property(prop["id"])["lifecycle_status"] == "UNDER_CONTRACT"

    def test_reject_closed_offer_returns_terminal_lockdown(self, api):
        """PRD §3.5: "Any submit-review, counter, resume, accept, reject, or
        withdraw attempted on an offer not in a legal from-state for that action
        is rejected with ERR_OFFER_NOT_REVIEWABLE (HTTP 409)."
        PRD §3.7: "Settlement moves the closing to SETTLED, the offer to CLOSED".

        Design: Corner/state_machines/reject_closed_offer_returns_terminal_lockdown
        """
        ctx = setup_settled_sale()
        offer = ctx["offer"]
        prop = ctx["property"]
        resp = api.reject_offer(offer["id"], SPEC)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_REVIEWABLE)
        assert get_offer(offer["id"])["status"] == "CLOSED"
        assert get_property(prop["id"])["lifecycle_status"] == "DISPOSED"

    def test_double_accept_offer_returns_invalid_state(self, api):
        """PRD §3.6: "The offer itself must be in UNDER_REVIEW or COUNTERED."
        Combined with §3.5's blanket rule: "Any submit-review, counter, resume,
        accept, reject, or withdraw attempted on an offer not in a legal
        from-state for that action is rejected with ERR_OFFER_NOT_REVIEWABLE
        (HTTP 409)."

        Design: Corner/state_machines/double_accept_offer_returns_invalid_state
        """
        ctx = setup_property_with_accepted_offer()
        offer = ctx["offer"]
        prop = ctx["property"]
        # second accept
        resp = api.accept_offer(offer["id"], CO)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_REVIEWABLE)
        # no additional supersede cascade — property still UNDER_CONTRACT
        assert get_property(prop["id"])["lifecycle_status"] == "UNDER_CONTRACT"


class TestOfferAcceptanceCascade:
    def test_rescind_accepted_offer_reopens_marketing(self, api):
        """PRD §3.6: "Before settlement, an OREOSpecialist or CreditOfficer may
        rescind the accepted offer — but only while no closing statement in
        DRAFT or SETTLED exists for it... Rescission moves the offer to
        RESCINDED and reverts the property from UNDER_CONTRACT to MARKETED; the
        property may then sit MARKETED with zero active listings until
        re-listed, because the original mandate was terminated at acceptance."

        Design: Corner/state_machines/rescind_accepted_offer_reopens_marketing
        """
        ctx = setup_property_with_accepted_offer()
        offer = ctx["offer"]
        prop = ctx["property"]
        listing = ctx["listing"]
        resc_resp = api.rescind_offer(offer["id"], CO)
        rescinded = validate_success(resc_resp)
        assert rescinded["status"] == "RESCINDED"
        p_after = get_property(prop["id"])
        assert p_after["lifecycle_status"] == "MARKETED"
        # listing stays TERMINATED (not resurrected)
        l_after = get_listing(listing["id"])
        assert l_after["status"] == "TERMINATED"
        assert l_after["termination_reason"] == "UNDER_CONTRACT"

    def test_accept_offer_supersedes_competing_pending_offers(self, api):
        """PRD §3.6: "When acceptance succeeds, the offer moves to ACCEPTED, the
        property moves from MARKETED to UNDER_CONTRACT, the ACTIVE listing
        agreement on the property moves to TERMINATED with termination_reason
        UNDER_CONTRACT, every other offer on the property sitting in RECEIVED,
        UNDER_REVIEW, or COUNTERED moves to REJECTED with rejection_reason
        SUPERSEDED, and property.version increments."

        Design: Corner/state_machines/accept_offer_supersedes_competing_pending_offers
        """
        setup_approval_tiers()
        ctx = create_marketed_property()
        prop = ctx["property"]
        listing = ctx["listing"]
        offer_a = create_offer_under_review(
            prop["id"],
            prop["version"],
            offer_price=450000.00,
            listing_agreement_id=listing["id"],
            buyer_name="Buyer A",
        )
        prop_v = get_property(prop["id"])["version"]
        offer_b = create_offer_under_review(
            prop["id"],
            prop_v,
            offer_price=445000.00,
            listing_agreement_id=listing["id"],
            buyer_name="Buyer B",
        )
        # accept A; B must cascade-reject
        accept_resp = api.accept_offer(offer_a["id"], CO)
        validate_success(accept_resp)
        assert get_offer(offer_a["id"])["status"] == "ACCEPTED"
        b_after = get_offer(offer_b["id"])
        assert b_after["status"] == "REJECTED"
        assert b_after["rejection_reason"] == "SUPERSEDED"
        assert get_property(prop["id"])["lifecycle_status"] == "UNDER_CONTRACT"


class TestOfferAcceptanceGates:
    def test_offer_create_on_unlisted_property_returns_not_marketable(self, api):
        """PRD §3.5: "The property must be MARKETED for an offer to be created
        — otherwise ERR_PROPERTY_NOT_MARKETABLE".

        Design: Corner/validations/offer_create_on_unlisted_property_returns_not_marketable
        """
        prop, _ap, _a = create_property_with_certified_appraisal()
        # property is HELD (no listing activated)
        from test_helpers import create_offer_payload

        payload = create_offer_payload(
            property_id=prop["id"],
            expected_property_version=prop["version"],
        )
        resp = api.create_offer(payload, SPEC)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_MARKETABLE)

    def test_offer_create_when_appraisal_overdue_returns_409(self, api):
        """PRD §3.5: "an UNAPPRAISED or OVERDUE property also blocks creation
        with ERR_APPRAISAL_OVERDUE."

        Design: Corner/validations/offer_create_when_appraisal_overdue_returns_409
        """
        # Long-lived listing so the property stays MARKETED past appraisal expiry
        ctx = create_marketed_property(
            appraised_value=400000.00, listing_end="2028-12-05"
        )
        prop = ctx["property"]
        listing = ctx["listing"]
        # advance past E+365 (E=2026-06-01, E+365=2027-06-01)
        set_clock("2027-06-02T00:00:00Z")
        prop_now = get_property(prop["id"])
        assert prop_now["appraisal_status"] == "OVERDUE"
        from test_helpers import create_offer_payload

        payload = create_offer_payload(
            property_id=prop["id"],
            listing_agreement_id=listing["id"],
            expected_property_version=prop_now["version"],
        )
        resp = api.create_offer(payload, SPEC)
        validate_error(resp, ApiErrorId.ERR_APPRAISAL_OVERDUE)

    def test_accept_lowball_offer_returns_below_min_proceeds_422(self, api):
        """PRD §3.6: "First, projected net_proceeds — current_price minus the
        tiered broker commission minus the flat 2500.00 closing cost — must be
        strictly greater than zero, or acceptance fails with
        ERR_BELOW_MIN_PROCEEDS (HTTP 422)."

        Design: Corner/validations/accept_lowball_offer_returns_below_min_proceeds_422
        """
        setup_approval_tiers()
        ctx = create_marketed_property()
        offer = create_offer_under_review(
            ctx["property"]["id"],
            ctx["property"]["version"],
            offer_price=2000.00,
            listing_agreement_id=ctx["listing"]["id"],
            buyer_name="Lowball LLC",
        )
        # 2000 - 0.06*2000 (120) - 2500 = -620 -> below floor
        resp = api.accept_offer(offer["id"], COMMITTEE)
        validate_error(resp, ApiErrorId.ERR_BELOW_MIN_PROCEEDS)
        assert get_offer(offer["id"])["status"] == "UNDER_REVIEW"
        assert (
            get_property(ctx["property"]["id"])["lifecycle_status"] == "MARKETED"
        )

    def test_specialist_accept_tier2_deal_returns_authority_error(self, api):
        """PRD §3.6: "A caller whose rank is below the required rank is rejected
        with ERR_APPROVAL_AUTHORITY_EXCEEDED (HTTP 403). Concretely, an
        OREOSpecialist may accept only tier-1 deals, a CreditOfficer may accept
        tier-1 or tier-2 deals, and an OREOCommittee member may accept
        anything."

        Design: Corner/validations/specialist_accept_tier2_deal_returns_authority_error
        """
        setup_approval_tiers()
        ctx = create_marketed_property()
        # 450000 CASH -> net_proceeds = 450000 - 27000 - 2500 = 420500 -> tier 2
        offer = create_offer_under_review(
            ctx["property"]["id"],
            ctx["property"]["version"],
            offer_price=450000.00,
            listing_agreement_id=ctx["listing"]["id"],
        )
        # OREOSpecialist (rank 1) -> denied
        resp1 = api.accept_offer(offer["id"], SPEC)
        validate_error(resp1, ApiErrorId.ERR_APPROVAL_AUTHORITY_EXCEEDED)
        # CreditOfficer (rank 2) -> allowed
        resp2 = api.accept_offer(offer["id"], CO)
        accepted = validate_success(resp2)
        assert accepted["status"] == "ACCEPTED"

    def test_specialist_accept_deep_discount_returns_authority_error(self, api):
        """PRD §3.6: "Independent of tiers, a deep-discount rule guards
        fire-sale economics: when projected net_proceeds is strictly less than
        0.9 times the property's current carrying_value, the required rank is
        forced to 3... A caller whose rank is below the required rank is
        rejected with ERR_APPROVAL_AUTHORITY_EXCEEDED (HTTP 403)."

        Design: Corner/validations/specialist_accept_deep_discount_returns_authority_error
        """
        setup_approval_tiers()
        ctx = create_marketed_property(listing_price=250000.00)
        # offer 200000 -> net = 200000 - 12000 - 2500 = 185500 -> tier 1 by price
        # but 185500 < 0.9 * 368000 = 331200 -> deep-discount -> rank 3
        offer = create_offer_under_review(
            ctx["property"]["id"],
            ctx["property"]["version"],
            offer_price=200000.00,
            listing_agreement_id=ctx["listing"]["id"],
            buyer_name="Discount Buyer",
            earnest_money=2000.00,
        )
        resp1 = api.accept_offer(offer["id"], SPEC)
        validate_error(resp1, ApiErrorId.ERR_APPROVAL_AUTHORITY_EXCEEDED)
        resp2 = api.accept_offer(offer["id"], COMMITTEE)
        accepted = validate_success(resp2)
        assert accepted["status"] == "ACCEPTED"

    def test_accept_blocked_by_pending_write_down_returns_409(self, api):
        """PRD §3.6: "it must have pending_write_down_count equal to zero — a
        PROPOSED write-down sitting on the property blocks acceptance with
        ERR_WRITE_DOWN_PENDING (HTTP 409) until the committee disposes of it".

        Design: Corner/validations/accept_blocked_by_pending_write_down_returns_409
        """
        setup_approval_tiers()
        # property with certified 400k appraisal + ACTIVE listing ending 2027
        ctx = create_marketed_property(
            appraised_value=400000.00, listing_end="2027-06-05"
        )
        prop = ctx["property"]
        appraiser = ctx["appraiser"]
        listing = ctx["listing"]

        # move clock outside the measurement window; certify a lower appraisal
        set_clock("2026-12-10T00:00:00Z")
        prop_now = get_property(prop["id"])
        a2 = create_draft_appraisal(
            prop["id"],
            appraiser["id"],
            prop_now["version"],
            effective_date="2026-12-10",
            appraised_value=350000.00,
        )
        submit_appraisal(a2["id"], appraiser["id"])
        certify_appraisal(a2["id"])

        # confirm pending write-down exists
        prop_now2 = get_property(prop["id"])
        assert prop_now2["pending_write_down_count"] == 1

        # try to accept an offer
        offer = create_offer_under_review(
            prop["id"],
            prop_now2["version"],
            offer_price=450000.00,
            listing_agreement_id=listing["id"],
        )
        resp = api.accept_offer(offer["id"], CO)
        validate_error(resp, ApiErrorId.ERR_WRITE_DOWN_PENDING)
        assert get_offer(offer["id"])["status"] == "UNDER_REVIEW"

    def test_offer_accept_blocked_by_open_environmental_issue(self, api):
        """PRD §3.6: "it must carry no OPEN or IN_REMEDIATION environmental
        issue (ERR_ENVIRONMENTAL_ISSUE_OPEN)".

        Design: Difficulty/cross_entity_state_dependency/offer_accept_blocked_by_open_environmental_issue
        """
        setup_approval_tiers()
        ctx = create_marketed_property()
        prop = ctx["property"]
        listing = ctx["listing"]
        offer = create_offer_under_review(
            prop["id"],
            prop["version"],
            offer_price=450000.00,
            listing_agreement_id=listing["id"],
        )
        # open ENV issue blocks accept
        issue_resp = api.create_issue(
            create_issue_payload(
                property_id=prop["id"],
                issue_type="ENVIRONMENTAL",
                severity="HIGH",
                description="Asbestos in basement",
            ),
            PM,
        )
        issue = validate_success(issue_resp, expected_status=201)

        r1 = api.accept_offer(offer["id"], CO)
        validate_error(r1, ApiErrorId.ERR_ENVIRONMENTAL_ISSUE_OPEN)

    def test_offer_accept_unblocked_after_environmental_issue_resolved(self, api):
        """PRD §3.6: "it must carry no OPEN or IN_REMEDIATION environmental
        issue (ERR_ENVIRONMENTAL_ISSUE_OPEN)"; PRD §3.8: "an IN_REMEDIATION
        issue moves to RESOLVED via resolve".

        Design: Difficulty/cross_entity_state_dependency/offer_accept_blocked_by_open_environmental_issue
        """
        setup_approval_tiers()
        ctx = create_marketed_property()
        prop = ctx["property"]
        listing = ctx["listing"]
        offer = create_offer_under_review(
            prop["id"],
            prop["version"],
            offer_price=450000.00,
            listing_agreement_id=listing["id"],
        )
        issue_resp = api.create_issue(
            create_issue_payload(
                property_id=prop["id"],
                issue_type="ENVIRONMENTAL",
                severity="HIGH",
                description="Asbestos in basement",
            ),
            PM,
        )
        issue = validate_success(issue_resp, expected_status=201)

        # OPEN blocks
        r1 = api.accept_offer(offer["id"], CO)
        validate_error(r1, ApiErrorId.ERR_ENVIRONMENTAL_ISSUE_OPEN)
        # IN_REMEDIATION still blocks
        api.start_remediation(issue["id"], PM)
        r2 = api.accept_offer(offer["id"], CO)
        validate_error(r2, ApiErrorId.ERR_ENVIRONMENTAL_ISSUE_OPEN)
        # resolve unblocks
        api.resolve_issue(issue["id"], {"resolution_notes": "Abatement completed"}, PM)
        r3 = api.accept_offer(offer["id"], CO)
        accepted = validate_success(r3)
        assert accepted["status"] == "ACCEPTED"
        assert get_property(prop["id"])["lifecycle_status"] == "UNDER_CONTRACT"


class TestClosingCreationGates:
    def test_closing_create_on_unaccepted_offer_returns_409(self, api):
        """PRD §3.7: "The offer must be ACCEPTED (otherwise
        ERR_OFFER_NOT_ACCEPTED)".

        Design: Corner/validations/closing_create_on_unaccepted_offer_returns_409
        """
        setup_approval_tiers()
        ctx = create_marketed_property()
        offer = create_offer_under_review(
            ctx["property"]["id"],
            ctx["property"]["version"],
            offer_price=450000.00,
            listing_agreement_id=ctx["listing"]["id"],
        )
        # offer UNDER_REVIEW (never accepted)
        resp = api.create_closing_statement(
            {"offer_id": offer["id"], "closing_date": "2026-08-01"}, SPEC
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_ACCEPTED)

    def test_closing_with_open_title_issue_returns_409(self, api):
        """PRD §3.7: "no TITLE issue in OPEN or IN_REMEDIATION may exist either,
        else ERR_TITLE_ISSUE_OPEN (HTTP 409). Title issues do not block
        marketing or acceptance, but the bank will not close over one."

        Design: Corner/validations/closing_with_open_title_issue_returns_409
        """
        ctx = setup_property_with_accepted_offer()
        # open a TITLE issue after acceptance (allowed: TITLE does not gate accept)
        issue_resp = api.create_issue(
            create_issue_payload(
                property_id=ctx["property"]["id"],
                issue_type="TITLE",
                severity="HIGH",
                description="Unreleased mechanics lien",
            ),
            PM,
        )
        validate_success(issue_resp, expected_status=201)
        # closing must be rejected
        resp = api.create_closing_statement(
            {"offer_id": ctx["offer"]["id"], "closing_date": "2026-08-01"}, SPEC
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_ISSUE_OPEN)

    def test_closing_date_beyond_deadline_returns_422(self, api):
        """PRD §3.7: "the closing_date must be on or before the property's
        holding_deadline (otherwise ERR_CLOSING_BEYOND_DEADLINE, HTTP 422)".

        Design: Corner/validations/closing_date_beyond_deadline_returns_422
        """
        # long-lived listing to survive to 2031 without expiring
        ctx = setup_property_with_accepted_offer(listing_end="2032-06-05")
        # advance clock to 2031-05-01 (still <= deadline 2031-05-09, so no charge-off)
        set_clock("2031-05-01T00:00:00Z")
        resp = api.create_closing_statement(
            {"offer_id": ctx["offer"]["id"], "closing_date": "2031-06-01"}, SPEC
        )
        validate_error(resp, ApiErrorId.ERR_CLOSING_BEYOND_DEADLINE)
        # property still UNDER_CONTRACT (not charged off)
        assert (
            get_property(ctx["property"]["id"])["lifecycle_status"]
            == "UNDER_CONTRACT"
        )

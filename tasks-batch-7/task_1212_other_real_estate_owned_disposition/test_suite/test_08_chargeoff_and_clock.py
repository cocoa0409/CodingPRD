"""Charge-off cascades (manual + clock-driven), holding-period boundary
precision, and the validation-priority ladder."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    validate_success,
    validate_error,
    create_property,
    create_marketed_property,
    create_offer_under_review,
    setup_approval_tiers,
    setup_property_with_accepted_offer,
    get_property,
    get_offer,
    get_listing,
    list_write_downs,
    list_ledger_entries,
    set_clock,
    create_issue_payload,
)

ADMIN = TEST_USERS["oreo_admin_headers"]
PM = TEST_USERS["property_manager_headers"]
SPEC = TEST_USERS["oreo_specialist_headers"]
CO = TEST_USERS["credit_officer_headers"]
COMMITTEE = TEST_USERS["oreo_committee_headers"]
COMP = TEST_USERS["compliance_officer_headers"]


class TestHoldingDeadlineBoundary:
    def test_holding_deadline_exact_day_compliance_boundary_at_deadline(self, api):
        """PRD §3.10: "a property remains compliant while the logical clock is
        on or before its holding_deadline — the exact deadline day still counts
        as compliant — and is in violation once the clock is strictly after
        it."

        Design: Difficulty/boundary_precision_check/holding_deadline_exact_day_compliance_boundary
        """
        prop = create_property(
            address="5 Cedar Ln", county="Fresno", acquisition_date="2026-05-10"
        )
        # holding_deadline = 2026-05-10 + 1825 days = 2031-05-09
        # clock exactly at deadline -> still compliant
        set_clock("2031-05-09T00:00:00Z")
        after = get_property(prop["id"])
        assert after["lifecycle_status"] == "HELD"

    def test_holding_deadline_one_day_past_triggers_chargeoff(self, api):
        """PRD §3.10: "is in violation once the clock is strictly after it";
        PRD §2.9: "every property whose holding_deadline is now strictly in
        the past and whose lifecycle_status is one of HELD, MARKETED, or
        UNDER_CONTRACT transitions to CHARGED_OFF via the full charge-off
        cascade."

        Design: Difficulty/boundary_precision_check/holding_deadline_exact_day_compliance_boundary
        """
        prop = create_property(
            address="5 Cedar Ln", county="Fresno", acquisition_date="2026-05-10"
        )
        # one day past deadline
        set_clock("2031-05-10T00:00:00Z")
        after = get_property(prop["id"])
        assert after["lifecycle_status"] == "CHARGED_OFF"


class TestClockChargeoffCascade:
    def test_clock_crossing_deadline_chargeoff_cascade_writes_down(self, api):
        """PRD §3.10: "When a property exhausts its time, charge-off arrives by
        one of two paths... Either path runs the same cascade. First, an
        auto-generated write-down is created already POSTED, with amount equal
        to the property's current carrying_value, reason REGULATORY_CHARGE_OFF,
        auto_generated true, and proposed_by_user_id system. Second, that
        posting appends a CHARGE_OFF ledger entry carrying the negative of the
        carrying value and drives carrying_value to 0.00."

        Design: Difficulty/transitive_cascade/clock_crossing_deadline_chargeoff_cascade
        """
        ctx = create_marketed_property(listing_end="2032-06-05")
        prop = ctx["property"]
        # advance past holding_deadline (2031-05-09)
        set_clock("2031-05-10T00:00:00Z")
        after = get_property(prop["id"])
        assert after["lifecycle_status"] == "CHARGED_OFF"
        assert after["carrying_value"] == 0.00

        # auto-generated POSTED write-down of full carrying balance
        wds = list_write_downs(prop["id"])
        chargeoff_wds = [w for w in wds if w["reason"] == "REGULATORY_CHARGE_OFF"]
        assert len(chargeoff_wds) == 1
        wd = chargeoff_wds[0]
        assert wd["status"] == "POSTED"
        assert wd["amount"] == 368000.00
        assert wd["auto_generated"] is True

        # CHARGE_OFF ledger entry of -368000
        entries = list_ledger_entries(prop["id"])
        co_entries = [e for e in entries if e["entry_type"] == "CHARGE_OFF"]
        assert len(co_entries) == 1
        assert co_entries[0]["amount"] == -368000.00

    def test_clock_crossing_deadline_chargeoff_cascade_fans_out(self, api):
        """PRD §3.10: "Third, every ACTIVE listing agreement on the property
        moves to TERMINATED with termination_reason CHARGE_OFF — DRAFT
        agreements are left untouched. Fourth, every offer on the property in
        RECEIVED, UNDER_REVIEW, or COUNTERED moves to REJECTED with
        rejection_reason PROPERTY_CHARGED_OFF".

        Design: Difficulty/transitive_cascade/clock_crossing_deadline_chargeoff_cascade
        """
        setup_approval_tiers()
        ctx = create_marketed_property(listing_end="2032-06-05")
        prop = ctx["property"]
        listing = ctx["listing"]
        offer = create_offer_under_review(
            prop["id"],
            prop["version"],
            offer_price=450000.00,
            listing_agreement_id=listing["id"],
        )
        set_clock("2031-05-10T00:00:00Z")
        # listing -> TERMINATED/CHARGE_OFF
        l_after = get_listing(listing["id"])
        assert l_after["status"] == "TERMINATED"
        assert l_after["termination_reason"] == "CHARGE_OFF"
        # offer -> REJECTED/PROPERTY_CHARGED_OFF
        o_after = get_offer(offer["id"])
        assert o_after["status"] == "REJECTED"
        assert o_after["rejection_reason"] == "PROPERTY_CHARGED_OFF"


class TestValidationPriorityLadder:
    def test_state_vs_fiscal_on_chargedoff_lowball_accept(self, api):
        """PRD §2.8: "the first applicable rule along a fixed priority ladder
        is the one reported. The ladder is evaluated in this order: ... then
        state-machine preconditions... then ... and finally, on offer
        acceptance only, the fiscal gates in their own sub-order — the
        pending-write-down block (ERR_WRITE_DOWN_PENDING) first, then the
        positive-net-proceeds floor (ERR_BELOW_MIN_PROCEEDS), then
        approval-authority rank including the deep-discount override
        (ERR_APPROVAL_AUTHORITY_EXCEEDED)."
        PRD §3.5: "Any submit-review, counter, resume, accept, reject, or
        withdraw attempted on an offer not in a legal from-state for that
        action is rejected with ERR_OFFER_NOT_REVIEWABLE (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_chargedoff_lowball_accept
        """
        setup_approval_tiers()
        ctx = create_marketed_property(listing_end="2032-06-05")
        prop = ctx["property"]
        listing = ctx["listing"]
        # lowball offer: net_proceeds will be negative once accepted (fiscal violation)
        offer = create_offer_under_review(
            prop["id"],
            prop["version"],
            offer_price=2000.00,
            listing_agreement_id=listing["id"],
            buyer_name="Lowball LLC",
            earnest_money=100.00,
        )
        # charge off -> cascade-rejects the offer
        set_clock("2031-05-10T00:00:00Z")
        assert get_property(prop["id"])["lifecycle_status"] == "CHARGED_OFF"
        assert get_offer(offer["id"])["status"] == "REJECTED"
        # now accept: violates both state (REJECTED) and fiscal (net -620).
        # state error must win per the priority ladder.
        resp = api.accept_offer(offer["id"], CO)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_REVIEWABLE)

    def test_state_vs_fiscal_priority_lowball_offer_state_unchanged_after_error(self, api):
        """PRD §3.5: "Any submit-review, counter, resume, accept, reject, or
        withdraw attempted on an offer not in a legal from-state for that
        action is rejected with ERR_OFFER_NOT_REVIEWABLE (HTTP 409)." and the
        cascade from §3.10 leaves the offer REJECTED with no further mutation
        when a subsequent accept is rejected.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_chargedoff_lowball_accept
        """
        setup_approval_tiers()
        ctx = create_marketed_property(listing_end="2032-06-05")
        prop = ctx["property"]
        listing = ctx["listing"]
        offer = create_offer_under_review(
            prop["id"],
            prop["version"],
            offer_price=2000.00,
            listing_agreement_id=listing["id"],
            buyer_name="Lowball LLC",
            earnest_money=100.00,
        )
        set_clock("2031-05-10T00:00:00Z")
        api.accept_offer(offer["id"], CO)  # -> ERR_OFFER_NOT_REVIEWABLE
        # offer state unchanged (still REJECTED), property still CHARGED_OFF
        assert get_offer(offer["id"])["status"] == "REJECTED"
        assert get_offer(offer["id"])["rejection_reason"] == "PROPERTY_CHARGED_OFF"
        assert get_property(prop["id"])["lifecycle_status"] == "CHARGED_OFF"

    def test_safety_vs_temporal_on_closing_create(self, api):
        """PRD §2.8: "then the environmental safety gate
        (ERR_ENVIRONMENTAL_ISSUE_OPEN); then temporal rules
        (ERR_LISTING_OVERLAP, ERR_EFFECTIVE_DATE_IN_FUTURE,
        ERR_CLOSING_BEYOND_DEADLINE, ERR_EXTENSION_CAP_EXCEEDED)" — safety is
        evaluated before temporal.
        PRD §3.7: "no ENVIRONMENTAL issue may be open or in remediation
        (ERR_ENVIRONMENTAL_ISSUE_OPEN)" and "the closing_date must be on or
        before the property's holding_deadline (otherwise
        ERR_CLOSING_BEYOND_DEADLINE, HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_closing_create
        """
        # property UNDER_CONTRACT via accepted offer; then add ENV issue
        ctx = setup_property_with_accepted_offer(listing_end="2032-06-05")
        prop = ctx["property"]
        # add ENV issue after acceptance (acceptance already passed the env gate)
        api.create_issue(
            create_issue_payload(
                property_id=prop["id"],
                issue_type="ENVIRONMENTAL",
                severity="HIGH",
                description="Underground storage tank",
            ),
            PM,
        )
        # advance clock near (but not past) deadline so no charge-off
        set_clock("2031-05-01T00:00:00Z")
        # attempt closing with closing_date beyond deadline AND open env issue
        resp = api.create_closing_statement(
            {"offer_id": ctx["offer"]["id"], "closing_date": "2031-06-01"}, SPEC
        )
        validate_error(resp, ApiErrorId.ERR_ENVIRONMENTAL_ISSUE_OPEN)

    def test_safety_vs_temporal_no_closing_row_created(self, api):
        """PRD §2.8: "then the environmental safety gate
        (ERR_ENVIRONMENTAL_ISSUE_OPEN); then temporal rules
        (ERR_LISTING_OVERLAP, ERR_EFFECTIVE_DATE_IN_FUTURE,
        ERR_CLOSING_BEYOND_DEADLINE, ERR_EXTENSION_CAP_EXCEEDED)".
        PRD §3.7: Closing creation is blocked; the failed call must not leave
        a ClosingStatement row.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_on_closing_create
        """
        ctx = setup_property_with_accepted_offer(listing_end="2032-06-05")
        prop = ctx["property"]
        api.create_issue(
            create_issue_payload(
                property_id=prop["id"],
                issue_type="ENVIRONMENTAL",
                severity="HIGH",
                description="Underground storage tank",
            ),
            PM,
        )
        set_clock("2031-05-01T00:00:00Z")
        api.create_closing_statement(
            {"offer_id": ctx["offer"]["id"], "closing_date": "2031-06-01"}, SPEC
        )
        # no ClosingStatement for the offer
        list_resp = api.list_closing_statements(
            ADMIN, params={"offer_id": ctx["offer"]["id"]}
        )
        from test_helpers import validate_paginated

        data, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 0

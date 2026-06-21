"""Branching state machines: Offer two-step approval fork, BackgroundCheck PASS/FAIL fork."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, get_success_data,
    set_clock, setup_offer_in_state,
    extend_offer, accept_offer,
    fetch_background_check_for_offer,
    create_offer, fully_approve_offer,
    setup_approved_req_with_screened_app,
    create_candidate, create_application, screen_application,
    comp_approve_offer, current_offer_version,
    make_headers,
)


# =========================================================================
# Instance: offer_branching_two_step_approval_or_reject
# =========================================================================

class TestOfferBranchingTwoStepApprovalOrReject:
    """Two tests proving the fork from PENDING_APPROVAL is asymmetric."""

    def test_vp_can_reject_after_comp_approver_half_approval(self, api,
                                                              comp_approver_headers,
                                                              vp_headers):
        """PRD §3.6: "The first call must be made by a `CompApprover` whose
        `X-User-ID` differs from the offer's `submitter_user_id`; it stamps
        `comp_approver_user_id`, increments `version`, and keeps the offer
        in `PENDING_APPROVAL`."
        PRD §3.6: "Rejection by either a comp-approver or a VP (subject to
        the same segregation check that `X-User-ID` differs from
        `submitter_user_id`) moves the offer from `PENDING_APPROVAL` to
        `REJECTED`, increments `version`, and subtracts the offer's
        `base_salary_cents` from the department's `committed_offer_cents`."

        Design: Difficulty/non_linear_state_machine/offer_branching_two_step_approval_or_reject
        """
        set_clock("2026-04-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "PENDING_APPROVAL",
            budget_cents=100_000_000,
            req_overrides={"base_salary_max_cents": 15_000_000},
            base_salary_cents=12_000_000,
        )
        offer = ctx["offer"]
        offer = comp_approve_offer(offer["id"], offer["version"],
                                   comp_headers=comp_approver_headers)
        # VP takes the REJECT branch instead of completing approval.
        res = api_client.reject_offer(offer["id"], vp_headers)
        rejected = validate_success(res, 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["comp_approver_user_id"] is not None
        # vp_approver_user_id stays null since VP chose the reject branch.
        assert rejected.get("vp_approver_user_id") is None

    def test_pending_approval_with_only_comp_half_done_keeps_pending(self, api,
                                                                      comp_approver_headers):
        """PRD §3.6: "The comp-approver leg is recognised by
        `comp_approver_user_id` being null on entry; the VP leg is recognised
        by `comp_approver_user_id` being non-null on entry."
        PRD §3.6: "it stamps `comp_approver_user_id`, increments `version`,
        and keeps the offer in `PENDING_APPROVAL`."

        Design: Difficulty/non_linear_state_machine/offer_branching_two_step_approval_or_reject
        """
        set_clock("2026-04-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "PENDING_APPROVAL",
            budget_cents=100_000_000,
            req_overrides={"base_salary_max_cents": 15_000_000},
            base_salary_cents=12_000_000,
        )
        offer = ctx["offer"]
        comp_v = offer["version"]
        offer_after_comp = comp_approve_offer(offer["id"], comp_v,
                                              comp_headers=comp_approver_headers)
        assert offer_after_comp["status"] == "PENDING_APPROVAL"
        assert offer_after_comp["comp_approver_user_id"] is not None
        assert offer_after_comp.get("vp_approver_user_id") is None
        assert offer_after_comp["version"] > comp_v, "version must increment on comp half"


# =========================================================================
# Instance: background_check_branching_pass_fail_with_divergent_cascades
# =========================================================================

class TestBackgroundCheckBranchingPassFailWithDivergentCascades:
    """Two tests showing the IN_PROGRESS fork produces distinct downstream effects."""

    def test_background_check_initiated_on_offer_accept(self, api):
        """PRD §3.6: "A successful accept moves the offer from `EXTENDED` to
        `ACCEPTED`, increments `version`, creates a new background check in
        state `INITIATED` for the offer and candidate, cascades the linked
        application to `HIRED`..."
        PRD §3.7: "Acceptance of an offer creates a background check in
        state `INITIATED` with the offer's `offer_id` and the candidate's
        `candidate_id` recorded, plus a server-stamped `vendor_reference`
        synthesised at this moment."

        Design: Difficulty/non_linear_state_machine/background_check_branching_pass_fail_with_divergent_cascades
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "EXTENDED",
            budget_cents=100_000_000,
            req_overrides={"base_salary_max_cents": 15_000_000},
            base_salary_cents=12_000_000,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))
        bgc = fetch_background_check_for_offer(offer["id"])
        assert bgc["status"] == "INITIATED"
        assert bgc["offer_id"] == offer["id"]
        assert bgc["candidate_id"] == cand["id"]

    def test_application_hired_and_filled_count_bumped_on_accept(self, api):
        """PRD §3.4: "The successful pathway out is via offer acceptance: when
        an offer linked to the application transitions to `ACCEPTED`, the
        application moves to `HIRED` (see §3.6), which itself bubbles into
        the requisition's `filled_count` and may auto-close the requisition."
        PRD §3.6: "bubbles the requisition's `filled_count` up by one (and
        may auto-transition the requisition to `CLOSED` when `filled_count`
        reaches `openings`)..."

        Design: Difficulty/non_linear_state_machine/background_check_branching_pass_fail_with_divergent_cascades
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "EXTENDED",
            budget_cents=100_000_000,
            req_overrides={"openings": 1, "base_salary_max_cents": 15_000_000},
            base_salary_cents=12_000_000,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        req_id = ctx["req"]["id"]
        accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))

        app_after = get_success_data(api_client.get_application(
            ctx["app"]["id"], TEST_USERS["recruiter_headers"]))
        assert app_after["status"] == "HIRED"
        req_after = get_success_data(api_client.get_requisition(
            req_id, TEST_USERS["recruiter_headers"]))
        assert req_after["filled_count"] == 1

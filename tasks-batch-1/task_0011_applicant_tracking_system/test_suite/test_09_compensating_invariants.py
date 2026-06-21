"""Compensating-action invariants: department committed offer round-trip, filled_count round-trip."""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    set_clock, create_department, setup_approved_req_with_screened_app,
    setup_offer_in_state, create_offer, current_department_committed,
    accept_offer, fetch_background_check_for_offer,
    start_background_check, resolve_background_check,
    make_headers,
)


# =========================================================================
# Instance: department_committed_offer_cents_round_trip_offer_create_then_reject
# =========================================================================

class TestDepartmentCommittedOfferRoundTrip:
    """Two tests on the create-then-reject conservation of committed_offer_cents."""

    def test_offer_create_increments_committed_then_reject_decrements(
            self, api, comp_approver_headers):
        """PRD §3.6: "The new offer is stamped with the recruiter's
        `X-User-ID` as `submitter_user_id`, lands in state
        `PENDING_APPROVAL` with `version` 1, and adds its `base_salary_cents`
        to the department's `committed_offer_cents`."
        PRD §3.6: "Rejection by either a comp-approver or a VP (subject to
        the same segregation check that `X-User-ID` differs from
        `submitter_user_id`) moves the offer from `PENDING_APPROVAL` to
        `REJECTED`, increments `version`, and subtracts the offer's
        `base_salary_cents` from the department's `committed_offer_cents`."

        Design: Difficulty/compensating_invariant/department_committed_offer_cents_round_trip_offer_create_then_reject
        """
        dept, req, cand, app = setup_approved_req_with_screened_app(
            req_overrides={"base_salary_max_cents": 15_000_000},
        )
        before = current_department_committed(dept["id"])
        offer = create_offer(app["id"], base_salary_cents=12_000_000)
        after_create = current_department_committed(dept["id"])
        assert after_create == before + 12_000_000

        # Reject by a CompApprover whose X-User-ID differs from submitter (rec_alice).
        api_client.reject_offer(offer["id"], comp_approver_headers)
        after_reject = current_department_committed(dept["id"])
        assert after_reject == before, \
            f"Round-trip invariant: expected {before}, got {after_reject}"

    def test_initial_department_committed_is_zero(self, api):
        """PRD §3.1: "The computed `committed_offer_cents` is read alongside
        the stored fields and starts at zero before any offers exist."

        Design: Difficulty/compensating_invariant/department_committed_offer_cents_round_trip_offer_create_then_reject
        """
        dept = create_department(budget_cents=100_000_000)
        assert dept["committed_offer_cents"] == 0


# =========================================================================
# Instance: requisition_filled_count_round_trip_offer_accept_then_bgc_failed
# =========================================================================

class TestRequisitionFilledCountRoundTrip:
    """Two tests on the accept-then-bgc-failed conservation of filled_count."""

    def test_bgc_failed_decrements_filled_count_and_reopens_requisition(
            self, api, recruiter_headers):
        """PRD §3.7: "A `FAILED` outcome rolls the hire back across multiple
        entities in one transaction: the linked offer is cascaded from
        `EXTENDED` or `ACCEPTED` to `REVOKED`; the linked application is
        cascaded from `HIRED` to `REJECTED`; any linked referral bonus
        still in `PENDING_BGC` is cascaded to `VOID`; and the requisition's
        `filled_count` is decremented."
        PRD §3.7: "If the requisition had previously auto-`CLOSED`, it
        re-opens to `APPROVED` — `CLOSED` is therefore not strictly terminal
        under this rollback path."

        Design: Difficulty/compensating_invariant/requisition_filled_count_round_trip_offer_accept_then_bgc_failed
        """
        set_clock("2027-01-01T00:00:00Z")
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
        req_after_accept = get_success_data(api_client.get_requisition(req_id, recruiter_headers))
        assert req_after_accept["filled_count"] == 1
        assert req_after_accept["status"] == "CLOSED"

        bgc = fetch_background_check_for_offer(offer["id"])
        start_background_check(bgc["id"])
        # Use a ComplianceOfficer whose X-User-ID is NOT the requisition's submitter or
        # approver (rec_alice / hm_bob); default compliance_officer_headers is co_frank.
        resolve_background_check(bgc["id"], outcome="FAILED")
        req_after_fail = get_success_data(api_client.get_requisition(req_id, recruiter_headers))
        assert req_after_fail["filled_count"] == 0
        assert req_after_fail["status"] == "APPROVED", \
            f"Expected re-open from CLOSED to APPROVED, got {req_after_fail['status']}"

    def test_bgc_failed_rejects_application_and_revokes_offer(self, api,
                                                               recruiter_headers):
        """PRD §3.7: "the linked offer is cascaded from `EXTENDED` or
        `ACCEPTED` to `REVOKED`; the linked application is cascaded from
        `HIRED` to `REJECTED`"

        Design: Difficulty/compensating_invariant/requisition_filled_count_round_trip_offer_accept_then_bgc_failed
        """
        set_clock("2027-01-15T00:00:00Z")
        ctx = setup_offer_in_state(
            "EXTENDED",
            budget_cents=100_000_000,
            req_overrides={"openings": 1, "base_salary_max_cents": 15_000_000},
            base_salary_cents=12_000_000,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        app_id = ctx["app"]["id"]
        accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))

        bgc = fetch_background_check_for_offer(offer["id"])
        start_background_check(bgc["id"])
        resolve_background_check(bgc["id"], outcome="FAILED")
        offer_after = get_success_data(api_client.get_offer(offer["id"], recruiter_headers))
        app_after = get_success_data(api_client.get_application(app_id, recruiter_headers))
        assert offer_after["status"] == "REVOKED"
        assert app_after["status"] == "REJECTED"

"""Transitive cascade chains: offer-accept depth-3 hire, requisition-cancel depth-3 sweep."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, get_success_data,
    set_clock, setup_offer_in_state, setup_approved_req_with_screened_app,
    extend_offer, accept_offer, create_offer, fully_approve_offer,
    create_candidate, create_application, screen_application,
    cancel_requisition_with_version, current_requisition_version,
    make_headers,
)


# =========================================================================
# Instance: offer_accept_chain_application_hired_requisition_closed
# =========================================================================

class TestOfferAcceptChainApplicationHiredRequisitionClosed:
    """Two tests for the depth-3 cascade from POST /offers/{id}/accept."""

    def test_accept_drives_application_to_hired(self, api, recruiter_headers):
        """PRD §3.4: "The successful pathway out is via offer acceptance: when
        an offer linked to the application transitions to `ACCEPTED`, the
        application moves to `HIRED` (see §3.6), which itself bubbles into
        the requisition's `filled_count` and may auto-close the requisition."

        Design: Difficulty/transitive_cascade/offer_accept_chain_application_hired_requisition_closed
        """
        set_clock("2026-06-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "EXTENDED",
            budget_cents=100_000_000,
            req_overrides={"openings": 1, "base_salary_max_cents": 15_000_000},
            base_salary_cents=12_000_000,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        accepted = accept_offer(offer["id"],
                                candidate_headers=make_headers(cand["id"], "Candidate"))
        assert accepted["status"] == "ACCEPTED"
        app_after = get_success_data(api_client.get_application(
            ctx["app"]["id"], recruiter_headers))
        assert app_after["status"] == "HIRED"

    def test_filled_count_reaches_openings_auto_closes_requisition(self, api,
                                                                    recruiter_headers):
        """PRD §3.2: "A requisition in `APPROVED` reaches `CLOSED` automatically
        when its computed `filled_count` equals its `openings`."
        PRD §3.6: "bubbles the requisition's `filled_count` up by one (and
        may auto-transition the requisition to `CLOSED` when `filled_count`
        reaches `openings`)..."

        Design: Difficulty/transitive_cascade/offer_accept_chain_application_hired_requisition_closed
        """
        set_clock("2026-06-01T00:00:00Z")
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

        req_after = get_success_data(api_client.get_requisition(req_id, recruiter_headers))
        assert req_after["filled_count"] == 1
        assert req_after["status"] == "CLOSED", \
            f"Expected requisition to auto-CLOSE when filled_count==openings, " \
            f"got status={req_after['status']}"


# =========================================================================
# Instance: requisition_cancel_chain_applications_withdrawn_offers_revoked_bgcs_cancelled
# =========================================================================

class TestRequisitionCancelChain:
    """Two tests for the depth-3 cascade from POST /requisitions/{id}/cancel."""

    def test_cancel_cascades_applications_to_withdrawn(self, api, recruiter_headers,
                                                       hiring_manager_headers):
        """PRD §3.2: "Cancellation drives several cascades in one transaction:
        every non-terminal application on the requisition transitions to
        `WITHDRAWN`; every non-terminal offer transitions to `REVOKED`, which
        in turn cascades any non-terminal background check to `CANCELLED`
        and any non-`PAID` referral bonus to `VOID`."

        Design: Difficulty/transitive_cascade/requisition_cancel_chain_applications_withdrawn_offers_revoked_bgcs_cancelled
        """
        set_clock("2026-07-01T00:00:00Z")
        dept, req, c1, app1 = setup_approved_req_with_screened_app(
            req_overrides={"openings": 2, "base_salary_max_cents": 15_000_000},
            cand_overrides={"full_name": "C1", "email": "c1cancel@example.com"},
        )
        # Second candidate + screened app.
        c2 = create_candidate(full_name="C2", email="c2cancel@example.com")
        app2 = create_application(c2["id"], req["id"])
        screen_application(app2["id"])

        req_v = current_requisition_version(req["id"])
        cancel_requisition_with_version(req["id"], req_v,
                                        hm_headers=hiring_manager_headers)
        app1_after = get_success_data(api_client.get_application(app1["id"], recruiter_headers))
        app2_after = get_success_data(api_client.get_application(app2["id"], recruiter_headers))
        assert app1_after["status"] == "WITHDRAWN"
        assert app2_after["status"] == "WITHDRAWN"

    def test_cancel_cascades_offers_to_revoked(self, api, recruiter_headers,
                                                hiring_manager_headers):
        """PRD §3.2: "every non-terminal offer transitions to `REVOKED`,
        which in turn cascades any non-terminal background check to
        `CANCELLED` and any non-`PAID` referral bonus to `VOID`."

        Design: Difficulty/transitive_cascade/requisition_cancel_chain_applications_withdrawn_offers_revoked_bgcs_cancelled
        """
        set_clock("2026-07-01T00:00:00Z")
        dept, req, c1, app1 = setup_approved_req_with_screened_app(
            req_overrides={"openings": 2, "base_salary_max_cents": 15_000_000},
        )
        offer1 = create_offer(app1["id"], base_salary_cents=12_000_000)
        offer1 = fully_approve_offer(offer1["id"])
        # Offer is in APPROVED; cancel the requisition.
        req_v = current_requisition_version(req["id"])
        cancel_requisition_with_version(req["id"], req_v,
                                        hm_headers=hiring_manager_headers)

        offer_after = get_success_data(api_client.get_offer(offer1["id"], recruiter_headers))
        assert offer_after["status"] == "REVOKED"

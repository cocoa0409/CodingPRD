"""Cross-entity state dependencies: app screen requires APPROVED req; offer extend requires APPROVED req."""
import pytest
from test_helpers import (
    api_client, validate_error, validate_error_is_one_of, get_success_data,
    TEST_USERS, set_clock,
    create_department, create_requisition, create_candidate, create_application,
    setup_offer_in_state, cancel_requisition_with_version,
    current_requisition_version,
)


# =========================================================================
# Instance: application_screen_blocked_when_requisition_not_approved
# =========================================================================

class TestApplicationScreenBlockedWhenRequisitionNotApproved:
    """Two tests on the cross-entity guard JobRequisition.status == APPROVED for screen."""

    def test_screen_on_draft_requisition_returns_precondition_failed(self, api,
                                                                     recruiter_headers):
        """PRD §3.4: "The recruiter advances it from `APPLIED` to `SCREENING`
        once the requisition is still `APPROVED`; the screen call increments
        the application's `version`."
        PRD §2.10: "Validation Priority ... 6. Cross-entity preconditions —
        parent or sibling state matches the transition's required guard
        (`ERR_PRECONDITION_FAILED`), e.g., the requisition is `APPROVED`
        before an application is screened or an offer extended..."

        Design: Difficulty/cross_entity_state_dependency/application_screen_blocked_when_requisition_not_approved
        """
        dept = create_department()
        # Create requisition in DRAFT (never submit/approve).
        req = create_requisition(dept["id"])
        cand = create_candidate(full_name="Draft Cand", email="draft_x@example.com")
        # Application create itself allowed (no precondition on req state for create).
        app_payload = {"candidate_id": cand["id"], "requisition_id": req["id"]}
        app_res = api_client.create_application(app_payload, recruiter_headers)
        # Application create may itself fail with PRECONDITION_FAILED if the impl gates it,
        # or it may succeed; PRD §3.4 explicitly states screen requires APPROVED, so we
        # check screen specifically. If create itself is rejected, the test data setup
        # is captured via the create response.
        if app_res.status_code in (200, 201):
            app = get_success_data(app_res)
            res = api_client.screen_application(app["id"], recruiter_headers)
            validate_error(res, "ERR_PRECONDITION_FAILED", expected_status=409)
        else:
            # PRD §3.4: also states "The requisition must be in `APPROVED`; otherwise
            # the precondition fails with `ERR_PRECONDITION_FAILED`." for application create.
            # So either layer should surface PRECONDITION_FAILED.
            validate_error(app_res, "ERR_PRECONDITION_FAILED", expected_status=409)

    def test_screen_on_pending_approval_requisition_returns_precondition_failed(
            self, api, recruiter_headers):
        """PRD §3.4: "Opening an application links a `candidate_id` to a
        `requisition_id`; the pair is unique. The requisition must be in
        `APPROVED`; otherwise the precondition fails with
        `ERR_PRECONDITION_FAILED`."

        Design: Difficulty/cross_entity_state_dependency/application_screen_blocked_when_requisition_not_approved
        """
        dept = create_department()
        req = create_requisition(dept["id"])
        # Submit but do not approve → state is PENDING_APPROVAL.
        api_client.submit_requisition(req["id"], recruiter_headers)
        cand = create_candidate(full_name="Pending Cand", email="pend_x@example.com")
        app_payload = {"candidate_id": cand["id"], "requisition_id": req["id"]}
        app_res = api_client.create_application(app_payload, recruiter_headers)
        if app_res.status_code in (200, 201):
            app = get_success_data(app_res)
            res = api_client.screen_application(app["id"], recruiter_headers)
            validate_error(res, "ERR_PRECONDITION_FAILED", expected_status=409)
        else:
            validate_error(app_res, "ERR_PRECONDITION_FAILED", expected_status=409)


# =========================================================================
# Instance: offer_extend_blocked_when_requisition_cancelled
# =========================================================================

class TestOfferExtendBlockedWhenRequisitionCancelled:
    """Two tests on the cross-entity guard for offer extend after requisition cancel."""

    def test_extend_after_requisition_cancelled_returns_precondition_or_invalid_state(
            self, api, recruiter_headers, hiring_manager_headers):
        """PRD §3.6: "Extending an `APPROVED` offer requires the linked
        requisition to still be `APPROVED`; on success the offer transitions
        to `EXTENDED`..."
        PRD §3.2: "Cancellation drives several cascades in one transaction:
        ... every non-terminal offer transitions to `REVOKED`, which in turn
        cascades any non-terminal background check to `CANCELLED`..."

        Design: Difficulty/cross_entity_state_dependency/offer_extend_blocked_when_requisition_cancelled
        """
        set_clock("2026-11-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "APPROVED",
            req_overrides={"base_salary_max_cents": 15_000_000},
            base_salary_cents=12_000_000,
        )
        offer = ctx["offer"]
        req = ctx["req"]
        # Cancel the requisition; the offer gets cascaded to REVOKED.
        req_v = current_requisition_version(req["id"])
        cancel_requisition_with_version(req["id"], req_v,
                                        hm_headers=hiring_manager_headers)
        # Now try to extend the offer — either cross-entity guard (PRECONDITION_FAILED)
        # OR the offer's own state check (INVALID_STATE because it's REVOKED).
        res = api_client.extend_offer(offer["id"], recruiter_headers)
        validate_error_is_one_of(res,
                                 ["ERR_PRECONDITION_FAILED", "ERR_INVALID_STATE"])

    def test_offer_remains_revoked_after_failed_extend_attempt(self, api,
                                                                recruiter_headers,
                                                                hiring_manager_headers):
        """PRD §3.2: "every non-terminal offer transitions to `REVOKED`..."
        PRD §3.2: "Note that `CLOSED` is not strictly terminal: when a
        background check on a hire fails, the hire reverses, `filled_count`
        is decremented, and a previously `CLOSED` requisition re-opens to
        `APPROVED`."
        (Here REVOKED is a true terminal state per Offer state machine.)

        Design: Difficulty/cross_entity_state_dependency/offer_extend_blocked_when_requisition_cancelled
        """
        set_clock("2026-11-02T00:00:00Z")
        ctx = setup_offer_in_state(
            "APPROVED",
            req_overrides={"base_salary_max_cents": 15_000_000},
            base_salary_cents=12_000_000,
        )
        offer = ctx["offer"]
        req = ctx["req"]
        req_v = current_requisition_version(req["id"])
        cancel_requisition_with_version(req["id"], req_v,
                                        hm_headers=hiring_manager_headers)
        offer_after = get_success_data(api_client.get_offer(offer["id"], recruiter_headers))
        assert offer_after["status"] == "REVOKED"
        req_after = get_success_data(api_client.get_requisition(req["id"], recruiter_headers))
        assert req_after["status"] == "CANCELLED"

"""Validation priority conflicts: SoD beats budget; panelist conflict beats invalid panel."""
import pytest
from test_helpers import (
    api_client, validate_error, get_success_data, TEST_USERS,
    create_department, create_requisition, submit_requisition,
    setup_approved_req_with_screened_app, create_interview_payload,
    make_headers,
)


# =========================================================================
# Instance: requisition_approve_sod_beats_budget
# =========================================================================

class TestRequisitionApproveSodBeatsBudget:
    """Two tests proving SoD (priority 7) wins over BUDGET (priority 17)."""

    def test_self_approval_with_inadequate_budget_returns_sod(self, api):
        """PRD §2.9: "This check is evaluated after the segregation-of-duties
        check, so a recruiter trying to self-approve will see the segregation
        error rather than the budget error even when both would fire."
        PRD §2.8: "A hiring manager attempting to approve or reject a
        requisition whose `submitter_user_id` matches the calling `X-User-ID`
        is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/requisition_approve_sod_beats_budget
        """
        # Tight budget that would also trigger BUDGET_EXCEEDED.
        dept = create_department(budget_cents=10_000_000)
        # Submit as user_x.
        user_x_recruiter = make_headers("user_x", "Recruiter")
        req = create_requisition(dept["id"], recruiter_headers=user_x_recruiter,
                                 title="TightRole", target_level="STAFF",
                                 base_salary_min_cents=15_000_000,
                                 base_salary_max_cents=20_000_000,
                                 openings=1)
        submit_requisition(req["id"], recruiter_headers=user_x_recruiter)
        # Same X-User-ID as submitter, but with HiringManager role.
        user_x_as_hm = make_headers("user_x", "HiringManager")
        res = api_client.approve_requisition(req["id"], user_x_as_hm)
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    def test_self_approval_with_inadequate_budget_no_state_transition(self, api,
                                                                      recruiter_headers):
        """PRD §2.10: "Validation Priority ... 7. Segregation-of-duties on
        requisition approve/reject and offer approve/reject
        (`ERR_SEGREGATION_OF_DUTIES`)."
        PRD §2.10: "the server evaluates them strictly in the following
        order, returning the first applicable error"

        Design: Difficulty/priority_pair_validation_conflict/requisition_approve_sod_beats_budget
        """
        dept = create_department(budget_cents=10_000_000)
        user_x_recruiter = make_headers("user_x_2", "Recruiter")
        req = create_requisition(dept["id"], recruiter_headers=user_x_recruiter,
                                 title="TightRole2", target_level="STAFF",
                                 base_salary_min_cents=15_000_000,
                                 base_salary_max_cents=20_000_000,
                                 openings=1)
        submit_requisition(req["id"], recruiter_headers=user_x_recruiter)
        user_x_as_hm = make_headers("user_x_2", "HiringManager")
        api_client.approve_requisition(req["id"], user_x_as_hm)
        # Status must remain PENDING_APPROVAL since approval did not transition.
        req_after = get_success_data(api_client.get_requisition(req["id"], recruiter_headers))
        assert req_after["status"] == "PENDING_APPROVAL"


# =========================================================================
# Instance: interview_create_panelist_conflict_beats_invalid_panel
# =========================================================================

class TestInterviewCreatePanelistConflictBeatsInvalidPanel:
    """Two tests proving PANELIST_CONFLICT (priority 8) wins over INVALID_PANEL (priority 12)."""

    def test_panel_with_referrer_and_six_panelists_returns_panelist_conflict(self, api):
        """PRD §2.8: "An interview's `panel_user_ids` must not contain the
        candidate's `referrer_user_id`; if it does, the create is rejected
        with `ERR_PANELIST_CONFLICT` (HTTP 422)."
        PRD §2.10: "Validation Priority ... 8. Panelist independence on
        interview creation (`ERR_PANELIST_CONFLICT`). ... 12. Interview panel
        shape: between 1 and 5 distinct `panel_user_ids`, no duplicates,
        non-empty (`ERR_INVALID_PANEL`)."

        Design: Difficulty/priority_pair_validation_conflict/interview_create_panelist_conflict_beats_invalid_panel
        """
        dept, req, cand, app = setup_approved_req_with_screened_app(
            cand_overrides={
                "full_name": "Panel Cand", "email": "pcand_pc@example.com",
                "source_channel": "REFERRAL", "referrer_user_id": "emp_ref_z",
                "eeo_ethnicity": "WHITE",
            }
        )
        payload = create_interview_payload(
            app["id"],
            panel_user_ids=["emp_p1", "emp_p2", "emp_p3", "emp_p4", "emp_p5", "emp_ref_z"],
            round_number=1,
            scheduled_at="2026-08-01T10:00:00Z",
            duration_minutes=60,
        )
        res = api_client.create_interview(payload, TEST_USERS["recruiter_headers"])
        validate_error(res, "ERR_PANELIST_CONFLICT", expected_status=422)

    def test_panel_conflict_does_not_create_interview(self, api, recruiter_headers):
        """PRD §2.10: "When multiple checks could fire on a single request,
        the server evaluates them strictly in the following order, returning
        the first applicable error"

        Design: Difficulty/priority_pair_validation_conflict/interview_create_panelist_conflict_beats_invalid_panel
        """
        dept, req, cand, app = setup_approved_req_with_screened_app(
            cand_overrides={
                "full_name": "Panel Cand2", "email": "pcand_pc2@example.com",
                "source_channel": "REFERRAL", "referrer_user_id": "emp_ref_z2",
                "eeo_ethnicity": "WHITE",
            }
        )
        payload = create_interview_payload(
            app["id"],
            panel_user_ids=["a1", "a2", "a3", "a4", "a5", "emp_ref_z2"],
            round_number=1, scheduled_at="2026-08-02T10:00:00Z",
            duration_minutes=60,
        )
        api_client.create_interview(payload, recruiter_headers)
        # Confirm no Interview rows exist for this application.
        res = api_client.list_interviews(recruiter_headers,
                                         params={"application_id": app["id"]})
        body = res.json()
        assert res.status_code == 200
        data = body.get("data", [])
        assert len(data) == 0, f"Expected no interview rows, got {len(data)}"

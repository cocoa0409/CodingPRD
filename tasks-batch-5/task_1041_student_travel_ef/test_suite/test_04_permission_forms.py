"""Permission-form review cycle and state gating (queue-A rule 3 + corner)."""
from test_helpers import (
    validate_success, validate_error, OPERATOR,
    ApiErrorId,
    setup_permission_form_changes_requested, setup_open_departure,
    enroll, make_permission_form,
)


class TestPermissionFormRevisionCycle:
    """Design: Difficulty/non_linear_state_machine/permission_form_changes_requested_resubmit_cycle"""

    def test_resubmit_from_changes_requested_returns_to_submitted(self, api):
        """PRD §3.7: "From CHANGES_REQUESTED the traveler may resubmit — a revision loop
        that returns the form CHANGES_REQUESTED → SUBMITTED, again requiring guardian_consent
        to be true — and the cycle repeats until an operator approves."

        Design: Difficulty/non_linear_state_machine/permission_form_changes_requested_resubmit_cycle
        """
        ctx = setup_permission_form_changes_requested(api, clock="2026-08-18T00:00:00Z")
        assert ctx["permission_form"]["status"] == "CHANGES_REQUESTED"
        resubmitted = validate_success(api.submit_permission_form(ctx["permission_form"]["id"], OPERATOR))
        assert resubmitted["status"] == "SUBMITTED"

    def test_approve_after_resubmit_reaches_approved(self, api):
        """PRD §3.7: "Approval advances SUBMITTED → APPROVED and reconciles the enrollment's
        derived doc_complete flag to true".

        Design: Difficulty/non_linear_state_machine/permission_form_changes_requested_resubmit_cycle
        """
        ctx = setup_permission_form_changes_requested(api, clock="2026-08-18T00:00:00Z")
        validate_success(api.submit_permission_form(ctx["permission_form"]["id"], OPERATOR))
        approved = validate_success(
            api.review_permission_form(ctx["permission_form"]["id"], {"decision": "APPROVE"}, OPERATOR)
        )
        assert approved["status"] == "APPROVED"


def test_review_on_draft_form_returns_invalid_state(api):
    """PRD §3.7: "Submitting a form advances it DRAFT → SUBMITTED and requires that
    guardian_consent be true and that both passport_number and passport_expiry be present.
    Operator review then either approves or requests changes."
    PRD §2.9: "State legality is next: a resource that is not in a state permitting the
    requested transition yields ERR_INVALID_STATE (409) unless a more specific state error
    applies."

    Design: Corner/state_machines/permission_form_review_on_draft_returns_invalid_state
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z")
    enr = enroll(api, ctx["departure"]["id"], traveler_gender="FEMALE", traveler_name="Draft D")
    pf = make_permission_form(api, enr["id"], passport_number="Y7654321")  # created DRAFT, never submitted
    resp = api.review_permission_form(pf["id"], {"decision": "APPROVE"}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

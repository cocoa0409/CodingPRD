"""Review rounds, note consolidation, and approval preconditions."""

from test_helpers import (
    ApiErrorId, close_round_notes, create_review_note, create_review_round,
    setup_published_dailies, validate_error, validate_success,
)
from test_helpers.test_users import make_reviewer_lead_headers

RL = make_reviewer_lead_headers()


class TestReviewRoundApproval:
    def test_review_round_approve_with_unresolved_critical_returns_invalid_state(self, api):
        """PRD §3.6: "Approval then moves the round from `NOTES_CLOSED` to
        `APPROVED`, and is permitted only when `unresolved_critical` is false and
        `open_note_count` is zero — a round with any outstanding note, or any
        unresolved critical one, cannot be approved."
        PRD §2.9 item 6: "The target resource must currently be in the from-state
        required by the requested transition; otherwise `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/review_round_approve_with_unresolved_critical_returns_invalid_state
        """
        project, _batch, _assets, pkg = setup_published_dailies(
            project_overrides={"title": "P", "client_code": "CL203",
                               "storage_quota_gb": 100})
        rr = create_review_round(project["id"], "DAILIES", pkg["id"],
                                 round_label="RR-01")
        create_review_note(project["id"], rr["id"], severity="CRITICAL",
                           body="bad frame at 12")
        close_round_notes(project["id"], rr["id"])
        resp = api.approve_review_round(project["id"], rr["id"], RL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_review_round(project["id"], rr["id"], RL))
        assert after["status"] == "NOTES_CLOSED"

    def test_review_round_approve_succeeds_after_resolving_critical(self, api):
        """PRD §3.6: "Approval then moves the round from `NOTES_CLOSED` to
        `APPROVED`, and is permitted only when `unresolved_critical` is false and
        `open_note_count` is zero."
        PRD §3.6: "Resolution moves a note from `OPEN` or `ACKED` to `RESOLVED`,
        permitted while the parent round is `OPEN` or `NOTES_CLOSED`, and
        recomputes the parent round's `unresolved_critical` and
        `open_note_count`."

        Design: Corner/state_machines/review_round_approve_with_unresolved_critical_returns_invalid_state
        """
        project, _batch, _assets, pkg = setup_published_dailies(
            project_overrides={"title": "P", "client_code": "CL203",
                               "storage_quota_gb": 100})
        rr = create_review_round(project["id"], "DAILIES", pkg["id"],
                                 round_label="RR-01")
        note = create_review_note(project["id"], rr["id"], severity="CRITICAL",
                                  body="bad frame at 12")
        close_round_notes(project["id"], rr["id"])
        blocked = api.approve_review_round(project["id"], rr["id"], RL)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)
        # Resolve the critical note, then approval succeeds.
        from test_helpers.test_users import make_conform_editor_headers
        api.resolve_review_note(project["id"], note["id"],
                                make_conform_editor_headers())
        approved = validate_success(
            api.approve_review_round(project["id"], rr["id"], RL))
        assert approved["status"] == "APPROVED"

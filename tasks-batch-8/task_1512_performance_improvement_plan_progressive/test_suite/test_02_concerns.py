"""Concern state-machine claims: invalid transitions, terminal lockdown,
issuance cascade, and immediate consistency."""
import pytest

from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cast,
    create_coaching_entries,
    create_concern_payload,
    create_and_submit_concern,
    create_and_accept_concern,
    create_and_publish_template,
    create_draft_pip,
    create_and_issue_pip,
    setup_concern_and_template,
    make_manager_headers,
    make_hrbp_headers,
)


class TestConcernInvalidTransitions:
    def test_submit_already_submitted_concern_rejected(self, api):
        """PRD §3.2: "Four gates guard submission, each with its own rejection: the
        concern must still be `DRAFT` (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/concern_submit_from_submitted_returns_invalid_state
        """
        cast = setup_cast()
        entry_ids = create_coaching_entries(cast)
        concern = create_and_submit_concern(cast, entry_ids)
        resp = api.submit_concern(
            cast["ou_id"], cast["emp_id"], concern["id"],
            make_manager_headers(cast["mgr_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_accept_rejected_concern_rejected(self, api):
        """PRD §3.2: "Rejection moves the concern `SUBMITTED` →
        `REJECTED_INSUFFICIENT`, records the same decision fields, and terminates
        the concern."

        Design: Corner/state_machines/concern_terminal_lockdown_rejected_insufficient
        """
        cast = setup_cast()
        entry_ids = create_coaching_entries(cast)
        concern = create_and_submit_concern(cast, entry_ids)
        resp = api.reject_concern(
            cast["ou_id"], cast["emp_id"], concern["id"],
            make_hrbp_headers(cast["hrbp_id"]),
        )
        validate_success(resp)
        # REJECTED_INSUFFICIENT is terminal: accept must now fail.
        resp = api.accept_concern(
            cast["ou_id"], cast["emp_id"], concern["id"],
            make_hrbp_headers(cast["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPipIssuanceCascade:
    def test_issue_cascades_concern_supersede_and_active_pip(self, api):
        """PRD §3.3: "Issuance cascades outward: the concern flips to
        `SUPERSEDED_BY_PIP`, the employee's `active_pip_id` is set to the plan, and
        the plan's `version` increments."

        Design: Difficulty/transitive_cascade/concern_accept_cascades_coaching_entries_escalate_pip_issue_supersedes_concern
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)
        pip = create_draft_pip(cast, concern["id"], template["id"])
        hrbp_headers = make_hrbp_headers(cast["hrbp_id"])
        resp = api.issue_pip(
            cast["ou_id"], cast["emp_id"], pip["id"],
            {"expected_pip_version": pip["version"]},
            hrbp_headers,
        )
        issued = validate_success(resp)
        assert issued["status"] == "ISSUED"
        assert issued["version"] == pip["version"] + 1

        concern_after = get_success_data(
            api.get_concern(cast["ou_id"], cast["emp_id"], concern["id"], hrbp_headers)
        )
        assert concern_after["status"] == "SUPERSEDED_BY_PIP"

        emp_after = get_success_data(
            api.get_employee(cast["ou_id"], cast["emp_id"], hrbp_headers)
        )
        assert emp_after["active_pip_id"] == pip["id"]

    def test_issue_cascade_visible_in_immediate_followup_reads(self, api):
        """PRD §3.3: "Issuance cascades outward: the concern flips to
        `SUPERSEDED_BY_PIP`, the employee's `active_pip_id` is set to the plan, and
        the plan's `version` increments."

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_response
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)
        pip = create_draft_pip(cast, concern["id"], template["id"])
        hrbp_headers = make_hrbp_headers(cast["hrbp_id"])
        validate_success(api.issue_pip(
            cast["ou_id"], cast["emp_id"], pip["id"],
            {"expected_pip_version": pip["version"]},
            hrbp_headers,
        ))
        # Immediate follow-up GETs (no delay) must observe the cascaded state.
        concern_after = get_success_data(
            api.get_concern(cast["ou_id"], cast["emp_id"], concern["id"], hrbp_headers)
        )
        assert concern_after["status"] == "SUPERSEDED_BY_PIP"
        emp_after = get_success_data(
            api.get_employee(cast["ou_id"], cast["emp_id"], hrbp_headers)
        )
        assert emp_after["active_pip_id"] == pip["id"]


class TestConcernAcceptEscalationCascade:
    def test_accept_escalates_linked_coaching_entries(self, api):
        """PRD §3.2: "it stamps `decided_at` and `decided_by_hrbp_id` and, as a
        cascade, escalates every linked coaching entry's severity to `ESCALATED`."

        Design: Difficulty/transitive_cascade/concern_accept_cascades_coaching_entries_escalate_pip_issue_supersedes_concern
        """
        cast = setup_cast()
        entry_ids = create_coaching_entries(cast)
        concern = create_and_accept_concern(cast, entry_ids)
        assert concern["status"] == "ACCEPTED"
        hrbp_headers = make_hrbp_headers(cast["hrbp_id"])
        for entry_id in entry_ids:
            entry = get_success_data(
                api.flat_get_coaching_log_entry(entry_id, hrbp_headers)
            )
            assert entry["severity"] == "ESCALATED", (
                f"linked entry {entry_id} must escalate to ESCALATED on accept, "
                f"got {entry['severity']}"
            )
        assert concern["decided_by_hrbp_id"] == cast["hrbp_id"]

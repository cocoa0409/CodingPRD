"""Report drafting, submission, review, revision loop, and terminal states
(PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    assert_report,
    edit_report,
    make_funder_headers,
    return_report,
    revise_report,
    set_clock,
    setup_active_grant,
    start_report,
    start_review,
    submit_report,
    validate_error,
    validate_success,
    walk_report_to_accepted,
    api_client,
)

OFFICER = TEST_USERS["officer_headers"]


def _draft_ready_report(ctx, clock="2026-06-15T00:00:00Z", report_index=0):
    """SCHEDULED -> DRAFT with narrative + outcome entries present."""
    set_clock(clock)
    report = ctx["reports"][report_index]
    start_report(report["id"])
    edit_report(report["id"])
    return report


class TestReportRevisionCycle:
    def test_report_revision_cycle_revise_increments_count(self, api):
        """PRD §3.4: "A returned report re-enters the revision loop. A
        `GrantsOfficer` reopens it, moving `RETURNED` back to `DRAFT`; the grant
        must not be `SUSPENDED` (else `ERR_GRANT_SUSPENDED`). Each such reopen
        increments `revision_count` by exactly one."
        PRD §3.4: "returning also transitions every `VarianceExplanation` on the
        report that is in `SUBMITTED` back to `DRAFTED`" and "Returning a report
        requires a `returned_reason` in the payload, which is stored on the
        report."

        Design: Difficulty/non_linear_state_machine/report_revision_cycle
        """
        ctx = setup_active_grant()
        funder_id = ctx["funder"]["id"]
        report = _draft_ready_report(ctx)
        submit_report(report["id"])
        start_review(report["id"], funder_id)
        return_report(report["id"], funder_id, reason="needs detail")

        resp = api.revise_report(report["id"], OFFICER)
        data = validate_success(resp)
        assert data["status"] == "DRAFT"
        assert data["revision_count"] == 1, (
            f"revision_count must be 1 after one RETURNED -> DRAFT arc, got "
            f"{data['revision_count']}"
        )

    def test_report_revision_cycle_resubmit_closes_loop(self, api):
        """PRD §3.4: "The loop may repeat indefinitely — `RETURNED` to `DRAFT` to
        `SUBMITTED` and back — until the funder accepts; `ACCEPTED` is the
        terminal state of the report lifecycle."
        PRD §3.4: "Returning a report requires a `returned_reason` in the
        payload, which is stored on the report."

        Design: Difficulty/non_linear_state_machine/report_revision_cycle
        """
        ctx = setup_active_grant()
        funder_id = ctx["funder"]["id"]
        report = _draft_ready_report(ctx)
        submit_report(report["id"])
        start_review(report["id"], funder_id)
        return_report(report["id"], funder_id, reason="needs detail")
        revise_report(report["id"])

        resp = api.submit_report(report["id"], OFFICER)
        data = validate_success(resp)
        assert data["status"] == "SUBMITTED"

        fetched = validate_success(api.get_report(report["id"], OFFICER))
        assert fetched["returned_reason"] == "needs detail"
        assert fetched["revision_count"] == 1


class TestReportTerminalState:
    def test_accepted_report_return_rejected(self, api):
        """PRD §3.4: "`ACCEPTED` is the terminal state of the report lifecycle."
        PRD §5: `ERR_INVALID_STATE` (409) is the "generic state-machine
        rejection: trigger not valid from current state".

        Design: Corner/state_machines/accepted_report_return_rejected
        """
        ctx = setup_active_grant()
        funder_id = ctx["funder"]["id"]
        report = _draft_ready_report(ctx)
        walk_report_to_accepted(report["id"], funder_id)

        resp = api.return_report(
            report["id"], {"returned_reason": "x"},
            # funder-scoped: X-User-ID must equal the awarding funder's id
            make_funder_headers(funder_id),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_late_report_submit_flagged(self, api):
        """PRD §3.4: "On successful submission, `submitted_at` is set to the
        current logical time, `submitted_late` is recomputed as whether
        `submitted_at` falls after the end of the due date's day (23:59:59Z),
        and every `VarianceExplanation` on the report in `DRAFTED` transitions
        to `SUBMITTED`."

        Design: Corner/state_machines/late_report_submit_flagged
        """
        ctx = setup_active_grant()
        # R1 due_date is 2026-09-30 (period_end 2026-08-31 + 30 days).
        report = _draft_ready_report(ctx, clock="2026-10-05T00:00:00Z")
        resp = api.submit_report(report["id"], OFFICER)
        data = validate_success(resp)
        assert data["status"] == "SUBMITTED"
        assert data["submitted_late"] is True, (
            "submit on 2026-10-05 is after due_date 2026-09-30 end-of-day and "
            "must be flagged late, not rejected"
        )


class TestSubmitContentGates:
    def test_outcome_data_required_on_submit(self, api):
        """PRD §3.4: "the `narrative_draft` must be non-empty and
        `outcome_entries` must contain at least one entry — otherwise
        `ERR_OUTCOME_DATA_REQUIRED` (HTTP 422)."

        Design: Corner/validations/outcome_data_required_on_submit
        """
        ctx = setup_active_grant()
        set_clock("2026-06-15T00:00:00Z")
        report = ctx["reports"][0]
        start_report(report["id"])
        # No edit: narrative_draft is "" and outcome_entries is [].
        resp = api.submit_report(report["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_OUTCOME_DATA_REQUIRED)

"""Validation priority: the lowest-numbered tier wins when several rules fail (PRD §2.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_filing_cycle,
    get_owner,
    get_report,
    make_owner_headers,
    set_clock,
    setup_report_scenario,
    submit_report,
    validate_error,
)

OFFICER = TEST_USERS["officer_headers"]


class TestStateBeatsFiscal:
    def _setup_restricted_owner_with_submitted_report(self, submit_clock):
        """Owner submits 50000-sqft OFFICE report late; the late fine pushes the
        owner over the restriction threshold while the report sits in SUBMITTED."""
        ctx = setup_report_scenario()
        set_clock(submit_clock)
        ctx["report"] = submit_report(ctx["report"]["id"], ctx["owner"]["id"])
        assert ctx["report"]["status"] == "SUBMITTED"
        assert ctx["report"]["is_late"] is True
        return ctx

    def test_late_submit_drives_owner_restricted(self, api):
        """PRD §3.7: "Whenever this total is strictly greater than one hundred
        thousand cents — exactly one thousand dollars, the restriction threshold —
        the owner's `standing` is `RESTRICTED`; at exactly the threshold the standing
        stays `NORMAL`, and a total at or below the threshold leaves or returns the
        owner to `NORMAL`."
        PRD §3.5: "When `days_late` exceeds zero, the system creates a
        `FineAssessment` of `fine_type` `LATE_SUBMISSION` in `ASSESSED` status whose
        `provisional_amount_cents` is the provisional late-fine variant of §3.7, and
        recomputes the owner's exposure"

        Precondition arm of the priority pair: 24 days late -> 120000 cents ->
        RESTRICTED. The fiscal violation is genuinely armed for the second submit.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_submit
        """
        ctx = self._setup_restricted_owner_with_submitted_report("2027-06-25T00:00:00Z")
        owner = get_owner(ctx["owner"]["id"])
        assert owner["outstanding_fines_cents"] == 120000
        assert owner["standing"] == "RESTRICTED"

    def test_state_error_precedes_fiscal_on_double_submit(self, api):
        """PRD §2.8: "When a single request violates several rules, the system does
        not choose arbitrarily among them: checks are evaluated in a fixed priority
        order, and the request reports the error belonging to the lowest-numbered
        priority tier."
        PRD §2.8: "7. **State-machine preconditions.** The target resource's current
        state must allow the requested transition (`ERR_INVALID_STATE_TRANSITION`)."
        PRD §2.8: "11. **Fiscal gates.** Submission is blocked while the owner's
        standing is `RESTRICTED` (`ERR_OWNER_RESTRICTED`, HTTP 403)"

        The second submit violates both the from-state rule (SUBMITTED, not
        DRAFT|FLAGGED) and the fiscal gate; state (tier 7) wins over fiscal (tier 11).

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_submit
        """
        ctx = self._setup_restricted_owner_with_submitted_report("2027-06-25T00:00:00Z")
        assert get_owner(ctx["owner"]["id"])["standing"] == "RESTRICTED"

        resp = api.submit_report(ctx["report"]["id"], make_owner_headers(ctx["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestTemporalBeatsConstraint:
    def test_submit_after_close_reports_temporal_error_not_completeness(self, api):
        """PRD §2.8: "When a single request violates several rules, the system does
        not choose arbitrarily among them: checks are evaluated in a fixed priority
        order, and the request reports the error belonging to the lowest-numbered
        priority tier."
        PRD §2.8: "Report creation requires an `OPEN` cycle (`ERR_CYCLE_NOT_OPEN`),
        submission requires an `OPEN` cycle (`ERR_FILING_CLOSED` once filing has
        closed or the cycle is published), close-filing requires the logical clock to
        sit strictly past the deadline (`ERR_CYCLE_NOT_CLOSABLE`), cycle
        configuration edits are allowed only while the cycle is `SCHEDULED` or `OPEN`
        (`ERR_CYCLE_NOT_EDITABLE`), and disclosure publication requires a closed or
        published cycle (`ERR_CYCLE_NOT_CLOSED`)."
        PRD §2.8: "10. **Constraint gates.** Data completeness at or above the cycle
        minimum (`ERR_DATA_COMPLETENESS_BELOW_THRESHOLD`, HTTP 422)"

        The submit violates both the cycle gate (FILING_CLOSED) and completeness
        (60.00 < 90); temporal (tier 8) wins over constraint (tier 10).

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_late_incomplete_submit
        """
        ctx = setup_report_scenario(consent_indexes=(0,))
        assert ctx["report"]["data_completeness_pct"] == pytest.approx(60.00, abs=0.005)
        close_filing_cycle(ctx["cycle"]["id"])

        resp = api.submit_report(ctx["report"]["id"], make_owner_headers(ctx["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FILING_CLOSED)

    def test_completeness_gate_fires_when_cycle_open(self, api):
        """PRD §3.5: "The report's `data_completeness_pct` must be at least the
        cycle's `data_completeness_min_pct` — the threshold is inclusive — or the
        submission fails with `ERR_DATA_COMPLETENESS_BELOW_THRESHOLD`."

        The isolated constraint arm of the same pair: identical 60.00-completeness
        report, but the cycle is still OPEN, so the constraint gate is what fires.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_late_incomplete_submit
        """
        ctx = setup_report_scenario(consent_indexes=(0,))
        assert ctx["report"]["data_completeness_pct"] == pytest.approx(60.00, abs=0.005)
        assert ctx["cycle"]["status"] == "OPEN"

        resp = api.submit_report(ctx["report"]["id"], make_owner_headers(ctx["owner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DATA_COMPLETENESS_BELOW_THRESHOLD)
        still = get_report(ctx["report"]["id"])
        assert still["status"] == "DRAFT"

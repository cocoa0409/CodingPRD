"""Marshal reports: auto-creation on completion, submission, adjudication
gating on deficiencies, and the rejection/revision loop."""
import re

from test_helpers import (
    ApiErrorId,
    add_days,
    assert_report,
    create_revision_payload,
    get_deficiency,
    get_success_data,
    iso_utc,
    make_fire_marshal_headers,
    parse_date,
    set_clock,
    setup_completed_event,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MARSHAL = TEST_USERS["fire_marshal_headers"]


class TestReportAutoCreation:
    def test_complete_auto_creates_draft_report_and_due_date(self, api):
        """PRD §3.7: "Every completed inspection event owns a one-to-one marshal
        report, auto-created in `DRAFT` at completion."
        PRD §3.4: "The server stamps `completed_at` with the current clock and
        sets `report_due_date` to the completion date plus seven calendar days."

        Design: Corner/endpoints/complete_auto_creates_draft_marshal_report
        """
        ctx = setup_completed_event(
            scheduled_start="2026-08-02T09:00:00Z",
            scheduled_end="2026-08-02T10:00:00Z",
            complete_clock="2026-08-02T09:30:00Z",
            legal_name="AutoRep Co")
        reports = get_success_data(
            api.list_event_reports(ctx["ev"]["id"], ctx["admin"]))
        assert len(reports) == 1, "completion auto-creates exactly one report"
        report = reports[0]
        assert_report(report)
        assert report["status"] == "DRAFT"
        ev = validate_success(api.get_event(ctx["ev"]["id"], ctx["admin"]))
        assert str(ev["report_due_date"])[:10] == "2026-08-09", (
            "completed 2026-08-02 plus seven calendar days")


class TestRejectRevisionLoop:
    def _rejected_report(self, api):
        """Completed event -> report submitted at 2026-08-03 -> REJECTED."""
        ctx = setup_completed_event(
            system_category="SPRINKLER", device_type="SPRINKLER_HEAD",
            occupancy_class="ASSEMBLY",
            scheduled_start="2026-08-02T09:00:00Z",
            scheduled_end="2026-08-02T10:00:00Z",
            complete_clock="2026-08-02T09:30:00Z",
            legal_name="Report Loop Inc")
        report = ctx["report"]
        submitted = validate_success(api.submit_report(report["id"], ctx["admin"]))
        assert submitted["status"] == "SUBMITTED"
        rejected = validate_success(api.reject_report(report["id"], MARSHAL))
        assert rejected["status"] == "REJECTED"
        ctx["rep1"] = rejected
        return ctx

    def test_revision_loop_runs_to_acceptance_with_portal_token(self, api):
        """PRD §3.7: "A `ContractorAdmin` creates a revision by posting a new
        report against the same event with `revision_of_id` pointing at the
        rejected report; the pointer must reference a report that exists, is
        `REJECTED`, and belongs to the same event, else
        `ERR_REPORT_REVISION_INVALID`."
        PRD §3.7: "Acceptance stamps the `portal_submission_id`, a server-minted
        receipt token that is not a UUID: it is the parent property's
        jurisdiction code followed by a hyphen and a zero-padded eight-digit
        counter, sequential per jurisdiction."

        Design: Difficulty/non_linear_state_machine/marshal_report_reject_revision_loop
        """
        ctx = self._rejected_report(api)
        rep2 = validate_success(api.create_revision_report(
            ctx["ev"]["id"], create_revision_payload(ctx["rep1"]["id"]),
            ctx["admin"]), 201)
        assert rep2["revision_of_id"] == ctx["rep1"]["id"]
        validate_success(api.submit_report(rep2["id"], ctx["admin"]))
        accepted = validate_success(api.accept_report(rep2["id"], MARSHAL))
        assert accepted["status"] == "ACCEPTED"
        token = accepted["portal_submission_id"]
        assert isinstance(token, str) and re.fullmatch(r"LACO-\d{8}", token), (
            f"portal receipt token must be '<jurisdiction_code>-' plus a "
            f"zero-padded eight-digit counter, got {token!r}")

    def test_rejected_report_retained_and_revision_starts_draft(self, api):
        """PRD §3.7: "The rejected report remains `REJECTED` for audit, and the
        new report starts its own lifecycle in `DRAFT`."
        PRD §3.7: "Reports may be listed under their event — the active
        one-to-one report plus any revisions"

        Design: Difficulty/non_linear_state_machine/marshal_report_reject_revision_loop
        """
        ctx = self._rejected_report(api)
        rep2 = validate_success(api.create_revision_report(
            ctx["ev"]["id"], create_revision_payload(ctx["rep1"]["id"]),
            ctx["admin"]), 201)
        assert rep2["status"] == "DRAFT", "the revision starts its own lifecycle"

        rep1 = validate_success(api.get_report(ctx["rep1"]["id"], ctx["admin"]))
        assert rep1["status"] == "REJECTED", "the rejected report remains for audit"
        listed = get_success_data(api.list_event_reports(ctx["ev"]["id"], ctx["admin"]))
        assert {r["id"] for r in listed} == {rep1["id"], rep2["id"]}, (
            "the event lists the original report plus the revision")


class TestAcceptanceGating:
    def _submitted_with_critical_deficiency(self, api):
        """Completed event with one CRITICAL deficiency; report submitted."""
        ctx = setup_completed_event(
            deficiency_classifications=("CRITICAL",),
            legal_name="ReportGate Co")
        ctx["deficiency"] = ctx["defs"][0]
        set_clock("2026-08-05T00:00:00Z")
        validate_success(api.submit_report(ctx["report"]["id"], ctx["admin"]))
        return ctx

    def test_accept_blocked_by_overdue_unresolved_deficiency(self, api):
        """PRD §3.7: "Acceptance requires a `SUBMITTED` report and a clean
        deficiency posture on the parent event: every deficiency must be in
        `VERIFIED` or `WAIVED`, or still within its `correction_deadline` window
        — an overdue, unresolved deficiency blocks acceptance with
        `ERR_UNRESOLVED_OVERDUE_DEFICIENCIES`."

        Design: Difficulty/cross_entity_state_dependency/report_accept_gated_by_deficiency_resolution_state
        """
        ctx = self._submitted_with_critical_deficiency(api)
        deadline = parse_date(
            get_deficiency(ctx["con"], ctx["deficiency"]["id"])["correction_deadline"])
        # Advance strictly past the deadline (and never backward past submit).
        set_clock(iso_utc(max(add_days(deadline, 1), parse_date("2026-08-06"))))
        resp = api.accept_report(ctx["report"]["id"], MARSHAL)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_OVERDUE_DEFICIENCIES)
        report = validate_success(api.get_report(ctx["report"]["id"], ctx["admin"]))
        assert report["status"] == "SUBMITTED", "the blocked accept changes nothing"
        deficiency = get_deficiency(ctx["con"], ctx["deficiency"]["id"])
        assert deficiency["status"] == "OPEN"

    def test_accept_succeeds_once_deficiency_verified(self, api):
        """PRD §3.7: "Acceptance requires a `SUBMITTED` report and a clean
        deficiency posture on the parent event: every deficiency must be in
        `VERIFIED` or `WAIVED`, or still within its `correction_deadline` window
        — an overdue, unresolved deficiency blocks acceptance with
        `ERR_UNRESOLVED_OVERDUE_DEFICIENCIES`."
        PRD §3.5: "Verification lands in `VERIFIED`, the terminal-accepted state."

        Design: Difficulty/cross_entity_state_dependency/report_accept_gated_by_deficiency_resolution_state
        """
        ctx = self._submitted_with_critical_deficiency(api)
        d_id = ctx["deficiency"]["id"]
        corrected = validate_success(api.attest_correction(d_id, ctx["admin"]))
        assert corrected["status"] == "CORRECTED"
        verified = validate_success(
            api.verify_deficiency(d_id, make_fire_marshal_headers("fm-verify-2")))
        assert verified["status"] == "VERIFIED"
        accepted = validate_success(api.accept_report(ctx["report"]["id"], MARSHAL))
        assert accepted["status"] == "ACCEPTED"
        assert isinstance(accepted["portal_submission_id"], str)

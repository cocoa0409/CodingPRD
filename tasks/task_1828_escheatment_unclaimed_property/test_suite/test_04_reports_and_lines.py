"""Holder report assembly: periods, lines, submission gates, amendment, and
the reject/reopen cycle (PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_version_incremented,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)
from test_helpers.fixtures import (
    CO,
    READER,
    SA,
    accept_report,
    add_line_item,
    create_owner,
    create_property,
    create_report,
    create_reportable_properties,
    create_reportable_property,
    create_rule,
    get_report,
    record_contact,
    run_sweep,
    send_letter,
    set_clock,
    setup_accepted_single_line_report,
    setup_draft_report_with_lines,
    submit_report,
)

CO_H = TEST_USERS["compliance_officer_headers"]
SA_H = TEST_USERS["state_auditor_headers"]
HA_H = TEST_USERS["holder_admin_headers"]


class TestReportPeriodsAndEmptySubmit:
    def test_duplicate_report_period_rejected(self, api):
        """PRD §3.4: "only one report per state-and-year pair may exist outside
        `SUPERSEDED`, and a duplicate base report is refused with
        `ERR_DUPLICATE_REPORT_PERIOD` — amendments, which carry a
        `supersedes_report_id`, are expressly exempt from this rule."

        Design: Corner/errors/duplicate_report_period_rejected
        """
        get_success_data(api.create_report({"state_code": "CA", "report_year": 2026}, CO_H), 201)
        dup = api.create_report({"state_code": "CA", "report_year": 2026}, CO_H)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD, 409)
        other_year = api.create_report({"state_code": "CA", "report_year": 2027}, CO_H)
        validate_success(other_year, 201)

    def test_submit_empty_report_rejected(self, api):
        """PRD §3.4: "A `ComplianceOfficer` submits a report that is `DRAFT`
        (else `ERR_REPORT_NOT_DRAFT`), holds at least one `INCLUDED` line (else
        `ERR_EMPTY_REPORT`)"

        Design: Corner/errors/submit_empty_report_rejected
        """
        report = create_report()
        resp = api.submit_report(report["id"], CO_H)
        validate_error(resp, ApiErrorId.ERR_EMPTY_REPORT, 422)
        assert get_report(report["id"])["status"] == "DRAFT"


class TestReportStateGates:
    def test_accept_draft_report_rejected(self, api):
        """PRD §3.4: "A `StateAuditor` accepts a report that is `SUBMITTED`
        (else `ERR_REPORT_NOT_SUBMITTED`)"

        Design: Corner/errors/accept_draft_report_rejected
        """
        report = create_report()
        resp = api.accept_report(report["id"], SA_H)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_SUBMITTED, 409)

    def test_reopen_draft_report_rejected(self, api):
        """PRD §3.4: "A `ComplianceOfficer` may then reopen a `REJECTED`
        report — reopening any other state is refused with
        `ERR_REPORT_NOT_REJECTED`"

        Design: Corner/errors/reopen_draft_report_rejected
        """
        report = create_report()
        resp = api.reopen_report(report["id"], CO_H)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_REJECTED, 409)

    def test_amendment_on_draft_report_rejected(self, api):
        """PRD §3.4: "A `ComplianceOfficer` creates an amendment against an
        `ACCEPTED` report — any other state is refused with
        `ERR_REPORT_NOT_ACCEPTED`"

        Design: Corner/errors/amendment_on_draft_report_rejected
        """
        report = create_report()
        resp = api.create_amendment(
            report["id"], {"expected_report_version": report["version"]}, CO_H
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_ACCEPTED, 409)

    def test_pending_amendment_exists_rejected(self, api):
        """PRD §3.4: "at most one pending amendment, meaning one in `DRAFT` or
        `SUBMITTED`, may exist per superseded report (else
        `ERR_PENDING_AMENDMENT_EXISTS`)."

        Design: Corner/errors/pending_amendment_exists_rejected
        """
        chain = setup_accepted_single_line_report(value=80000)
        r1 = chain["report"]
        first = api.create_amendment(
            r1["id"], {"expected_report_version": chain["accepted_version"]}, CO_H
        )
        validate_success(first, 201)
        fresh = get_report(r1["id"])["version"]
        second = api.create_amendment(
            r1["id"], {"expected_report_version": fresh}, CO_H
        )
        # The OCC version is fresh, so the failure is the uniqueness rule.
        validate_error(second, ApiErrorId.ERR_PENDING_AMENDMENT_EXISTS, 409)

    def test_remove_final_line_after_reopen_rejected(self, api):
        """PRD §3.4: "Removing a line is permitted only while the report is
        `DRAFT` (else `ERR_REPORT_NOT_DRAFT`) and the line is `INCLUDED` (else
        `ERR_LINE_ITEM_NOT_REMOVABLE`); removal moves the line to `REMOVED`,
        its terminal state along with `FINAL`."

        Design: Corner/errors/remove_final_line_after_reopen_rejected
        """
        _, _, prop, _ = create_reportable_property(original_value_cents=80000)
        report = create_report()
        line = add_line_item(report["id"], prop["id"])
        submit_report(report["id"])  # CASH line finalizes
        get_success_data(
            api.reject_report(report["id"], {"rejection_reason": "bad format"}, SA_H),
            200,
        )
        reopened = get_success_data(api.reopen_report(report["id"], CO_H), 200)
        assert reopened["status"] == "DRAFT"
        resp = api.remove_line_item(report["id"], line["id"], CO_H)
        # The report is DRAFT (state gate passes) but the line stayed FINAL.
        validate_error(resp, ApiErrorId.ERR_LINE_ITEM_NOT_REMOVABLE, 409)

    def test_line_remove_under_wrong_report_is_not_found(self, api):
        """PRD §2.9: "A request targeting a line item under a report that does
        not exist therefore fails with `ERR_REPORT_NOT_FOUND` before the line
        is ever examined, and a line item that exists but does not belong to
        the report named in the path is likewise reported as
        `ERR_LINE_ITEM_NOT_FOUND`."

        Design: Corner/errors/line_remove_from_wrong_report_not_found
        """
        _, _, prop, _ = create_reportable_property(original_value_cents=80000)
        r1 = create_report(report_year=2026)
        line = add_line_item(r1["id"], prop["id"])
        r2 = create_report(report_year=2027)
        resp = api.remove_line_item(r2["id"], line["id"], CO_H)
        validate_error(resp, ApiErrorId.ERR_LINE_ITEM_NOT_FOUND, 404)


class TestReportTotals:
    def test_removed_line_drops_out_of_all_aggregates(self, api):
        """PRD §3.4: "At every line addition, line removal, submission,
        liquidation settlement, amendment copy, and reactivation cascade, the
        included set — lines in `INCLUDED` or `FINAL`, excluding `REMOVED` —
        is re-aggregated: `total_provisional_cents` is the sum of the included
        lines' `provisional_value_cents`; `total_final_cents` sums, for each
        included line, its `final_value_cents` when the line is `FINAL` and its
        `provisional_value_cents` otherwise; and `line_count` is the size of
        the included set."

        Design: Corner/calculations/report_totals_exclude_removed_lines
        """
        setup = setup_draft_report_with_lines([50000, 70000])
        report = setup["report"]
        lines = setup["lines"]
        before = get_report(report["id"])
        assert before["total_provisional_cents"] == 120000
        removed = get_success_data(
            api.remove_line_item(report["id"], lines[0]["id"], CO_H), 200
        )
        assert removed["status"] == "REMOVED"
        after = get_report(report["id"])
        assert after["total_provisional_cents"] == 70000
        assert after["total_final_cents"] == 70000
        assert after["line_count"] == 1
        assert_version_incremented(after["version"], before["version"])


class TestDueDiligenceCompleteAtSubmit:
    def test_threshold_lowered_after_reportable_blocks_submit(self, api):
        """PRD §3.4: "for every `INCLUDED` line whose property's
        `original_value_cents` is at or above the applicable rule's
        `dd_threshold_cents`, that property must show at least one letter in a
        terminal state — `EXPIRED` or `UNDELIVERABLE` — else the submission is
        refused with `ERR_DUE_DILIGENCE_INCOMPLETE`."

        Design: Corner/validations/submit_due_diligence_incomplete_after_threshold_lowered
        """
        rule = create_rule(property_type="UNCASHED_CHECK")  # threshold 5000
        owner = create_owner()
        prop = create_property(
            owner["id"], property_type="UNCASHED_CHECK", original_value_cents=4999
        )
        run_sweep()  # ACTIVE -> DORMANT
        run_sweep()  # DORMANT -> REPORTABLE (4999 < 5000: no letter needed)
        get_success_data(
            api.update_dormancy_rule(rule["id"], {"dd_threshold_cents": 4000}, HA_H),
            200,
        )
        report = create_report()
        add_line_item(report["id"], prop["id"])
        resp = api.submit_report(report["id"], CO_H)
        # 4999 >= 4000 under the current rule, and no terminal letter exists.
        validate_error(resp, ApiErrorId.ERR_DUE_DILIGENCE_INCOMPLETE, 422)
        assert get_report(report["id"])["status"] == "DRAFT"


class TestAmendmentSupersedes:
    def test_accepted_amendment_supersedes_original_terminal(self, api):
        """PRD §3.4: "when the accepted report is an amendment — its
        `supersedes_report_id` set — the superseded report moves `ACCEPTED →
        SUPERSEDED`, the only terminal state a report has."

        Design: Corner/state_machines/report_superseded_terminal_lockdown
        """
        chain = setup_accepted_single_line_report(value=80000)
        r1 = chain["report"]
        amendment = get_success_data(
            api.create_amendment(
                r1["id"], {"expected_report_version": chain["accepted_version"]}, CO_H
            ),
            201,
        )
        assert amendment["supersedes_report_id"] == r1["id"]
        assert amendment["status"] == "DRAFT"
        submit_report(amendment["id"])
        accept_report(amendment["id"])
        original = get_report(r1["id"])
        assert original["status"] == "SUPERSEDED"
        resp = api.reject_report(r1["id"], {"rejection_reason": "too late"}, SA_H)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_SUBMITTED, 409)
        assert get_report(r1["id"])["status"] == "SUPERSEDED"


class TestRejectReopenCycle:
    def _submitted_report(self):
        _, _, prop, _ = create_reportable_property(original_value_cents=80000)
        report = create_report()
        add_line_item(report["id"], prop["id"])
        submitted = submit_report(report["id"])  # clock is 2026-09-01
        return report, submitted

    def test_submit_then_reject_records_reason(self, api):
        """PRD §3.4: "On submission the report's `submitted_date` is set to the
        clock date, `submitted_by_user_id` records the submitting officer"
        PRD §3.4: "A `StateAuditor` may instead reject a `SUBMITTED` report,
        recording the supplied `rejection_reason`."

        Design: Difficulty/non_linear_state_machine/report_reject_reopen_resubmit_cycle
        """
        report, submitted = self._submitted_report()
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_date"] == "2026-09-01"
        rejected = get_success_data(
            api.reject_report(
                report["id"], {"rejection_reason": "malformed NAUPA file"}, SA_H
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "malformed NAUPA file"

    def test_reopen_clears_submission_metadata(self, api):
        """PRD §3.4: "A `ComplianceOfficer` may then reopen a `REJECTED` report
        — reopening any other state is refused with `ERR_REPORT_NOT_REJECTED` —
        returning it to `DRAFT` and clearing `submitted_date`,
        `submitted_by_user_id`, and `rejection_reason` to null for another
        attempt."

        Design: Difficulty/non_linear_state_machine/report_reject_reopen_resubmit_cycle
        """
        report, submitted = self._submitted_report()
        get_success_data(
            api.reject_report(
                report["id"], {"rejection_reason": "malformed NAUPA file"}, SA_H
            ),
            200,
        )
        reopened = get_success_data(api.reopen_report(report["id"], CO_H), 200)
        assert reopened["status"] == "DRAFT"
        assert reopened["submitted_date"] is None
        assert reopened["submitted_by_user_id"] is None
        assert reopened["rejection_reason"] is None


class TestLineItemGates:
    def _dormant_and_reportable_pair(self):
        create_rule()
        owner = create_owner()
        p1 = create_property(owner["id"], original_value_cents=60000)
        p2 = create_property(owner["id"], original_value_cents=60000)
        run_sweep()  # both DORMANT
        report = create_report()
        send_letter(p2["id"])
        set_clock("2026-09-01T00:00:00Z")
        run_sweep()  # p2's letter expires -> p2 REPORTABLE; p1 stays DORMANT
        return p1, p2, report

    def test_dormant_property_cannot_be_lined(self, api):
        """PRD §3.4: "The property must be `REPORTABLE` and of the report's own
        state, else `ERR_PROPERTY_NOT_REPORTABLE`"

        Design: Difficulty/cross_entity_state_dependency/line_item_requires_reportable_property_and_draft_report
        """
        p1, p2, report = self._dormant_and_reportable_pair()
        resp = api.add_line_item(
            report["id"],
            {"property_id": p1["id"],
             "expected_report_version": get_report(report["id"])["version"]},
            CO_H,
        )
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_REPORTABLE, 422)

    def test_line_add_to_submitted_report_rejected(self, api):
        """PRD §3.4: "The report must be `DRAFT`, else `ERR_REPORT_NOT_DRAFT`."
        PRD §2.7: "If the report's current `version` has advanced beyond that
        observed value, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Difficulty/cross_entity_state_dependency/line_item_requires_reportable_property_and_draft_report
        """
        p1, p2, report = self._dormant_and_reportable_pair()
        line = add_line_item(report["id"], p2["id"])
        assert line["status"] == "INCLUDED"
        submit_report(report["id"])
        # Fresh OCC version: the state gate, not the concurrency check, fires.
        resp = api.add_line_item(
            report["id"],
            {"property_id": p2["id"],
             "expected_report_version": get_report(report["id"])["version"]},
            CO_H,
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_DRAFT, 409)



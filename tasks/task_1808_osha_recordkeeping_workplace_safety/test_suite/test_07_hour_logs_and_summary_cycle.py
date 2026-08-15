"""Hour logs and the 300A annual summary cycle (prepare, certify, post)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_day_entry,
    assert_hour_log,
    assert_summary,
    create_approved_hour_log,
    create_case,
    create_classified_case,
    create_summary,
    fresh_summary_version,
    get_summary,
    get_success_data,
    prepare_summary,
    set_clock,
    setup_certified_summary,
    setup_org,
    setup_prepared_summary,
    setup_year_hour_logs,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import COORDINATOR, OFFICER
from test_helpers.test_users import (
    make_recordkeeping_coordinator_headers,
    make_safety_officer_headers,
)


class TestPrepareGates:
    def test_prepare_blocked_by_unresolved_cases(self, api):
        """PRD §3.7: "Preparation runs the rollup and is gated twice: every
        case of the establishment whose `log_year` matches must be out of
        `INTAKE` and `PENDING_REVIEW`, unresolved cases failing with
        `ERR_CASES_UNRESOLVED`, and all twelve monthly logs must exist in
        `APPROVED` or `LOCKED` status with total hours greater than zero,
        failing otherwise with `ERR_HOURS_INCOMPLETE`."

        Design: Corner/validations/cases_unresolved_blocks_summary_prepare
        """
        _, establishment, employee = setup_org(fein="07-0000026",
                                               site_name="Unres Site")
        set_clock("2026-07-01T12:00:00Z")
        create_case(establishment["id"], employee["id"],
                    "2026-07-01T10:00:00Z", description="U")
        setup_year_hour_logs(establishment["id"], 2026)
        summary = create_summary(establishment["id"], 2026)

        resp = api.prepare_summary(summary["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_CASES_UNRESOLVED)

    def test_prepare_blocked_with_zero_total_hours(self, api):
        """PRD §3.7: "all twelve monthly logs must exist in `APPROVED` or
        `LOCKED` status with total hours greater than zero, failing otherwise
        with `ERR_HOURS_INCOMPLETE`."
        PRD §2.6: "When the denominator hours for a year are zero, a published
        rate is null rather than zero: the annual-summary preparation step
        treats zero hours as a hard error (§3.7), while the live rate read-out
        simply returns null rates for that year."

        Design: Corner/calculations/trir_null_when_zero_hours_on_prepare
        """
        _, establishment, _ = setup_org(fein="90-0000018",
                                        site_name="Site Zero")
        for month in range(1, 13):
            create_approved_hour_log(establishment["id"], 2026, month,
                                     hours_worked=0, employment_count=5)
        summary = create_summary(establishment["id"], 2026)

        resp = api.prepare_summary(summary["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_HOURS_INCOMPLETE)


class TestCertifySegregationAndState:
    def test_certify_by_preparer_rejected(self, api):
        """PRD §3.7: "The certifier must differ from `prepared_by` — a
        collision fails with `ERR_DUTY_SEGREGATION`"

        Design: Corner/validations/duty_segregation_certifier_not_preparer
        """
        _, establishment, _ = setup_org(fein="04-0000023",
                                        site_name="SoD Site")
        preparer = make_recordkeeping_coordinator_headers("exec-1")
        summary = setup_prepared_summary(establishment["id"], 2026,
                                         preparer_headers=preparer)
        assert summary["prepared_by"] == "exec-1"

        resp = api.certify_summary(
            summary["id"],
            {"expected_summary_version": fresh_summary_version(
                summary["id"])},
            make_safety_officer_headers("exec-1"))
        validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION)

    def test_certify_from_draft_after_bounce_rejected(self, api):
        """PRD §3.7: "any case mutation for the year — a classification, a
        reclassification, or a day-entry change — bounces the summary back to
        `DRAFT`, clearing `prepared_by` and discarding the provisional
        figures."
        PRD §2.9: "Fourth, state admissibility: the target resource must
        currently sit in a state from which the requested transition exists,
        failing with `ERR_INVALID_STATE`."

        Design: Corner/errors/error_summary_certify_from_draft_after_bounce
        """
        _, establishment, employee = setup_org(fein="10-0000029",
                                               site_name="Stale Site")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-07-01T10:00:00Z",
            classification="JOB_TRANSFER_RESTRICTION",
            clock_iso="2026-07-01T12:00:00Z", description="St")
        summary = setup_prepared_summary(establishment["id"], 2026)
        assert summary["status"] == "PREPARED"

        add_day_entry(case["id"], "RESTRICTED", "2026-07-02", "2026-07-04")
        bounced = get_summary(summary["id"])
        assert bounced["status"] == "DRAFT"

        resp = api.certify_summary(
            summary["id"],
            {"expected_summary_version": bounced["version"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestHourLogReopenDependency:
    def _prepared_summary_with_logs(self, fein):
        """Two resolved cases + twelve approved logs + PREPARED summary."""
        _, establishment, employee = setup_org(fein=fein, site_name="Mine 3",
                                               size_class="LARGE",
                                               naics_code="212111",
                                               state_code="WV")
        case_1 = create_classified_case(
            establishment["id"], employee["id"], "2026-07-15T10:00:00Z",
            clock_iso="2026-07-15T12:00:00Z", description="Contusion",
            body_part="hip")
        create_classified_case(
            establishment["id"], employee["id"], "2026-07-20T10:00:00Z",
            classification="FIRST_AID_ONLY", clock_iso="2026-07-20T12:00:00Z",
            description="Hearing test", body_part="ears",
            event_type="HEARING_LOSS")
        logs = setup_year_hour_logs(establishment["id"], 2026)
        summary = create_summary(establishment["id"], 2026)
        prepared = prepare_summary(summary["id"])
        assert prepared["status"] == "PREPARED"
        return establishment, case_1, logs, prepared

    def test_hour_log_reopen_blocked_while_summary_prepared(self, api):
        """PRD §3.7: "An approved log can be reopened to `DRAFT` only while
        no summary for that establishment-year sits in `PREPARED`,
        `CERTIFIED`, or `POSTED`, failing otherwise with
        `ERR_SUMMARY_LOCKED`; reopening likewise recomputes
        `current_year_hours`."

        Design: Difficulty/cross_entity_state_dependency/hour_log_reopen_gated_by_summary_state
        """
        _, _, logs, _ = self._prepared_summary_with_logs("55-7778889")
        resp = api.reopen_hour_log(logs[2]["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_SUMMARY_LOCKED)

    def test_hour_log_reopen_allowed_after_summary_bounce(self, api):
        """PRD §3.7: "any case mutation for the year — a classification, a
        reclassification, or a day-entry change — bounces the summary back to
        `DRAFT`, clearing `prepared_by` and discarding the provisional
        figures."
        PRD §3.7: "An approved log can be reopened to `DRAFT` only while no
        summary for that establishment-year sits in `PREPARED`, `CERTIFIED`,
        or `POSTED`, failing otherwise with `ERR_SUMMARY_LOCKED`"

        Design: Difficulty/cross_entity_state_dependency/hour_log_reopen_gated_by_summary_state
        """
        _, case_1, logs, summary = self._prepared_summary_with_logs(
            "55-7778890")

        add_day_entry(case_1["id"], "RESTRICTED", "2026-07-16", "2026-07-18")
        assert get_summary(summary["id"])["status"] == "DRAFT"

        resp = api.reopen_hour_log(logs[2]["id"], COORDINATOR)
        reopened = validate_success(resp, 200)
        assert_hour_log(reopened)
        assert reopened["status"] == "DRAFT"


class TestSummaryBounceInvariant:
    def _prepared_two_case_summary(self, fein):
        """Case 1 RECORDABLE (JTR) with 4 restricted days; case 2 RECORDABLE
        (MEDICAL_TREATMENT); twelve approved logs; PREPARED summary."""
        _, establishment, employee = setup_org(fein=fein, site_name="Shop 8",
                                               naics_code="336411",
                                               state_code="KS")
        case_1 = create_classified_case(
            establishment["id"], employee["id"], "2026-07-01T10:00:00Z",
            classification="JOB_TRANSFER_RESTRICTION",
            clock_iso="2026-07-01T12:00:00Z", description="Rivet burn")
        add_day_entry(case_1["id"], "RESTRICTED", "2026-07-02", "2026-07-05")
        create_classified_case(
            establishment["id"], employee["id"], "2026-07-10T10:00:00Z",
            clock_iso="2026-07-10T12:00:00Z", description="Noise exposure",
            body_part="ears", event_type="HEARING_LOSS")
        setup_year_hour_logs(establishment["id"], 2026)
        summary = create_summary(establishment["id"], 2026)
        prepared = prepare_summary(summary["id"])
        return case_1, prepared

    def test_day_entry_add_bounces_prepared_summary(self, api):
        """PRD §3.7: "While the summary sits in `PREPARED` these rates are
        live reflections of the underlying cases: any case mutation for the
        year — a classification, a reclassification, or a day-entry change —
        bounces the summary back to `DRAFT`, clearing `prepared_by` and
        discarding the provisional figures."

        Design: Difficulty/compensating_invariant/summary_prepare_bounce_preserves_case_count
        """
        case_1, prepared = self._prepared_two_case_summary("55-7897890")
        assert prepared["total_recordable_cases"] == 2
        assert prepared["total_restricted_days"] == 4

        add_day_entry(case_1["id"], "RESTRICTED", "2026-07-06", "2026-07-07")
        bounced = get_summary(prepared["id"])
        assert_summary(bounced)
        assert bounced["status"] == "DRAFT"
        assert bounced["prepared_by"] is None

    def test_reprepare_conserves_recordable_case_count(self, api):
        """PRD §3.7: "The prepared summary counts `total_recordable_cases`
        and `total_dart_cases` over the year's cases, sums the per-case capped
        `days_away_count` and `restricted_days_count` into `total_days_away`
        and `total_restricted_days` — each case's counts are capped first,
        then summed, never summed raw and capped afterwards"

        Design: Difficulty/compensating_invariant/summary_prepare_bounce_preserves_case_count
        """
        case_1, prepared = self._prepared_two_case_summary("55-7897891")
        add_day_entry(case_1["id"], "RESTRICTED", "2026-07-06", "2026-07-07")
        assert get_summary(prepared["id"])["status"] == "DRAFT"

        reprepared = prepare_summary(prepared["id"])
        assert reprepared["status"] == "PREPARED"
        assert reprepared["total_recordable_cases"] == 2, (
            "Recordable case count is conserved across the DRAFT round-trip")
        assert reprepared["total_restricted_days"] == 6, (
            "Day totals track the added entry (4 + 2)")


class TestPostingWindowBoundary:
    def _certified_summary(self, fein, site_name):
        _, establishment, employee = setup_org(fein=fein,
                                               site_name=site_name)
        create_classified_case(
            establishment["id"], employee["id"], "2026-08-01T10:00:00Z",
            clock_iso="2026-08-01T12:00:00Z", description="Burn",
            body_part="hand")
        return setup_certified_summary(establishment["id"], 2026)

    def test_post_on_apr30_inside_window(self, api):
        """PRD §3.7: "Posting is the public act: a `RecordkeepingCoordinator`
        posts a `CERTIFIED` summary only while the logical clock sits inside
        the posting window, boundaries inclusive; an attempt outside it fails
        with `ERR_POSTING_WINDOW`, and success stamps `posted_at` and lands
        the summary in the terminal `POSTED` state."
        PRD §3.7: "at creation the system fixes the posting window:
        `posting_window_open` at 00:00:00 UTC on February 1 of the following
        year, `posting_window_close` at 23:59:59 UTC on April 30 of that
        year."

        Design: Difficulty/boundary_precision_check/posting_window_apr30_inclusive_vs_may01
        """
        summary = self._certified_summary("55-2223334", "Forge 1")
        assert summary["posting_window_open"].startswith(
            "2027-02-01T00:00:00")
        assert summary["posting_window_close"].startswith(
            "2027-04-30T23:59:59")

        set_clock("2027-04-30T12:00:00Z")
        resp = api.post_summary(summary["id"], COORDINATOR)
        posted = validate_success(resp, 200)
        assert posted["status"] == "POSTED", (
            "April 30 of year+1 is inside the inclusive window")
        assert posted["posted_at"].startswith("2027-04-30")

    def test_post_on_may01_outside_window_rejected(self, api):
        """PRD §3.7: "Posting is the public act: a `RecordkeepingCoordinator`
        posts a `CERTIFIED` summary only while the logical clock sits inside
        the posting window, boundaries inclusive; an attempt outside it fails
        with `ERR_POSTING_WINDOW`, and success stamps `posted_at` and lands
        the summary in the terminal `POSTED` state."

        Design: Difficulty/boundary_precision_check/posting_window_apr30_inclusive_vs_may01
        """
        summary = self._certified_summary("55-2223335", "Forge 2")
        set_clock("2027-05-01T00:00:00Z")
        resp = api.post_summary(summary["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_POSTING_WINDOW)
        assert get_summary(summary["id"])["status"] == "CERTIFIED"

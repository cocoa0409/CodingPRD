"""Federal reports (PRD §3.7): snapshot input sets and half-open period
boundaries, per-case rounding order, snapshot immutability, the
documentation gate, segregation of duties, and period overlap.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_agency_director_headers,
    make_federal_officer_headers, setup_arrived_case,
    make_case, set_clock, make_service_delivery_note,
    make_case_note, get_benchmark_by_type, fulfill_benchmark,
    make_federal_report,
)
from test_helpers.fixtures import AD, FO


def _case_arrived_in_q4(case_number, with_member=True):
    """Arrived case on 2026-10-05 with a READY setup window inside Q4."""
    members = ([{"full_name": "Adult R", "date_of_birth": "1990-01-01",
                 "relationship": "PRINCIPAL", "work_eligible": True}]
               if with_member else [])
    return setup_arrived_case(
        case_number=case_number, household_size=1, members=members,
        scheduled_arrival_date="2026-10-05", actual_arrival_date="2026-10-05",
        occupancy_start="2026-10-05", occupancy_end="2027-04-05")


def _case_arrived_mid_december(case_number):
    """Arrived case on 2026-12-10: for the Q4 period [2026-10-01,
    2027-01-01) only December's month window overlaps
    [max(arrival, period_start), period_end), so case_months == 1 and every
    seeded due date (2027-01-09 or later) falls outside the period."""
    return setup_arrived_case(
        case_number=case_number, household_size=1, members=[],
        scheduled_arrival_date="2026-12-10", actual_arrival_date="2026-12-10",
        occupancy_start="2026-12-01", occupancy_end="2027-06-01")


class TestReportAllocationPerCaseRounding:
    def test_round_per_case_then_sum(self, api):
        """PRD §3.7: "Round each case's allocation half-up to integer cents
        first, and only then sum the per-case rounded amounts into
        `per_capita_allocation_cents`. The alternative order — summing raw
        values and rounding once at the end — is forbidden". (Each size-1
        case with one covered month: round-half-up of 1250000 / 12 =
        104166.66... to 104167; two cases total 208334.)

        Design: Difficulty/combinatorial_formula/report_allocation_per_case_rounding
        """
        _case_arrived_mid_december("CASE-CF2A")
        _case_arrived_mid_december("CASE-CF2B")
        report = make_federal_report("2026-10-01", "2027-01-01")
        assert report["cases_arrived_count"] == 2
        assert report["per_capita_allocation_cents"] == 208334

    def test_out_of_period_due_dates_not_counted(self, api):
        """PRD §3.7: "The counted benchmarks are the benchmarks belonging to
        included cases whose actual-basis `due_date` falls inside the period
        — a due date exactly on `period_start` is included, a due date
        exactly on `period_end` is excluded."

        Design: Difficulty/combinatorial_formula/report_allocation_per_case_rounding
        """
        _case_arrived_mid_december("CASE-CF2C")
        _case_arrived_mid_december("CASE-CF2D")
        report = make_federal_report("2026-10-01", "2027-01-01")
        assert report["cases_arrived_count"] == 2
        assert report["benchmarks_met_count"] == 0


class TestReportSnapshotInputSet:
    def _fixture(self):
        ctx = _case_arrived_in_q4("CASE-CA2A")
        note = make_service_delivery_note(ctx["case"]["id"],
                                          body="Home visit done",
                                          service_date="2026-11-04")
        set_clock("2026-11-04T00:00:00Z")
        bm = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT")
        fulfill_benchmark(bm["id"], "2026-11-04", note["id"])
        make_case(case_number="CASE-CA2B", household_size=3,
                  scheduled_arrival_date="2026-12-01")  # never arrives
        return ctx

    def test_pre_arrival_case_excluded_from_counts(self, api):
        """PRD §3.7: "The included cases are those whose
        `actual_arrival_date` falls inside the half-open period, in any
        status — `ARRIVED` or `TRANSFERRED_OUT` both count; `PRE_ARRIVAL`
        cases are never included because they have no actual arrival."

        Design: Corner/calculations/report_snapshot_input_set
        """
        self._fixture()
        report = make_federal_report("2026-10-01", "2027-01-01")
        assert report["cases_arrived_count"] == 1

    def test_benchmark_status_counts_and_half_open_due_dates(self, api):
        """PRD §3.7: "From those counted benchmarks, `benchmarks_met_count`
        counts the ones in `MET` status, `benchmarks_met_on_time_count`
        counts the subset of those with `on_time` true,
        `benchmarks_pending_count` counts those still `PENDING`, and
        `benchmarks_waived_count` counts those `WAIVED`." and "The counted
        benchmarks are the benchmarks belonging to included cases whose
        actual-basis `due_date` falls inside the period — a due date exactly
        on `period_start` is included, a due date exactly on `period_end` is
        excluded."

        Design: Corner/calculations/report_snapshot_input_set
        """
        self._fixture()
        report = make_federal_report("2026-10-01", "2027-01-01")
        assert report["benchmarks_met_count"] == 1
        assert report["benchmarks_met_on_time_count"] == 1
        assert report["benchmarks_pending_count"] == 3
        assert report["benchmarks_waived_count"] == 0


class TestReportSnapshotFrozenAfterGeneration:
    def _fixture(self):
        ctx = _case_arrived_in_q4("CASE-CA3A")
        note_a = make_service_delivery_note(ctx["case"]["id"],
                                            body="Home visit done",
                                            service_date="2026-11-04")
        note_b = make_service_delivery_note(ctx["case"]["id"],
                                            body="Health screening done",
                                            service_date="2026-11-05")
        set_clock("2026-11-04T00:00:00Z")
        bm_home = get_benchmark_by_type(ctx["case"]["id"], "HOME_VISIT")
        fulfill_benchmark(bm_home["id"], "2026-11-04", note_a["id"])
        report = make_federal_report("2026-10-01", "2027-01-01")
        set_clock("2026-11-05T00:00:00Z")
        bm_health = get_benchmark_by_type(ctx["case"]["id"], "HEALTH_SCREENING")
        fulfill_benchmark(bm_health["id"], "2026-11-05", note_b["id"])
        return report

    def test_met_count_frozen(self, api):
        """PRD §3.7: "Because these are snapshots taken at generation,
        benchmark transitions that happen afterwards never mutate an existing
        report." PRD §2.8: "the counts and dollar figures on a
        `FederalReport` are **snapshots** frozen at generation time: later
        benchmark transitions, arrivals, or transfer cascades do not mutate
        an existing report's numbers."

        Design: Corner/calculations/report_snapshot_frozen_after_generation
        """
        report = self._fixture()
        assert report["benchmarks_met_count"] == 1
        reread = validate_success(api.get_federal_report(report["id"], FO))
        assert reread["benchmarks_met_count"] == 1
        assert reread["benchmarks_met_on_time_count"] == 1

    def test_pending_count_frozen(self, api):
        """PRD §3.7: "Because these are snapshots taken at generation,
        benchmark transitions that happen afterwards never mutate an existing
        report."

        Design: Corner/calculations/report_snapshot_frozen_after_generation
        """
        report = self._fixture()
        reread = validate_success(api.get_federal_report(report["id"], FO))
        assert reread["benchmarks_pending_count"] == 3


class TestReportPeriodOverlap:
    def test_overlapping_period_rejected(self, api):
        """PRD §3.7: "Report periods must not overlap any existing federal
        report of any status — again judged as half-open intervals, so a
        period starting exactly where another ends is allowed — and an
        overlap is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)."

        Design: Corner/validations/report_period_overlap_and_adjacency
        """
        make_federal_report("2026-10-01", "2027-01-01")
        resp = api.create_federal_report(
            {"period_start": "2026-12-01", "period_end": "2027-03-01"}, AD)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

    def test_flush_adjacent_period_allowed(self, api):
        """PRD §3.7: "Report periods must not overlap any existing federal
        report of any status — again judged as half-open intervals, so a
        period starting exactly where another ends is allowed".

        Design: Corner/validations/report_period_overlap_and_adjacency
        """
        make_federal_report("2026-10-01", "2027-01-01")
        adjacent = validate_success(api.create_federal_report(
            {"period_start": "2027-01-01", "period_end": "2027-04-01"}, AD), 201)
        assert adjacent["status"] == "DRAFT"


class TestReportDocumentationGate:
    def test_submit_blocked_while_included_case_undocumented(self, api):
        """PRD §3.7: "an `AgencyDirector` may submit a `DRAFT` report only
        when every case counted in `cases_arrived_count` has at least one
        case note; a report covering an undocumented case is rejected with
        `ERR_REPORT_DOCUMENTATION_INCOMPLETE` (HTTP 422)."

        Design: Corner/validations/report_documentation_gate
        """
        _case_arrived_in_q4("CASE-V18", with_member=False)
        report = make_federal_report("2026-10-01", "2027-01-01")
        assert report["cases_arrived_count"] == 1
        resp = api.submit_federal_report(report["id"], AD)
        validate_error(resp, ApiErrorId.ERR_REPORT_DOCUMENTATION_INCOMPLETE)

    def test_submit_succeeds_after_documenting_case(self, api):
        """PRD §3.7: "Successful submission moves the report `DRAFT` →
        `SUBMITTED` and stamps `submitted_by_user_id` from the submitter's
        `X-User-ID`."

        Design: Corner/validations/report_documentation_gate
        """
        ctx = _case_arrived_in_q4("CASE-V18B", with_member=False)
        report = make_federal_report("2026-10-01", "2027-01-01")
        make_case_note(ctx["case"]["id"], note_type="GENERAL",
                       body="Case file opened and reviewed")
        submitted = validate_success(
            api.submit_federal_report(report["id"],
                                      make_agency_director_headers("dir-v18")))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == "dir-v18"


class TestSegregationOfDuties:
    def _submitted_report_by(self, api, submitter_id):
        report = make_federal_report("2026-10-01", "2027-01-01")
        submitted = validate_success(api.submit_federal_report(
            report["id"], make_agency_director_headers(submitter_id)))
        assert submitted["status"] == "SUBMITTED"
        return report

    def test_review_by_submitter_user_id_rejected(self, api):
        """PRD §3.7: "Segregation of duties is enforced on user identity, not
        role: the reviewer's `X-User-ID` must differ from the report's
        `submitted_by_user_id`, even when the same operator holds both roles,
        else the review is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Design: Corner/validations/sod_same_user_review_returns_segregation_error
        """
        report = self._submitted_report_by(api, "dir-1")
        resp = api.review_federal_report(report["id"], {"decision": "ACCEPTED"},
                                         make_federal_officer_headers("dir-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_review_by_different_officer_accepted(self, api):
        """PRD §3.7: "On `ACCEPTED` the report moves `SUBMITTED` → `ACCEPTED`
        — its terminal state — with `reviewed_by_user_id` stamped."

        Design: Corner/validations/sod_same_user_review_returns_segregation_error
        """
        report = self._submitted_report_by(api, "dir-1")
        reviewed = validate_success(api.review_federal_report(
            report["id"], {"decision": "ACCEPTED"},
            make_federal_officer_headers("off-2")))
        assert reviewed["status"] == "ACCEPTED"
        assert reviewed["reviewed_by_user_id"] == "off-2"

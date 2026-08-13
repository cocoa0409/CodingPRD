"""Diversion reporting: round-per-source rollup, grade thresholds, zero-data
behavior, publish guards, supersession, and OCC on report creation."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_diversion_report,
    complete_run,
    create_active_program,
    create_report,
    create_serviced_booking,
    get_program,
    open_site,
    record_intake,
    register_household,
    schedule_run,
    set_clock,
    validate_error,
    validate_success,
)

PAST_WINDOW_END = "2027-01-20T00:00:00Z"


class TestRollupRounding:

    def _setup_rollup_scenario(self):
        """Two SERVICED bookings with actual_tons 0.0204 each; one RECORDED
        intake weighed 0.0300 t; one COMPLETED run diverting 0.063 t."""
        ctx = create_active_program()
        program, site, zone = ctx["program"], ctx["site"], ctx["zone"]
        open_site(site)
        h1 = register_household(program["id"], zone["id"])
        h2 = register_household(program["id"], zone["id"])
        create_serviced_booking(h1, zone["id"], tree_count=1,
                                size_class="MEDIUM", actual_tons=0.0204)
        create_serviced_booking(h2, zone["id"], tree_count=1,
                                size_class="MEDIUM", actual_tons=0.0204)
        record_intake(site["id"], tree_count=1, size_class="MEDIUM",
                      source_type="COMMERCIAL_LANDSCAPER", weighed_tons=0.03)
        run = schedule_run(program["id"], site["id"])
        complete_run(run, measured_input_tons=0.063,
                     measured_output_cy=0.126)
        return ctx

    def test_rollup_rounds_per_source_then_sums(self):
        """PRD section 3.8: "The rollup pins its rounding order: every source
        is rounded first, and only the rounded contributions are summed —
        summing raw figures first and rounding once at the end is the rejected
        alternative, because the two orders can produce different totals."
        PRD section 3.8: "The `collected_tons` is the sum of those rounded
        booking and intake contributions."

        Design: Difficulty/combinatorial_formula/diversion_rollup_round_per_source
        """
        ctx = self._setup_rollup_scenario()
        report = create_report(ctx["program"]["id"])
        assert_diversion_report(report)
        assert report["status"] == "DRAFT"
        # round3(0.0204) + round3(0.0204) + round3(0.0300) = 0.020+0.020+0.030
        # = 0.070; the rejected sum-then-round order would give
        # round3(0.0708) = 0.071.
        assert report["collected_tons"] == pytest.approx(0.07)
        # round3(0.063 - 0) over the single COMPLETED run
        assert report["diverted_tons"] == pytest.approx(0.063)
        assert report["disposed_tons"] == pytest.approx(0.007)

    def test_rollup_rate_and_grade_at_inclusive_threshold(self):
        """PRD section 3.8: "The `diversion_rate` is the diverted figure
        divided by the collected figure, rounded half-up to four decimal
        places — and is defined as exactly 0.0000 when nothing was collected
        at all. The `grade` is `NO_DATA` when the collected tonnage is zero;
        otherwise it is `A` when the rate reaches 0.9000, `B` when it falls
        short of that but reaches 0.7500, and `C` below that — both thresholds
        inclusive. The `below_target` flag is true exactly when the
        `diversion_rate` is strictly less than the program's
        `target_diversion_rate`."

        Design: Difficulty/combinatorial_formula/diversion_rollup_round_per_source
        """
        ctx = self._setup_rollup_scenario()
        report = create_report(ctx["program"]["id"])
        # round4(0.063 / 0.070) = 0.9000 — exactly the inclusive A threshold.
        assert report["diversion_rate"] == pytest.approx(0.9)
        assert report["grade"] == "A"
        assert report["below_target"] is False, \
            "0.9000 < target 0.9 is false"


class TestGradeBoundaries:

    def test_diversion_grade_b_at_exact_threshold(self):
        """PRD section 3.8: "otherwise it is `A` when the rate reaches
        0.9000, `B` when it falls short of that but reaches 0.7500, and `C`
        below that — both thresholds inclusive. The `below_target` flag is
        true exactly when the `diversion_rate` is strictly less than the
        program's `target_diversion_rate`."

        Design: Corner/calculations/diversion_grade_b_at_exact_threshold
        """
        ctx = create_active_program()
        program, site = ctx["program"], ctx["site"]
        open_site(site)
        record_intake(site["id"], tree_count=1, size_class="MEDIUM",
                      weighed_tons=0.1)
        run = schedule_run(program["id"], site["id"])
        complete_run(run, measured_input_tons=0.075, measured_output_cy=0.15)

        report = create_report(program["id"])
        assert report["collected_tons"] == pytest.approx(0.1)
        assert report["diverted_tons"] == pytest.approx(0.075)
        # round4(0.075 / 0.100) = 0.7500 — exactly the inclusive B threshold.
        assert report["diversion_rate"] == pytest.approx(0.75)
        assert report["grade"] == "B"
        assert report["below_target"] is True, "0.7500 < target 0.9"

    def test_diversion_rollup_zero_collection_no_data(self):
        """PRD section 3.8: "The `diversion_rate` is the diverted figure
        divided by the collected figure, rounded half-up to four decimal
        places — and is defined as exactly 0.0000 when nothing was collected
        at all. The `grade` is `NO_DATA` when the collected tonnage is zero".

        Design: Corner/calculations/diversion_rollup_zero_collection_no_data
        """
        ctx = create_active_program()
        report = create_report(ctx["program"]["id"])
        assert_diversion_report(report)
        assert report["collected_tons"] == pytest.approx(0.0)
        assert report["diverted_tons"] == pytest.approx(0.0)
        assert report["disposed_tons"] == pytest.approx(0.0)
        assert report["diversion_rate"] == pytest.approx(0.0)
        assert report["grade"] == "NO_DATA"
        assert report["below_target"] is True, "0.0000 < target 0.9"


class TestReportLifecycle:

    def test_report_publish_before_window_end_rejected(self):
        """PRD section 3.8: "Publishing moves a report `DRAFT → PUBLISHED` and
        is guarded twice: the clock must have passed the program's
        `window_end`, and no chipping run may remain in `SCHEDULED` for the
        program; either failure is rejected with
        `ERR_REPORT_NOT_PUBLISHABLE`."

        Design: Corner/validations/report_publish_before_window_end_rejected
        """
        ctx = create_active_program()
        report = create_report(ctx["program"]["id"])

        # The clock (2027-01-10) has not passed window_end (2027-01-16).
        set_clock("2027-01-10T00:00:00Z")
        resp = api_client.patch_diversion_report(
            report["id"], {"status": "PUBLISHED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_PUBLISHABLE)
        after = api_client.get_diversion_report(report["id"], ADMIN)
        assert after.json()["data"]["status"] == "DRAFT"

    def test_occ_report_create_supersede_and_stale(self):
        """PRD section 3.8: "creating a report increments the program's
        `version` by one, and any existing `PUBLISHED` report for the program
        is immediately moved to `SUPERSEDED`, its terminal state."
        PRD section 2.6: "Finally, generating a diversion report (`POST
        /diversion-reports`) supersedes the program's currently published
        report and therefore must carry `expected_program_version`; when it no
        longer matches the program's current version, the client's basis for
        supersession is stale — another writer may just have created a report
        that superseded the prior one — and the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_report_create_supersede_and_stale
        """
        ctx = create_active_program()
        program_id = ctx["program"]["id"]

        # Past window_end with no SCHEDULED runs: R1 can be published.
        set_clock(PAST_WINDOW_END)
        r1 = create_report(program_id)
        published = api_client.patch_diversion_report(
            r1["id"], {"status": "PUBLISHED"}, ADMIN)
        assert validate_success(published, 200)["status"] == "PUBLISHED"

        # R2 with the fresh program version supersedes R1.
        version_before_r2 = get_program(program_id)["version"]
        r2_resp = api_client.create_diversion_report(
            {"program_id": program_id,
             "expected_program_version": version_before_r2}, ADMIN)
        r2 = validate_success(r2_resp, 201)
        assert r2["status"] == "DRAFT"
        r1_after = api_client.get_diversion_report(r1["id"], ADMIN)
        assert r1_after.json()["data"]["status"] == "SUPERSEDED"

        # R3 carrying R2's pre-creation program version is stale.
        stale_resp = api_client.create_diversion_report(
            {"program_id": program_id,
             "expected_program_version": version_before_r2}, ADMIN)
        validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION)
        data, meta = _list_reports(program_id)
        assert len(data) == 2, "the stale create must not persist a report"


def _list_reports(program_id):
    resp = api_client.list_diversion_reports(ADMIN,
                                             params={"program_id": program_id})
    body = resp.json()
    return body["data"], body["meta"]

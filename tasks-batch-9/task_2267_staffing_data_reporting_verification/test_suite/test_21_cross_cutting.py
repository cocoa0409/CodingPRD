"""Concerns that cut across the whole quarter: version tokens on guarded
writes, the risk-floor boundary, ancestor rollups, and filtered listings."""

from test_helpers import (
    ApiErrorId,
    AppealGrounds,
    AppealStatus,
    AuditReadinessVariant,
    EntryStatus,
    MeasureScenario,
    SubmissionScenario,
    SubmissionStatus,
    TEST_DEFAULTS,
    allocation_line,
    approx_hours,
    approx_ratio,
    approx_score,
    assert_audit_readiness_read,
    build_draft_submission,
    build_supported_quarter,
    create_hour_entry_payload,
    create_rating_appeal_payload,
    replace_allocations_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CREATION_TIME_TOKEN = 1
STALE_APPEAL_NARRATIVE = "Filed against the pre-publication view of the measure."
REFILED_APPEAL_NARRATIVE = "Refiled against the published view of the measure."
SHORT_SHIFT_DOCUMENT_REF = "TC-K0701"


class TestStaleTokensAreRefusedOnEveryVersionedWrite:
    def test_01_a_token_captured_before_the_intervening_writes_is_refused(
        self, api, client
    ):
        """PRD: "`POST /hour-entries` requires `expected_submission_version` as a
        non-optional body field carrying the client's last observed `version` of the target
        `QuarterlySubmission`. If that value does not equal the submission's current
        `version`, the create is rejected with `ERR_STALE_SUBMISSION_VERSION` and HTTP
        412." PRD: "`PUT /hour-entries/{id}/allocations` requires
        `expected_submission_version` on the same terms and rejects a mismatch with
        `ERR_STALE_SUBMISSION_VERSION` and HTTP 412." PRD: "`POST /rating-appeals` requires
        `expected_measure_version` as a non-optional body field carrying the client's last
        observed `version` of the `StaffingMeasure` being appealed. A mismatch is rejected
        with `ERR_STALE_MEASURE_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_versions_rejected_on_every_occ_write
        """
        scenario = build_supported_quarter(client)
        universe = scenario.universe
        entry = scenario.entries[0]
        current_version = scenario.refresh()["version"]
        assert current_version > CREATION_TIME_TOKEN

        stale_create = api.create_hour_entry(
            create_hour_entry_payload(
                scenario.id,
                universe.w_rn["id"],
                universe.jc_rn["id"],
                CREATION_TIME_TOKEN,
                work_date="2026-04-09",
            ),
            universe.coord_headers,
        )
        validate_error(
            stale_create,
            ApiErrorId.ERR_STALE_SUBMISSION_VERSION.value,
            expected_status=412,
        )

        stale_replacement = api.replace_hour_entry_allocations(
            entry["id"],
            replace_allocations_payload(
                [
                    allocation_line(universe.jc_rn["id"], 50.00),
                    allocation_line(universe.jc_admin["id"], 50.00),
                ],
                CREATION_TIME_TOKEN,
            ),
            universe.coord_headers,
        )
        validate_error(
            stale_replacement,
            ApiErrorId.ERR_STALE_SUBMISSION_VERSION.value,
            expected_status=412,
        )

        stored_entry = validate_success(
            api.get_hour_entry(entry["id"], universe.coord_headers)
        )
        assert stored_entry["allocation_revision"] == 0
        assert stored_entry["direct_care_hours"] == approx_hours(8.00)

        untouched = scenario.refresh()
        assert untouched["version"] == current_version
        assert untouched["total_direct_care_hours"] == approx_hours(8.00)

        scenario.validate()
        scenario.submit()
        scenario.accept()
        measure = MeasureScenario(scenario)
        computation_time_version = measure.measure["version"]
        published = measure.publish()
        assert published["version"] > computation_time_version

        stale_appeal = api.create_rating_appeal(
            create_rating_appeal_payload(
                measure.id,
                computation_time_version,
                grounds=AppealGrounds.MEASURE_CALCULATION_ERROR.value,
                narrative=STALE_APPEAL_NARRATIVE,
            ),
            universe.fac_admin_headers,
        )
        validate_error(
            stale_appeal,
            ApiErrorId.ERR_STALE_MEASURE_VERSION.value,
            expected_status=412,
        )

        refiled = validate_success(
            api.create_rating_appeal(
                create_rating_appeal_payload(
                    measure.id,
                    published["version"],
                    grounds=AppealGrounds.MEASURE_CALCULATION_ERROR.value,
                    narrative=REFILED_APPEAL_NARRATIVE,
                ),
                universe.fac_admin_headers,
            ),
            expected_status=201,
        )
        assert refiled["status"] == AppealStatus.SUBMITTED.value


class TestAuditRiskFloorBoundary:
    def test_01_a_score_of_exactly_seventy_is_not_at_risk_while_sixty_nine_ninety_seven_is(
        self, api, client, reading_auditor_headers
    ):
        """PRD: "The score is then 100 multiplied by the sum of the support ratio
        weighted at 0.50, the vendor attestation ratio weighted at 0.30, and the census
        reconciled ratio weighted at 0.20, with that single product rounded half up to 2
        decimal places. A submission is at risk when the score is strictly below 70.00, so
        a score of exactly 70.00 is not at risk." PRD: "The **full** reading takes every
        `ACTIVE` hour entry of the submission, with no truncation and therefore no
        dependence on ordering." PRD: "The shift length in hours, stored as `raw_hours`, is
        derived from the two times of day: convert each to a count of minutes since
        midnight by multiplying its hour part by 60 and adding its minute part, subtract the
        start from the end to get the elapsed minutes, divide by 60, and round half up to 2
        decimal places."

        Design: Corner/cross_cutting_complexity_layers/audit_risk_floor_boundary_seventy_exact_versus_just_below
        """
        on_the_floor = build_draft_submission(client)
        universe = on_the_floor.universe
        supported = on_the_floor.capture_supported_hours(document_ref="TC-B0401")
        unverified = on_the_floor.capture_hours(
            work_date="2026-04-02", shift_start="07:00", shift_end="19:00"
        )
        on_the_floor.report_reconciled_census("2026-04-01", 5, 5)
        on_the_floor.verify_hours(supported["id"])
        assert unverified["direct_care_hours"] == approx_hours(12.00)

        later_period = universe.open_period(
            period_code=TEST_DEFAULTS["SECOND_PERIOD_CODE"],
            start_date=TEST_DEFAULTS["SECOND_PERIOD_START"],
            end_date=TEST_DEFAULTS["SECOND_PERIOD_END"],
            submission_deadline=TEST_DEFAULTS["SECOND_PERIOD_DEADLINE"],
            correction_window_end=TEST_DEFAULTS["SECOND_PERIOD_CORRECTION_END"],
        )
        below_the_floor = SubmissionScenario(
            universe, reporting_period_id=later_period["id"]
        )
        short_shift = below_the_floor.capture_supported_hours(
            work_date="2026-07-01",
            shift_start="07:00",
            shift_end="14:59",
            paid_hours=7.98,
            document_ref=SHORT_SHIFT_DOCUMENT_REF,
        )
        assert short_shift["raw_hours"] == approx_hours(7.98)
        below_the_floor.capture_hours(
            work_date="2026-07-02", shift_start="07:00", shift_end="19:00"
        )
        below_the_floor.report_reconciled_census("2026-07-01", 5, 5)
        below_the_floor.verify_hours(short_shift["id"])

        exactly_seventy = validate_success(
            api.get_audit_readiness(
                universe.facility_id,
                reading_auditor_headers,
                {
                    "submission_id": on_the_floor.id,
                    "variant": AuditReadinessVariant.FULL.value,
                },
            )
        )
        assert_audit_readiness_read(
            exactly_seventy, AuditReadinessVariant.FULL.value
        )
        assert exactly_seventy["considered_entry_count"] == 2
        assert exactly_seventy["considered_hours"] == approx_hours(20.00)
        assert exactly_seventy["supported_hours"] == approx_hours(8.00)
        assert exactly_seventy["support_ratio"] == approx_ratio(0.4000)
        assert exactly_seventy["vendor_attestation_ratio"] == approx_ratio(1.0000)
        assert exactly_seventy["census_reconciled_ratio"] == approx_ratio(1.0000)
        assert exactly_seventy["score"] == approx_score(70.00)
        assert exactly_seventy["at_risk"] is False

        just_below = validate_success(
            api.get_audit_readiness(
                universe.facility_id,
                reading_auditor_headers,
                {
                    "submission_id": below_the_floor.id,
                    "variant": AuditReadinessVariant.FULL.value,
                },
            )
        )
        assert_audit_readiness_read(just_below, AuditReadinessVariant.FULL.value)
        assert just_below["considered_hours"] == approx_hours(19.98)
        assert just_below["supported_hours"] == approx_hours(7.98)
        assert just_below["support_ratio"] == approx_ratio(0.3994)
        assert just_below["score"] == approx_score(69.97)
        assert just_below["at_risk"] is True


class TestAncestorRollupsTrackDifferentQuantities:
    def test_01_the_worker_total_follows_raw_hours_while_the_rating_waits_for_publication(
        self, api, client
    ):
        """PRD: "In the same pass, `reported_hours_total` is refreshed for every worker
        referenced by the active hour population, as the sum of `raw_hours` over that
        worker's active entries in the submission, rounded half up to 2 decimal places."
        PRD: "Replacement re-runs the classification above from scratch on the stored
        `raw_hours`, increments `allocation_revision` by one". PRD: "The void removes the
        entry's hours from every submission rollup, refreshes the owning worker's
        `reported_hours_total`, reverts a `VALIDATED` parent submission to `DRAFT`, and
        increments the submission's `version` by one." PRD: "Publishing stamps
        `published_at` with the logical clock instant, sets `appeal_deadline` to
        `published_at` plus 30 calendar days, and refreshes the facility's
        `latest_staffing_rating`."

        Design: Corner/cross_cutting_complexity_layers/worker_and_facility_derived_totals_track_create_update_and_void
        """
        scenario = build_draft_submission(client)
        universe = scenario.universe
        supported = scenario.capture_supported_hours(document_ref="TC-B0401")
        big_shift = scenario.capture_hours(
            work_date="2026-04-02", shift_start="07:00", shift_end="19:00"
        )
        census_day = scenario.report_census("2026-04-01", 5, 5)

        worker = validate_success(
            api.get_worker(universe.w_rn["id"], universe.coord_headers)
        )
        assert worker["reported_hours_total"] == approx_hours(20.00)
        assert scenario.refresh()["total_direct_care_hours"] == approx_hours(20.00)

        replaced = scenario.replace_allocations(
            big_shift["id"],
            [
                allocation_line(universe.jc_rn["id"], 50.00),
                allocation_line(universe.jc_admin["id"], 50.00),
            ],
        )
        assert replaced["direct_care_hours"] == approx_hours(6.00)
        assert replaced["excluded_hours"] == approx_hours(6.00)
        assert scenario.refresh()["total_direct_care_hours"] == approx_hours(14.00)
        worker = validate_success(
            api.get_worker(universe.w_rn["id"], universe.coord_headers)
        )
        assert worker["reported_hours_total"] == approx_hours(20.00)

        scenario.void_hours(big_shift["id"])
        worker = validate_success(
            api.get_worker(universe.w_rn["id"], universe.coord_headers)
        )
        assert worker["reported_hours_total"] == approx_hours(8.00)
        after_void = scenario.refresh()
        assert after_void["total_raw_hours"] == approx_hours(8.00)
        assert after_void["total_direct_care_hours"] == approx_hours(8.00)

        scenario.reconcile_census(census_day["id"])
        scenario.verify_hours(supported["id"])
        scenario.validate()
        scenario.submit()
        accepted = scenario.accept()
        assert accepted["status"] == SubmissionStatus.ACCEPTED.value

        measure = MeasureScenario(scenario)
        before_publication = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert before_publication["latest_staffing_rating"] is None

        published = measure.publish()
        after_publication = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert after_publication["latest_staffing_rating"] == published[
            "staffing_rating"
        ]
        assert after_publication["latest_staffing_rating"] == 1


class TestHourEntryListingAcrossAVoid:
    def test_01_entry_status_is_a_filter_and_the_page_counts_follow_it(
        self, api, client
    ):
        """PRD: "The `meta` object of every list response carries `limit`, `offset`,
        `total_count`, and `has_more`, where `total_count` is the size of the filtered
        result set before the window is applied and `has_more` indicates whether rows
        remain beyond the window." PRD: "Voiding moves `entry_status` from `ACTIVE` to
        `VOID`, which is terminal". PRD: `GET /hour-entries` "Lists hour entries,
        filterable by submission, facility, period, worker, category, vendor batch, payroll
        document, date, and both status dimensions."

        Design: Corner/cross_cutting_complexity_layers/hour_entry_listing_filters_and_pages_consistently_across_a_void
        """
        scenario = build_draft_submission(client)
        universe = scenario.universe
        scenario.capture_supported_hours(document_ref="TC-B0401")
        second = scenario.capture_hours(work_date="2026-04-02")
        third = scenario.capture_hours(work_date="2026-04-03")

        first_page, first_meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers,
                {
                    "submission_id": scenario.id,
                    "entry_status": EntryStatus.ACTIVE.value,
                    "limit": 2,
                    "offset": 0,
                },
            )
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers,
                {
                    "submission_id": scenario.id,
                    "entry_status": EntryStatus.ACTIVE.value,
                    "limit": 2,
                    "offset": 2,
                },
            )
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False

        scenario.void_hours(third["id"])

        active_page, active_meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers,
                {
                    "submission_id": scenario.id,
                    "entry_status": EntryStatus.ACTIVE.value,
                    "limit": 2,
                    "offset": 0,
                },
            )
        )
        assert len(active_page) == 2
        assert active_meta["total_count"] == 2
        assert active_meta["has_more"] is False
        assert third["id"] not in [row["id"] for row in active_page]

        void_page, void_meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers,
                {
                    "submission_id": scenario.id,
                    "entry_status": EntryStatus.VOID.value,
                    "limit": 2,
                    "offset": 0,
                },
            )
        )
        assert len(void_page) == 1
        assert void_meta["total_count"] == 1
        assert void_page[0]["id"] == third["id"]

        composed, composed_meta = validate_paginated(
            api.list_hour_entries(
                universe.coord_headers,
                {
                    "submission_id": scenario.id,
                    "worker_id": universe.w_rn["id"],
                    "work_date": "2026-04-02",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert len(composed) == 1
        assert composed_meta["total_count"] == 1
        assert composed[0]["id"] == second["id"]

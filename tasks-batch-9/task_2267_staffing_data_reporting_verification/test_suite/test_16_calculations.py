"""Hand-computable arithmetic: the hours-per-resident-day readings, the
audit-readiness weighting, the amendment surcharge, and the star assignment."""

from test_helpers import (
    AuditReadinessVariant,
    AuditStatus,
    CaseTriggerReason,
    HprdVariant,
    MeasureVariant,
    PublicationStatus,
    SubmissionStatus,
    allocation_line,
    approx_hours,
    approx_ratio,
    approx_score,
    assert_audit_readiness_read,
    assert_hprd_read,
    assert_staffing_measure,
    build_draft_submission,
    create_staffing_measure_payload,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import ACCEPTING_AUDITOR_USER_ID


class TestHprdSplitCreditAndWeekendSplit:
    def test_01_the_weekend_metric_divides_only_saturday_hours_by_only_saturday_days(
        self, api, draft_submission
    ):
        """PRD: "`weekend_total_nurse_hprd` is the weekend direct-care hours divided by
        the weekend denominator, rounded half up to 4 decimal places". PRD: "compute that
        line's direct-care contribution as `raw_hours` multiplied by the line's `percent`
        divided by 100, multiplied by the credit fraction, **then rounded half up to 2
        decimal places**." PRD: "`is_weekend` is set to true when `work_date` falls on a
        Saturday or a Sunday and false otherwise."

        Design: Corner/calculations/hprd_correct_result_with_split_role_credit_and_weekend_split
        """
        scenario = draft_submission
        universe = scenario.universe

        weekday = scenario.capture_hours(work_date="2026-04-01")
        saturday = scenario.capture_hours(
            work_date="2026-04-04",
            job_category_id=universe.jc_split["id"],
            allocations=[allocation_line(universe.jc_split["id"], 100.00)],
        )
        assert weekday["direct_care_hours"] == approx_hours(8.00)
        assert weekday["excluded_hours"] == approx_hours(0.00)
        assert weekday["is_weekend"] is False
        assert saturday["direct_care_hours"] == approx_hours(4.80)
        assert saturday["excluded_hours"] == approx_hours(3.20)
        assert saturday["is_weekend"] is True

        scenario.report_census("2026-04-01", 5, 5)
        scenario.report_census("2026-04-04", 5, 5)

        data = validate_success(
            api.get_submission_hprd(scenario.id, universe.coord_headers)
        )

        assert_hprd_read(data, HprdVariant.AS_SUBMITTED.value)
        assert data["total_direct_care_hours"] == approx_hours(12.80)
        assert data["total_rn_hours"] == approx_hours(12.80)
        assert data["weekend_direct_care_hours"] == approx_hours(4.80)
        assert data["resident_days"] == 10
        assert data["weekend_resident_days"] == 5
        assert data["total_nurse_hprd"] == approx_ratio(1.2800)
        assert data["rn_hprd"] == approx_ratio(1.2800)
        assert data["weekend_total_nurse_hprd"] == approx_ratio(0.9600)
        assert data["implausible"] is False


class TestHprdRoundingAndNullWeekendMetric:
    def test_01_a_non_terminating_quotient_rounds_half_up_to_four_places(
        self, api, draft_submission
    ):
        """PRD: "`total_nurse_hprd` is the total direct-care hours divided by the
        resident-day denominator, rounded half up to 4 decimal places, or null when that
        denominator is 0". PRD: "`weekend_hprd_reported` is null when the weekend
        resident-day total is 0".

        Design: Corner/calculations/hprd_rounds_half_up_to_four_decimals_and_nulls_weekend_metric
        """
        scenario = draft_submission
        universe = scenario.universe
        scenario.capture_hours(work_date="2026-04-01")
        scenario.report_census("2026-04-01", 1, 1)
        scenario.report_census("2026-04-02", 1, None)
        scenario.report_census("2026-04-03", 1, None)

        data = validate_success(
            api.get_submission_hprd(scenario.id, universe.coord_headers)
        )

        assert data["resident_days"] == 3
        assert data["total_direct_care_hours"] == approx_hours(8.00)
        assert data["total_nurse_hprd"] == approx_ratio(2.6667)
        assert data["rn_hprd"] == approx_ratio(2.6667)
        assert data["weekend_resident_days"] == 0
        assert data["weekend_total_nurse_hprd"] is None

        assert scenario.refresh()["weekend_hprd_reported"] is None


class TestAuditReadinessRatioRounding:
    def test_01_each_ratio_is_rounded_to_four_places_before_it_is_weighted(
        self, api, client, reading_auditor_headers
    ):
        """PRD: "Each of the three ratios is rounded to 4 decimal places before it is
        weighted. The score is then 100 multiplied by the sum of the support ratio
        weighted at 0.50, the vendor attestation ratio weighted at 0.30, and the census
        reconciled ratio weighted at 0.20, with that single product rounded half up to 2
        decimal places. A submission is at risk when the score is strictly below 70.00".
        PRD: "The **full** reading takes every `ACTIVE` hour entry of the submission,
        with no truncation".

        Design: Corner/calculations/audit_support_score_rounds_each_ratio_before_weighting
        """
        scenario = build_draft_submission(client)
        universe = scenario.universe
        supported = scenario.capture_supported_hours(
            work_date="2026-04-01", document_ref="TC-G0401"
        )
        for day in ("2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05", "2026-04-06"):
            scenario.capture_hours(work_date=day)
        scenario.report_census("2026-04-01", 5, 5)
        scenario.verify_hours(supported["id"])

        data = validate_success(
            api.get_audit_readiness(
                universe.facility_id,
                reading_auditor_headers,
                {
                    "submission_id": scenario.id,
                    "variant": AuditReadinessVariant.FULL.value,
                },
            )
        )

        assert_audit_readiness_read(data, AuditReadinessVariant.FULL.value)
        assert data["considered_entry_count"] == 6
        assert data["considered_hours"] == approx_hours(48.00)
        assert data["supported_hours"] == approx_hours(8.00)
        assert data["support_ratio"] == approx_ratio(0.1667)
        assert data["vendor_attestation_ratio"] == approx_ratio(1.0000)
        assert data["census_reconciled_ratio"] == approx_ratio(0.0000)
        assert data["score"] == approx_score(38.34)
        assert data["at_risk"] is True


class TestFirstAmendmentBaseFee:
    def test_01_the_first_reopen_before_the_deadline_costs_exactly_the_base_fee(
        self, api, accepted_quarter
    ):
        """PRD: the base fee "is 25000 cents plus 2500 cents for each amendment beyond
        the first, that is, 2500 cents multiplied by one less than the prospective
        amendment index." PRD: "take the whole seconds from that deadline to the current
        logical clock instant; if that is zero or negative there are no late days". PRD:
        reopening "clears both `validated_by_worker_id` and `attested_by_worker_id` so
        the segregation-of-duties pairing must be re-established".

        Design: Corner/calculations/first_reopen_applies_base_amendment_fee_with_zero_late_days
        """
        scenario = accepted_quarter
        universe = scenario.universe

        data = scenario.reopen()

        assert data["status"] == SubmissionStatus.DRAFT.value
        assert data["amendment_index"] == 1
        assert data["amendment_surcharge_cents"] == 25000
        assert data["waived_surcharge_cents"] == 0
        assert data["validated_by_worker_id"] is None
        assert data["attested_by_worker_id"] is None

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["outstanding_surcharge_cents"] == 25000


class TestZeroRnDayOverride:
    def test_01_four_days_with_no_rn_hours_force_a_one_star_rating(
        self, api, client, cms_publisher_headers
    ):
        """PRD: "Step four is the zero-RN-day override, applied last and
        unconditionally. `days_with_zero_rn_hours` is the count of the source
        submission's census days in `REPORTED`, `RECONCILED`, or `DISPUTED` whose
        `census_date` has no `ACTIVE` hour entry of that submission carrying `rn_hours`
        greater than 0.00. When that count reaches 4 or more, `staffing_rating` is forced
        to 1 regardless of everything computed above". PRD: "when it is exactly 2.4000 or
        greater, the star is unchanged."

        Design: Corner/calculations/zero_rn_day_override_beats_tier_and_weekend_steps
        """
        scenario = build_draft_submission(client)
        saturday = scenario.capture_supported_hours(
            work_date="2026-04-04", document_ref="TC-Z0404"
        )
        sunday = scenario.capture_supported_hours(
            work_date="2026-04-05", document_ref="TC-Z0405"
        )
        for day in (
            "2026-04-04",
            "2026-04-05",
            "2026-04-06",
            "2026-04-07",
            "2026-04-08",
            "2026-04-09",
        ):
            scenario.report_reconciled_census(day, 1, 1)
        scenario.verify_hours(saturday["id"])
        scenario.verify_hours(sunday["id"])
        scenario.validate()
        scenario.submit()
        scenario.accept()

        data = validate_success(
            api.create_staffing_measure(
                create_staffing_measure_payload(scenario.id), cms_publisher_headers
            ),
            expected_status=201,
        )

        assert_staffing_measure(data)
        assert data["total_nurse_hprd"] == approx_ratio(2.6667)
        assert data["rn_hprd"] == approx_ratio(2.6667)
        assert data["total_nurse_points"] == 3
        assert data["rn_points"] == 5
        assert data["weekend_total_nurse_hprd"] == approx_ratio(8.0000)
        assert data["days_with_zero_rn_hours"] == 4
        assert data["staffing_rating"] == 1
        assert data["publication_status"] == PublicationStatus.PROVISIONAL.value
        assert data["audit_status"] == AuditStatus.NOT_AUDITED.value


class TestVariantSelectionOnPersistedWrites:
    def test_01_validate_and_measure_both_persist_the_as_submitted_reading(
        self, api, client, cms_publisher_headers
    ):
        """PRD: "The validation pass writes the as-submitted `total_nurse_hprd` to
        `hprd_reported`". PRD: the new measure "sets `measure_variant` to `AS_SUBMITTED`
        ... It then computes `total_nurse_hprd`, `rn_hprd`, and
        `weekend_total_nurse_hprd` under the as-submitted reading described in §3.6".
        PRD: "Under the **audit-adjusted** reading, the numerator population is narrowed
        to active entries whose `verification_status` is `SUPPORTED`".

        Design: Corner/calculations/validate_and_measure_both_select_the_as_submitted_variant
        """
        scenario = build_draft_submission(client)
        universe = scenario.universe
        scenario.capture_supported_hours(work_date="2026-04-01", document_ref="TC-V0401")
        scenario.report_reconciled_census("2026-04-01", 5, 5)

        validated = scenario.validate()
        assert validated["hprd_reported"] == approx_ratio(1.6000)

        adjusted = validate_success(
            api.get_submission_hprd(
                scenario.id,
                universe.coord_headers,
                {"variant": HprdVariant.AUDIT_ADJUSTED.value},
            )
        )
        assert_hprd_read(adjusted, HprdVariant.AUDIT_ADJUSTED.value)
        assert adjusted["total_direct_care_hours"] == approx_hours(0.00)
        assert adjusted["total_nurse_hprd"] == approx_ratio(0.0000)

        scenario.submit()
        accepted = scenario.accept()
        assert accepted["accepted_by_user_id"] == ACCEPTING_AUDITOR_USER_ID
        assert accepted["audit_support_score"] == approx_score(50.00)

        cases, meta = validate_paginated(
            api.list_discrepancy_cases(
                universe.admin_headers, {"facility_id": scenario.facility_id}
            )
        )
        assert meta["total_count"] == 1
        assert (
            cases[0]["trigger_reason"]
            == CaseTriggerReason.AUDIT_SCORE_BELOW_FLOOR.value
        )
        assert cases[0]["auto_opened"] is True

        measure = validate_success(
            api.create_staffing_measure(
                create_staffing_measure_payload(scenario.id), cms_publisher_headers
            ),
            expected_status=201,
        )
        assert measure["measure_variant"] == MeasureVariant.AS_SUBMITTED.value
        assert measure["total_nurse_hprd"] == approx_ratio(1.6000)
        assert measure["staffing_rating"] == 1

"""Writes on one entity gated by the state of a different entity."""

import pytest

from test_helpers import (
    ApiErrorId,
    AppealGrounds,
    AppealStatus,
    CaseScenario,
    CaseStatus,
    CaseTriggerReason,
    FacilityPosture,
    MeasureScenario,
    PublicationStatus,
    SubmissionStatus,
    assert_instant_equals,
    build_accepted_quarter,
    build_validated_quarter,
    create_rating_appeal_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

APPEAL_NARRATIVE = (
    "The weekend downgrade was applied to a period with no weekend census."
)


@pytest.fixture
def quarter_under_hold(client):
    """A VALIDATED quarter whose facility has been pulled into `AUDIT_HOLD` by an
    open census investigation."""
    scenario = build_validated_quarter(client)
    case = CaseScenario(
        scenario,
        trigger_reason=CaseTriggerReason.CENSUS_MISMATCH.value,
        detail="Reported census for 2026-04-01 conflicts with the state register.",
    )
    return scenario, case


@pytest.fixture
def provisional_measure_scenario(client):
    """An accepted quarter and the `PROVISIONAL` measure computed from it."""
    scenario = build_accepted_quarter(client)
    return scenario, MeasureScenario(scenario)


class TestAttestationGatedOnFacilityPosture:
    def test_01_an_open_investigation_blocks_the_attestation(
        self, api, quarter_under_hold
    ):
        """PRD: "`posture` is `SANCTIONED` when `substantiated_case_count` is at
        least 1; otherwise `AUDIT_HOLD` when `open_case_count` is at least 1;
        otherwise `REPORTING_OPEN`." PRD: attestation "requires ... the facility's
        `posture` to be exactly `REPORTING_OPEN` — an `AUDIT_HOLD` facility is
        refused with `ERR_FACILITY_UNDER_HOLD`".

        Design: Difficulty/cross_entity_state_dependency/submit_gated_on_facility_posture_from_open_discrepancy_case
        """
        scenario, _ = quarter_under_hold
        universe = scenario.universe

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["posture"] == FacilityPosture.AUDIT_HOLD.value
        assert facility["open_case_count"] == 1

        response = api.submit_submission(scenario.id, universe.fac_admin_headers)
        validate_error(response, ApiErrorId.ERR_FACILITY_UNDER_HOLD.value)

    def test_02_the_blocked_quarter_stays_validated_with_no_fatal_finding(
        self, api, quarter_under_hold
    ):
        """PRD: attestation "moves the submission from `VALIDATED` to `SUBMITTED`"
        and separately "requires ... `open_fatal_finding_count` to be exactly 0
        (`ERR_FATAL_FINDINGS_OPEN`)". The refusal is the posture gate, not the
        finding gate, and it leaves the quarter where it was.

        Design: Difficulty/cross_entity_state_dependency/submit_gated_on_facility_posture_from_open_discrepancy_case
        """
        scenario, _ = quarter_under_hold
        api.submit_submission(scenario.id, scenario.universe.fac_admin_headers)

        data = scenario.refresh()
        assert data["status"] == SubmissionStatus.VALIDATED.value
        assert data["open_fatal_finding_count"] == 0
        assert data["attested_by_worker_id"] is None

    def test_03_dismissing_the_investigation_returns_the_facility_to_reporting_open(
        self, api, quarter_under_hold
    ):
        """PRD: "**Dismissal** is permitted only from `UNDER_REVIEW`, records the
        supplied `resolution_note`, moves `status` to the terminal `DISMISSED`, ...
        and re-derives the facility's `posture` and `open_case_count` — which drops
        an `AUDIT_HOLD` facility back to `REPORTING_OPEN` if that was its last open
        case and it has no substantiated one."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_on_facility_posture_from_open_discrepancy_case
        """
        scenario, case = quarter_under_hold
        universe = scenario.universe

        case.request_info("Send the state register extract for 2026-04-01.")
        case.respond("Register extract attached; our count of 5 is correct.")
        closed = case.dismiss("Facility count confirmed against the register.")
        assert closed["status"] == CaseStatus.DISMISSED.value

        facility = validate_success(
            api.get_facility(universe.facility_id, universe.coord_headers)
        )
        assert facility["posture"] == FacilityPosture.REPORTING_OPEN.value
        assert facility["open_case_count"] == 0
        assert facility["substantiated_case_count"] == 0

    def test_04_the_same_attestation_then_succeeds(self, api, quarter_under_hold):
        """PRD: attestation "records the acting worker's id as
        `attested_by_worker_id`, stamps `submitted_at` with the logical clock
        instant, and increments `version` by one."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_on_facility_posture_from_open_discrepancy_case
        """
        scenario, case = quarter_under_hold
        universe = scenario.universe
        case.request_info("Send the state register extract for 2026-04-01.")
        case.respond("Register extract attached; our count of 5 is correct.")
        case.dismiss("Facility count confirmed against the register.")

        data = validate_success(
            api.submit_submission(scenario.id, universe.fac_admin_headers)
        )

        assert data["status"] == SubmissionStatus.SUBMITTED.value
        assert data["attested_by_worker_id"] == universe.w_admin["id"]


class TestAppealGatedOnMeasurePublication:
    def test_01_a_provisional_measure_cannot_be_appealed(
        self, api, provisional_measure_scenario
    ):
        """PRD: "Filing requires the referenced measure's `publication_status` to be
        `PUBLISHED` (`ERR_MEASURE_NOT_PUBLISHED`)".

        Design: Difficulty/cross_entity_state_dependency/appeal_creation_gated_on_measure_publication_status
        """
        scenario, measure = provisional_measure_scenario

        response = api.create_rating_appeal(
            create_rating_appeal_payload(
                measure.id,
                measure.version,
                grounds=AppealGrounds.MEASURE_CALCULATION_ERROR.value,
                narrative=APPEAL_NARRATIVE,
            ),
            scenario.universe.fac_admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_MEASURE_NOT_PUBLISHED.value)

        appeals, _ = validate_paginated(
            api.list_rating_appeals(scenario.universe.fac_admin_headers, {"limit": 100})
        )
        assert appeals == []

    def test_02_an_unpublished_measure_carries_no_appeal_window(
        self, provisional_measure_scenario
    ):
        """PRD: the new measure "sets ... `published_at` and `appeal_deadline` to
        null, `has_open_appeal` to false".

        Design: Difficulty/cross_entity_state_dependency/appeal_creation_gated_on_measure_publication_status
        """
        _, measure = provisional_measure_scenario

        data = measure.refresh()
        assert data["publication_status"] == PublicationStatus.PROVISIONAL.value
        assert data["appeal_deadline"] is None
        assert data["has_open_appeal"] is False

    def test_03_publishing_opens_a_thirty_day_appeal_window(
        self, provisional_measure_scenario
    ):
        """PRD: "**Publishing** moves it from `PROVISIONAL` to `PUBLISHED`" and
        "Publishing stamps `published_at` with the logical clock instant, sets
        `appeal_deadline` to `published_at` plus 30 calendar days, and refreshes the
        facility's `latest_staffing_rating`." PRD: "Before any clock write, the
        logical clock reads exactly `2026-08-01T00:00:00Z`".

        Design: Difficulty/cross_entity_state_dependency/appeal_creation_gated_on_measure_publication_status
        """
        _, measure = provisional_measure_scenario

        data = measure.publish()

        assert data["publication_status"] == PublicationStatus.PUBLISHED.value
        assert_instant_equals(data["published_at"], "2026-08-01T00:00:00Z", "published_at")
        assert_instant_equals(
            data["appeal_deadline"], "2026-08-31T00:00:00Z", "appeal_deadline"
        )

    def test_04_the_identical_filing_is_accepted_once_the_measure_is_published(
        self, api, provisional_measure_scenario
    ):
        """PRD: "The appeal copies `facility_id` from the appealed measure, records
        the acting worker's id as `filed_by_worker_id`, enters `status` `SUBMITTED`
        with `decided_by_user_id`, `decision_note`, and `decided_at` null and
        `surcharge_waived_cents` at 0, sets the appealed measure's `has_open_appeal`
        to true, and increments that measure's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/appeal_creation_gated_on_measure_publication_status
        """
        scenario, measure = provisional_measure_scenario
        measure.publish()

        data = validate_success(
            api.create_rating_appeal(
                create_rating_appeal_payload(
                    measure.id,
                    measure.version,
                    grounds=AppealGrounds.MEASURE_CALCULATION_ERROR.value,
                    narrative=APPEAL_NARRATIVE,
                ),
                scenario.universe.fac_admin_headers,
            ),
            expected_status=201,
        )

        assert data["status"] == AppealStatus.SUBMITTED.value
        assert data["facility_id"] == scenario.facility_id
        assert data["filed_by_worker_id"] == scenario.universe.w_admin["id"]
        assert data["surcharge_waived_cents"] == 0
        assert measure.refresh()["has_open_appeal"] is True

    def test_05_publication_relabels_the_facility_with_the_measures_rating(
        self, api, provisional_measure_scenario
    ):
        """PRD: "`latest_staffing_rating` is the `staffing_rating` of the facility's
        `StaffingMeasure` whose `publication_status` is `PUBLISHED`, choosing the
        candidate with the latest `published_at` and breaking ties by the latest
        `created_at`; when no published measure remains for the facility,
        `latest_staffing_rating` is null."

        Design: Difficulty/cross_entity_state_dependency/appeal_creation_gated_on_measure_publication_status
        """
        scenario, measure = provisional_measure_scenario
        published = measure.publish()

        facility = validate_success(
            api.get_facility(
                scenario.facility_id, scenario.universe.coord_headers
            )
        )
        assert facility["latest_staffing_rating"] == published["staffing_rating"]

"""The declared consistency model: a cascade fired by one write is already
visible to the very next read, with no settling delay."""

from test_helpers import (
    CaseScenario,
    CaseStatus,
    CaseTriggerReason,
    FacilityPosture,
    FindingCode,
    FindingSeverity,
    FindingStatus,
    SubmissionScenario,
    SubmissionStatus,
    TEST_DEFAULTS,
    build_accepted_quarter,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CASE_AUDITOR_USER_ID

CASE_DETAIL = "The reported night hours are not corroborated by the timecards."
INFO_REQUEST_NOTE = "Provide the 2026-04-01 timecards."
RESPONSE_NOTE = "Timecards attached."
RESOLUTION_NOTE = "Timecards do not corroborate the reported night hours."


class TestSubstantiationCascadeIsVisibleImmediately:
    def test_01_the_derived_posture_and_the_sibling_revert_are_readable_at_once(
        self, api, client, reading_auditor_headers
    ):
        """PRD: "Substantiation records `substantiated_by_user_id` and the supplied
        `resolution_note`, moves `status` to `SUBSTANTIATED`, and then fires three
        cascades." PRD: "the facility's `posture` is re-derived, which sets it to
        `SANCTIONED` and refreshes `substantiated_case_count` and `open_case_count`. Third,
        every `VALIDATED` submission of that facility reverts to `DRAFT`, gains a `FATAL`
        `FACILITY_SANCTIONED` finding, and has its `version` incremented by one." PRD:
        "when a facility's `posture` becomes `SANCTIONED` through the substantiation of a
        discrepancy case, every `VALIDATED` submission of that facility reverts to `DRAFT`,
        gains a new `ValidationFinding` with `code` `FACILITY_SANCTIONED`, `severity`
        `FATAL`, and `status` `OPEN`, has its `open_fatal_finding_count` refreshed, and has
        its `version` incremented by one."

        Design: Corner/consistency_model/substantiation_cascade_is_visible_in_the_same_response
        """
        accepted = build_accepted_quarter(client)
        universe = accepted.universe

        later_period = universe.open_period(
            period_code=TEST_DEFAULTS["SECOND_PERIOD_CODE"],
            start_date=TEST_DEFAULTS["SECOND_PERIOD_START"],
            end_date=TEST_DEFAULTS["SECOND_PERIOD_END"],
            submission_deadline=TEST_DEFAULTS["SECOND_PERIOD_DEADLINE"],
            correction_window_end=TEST_DEFAULTS["SECOND_PERIOD_CORRECTION_END"],
        )
        later_quarter = SubmissionScenario(
            universe, reporting_period_id=later_period["id"]
        )
        later_quarter.report_census("2026-07-01", 5, 5)
        validated = later_quarter.validate()
        assert validated["status"] == SubmissionStatus.VALIDATED.value
        assert validated["validated_by_worker_id"] == universe.w_coord["id"]

        case = CaseScenario(
            accepted,
            trigger_reason=CaseTriggerReason.UNSUPPORTED_HOURS.value,
            detail=CASE_DETAIL,
        )
        case.request_info(INFO_REQUEST_NOTE)
        answered = case.respond(RESPONSE_NOTE)
        assert answered["status"] == CaseStatus.UNDER_REVIEW.value
        assert answered["facility_response_count"] == 1

        substantiated = case.substantiate(RESOLUTION_NOTE)
        assert substantiated["status"] == CaseStatus.SUBSTANTIATED.value
        assert substantiated["substantiated_by_user_id"] == CASE_AUDITOR_USER_ID
        assert substantiated["resolution_note"] == RESOLUTION_NOTE

        facility = validate_success(
            api.get_facility(universe.facility_id, reading_auditor_headers)
        )
        assert facility["posture"] == FacilityPosture.SANCTIONED.value
        assert facility["substantiated_case_count"] == 1
        assert facility["open_case_count"] == 0

        reverted = validate_success(
            api.get_submission(later_quarter.id, reading_auditor_headers)
        )
        assert reverted["status"] == SubmissionStatus.DRAFT.value
        assert reverted["open_fatal_finding_count"] == 1
        assert reverted["version"] == validated["version"] + 1

        findings, meta = validate_paginated(
            api.list_submission_findings(
                later_quarter.id,
                reading_auditor_headers,
                {
                    "code": FindingCode.FACILITY_SANCTIONED.value,
                    "status": FindingStatus.OPEN.value,
                },
            )
        )
        assert meta["total_count"] == 1
        assert findings[0]["severity"] == FindingSeverity.FATAL.value
        assert findings[0]["status"] == FindingStatus.OPEN.value

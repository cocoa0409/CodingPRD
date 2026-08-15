"""Examination scheduling: date ranges, half-open window overlap, initial state
(PRD §3.2, §2.8, §2.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    RAM,
    ApiErrorId,
    assert_examination,
    create_agency,
    create_examination,
    create_examination_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestInitialStateAndDateRange:
    def test_initial_state_of_new_exam_is_scheduled(self, api):
        """PRD §3.2: "A freshly scheduled examination lands in `SCHEDULED` with
        `posture` `NORMAL`, an `overdue_item_count` of zero, and a
        `repeat_finding_risk_score_bp` of zero."

        Design: Corner/state_machines/initial_state_of_new_exam_is_scheduled
        """
        agency = create_agency(agency_code="IS")
        resp = api.create_examination(create_examination_payload(agency["id"]), RAM)
        data = validate_success(resp, 201)
        assert_examination(data)
        assert data["status"] == "SCHEDULED"
        assert data["posture"] == "NORMAL"
        assert data["overdue_item_count"] == 0
        assert data["repeat_finding_risk_score_bp"] == 0

    def test_invalid_date_range_on_exam_create(self, api):
        """PRD §3.2: "The end date must fall strictly after the start date — an
        equal pair is already invalid — with violations rejected as
        `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/invalid_date_range_on_exam_create
        """
        agency = create_agency(agency_code="DR")
        resp = api.create_examination(
            create_examination_payload(
                agency["id"],
                scheduled_start_date="2026-07-10T00:00:00Z",
                scheduled_end_date="2026-07-06T00:00:00Z"),
            RAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_invalid_fk_reference_returns_invalid_reference(self, api):
        """PRD §2.8: "A reference that dangles — or that points into a different
        examination's subtree — is rejected with `ERR_INVALID_REFERENCE`
        (HTTP 422)."

        Design: Corner/validations/invalid_fk_reference_returns_invalid_reference
        """
        resp = api.create_examination(
            create_examination_payload(NON_EXISTENT_UUID), RAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)


class TestHalfOpenWindowOverlap:
    def test_overlapping_exam_window_rejected(self, api):
        """PRD §3.2: "Scheduling also enforces exclusivity of the regulator's
        attention: for the same agency, the new window must not overlap any
        existing examination whose status is anything other than `CANCELLED` or
        `CLOSED`. Overlap is judged on half-open intervals — the windows collide
        when the new examination starts before the incumbent ends and the
        incumbent starts before the new one ends — so two windows that merely
        touch, one ending on the very day the other begins, do not collide. A
        genuine collision is rejected with `ERR_EXAM_SCHEDULE_OVERLAP`."

        Here [2026-07-09, 2026-07-15] collides with the incumbent
        [2026-07-06, 2026-07-10] because 7/09 starts before 7/10 while the
        incumbent starts before 7/15.

        Design: Difficulty/resource_temporal_overlap/exam_interval_half_open_overlap_rejected
        """
        agency = create_agency(agency_code="OCC6")
        create_examination(
            agency["id"], exam_cycle_code="P1",
            scheduled_start_date="2026-07-06T00:00:00Z",
            scheduled_end_date="2026-07-10T00:00:00Z")
        resp = api.create_examination(
            create_examination_payload(
                agency["id"], exam_cycle_code="P2", exam_type="COMPLIANCE",
                scheduled_start_date="2026-07-09T00:00:00Z",
                scheduled_end_date="2026-07-15T00:00:00Z"),
            RAM)
        validate_error(resp, ApiErrorId.ERR_EXAM_SCHEDULE_OVERLAP)

    def test_touching_adjacent_exam_windows_accepted(self, api):
        """PRD §3.2: "Overlap is judged on half-open intervals — the windows
        collide when the new examination starts before the incumbent ends and
        the incumbent starts before the new one ends — so two windows that
        merely touch, one ending on the very day the other begins, do not
        collide. A genuine collision is rejected with
        `ERR_EXAM_SCHEDULE_OVERLAP`."

        The incumbent ends 2026-07-10 and the new window begins 2026-07-10;
        touching windows do not collide.

        Design: Difficulty/resource_temporal_overlap/exam_interval_half_open_overlap_rejected
        """
        agency = create_agency(agency_code="OCC6A")
        create_examination(
            agency["id"], exam_cycle_code="P1",
            scheduled_start_date="2026-07-06T00:00:00Z",
            scheduled_end_date="2026-07-10T00:00:00Z")
        resp = api.create_examination(
            create_examination_payload(
                agency["id"], exam_cycle_code="P3", exam_type="TRUST",
                scheduled_start_date="2026-07-10T00:00:00Z",
                scheduled_end_date="2026-07-15T00:00:00Z"),
            RAM)
        data = validate_success(resp, 201)
        assert_examination(data)

    def test_adjacent_window_boundary_not_overlap(self, api):
        """PRD §3.2: "Overlap is judged on half-open intervals — the windows
        collide when the new examination starts before the incumbent ends and
        the incumbent starts before the new one ends — so two windows that
        merely touch, one ending on the very day the other begins, do not
        collide. A genuine collision is rejected with
        `ERR_EXAM_SCHEDULE_OVERLAP`."

        Boundary precision variant: e1 == s2 exactly (2026-07-10) is adjacency,
        not overlap.

        Design: Difficulty/boundary_precision_check/empty_attendees_and_adjacent_exam_interval
        """
        agency = create_agency(agency_code="FRB4")
        create_examination(
            agency["id"], exam_cycle_code="A",
            scheduled_start_date="2026-07-06T00:00:00Z",
            scheduled_end_date="2026-07-10T00:00:00Z")
        resp = api.create_examination(
            create_examination_payload(
                agency["id"], exam_cycle_code="B", exam_type="COMPLIANCE",
                scheduled_start_date="2026-07-10T00:00:00Z",
                scheduled_end_date="2026-07-20T00:00:00Z"),
            RAM)
        data = validate_success(resp, 201)
        assert is_valid_uuid(data["id"])


class TestOverlapVersusUniquenessPriority:
    def test_overlap_with_duplicate_cycle_code_returns_schedule_overlap(self, api):
        """PRD §2.9: "When several checks could apply to one request, the server
        evaluates them in a single fixed order, and the first failing check
        determines the error response."
        PRD §2.9: "8. **Examination schedule overlap.** The new examination's
        scheduled window must not overlap a live examination for the same agency
        — otherwise `ERR_EXAM_SCHEDULE_OVERLAP` (HTTP 422). Applies to
        examination creation only."
        PRD §2.9: "11. **Uniqueness.** `agency_code` globally unique;
        `request_ref` unique within its examination; `issue_ref` unique within
        its examination; `sequence_index` unique within its plan — otherwise
        `ERR_DUPLICATE_KEY` (HTTP 409). Applies to agency creation, first-day-item
        creation, issue filing, and milestone creation."

        The new examination reuses the incumbent's cycle code AND overlaps its
        window; the schedule-overlap check (step 8) reports the failure.

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_overlap_beats_business_constraint_duplicate
        """
        agency = create_agency(agency_code="FRB3")
        create_examination(
            agency["id"], exam_cycle_code="BASE",
            scheduled_start_date="2026-07-06T00:00:00Z",
            scheduled_end_date="2026-07-10T00:00:00Z")
        resp = api.create_examination(
            create_examination_payload(
                agency["id"], exam_cycle_code="BASE", exam_type="COMPLIANCE",
                scheduled_start_date="2026-07-08T00:00:00Z",
                scheduled_end_date="2026-07-15T00:00:00Z"),
            RAM)
        validate_error(resp, ApiErrorId.ERR_EXAM_SCHEDULE_OVERLAP)

    def test_contained_overlap_also_returns_schedule_overlap(self, api):
        """PRD §3.2: "Overlap is judged on half-open intervals — the windows
        collide when the new examination starts before the incumbent ends and
        the incumbent starts before the new one ends — so two windows that
        merely touch, one ending on the very day the other begins, do not
        collide. A genuine collision is rejected with
        `ERR_EXAM_SCHEDULE_OVERLAP`."

        A window wholly inside the incumbent ([2026-07-07, 2026-07-09] inside
        [2026-07-06, 2026-07-10]) collides even while reusing the incumbent's
        cycle code; the schedule-overlap rule reports the failure.

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_overlap_beats_business_constraint_duplicate
        """
        agency = create_agency(agency_code="FRB3B")
        create_examination(
            agency["id"], exam_cycle_code="BASE",
            scheduled_start_date="2026-07-06T00:00:00Z",
            scheduled_end_date="2026-07-10T00:00:00Z")
        resp = api.create_examination(
            create_examination_payload(
                agency["id"], exam_cycle_code="BASE", exam_type="COMPLIANCE",
                scheduled_start_date="2026-07-07T00:00:00Z",
                scheduled_end_date="2026-07-09T00:00:00Z"),
            RAM)
        err = validate_error(resp, ApiErrorId.ERR_EXAM_SCHEDULE_OVERLAP)
        assert err["error_id"] != ApiErrorId.ERR_DUPLICATE_KEY

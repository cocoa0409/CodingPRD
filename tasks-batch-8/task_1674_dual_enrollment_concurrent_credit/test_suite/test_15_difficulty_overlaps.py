"""Difficulty rule resource_temporal_overlap: the half-open [start, end) term
geometry versus the closed [effective_from, effective_to] articulation-window
geometry (PRD 2.4, 3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_term,
    create_articulation_agreement,
    create_course,
    create_high_school,
    create_hs_term,
    validate_error,
    validate_success,
)


class TestTermOverlapHalfOpenAdjacency:
    def test_adjacent_term_touching_at_the_endpoint_is_allowed(self, api, admin_headers):
        """PRD 2.4: "Terms are also non-overlapping within an institution calendar:
        a new term whose half-open interval from `start_date` (inclusive) to
        `end_date` (exclusive) overlaps an existing term of the same
        `institution_type` — and, for `HIGH_SCHOOL` terms, the same
        `high_school_id` — is rejected with `ERR_TERM_OVERLAP` (HTTP 409)."
        PRD 2.4: "Two terms whose intervals merely touch, one's `end_date` equal to
        the other's `start_date`, do not conflict."

        Design: Difficulty/resource_temporal_overlap/term_overlap_half_open_adjacency
        """
        school = create_high_school()
        create_hs_term(school["id"])  # occupies [2026-08-20, 2026-12-20)

        response = api.create_term(
            {
                "institution_type": "HIGH_SCHOOL",
                "high_school_id": school["id"],
                "name": "Spring 2027 HS",
                "start_date": "2026-12-20T00:00:00Z",  # == existing end_date
                "end_date": "2027-05-10T00:00:00Z",
                "add_deadline": "2027-01-10T00:00:00Z",
                "drop_deadline": "2027-02-01T00:00:00Z",
                "withdraw_deadline": "2027-03-15T00:00:00Z",
            },
            admin_headers,
        )
        adjacent = validate_success(response, 201)
        assert_term(adjacent)
        assert adjacent["name"] == "Spring 2027 HS"

    def test_one_day_of_real_overlap_is_rejected(self, api, admin_headers):
        """PRD 2.4: "Terms are also non-overlapping within an institution calendar:
        a new term whose half-open interval from `start_date` (inclusive) to
        `end_date` (exclusive) overlaps an existing term of the same
        `institution_type` — and, for `HIGH_SCHOOL` terms, the same
        `high_school_id` — is rejected with `ERR_TERM_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/term_overlap_half_open_adjacency
        """
        school = create_high_school()
        create_hs_term(school["id"])  # occupies [2026-08-20, 2026-12-20)

        response = api.create_term(
            {
                "institution_type": "HIGH_SCHOOL",
                "high_school_id": school["id"],
                "name": "Winter Bridge",
                "start_date": "2026-12-19T00:00:00Z",  # one day before the end
                "end_date": "2027-01-05T00:00:00Z",
                "add_deadline": "2026-12-22T00:00:00Z",
                "drop_deadline": "2026-12-26T00:00:00Z",
                "withdraw_deadline": "2027-01-02T00:00:00Z",
            },
            admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_TERM_OVERLAP.value)


class TestArticulationWindowClosedIntervalConflict:
    def _existing_agreement(self):
        school = create_high_school()
        course = create_course(
            course_code="MATH151", title="College Algebra",
            placement_exam_code="MATH", min_placement_score=70,
        )
        create_articulation_agreement(
            course["id"], "StateU",
            effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-30T00:00:00Z",
        )
        return course

    def test_touching_windows_conflict_under_closed_intervals(self, api, admin_headers):
        """PRD 3.9: "The active window is a closed interval — the agreement is
        active when the logical clock reads at or after `effective_from` and at or
        before `effective_to`."
        PRD 3.9: "Unlike terms, articulation windows for the same `course_id` and
        `target_institution` pair conflict even when they merely touch: a new
        agreement whose closed window overlaps an existing agreement's closed
        window is rejected with `ERR_ARTICULATION_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/articulation_window_closed_interval_conflict
        """
        course = self._existing_agreement()
        response = api.create_articulation_agreement(
            {
                "course_id": course["id"],
                "target_institution": "StateU",
                "transfer_credit_hours": 3.0,
                "min_grade_for_transfer": "C",
                "effective_from": "2026-06-30T00:00:00Z",  # touches effective_to
                "effective_to": "2026-12-31T00:00:00Z",
            },
            admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_ARTICULATION_WINDOW_OVERLAP.value)

    def test_window_starting_the_next_day_is_accepted(self, api, admin_headers):
        """PRD 3.9: "Unlike terms, articulation windows for the same `course_id`
        and `target_institution` pair conflict even when they merely touch: a new
        agreement whose closed window overlaps an existing agreement's closed
        window is rejected with `ERR_ARTICULATION_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/articulation_window_closed_interval_conflict
        """
        course = self._existing_agreement()
        response = api.create_articulation_agreement(
            {
                "course_id": course["id"],
                "target_institution": "StateU",
                "transfer_credit_hours": 3.0,
                "min_grade_for_transfer": "C",
                "effective_from": "2026-07-01T00:00:00Z",  # strictly after
                "effective_to": "2026-12-31T00:00:00Z",
            },
            admin_headers,
        )
        created = validate_success(response, 201)
        assert created["target_institution"] == "StateU"
        assert created["transfer_credit_hours"] == 3.0

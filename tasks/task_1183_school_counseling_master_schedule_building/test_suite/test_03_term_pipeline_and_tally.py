"""Term posture pipeline, tally math, and section generation."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_student_headers,
    setup_counselor, setup_term, setup_course, setup_student,
    setup_teacher, setup_room, qualify_teacher,
    make_course_request, make_and_submit_request,
    setup_students_with_submitted_requests, setup_students_with_draft_requests,
    drive_term_to_building, list_term_sections,
)

ADMIN = TEST_USERS["admin_headers"]


def _preview_row(rows, course_id):
    for row in rows:
        if row["course_id"] == course_id:
            return row
    return None


class TestTallyPreviewVsFinalSectionCount:
    """Difficulty instance: optimistic preview vs final generation tally."""

    def _setup_tally_scenario(self, api):
        counselor = setup_counselor(max_caseload=100, full_name="C One")
        term = setup_term("2026-FALL", periods_per_day=8, max_students_per_section=32,
                          class_size_target=25, singleton_section_cap=2,
                          change_request_max_per_student=3)
        course = setup_course("MATH-301", credits=1.0, subject_area="MATH", title="Algebra II")
        setup_students_with_submitted_requests(counselor["id"], term["id"], course["id"],
                                               25, "S", grade_level=9)
        setup_students_with_draft_requests(counselor["id"], term["id"], course["id"],
                                           2, "D", grade_level=9)
        return counselor, term, course

    def test_tally_preview_counts_drafts_at_halved_weight(self, api):
        """PRD §3.2: "The preview runs the same demand math as final generation
        but additionally counts `DRAFT` requests at halved weight — 0.5 for a
        primary draft, 0.25 for an alternate draft — on top of the submitted
        demand, so preview section counts are never lower than the final counts
        for identical submitted data whenever drafts exist."
        PRD §3.2: "It returns one row per course with positive demand, each row
        carrying `course_id`, `course_code`, `demand`, and `projected_sections`."

        Design: Difficulty/dual_variant_calc/tally_preview_vs_final_section_count
        """
        _, term, course = self._setup_tally_scenario(api)
        resp = api.get_tally_preview(term["id"], ADMIN)
        data = validate_success(resp, 200)
        row = _preview_row(data["rows"], course["id"])
        assert row is not None, "preview must contain a row for MATH-301"
        assert float(row["demand"]) == pytest.approx(26.0), (
            f"preview demand must be 25*1.0 + 2*0.5 = 26.0, got {row['demand']}"
        )
        assert row["projected_sections"] == 2, (
            f"ceil(26.0/25) == 2, got {row['projected_sections']}"
        )

    def test_final_tally_excludes_drafts_and_creates_one_section(self, api):
        """PRD §3.3: "The final tally counts only `SUBMITTED` and `LOCKED`
        requests at full or alternate weight — drafts are excluded entirely,
        having been withdrawn at close."
        PRD §3.3: "that demand is then divided by the term's `class_size_target`,
        and only then is the quotient rounded up to a whole section count"
        PRD §3.3: "The term moves `COLLECTING` → `TALLYING`, every request still
        in `DRAFT` is swept to `WITHDRAWN`"

        Design: Difficulty/dual_variant_calc/tally_preview_vs_final_section_count
        """
        _, term, course = self._setup_tally_scenario(api)
        drive_term_to_building(term["id"])
        sections = [s for s in list_term_sections(term["id"]) if s["course_id"] == course["id"]]
        assert len(sections) == 1, (
            f"final demand 25.0 -> ceil(25.0/25) == 1 section, got {len(sections)}"
        )
        assert sections[0]["state"] == "DRAFT"
        reqs = get_success_data(api.list_course_requests(ADMIN, params={
            "term_id": term["id"], "state": "WITHDRAWN",
        }))
        assert len(reqs) == 2, "the 2 DRAFT requests must be WITHDRAWN by close-collection"


class TestTallyWeightsAndPreviewShape:
    def test_tally_weight_alternate_half_weight(self, api):
        """PRD §3.2: "Every request carries a computed `tally_weight`: 1.0 for a
        primary request in `SUBMITTED` or `LOCKED`, 0.5 for an alternate in one
        of those states, and 0 in every other case."

        Design: Corner/calculations/tally_weight_alternate_half_weight
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Alt")
        term = setup_term("2049-FALL")
        course = setup_course("ALT-1", credits=1.0, subject_area="ELECTIVE")
        s_alt = setup_student(counselor["id"], "ALT1", grade_level=9)
        s_b1 = setup_student(counselor["id"], "AB01", grade_level=9)
        s_b2 = setup_student(counselor["id"], "AB02", grade_level=9)
        make_and_submit_request(s_alt["id"], course["id"], term["id"], 1)
        make_and_submit_request(s_b1["id"], course["id"], term["id"], 1, is_alternate=True)
        make_and_submit_request(s_b2["id"], course["id"], term["id"], 1, is_alternate=True)
        data = validate_success(api.get_tally_preview(term["id"], ADMIN), 200)
        row = _preview_row(data["rows"], course["id"])
        assert row is not None
        assert float(row["demand"]) == pytest.approx(2.0), (
            f"1.0 primary + 2 x 0.5 alternates = 2.0, got {row['demand']}"
        )

    def test_computed_read_tally_preview_shape(self, api):
        """PRD §3.2: "It returns one row per course with positive demand, each
        row carrying `course_id`, `course_code`, `demand`, and
        `projected_sections`."

        Design: Corner/endpoints/computed_read_tally_preview_shape
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Z")
        term = setup_term("2060-FALL")
        setup_course("Z-0", credits=1.0, subject_area="ELECTIVE", title="Zero")
        k_nz = setup_course("NZ-1", credits=1.0, subject_area="ELECTIVE", title="NonZero")
        s_nz = setup_student(counselor["id"], "NZ01", grade_level=9)
        make_and_submit_request(s_nz["id"], k_nz["id"], term["id"], 1)
        data = validate_success(api.get_tally_preview(term["id"], ADMIN), 200)
        rows = data["rows"]
        assert _preview_row(rows, k_nz["id"]) is not None, "NZ-1 has positive demand"
        assert all(r["course_code"] != "Z-0" for r in rows), "zero-demand course must be absent"


class TestSectionGeneration:
    def test_singleton_course_forces_single_section(self, api):
        """PRD §3.3: "A `singleton` course yields exactly one section when its
        demand is positive and zero otherwise"

        Design: Corner/calculations/singleton_course_forces_single_section
        """
        counselor = setup_counselor(max_caseload=500, full_name="C Sg")
        term = setup_term("2051-FALL")
        course = setup_course("SG-1", credits=1.0, subject_area="ELECTIVE",
                              title="Singleton Seminar", singleton=True)
        setup_students_with_submitted_requests(counselor["id"], term["id"], course["id"],
                                               60, "SG", grade_level=9)
        get_success_data(api.close_collection(term["id"], ADMIN))
        get_success_data(api.generate_sections(term["id"], ADMIN))
        sections = [s for s in list_term_sections(term["id"]) if s["course_id"] == course["id"]]
        assert len(sections) == 1, (
            f"singleton override must yield exactly 1 section despite demand 60.0, got {len(sections)}"
        )

    def test_close_collection_cascades_draft_withdrawal(self, api):
        """PRD §3.3: "The term moves `COLLECTING` → `TALLYING`, every request
        still in `DRAFT` is swept to `WITHDRAWN` (each such request's
        `tally_weight` recomputing to zero), `total_requested_seats` is
        recomputed over the surviving `SUBMITTED` and `LOCKED` requests, and the
        term's `version` increments by one."

        Design: Corner/cross_cutting_layers/close_collection_cascades_draft_withdrawal
        """
        counselor = setup_counselor(max_caseload=100, full_name="C Casc")
        term = setup_term("2073-FALL")
        submitted = []
        drafted = []
        for i in range(1, 6):
            student = setup_student(counselor["id"], f"CC{i:02d}", grade_level=9)
            course = setup_course(f"CASC-{i}", credits=1.0, subject_area="ELECTIVE")
            if i <= 2:
                submitted.append(make_and_submit_request(student["id"], course["id"], term["id"], 1))
            else:
                drafted.append(make_course_request(student["id"], course["id"], term["id"], 1))
        resp = api.close_collection(term["id"], ADMIN)
        term_data = validate_success(resp, 200)
        assert term_data["posture"] == "TALLYING"
        assert term_data["total_requested_seats"] == 2, (
            f"only 2 SUBMITTED requests survive the tally, got {term_data['total_requested_seats']}"
        )
        for req in drafted:
            current = validate_success(api.get_course_request(req["id"], ADMIN), 200)
            assert current["state"] == "WITHDRAWN", f"draft {req['id']} must be swept to WITHDRAWN"
            assert float(current["tally_weight"]) == 0

    def test_guarded_transition_publish_blocked(self, api):
        """PRD §3.4: "An administrator may publish only while the term is in
        `BUILDING`, only when every non-`CANCELLED` section has reached
        `SCHEDULED` with both teacher and room assigned, and only when no grid
        conflicts remain among the term's non-`CANCELLED` sections; a violation
        blocks publication with `ERR_PUBLISH_BLOCKED` (HTTP 409)."

        Design: Corner/state_machines/guarded_transition_publish_blocked
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Grd")
        term = setup_term("2046-FALL")
        course = setup_course("GRD-1", credits=1.0, subject_area="ELECTIVE")
        student = setup_student(counselor["id"], "GRD1", grade_level=9)
        make_and_submit_request(student["id"], course["id"], term["id"], 1)
        drive_term_to_building(term["id"])
        # one DRAFT section remains unscheduled
        resp = api.publish_term(term["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PUBLISH_BLOCKED, 409)

    def test_fk_reverse_reachability_section_roster(self, api):
        """PRD §3.3: "a section's roster reads back its schedule entries,
        filterable by `state`." A DRAFT section with no placements reads back an
        empty list.

        Design: Corner/entities/fk_reverse_reachability_section_roster
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Rr")
        term = setup_term("2041-FALL")
        course = setup_course("RR-1", credits=1.0, subject_area="ELECTIVE", title="Roster")
        student = setup_student(counselor["id"], "RR01", grade_level=9)
        make_and_submit_request(student["id"], course["id"], term["id"], 1)
        drive_term_to_building(term["id"])
        sections = list_term_sections(term["id"])
        assert len(sections) == 1
        data = validate_success(api.get_section_roster(sections[0]["id"], ADMIN), 200)
        assert data == [], f"unplaced DRAFT section roster must be empty, got {data}"

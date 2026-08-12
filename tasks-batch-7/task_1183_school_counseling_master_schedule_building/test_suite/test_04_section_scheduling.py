"""Section scheduling: grid conflicts, term-posture gating, teacher load."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_counselor_headers,
    setup_counselor, setup_term, setup_course, setup_student,
    setup_teacher, setup_room, qualify_teacher,
    make_and_submit_request, drive_term_to_building, list_term_sections,
    get_term_version, schedule_section,
)

ADMIN = TEST_USERS["admin_headers"]


def _building_term_with_two_courses(api, code, counselor_name, ref="G001"):
    """Term in BUILDING with one DRAFT section per course (two courses)."""
    counselor = setup_counselor(max_caseload=100, full_name=counselor_name)
    term = setup_term(code)
    c_a = setup_course(f"{code}-A", credits=1.0, subject_area="SCIENCE", title="Bio")
    c_b = setup_course(f"{code}-B", credits=1.0, subject_area="SCIENCE", title="Chem")
    student = setup_student(counselor["id"], ref, grade_level=10)
    make_and_submit_request(student["id"], c_a["id"], term["id"], 1)
    make_and_submit_request(student["id"], c_b["id"], term["id"], 2)
    drive_term_to_building(term["id"])
    sections = list_term_sections(term["id"])
    sec_a = next(s for s in sections if s["course_id"] == c_a["id"])
    sec_b = next(s for s in sections if s["course_id"] == c_b["id"])
    return counselor, term, c_a, c_b, student, sec_a, sec_b


class TestSectionGridPointSlotSemantics:
    def test_same_period_teacher_conflict_rejected(self, api):
        """PRD §3.3: "no other non-`CANCELLED` section in the term may occupy the
        same teacher-and-period slot or the same room-and-period slot."
        PRD §3.3: "A collision is rejected with `ERR_GRID_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/section_grid_point_slot_semantics
        """
        _, term, c_a, c_b, _, sec_a, sec_b = _building_term_with_two_courses(
            api, "2037-FALL", "C Fifteen")
        teacher = setup_teacher(max_sections=5, full_name="T Grid")
        qualify_teacher(teacher["id"], c_a["id"])
        qualify_teacher(teacher["id"], c_b["id"])
        rm1 = setup_room("GR-1", capacity=32)
        rm2 = setup_room("GR-2", capacity=32)
        schedule_section(sec_a["id"], teacher["id"], rm1["id"], 3, 32, term["id"])
        resp = api.patch_section(sec_b["id"], {
            "teacher_id": teacher["id"], "room_id": rm2["id"], "period": 3,
            "capacity": 32, "expected_term_version": get_term_version(term["id"]),
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_GRID_CONFLICT, 409)

    def test_adjacent_period_same_resources_accepted(self, api):
        """PRD §3.3: "Grid occupancy is point-slot semantics — two sections
        collide only when they occupy the same period integer for the same
        resource, so sections in adjacent periods coexist freely."

        Design: Difficulty/resource_temporal_overlap/section_grid_point_slot_semantics
        """
        _, term, c_a, c_b, _, sec_a, sec_b = _building_term_with_two_courses(
            api, "2037-FALL", "C Fifteen")
        teacher = setup_teacher(max_sections=5, full_name="T Grid")
        qualify_teacher(teacher["id"], c_a["id"])
        qualify_teacher(teacher["id"], c_b["id"])
        rm1 = setup_room("GR-1", capacity=32)
        schedule_section(sec_a["id"], teacher["id"], rm1["id"], 3, 32, term["id"])
        resp = api.patch_section(sec_b["id"], {
            "teacher_id": teacher["id"], "room_id": rm1["id"], "period": 4,
            "capacity": 32, "expected_term_version": get_term_version(term["id"]),
        }, ADMIN)
        data = validate_success(resp, 200)
        assert data["state"] == "SCHEDULED", (
            "adjacent period 4 with the same teacher and room must schedule cleanly"
        )


class TestSectionSchedulingGatedByTermPosture:
    def _setup_gate(self, api):
        counselor = setup_counselor(max_caseload=100, full_name="C Thirteen")
        term = setup_term("2035-FALL")
        course = setup_course("HIS-201", credits=1.0, subject_area="SOCIAL_STUDIES", title="History")
        student = setup_student(counselor["id"], "GT01", grade_level=10)
        make_and_submit_request(student["id"], course["id"], term["id"], 1)
        drive_term_to_building(term["id"])
        teacher = setup_teacher(max_sections=5, full_name="T Gate")
        qualify_teacher(teacher["id"], course["id"])
        room = setup_room("G-1", capacity=32)
        section = list_term_sections(term["id"])[0]
        return term, teacher, room, section

    def test_patch_succeeds_while_building(self, api):
        """PRD §3.3: "Staffing happens section by section while the term is in
        `BUILDING`. An administrator schedules a draft section by supplying its
        `teacher_id`, `room_id`, `period`, and `capacity`... on success the
        section moves `DRAFT` → `SCHEDULED`"

        Design: Difficulty/cross_entity_state_dependency/section_scheduling_gated_by_term_posture
        """
        term, teacher, room, section = self._setup_gate(api)
        data = schedule_section(section["id"], teacher["id"], room["id"], 1, 32, term["id"])
        assert data["state"] == "SCHEDULED"

    def test_patch_rejected_after_publish_with_posture_error(self, api):
        """PRD §3.3: "The term must be in `BUILDING` (`ERR_INVALID_TERM_POSTURE`)
        and the section still in `DRAFT` (`ERR_INVALID_STATE`)."
        PRD §2.4: "section scheduling requires `BUILDING`... An operation
        attempted under the wrong posture is rejected with
        `ERR_INVALID_TERM_POSTURE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/section_scheduling_gated_by_term_posture
        """
        term, teacher, room, section = self._setup_gate(api)
        schedule_section(section["id"], teacher["id"], room["id"], 1, 32, term["id"])
        get_success_data(api.publish_term(term["id"], ADMIN))
        resp = api.patch_section(section["id"], {
            "teacher_id": teacher["id"], "room_id": room["id"], "period": 2,
            "capacity": 32, "expected_term_version": get_term_version(term["id"]),
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_TERM_POSTURE, 409)


class TestTeacherLoadInvariant:
    def _setup_invariant(self, api):
        counselor = setup_counselor(max_caseload=100, full_name="C Eighteen")
        term = setup_term("2039-FALL")
        c1 = setup_course("INV-A", credits=1.0, subject_area="ELECTIVE")
        c2 = setup_course("INV-B", credits=1.0, subject_area="ELECTIVE")
        student = setup_student(counselor["id"], "IN01", grade_level=9)
        make_and_submit_request(student["id"], c1["id"], term["id"], 1)
        make_and_submit_request(student["id"], c2["id"], term["id"], 2)
        drive_term_to_building(term["id"])
        teacher = setup_teacher(max_sections=3, full_name="T Inv")
        qualify_teacher(teacher["id"], c1["id"])
        qualify_teacher(teacher["id"], c2["id"])
        room = setup_room("INV-1", capacity=32)
        sections = sorted(list_term_sections(term["id"]), key=lambda s: s["created_at"])
        sec1, sec_inv = sections[0], sections[1]
        schedule_section(sec1["id"], teacher["id"], room["id"], 1, 32, term["id"])
        return term, teacher, room, sec_inv

    def test_schedule_then_cancel_restores_teacher_load(self, api):
        """PRD §3.1: "their `assigned_section_count` is a computed tally of their
        sections in state `SCHEDULED` or `PUBLISHED` in the active term,
        refreshed whenever a section is created, scheduled, cancelled, or touched
        by a rebalance run."
        PRD §3.3: "A `SCHEDULED` section that proves unnecessary can be cancelled
        while `BUILDING` continues, provided it still has zero enrolled students;
        cancellation recomputes the teacher's load."

        Design: Difficulty/compensating_invariant/schedule_cancel_preserves_teacher_load_arithmetic
        """
        term, teacher, room, sec_inv = self._setup_invariant(api)
        before = get_success_data(api.get_teacher(teacher["id"], ADMIN))
        assert before["assigned_section_count"] == 1
        schedule_section(sec_inv["id"], teacher["id"], room["id"], 5, 32, term["id"])
        mid = get_success_data(api.get_teacher(teacher["id"], ADMIN))
        assert mid["assigned_section_count"] == 2, "scheduling must raise the count to 2"
        get_success_data(api.cancel_section(sec_inv["id"], ADMIN))
        after = get_success_data(api.get_teacher(teacher["id"], ADMIN))
        assert after["assigned_section_count"] == 1, (
            "the forward/compensating pair must leave the count at 1 with zero drift"
        )

    def test_cancelled_section_state_after_cancel(self, api):
        """PRD §3.3: "A `SCHEDULED` section that proves unnecessary can be
        cancelled while `BUILDING` continues, provided it still has zero enrolled
        students" — the cancelled section lands in `CANCELLED`.

        Design: Difficulty/compensating_invariant/schedule_cancel_preserves_teacher_load_arithmetic
        """
        term, teacher, room, sec_inv = self._setup_invariant(api)
        schedule_section(sec_inv["id"], teacher["id"], room["id"], 5, 32, term["id"])
        data = validate_success(api.cancel_section(sec_inv["id"], ADMIN), 200)
        assert data["state"] == "CANCELLED"
        current = validate_success(api.get_section(sec_inv["id"], ADMIN), 200)
        assert current["state"] == "CANCELLED"


class TestSectionAssignmentValidity:
    def test_room_type_mismatch_rejected(self, api):
        """PRD §3.3: "A qualification row must exist pairing the teacher with the
        section's course, and the room's `room_type` must equal the course's
        `required_room_type`; either failure is `ERR_SECTION_ASSIGNMENT_INVALID`
        (HTTP 422)."

        Design: Corner/validations/room_type_mismatch_rejected
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Lab")
        term = setup_term("2055-FALL")
        course = setup_course("CHEM-L", credits=1.0, subject_area="SCIENCE",
                              title="Chem Lab", required_room_type="LAB")
        student = setup_student(counselor["id"], "LAB1", grade_level=9)
        make_and_submit_request(student["id"], course["id"], term["id"], 1)
        drive_term_to_building(term["id"])
        teacher = setup_teacher(max_sections=3, full_name="T Lab")
        qualify_teacher(teacher["id"], course["id"])
        room = setup_room("ST-1", capacity=32, room_type="STANDARD")
        section = list_term_sections(term["id"])[0]
        resp = api.patch_section(section["id"], {
            "teacher_id": teacher["id"], "room_id": room["id"], "period": 1,
            "capacity": 32, "expected_term_version": get_term_version(term["id"]),
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SECTION_ASSIGNMENT_INVALID, 422)

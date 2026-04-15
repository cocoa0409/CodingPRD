"""Tests for prerequisite DAG, cycle detection, corequisites, and prerequisite graph endpoint."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    assert_prerequisite_graph,
    create_course_payload, create_enrollment_payload,
)
from test_helpers.fixtures import (
    create_semester, create_department, create_instructor, create_course, create_section,
    create_student, create_semester_in_open_enrollment, enroll_student,
    setup_prerequisite_chain,
)


class TestPrerequisiteEnforcement:
    """Tests for prerequisite validation during enrollment."""

    def test_enroll_without_prerequisite_fails(self):
        """Student missing a prerequisite -> PREREQUISITE_NOT_MET."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Create prerequisite course
        prereq = create_course(sid, dept["id"], course_code="PRE-101", credit_hours=3)

        # Create target course that requires the prerequisite
        target = create_course(sid, dept["id"], course_code="ADV-201", credit_hours=3,
                                prerequisite_ids=[prereq["id"]])
        target_section = create_section(sid, dept["id"], target["id"], instructor["id"],
                                         schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                                         location="Room-X")

        # Student without the prerequisite
        student = create_student(sid, dept["id"], completed_course_ids=[])
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], target["id"], target_section["id"],
            payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.PREREQUISITE_NOT_MET)

    def test_enroll_with_prerequisite_succeeds(self):
        """Student with completed prerequisite can enroll."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        prereq = create_course(sid, dept["id"], course_code="PRE-201", credit_hours=3)
        target = create_course(sid, dept["id"], course_code="ADV-301", credit_hours=3,
                                prerequisite_ids=[prereq["id"]])
        target_section = create_section(sid, dept["id"], target["id"], instructor["id"],
                                         schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                                         location="Room-Y")

        # Student has completed the prerequisite
        student = create_student(sid, dept["id"], completed_course_ids=[prereq["id"]])
        enrollment = enroll_student(sid, dept["id"], target["id"], target_section["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"

    def test_transitive_prerequisite_enforcement(self):
        """Student must have completed ALL transitive prerequisites, not just direct ones."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        # Chain: A -> B -> C (C requires B, B requires A)
        course_a = create_course(sid, dept["id"], course_code="A-100", credit_hours=3)
        course_b = create_course(sid, dept["id"], course_code="B-200", credit_hours=3,
                                  prerequisite_ids=[course_a["id"]])
        course_c = create_course(sid, dept["id"], course_code="C-300", credit_hours=3,
                                  prerequisite_ids=[course_b["id"]])
        section_c = create_section(sid, dept["id"], course_c["id"], instructor["id"],
                                    schedule_days="TR", schedule_start="16:00", schedule_end="17:00",
                                    location="Room-Z")

        # Student completed B but NOT A -> should fail (transitive prereq A not met)
        student = create_student(sid, dept["id"], completed_course_ids=[course_b["id"]])
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], course_c["id"], section_c["id"],
            payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.PREREQUISITE_NOT_MET)

    def test_transitive_prerequisite_all_completed(self):
        """Student with all transitive prerequisites completed can enroll in leaf course."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        course_a = create_course(sid, dept["id"], course_code="TA-100", credit_hours=3)
        course_b = create_course(sid, dept["id"], course_code="TB-200", credit_hours=3,
                                  prerequisite_ids=[course_a["id"]])
        course_c = create_course(sid, dept["id"], course_code="TC-300", credit_hours=3,
                                  prerequisite_ids=[course_b["id"]])
        section_c = create_section(sid, dept["id"], course_c["id"], instructor["id"],
                                    schedule_days="TR", schedule_start="16:00", schedule_end="17:00",
                                    location="Room-W")

        # Student has completed both A and B
        student = create_student(sid, dept["id"],
                                  completed_course_ids=[course_a["id"], course_b["id"]])
        enrollment = enroll_student(sid, dept["id"], course_c["id"], section_c["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"


class TestPrerequisiteCycleDetection:
    """Tests for cycle detection in prerequisite graphs."""

    def test_self_referential_cycle(self):
        """Course cannot be its own prerequisite -> PREREQUISITE_CYCLE_DETECTED."""
        semester = create_semester()
        dept = create_department(semester["id"])
        course = create_course(semester["id"], dept["id"])

        # Update to make it its own prerequisite
        resp = api_client.update_course(
            semester["id"], dept["id"], course["id"],
            {"prerequisite_ids": [course["id"]]}, TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.PREREQUISITE_CYCLE_DETECTED)

    def test_two_node_cycle(self):
        """A -> B -> A creates a cycle -> PREREQUISITE_CYCLE_DETECTED."""
        semester = create_semester()
        dept = create_department(semester["id"])

        course_a = create_course(semester["id"], dept["id"], course_code="CYC-A")
        course_b = create_course(semester["id"], dept["id"], course_code="CYC-B",
                                  prerequisite_ids=[course_a["id"]])

        # Now try to make A depend on B (cycle)
        resp = api_client.update_course(
            semester["id"], dept["id"], course_a["id"],
            {"prerequisite_ids": [course_b["id"]]}, TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.PREREQUISITE_CYCLE_DETECTED)

    def test_three_node_cycle(self):
        """A -> B -> C -> A creates a cycle -> PREREQUISITE_CYCLE_DETECTED."""
        semester = create_semester()
        dept = create_department(semester["id"])

        course_a = create_course(semester["id"], dept["id"], course_code="CYC3-A")
        course_b = create_course(semester["id"], dept["id"], course_code="CYC3-B",
                                  prerequisite_ids=[course_a["id"]])
        course_c = create_course(semester["id"], dept["id"], course_code="CYC3-C",
                                  prerequisite_ids=[course_b["id"]])

        # Try to close the cycle: A depends on C
        resp = api_client.update_course(
            semester["id"], dept["id"], course_a["id"],
            {"prerequisite_ids": [course_c["id"]]}, TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.PREREQUISITE_CYCLE_DETECTED)

    def test_cycle_on_creation(self):
        """Creating a course that forms a cycle should be rejected."""
        semester = create_semester()
        dept = create_department(semester["id"])

        course_a = create_course(semester["id"], dept["id"], course_code="CRCY-A")
        course_b = create_course(semester["id"], dept["id"], course_code="CRCY-B",
                                  prerequisite_ids=[course_a["id"]])

        # Try to create C that depends on B, and then update B to depend on C (creating cycle)
        course_c = create_course(semester["id"], dept["id"], course_code="CRCY-C",
                                  prerequisite_ids=[course_b["id"]])
        resp = api_client.update_course(
            semester["id"], dept["id"], course_a["id"],
            {"prerequisite_ids": [course_c["id"]]}, TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.PREREQUISITE_CYCLE_DETECTED)


class TestCorequisites:
    """Tests for corequisite validation."""

    def test_corequisite_not_satisfied(self):
        """Student missing corequisite (not completed, not concurrently enrolled) -> COREQUISITE_NOT_SATISFIED."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        coreq = create_course(sid, dept["id"], course_code="COREQ-101", credit_hours=3)
        target = create_course(sid, dept["id"], course_code="COREQ-201", credit_hours=3,
                                corequisite_ids=[coreq["id"]])
        target_section = create_section(sid, dept["id"], target["id"], instructor["id"],
                                         schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                                         location="Room-CR")

        student = create_student(sid, dept["id"], completed_course_ids=[])
        payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(
            sid, dept["id"], target["id"], target_section["id"],
            payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.COREQUISITE_NOT_SATISFIED)

    def test_corequisite_satisfied_by_completion(self):
        """Corequisite satisfied if course is in completed_course_ids."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        coreq = create_course(sid, dept["id"], course_code="COREQC-101", credit_hours=3)
        target = create_course(sid, dept["id"], course_code="COREQC-201", credit_hours=3,
                                corequisite_ids=[coreq["id"]])
        target_section = create_section(sid, dept["id"], target["id"], instructor["id"],
                                         schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                                         location="Room-CRC")

        student = create_student(sid, dept["id"], completed_course_ids=[coreq["id"]])
        enrollment = enroll_student(sid, dept["id"], target["id"], target_section["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"

    def test_corequisite_satisfied_by_concurrent_enrollment(self):
        """Corequisite satisfied if student is ENROLLED in the corequisite course concurrently."""
        semester, dept, course, section, instructor = create_semester_in_open_enrollment()
        sid = semester["id"]

        coreq = create_course(sid, dept["id"], course_code="CONC-101", credit_hours=3)
        coreq_section = create_section(sid, dept["id"], coreq["id"], instructor["id"],
                                        schedule_days="MWF", schedule_start="08:00", schedule_end="09:00",
                                        location="Room-CQ1")

        target = create_course(sid, dept["id"], course_code="CONC-201", credit_hours=3,
                                corequisite_ids=[coreq["id"]])
        target_section = create_section(sid, dept["id"], target["id"], instructor["id"],
                                         schedule_days="TR", schedule_start="14:00", schedule_end="15:00",
                                         location="Room-CQ2")

        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        # First enroll in the corequisite course
        enroll_student(sid, dept["id"], coreq["id"], coreq_section["id"], student["id"])

        # Now enroll in the target course (corequisite satisfied by concurrent enrollment)
        enrollment = enroll_student(sid, dept["id"], target["id"], target_section["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"


class TestPrerequisiteGraph:
    """Tests for GET .../prerequisite-graph endpoint."""

    def test_prerequisite_graph_no_prerequisites(self):
        """Course with no prerequisites has empty dependency_chain, depth=0, has_cycle=false."""
        semester = create_semester()
        dept = create_department(semester["id"])
        course = create_course(semester["id"], dept["id"])

        resp = api_client.get_prerequisite_graph(
            semester["id"], dept["id"], course["id"], TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert_prerequisite_graph(data)
        assert data["course_id"] == course["id"]
        assert data["dependency_chain"] == []
        assert data["depth"] == 0
        assert data["has_cycle"] is False

    def test_prerequisite_graph_chain(self):
        """Chain of prerequisites shows correct depth and dependency_chain."""
        semester = create_semester()
        dept = create_department(semester["id"])
        courses = setup_prerequisite_chain(semester["id"], dept["id"], chain_length=3)

        # The leaf course (index 2) depends on courses[1] and courses[0]
        resp = api_client.get_prerequisite_graph(
            semester["id"], dept["id"], courses[2]["id"], TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert_prerequisite_graph(data)
        assert data["depth"] == 2, f"Expected depth 2 for 3-course chain, got {data['depth']}"
        assert data["has_cycle"] is False
        # dependency_chain should contain both ancestor courses
        chain_ids = data["dependency_chain"]
        assert courses[0]["id"] in chain_ids, "Root course should be in dependency chain"
        assert courses[1]["id"] in chain_ids, "Middle course should be in dependency chain"
        assert len(chain_ids) == 2

    def test_prerequisite_graph_any_role_access(self):
        """Any authenticated role can view the prerequisite graph."""
        semester = create_semester()
        dept = create_department(semester["id"])
        course = create_course(semester["id"], dept["id"])

        for role in ["registrar_headers", "professor_headers", "student_headers"]:
            resp = api_client.get_prerequisite_graph(
                semester["id"], dept["id"], course["id"], TEST_USERS[role]
            )
            validate_success(resp)

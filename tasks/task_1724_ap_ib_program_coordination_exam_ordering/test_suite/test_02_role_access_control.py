"""Role-based access control and entity-backed ownership (PRD §2.1, §2.8 step
2, §4 endpoint role table).
"""
from test_helpers import (
    COORD,
    REGISTRAR,
    ApiErrorId,
    create_course_payload,
    create_registration_payload,
    get_application,
    get_authorization,
    get_order,
    make_application,
    make_authorization,
    make_course,
    make_cycle,
    make_open_cycle,
    make_order,
    make_registration,
    make_student,
    make_student_headers,
    make_teacher,
    make_teacher_headers,
    setup_sat_scenario,
    validate_error,
    validate_paginated,
)


class TestExclusiveRoleDenials:
    def test_student_cannot_create_course(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint, or that violates entity-backed ownership, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 endpoint table: POST /courses lists ApCoordinator as its only authorized role.

        Design: Corner/rbac/student_cannot_create_course_returns_forbidden
        """
        cycle = make_cycle()
        student = make_student()
        res = api.create_course(
            create_course_payload(cycle["id"]),
            make_student_headers(student["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)
        courses, meta = validate_paginated(
            api.list_courses(COORD, params={"cycle_id": cycle["id"]})
        )
        assert courses == [], "the rejected create must not persist a course"
        assert meta["total_count"] == 0

    def test_teacher_cannot_approve_fee_application(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint, or that violates entity-backed ownership, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 endpoint table: POST /fee-reduction-applications/{id}/approve lists ApCoordinator as its only authorized role.

        Design: Corner/rbac/teacher_cannot_approve_fee_application_returns_forbidden
        """
        cycle = make_open_cycle()
        student = make_student(subgroup_code="FRL")
        application = make_application(student["id"], cycle["id"])
        teacher = make_teacher()
        res = api.approve_fee_reduction_application(
            application["id"], make_teacher_headers(teacher["id"])
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)
        assert get_application(application["id"])["status"] == "SUBMITTED"

    def test_registrar_cannot_submit_order(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint, or that violates entity-backed ownership, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4 endpoint table: POST /exam-orders/{id}/submit lists ApCoordinator as its only authorized role.

        Design: Corner/rbac/registrar_cannot_submit_order_returns_forbidden
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])
        student = make_student()
        make_registration(student["id"], course["id"])
        order = make_order(cycle["id"])
        res = api.submit_exam_order(order["id"], REGISTRAR)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)
        assert get_order(order["id"])["status"] == "DRAFT"

    def test_coordinator_cannot_complete_training(self, api):
        """PRD §2.1: "These ownership rules are what segregate duties — for
        example, the coordinator who opens a teacher's authorization record
        cannot attest the training on that teacher's behalf."
        PRD §4 endpoint table: POST /teacher-authorizations/{id}/complete-training lists Teacher as its only authorized role.

        Design: Corner/rbac/coordinator_cannot_complete_training_returns_forbidden
        """
        cycle = make_cycle()
        course = make_course(cycle["id"])
        teacher = make_teacher()
        auth = make_authorization(teacher["id"], course["id"])
        res = api.complete_training(auth["id"], COORD)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)
        assert get_authorization(auth["id"])["status"] == "PENDING_TRAINING"


class TestEntityBackedOwnership:
    def test_student_cannot_register_for_another_student(self, api):
        """PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id`
        of the acting Student, and ownership checks on any resource that
        references a student compare the resource's `student_id` field to
        `X-User-ID` — this governs creating a registration, cancelling one's
        own registration, submitting or resubmitting a fee-reduction
        application, reading one's own statement, and reading filtered lists"

        Design: Corner/rbac/student_cannot_register_for_another_student
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])
        student_a = make_student(full_name="Stu A")
        student_b = make_student(full_name="Stu B")
        res = api.create_registration(
            create_registration_payload(student_b["id"], course["id"]),
            make_student_headers(student_a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_teacher_cannot_complete_training_for_another_teacher(self, api):
        """PRD §3.2: "Training is attested by the teacher on the record, and
        only by that teacher: the caller's identity must match the record's
        `teacher_id`, otherwise the attestation is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/teacher_cannot_complete_training_for_another_teacher
        """
        cycle = make_cycle()
        course = make_course(cycle["id"])
        teacher_1 = make_teacher(full_name="T One", email="t1@x.edu")
        teacher_2 = make_teacher(full_name="T Two", email="t2@x.edu")
        auth = make_authorization(teacher_1["id"], course["id"])
        res = api.complete_training(auth["id"], make_teacher_headers(teacher_2["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)
        assert get_authorization(auth["id"])["status"] == "PENDING_TRAINING"

    def test_teacher_cannot_file_irregularity_without_assignment(self, api):
        """PRD §3.6: "The filing is done by a teacher, and only by a teacher
        who holds an `ASSIGNED` proctor assignment on the session being
        reported — anyone else is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/teacher_cannot_file_irregularity_without_assignment
        """
        scenario = setup_sat_scenario(num_students=1, present=1, with_proctor=True)
        bystander = make_teacher(full_name="T Bystander", email="bys@x.edu")
        res = api.create_irregularity_report(
            {
                "session_id": scenario["session"]["id"],
                "category": "MISCONDUCT",
                "details": "Bystander report",
            },
            make_teacher_headers(bystander["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)
        reports, meta = validate_paginated(
            api.list_irregularity_reports(
                COORD, params={"session_id": scenario["session"]["id"]}
            )
        )
        assert reports == [], "the rejected filing must not persist a report"

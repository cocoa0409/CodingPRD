"""Enrollment creation: capacity boundary, optimistic concurrency, initial states."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_open_year_with_section, setup_family_with_enrollment,
    create_family, create_student, enroll_student_fresh,
    get_section, get_enrollment, get_milestone_for_student,
    get_commitment_for_family,
)

ADMIN = TEST_USERS["admin_headers"]


class TestCapacityBoundary:
    def test_exact_fill_flips_full_and_next_enrollment_rejected(self):
        """PRD §3.2: "when an enrollment raises `enrolled_count` to equal `capacity`
        the section flips `OPEN` → `FULL`". PRD §3.3: "an enrollment attempted when
        `enrolled_count` has already reached `capacity` fails with
        `ERR_SECTION_FULL`".

        Design: Difficulty/boundary_precision_check/section_capacity_exact_fill_third_enrollment_returns_section_full
        """
        ctx = setup_open_year_with_section(grade="G2", capacity=2)
        section = ctx["section"]
        family = create_family()
        students = [
            create_student(family["id"], grade="G2", hebrew_level="BEGINNER")
            for _ in range(3)
        ]
        enroll_student_fresh(section["id"], students[0]["id"])
        enroll_student_fresh(section["id"], students[1]["id"])
        full = get_section(section["id"])
        assert full["enrolled_count"] == 2
        assert full["status"] == "FULL"
        resp = api_client.create_enrollment(
            section["id"],
            {"student_id": students[2]["id"],
             "expected_section_version": full["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SECTION_FULL)
        after = get_section(section["id"])
        assert after["enrolled_count"] == 2

    def test_one_below_capacity_leaves_section_open(self):
        """PRD §3.2: "when an enrollment raises `enrolled_count` to equal `capacity`
        the section flips `OPEN` → `FULL`" — one below capacity the section stays
        OPEN; §3.3: "an enrollment attempted when `enrolled_count` has already
        reached `capacity` fails with `ERR_SECTION_FULL`".

        Design: Difficulty/boundary_precision_check/section_capacity_exact_fill_third_enrollment_returns_section_full
        """
        ctx = setup_open_year_with_section(grade="G2", capacity=2)
        section = ctx["section"]
        family = create_family()
        student = create_student(family["id"], grade="G2", hebrew_level="BEGINNER")
        enroll_student_fresh(section["id"], student["id"])
        mid = get_section(section["id"])
        assert mid["enrolled_count"] == 1
        assert mid["status"] == "OPEN"
        # The second seat is still available at enrolled_count == capacity - 1.
        student2 = create_student(family["id"], grade="G2", hebrew_level="BEGINNER")
        enr2 = enroll_student_fresh(section["id"], student2["id"])
        assert enr2["status"] == "REGISTERED"


class TestOccSection:
    def test_stale_section_version_rejected_fresh_accepted(self):
        """PRD §2.7: "If the section's current `version` has advanced since that
        observation — for example because another enrollment legitimately claimed a
        seat — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §3.3: "The section's `enrolled_count` increases by one and its `version`
        bumps".

        Design: Corner/cross_cutting/occ_stale_section_version_rejected_fresh_accepted
        """
        ctx = setup_open_year_with_section()
        section = ctx["section"]
        assert section["version"] == 1
        family = create_family()
        st1 = create_student(family["id"])
        st2 = create_student(family["id"])
        enroll_student_fresh(section["id"], st1["id"])
        # Reuse the pre-first-enrollment version (1) — now stale.
        resp = api_client.create_enrollment(
            section["id"],
            {"student_id": st2["id"], "expected_section_version": section["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        fresh = get_section(section["id"])
        assert fresh["version"] == 2
        enr2 = enroll_student_fresh(section["id"], st2["id"])
        assert get_section(section["id"])["enrolled_count"] == 2
        assert enr2["status"] == "REGISTERED"


class TestInitialStates:
    def test_fresh_entities_land_in_initial_states(self):
        """PRD §3.1: "A new year starts in `SETUP`." §3.1: "the plan starts in
        `DRAFT`." §3.2: "a new teacher starts in `APPLIED`." §3.2: "A section starts
        in `OPEN` with `enrolled_count` 0." §3.3: "A successful enrollment is created
        in `REGISTERED` status." §3.4: "A milestone is auto-created in `TRACKING`".
        §3.8: "Each family's volunteer obligation lives on its VolunteerCommitment,
        auto-created in `OPEN`... with `required_hours` copied from the year's
        configuration".

        Design: Corner/state_machines/initial_states_and_payment_auto_transitions
        """
        from test_helpers import create_year_with_plan, create_teacher_payload
        year, plan = create_year_with_plan()
        assert year["status"] == "SETUP"
        assert plan["status"] == "DRAFT"
        teacher = get_success_data(
            api_client.create_teacher(create_teacher_payload(), ADMIN), 201
        )
        assert teacher["status"] == "APPLIED"
        # Move the year OPEN with the plan, then finish the hiring pipeline.
        get_success_data(api_client.submit_security_plan(plan["id"], ADMIN))
        get_success_data(api_client.approve_security_plan(plan["id"], ADMIN))
        get_success_data(api_client.open_school_year(year["id"], ADMIN))
        get_success_data(api_client.vet_teacher(teacher["id"], ADMIN))
        get_success_data(api_client.hire_teacher(teacher["id"], ADMIN))
        from test_helpers import create_section_payload
        section = get_success_data(
            api_client.create_section(
                year["id"], {**create_section_payload(), "teacher_id": teacher["id"]},
                ADMIN,
            ),
            201,
        )
        assert section["status"] == "OPEN"
        assert section["enrolled_count"] == 0
        family = create_family()
        student = create_student(family["id"])
        enr = enroll_student_fresh(section["id"], student["id"])
        assert enr["status"] == "REGISTERED"
        milestone = get_milestone_for_student(student["id"])
        assert milestone["status"] == "TRACKING"
        commitment = get_commitment_for_family(family["id"])
        assert commitment["status"] == "OPEN"
        assert commitment["required_hours"] == 8


class TestSeatConservation:
    def test_enroll_then_withdraw_restores_seat_count(self):
        """PRD §3.7: "The section immediately feels the departure: its
        `enrolled_count` decreases by one, its `version` bumps, and if the section
        was `FULL` and the count has fallen below `capacity` it reopens to `OPEN`."
        PRD §3.7: "withdrawal moves an enrollment from `REGISTERED` or `ACTIVE`...
        to `WITHDRAWN`".

        Design: Difficulty/compensating_invariant/enroll_then_withdraw_restores_seat_count
        """
        ctx = setup_open_year_with_section(grade="G2", capacity=1)
        section = ctx["section"]
        fam_a = create_family()
        stu_a = create_student(fam_a["id"], grade="G2", hebrew_level="BEGINNER")
        enr_a = enroll_student_fresh(section["id"], stu_a["id"])
        full = get_section(section["id"])
        assert full["enrolled_count"] == 1 and full["status"] == "FULL"

        get_success_data(api_client.withdraw_enrollment(enr_a["id"], ADMIN))
        mid = get_section(section["id"])
        assert mid["enrolled_count"] == 0
        assert mid["status"] == "OPEN"
        assert get_enrollment(enr_a["id"])["status"] == "WITHDRAWN"

        # The freed seat is reusable by a different family's student.
        fam_b = create_family()
        stu_b = create_student(fam_b["id"], grade="G2", hebrew_level="BEGINNER")
        enr_b = enroll_student_fresh(section["id"], stu_b["id"])
        end = get_section(section["id"])
        assert end["enrolled_count"] == 1
        assert end["status"] == "FULL"

    def test_full_section_reopens_after_withdrawal_from_full(self):
        """PRD §3.2: "when a withdrawal lowers `enrolled_count` back below
        `capacity` a `FULL` section flips back to `OPEN` — both automatic, no client
        call involved".

        Design: Difficulty/compensating_invariant/enroll_then_withdraw_restores_seat_count
        """
        ctx = setup_open_year_with_section(grade="G2", capacity=2)
        section = ctx["section"]
        family = create_family()
        s1 = create_student(family["id"], grade="G2", hebrew_level="BEGINNER")
        s2 = create_student(family["id"], grade="G2", hebrew_level="BEGINNER")
        e1 = enroll_student_fresh(section["id"], s1["id"])
        enroll_student_fresh(section["id"], s2["id"])
        assert get_section(section["id"])["status"] == "FULL"
        get_success_data(api_client.withdraw_enrollment(e1["id"], ADMIN))
        after = get_section(section["id"])
        assert after["enrolled_count"] == 1
        assert after["status"] == "OPEN"

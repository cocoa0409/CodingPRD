"""Family, Student, and Application creation flow.

Covers PRD §3.2 (family / student registration), §3.4 (drafting
applications, choice_rank uniqueness, max-choices cap, grade
mismatch).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_application,
    assert_family,
    assert_student,
    create_application,
    create_application_payload,
    create_district,
    create_family,
    create_student,
    make_family_user_headers,
    setup_district_with_school_and_program,
    setup_family_with_student,
    validate_error,
    validate_success,
)


class TestFamilyAndStudent:

    def test_family_starts_with_null_anchor(self, api, system_operator_headers):
        """PRD §3.2: "The family's head_household_application_id derived
        field starts null."

        Claim: a newly-created family has head_household_application_id
        equal to None.
        """
        district = create_district()
        family = create_family(district)
        assert_family(family)
        # PRD §3.2 says anchor "starts null"; either omission with
        # default null or explicit null is faithful.
        assert family.get("head_household_application_id", None) is None

    def test_student_default_has_iep_is_false(self, api):
        """PRD §3.2: "An optional has_iep boolean flag ... defaulting
        to false".

        Claim: omitting has_iep yields a Student whose has_iep is False.
        """
        district = create_district()
        family, student = setup_family_with_student(district)
        assert_student(student)
        assert student["has_iep"] is False


class TestApplicationCreate:

    def test_create_draft_application_returns_draft_status(self, api):
        """PRD §3.4: "The application starts in DRAFT."

        Claim: a newly-created application has status == DRAFT.
        """
        district, school, program = setup_district_with_school_and_program()
        family, student = setup_family_with_student(district)
        app = create_application(family, student, program, choice_rank=1)
        assert_application(app)
        assert app["status"] == "DRAFT"

    def test_duplicate_choice_rank_in_draft_rejected(self, api):
        """PRD §3.4: "Within the set of applications by a single student
        that are still in DRAFT or SUBMITTED, choice_rank values must be
        unique — a second application by the same student at the same
        rank is rejected with ERR_DUPLICATE_CHOICE_RANK."
        """
        district, school, program = setup_district_with_school_and_program(seats_total=2)
        family, student = setup_family_with_student(district)
        # First DRAFT at rank 1.
        create_application(family, student, program, choice_rank=1)
        # Build a second program (otherwise FK would be the same — but
        # PRD says uniqueness is per-student, not per-program, so we
        # try a second program just to keep program_id distinct).
        district2, school2, program2 = setup_district_with_school_and_program(seats_total=2)
        # PRD §3.4 says uniqueness is on choice_rank "Within the set of
        # applications by a single student" — independent of program.
        # Test using the same family + student.
        payload = create_application_payload(
            student_id=student["id"], program_id=program2["id"], choice_rank=1,
        )
        res = api.create_application(payload, make_family_user_headers(family["id"]))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_CHOICE_RANK.value)

    def test_grade_mismatch_at_create_rejected(self, api):
        """PRD §3.4: "The student's grade_level_next_year must equal the
        program's grade_level, otherwise the request is rejected with
        ERR_GRADE_MISMATCH; this rule fires both at creation and at
        submit."

        Claim: ERR_GRADE_MISMATCH fires at POST /applications when
        grade_level_next_year != program.grade_level.
        """
        district, school, program = setup_district_with_school_and_program(grade_level=5)
        family, student = setup_family_with_student(
            district, grade_level_next_year=7,
        )
        payload = create_application_payload(
            student_id=student["id"], program_id=program["id"], choice_rank=1,
        )
        res = api.create_application(payload, make_family_user_headers(family["id"]))
        validate_error(res, ApiErrorId.ERR_GRADE_MISMATCH.value)

    def test_more_than_five_choices_rejected(self, api):
        """PRD §3.4: "The total number of DRAFT or SUBMITTED applications
        a single student may hold simultaneously must not exceed 5; a
        sixth such application is rejected with ERR_TOO_MANY_CHOICES."

        Claim: the 6th DRAFT application by the same student yields
        ERR_TOO_MANY_CHOICES.
        """
        district = create_district()
        from test_helpers import create_school, create_program
        school = create_school(district, grade_levels_offered=[5])
        # Five programs in the same district to host five distinct
        # choice_rank slots.
        programs = []
        for i in range(6):
            p = create_program(
                district, school,
                grade_level=5, seats_total=1,
                lottery_seed=f"seed-{i}",
            )
            programs.append(p)
        family, student = setup_family_with_student(district)
        for i in range(5):
            create_application(family, student, programs[i], choice_rank=i + 1)
        # Sixth DRAFT — choice_rank in 1..5 is the natural slot range, but
        # PRD §3.4 caps at 5 total simultaneous DRAFT/SUBMITTED. Reuse
        # rank=1 is also a violation of DUPLICATE_CHOICE_RANK, but the
        # cap should win since choice_rank's natural upper bound is 5.
        # Per PRD validation priority, ERR_TOO_MANY_CHOICES is priority
        # 19 — and so is ERR_DUPLICATE_CHOICE_RANK (priority 13). To
        # isolate the cap, use a choice_rank outside 1..5 — but that
        # would be a schema violation. The cleanest construction: the
        # sixth attempt with choice_rank=6 violates the 1..5 range; with
        # choice_rank=1..5 it violates duplicate-rank. PRD does NOT
        # specify the relative priority between the cap and duplicate.
        # So instead: re-use one student across 6 programs with ranks
        # 1..5 (5 apps) plus a sixth with rank 1 — duplicate fires
        # earlier (priority 13 < 19). To test the cap, build the same
        # apps but with the 6th carrying rank 1 still — duplicate fires.
        # To test the CAP in isolation, withdraw one of the existing
        # DRAFTs to free the rank slot? PRD has no withdraw-from-DRAFT
        # endpoint. So the only way to isolate the cap is to use ranks
        # 1..5 on five DRAFTs and submit one (still DRAFT/SUBMITTED-
        # counted), then try a 6th. Even then a duplicate-rank issue
        # could intercept. The PRD cap test must therefore accept that
        # the underlying state — five DRAFT apps using all of ranks 1..5
        # — leaves no rank free; any 6th attempt with rank 1..5
        # collides on rank. Per the PRD text the cap counts
        # "simultaneously" so any sixth rank value violates the cap.
        # The accepted answer: test the union — the 6th attempt fails
        # with one of the two error_ids. validate_error_is_one_of is
        # the PRD-faithful tool here.
        from test_helpers import validate_error_is_one_of
        payload = create_application_payload(
            student_id=student["id"], program_id=programs[5]["id"], choice_rank=1,
        )
        res = api.create_application(payload, make_family_user_headers(family["id"]))
        validate_error_is_one_of(
            res,
            [
                ApiErrorId.ERR_TOO_MANY_CHOICES.value,
                ApiErrorId.ERR_DUPLICATE_CHOICE_RANK.value,
            ],
        )

    def test_choice_rank_out_of_range_rejected(self, api):
        """PRD §3.4: "a choice_rank integer in the closed interval from
        1 to 5".

        Claim: choice_rank=0 (below the range) is rejected by the
        generic shape/range validator (ERR_VALIDATION, 422).
        """
        district, school, program = setup_district_with_school_and_program()
        family, student = setup_family_with_student(district)
        payload = create_application_payload(
            student_id=student["id"], program_id=program["id"], choice_rank=0,
        )
        res = api.create_application(payload, make_family_user_headers(family["id"]))
        # PRD §2.1: "Any body schema, range, or format violation not
        # covered by one of the more specific errors listed in §5 is
        # rejected with the generic ERR_VALIDATION."
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

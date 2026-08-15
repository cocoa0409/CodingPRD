"""Member enrollment validation, project lifecycle, and the suspension cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    TEST_DEFAULTS,
    assert_project,
    build_approved_record_book,
    complete_project_with_grade,
    create_active_member,
    create_draft_record_book_with_entry,
    create_member_payload,
    create_project_payload,
    make_member_headers,
    make_volunteer_headers,
    setup_active_member_with_project,
    setup_club_with_volunteers,
    validate_error,
    validate_success,
)


class TestMemberEnrollmentValidation:
    @pytest.mark.parametrize("missing_field", ["full_name", "birth_date", "club_id"])
    def test_member_missing_required_field_rejected(self, api, missing_field):
        """PRD §3.3: "A `Volunteer` or `ProgramAdmin` enrolls a youth member with
        a `full_name`, a `birth_date` (an ISO 8601 calendar date used to derive
        the member's age division), the home `club_id`, and an optional
        `is_club_officer` flag that defaults to false and later feeds the
        leadership bonus in record-book scoring (§3.5)." PRD §2.9: "required
        input fields are present, enum values are valid,
        `ends_at` is strictly after `starts_at`, and amounts are non-negative;
        otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/member_missing_required_field_rejected
        """
        ctx = setup_club_with_volunteers()
        payload = create_member_payload(ctx["club"]["id"])
        del payload[missing_field]
        res = api.create_member(payload, make_volunteer_headers(ctx["vol1"]["id"]))
        validate_error(res, "ERR_INVALID_REQUEST")


class TestProjectValidation:
    def test_project_invalid_enum_rejected(self, api):
        """PRD §3.4: "It is created — by the member themselves or by a volunteer
        — with a `member_id`, a `project_type` of BEEF, SHEEP, SWINE, CROPS,
        FOODS, or ROBOTICS, and a `program_year` such as 2026; it starts in
        PLANNED status with `grade` NONE." PRD §2.9: "required
        input fields are present, enum values are valid, `ends_at` is strictly
        after `starts_at`, and amounts are non-negative; otherwise
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/project_invalid_enum_rejected
        """
        ctx = setup_club_with_volunteers()
        member = create_active_member(ctx["club"]["id"], ctx["vol1"]["id"])
        payload = create_project_payload(member["id"], project_type="LLAMA")
        res = api.create_project(payload, make_member_headers(member["id"]))
        validate_error(res, "ERR_INVALID_REQUEST")


class TestProjectStateMachine:
    def test_complete_from_planned_rejected(self, api):
        """PRD §3.4: "Completion is a volunteer's judgment call with documentary
        backing: completing a project (ACTIVE → COMPLETED) requires that a
        record book exists for the project in APPROVED status, and the volunteer
        supplies a `grade` of A, B, or C, which is stored on the project and
        later feeds scholarship points (§3.9); completion recomputes the
        member's posture." PRD §3.3: "any transition attempted from a state
        other than its declared from-state is rejected with `ERR_INVALID_STATE`
        (HTTP 409) — here and everywhere else in this section."

        Design: Corner/state_machines/project_invalid_transition_complete_from_planned
        """
        ctx = setup_club_with_volunteers()
        member = create_active_member(ctx["club"]["id"], ctx["vol1"]["id"])
        project = validate_success(
            api.create_project(
                create_project_payload(member["id"]), make_member_headers(member["id"])
            ),
            201,
        )
        assert project["status"] == "PLANNED"
        res = api.complete_project(
            project["id"], {"grade": "A"}, make_volunteer_headers(ctx["vol1"]["id"])
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestMemberSuspendCascade:
    def test_suspend_drops_active_project_and_rejects_draft_book(self, api):
        """PRD §3.3: "Suspension moves ACTIVE → SUSPENDED and is the system's
        big eraser: it forces the member's `eligibility_posture` to INELIGIBLE
        and drops every project of the member that is still PLANNED or ACTIVE,
        moving each to DROPPED." PRD §3.4: "Dropping an ACTIVE project also
        rejects its record book if that book is still in flight — a book in
        DRAFT, SUBMITTED, UNDER_REVIEW, or RETURNED moves to REJECTED — while a
        book already APPROVED or REJECTED is untouched."

        Design: Difficulty/transitive_cascade/member_suspend_drops_project_rejects_record_book
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        rb = create_draft_record_book_with_entry(project["id"], member["id"])
        assert rb["status"] == "DRAFT"

        suspended = validate_success(
            api.suspend_member(member["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert suspended["enrollment_status"] == "SUSPENDED"
        assert suspended["eligibility_posture"] == "INELIGIBLE", (
            "suspension must force the posture to INELIGIBLE"
        )

        project_after = validate_success(
            api.get_project(project["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert project_after["status"] == "DROPPED", (
            f"ACTIVE project must be dropped by suspension, got {project_after['status']}"
        )

        rb_after = validate_success(
            api.get_record_book(rb["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert rb_after["status"] == "REJECTED", (
            f"in-flight DRAFT book must be rejected through the drop cascade, "
            f"got {rb_after['status']}"
        )

    def test_suspend_leaves_completed_project_untouched(self, api):
        """PRD §3.3: "it forces the member's `eligibility_posture` to INELIGIBLE
        and drops every project of the member that is still PLANNED or ACTIVE,
        moving each to DROPPED."

        Design: Difficulty/transitive_cascade/member_suspend_drops_project_rejects_record_book
        """
        ctx = setup_club_with_volunteers()
        member, project = setup_active_member_with_project(ctx)
        build_approved_record_book(ctx, member, project)
        completed = complete_project_with_grade(project["id"], ctx["vol1"]["id"], "A")
        assert completed["status"] == "COMPLETED"

        validate_success(
            api.suspend_member(member["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        project_after = validate_success(
            api.get_project(project["id"], make_volunteer_headers(ctx["vol1"]["id"])), 200
        )
        assert_project(project_after)
        assert project_after["status"] == "COMPLETED", (
            "only PLANNED or ACTIVE projects are dropped; COMPLETED must survive suspension"
        )
        assert project_after["grade"] == "A"

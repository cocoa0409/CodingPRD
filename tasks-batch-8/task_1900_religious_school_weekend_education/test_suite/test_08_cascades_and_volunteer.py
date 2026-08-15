"""Transitive cascades: teacher separation chain, volunteer-void chain, volunteer
hours filtering, milestone scheduling gates."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_open_year_with_section, setup_section_with_attendance,
    setup_family_with_enrollment, create_family, create_student,
    enroll_student_fresh, create_sessions, get_section,
    get_milestone_for_student, get_commitment_for_family,
    fulfill_commitment,
)

ADMIN = TEST_USERS["admin_headers"]


class TestTeacherSeparationCascade:
    def test_depth3_cascade_unstaffs_cancels_reevaluates(self):
        """PRD §3.2: "Separating a `HIRED` teacher triggers a three-hop cascade
        that keeps the schedule consistent: first, every section assigned to that
        teacher in `OPEN` or `FULL` status has its `teacher_id` cleared to null and
        its `staffing_status` recomputed to `UNSTAFFED`, with each such section's
        `version` bumping; second, every `SCHEDULED` session of each unstaffed
        section moves to `CANCELLED` with `cancel_reason` `TEACHER_SEPARATION`;
        third, for each cancelled session the attendance of the section's enrolled
        students is recomputed with the cancelled session excluded, and every
        affected Milestone is re-evaluated against the threshold".

        Design: Difficulty/transitive_cascade/teacher_separation_cascade_section_session_milestone
        """
        ctx = setup_open_year_with_section()
        section, teacher = ctx["section"], ctx["teacher"]
        bundle = setup_family_with_enrollment(section, 1)
        student = bundle["students"][0]
        s1, s2 = create_sessions(section["id"], ["2026-09-13", "2026-09-20"])

        sep = get_success_data(api_client.separate_teacher(teacher["id"], ADMIN))
        assert sep["status"] == "SEPARATED"

        # Hop 1: section unstaffed.
        section_now = get_section(section["id"])
        assert section_now["teacher_id"] is None
        assert section_now["staffing_status"] == "UNSTAFFED"
        # Hop 2: both SCHEDULED sessions cancelled with the cascade reason.
        for s in (s1, s2):
            s_now = get_success_data(api_client.get_session(s["id"], ADMIN))
            assert s_now["status"] == "CANCELLED"
            assert s_now["cancel_reason"] == "TEACHER_SEPARATION"
        # Hop 3: milestone re-evaluated; no held sessions -> 0.0, TRACKING.
        milestone = get_milestone_for_student(student["id"])
        assert milestone["status"] == "TRACKING"
        assert milestone["current_attendance_pct"] == pytest.approx(0.0, abs=0.001)

    def test_separation_of_vetted_teacher_has_no_cascade(self):
        """PRD §3.2: "Separating a `VETTED` teacher simply moves them to
        `SEPARATED`." — no section cascade, because a VETTED teacher cannot be
        assigned to a section (only `HIRED` teachers may be assigned).

        Design: Difficulty/transitive_cascade/teacher_separation_cascade_section_session_milestone
        """
        from test_helpers import create_teacher_payload
        teacher = get_success_data(
            api_client.create_teacher(create_teacher_payload(), ADMIN), 201
        )
        get_success_data(api_client.vet_teacher(teacher["id"], ADMIN))
        sep = get_success_data(api_client.separate_teacher(teacher["id"], ADMIN))
        assert sep["status"] == "SEPARATED"


class TestVolunteerVoidCascade:
    def test_entry_void_reverts_commitment_and_scheduled_milestone(self):
        """PRD §3.8: "When the void drops the family's total back below
        `required_hours`, the commitment regresses `FULFILLED` → `OPEN`, and —
        because ceremony bookings were contingent on fulfillment — every `SCHEDULED`
        milestone of that family in that year automatically reverts to `ELIGIBLE`."

        Design: Difficulty/transitive_cascade/volunteer_entry_void_cascade_commitment_to_milestone
        """
        ctx = setup_section_with_attendance(
            ["PRESENT", "PRESENT", "PRESENT", "PRESENT", "ABSENT"],
            clock_to="2026-10-11T12:00:00Z",
        )
        family, student, milestone = ctx["family"], ctx["student"], ctx["milestone"]
        assert milestone["status"] == "ELIGIBLE"
        commitment = get_commitment_for_family(family["id"])
        fulfilled = fulfill_commitment(commitment["id"], hours=8, note="Gala setup")
        assert fulfilled["status"] == "FULFILLED"
        entry_id = fulfilled["entries"][0]["entry_id"]
        scheduled = get_success_data(
            api_client.schedule_milestone(
                milestone["id"], {"ceremony_date": "2027-05-16"}, ADMIN
            )
        )
        assert scheduled["status"] == "SCHEDULED"

        # Hop 1: void drops hours below required -> commitment reverts to OPEN.
        voided = get_success_data(
            api_client.void_volunteer_entry(commitment["id"], entry_id, ADMIN)
        )
        assert voided["logged_hours"] == 0
        assert voided["status"] == "OPEN"
        # Hop 2: SCHEDULED milestone reverts to ELIGIBLE (attendance still 80.0,
        # so the revert came from the volunteer link alone).
        m_now = get_success_data(api_client.get_milestone(milestone["id"], ADMIN))
        assert m_now["status"] == "ELIGIBLE"
        assert m_now["current_attendance_pct"] == pytest.approx(80.0, abs=0.001)

    def test_commitment_fulfilled_at_exact_required_hours(self):
        """PRD §3.8: "the moment that sum reaches or exceeds `required_hours` the
        commitment flips `OPEN` → `FULFILLED`".

        Design: Difficulty/transitive_cascade/volunteer_entry_void_cascade_commitment_to_milestone
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_enrollment(ctx["section"], 1)
        commitment = get_commitment_for_family(bundle["family"]["id"])
        fulfilled = fulfill_commitment(commitment["id"], hours=8, note="Booth")
        assert fulfilled["logged_hours"] == 8
        assert fulfilled["status"] == "FULFILLED"


class TestVolunteerHoursFiltering:
    def test_voided_entries_excluded_from_logged_hours(self):
        """PRD §3.8: "The commitment's `logged_hours` is always the sum of `hours`
        over `ACTIVE` entries only — voided entries never count". PRD §3.8: "An
        administrator may void an entry, flipping that entry's status to `VOIDED`
        and recomputing `logged_hours`."

        Design: Corner/calculations/volunteer_logged_hours_exclude_voided
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_enrollment(ctx["section"], 1)
        commitment = get_commitment_for_family(bundle["family"]["id"])
        get_success_data(
            api_client.add_volunteer_entry(
                commitment["id"], {"hours": 5, "note": "Setup"}, ADMIN
            )
        )
        after_two = get_success_data(
            api_client.add_volunteer_entry(
                commitment["id"], {"hours": 4, "note": "Cleanup"}, ADMIN
            )
        )
        assert after_two["logged_hours"] == 9
        assert after_two["status"] == "FULFILLED"
        entry2 = after_two["entries"][1]["entry_id"]
        after_void = get_success_data(
            api_client.void_volunteer_entry(commitment["id"], entry2, ADMIN)
        )
        # The void call's own response already reflects the recompute.
        assert after_void["logged_hours"] == 5
        assert after_void["status"] == "OPEN"


class TestMilestoneScheduleGates:
    def test_schedule_requires_eligible_first(self):
        """PRD §3.4: "Scheduling the ceremony is a deliberate administrative act
        with two gates, checked in a fixed order: first the milestone must be in
        `ELIGIBLE` (`ERR_MILESTONE_NOT_ELIGIBLE`)".

        Design: Corner/validations/milestone_schedule_requires_eligible
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_enrollment(ctx["section"], 1)
        milestone = get_milestone_for_student(bundle["students"][0]["id"])
        assert milestone["status"] == "TRACKING"
        resp = api_client.schedule_milestone(
            milestone["id"], {"ceremony_date": "2027-05-16"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_ELIGIBLE)

    def test_schedule_blocked_until_volunteer_fulfilled(self):
        """PRD §3.4: "only then is the family's VolunteerCommitment for the year
        examined, which must be `FULFILLED` (`ERR_VOLUNTEER_REQUIREMENT_UNMET`)".
        PRD §3.4: "A successful schedule moves the milestone `ELIGIBLE` →
        `SCHEDULED`".

        Design: Difficulty/cross_entity_state_dependency/milestone_schedule_requires_family_volunteer_fulfilled
        """
        ctx = setup_section_with_attendance(
            ["PRESENT", "PRESENT", "PRESENT", "PRESENT", "ABSENT"],
            clock_to="2026-10-11T12:00:00Z",
        )
        family, milestone = ctx["family"], ctx["milestone"]
        assert milestone["status"] == "ELIGIBLE"
        commitment = get_commitment_for_family(family["id"])
        assert commitment["status"] == "OPEN"
        assert commitment["logged_hours"] == 0
        # First schedule attempt: volunteer gate fires.
        resp = api_client.schedule_milestone(
            milestone["id"], {"ceremony_date": "2027-05-16"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_REQUIREMENT_UNMET)
        # Log exactly the required hours -> gate opens.
        fulfilled = fulfill_commitment(commitment["id"], hours=8,
                                       note="Purim carnival booth")
        assert fulfilled["status"] == "FULFILLED"
        scheduled = get_success_data(
            api_client.schedule_milestone(
                milestone["id"], {"ceremony_date": "2027-05-16"}, ADMIN
            )
        )
        assert scheduled["status"] == "SCHEDULED"

    def test_eligible_milestone_schedules_when_commitment_fulfilled(self):
        """PRD §3.4: "A successful schedule moves the milestone `ELIGIBLE` →
        `SCHEDULED` and may record an optional `ceremony_date`."

        Design: Difficulty/cross_entity_state_dependency/milestone_schedule_requires_family_volunteer_fulfilled
        """
        ctx = setup_section_with_attendance(
            ["PRESENT", "PRESENT", "PRESENT", "PRESENT", "PRESENT"],
            clock_to="2026-10-11T12:00:00Z",
        )
        family, milestone = ctx["family"], ctx["milestone"]
        assert milestone["status"] == "ELIGIBLE"
        commitment = get_commitment_for_family(family["id"])
        fulfill_commitment(commitment["id"], hours=8)
        scheduled = get_success_data(
            api_client.schedule_milestone(
                milestone["id"], {"ceremony_date": "2027-05-16"}, ADMIN
            )
        )
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["ceremony_date"] == "2027-05-16"

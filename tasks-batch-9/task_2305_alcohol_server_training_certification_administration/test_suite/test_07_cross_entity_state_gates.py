"""Refusals whose cause lives in an entity the request never names.

A catalogue edit blocks a classroom two entities away, and a regulator's refusal blocks an
employer's staffing decision.
"""
from test_helpers import (
    ApiErrorId,
    assert_employer_location,
    certify_one_server,
    enroll_server,
    get_approval,
    get_certificate_row,
    get_course_row,
    get_enrollment_row,
    get_location,
    get_server,
    get_session,
    lock_roster,
    mark_attendance,
    register_alcohol_server,
    revise_course_content,
    server_assignment_payload,
    set_clock,
    setup_employer_account,
    setup_training_base,
    transmit_and_reject,
    validate_error,
    validate_paginated,
)

TRANSMIT_CLOCK = "2026-08-20T10:00:00Z"


def _revise_the_course_under_a_locked_roster():
    """Lock a roster, then edit the course the session's approval was pinned against."""
    base = setup_training_base()
    server = register_alcohol_server(base["jurisdiction"]["id"])
    enrollment = enroll_server(base["session"]["id"], server["id"])
    lock_roster(base["session"]["id"], base["trainer_headers"])
    mark_attendance(enrollment["id"], True, base["trainer_headers"])

    revise_course_content(base["course"]["id"], contact_hours=5)
    return base, enrollment


class TestCatalogueEditBlocksTheClassroom:
    def test_opening_the_exam_is_refused_because_the_pinned_approval_went_stale(self, api):
        """PRD §3.2: "That version bump has a deliberate consequence: every approval of this
        course sitting in `APPROVED` moves `APPROVED → STALE`, because its
        `pinned_course_version` no longer equals the course's `version`."
        PRD §3.2: "Sessions already pinned to a now-stale approval keep their pin — no
        repinning happens — and they will fail at exam-opening time with
        `ERR_APPROVAL_STALE_CONTENT`."
        PRD §3.2: "An accepted revision applies the supplied changes, raises
        `content_revision_count` by one and increments the course's `version`."

        Design: Difficulty/cross_entity_state_dependency/open_exam_blocked_because_a_course_revision_staled_the_pinned_approval
        """
        base, enrollment = _revise_the_course_under_a_locked_roster()

        response = api.open_exam(base["session"]["id"],
                                 {"proctor_trainer_id": base["trainer"]["id"]},
                                 base["trainer_headers"])
        validate_error(response, ApiErrorId.ERR_APPROVAL_STALE_CONTENT, 409)

        approval = get_approval(base["approval"]["id"])
        assert approval["approval_status"] == "STALE"
        course = get_course_row(base["course"]["id"])
        assert course["status"] == "PUBLISHED", (
            "the revision does not unpublish the course, got "
            f"{course['status']}")
        assert course["content_revision_count"] == 1
        assert course["contact_hours"] == 5

    def test_the_refused_opening_leaves_the_roster_and_the_seat_where_they_were(self, api):
        """PRD §3.6: "On success the session records `proctor_trainer_id`, stamps
        `exam_opened_at` from the logical clock, and every enrollment sitting in `ATTENDED` moves
        `ATTENDED → EXAM_SCHEDULED`."
        PRD §3.6: "Opening the exam moves the class `ROSTER_LOCKED → EXAM_OPEN` and is where
        the heaviest gate sits."
        PRD §3.6: "Opening an attempt on a seat requires the session to be `EXAM_OPEN` and the
        seat to be in `EXAM_SCHEDULED` or `EXAM_FAILED`."

        Design: Difficulty/cross_entity_state_dependency/open_exam_blocked_because_a_course_revision_staled_the_pinned_approval
        """
        base, enrollment = _revise_the_course_under_a_locked_roster()

        api.open_exam(base["session"]["id"],
                      {"proctor_trainer_id": base["trainer"]["id"]},
                      base["trainer_headers"])

        session = get_session(base["session"]["id"])
        assert session["session_status"] == "ROSTER_LOCKED"
        assert session["proctor_trainer_id"] is None
        assert session["exam_opened_at"] is None

        assert get_enrollment_row(enrollment["id"])["enrollment_state"] == "ATTENDED", (
            "no seat advanced to EXAM_SCHEDULED behind the refusal")

        attempts, meta = validate_paginated(
            api.list_exam_attempts(enrollment["id"], base["trainer_headers"]))
        assert meta["total_count"] == 0, (
            f"the refused opening created no attempt, got {meta['total_count']}")


class TestRegistryRefusalBlocksStaffing:
    def test_assigning_a_registry_suspended_server_is_refused(self, api):
        """PRD §3.8: "At a location whose `training_requirement` is `MANDATED`, a server whose
        `work_eligibility` is `RESTRICTED` is refused outright with
        `ERR_SERVER_WORK_RESTRICTED`; an `UNCERTIFIED` server is accepted and simply starts the
        new-hire training window."
        PRD §3.7: "Because the registry refused the record, the certificate's `validity_state`
        moves to `SUSPENDED` — reachable from `ACTIVE` or `GRACE`, and only where the
        jurisdiction actually requires registry submission."
        PRD §2.8: "The server's `active_certificate_id` is re-selected, and then
        `work_eligibility` is derived from the governing certificate: no certificate at all
        yields `UNCERTIFIED`; a governing certificate whose `validity_state` is `ACTIVE` yields
        `ELIGIBLE`; `GRACE` yields `GRACE`; `LAPSED` or `SUSPENDED` yields `RESTRICTED`."

        Design: Difficulty/cross_entity_state_dependency/server_assignment_creation_blocked_by_registry_driven_work_restriction
        """
        base = setup_training_base()
        employer = setup_employer_account(
            base["jurisdiction"]["id"], seat_quantity=0,
            location_specs=[{"location_name": "Alamo Taproom",
                             "annual_premium_cents": 4821734}])
        walk = certify_one_server(base)
        set_clock(TRANSMIT_CLOCK)
        transmit_and_reject(walk["certificate"]["id"], "NAME_MISMATCH")

        response = api.create_server_assignment(
            employer["locations"][0]["id"],
            server_assignment_payload(walk["server"]["id"], role_title="Bartender"),
            employer["employer_headers"])
        validate_error(response, ApiErrorId.ERR_SERVER_WORK_RESTRICTED, 422)

        assert get_server(walk["server"]["id"])["work_eligibility"] == "RESTRICTED"
        certificate = get_certificate_row(walk["certificate"]["id"])
        assert certificate["validity_state"] == "SUSPENDED"
        assert certificate["registry_state"] == "RESUBMIT_REQUIRED"

    def test_the_refused_assignment_leaves_the_location_reading_an_empty_roster(self, api):
        """PRD §3.8: "A fresh location starts with `assigned_server_count`,
        `compliant_server_count`, `grace_server_count` and `restricted_server_count` at zero and
        both `compliance_rate_strict_pct` and `compliance_rate_grace_inclusive_pct` at 100.00."
        PRD §3.8: "When `assigned_server_count` is zero — an empty location has nothing out of
        compliance — both rates read 100.00."
        PRD §3.8: "Otherwise it is `COMPLIANT` at 95.00 or above, `AT_RISK` at 80.00 or above
        but below 95.00, and `NON_COMPLIANT` below 80.00."
        PRD §3.8: "Assignments at a location can be listed with a filter on
        `assignment_state`."

        Design: Difficulty/cross_entity_state_dependency/server_assignment_creation_blocked_by_registry_driven_work_restriction
        """
        base = setup_training_base()
        employer = setup_employer_account(
            base["jurisdiction"]["id"], seat_quantity=0,
            location_specs=[{"location_name": "Alamo Taproom",
                             "annual_premium_cents": 4821734}])
        walk = certify_one_server(base)
        set_clock(TRANSMIT_CLOCK)
        transmit_and_reject(walk["certificate"]["id"], "NAME_MISMATCH")

        api.create_server_assignment(
            employer["locations"][0]["id"],
            server_assignment_payload(walk["server"]["id"], role_title="Bartender"),
            employer["employer_headers"])

        location = get_location(employer["locations"][0]["id"])
        assert_employer_location(location)
        assert location["assigned_server_count"] == 0
        assert location["restricted_server_count"] == 0
        assert location["compliance_rate_strict_pct"] == 100.00, (
            "an empty roster has nothing out of compliance, got "
            f"{location['compliance_rate_strict_pct']}")
        assert location["compliance_posture"] == "COMPLIANT"

        assignments, meta = validate_paginated(api.list_location_server_assignments(
            location["id"], employer["employer_headers"]))
        assert meta["total_count"] == 0, (
            f"the refused request created no assignment, got {meta['total_count']}")

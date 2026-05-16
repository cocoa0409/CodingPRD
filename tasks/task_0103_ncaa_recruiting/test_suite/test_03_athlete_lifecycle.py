"""Athlete lifecycle: registration, eligibility, commitment, enrollment.

PRD §3.2 (athlete creation, eligibility center, commitment, enrollment),
§3.3 (cascade to ACTIVE on enrollment).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_athlete,
    assert_eligibility_record,
    commit_athlete,
    create_athlete,
    create_athlete_payload,
    create_eligibility_record,
    create_eligibility_record_payload,
    create_program,
    enroll_athlete,
    offer_slot,
    setup_enrolled_athlete,
    sign_slot,
    transition_athlete_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.2 Athlete registration
# ===========================================================================
class TestAthleteCreation:
    """PRD §3.2: "An Athlete is registered by a ComplianceOfficer or by
    a Coach with the prospect's full_name, high_school, and
    graduation_year. The new athlete starts in PROSPECTIVE status with
    amateur_status AMATEUR, years_of_eligibility_remaining equal to 4,
    and current_program_id null." """

    def test_create_athlete_initializes_status_and_defaults(
        self, api, officer_headers,
    ):
        """PRD §3.2: "The new athlete starts in PROSPECTIVE status with
        amateur_status AMATEUR, years_of_eligibility_remaining equal to
        4, and current_program_id null."

        Claim: fresh athlete has status=PROSPECTIVE,
        amateur_status=AMATEUR, years_of_eligibility_remaining=4,
        current_program_id=null.
        """
        res = api.create_athlete(
            create_athlete_payload(), officer_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_athlete(data)
        assert data["status"] == "PROSPECTIVE"
        assert data["amateur_status"] == "AMATEUR"
        assert data["years_of_eligibility_remaining"] == 4
        assert data.get("current_program_id") in (None, "")


# ===========================================================================
# §3.2 EligibilityRecord
# ===========================================================================
class TestEligibilityRecord:
    """PRD §3.2: an EligibilityRecord is posted by a ComplianceOfficer
    and is immutable; a second record for the same athlete is rejected."""

    def test_post_eligibility_sets_athlete_eligibility_record_id(
        self, api, officer_headers,
    ):
        """PRD §3.2: "Posting it sets the athlete's eligibility_record_id
        to the new record's id."

        Claim: after POST /eligibility-records, the athlete's
        eligibility_record_id equals the record's id.
        """
        athlete = create_athlete()
        record = create_eligibility_record(
            athlete["id"], decision="QUALIFIER",
        )
        assert_eligibility_record(record)
        # Refresh athlete
        a_resp = api.get_athlete(athlete["id"], officer_headers)
        a_data = validate_success(a_resp)
        assert a_data["eligibility_record_id"] == record["id"], (
            f"athlete.eligibility_record_id should equal record.id "
            f"({record['id']}), got {a_data.get('eligibility_record_id')!r}"
        )

    def test_second_eligibility_record_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.2: "Attempting to post a second record for the same
        athlete is rejected with ERR_ELIGIBILITY_ALREADY_DECIDED."

        Claim: posting a second EligibilityRecord on the same athlete
        -> ERR_ELIGIBILITY_ALREADY_DECIDED.
        """
        athlete = create_athlete()
        create_eligibility_record(athlete["id"], decision="QUALIFIER")
        res = api.create_eligibility_record(
            create_eligibility_record_payload(
                athlete_id=athlete["id"], decision="PARTIAL_QUALIFIER",
            ),
            officer_headers,
        )
        validate_error(res, "ERR_ELIGIBILITY_ALREADY_DECIDED")


# ===========================================================================
# §3.2 Commit transition: eligibility-cleared and signed-slot preconditions
# ===========================================================================
class TestAthleteCommit:
    """PRD §3.2: "The transition requires that the athlete's
    eligibility_record_id is set and the record's decision is QUALIFIER
    or PARTIAL_QUALIFIER (otherwise ERR_ELIGIBILITY_NOT_CLEARED), and
    that at least one ScholarshipSlot for this athlete already sits in
    SIGNED status for the same program_id (otherwise
    ERR_NO_SIGNED_SLOT)." """

    def test_commit_without_eligibility_record_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.2: "The transition requires that the athlete's
        eligibility_record_id is set and the record's decision is
        QUALIFIER or PARTIAL_QUALIFIER (otherwise
        ERR_ELIGIBILITY_NOT_CLEARED)."

        Claim: commit attempt before any EligibilityRecord is posted ->
        ERR_ELIGIBILITY_NOT_CLEARED.
        """
        program = create_program()
        athlete = create_athlete()
        res = api.transition_athlete(
            athlete["id"],
            transition_athlete_payload(
                to_status="COMMITTED", program_id=program["id"],
            ),
            officer_headers,
        )
        validate_error(res, "ERR_ELIGIBILITY_NOT_CLEARED")

    def test_commit_with_non_qualifier_decision_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.2: "The transition requires that the athlete's
        eligibility_record_id is set and the record's decision is
        QUALIFIER or PARTIAL_QUALIFIER (otherwise
        ERR_ELIGIBILITY_NOT_CLEARED)."

        Claim: commit attempt with a NON_QUALIFIER record ->
        ERR_ELIGIBILITY_NOT_CLEARED.
        """
        program = create_program()
        athlete = create_athlete()
        create_eligibility_record(athlete["id"], decision="NON_QUALIFIER")
        res = api.transition_athlete(
            athlete["id"],
            transition_athlete_payload(
                to_status="COMMITTED", program_id=program["id"],
            ),
            officer_headers,
        )
        validate_error(res, "ERR_ELIGIBILITY_NOT_CLEARED")

    def test_commit_without_signed_slot_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.2: "at least one ScholarshipSlot for this athlete
        already sits in SIGNED status for the same program_id
        (otherwise ERR_NO_SIGNED_SLOT)."

        Claim: commit attempt when athlete has QUALIFIER eligibility
        but no SIGNED slot at the destination program ->
        ERR_NO_SIGNED_SLOT.
        """
        program = create_program()
        athlete = create_athlete()
        create_eligibility_record(athlete["id"], decision="QUALIFIER")
        res = api.transition_athlete(
            athlete["id"],
            transition_athlete_payload(
                to_status="COMMITTED", program_id=program["id"],
            ),
            officer_headers,
        )
        validate_error(res, "ERR_NO_SIGNED_SLOT")

    def test_commit_pins_current_program_id(
        self, api, officer_headers,
    ):
        """PRD §3.2: "The transition's side effect is to set
        current_program_id to the supplied program."

        Claim: after PROSPECTIVE->COMMITTED, athlete.current_program_id
        equals the supplied program_id.
        """
        program = create_program()
        athlete = create_athlete()
        create_eligibility_record(athlete["id"], decision="QUALIFIER")
        slot = offer_slot(program["id"], athlete["id"])
        sign_slot(slot["id"])
        a = commit_athlete(athlete["id"], program["id"])
        assert a["status"] == "COMMITTED"
        assert a["current_program_id"] == program["id"]


# ===========================================================================
# §3.2 Enrollment cascade
# ===========================================================================
class TestAthleteEnrollment:
    """PRD §3.2: "On enrollment, the system cascades: every SIGNED slot
    for this athlete at that program transitions to ACTIVE, with
    activated_at pinned to the transition timestamp; ... and the
    program's active_roster_count and total_equivalencies_used are
    recomputed." """

    def test_enroll_cascades_signed_slot_to_active(
        self, api, officer_headers,
    ):
        """PRD §3.2: "every SIGNED slot for this athlete at that
        program transitions to ACTIVE, with activated_at pinned to
        the transition timestamp."

        Claim: after COMMITTED->ENROLLED, the SIGNED slot now has
        status=ACTIVE and activated_at set.
        """
        athlete, program, slot = setup_enrolled_athlete()
        assert athlete["status"] == "ENROLLED"
        assert slot["status"] == "ACTIVE"
        assert slot.get("activated_at"), (
            "activated_at must be set after the SIGNED->ACTIVE cascade"
        )

    def test_enroll_recomputes_program_active_roster_count(
        self, api, officer_headers,
    ):
        """PRD §3.2: "the program's active_roster_count and
        total_equivalencies_used are recomputed."
        PRD §3.3: "active_roster_count is the count of Athlete rows
        whose status is ENROLLED and whose current_program_id equals
        the program's id."

        Claim: a single enrollment moves Program.active_roster_count
        from 0 to 1.
        """
        athlete, program, _slot = setup_enrolled_athlete()
        assert program["active_roster_count"] == 1, (
            f"active_roster_count should be 1 after one enrollment, "
            f"got {program['active_roster_count']}"
        )


# ===========================================================================
# §2.8 Roster cap on enrollment
# ===========================================================================
class TestRosterCapOnEnrollment:
    """PRD §2.8 / §3.3: roster cap blocks COMMITTED->ENROLLED when the
    projected active_roster_count + 1 would exceed roster_cap_count."""

    def test_enroll_blocked_when_roster_at_cap(
        self, api, officer_headers,
    ):
        """PRD §3.3: "an enrollment that would push the count to
        exactly roster_cap_count is permitted, but roster_cap_count +
        1 is not."

        Claim: a program with roster_cap_count=1 already at
        active_roster_count=1 rejects the next ENROLLED transition
        with ERR_ROSTER_CAP_EXCEEDED.
        """
        program = create_program(
            sport="MENS_BASKETBALL",
            scholarship_cap_equivalencies=13.0,
            roster_cap_count=1,
        )
        # First athlete enrolls (fills cap)
        a1, _p, _s = setup_enrolled_athlete(program=program)
        # Second athlete: must be brought up to COMMITTED, then enroll
        # is what we want to fail.
        a2 = create_athlete()
        create_eligibility_record(a2["id"], decision="QUALIFIER")
        slot2 = offer_slot(
            program["id"], a2["id"],
            fractional_equivalency=1.00,
        )
        sign_slot(slot2["id"])
        commit_athlete(a2["id"], program["id"])
        res = api.transition_athlete(
            a2["id"],
            transition_athlete_payload(to_status="ENROLLED"),
            officer_headers,
        )
        validate_error(res, "ERR_ROSTER_CAP_EXCEEDED")
        # PRD §3.3: "blocks the enclosing Athlete ENROLLED transition";
        # the athlete remains in COMMITTED.
        a_resp = api.get_athlete(a2["id"], officer_headers)
        a_data = validate_success(a_resp)
        assert a_data["status"] == "COMMITTED", (
            f"failed enrollment should leave athlete in COMMITTED, "
            f"got {a_data['status']}"
        )


# ===========================================================================
# §2.8 Invalid state transitions
# ===========================================================================
class TestInvalidStateTransitions:
    """PRD §2.8: "The target resource is in a permitted from-state for
    the requested transition; otherwise ERR_INVALID_STATE." """

    def test_enroll_directly_from_prospective_rejected(
        self, api, officer_headers,
    ):
        """PRD §2.8: from-state validity check produces ERR_INVALID_STATE
        when the transition is not permitted from the current state.
        PRD §3.2 lists the valid moves; PROSPECTIVE -> ENROLLED is not
        among them.

        Claim: POST /athletes/{id}/state with to_status=ENROLLED while
        the athlete is PROSPECTIVE -> ERR_INVALID_STATE.
        """
        athlete = create_athlete()
        res = api.transition_athlete(
            athlete["id"],
            transition_athlete_payload(to_status="ENROLLED"),
            officer_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

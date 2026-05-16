"""ScholarshipSlot lifecycle: offer, sign, cap enforcement, revoke.

PRD §3.3 (slot creation, signing, cap rules), §3.7 (ACTIVE->REVOKED
requires SUSTAINED violation).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_scholarship_slot,
    commit_athlete,
    create_athlete,
    create_eligibility_record,
    create_program,
    create_scholarship_slot_payload,
    enroll_athlete,
    offer_slot,
    setup_enrolled_athlete,
    setup_ineligible_athlete_via_violation,
    sign_slot,
    transition_scholarship_slot_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 Slot creation
# ===========================================================================
class TestSlotOffer:
    """PRD §3.3: "A Coach offers a scholarship slot by posting a
    ScholarshipSlot with program_id, athlete_id, fractional_equivalency
    ... and annual_value_cents. The slot is created in OFFERED status." """

    def test_create_slot_in_offered_status(self, api, coach_headers):
        """PRD §3.3: "The slot is created in OFFERED status."

        Claim: POST /scholarship-slots returns 201 with status=OFFERED.
        """
        program = create_program()
        athlete = create_athlete()
        res = api.create_scholarship_slot(
            create_scholarship_slot_payload(
                program_id=program["id"],
                athlete_id=athlete["id"],
                fractional_equivalency=0.50,
                annual_value_cents=2_500_000,
            ),
            coach_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_scholarship_slot(data)
        assert data["status"] == "OFFERED"


# ===========================================================================
# §3.3 Sign preconditions
# ===========================================================================
class TestSlotSign:
    """PRD §3.3 / §2.8: signing requires eligibility cleared, athlete
    available, and cap not exceeded — in that priority order."""

    def test_sign_without_eligibility_cleared_rejected(
        self, api, coach_headers,
    ):
        """PRD §3.3: "the athlete must have a posted EligibilityRecord
        whose decision is QUALIFIER or PARTIAL_QUALIFIER, otherwise
        ERR_ELIGIBILITY_NOT_CLEARED."

        Claim: signing a slot for an athlete with no EligibilityRecord
        -> ERR_ELIGIBILITY_NOT_CLEARED.
        """
        program = create_program()
        athlete = create_athlete()
        slot = offer_slot(program["id"], athlete["id"])
        res = api.transition_scholarship_slot(
            slot["id"],
            transition_scholarship_slot_payload(to_status="SIGNED"),
            coach_headers,
        )
        validate_error(res, "ERR_ELIGIBILITY_NOT_CLEARED")

    def test_sign_with_incomplete_decision_rejected(
        self, api, coach_headers,
    ):
        """PRD §3.3: "the athlete must have a posted EligibilityRecord
        whose decision is QUALIFIER or PARTIAL_QUALIFIER, otherwise
        ERR_ELIGIBILITY_NOT_CLEARED."

        Claim: signing a slot for an athlete with decision=INCOMPLETE
        -> ERR_ELIGIBILITY_NOT_CLEARED.
        """
        program = create_program()
        athlete = create_athlete()
        create_eligibility_record(athlete["id"], decision="INCOMPLETE")
        slot = offer_slot(program["id"], athlete["id"])
        res = api.transition_scholarship_slot(
            slot["id"],
            transition_scholarship_slot_payload(to_status="SIGNED"),
            coach_headers,
        )
        validate_error(res, "ERR_ELIGIBILITY_NOT_CLEARED")

    def test_sign_partial_qualifier_accepted(self, api, coach_headers):
        """PRD §3.3: "decision is QUALIFIER or PARTIAL_QUALIFIER."

        Claim: a PARTIAL_QUALIFIER decision allows OFFERED->SIGNED.
        """
        program = create_program()
        athlete = create_athlete()
        create_eligibility_record(
            athlete["id"], decision="PARTIAL_QUALIFIER",
        )
        slot = offer_slot(program["id"], athlete["id"])
        s = sign_slot(slot["id"])
        assert s["status"] == "SIGNED"

    def test_sign_pins_signed_at(self, api, coach_headers):
        """PRD §3.3: "On success, signed_at is pinned to the request
        timestamp."

        Claim: after OFFERED->SIGNED, the slot carries a signed_at
        timestamp.
        """
        program = create_program()
        athlete = create_athlete()
        create_eligibility_record(athlete["id"], decision="QUALIFIER")
        slot = offer_slot(program["id"], athlete["id"])
        s = sign_slot(slot["id"])
        assert s.get("signed_at"), "signed_at must be set after SIGNED"


# ===========================================================================
# §3.3 Scholarship cap enforcement (boundary precision)
# ===========================================================================
class TestSlotScholarshipCap:
    """PRD §3.3: "Program.total_equivalencies_used plus this slot's
    fractional_equivalency must be less than or equal to its
    scholarship_cap_equivalencies, otherwise
    ERR_SCHOLARSHIP_CAP_EXCEEDED." """

    def test_sign_at_exact_cap_boundary_accepted(self, api, coach_headers):
        """PRD §3.3: "Program.total_equivalencies_used plus this slot's
        fractional_equivalency must be less than or equal to its
        scholarship_cap_equivalencies."

        Claim: program with cap=1.00, first slot fractional=1.00 ->
        SIGNED OK (total goes to exactly the cap).
        """
        program = create_program(
            sport="MENS_BASKETBALL",
            scholarship_cap_equivalencies=1.00,
            roster_cap_count=10,
        )
        athlete = create_athlete()
        create_eligibility_record(athlete["id"], decision="QUALIFIER")
        slot = offer_slot(
            program["id"], athlete["id"],
            fractional_equivalency=1.00,
        )
        s = sign_slot(slot["id"])
        assert s["status"] == "SIGNED"

    def test_sign_above_cap_rejected(self, api, coach_headers):
        """PRD §3.3: "Program.total_equivalencies_used plus this slot's
        fractional_equivalency must be less than or equal to its
        scholarship_cap_equivalencies, otherwise
        ERR_SCHOLARSHIP_CAP_EXCEEDED."

        Claim: program with cap=1.00 already at total=1.00, second
        signing of 0.01 -> ERR_SCHOLARSHIP_CAP_EXCEEDED.
        """
        program = create_program(
            sport="MENS_BASKETBALL",
            scholarship_cap_equivalencies=1.00,
            roster_cap_count=10,
        )
        a1 = create_athlete()
        create_eligibility_record(a1["id"], decision="QUALIFIER")
        slot1 = offer_slot(
            program["id"], a1["id"], fractional_equivalency=1.00,
        )
        sign_slot(slot1["id"])
        # Now total_equivalencies_used == 1.00 == cap.
        a2 = create_athlete()
        create_eligibility_record(a2["id"], decision="QUALIFIER")
        slot2 = offer_slot(
            program["id"], a2["id"], fractional_equivalency=0.01,
        )
        res = api.transition_scholarship_slot(
            slot2["id"],
            transition_scholarship_slot_payload(to_status="SIGNED"),
            coach_headers,
        )
        validate_error(res, "ERR_SCHOLARSHIP_CAP_EXCEEDED")


# ===========================================================================
# §3.3 Athlete availability
# ===========================================================================
class TestSlotAthleteAvailability:
    """PRD §3.3: "a slot can only be signed for an athlete who is not
    currently in TRANSFER_PORTAL or INELIGIBLE (otherwise
    ERR_ATHLETE_NOT_AVAILABLE)." """

    def test_sign_for_ineligible_athlete_rejected(
        self, api, coach_headers,
    ):
        """PRD §3.3: "a slot can only be signed for an athlete who is
        not currently in TRANSFER_PORTAL or INELIGIBLE (otherwise
        ERR_ATHLETE_NOT_AVAILABLE)."

        Claim: signing a fresh slot for an athlete in INELIGIBLE ->
        ERR_ATHLETE_NOT_AVAILABLE.
        """
        # Force an athlete into INELIGIBLE via a LEVEL_I SUSTAINED
        # violation cascade.
        program, athlete, _v = setup_ineligible_athlete_via_violation()
        assert athlete["status"] == "INELIGIBLE"
        # Coach offers a new slot for the same program/athlete.
        slot = offer_slot(program["id"], athlete["id"])
        res = api.transition_scholarship_slot(
            slot["id"],
            transition_scholarship_slot_payload(to_status="SIGNED"),
            coach_headers,
        )
        validate_error(res, "ERR_ATHLETE_NOT_AVAILABLE")


# ===========================================================================
# §3.3 OFFERED -> WITHDRAWN
# ===========================================================================
class TestSlotWithdrawn:
    """PRD §3.3: "A coach may also walk an offer back via OFFERED ->
    WITHDRAWN; this terminal transition takes no preconditions and
    produces no side effects." """

    def test_withdraw_offer_succeeds(self, api, coach_headers):
        """PRD §3.3: "A coach may also walk an offer back via OFFERED
        -> WITHDRAWN; this terminal transition takes no preconditions
        and produces no side effects."

        Claim: OFFERED -> WITHDRAWN succeeds with no eligibility check.
        """
        program = create_program()
        athlete = create_athlete()
        # No EligibilityRecord — withdraw should still work.
        slot = offer_slot(program["id"], athlete["id"])
        res = api.transition_scholarship_slot(
            slot["id"],
            transition_scholarship_slot_payload(to_status="WITHDRAWN"),
            coach_headers,
        )
        data = validate_success(res)
        assert data["status"] == "WITHDRAWN"


# ===========================================================================
# §3.3 ACTIVE -> REVOKED requires SUSTAINED violation
# ===========================================================================
class TestSlotRevoke:
    """PRD §3.3: "It requires that a ComplianceViolation linked to this
    slot's athlete_id exists with outcome SUSTAINED and severity of
    either LEVEL_I or LEVEL_II; absent such a violation, the transition
    is rejected with ERR_NO_SUSTAINED_VIOLATION." """

    def test_revoke_active_without_sustained_violation_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.3: "absent such a violation, the transition is
        rejected with ERR_NO_SUSTAINED_VIOLATION."

        Claim: ACTIVE -> REVOKED with no SUSTAINED violation on the
        athlete -> ERR_NO_SUSTAINED_VIOLATION.
        """
        athlete, program, slot = setup_enrolled_athlete()
        assert slot["status"] == "ACTIVE"
        res = api.transition_scholarship_slot(
            slot["id"],
            transition_scholarship_slot_payload(to_status="REVOKED"),
            officer_headers,
        )
        validate_error(res, "ERR_NO_SUSTAINED_VIOLATION")


# ===========================================================================
# §3.3 SIGNED -> ACTIVE is not directly invocable
# ===========================================================================
class TestSlotNoDirectActive:
    """PRD §3.3: "The SIGNED -> ACTIVE transition is never invoked
    directly. It happens only as part of the Athlete enrollment
    cascade." """

    def test_direct_signed_to_active_rejected(self, api, coach_headers):
        """PRD §3.3: "The SIGNED -> ACTIVE transition is never invoked
        directly. It happens only as part of the Athlete enrollment
        cascade."

        Claim: direct POST /scholarship-slots/{id}/state with
        to_status=ACTIVE on a SIGNED slot -> ERR_INVALID_STATE.
        """
        program = create_program()
        athlete = create_athlete()
        create_eligibility_record(athlete["id"], decision="QUALIFIER")
        slot = offer_slot(program["id"], athlete["id"])
        sign_slot(slot["id"])
        res = api.transition_scholarship_slot(
            slot["id"],
            transition_scholarship_slot_payload(to_status="ACTIVE"),
            coach_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §2.8 Body shape constraints — fractional_equivalency range
# ===========================================================================
class TestSlotBodyShape:
    """PRD §2.6 / §2.8: "fractional_equivalency outside [0.01, 1.00] or
    not at two decimal places" -> ERR_VALIDATION_FAILED."""

    @pytest.mark.parametrize("invalid_fe", [-0.5, 0.0, 1.5])
    def test_create_slot_with_out_of_range_fractional(
        self, api, coach_headers, invalid_fe,
    ):
        """PRD §2.6: "fractional_equivalency outside [0.01, 1.00] or
        not at two decimal places" -> ERR_VALIDATION_FAILED.

        Claim: out-of-range fractional_equivalency -> ERR_VALIDATION_FAILED.
        """
        program = create_program()
        athlete = create_athlete()
        res = api.create_scholarship_slot(
            create_scholarship_slot_payload(
                program_id=program["id"],
                athlete_id=athlete["id"],
                fractional_equivalency=invalid_fe,
            ),
            coach_headers,
        )
        validate_error(res, "ERR_VALIDATION_FAILED")

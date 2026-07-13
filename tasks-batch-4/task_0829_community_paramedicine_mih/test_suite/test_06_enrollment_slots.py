"""Enrollment-slot ledger: the screened-state precedence over the fiscal cap check, the
exact enrollment-cap boundary, and the consume/release slot-conservation invariant."""
from test_helpers import (
    validate_error, ApiErrorId,
    bootstrap, enroll_patient, create_patient, create_referral,
    create_screened_referral, refetch_program, refetch_enrollment,
    assert_slots_conserved,
)


def test_unscreened_accept_on_full_program_returns_state_error(api):
    """PRD 2.6: "Lower-numbered checks always take precedence: a mid-flight state violation
    surfaces before a fiscal check". Since the state check (item 6, ERR_REFERRAL_NOT_SCREENED)
    outranks the fiscal cap check (item 11), an un-screened accept against a full program
    returns the state error, per PRD 3.3: "attempting either transition on a referral that is
    not SCREENED is rejected with ERR_REFERRAL_NOT_SCREENED."

    Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_enrollment_cap
    """
    org = bootstrap(api, program_overrides={"enrollment_cap": 1})
    enroll_patient(api, org)  # fills the single slot
    p2 = create_patient(api, org, full_name="Pat Two")
    ref2 = create_referral(api, org, p2["id"])  # left SUBMITTED (not screened)
    resp = api.accept_referral(ref2["id"], org["coord_headers"])
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_SCREENED)


def test_unscreened_accept_full_program_not_fiscal_error(api):
    """PRD 2.6: "a mid-flight state violation surfaces before a fiscal check". The full pilot
    would otherwise yield ERR_ENROLLMENT_CAP_REACHED (item 11), but the un-screened referral
    must surface the higher-priority state error, never the fiscal one.

    Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_enrollment_cap
    """
    org = bootstrap(api, program_overrides={"enrollment_cap": 1})
    enroll_patient(api, org)
    p2 = create_patient(api, org, full_name="Pat Two")
    ref2 = create_referral(api, org, p2["id"])
    resp = api.accept_referral(ref2["id"], org["coord_headers"])
    error = validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_SCREENED)
    assert error["error_id"] != ApiErrorId.ERR_ENROLLMENT_CAP_REACHED.value


def test_accept_at_enrollment_cap_boundary_rejected(api):
    """PRD 3.3: "the program must have a free slot, meaning its active_enrollment_count is
    strictly less than its enrollment_cap (otherwise ERR_ENROLLMENT_CAP_REACHED)."
    With cap 2 and exactly 2 active enrollments, the third (screened) accept is rejected.

    Design: Difficulty/boundary_precision_check/enrollment_cap_exact_boundary
    """
    org = bootstrap(api, program_overrides={"enrollment_cap": 2})
    enroll_patient(api, org, {"full_name": "Pat A"})
    enroll_patient(api, org, {"full_name": "Pat B"})
    third = create_screened_referral(api, org, {"full_name": "Pat C"})
    resp = api.accept_referral(third["referral_id"], org["coord_headers"])
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_CAP_REACHED)


def test_accept_at_cap_boundary_leaves_count_unchanged(api):
    """PRD 2.9: "A referral cannot be accepted once active_enrollment_count has reached
    enrollment_cap." A rejected third accept at cap 2 leaves active_enrollment_count at 2.

    Design: Difficulty/boundary_precision_check/enrollment_cap_exact_boundary
    """
    org = bootstrap(api, program_overrides={"enrollment_cap": 2})
    enroll_patient(api, org, {"full_name": "Pat A"})
    enroll_patient(api, org, {"full_name": "Pat B"})
    third = create_screened_referral(api, org, {"full_name": "Pat C"})
    api.accept_referral(third["referral_id"], org["coord_headers"])
    program = refetch_program(api, org)
    assert program["active_enrollment_count"] == 2, (
        f"expected active_enrollment_count 2, got {program['active_enrollment_count']}")


def test_discharge_restores_enrollment_slots(api):
    """PRD 2.9: "discharging or withdrawing an enrollment decrements it by one. After either
    change, remaining_slots is recomputed as enrollment_cap minus active_enrollment_count."
    Accepting then discharging on a cap-2 program returns active to 0 and remaining to 2.

    Design: Difficulty/compensating_invariant/enrollment_slot_consume_release_conserves_cap
    """
    org = bootstrap(api, program_overrides={"enrollment_cap": 2})
    enr = enroll_patient(api, org)
    api.discharge_enrollment(enr["enrollment_id"], org["coord_headers"])
    program = refetch_program(api, org)
    assert program["active_enrollment_count"] == 0, (
        f"expected active 0, got {program['active_enrollment_count']}")
    assert program["remaining_slots"] == 2, (
        f"expected remaining 2, got {program['remaining_slots']}")


def test_slot_count_conserves_enrollment_cap_invariant(api):
    """PRD 2.9: "remaining_slots is recomputed as enrollment_cap minus
    active_enrollment_count." The conserved quantity active_enrollment_count +
    remaining_slots always equals enrollment_cap (2), both after an accept consumes a slot
    and after the compensating discharge releases it.

    Design: Difficulty/compensating_invariant/enrollment_slot_consume_release_conserves_cap
    """
    org = bootstrap(api, program_overrides={"enrollment_cap": 2})
    enr = enroll_patient(api, org)
    assert_slots_conserved(refetch_program(api, org), 2)  # after consume
    api.discharge_enrollment(enr["enrollment_id"], org["coord_headers"])
    assert_slots_conserved(refetch_program(api, org), 2)  # after release

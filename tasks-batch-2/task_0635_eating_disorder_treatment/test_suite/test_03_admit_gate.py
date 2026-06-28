"""The admit gate: ordered preconditions, capacity/occupancy boundaries,
cross-entity dependencies, and the fiscal authorization requirement.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    ADMIN,
    INTAKE,
    fixtures as fx,
)


def test_admit_waitlisted_fails_state_before_fiscal(api):
    """PRD §3.4: "Its preconditions are evaluated in this order. First, the
    admission must be `PENDING_ADMISSION`, else `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_admit
    """
    # WAITLISTED admission, never promoted, no authorization.
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"])
    admission = fx.create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"]
    )
    resp = api.admit_admission(admission["id"], INTAKE)
    # Both the state precondition (priority 6) and the fiscal precondition
    # (priority 16) would fail; the state check fires first.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_admit_full_program_fails_capacity_before_fiscal(api):
    """PRD §3.4: "Then the program must have room — its occupancy posture must be
    `OPEN`, meaning the occupied bed count is strictly below the bed capacity —
    else `ERR_PROGRAM_AT_CAPACITY`. ... Finally, the admission must be financially
    covered: an insurance authorization for this admission must exist in
    `APPROVED` status with at least one day remaining, else
    `ERR_NO_ACTIVE_AUTHORIZATION`".

    Design: Difficulty/priority_pair_validation_conflict/capacity_before_fiscal_on_admit
    """
    # Capacity-1 program filled by admission X; second admission Y promoted with
    # NO authorization. Capacity (priority 10) fires before fiscal (priority 16).
    ctx = fx.setup_admitted_admission(bed_capacity=1)
    facility = ctx["facility"]
    program = ctx["program"]
    cohort = ctx["cohort"]
    assert program["occupancy_posture"] == "FULL"
    patient_y = fx.create_patient(facility["id"], full_name="Pat Y")
    admission_y = fx.create_admission(
        patient_y["id"], facility["id"], program["id"], cohort["id"]
    )
    validate_success(api.promote_admission(admission_y["id"], INTAKE))
    resp = api.admit_admission(admission_y["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_AT_CAPACITY.value)


def test_admit_waitlisted_stays_waitlisted_after_state_rejection(api):
    """PRD §3.4: "First, the admission must be `PENDING_ADMISSION`, else
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_admit
    """
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"])
    admission = fx.create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"]
    )
    resp = api.admit_admission(admission["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    data = validate_success(api.get_admission(admission["id"], INTAKE))
    assert data["clinical_status"] == "WAITLISTED", (
        f"admission must remain WAITLISTED, got {data['clinical_status']}"
    )


def test_admit_full_program_leaves_program_at_capacity(api):
    """PRD §3.4: "the program must have room — its occupancy posture must be
    `OPEN`, meaning the occupied bed count is strictly below the bed capacity —
    else `ERR_PROGRAM_AT_CAPACITY`."

    Design: Difficulty/priority_pair_validation_conflict/capacity_before_fiscal_on_admit
    """
    ctx = fx.setup_admitted_admission(bed_capacity=1)
    facility = ctx["facility"]
    program = ctx["program"]
    cohort = ctx["cohort"]
    patient_y = fx.create_patient(facility["id"], full_name="Pat Y")
    admission_y = fx.create_admission(
        patient_y["id"], facility["id"], program["id"], cohort["id"]
    )
    validate_success(api.promote_admission(admission_y["id"], INTAKE))
    resp = api.admit_admission(admission_y["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_AT_CAPACITY.value)
    # The blocked admission never seated; program stays at one occupied bed, FULL.
    program_after = validate_success(api.get_program(program["id"], ADMIN))
    assert program_after["beds_occupied"] == 1, (
        f"expected 1 occupied, got {program_after['beds_occupied']}"
    )
    assert program_after["occupancy_posture"] == "FULL"


def test_occupancy_open_one_below_capacity_admits(api):
    """PRD §2.8: "the posture is `FULL` when the occupied count is greater than or
    equal to the bed capacity, and `OPEN` otherwise."

    Design: Difficulty/boundary_precision_check/occupancy_full_at_exact_capacity_boundary
    """
    # Capacity 2: after one admit beds_occupied==1 < 2 -> still OPEN (X-1 side).
    ctx = fx.setup_admitted_admission(bed_capacity=2)
    program = validate_success(api.get_program(ctx["program"]["id"], ADMIN))
    assert program["beds_occupied"] == 1
    assert program["occupancy_posture"] == "OPEN", (
        f"expected OPEN one below capacity, got {program['occupancy_posture']}"
    )
    assert program["beds_available"] == 1, (
        f"expected 1 available, got {program['beds_available']}"
    )


def test_occupancy_full_at_exact_capacity_boundary(api):
    """PRD §2.8: "the posture is `FULL` when the occupied count is greater than or
    equal to the bed capacity, and `OPEN` otherwise."
    PRD §3.4: "the program must have room — its occupancy posture must be `OPEN`,
    meaning the occupied bed count is strictly below the bed capacity — else
    `ERR_PROGRAM_AT_CAPACITY`."

    Design: Difficulty/boundary_precision_check/occupancy_full_at_exact_capacity_boundary
    """
    # Capacity 1: after one admit beds_occupied==1==capacity -> FULL at boundary.
    ctx = fx.setup_admitted_admission(bed_capacity=1)
    program = validate_success(api.get_program(ctx["program"]["id"], ADMIN))
    assert program["beds_occupied"] == 1, (
        f"expected 1 occupied, got {program['beds_occupied']}"
    )
    assert program["occupancy_posture"] == "FULL", (
        f"expected FULL at boundary, got {program['occupancy_posture']}"
    )
    # A second PENDING_ADMISSION (with its own APPROVED auth) is rejected.
    second = fx.setup_pending_admission(
        bed_capacity=1, with_authorization=True
    )
    # second built its own program; build the second admission in the FULL program.
    facility = ctx["facility"]
    patient_y = fx.create_patient(facility["id"], full_name="Pat Y")
    fx.create_finalized_assessment(patient_y, facility["id"])
    patient_y = validate_success(api.get_patient(patient_y["id"], INTAKE))
    admission_y = fx.create_admission(
        patient_y["id"], facility["id"], ctx["program"]["id"], ctx["cohort"]["id"]
    )
    fx.create_approved_authorization(
        admission_y["id"], facility["id"], window_end_iso="2026-01-08T00:00:00Z"
    )
    validate_success(api.promote_admission(admission_y["id"], INTAKE))
    resp = api.admit_admission(admission_y["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_AT_CAPACITY.value)


def test_admit_blocked_by_closed_program(api):
    """PRD §3.4: "Then the program must be `OPEN`, else `ERR_PROGRAM_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/admit_blocked_by_closed_program
    """
    ctx = fx.setup_pending_admission(with_authorization=True)
    program = ctx["program"]
    admission = ctx["admission"]
    validate_success(api.close_program(program["id"], ADMIN))
    resp = api.admit_admission(admission["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED.value)
    data = validate_success(api.get_admission(admission["id"], INTAKE))
    assert data["clinical_status"] == "PENDING_ADMISSION", (
        f"admission must stay PENDING_ADMISSION, got {data['clinical_status']}"
    )


def test_admit_blocked_by_closed_program_status_is_closed(api):
    """PRD §2.8: "a `CLOSED` program rejects new promotions and admissions."
    PRD §3.4: "Then the program must be `OPEN`, else `ERR_PROGRAM_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/admit_blocked_by_closed_program
    """
    ctx = fx.setup_pending_admission(with_authorization=True)
    program = ctx["program"]
    admission = ctx["admission"]
    closed = validate_success(api.close_program(program["id"], ADMIN))
    assert closed["status"] == "CLOSED", f"expected CLOSED, got {closed['status']}"
    resp = api.admit_admission(admission["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED.value)


def test_admit_unstable_patient_into_php_blocked(api):
    """PRD §3.4: "Then the patient's `medical_stability_posture` must be admissible
    for the program's level of care: an `UNSTABLE` patient may be admitted only
    into a `RESIDENTIAL` program, and an attempt to admit an unstable patient into
    any other level is rejected with `ERR_LOC_NOT_ADMISSIBLE`."

    Design: Corner/validations/admit_unstable_patient_into_php_blocked
    """
    # composite from (8,7,6,4): 0.40*80 + 0.30*70 + 0.20*60 - 0.10*40 = 61.0;
    # bmi 15 (<16) -> +15 bonus -> provisional 76 -> UNSTABLE (>=75).
    ctx = fx.setup_pending_admission(
        level_of_care="PHP", patient_age_band="ADULT", bmi=15.0,
        med=8, beh=7, psy=6, mot=4, with_authorization=True,
    )
    patient = validate_success(api.get_patient(ctx["patient"]["id"], INTAKE))
    assert patient["medical_stability_posture"] == "UNSTABLE", (
        f"expected UNSTABLE, got {patient['medical_stability_posture']}"
    )
    resp = api.admit_admission(ctx["admission"]["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_LOC_NOT_ADMISSIBLE.value)


def test_admit_cohort_age_band_mismatch_blocked(api):
    """PRD §3.4: "Then the cohort's `age_band` must equal the patient's
    `age_band`, else `ERR_COHORT_AGE_MISMATCH`."

    Design: Corner/validations/admit_cohort_age_band_mismatch_blocked
    """
    # ADOLESCENT cohort, ADULT patient.
    ctx = fx.setup_pending_admission(
        cohort_age_band="ADOLESCENT", patient_age_band="ADULT",
        with_authorization=True,
    )
    resp = api.admit_admission(ctx["admission"]["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_COHORT_AGE_MISMATCH.value)


def test_admit_no_authorization_returns_fiscal_error(api):
    """PRD §3.4: "Finally, the admission must be financially covered: an insurance
    authorization for this admission must exist in `APPROVED` status with at least
    one day remaining, else `ERR_NO_ACTIVE_AUTHORIZATION` (HTTP 402)."

    Design: Corner/validations/admit_no_authorization_returns_fiscal_error
    """
    ctx = fx.setup_pending_admission(with_authorization=False)
    resp = api.admit_admission(ctx["admission"]["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AUTHORIZATION.value)


def test_admit_success_seats_bed_and_cohort(api):
    """PRD §3.4: "increments the program's `beds_occupied` by one and recomputes
    the program's `beds_available` and `occupancy_posture`, and increments the
    cohort's `slots_filled` by one."

    Design: Difficulty/compensating_invariant/bed_conservation_admit_then_discharge
    """
    ctx = fx.setup_admitted_admission(bed_capacity=5)
    program = validate_success(api.get_program(ctx["program"]["id"], ADMIN))
    assert program["beds_occupied"] == 1, (
        f"expected 1 occupied, got {program['beds_occupied']}"
    )
    assert program["beds_available"] == 4, (
        f"expected 4 available, got {program['beds_available']}"
    )
    cohort = validate_success(api.get_cohort(ctx["cohort"]["id"], ADMIN))
    assert cohort["slots_filled"] == 1, (
        f"expected 1 slot filled, got {cohort['slots_filled']}"
    )

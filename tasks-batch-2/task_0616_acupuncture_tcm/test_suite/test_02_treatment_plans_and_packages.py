"""Treatment-plan lifecycle (revision loop) and package-series accounting basics.

Covers the cyclic state-machine difficulty instance plus corner instances for plan
state errors and package preconditions / computed fields.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_practitioner_headers,
    assert_package_series, assert_package_balance_identity,
    create_treatment_plan_payload, create_package_series_payload,
    create_practitioner, create_patient, create_room, setup_finalized_intake,
    setup_active_plan, setup_clinic_scenario, setup_package_scenario,
    create_package, book_package_appointment, check_in_and_complete, get_plan_version,
)
from test_helpers import api_client

ADMIN = TEST_USERS["clinic_admin_headers"]


# ─── Cyclic state machine (queue A) ────────────────────────────────────────
def test_plan_hold_then_resume_returns_to_active(api):
    """PRD 3.3: "From ACTIVE a practitioner may place the plan ON_HOLD; this is
    permitted only when the plan's status is ACTIVE, and otherwise rejected with
    ERR_PLAN_NOT_ACTIVE, and it increments the plan's version."
    PRD 3.3: "From ON_HOLD the practitioner may resume the plan back to ACTIVE;
    this is permitted only when the plan's status is ON_HOLD, otherwise rejected
    with ERR_PLAN_NOT_ON_HOLD, and it increments the plan's version."

    Design: Difficulty/non_linear_state_machine/treatment_plan_cyclic_hold_resume
    """
    prac = create_practitioner()
    patient = create_patient(full_name="Cyc Pat")
    intake = setup_finalized_intake(patient["id"], prac["id"],
                                    tongue_finding="PALE", tongue_coating="NONE",
                                    pulse_finding="DEEP", tcm_pattern="YIN_DEFICIENCY")
    plan = setup_active_plan(patient["id"], prac["id"], intake["id"],
                             acupoints=["KI3"], planned_sessions=6)
    ph = make_practitioner_headers(prac["id"])

    held = validate_success(api.hold_plan(plan["id"], ph), 200)
    assert held["status"] == "ON_HOLD"

    resumed = validate_success(api.resume_plan(plan["id"], ph), 200)
    assert resumed["status"] == "ACTIVE", "plan returned to a prior state (cycle)"


def test_plan_cycle_increments_version_each_transition(api):
    """PRD 3.3: "this is permitted only when the plan's status is ACTIVE, and
    otherwise rejected with ERR_PLAN_NOT_ACTIVE, and it increments the plan's version."

    Design: Difficulty/non_linear_state_machine/treatment_plan_cyclic_hold_resume
    """
    ctx = setup_clinic_scenario()
    plan = ctx["plan"]
    ph = make_practitioner_headers(ctx["practitioner"]["id"])
    held = validate_success(api.hold_plan(plan["id"], ph), 200)
    assert held["version"] == plan["version"] + 1
    resumed = validate_success(api.resume_plan(plan["id"], ph), 200)
    assert resumed["version"] == held["version"] + 1


# ─── Plan state-error corner instances ─────────────────────────────────────
def test_resume_active_plan_rejected(api):
    """PRD 3.3: "From ON_HOLD the practitioner may resume the plan back to ACTIVE;
    this is permitted only when the plan's status is ON_HOLD, otherwise rejected
    with ERR_PLAN_NOT_ON_HOLD, and it increments the plan's version."

    Design: Corner/state_machines/resume_active_plan_rejected
    """
    ctx = setup_clinic_scenario()
    ph = make_practitioner_headers(ctx["practitioner"]["id"])
    validate_error(api.resume_plan(ctx["plan"]["id"], ph),
                   ApiErrorId.ERR_PLAN_NOT_ON_HOLD.value)


def test_complete_plan_with_open_appointment_rejected(api):
    """PRD 3.3: "completion is permitted only when the plan is ACTIVE (otherwise
    ERR_PLAN_NOT_ACTIVE) and only when no appointment of this plan is currently in
    clinical status SCHEDULED or CHECKED_IN (otherwise ERR_PLAN_HAS_OPEN_APPOINTMENTS);
    completion increments the plan's version."

    Design: Corner/state_machines/complete_plan_with_open_appointment_rejected
    """
    ctx = setup_clinic_scenario()
    plan = ctx["plan"]
    plv = get_plan_version(plan["id"])
    appt_payload = create_treatment_plan_payload  # noqa: F841 (only for naming clarity)
    # Book a SCHEDULED appointment under the plan.
    from test_helpers import create_appointment_payload
    get_success_data(api.create_appointment(
        create_appointment_payload(ctx["patient"]["id"], plan["id"],
                                   ctx["practitioner"]["id"], ctx["room"]["id"], plv,
                                   scheduled_start="2026-06-16T10:00:00Z",
                                   scheduled_end="2026-06-16T10:45:00Z"), ADMIN))
    ph = make_practitioner_headers(ctx["practitioner"]["id"])
    validate_error(api.complete_plan(plan["id"], ph),
                   ApiErrorId.ERR_PLAN_HAS_OPEN_APPOINTMENTS.value)


def test_create_plan_from_draft_intake_rejected(api):
    """PRD 3.3: "A plan may only be created from an intake whose status is FINALIZED
    and which belongs to the same patient; a violation is rejected with
    ERR_INTAKE_NOT_FINALIZED."

    Design: Corner/validations/plan_create_from_draft_intake_rejected
    """
    prac = create_practitioner()
    patient = create_patient(full_name="V1 Pat")
    from test_helpers import create_intake_payload
    intake = get_success_data(api.create_intake(
        create_intake_payload(patient["id"]), make_practitioner_headers(prac["id"])))
    payload = create_treatment_plan_payload(patient["id"], prac["id"], intake["id"])
    validate_error(api.create_treatment_plan(payload, make_practitioner_headers(prac["id"])),
                   ApiErrorId.ERR_INTAKE_NOT_FINALIZED.value)


def test_create_plan_wrong_patient_fk_not_found(api):
    """PRD 2.8: "After path existence, foreign keys supplied in the request body are
    checked for existence (for booking, plan creation, and dispense creation), again
    drawing from the not-found vocabulary just listed (ERR_PRACTITIONER_NOT_FOUND,
    ERR_ROOM_NOT_FOUND, ERR_PLAN_NOT_FOUND, ERR_PACKAGE_NOT_FOUND, ERR_INTAKE_NOT_FOUND,
    ERR_FORMULA_NOT_FOUND)."

    Design: Corner/entities/create_plan_wrong_patient_parent_not_found
    """
    prac = create_practitioner()
    real_patient = create_patient(full_name="Real Pat")
    intake = setup_finalized_intake(real_patient["id"], prac["id"])
    payload = create_treatment_plan_payload(
        "00000000-0000-4000-8000-000000000999", prac["id"], intake["id"])
    validate_error(api.create_treatment_plan(payload, make_practitioner_headers(prac["id"])),
                   ApiErrorId.ERR_PATIENT_NOT_FOUND.value)


# ─── Package-series corner instances ───────────────────────────────────────
def test_package_computed_fields_initialized(api):
    """PRD 3.4: "At purchase the series is ACTIVE with reserved_credits of 0,
    consumed_credits of 0, and both balances equal to total_credits."

    Design: Corner/entities/package_computed_fields_initialized
    """
    patient = create_patient(full_name="Pkg Init")
    data = validate_success(api.create_package_series(
        create_package_series_payload(patient["id"], total_credits=8, price_paid_cents=72000),
        ADMIN), 201)
    assert_package_series(data)
    assert data["reserved_credits"] == 0
    assert data["consumed_credits"] == 0
    assert data["provisional_remaining_credits"] == 8
    assert data["finalized_remaining_credits"] == 8
    assert data["status"] == "ACTIVE"
    assert_package_balance_identity(data)


def test_package_cancel_with_consumed_credits_rejected(api):
    """PRD 3.4: "cancellation requires consumed_credits to be 0 (otherwise
    ERR_PACKAGE_HAS_CONSUMED_CREDITS) and reserved_credits to be 0 (otherwise
    ERR_PACKAGE_HAS_RESERVED_CREDITS)."

    Design: Corner/state_machines/package_cancel_with_consumed_credits_rejected
    """
    ctx = setup_package_scenario(total_credits=3, price_paid_cents=27000)
    appt = book_package_appointment(ctx, ctx["package"]["id"],
                                    scheduled_start="2026-06-19T09:00:00Z",
                                    scheduled_end="2026-06-19T09:45:00Z")
    check_in_and_complete(ctx, appt["id"], clock_iso="2026-06-19T09:00:00Z")
    validate_error(api.cancel_package_series(ctx["package"]["id"], ADMIN),
                   ApiErrorId.ERR_PACKAGE_HAS_CONSUMED_CREDITS.value)

"""Ancillary charge, lifetime attendance, lock-in penalty boundary, reconciliation.

Corner queue B: section calculations.
"""
from test_helpers import (
    api_client, get_success_data, validate_success,
    create_program, set_clock, create_participant, create_certified_loc,
    create_active_care_plan, setup_enrolled_participant,
    create_attendance_day, complete_day, create_draft_capitation,
    finalize_capitation, get_participant_version,
    submit_disenrollment, approve_disenrollment, finalize_disenrollment,
    TEST_USERS,
)

PA = TEST_USERS["program_admin_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
MD = TEST_USERS["medical_director_headers"]
NS = TEST_USERS["nurse_staff_headers"]
BS = TEST_USERS["billing_specialist_headers"]


# ===========================================================================
# calculations / ancillary_meal_charge_flat_activity_bonus
# ===========================================================================
def test_ancillary_meal_charge_flat_activity_bonus():
    """PRD 3.7: "Each included day contributes a meal charge equal to its meals_provided
    multiplied by 850 cents, plus a flat activity bonus of 200 cents when that day's
    activities_count is greater than zero (and no bonus when it is zero). The activity
    bonus is a single flat amount per qualifying day - it is not multiplied by the number
    of activities."

    Day1 meals 2 + activities 3 => 2*850+200=1900; day2 meals 1 + activities 0 => 850;
    month total 2750, completed_days 2.

    Design: Corner/calculations/ancillary_meal_charge_flat_activity_bonus
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-10T08:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")

    d1 = create_attendance_day(participant["id"], "2026-06-03", meals_provided=2, activities_count=3)
    get_success_data(api_client.check_in_attendance_day(d1["id"], NS))
    complete_day(d1["id"])
    d2 = create_attendance_day(participant["id"], "2026-06-04", meals_provided=1, activities_count=0)
    get_success_data(api_client.check_in_attendance_day(d2["id"], NS))
    complete_day(d2["id"])

    resp = api_client.get_attendance_summary(
        participant["id"], BS, params={"service_month": "2026-06-01"})
    data = validate_success(resp)
    assert data["completed_days"] == 2
    assert data["month_ancillary_cents"] == 2750


# ===========================================================================
# calculations / lifetime_attendance_days_increments_on_complete
# ===========================================================================
def test_lifetime_attendance_days_increments_on_complete():
    """PRD 3.5: "A CHECKED_IN day is closed out by NurseStaff completing it, moving it to
    COMPLETED and incrementing the participant's lifetime_attendance_days by 1."
    PRD 2.6: "The lifetime_attendance_days field equals the count of the participant's
    AttendanceDay rows in COMPLETED status."

    Design: Corner/calculations/lifetime_attendance_days_increments_on_complete
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-02T08:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    day = create_attendance_day(participant["id"], "2026-06-02")
    get_success_data(api_client.check_in_attendance_day(day["id"], NS))
    complete_day(day["id"])

    refreshed = get_success_data(api_client.get_participant(participant["id"], NS))
    assert refreshed["lifetime_attendance_days"] == 1


# ===========================================================================
# calculations / lock_in_penalty_no_penalty_on_boundary
# ===========================================================================
def test_lock_in_penalty_zero_on_boundary():
    """PRD 3.8: "If the finalize date is on or after the lock_in_end_date, the penalty is
    0 - landing exactly on the end date incurs no penalty."

    Enroll 2026-02-01, lock_in_days 28 => lock_in_end_date 2026-03-01; voluntary disenroll
    requested effective 2026-03-01 (ON the end date) => lock_in_penalty_cents 0.

    Design: Corner/calculations/lock_in_penalty_no_penalty_on_boundary
    """
    program = create_program(lock_in_days=28)
    set_clock("2026-02-01T12:00:00Z")
    participant = create_participant(program["id"])
    create_certified_loc(participant["id"], assessed_on="2026-01-15")
    create_active_care_plan(participant["id"])
    get_success_data(api_client.enroll_participant(
        participant["id"], {"enrollment_effective_date": "2026-02-01"}, IC))

    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="MOVED",
                               requested_effective_date="2026-03-01")
    approve_disenrollment(req["id"])
    finalize_disenrollment(req["id"], participant["id"])

    refreshed = get_success_data(api_client.get_disenrollment_request(req["id"], BS))
    assert refreshed["lock_in_penalty_cents"] == 0


# ===========================================================================
# calculations / lock_in_penalty_inside_window
# ===========================================================================
def test_lock_in_penalty_inside_window():
    """PRD 3.8: "the penalty is one Medicare member-month prorated by the unserved
    fraction of the window: the number of whole calendar days remaining (the
    lock_in_end_date minus the finalize date) is multiplied by the program's
    medicare_monthly_rate_cents, divided by the program's lock_in_days, and rounded
    half-up to whole cents, yielding lock_in_penalty_cents."

    Enroll 2026-02-01, lock_in_days 60 => end 2026-04-02; requested 2026-03-01 =>
    remaining_days 32; round(280000*32/60)=149333.33->149333.

    Design: Corner/calculations/lock_in_penalty_inside_window
    """
    program = create_program(lock_in_days=60)
    set_clock("2026-02-01T12:00:00Z")
    participant = create_participant(program["id"])
    create_certified_loc(participant["id"], assessed_on="2026-01-15")
    create_active_care_plan(participant["id"])
    get_success_data(api_client.enroll_participant(
        participant["id"], {"enrollment_effective_date": "2026-02-01"}, IC))

    req = submit_disenrollment(participant["id"], kind="VOLUNTARY", reason_code="MOVED",
                               requested_effective_date="2026-03-01")
    approve_disenrollment(req["id"])
    finalize_disenrollment(req["id"], participant["id"])

    refreshed = get_success_data(api_client.get_disenrollment_request(req["id"], BS))
    assert refreshed["lock_in_penalty_cents"] == 149333


# ===========================================================================
# calculations / reconcile_recoup_reduces_reconciled
# ===========================================================================
def test_reconcile_recoup_reduces_reconciled():
    """PRD 3.7: "On reconcile the reconciled_cents is set to total_billed_cents minus
    recoup_cents, the payment moves to RECONCILED, and that reconciled_cents is added to
    the participant's ledger_reconciled_cents."

    A FINALIZED FULL_MONTH dual payment (total 630000) reconciled with recoup_cents 30000
    sets reconciled_cents 600000 and ledger_reconciled_cents 600000.

    Design: Corner/calculations/reconcile_recoup_reduces_reconciled
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, dual_eligible=True,
                                                   effective_date="2026-06-01")
    payment = create_draft_capitation(participant["id"], "2026-06-01", "FULL_MONTH")
    payment = finalize_capitation(payment["id"], participant["id"])

    reconciled = get_success_data(api_client.reconcile_capitation_payment(
        payment["id"], {"recoup_cents": 30000}, BS))
    assert reconciled["reconciled_cents"] == 600000
    assert reconciled["status"] == "RECONCILED"
    assert get_success_data(api_client.get_participant(participant["id"], BS))["ledger_reconciled_cents"] == 600000

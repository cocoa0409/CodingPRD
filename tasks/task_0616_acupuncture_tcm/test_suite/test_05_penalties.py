"""No-show and late-cancellation penalty calculation.

Covers the combinatorial three-input penalty difficulty instance plus corner
instances for the late-cancel penalty within cutoff and the active-member
first-strike waiver.
"""
from test_helpers import (
    validate_success, get_success_data, validate_paginated,
    TEST_USERS,
    setup_clinic_scenario, book_appointment, accumulate_no_show_strikes,
)
from test_helpers import api_client

ADMIN = TEST_USERS["clinic_admin_headers"]


def _charges_for(api, appt_id):
    data, _ = validate_paginated(api.list_charges(ADMIN, params={"appointment_id": appt_id}))
    return data


# ─── Three-input nonlinear penalty (queue A) ───────────────────────────────
def test_no_show_penalty_three_input_nonlinear(api):
    """PRD 3.7: "the tier base is 5000 cents for a no-show and 2500 cents for a late
    cancellation; a strike multiplier is formed as 1 plus the strike step of 0.5 times
    the prior strike count capped at 3 (so the prior strike count contributes through
    its value, but never more than 3, before being scaled); and the penalty is the tier
    base multiplied by that multiplier, rounded half up to whole cents."
    PRD 3.7: "A penalty greater than zero produces a PENALTY Charge and drives billing
    status to PENALTY_DUE; a penalty of zero drives billing status to WAIVED."

    Design: Difficulty/combinatorial_formula/no_show_penalty_three_input_nonlinear
    """
    ctx = setup_clinic_scenario()  # non-member, strike_count 0
    # Raise strike_count to 2 with two disposable no-shows.
    accumulate_no_show_strikes(ctx, 2, base_fee_cents=12000, start_hour=9, day="2026-06-03")
    patient_before = get_success_data(api.get_patient(ctx["patient"]["id"], ADMIN))
    assert patient_before["strike_count"] == 2

    # Third no-show: prior_strikes = 2 → multiplier 1 + 2*0.5 = 2.0 → 5000*2 = 10000.
    third = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                             scheduled_start="2026-06-03T11:00:00Z",
                             scheduled_end="2026-06-03T11:45:00Z")
    result = validate_success(api.no_show(third["id"], ADMIN), 200)
    assert result["clinical_status"] == "NO_SHOW"
    assert result["billing_status"] == "PENALTY_DUE"

    penalties = [c for c in _charges_for(api, third["id"]) if c["charge_type"] == "PENALTY"]
    assert len(penalties) == 1
    assert penalties[0]["total_due_cents"] == 10000

    patient_after = get_success_data(api.get_patient(ctx["patient"]["id"], ADMIN))
    assert patient_after["strike_count"] == 3


def test_no_show_records_producing_strike(api):
    """PRD 3.5: "It moves the clinical status from SCHEDULED to NO_SHOW, records this
    appointment as the producing strike by increasing the patient's strike_count by one
    and incrementing the patient's version, voids every ATTACHED add-on for the
    appointment (moving each to VOIDED), and increments the appointment's version."

    Design: Difficulty/combinatorial_formula/no_show_penalty_three_input_nonlinear
    """
    ctx = setup_clinic_scenario()
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-03T15:00:00Z",
                            scheduled_end="2026-06-03T15:45:00Z")
    before = get_success_data(api.get_patient(ctx["patient"]["id"], ADMIN))
    validate_success(api.no_show(appt["id"], ADMIN), 200)
    after = get_success_data(api.get_patient(ctx["patient"]["id"], ADMIN))
    assert after["strike_count"] == before["strike_count"] + 1


# ─── Late-cancel within cutoff (corner) ────────────────────────────────────
def test_late_cancel_within_cutoff_strike_and_penalty(api):
    """PRD 3.5: "Separately, if the cancellation occurs within the late-cancellation
    cutoff window measured back from scheduled_start, the patient's strike_count is
    increased by one and the late-cancel variant of the penalty calculation may create
    a PENALTY Charge; a cancellation outside that window incurs no strike."
    PRD 3.7: "the tier base is 5000 cents for a no-show and 2500 cents for a late
    cancellation; a strike multiplier is formed as 1 plus the strike step of 0.5 times
    the prior strike count capped at 3 (so the prior strike count contributes through its
    value, but never more than 3, before being scaled); and the penalty is the tier base
    multiplied by that multiplier, rounded half up to whole cents."

    Design: Corner/calculations/late_cancel_within_cutoff_strike_and_penalty
    """
    ctx = setup_clinic_scenario()  # non-member, prior strikes 0
    # Clock at 2026-06-22T00:00:00Z, appointment start 10:00 same day (10h lead).
    get_success_data(api.set_clock("2026-06-22T00:00:00Z", ADMIN))
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-22T10:00:00Z",
                            scheduled_end="2026-06-22T10:45:00Z")
    result = validate_success(api.cancel_appointment(appt["id"], ADMIN), 200)
    assert result["clinical_status"] == "CANCELLED"

    patient = get_success_data(api.get_patient(ctx["patient"]["id"], ADMIN))
    assert patient["strike_count"] == 1

    penalties = [c for c in _charges_for(api, appt["id"]) if c["charge_type"] == "PENALTY"]
    assert len(penalties) == 1
    assert penalties[0]["total_due_cents"] == 2500


# ─── Active-member first-strike waiver (corner) ────────────────────────────
def test_member_first_no_show_penalty_waived(api):
    """PRD 3.7: "When the patient's membership_status is ACTIVE and the prior strike
    count is exactly 0, the penalty is 0 cents — the first-strike waiver for active
    members."
    PRD 3.7: "A penalty greater than zero produces a PENALTY Charge and drives billing
    status to PENALTY_DUE; a penalty of zero drives billing status to WAIVED."

    Design: Corner/calculations/member_first_no_show_penalty_waived_zero
    """
    ctx = setup_clinic_scenario()
    get_success_data(api.set_membership(ctx["patient"]["id"], {"membership_status": "ACTIVE"}, ADMIN))
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-23T10:00:00Z",
                            scheduled_end="2026-06-23T10:45:00Z")
    result = validate_success(api.no_show(appt["id"], ADMIN), 200)
    assert result["clinical_status"] == "NO_SHOW"
    assert result["billing_status"] == "WAIVED"

    penalties = [c for c in _charges_for(api, appt["id"]) if c["charge_type"] == "PENALTY"]
    assert penalties == [], "active member first strike must not create a PENALTY Charge"
    patient = get_success_data(api.get_patient(ctx["patient"]["id"], ADMIN))
    assert patient["strike_count"] == 1

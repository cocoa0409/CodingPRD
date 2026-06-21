"""Combinatorial-formula difficulty tests.

Queue A / combinatorial_formula:
  - screening_outcome_ordered_multibranch_first_failure
  - plasma_annual_cap_round_per_collection_then_sum
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    create_health_screening_payload, create_donation_payload,
    create_center, create_donor, create_slot, book_appointment,
    advance_clock_payload,
    setup_checked_in_appointment,
    record_prior_plasma_collection,
    TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]
NURSE = TEST_USERS["intake_nurse_headers"]


def _collect_plasma_at(center, donor, clock, win_start, win_end, volume_ml=None):
    """Advance clock to `clock`, create a PLASMA slot, book + check-in + PASS screen for
    an existing donor. If volume_ml is given, also record the collection and return the
    donation; otherwise return the CHECKED_IN appointment ready for the trigger POST."""
    get_success_data(api_client.advance_clock(center["id"], advance_clock_payload(clock), ADMIN))
    slot = create_slot(center["id"], donation_type="PLASMA",
                       starts_at=win_start, ends_at=win_end, capacity=9)
    appt = book_appointment(donor["id"], slot)
    appt = get_success_data(api_client.check_in_appointment(appt["id"], NURSE))
    get_success_data(api_client.create_health_screening(
        create_health_screening_payload(appt["id"], hemoglobin_g_dl=13.5, weight_kg=donor["weight_kg"]), NURSE))
    if volume_ml is not None:
        return get_success_data(
            api_client.create_donation(appt["id"], create_donation_payload(volume_ml=volume_ml), NURSE))
    return appt


def _donor_with_two_prior_666ml_plasma():
    """A 60 kg plasma donor with two prior 666 mL collections (2025-01-01, 2025-02-01),
    clock left at 2025-02-01. Returns (center, donor)."""
    center = create_center(clock="2025-01-01T00:00:00.000Z", name="Plasma Center", region_code="US-TX")
    donor = create_donor(center["id"], full_name="Paula Plasma", date_of_birth="1990-02-02",
                         weight_kg=60, blood_type="A_NEG")
    # First collection at 2025-01-01 (clock already there).
    slot1 = create_slot(center["id"], donation_type="PLASMA",
                        starts_at="2025-01-01T08:00:00.000Z", ends_at="2025-01-01T18:00:00.000Z", capacity=9)
    a1 = book_appointment(donor["id"], slot1)
    a1 = get_success_data(api_client.check_in_appointment(a1["id"], NURSE))
    get_success_data(api_client.create_health_screening(
        create_health_screening_payload(a1["id"], hemoglobin_g_dl=13.5, weight_kg=60), NURSE))
    get_success_data(api_client.create_donation(a1["id"], create_donation_payload(volume_ml=666), NURSE))
    # Second collection at 2025-02-01.
    record_prior_plasma_collection(
        center, donor, clock="2025-02-01T00:00:00.000Z",
        slot_window_start="2025-02-01T08:00:00.000Z", slot_window_end="2025-02-01T18:00:00.000Z",
        volume_ml=666)
    return center, donor


# ─── screening_outcome_ordered_multibranch_first_failure ──────────────────────
def test_screening_reports_first_failing_check_hemoglobin_over_vitals(api):
    """PRD §3.4: "The screening evaluates five checks in this fixed order, and the
    first check that fails sets both outcome to FAIL and the failure_reason; only if all
    five pass is the outcome PASS. First, hemoglobin: it passes only when hemoglobin_g_dl
    is at least 12.5 g/dL (compared at one decimal place, so exactly 12.5 passes); below
    that, the reason is HEMOGLOBIN_LOW."

    A screening failing both hemoglobin (12.4) and vitals (systolic 200) reports
    HEMOGLOBIN_LOW because hemoglobin is checked first.

    Design: Difficulty/combinatorial_formula/screening_outcome_ordered_multibranch_first_failure
    """
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE",
        donor_overrides={"weight_kg": 65, "blood_type": "B_POS"},
    )
    res = api.create_health_screening(
        create_health_screening_payload(
            appt["id"], hemoglobin_g_dl=12.4, systolic_bp=200, pulse_bpm=70, weight_kg=65,
            recent_travel_risk=False, disqualifying_medication=False,
        ),
        NURSE,
    )
    screening = validate_success(res, 201)
    assert screening["outcome"] == "FAIL"
    assert screening["failure_reason"] == "HEMOGLOBIN_LOW", (
        "hemoglobin (check 1) must win over the later VITALS_OUT_OF_RANGE (check 3)")


def test_screening_reports_vitals_when_only_vitals_fail(api):
    """PRD §3.4: "Third, vitals: systolic_bp must lie between 90 and 180 inclusive and
    pulse_bpm must lie between 50 and 100 inclusive — if either falls outside its range,
    the reason is VITALS_OUT_OF_RANGE."

    With hemoglobin and weight passing, an out-of-range systolic surfaces
    VITALS_OUT_OF_RANGE — confirming the ordered formula reaches check 3 only when the
    earlier checks pass.

    Design: Difficulty/combinatorial_formula/screening_outcome_ordered_multibranch_first_failure
    """
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE",
        donor_overrides={"weight_kg": 65, "blood_type": "B_POS"},
    )
    res = api.create_health_screening(
        create_health_screening_payload(
            appt["id"], hemoglobin_g_dl=14.0, systolic_bp=200, pulse_bpm=70, weight_kg=65,
            recent_travel_risk=False, disqualifying_medication=False,
        ),
        NURSE,
    )
    screening = validate_success(res, 201)
    assert screening["outcome"] == "FAIL"
    assert screening["failure_reason"] == "VITALS_OUT_OF_RANGE", (
        "hemoglobin and weight pass, so the vitals check (3) is the first failure")


# ─── plasma_annual_cap_round_per_collection_then_sum ──────────────────────────
def test_plasma_annual_cap_round_then_sum_rejects_third_666ml(api):
    """PRD §3.5: "If that annual total is greater than 2.00 liters the collection is
    rejected with ERR_ANNUAL_PLASMA_CAP_EXCEEDED (HTTP 422); a total of exactly 2.00
    liters is allowed, and 2.01 is rejected. The round-then-sum order is mandatory:
    three collections of 666 mL each round to 0.67 L per line and sum to 2.01 L
    (rejected), whereas summing first would give 1.998 L rounding to 2.00 L — the
    per-line rounding is authoritative, so such a case rejects."

    Two prior 666 mL plasma collections (0.67 + 0.67 = 1.34 L) then a third 666 mL:
    round-then-sum = 2.01 L > 2.00 cap -> rejected.

    Design: Difficulty/combinatorial_formula/plasma_annual_cap_round_per_collection_then_sum
    """
    center, donor = _donor_with_two_prior_666ml_plasma()
    appt3 = _collect_plasma_at(
        center, donor, "2025-03-01T00:00:00.000Z",
        "2025-03-01T08:00:00.000Z", "2025-03-01T18:00:00.000Z")
    res = api.create_donation(appt3["id"], create_donation_payload(volume_ml=666), NURSE)
    validate_error(res, "ERR_ANNUAL_PLASMA_CAP_EXCEEDED", expected_status=422)


def test_plasma_annual_cap_allows_total_at_exactly_two_liters(api):
    """PRD §3.5: "If that annual total is greater than 2.00 liters the collection is
    rejected with ERR_ANNUAL_PLASMA_CAP_EXCEEDED (HTTP 422); a total of exactly 2.00
    liters is allowed, and 2.01 is rejected."

    Two prior 666 mL collections (round-then-sum 1.34 L) plus an in-flight 660 mL line
    (round(0.66,2)=0.66) sum to 2.00 L exactly -> allowed, creating a COLLECTED donation.

    Design: Difficulty/combinatorial_formula/plasma_annual_cap_round_per_collection_then_sum
    """
    center, donor = _donor_with_two_prior_666ml_plasma()
    appt3 = _collect_plasma_at(
        center, donor, "2025-03-01T00:00:00.000Z",
        "2025-03-01T08:00:00.000Z", "2025-03-01T18:00:00.000Z")
    res = api.create_donation(appt3["id"], create_donation_payload(volume_ml=660), NURSE)
    donation = validate_success(res, 201)
    assert donation["status"] == "COLLECTED", "annual total exactly 2.00 L is allowed"

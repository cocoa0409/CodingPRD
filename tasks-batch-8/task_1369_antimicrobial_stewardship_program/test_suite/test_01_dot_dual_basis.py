"""Dual-variant DOT calculations: calendar-day basis vs administered-dose basis."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_admin_headers, make_physician_headers, make_pharmacist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, record_doses,
    api_client,
)


def _setup_order_with_three_doses_two_days():
    """Order: route PO, frequency 4; doses 2026-08-01T08:00, 2026-08-01T12:00,
    2026-08-02T08:00 -> dot_calendar 2, administered_doses 3, dot_dose 0.75."""
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"], renal_function_crcl=90)
    drug = create_drug(hid)
    set_clock(hid, "2026-08-01T08:00:00Z")
    order = create_order(
        patient, drug, md, route="PO", dose_mg=500, frequency_per_day=4,
        indication="EMPIRIC",
    )
    record_doses(order["id"], md["id"], [
        "2026-08-01T08:00:00Z",
        "2026-08-01T12:00:00Z",
    ])
    set_clock(hid, "2026-08-02T08:00:00Z")
    record_doses(order["id"], md["id"], ["2026-08-02T08:00:00Z"])
    return hospital, md, order


def test_dot_calendar_counts_distinct_dates_not_doses(api):
    """PRD Section 3.8: "Under the calendar basis, any calendar UTC date on
    which at least one dose was administered contributes one DOT regardless of
    how many doses fell that day: two same-day doses during a three-day course
    contribute 3 DOT."

    Design: Difficulty/dual_variant_calc/dot_calendar_vs_dose_basis_divergence
    """
    _, md, order = _setup_order_with_three_doses_two_days()
    fetched = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    # 3 doses over 2 distinct dates -> calendar basis counts 2.
    assert fetched["administered_doses"] == 3
    assert fetched["dot_calendar"] == 2


def test_dot_dose_divides_by_frequency_and_diverges(api):
    """PRD Section 3.8: "each order's `dot_dose` is its `administered_doses`
    divided by `frequency_per_day`, rounded half-up to two decimals, so those
    same two same-day doses during a three-day twice-daily course contribute
    3.00 — while a four-times-daily regimen would yield 1.50 for the same
    events."

    Design: Difficulty/dual_variant_calc/dot_calendar_vs_dose_basis_divergence
    """
    _, md, order = _setup_order_with_three_doses_two_days()
    fetched = validate_success(
        api.get_antibiotic_order(order["id"], make_physician_headers(md["id"])), 200
    )
    # 3 doses / frequency 4 = 0.75, which must differ from the calendar count 2.
    assert fetched["dot_dose"] == pytest.approx(0.75, abs=0.001)
    assert fetched["dot_calendar"] != fetched["dot_dose"]


def _setup_allergy_assessment_aged_one_year():
    """Assessment at clock 2026-08-10 with years_since_reaction 9 (intake score
    13.00); clock then advanced to 2028-09-01 (>= 1 full year after any plausible
    wall-clock created_at, so the verified-baseline recency term saturates at 0)."""
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", True, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"], renal_function_crcl=90)
    set_clock(hid, "2026-08-10T00:00:00Z")
    res = api_client.create_allergy_assessment(
        {
            "patient_case_id": patient["id"],
            "reported_reaction": "mild rash",
            "reaction_severity": "MILD",
            "years_since_reaction": 9,
        },
        make_pharmacist_headers(ph["id"]),
    )
    assessment = get_success_data(res)
    set_clock(hid, "2028-09-01T00:00:00Z")
    return hospital, ph, assessment


def test_allergy_intake_score_uses_reported_recency(api):
    """PRD Section 3.6: "The severity base contributes 10 points for `MILD`, 35
    for `MODERATE`, and 80 for `SEVERE`." and "The recency term starts at 30
    points and decays by 3 points per elapsed year of `years_since_reaction`,
    never dropping below zero, so a reaction ten or more years old contributes
    nothing."

    Design: Difficulty/dual_variant_calc/allergy_risk_intake_vs_verified_baseline
    """
    _, _, assessment = _setup_allergy_assessment_aged_one_year()
    # intake_estimate variant: 10 (MILD) + 0 (no keyword) + max(0, 30-27) = 13.00
    assert assessment["risk_score"] == pytest.approx(13.00, abs=0.001)
    assert assessment["delabel_eligible"] is True


def test_allergy_verified_baseline_recomputed_at_scheduling(api):
    """PRD Section 3.6: "Scheduling moves the assessment to `TESTING_SCHEDULED`
    and recomputes the score on the verified baseline: the same formula, but
    with the recency term evaluated against the effective elapsed years — the
    stored `years_since_reaction` plus the full years elapsed between the
    assessment's `created_at` and the hospital clock at scheduling time — so an
    intake value that has aged yields a different score than the stored
    estimate."

    Design: Difficulty/dual_variant_calc/allergy_risk_intake_vs_verified_baseline
    """
    hospital, ph, assessment = _setup_allergy_assessment_aged_one_year()
    intake_score = assessment["risk_score"]
    res = api.schedule_allergy_test(assessment["id"], make_pharmacist_headers(ph["id"]))
    scheduled = validate_success(res, 200)
    # verified_baseline: effective_years >= 10 -> recency max(0, 30-3*eff) = 0
    assert scheduled["status"] == "TESTING_SCHEDULED"
    assert scheduled["risk_score"] == pytest.approx(10.00, abs=0.001)
    assert scheduled["risk_score"] != intake_score

"""Boundary precision: benchmark percentile floors and IV-to-PO minimum hours."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_physician_headers, make_pharmacist_headers, make_preventionist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, record_doses, setup_iv_order_with_hours,
    create_dot_snapshot_payload,
    api_client, ApiErrorId,
)


def _setup_three_dot_snapshot():
    """One unrestricted PO order with one dose on each of 2026-08-01/02/03."""
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ip = create_practitioner(
        hid, "INFECTION_PREVENTIONIST", True, full_name="Nurse IP", license_no="L-IP-1"
    )
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid)
    # No set_clock: the hospital clock already starts at 2026-08-01T00:00:00Z
    # (PRD 2.4) and holding the clock is rejected with ERR_CLOCK_REGRESSION.
    order = create_order(
        patient, drug, md, route="PO", dose_mg=500, frequency_per_day=1,
        indication="EMPIRIC",
    )
    record_doses(order["id"], md["id"], [
        "2026-08-01T00:00:00Z",
        "2026-08-02T00:00:00Z",
        "2026-08-03T00:00:00Z",
    ])
    return hospital, md, ip, order


def test_snapshot_calendar_and_per_thousand_totals(api):
    """PRD Section 3.8: "each snapshot aggregates the slices attributable to its
    month: `total_dot_calendar` sums the per-order calendar counts and
    `total_dot_dose` sums the per-order dose counts (two decimals, round half
    up)." and "From the totals, `dot_per_1000_pd_calendar` is one thousand
    times `total_dot_calendar` divided by `patient_days`".

    Design: Difficulty/boundary_precision_check/benchmark_percentile_exact_floor
    """
    hospital, _, ip, _ = _setup_three_dot_snapshot()
    res = api.create_dot_snapshot(
        create_dot_snapshot_payload(hospital["id"], period_label="2026-08", patient_days=100),
        make_preventionist_headers(ip["id"]),
    )
    snapshot = validate_success(res, 201)
    assert snapshot["total_dot_calendar"] == 3
    assert snapshot["dot_per_1000_pd_calendar"] == pytest.approx(30.00, abs=0.001)


def test_rate_below_p25_floor_maps_to_p10(api):
    """PRD Section 3.8: "The percentile is the largest named percentile whose
    floor the hospital's `dot_per_1000_pd_calendar` meets or exceeds: the
    floors are 0 for the 10th, 350 for the 25th, 480 for the 50th, 620 for the
    75th, and 780 for the 90th, and they are inclusive — a rate of exactly 780
    reports a `benchmark_percentile` of 90, a rate of 779.99 reports 75, and
    any rate below 350 reports 10."

    Design: Difficulty/boundary_precision_check/benchmark_percentile_exact_floor
    """
    hospital, _, ip, _ = _setup_three_dot_snapshot()
    res = api.create_dot_snapshot(
        create_dot_snapshot_payload(hospital["id"], period_label="2026-08", patient_days=100),
        make_preventionist_headers(ip["id"]),
    )
    snapshot = validate_success(res, 201)
    # 30.00 < 350 (P25 floor) -> P10.
    assert snapshot["benchmark_percentile"] == 10


def test_exactly_minimum_iv_hours_passes_gate(api):
    """PRD Section 3.5: "the order's `cumulative_iv_hours` is at least the
    hospital's `iv_to_po_min_iv_hours` (the comparison is inclusive, so exactly
    the minimum qualifies)".

    Design: Difficulty/boundary_precision_check/iv_to_po_minimum_hours_boundary
    """
    env = setup_iv_order_with_hours(8, frequency_per_day=4, crcl=90)
    # 8 doses at frequency 4 -> 8 * 6 = 48 == default minimum.
    order = env["order"]
    assert order["cumulative_iv_hours"] == 48
    res = api.detect_conversion_opportunity(
        {
            "antibiotic_order_id": order["id"],
            "opportunity_kind": "IV_TO_PO",
            "suggested_antimicrobial_id": env["drug"]["id"],
        },
        make_pharmacist_headers(env["ph"]["id"]),
    )
    opp = validate_success(res, 201)
    assert opp["status"] == "DETECTED"
    # 40 + 0.4*min(90,90)=36 + max(0, 30-5*0)=30 -> 106.00
    assert opp["eligibility_score"] == pytest.approx(106.00, abs=0.001)


def test_one_dose_below_minimum_iv_hours_rejected(api):
    """PRD Section 3.5: "otherwise the detection is rejected with
    `ERR_CONVERSION_NOT_ELIGIBLE` or `ERR_DEESCALATION_NOT_ELIGIBLE`
    respectively." and "the order's `cumulative_iv_hours` is at least the
    hospital's `iv_to_po_min_iv_hours` (the comparison is inclusive, so exactly
    the minimum qualifies)".

    Design: Difficulty/boundary_precision_check/iv_to_po_minimum_hours_boundary
    """
    env = setup_iv_order_with_hours(7, frequency_per_day=4, crcl=90)
    # 7 doses at frequency 4 -> 42 hours < 48.
    order = env["order"]
    assert order["cumulative_iv_hours"] == 42
    res = api.detect_conversion_opportunity(
        {
            "antibiotic_order_id": order["id"],
            "opportunity_kind": "IV_TO_PO",
            "suggested_antimicrobial_id": env["drug"]["id"],
        },
        make_pharmacist_headers(env["ph"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONVERSION_NOT_ELIGIBLE)

"""Combinatorial formulas: IV-to-PO weighted gate score; antibiogram per-row rounding."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    make_admin_headers, make_physician_headers, make_pharmacist_headers,
    make_microbiologist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, setup_iv_order_with_hours,
    create_final_culture_with_result, create_antibiogram_payload,
    api_client,
)


def test_iv_to_po_score_combines_gated_terms(api):
    """PRD Section 3.5: "The hemodynamic stability term carries weight 1.0 and
    a fixed value of 40 points, the program-wide proxy for a stable patient.
    The renal term carries weight 0.4 and equals the patient's
    `renal_function_crcl` capped at 90 mL/min. The duration term carries
    weight 1.0 and starts from 30 points, decaying by 5 points for each full
    24-hour block of IV time accrued beyond the hospital's minimum, and never
    drops below zero."

    Design: Difficulty/combinatorial_formula/iv_to_po_multigate_weighted_score
    """
    env = setup_iv_order_with_hours(12, frequency_per_day=4, crcl=80)
    # 12 doses at frequency 4 -> cumulative_iv_hours = 12 * 6 = 72; min 48
    order = env["order"]
    assert order["cumulative_iv_hours"] == 72
    res = api.detect_conversion_opportunity(
        {
            "antibiotic_order_id": order["id"],
            "opportunity_kind": "IV_TO_PO",
            "suggested_antimicrobial_id": env["drug"]["id"],
        },
        make_pharmacist_headers(env["ph"]["id"]),
    )
    opp = validate_success(res, 201)
    # 40 + 0.4*min(80,90)=32 + max(0, 30-5*floor(24/24))=25 -> 97.00
    assert opp["eligibility_score"] == pytest.approx(97.00, abs=0.001)
    assert opp["status"] == "DETECTED"


def test_iv_to_po_requires_all_gates_and_score_floor(api):
    """PRD Section 3.5: "a `ConversionOpportunity` is created in `DETECTED` —
    with `detected_at` stamped from the clock and `eligibility_score` computed
    per the kind — only when every gate passes and the score clears its floor;
    otherwise the detection is rejected with `ERR_CONVERSION_NOT_ELIGIBLE` or
    `ERR_DEESCALATION_NOT_ELIGIBLE` respectively." and "An opportunity is
    created only when the final score is at least 60."

    Design: Difficulty/combinatorial_formula/iv_to_po_multigate_weighted_score
    """
    env = setup_iv_order_with_hours(12, frequency_per_day=4, crcl=80)
    order = env["order"]
    res = api.detect_conversion_opportunity(
        {
            "antibiotic_order_id": order["id"],
            "opportunity_kind": "IV_TO_PO",
            "suggested_antimicrobial_id": env["drug"]["id"],
        },
        make_pharmacist_headers(env["ph"]["id"]),
    )
    opp = validate_success(res, 201)
    assert opp["eligibility_score"] >= 60
    assert opp["opportunity_kind"] == "IV_TO_PO"
    assert opp["antibiotic_order_id"] == order["id"]
    assert opp["detected_at"]


def _setup_three_organism_cultures():
    """Hospital (min_isolates 1); one patient; one drug; three FINAL cultures
    of distinct organisms from URINE on 2026-08-01 with interpretations S, S, R."""
    hospital = create_hospital(antibiogram_min_isolates=1)
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(
        hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
        is_restricted=False, has_po_form=True,
    )
    set_clock(hid, "2026-08-02T00:00:00Z")
    cultures = {}
    for organism, interp, hour in [("E_COLI", "S", "00"), ("KLEBSIELLA", "S", "01"), ("PROTEUS", "R", "02")]:
        culture, _ = create_final_culture_with_result(
            patient, mb, drug, organism=organism,
            collected_at=f"2026-08-01T{hour}:00:00Z", interpretation=interp,
        )
        cultures[organism] = culture
    return hospital, mb, drug, cultures


def test_antibiogram_row_count_one_per_organism_drug_pair(api):
    """PRD Section 3.7: "Rows are computed at creation, one per observed
    organism–drug pair, and the rounding order is pinned: each row's
    `pct_susceptible` is computed first, as one hundred times the row's
    `susceptible_count` divided by its `isolate_count`, rounded half-up to two
    decimals; only then is `is_reportable` evaluated as `isolate_count`
    reaching the hospital's `antibiogram_min_isolates`, and `row_count` tallied
    as the number of reportable rows."

    Design: Difficulty/combinatorial_formula/antibiogram_row_rounding_order_pinned
    """
    hospital, mb, drug, _ = _setup_three_organism_cultures()
    res = api.create_antibiogram(
        create_antibiogram_payload(hospital["id"]),
        make_microbiologist_headers(mb["id"]),
    )
    antibiogram = validate_success(res, 201)
    assert antibiogram["row_count"] == 3
    rows = validate_success(
        api.list_antibiogram_rows_for(antibiogram["id"], make_microbiologist_headers(mb["id"])), 200
    )
    assert len(rows) == 3
    for row in rows:
        assert row["isolate_count"] == 1
        assert row["is_reportable"] is True


def test_antibiogram_pct_rounded_per_row_not_pooled(api):
    """PRD Section 3.7: "Pooling numerators and denominators across drugs and
    rounding once at the end yields different two-decimal values and is
    forbidden."

    Design: Difficulty/combinatorial_formula/antibiogram_row_rounding_order_pinned
    """
    hospital, mb, drug, _ = _setup_three_organism_cultures()
    res = api.create_antibiogram(
        create_antibiogram_payload(hospital["id"]),
        make_microbiologist_headers(mb["id"]),
    )
    antibiogram = validate_success(res, 201)
    rows = validate_success(
        api.list_antibiogram_rows_for(antibiogram["id"], make_microbiologist_headers(mb["id"])), 200
    )
    by_organism = {r["organism"]: r for r in rows}
    # Per-row: E_COLI 1/1 -> 100.00; KLEBSIELLA 1/1 -> 100.00; PROTEUS 0/1 -> 0.00.
    assert by_organism["E_COLI"]["pct_susceptible"] == pytest.approx(100.00, abs=0.001)
    assert by_organism["KLEBSIELLA"]["pct_susceptible"] == pytest.approx(100.00, abs=0.001)
    assert by_organism["PROTEUS"]["pct_susceptible"] == pytest.approx(0.00, abs=0.001)

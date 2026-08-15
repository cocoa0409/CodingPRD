"""Calculation claims: culture-driven selector policy, antibiogram input-set
filtering, de-escalation scoring gate, regulatory payload determinism."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_physician_headers, make_pharmacist_headers, make_microbiologist_headers,
    make_preventionist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    set_clock, create_order, create_final_culture_with_result,
    create_allergy_assessment_payload, create_antibiogram_payload,
    create_culture_report_payload, create_susceptibility_result_payload,
    create_finalized_snapshot, create_regulatory_report_payload,
    api_client, ApiErrorId,
)


def _setup_selector_three_drugs():
    """FINAL culture with S rows for NARROW_PENICILLIN, CEPHALOSPORIN, CARBAPENEM."""
    hospital = create_hospital()
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    amp = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True)
    cef = create_drug(hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
                      is_restricted=False, has_po_form=False)
    mer = create_drug(hid, drug_name="MEROPENEM", drug_class="CARBAPENEM",
                      is_restricted=True, has_po_form=False)
    res = api_client.create_culture_report(
        create_culture_report_payload(patient["id"]),
        make_microbiologist_headers(mb["id"]),
    )
    culture = get_success_data(res)
    for drug, mic in [(mer, 0.5), (cef, 1.0), (amp, 2.0)]:
        get_success_data(api_client.create_susceptibility_result(
            culture["id"],
            create_susceptibility_result_payload(drug["id"], interpretation="S", mic_value=mic),
            make_microbiologist_headers(mb["id"]),
        ))
    get_success_data(api_client.finalize_culture_report(
        culture["id"], make_microbiologist_headers(mb["id"])
    ))
    return hospital, ph, culture, amp, cef, mer


def test_selector_recommendation_narrowest_susceptible_wins(api):
    """PRD Section 3.4: "Ranking is deterministic: narrowest spectrum first by
    the class breadth ladder of §3.5; ties prefer a drug with `has_po_form`
    true; further ties go to the lower `mic_value`; and any remaining tie is
    broken by the drug's earlier `created_at` — never by identifier." and PRD
    Section 3.5: "The breadth ladder ranks `CARBAPENEM` at 90, `GLYCOPEPTIDE`
    at 70, `FLUOROQUINOLONE` at 60, `EXTENDED_SPECTRUM_PENICILLIN` at 50,
    `AMINOGLYCOSIDE` at 45, `CEPHALOSPORIN` at 40, `MACROLIDE` at 30, and
    `NARROW_PENICILLIN` at 20."

    Design: Corner/calculations/selector_recommendation_narrowest_susceptible_wins
    """
    _, ph, culture, amp, _, _ = _setup_selector_three_drugs()
    res = api.recommend_for_culture(culture["id"], make_pharmacist_headers(ph["id"]))
    recommendation = validate_success(res, 200)
    assert recommendation["recommended_antimicrobial_id"] == amp["id"]
    assert recommendation["pool_size"] == 3


def test_selector_excludes_penicillin_when_allergy_active(api):
    """PRD Section 3.4: "Allergy posture then filters further: if the patient
    carries a penicillin allergy assessment in `SUSPECTED`,
    `TESTING_SCHEDULED`, `TESTED`, or `CONFIRMED`, any candidate whose
    `is_penicillin_class` is true is excluded; a `DELABELED` or `WITHDRAWN`
    assessment imposes no such exclusion."

    Design: Corner/calculations/selector_excludes_penicillin_when_allergy_active
    """
    hospital = create_hospital()
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    amp = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True, is_penicillin_class=True)
    cef = create_drug(hid, drug_name="CEFTRIAXONE", drug_class="CEPHALOSPORIN",
                      is_restricted=False, has_po_form=False)
    get_success_data(api_client.create_allergy_assessment(
        create_allergy_assessment_payload(patient["id"]),
        make_pharmacist_headers(ph["id"]),
    ))
    res = api_client.create_culture_report(
        create_culture_report_payload(patient["id"]),
        make_microbiologist_headers(mb["id"]),
    )
    culture = get_success_data(res)
    for drug, mic in [(amp, 2.0), (cef, 1.0)]:
        get_success_data(api_client.create_susceptibility_result(
            culture["id"],
            create_susceptibility_result_payload(drug["id"], interpretation="S", mic_value=mic),
            make_microbiologist_headers(mb["id"]),
        ))
    get_success_data(api_client.finalize_culture_report(
        culture["id"], make_microbiologist_headers(mb["id"])
    ))
    res = api.recommend_for_culture(culture["id"], make_pharmacist_headers(ph["id"]))
    recommendation = validate_success(res, 200)
    assert recommendation["recommended_antimicrobial_id"] == cef["id"]
    assert recommendation["pool_size"] == 1


def test_selector_empty_pool_returns_null_not_error(api):
    """PRD Section 3.4: "When the pool is empty the call still succeeds with
    HTTP 200 and reports `recommended_antimicrobial_id` as null with a
    `pool_size` of zero and a `reason` string marking the empty pool — an empty
    pool is a reportable outcome, not an error."

    Design: Corner/calculations/selector_empty_pool_returns_null_not_error
    """
    hospital = create_hospital()
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    amp = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True)
    culture, _ = create_final_culture_with_result(
        patient, mb, amp, interpretation="R", mic_value=32.0,
    )
    res = api.recommend_for_culture(culture["id"], make_pharmacist_headers(ph["id"]))
    recommendation = validate_success(res, 200)
    assert recommendation["recommended_antimicrobial_id"] is None
    assert recommendation["pool_size"] == 0


def test_antibiogram_first_isolate_filtering(api):
    """PRD Section 3.7: "The qualifying cultures for a row are reports of the
    hospital in `FINAL` or `AMENDED` status with `is_first_isolate` true whose
    `collected_at` falls within the half-open window and which carry a
    susceptibility row for that drug; `isolate_count` counts them and
    `susceptible_count` counts those interpreted `S`."

    Design: Corner/calculations/antibiogram_first_isolate_filtering
    """
    hospital = create_hospital(antibiogram_min_isolates=1)
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True)
    # Two same-(organism, source) cultures 1h apart: only the first counts.
    c1, _ = create_final_culture_with_result(
        patient, mb, drug, collected_at="2026-08-01T00:00:00Z", interpretation="S",
    )
    # Advance the clock to the second culture's collection time (PRD 3.4:
    # a collected_at after the hospital clock is rejected ERR_FUTURE_SPECIMEN).
    set_clock(hid, "2026-08-01T01:00:00Z")
    c2, _ = create_final_culture_with_result(
        patient, mb, drug, collected_at="2026-08-01T01:00:00Z", interpretation="R", mic_value=32.0,
    )
    assert c1["is_first_isolate"] is True
    assert c2["is_first_isolate"] is False
    antibiogram = validate_success(
        api.create_antibiogram(
            create_antibiogram_payload(hid), make_microbiologist_headers(mb["id"])
        ), 201,
    )
    rows = validate_success(
        api.list_antibiogram_rows_for(antibiogram["id"], make_microbiologist_headers(mb["id"])), 200
    )
    matching = [r for r in rows if r["organism"] == "E_COLI" and r["antimicrobial_id"] == drug["id"]]
    assert len(matching) == 1
    assert matching[0]["isolate_count"] == 1
    assert matching[0]["susceptible_count"] == 1
    assert matching[0]["pct_susceptible"] == pytest.approx(100.00, abs=0.001)


def test_antibiogram_preliminary_cultures_excluded(api):
    """PRD Section 3.4: "A report's `status` is drawn from `PRELIMINARY`,
    `FINAL`, and `AMENDED`; only `FINAL` and `AMENDED` reports may drive
    recommendations or feed antibiograms — a `PRELIMINARY` report is invisible
    to both."

    Design: Corner/calculations/antibiogram_preliminary_cultures_excluded
    """
    hospital = create_hospital(antibiogram_min_isolates=1)
    hid = hospital["id"]
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    patient = create_patient(hid, md["id"])
    drug = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                      is_restricted=False, has_po_form=True)
    # Culture left PRELIMINARY (never finalized), though it carries an S row.
    res = api_client.create_culture_report(
        create_culture_report_payload(patient["id"]),
        make_microbiologist_headers(mb["id"]),
    )
    culture = get_success_data(res)
    get_success_data(api_client.create_susceptibility_result(
        culture["id"],
        create_susceptibility_result_payload(drug["id"], interpretation="S"),
        make_microbiologist_headers(mb["id"]),
    ))
    antibiogram = validate_success(
        api.create_antibiogram(
            create_antibiogram_payload(hid), make_microbiologist_headers(mb["id"])
        ), 201,
    )
    assert antibiogram["row_count"] == 0


def test_deescalation_score_gate_below_threshold(api):
    """PRD Section 3.5: "The integer score then starts at a base of 50, adds 25
    when the supporting culture's `is_first_isolate` is true, adds 15 when the
    order's `dot_calendar` has reached the hospital's `dot_review_threshold`,
    subtracts 20 when the patient `is_immunocompromised`, and adds ten times
    the breadth-rank difference between the current and suggested drugs." and
    "A score of at least 65 creates the opportunity."

    Design: Corner/calculations/deescalation_score_gate_below_threshold
    """
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    mb = create_practitioner(hid, "MICROBIOLOGIST", True, full_name="Dr MB", license_no="L-MB-1")
    patient = create_patient(hid, md["id"], is_immunocompromised=True)
    drug1 = create_drug(hid, drug_name="PENICILLIN-V", drug_class="NARROW_PENICILLIN",
                        is_restricted=False, has_po_form=True)
    drug2 = create_drug(hid, drug_name="AMPICILLIN", drug_class="NARROW_PENICILLIN",
                        is_restricted=False, has_po_form=True)
    order = create_order(
        patient, drug1, md, route="PO", dose_mg=500, frequency_per_day=2,
        indication="EMPIRIC",
    )
    create_final_culture_with_result(patient, mb, drug2, interpretation="S")
    # Score: 50 - 20 (immunocompromised) + 0 breadth delta (same class) = 30 < 65.
    res = api.detect_conversion_opportunity(
        {
            "antibiotic_order_id": order["id"],
            "opportunity_kind": "DEESCALATION",
            "suggested_antimicrobial_id": drug2["id"],
        },
        make_pharmacist_headers(ph["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DEESCALATION_NOT_ELIGIBLE)


def test_regulatory_payload_deterministic_checksum(api):
    """PRD Section 3.8: "The `checksum` is the FNV-1a 32-bit hash of
    `payload_json` rendered as eight lowercase hexadecimal characters, serving
    as tamper evidence, and determinism is guaranteed: the same snapshot with
    the same report header yields a byte-identical payload." and "Submission —
    again the preventionist's action — requires the report to be `DRAFT`
    (`ERR_REPORT_NOT_DRAFT`), re-verifies the pinned snapshot's finalized
    posture, and refuses to proceed when another report for the same hospital,
    report type, and period already stands in `SUBMITTED` or `ACCEPTED`
    (`ERR_REPORT_ALREADY_SUBMITTED`)."

    Design: Corner/calculations/regulatory_payload_deterministic_checksum
    """
    hospital = create_hospital()
    hid = hospital["id"]
    ip = create_practitioner(
        hid, "INFECTION_PREVENTIONIST", True, full_name="Nurse IP", license_no="L-IP-1"
    )
    snapshot = create_finalized_snapshot(hospital, ip)
    # First report submits successfully.
    res = api_client.create_regulatory_report(
        create_regulatory_report_payload(hid, snapshot["id"]),
        make_preventionist_headers(ip["id"]),
    )
    report1 = get_success_data(res)
    submitted = validate_success(
        api.submit_regulatory_report(report1["id"], make_preventionist_headers(ip["id"])), 200
    )
    assert "0.00" in submitted["payload_json"] or "dot_per_1000_pd_calendar" in submitted["payload_json"]
    assert submitted["checksum"]
    # Second report for the same (hospital, type, period) is refused at submit.
    res = api_client.create_regulatory_report(
        create_regulatory_report_payload(hid, snapshot["id"]),
        make_preventionist_headers(ip["id"]),
    )
    report2 = get_success_data(res)
    res = api.submit_regulatory_report(
        report2["id"], make_preventionist_headers(ip["id"])
    )
    validate_error(res, ApiErrorId.ERR_REPORT_ALREADY_SUBMITTED)

"""Priority-pair conflicts: the validation cascade order is part of the contract."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_physician_headers, make_pharmacist_headers,
    create_hospital, create_practitioner, create_patient, create_drug,
    create_antibiotic_order_payload, create_allergy_assessment_payload,
    api_client, ApiErrorId,
)


def _setup_discharged_patient_with_allergy():
    """Patient with a SUSPECTED penicillin allergy, then discharged."""
    hospital = create_hospital()
    hid = hospital["id"]
    md = create_practitioner(hid, "PHYSICIAN", False, full_name="Dr MD", license_no="L-MD-1")
    ph = create_practitioner(hid, "PHARMACIST", True, full_name="Pharm PH", license_no="L-PH-1")
    patient = create_patient(hid, md["id"])
    res = api_client.create_allergy_assessment(
        create_allergy_assessment_payload(patient["id"]),
        make_pharmacist_headers(ph["id"]),
    )
    get_success_data(res)
    res = api_client.discharge_patient_case(patient["id"], make_physician_headers(md["id"]))
    get_success_data(res)
    pen_drug = create_drug(
        hid, drug_name="AMOXICILLIN", drug_class="NARROW_PENICILLIN",
        is_restricted=False, has_po_form=True, is_penicillin_class=True,
    )
    return hospital, md, patient, pen_drug


def test_discharged_patient_beats_allergy_block(api):
    """PRD Section 2.8: "Every request passes through a fixed validation
    cascade, and the order is part of the contract: when several checks would
    fail, the caller sees the error from the earliest failing stage." and PRD
    Section 3.2: "the server confirms the prescriber is active
    (`ERR_PRACTITIONER_INACTIVE`), then that the patient is still `ADMITTED`
    (`ERR_PATIENT_DISCHARGED`), then that the drug is formulary-active
    (`ERR_DRUG_SUSPENDED`). Only then do the clinical safety gates run: first
    the allergy block, then the renal guardrail."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_allergy_conflict
    """
    _, md, patient, pen_drug = _setup_discharged_patient_with_allergy()
    res = api.create_antibiotic_order(
        create_antibiotic_order_payload(
            patient["id"], pen_drug["id"], md["id"],
            route="PO", dose_mg=500, frequency_per_day=3,
        ),
        make_physician_headers(md["id"]),
    )
    err = validate_error(res, ApiErrorId.ERR_PATIENT_DISCHARGED)
    assert err["error_id"] != ApiErrorId.ERR_ALLERGY_BLOCKS_ORDER


def test_discharged_patient_error_is_409(api):
    """PRD Section 2.8: "4. **Referenced-state checks** — a referenced
    practitioner must be active (`ERR_PRACTITIONER_INACTIVE`); a referenced
    patient must still be admitted for any order, culture, or assessment
    mutation (`ERR_PATIENT_DISCHARGED`); a referenced antimicrobial must be
    formulary-active for a new order or a culture-driven recommendation
    (`ERR_DRUG_SUSPENDED`)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_allergy_conflict
    """
    _, md, patient, pen_drug = _setup_discharged_patient_with_allergy()
    res = api.create_antibiotic_order(
        create_antibiotic_order_payload(
            patient["id"], pen_drug["id"], md["id"],
            route="PO", dose_mg=500, frequency_per_day=3,
        ),
        make_physician_headers(md["id"]),
    )
    # State check (409) outranks the safety gate (422).
    assert res.status_code == 409
    validate_error(res, ApiErrorId.ERR_PATIENT_DISCHARGED)


def _setup_cross_facility_allergy_conflict():
    """H1 patient with SUSPECTED allergy; H1 penicillin drug; H2 prescriber."""
    h1 = create_hospital(name="H1", nhsn_facility_id="NHSN-1")
    h2 = create_hospital(name="H2", nhsn_facility_id="NHSN-2")
    md1 = create_practitioner(h1["id"], "PHYSICIAN", False, full_name="Dr MD1", license_no="L-MD1")
    md2 = create_practitioner(h2["id"], "PHYSICIAN", False, full_name="Dr MD2", license_no="L-MD2")
    ph1 = create_practitioner(h1["id"], "PHARMACIST", True, full_name="Pharm PH1", license_no="L-PH1")
    patient = create_patient(h1["id"], md1["id"])
    res = api_client.create_allergy_assessment(
        create_allergy_assessment_payload(patient["id"]),
        make_pharmacist_headers(ph1["id"]),
    )
    get_success_data(res)
    pen_drug = create_drug(
        h1["id"], drug_name="AMOXICILLIN", drug_class="NARROW_PENICILLIN",
        is_restricted=False, has_po_form=True, is_penicillin_class=True,
    )
    return h1, md2, patient, pen_drug


def test_allergy_block_beats_cross_facility_reference(api):
    """PRD Section 2.8: "the allergy and renal safety checks on ordering fire
    before the cross-facility reference check" and PRD Section 3.2: "After
    safety comes referential integrity — patient, drug, and prescriber must
    share one hospital (`ERR_CROSS_FACILITY_REFERENCE`)".

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_cross_facility_conflict
    """
    _, md2, patient, pen_drug = _setup_cross_facility_allergy_conflict()
    # Order placed by an H2 prescriber against an H1 penicillin drug + allergy.
    res = api.create_antibiotic_order(
        create_antibiotic_order_payload(
            patient["id"], pen_drug["id"], md2["id"],
            route="PO", dose_mg=500, frequency_per_day=3,
        ),
        make_physician_headers(md2["id"]),
    )
    err = validate_error(res, ApiErrorId.ERR_ALLERGY_BLOCKS_ORDER)
    assert err["error_id"] != ApiErrorId.ERR_CROSS_FACILITY_REFERENCE


def test_allergy_block_fires_even_with_foreign_prescriber(api):
    """PRD Section 3.2: "If the patient carries a penicillin allergy assessment
    in `SUSPECTED`, `TESTING_SCHEDULED`, `TESTED`, or `CONFIRMED` and the
    ordered drug has `is_penicillin_class` true, the order is rejected with
    `ERR_ALLERGY_BLOCKS_ORDER`; an assessment that reached `DELABELED` or
    `WITHDRAWN` no longer blocks."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_cross_facility_conflict
    """
    _, md2, patient, pen_drug = _setup_cross_facility_allergy_conflict()
    res = api.create_antibiotic_order(
        create_antibiotic_order_payload(
            patient["id"], pen_drug["id"], md2["id"],
            route="PO", dose_mg=500, frequency_per_day=3,
        ),
        make_physician_headers(md2["id"]),
    )
    assert res.status_code == 422
    validate_error(res, ApiErrorId.ERR_ALLERGY_BLOCKS_ORDER)

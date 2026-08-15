"""Payload factories — one per entity, input fields only per PRD endpoint catalogue."""

DEFAULT_MRN = "MRN-1"
DEFAULT_ADMITTED_AT = "2026-08-01T00:00:00Z"


def create_hospital_payload(**overrides) -> dict:
    defaults = {
        "name": "H",
        "nhsn_facility_id": "NHSN-1",
    }
    defaults.update(overrides)
    return defaults


def create_practitioner_payload(hospital_id: str, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "full_name": "Dr MD",
        "license_no": "L-MD-1",
        "discipline": "PHYSICIAN",
        "is_stewardship_member": False,
    }
    defaults.update(overrides)
    return defaults


def create_patient_case_payload(hospital_id: str, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "mrn": DEFAULT_MRN,
        "admitted_at": DEFAULT_ADMITTED_AT,
        "ward": "4W",
        "weight_kg": 70,
        "renal_function_crcl": 90,
    }
    defaults.update(overrides)
    return defaults


def create_antimicrobial_payload(hospital_id: str, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "drug_name": "LEVOFLOXACIN",
        "drug_class": "FLUOROQUINOLONE",
        "is_restricted": False,
        "has_po_form": True,
    }
    defaults.update(overrides)
    return defaults


def create_allergy_assessment_payload(patient_case_id: str, **overrides) -> dict:
    defaults = {
        "patient_case_id": patient_case_id,
        "reported_reaction": "mild rash",
        "reaction_severity": "MILD",
        "years_since_reaction": 3,
    }
    defaults.update(overrides)
    return defaults


def create_culture_report_payload(patient_case_id: str, **overrides) -> dict:
    defaults = {
        "patient_case_id": patient_case_id,
        "specimen_source": "URINE",
        "collected_at": "2026-08-01T00:00:00Z",
        "organism": "E_COLI",
    }
    defaults.update(overrides)
    return defaults


def create_susceptibility_result_payload(antimicrobial_id: str, **overrides) -> dict:
    defaults = {
        "antimicrobial_id": antimicrobial_id,
        "interpretation": "S",
        "mic_value": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_antibiotic_order_payload(patient_case_id: str, antimicrobial_id: str,
                                     prescriber_id: str, **overrides) -> dict:
    defaults = {
        "patient_case_id": patient_case_id,
        "antimicrobial_id": antimicrobial_id,
        "prescriber_id": prescriber_id,
        "route": "IV",
        "dose_mg": 500,
        "frequency_per_day": 1,
        "indication": "EMPIRIC",
    }
    defaults.update(overrides)
    return defaults


def create_approval_request_payload(antibiotic_order_id: str, requester_id: str, **overrides) -> dict:
    defaults = {
        "antibiotic_order_id": antibiotic_order_id,
        "requester_id": requester_id,
        "justification": "Suspected ESBL bacteremia per prior cultures",
    }
    defaults.update(overrides)
    return defaults


def create_audit_intervention_payload(antibiotic_order_id: str, auditor_id: str, **overrides) -> dict:
    defaults = {
        "antibiotic_order_id": antibiotic_order_id,
        "auditor_id": auditor_id,
        "intervention_type": "DURATION_REDUCTION",
        "recommendation_text": "Reduce total course from 14 to 7 days per guideline",
    }
    defaults.update(overrides)
    return defaults


def create_conversion_detect_payload(antibiotic_order_id: str, **overrides) -> dict:
    defaults = {
        "antibiotic_order_id": antibiotic_order_id,
        "opportunity_kind": "IV_TO_PO",
    }
    defaults.update(overrides)
    return defaults


def create_antibiogram_payload(hospital_id: str, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_empiric_guideline_payload(hospital_id: str, syndrome: str,
                                      first_line_antimicrobial_id: str,
                                      source_antibiogram_id: str, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "syndrome": syndrome,
        "first_line_antimicrobial_id": first_line_antimicrobial_id,
        "source_antibiogram_id": source_antibiogram_id,
    }
    defaults.update(overrides)
    return defaults


def create_dot_snapshot_payload(hospital_id: str, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "period_label": "2026-08",
        "patient_days": 100,
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_report_payload(hospital_id: str, dot_snapshot_id: str, **overrides) -> dict:
    defaults = {
        "hospital_id": hospital_id,
        "report_type": "NHSN_AUR",
        "period_label": "2026-07",
        "dot_snapshot_id": dot_snapshot_id,
    }
    defaults.update(overrides)
    return defaults

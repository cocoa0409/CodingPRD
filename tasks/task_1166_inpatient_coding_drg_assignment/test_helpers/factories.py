"""Payload factories — one per creatable resource, input fields only (PRD Section 4)."""

DEFAULTS = {
    "ADMIT_AT": "2026-04-20T08:00:00Z",
    "DISCHARGE_AT": "2026-04-25T10:00:00Z",
    "DISCHARGE_DISPOSITION": "HOME",
    "PATIENT_CLASS": "INPATIENT",
    "FINANCIAL_CLASS": "MEDICARE",
    "TOTAL_CHARGES_CENTS": 900000,
    "ACUITY": "MEDICAL_LOW",
    "DUE_AT": "2026-05-10T00:00:00Z",
    "DEFICIENCY_DUE_AT": "2026-04-30T00:00:00Z",
    "DEFICIENCY_TYPE": "MISSING_DISCHARGE_SUMMARY",
    "ICD_CODE": "I21.09",
    "POA": "Y",
    "PCS_CODE": "0DJ08ZZ",
    "PERFORMED_AT": "2026-04-22T09:00:00Z",
    "CREDENTIAL": "CCS",
    "PAID_AT": "2026-05-01T00:00:00Z",
    "WINDOW_START": "2026-04-01T00:00:00Z",
    "WINDOW_END": "2026-06-01T00:00:00Z",
    "SAMPLE_SIZE": 5,
    "RETURN_REASON": "query physician on specificity",
    "RESOLUTION": "APPLY",
    "THRESHOLD_DAYS": 3,
}


def create_patient_account_payload(**overrides) -> dict:
    defaults = {
        "mrn": "MRN-DEFAULT",
        "admit_at": DEFAULTS["ADMIT_AT"],
        "patient_class": DEFAULTS["PATIENT_CLASS"],
        "financial_class": DEFAULTS["FINANCIAL_CLASS"],
        "total_charges_cents": DEFAULTS["TOTAL_CHARGES_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def discharge_account_payload(**overrides) -> dict:
    defaults = {
        "discharge_at": DEFAULTS["DISCHARGE_AT"],
        "discharge_disposition": DEFAULTS["DISCHARGE_DISPOSITION"],
    }
    defaults.update(overrides)
    return defaults


def create_chart_payload(account_id: str, **overrides) -> dict:
    defaults = {"account_id": account_id, "acuity": DEFAULTS["ACUITY"]}
    defaults.update(overrides)
    return defaults


def create_deficiency_payload(chart_id: str, **overrides) -> dict:
    defaults = {
        "chart_id": chart_id,
        "type": DEFAULTS["DEFICIENCY_TYPE"],
        "due_at": DEFAULTS["DEFICIENCY_DUE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_diagnosis_line_payload(chart_id: str, **overrides) -> dict:
    defaults = {
        "chart_id": chart_id,
        "icd_code": DEFAULTS["ICD_CODE"],
        "poa": DEFAULTS["POA"],
        "sequence": 1,
    }
    defaults.update(overrides)
    return defaults


def create_procedure_line_payload(chart_id: str, **overrides) -> dict:
    defaults = {
        "chart_id": chart_id,
        "pcs_code": DEFAULTS["PCS_CODE"],
        "performed_at": DEFAULTS["PERFORMED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_coder_payload(**overrides) -> dict:
    defaults = {
        "employee_no": "E-DEFAULT",
        "full_name": "Test Coder",
        "credential": DEFAULTS["CREDENTIAL"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(chart_id: str, **overrides) -> dict:
    defaults = {"chart_id": chart_id, "due_at": DEFAULTS["DUE_AT"]}
    defaults.update(overrides)
    return defaults


def create_bill_payload(account_id: str, **overrides) -> dict:
    defaults = {"account_id": account_id}
    defaults.update(overrides)
    return defaults


def record_payment_payload(**overrides) -> dict:
    defaults = {
        "paid_amount_cents": 0,
        "paid_at": DEFAULTS["PAID_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_dnfb_sweep_payload(**overrides) -> dict:
    defaults = {"threshold_days": DEFAULTS["THRESHOLD_DAYS"]}
    defaults.update(overrides)
    return defaults


def create_audit_payload(subject_coder_id: str, **overrides) -> dict:
    defaults = {
        "subject_coder_id": subject_coder_id,
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "sample_size": DEFAULTS["SAMPLE_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(coded_case_id: str, **overrides) -> dict:
    defaults = {
        "coded_case_id": coded_case_id,
        "finding_type": "POA_CORRECTION",
    }
    defaults.update(overrides)
    return defaults


def resolve_finding_payload(**overrides) -> dict:
    defaults = {"resolution": DEFAULTS["RESOLUTION"]}
    defaults.update(overrides)
    return defaults


def create_review_payload(**overrides) -> dict:
    defaults = {"payer_ref": "PR-DEFAULT", "claimed_delta_cents": -200000}
    defaults.update(overrides)
    return defaults


def create_rebill_request_payload(review_id: str, delta_cents: int, expected_bill_version: int, **overrides) -> dict:
    defaults = {
        "review_id": review_id,
        "delta_cents": delta_cents,
        "expected_bill_version": expected_bill_version,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}

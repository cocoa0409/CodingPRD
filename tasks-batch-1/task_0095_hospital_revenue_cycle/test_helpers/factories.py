"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional input fields (those with a PRD default) are
omitted by default and only included when explicitly overridden.
"""

DEFAULTS = {
    "PAYER_NAME": "Acme Health",
    "PAYER_TYPE": "COMMERCIAL",
    "PATIENT_NAME": "Dana Reyes",
    "DOB": "1980-04-01",
    "MEMBER_NUMBER": "M-001",
    "PLAN_YEAR": 2026,
    "DEDUCTIBLE_CENTS": 100000,
    "COINSURANCE_PCT": 0.20,
    "OOP_MAX_CENTS": 500000,
    "ADMISSION_AT": "2026-03-01T09:00:00Z",
    "CPT_CODE": "99285",
    "UNIT_PRICE_CENTS": 300000,
    "PRINCIPAL_ICD10": "E11.65",
}


def create_payer_payload(**overrides) -> dict:
    """Required: name, payer_type. Optional (have PRD defaults):
    timely_filing_days, appeal_window_days, active."""
    payload = {
        "name": DEFAULTS["PAYER_NAME"],
        "payer_type": DEFAULTS["PAYER_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    """Required: full_name, date_of_birth. Optional: financial_class (default INSURED)."""
    payload = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
    }
    payload.update(overrides)
    return payload


def create_policy_payload(patient_id, payer_id, **overrides) -> dict:
    """Required: patient_id, payer_id, member_number, plan_year, deductible_cents,
    coinsurance_pct, oop_max_cents."""
    payload = {
        "patient_id": patient_id,
        "payer_id": payer_id,
        "member_number": DEFAULTS["MEMBER_NUMBER"],
        "plan_year": DEFAULTS["PLAN_YEAR"],
        "deductible_cents": DEFAULTS["DEDUCTIBLE_CENTS"],
        "coinsurance_pct": DEFAULTS["COINSURANCE_PCT"],
        "oop_max_cents": DEFAULTS["OOP_MAX_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_encounter_payload(patient_id, **overrides) -> dict:
    """Required: patient_id, admission_at. Optional: policy_id (null for self-pay)."""
    payload = {
        "patient_id": patient_id,
        "admission_at": DEFAULTS["ADMISSION_AT"],
    }
    payload.update(overrides)
    return payload


def create_charge_payload(**overrides) -> dict:
    """Required: cpt_code, units, unit_price_cents."""
    payload = {
        "cpt_code": DEFAULTS["CPT_CODE"],
        "units": 1,
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_coding_payload(**overrides) -> dict:
    """Required: principal_icd10. Optional: secondary_icd10 (default empty list)."""
    payload = {
        "principal_icd10": DEFAULTS["PRINCIPAL_ICD10"],
    }
    payload.update(overrides)
    return payload


def submit_claim_payload(payer_id, expected_encounter_version, **overrides) -> dict:
    """Required: payer_id, expected_encounter_version."""
    payload = {
        "payer_id": payer_id,
        "expected_encounter_version": expected_encounter_version,
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(allowed_amount_cents, claim_lines, **overrides) -> dict:
    """Required: allowed_amount_cents, claim_lines (list of {cpt_code, line_allowed_cents})."""
    payload = {
        "allowed_amount_cents": allowed_amount_cents,
        "claim_lines": claim_lines,
    }
    payload.update(overrides)
    return payload


def single_line(cpt_code, line_allowed_cents) -> list:
    """Convenience: a one-line claim_lines list summing to line_allowed_cents."""
    return [{"cpt_code": cpt_code, "line_allowed_cents": line_allowed_cents}]


def deny_payload(denial_reason, **overrides) -> dict:
    """Required: denial_reason."""
    payload = {"denial_reason": denial_reason}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, method="CARD", **overrides) -> dict:
    """Required: amount_cents, method."""
    payload = {"amount_cents": amount_cents, "method": method}
    payload.update(overrides)
    return payload


def write_off_payload(expected_patient_statement_version, reason="BAD_DEBT", **overrides) -> dict:
    """Required: reason, expected_patient_statement_version."""
    payload = {
        "reason": reason,
        "expected_patient_statement_version": expected_patient_statement_version,
    }
    payload.update(overrides)
    return payload

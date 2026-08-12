"""Payload factories — one per creatable resource, client-supplied fields only (PRD §3)."""

DEFAULTS = {
    "FULL_NAME": "Test Person",
    "PROVIDER_NAME": "Dr Test",
    "PROVIDER_TYPE": "CLINICIAN",
    "VACCINE_CODE": "MMR",
    "REQUIRED_DOSES": 2,
    "MIN_INTERVAL_DAYS": 28,
    "DEADLINE_DATE": "2026-08-01",
    "GRACE_PERIOD_DAYS": 0,
    "COVERAGE_START": "2026-04-01T00:00:00Z",
    "COVERAGE_END": "2027-03-31T00:00:00Z",
    "TERM_CODE": "SP26",
    "TERM_BUDGET_CENTS": 100000,
    "TERM_END_DATE": "2026-08-31",
    "MEDICATION_NAME": "Test Drug",
    "HOSPITAL_NAME": "General Hospital",
    "REFERRAL_REASON": "observation",
    "TEST_CODE": "CBC",
    "RESULT_SUMMARY": "positive",
    "EXEMPTION_REASON": "medical contraindication",
}


def create_student_payload(**overrides) -> dict:
    """PRD §3.1: external_ref + full_name required; enrollment_status optional."""
    defaults = {
        "external_ref": "S-0001",
        "full_name": DEFAULTS["FULL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(student_id, expected_student_version, **overrides) -> dict:
    """PRD §3.2 / §2.8: policy creation carries the OCC field expected_student_version."""
    defaults = {
        "student_id": student_id,
        "payer_type": "EXTERNAL",
        "policy_number": "POL-1",
        "coverage_start": DEFAULTS["COVERAGE_START"],
        "coverage_end": DEFAULTS["COVERAGE_END"],
        "copay_cents": 0,
        "deductible_cents": 0,
        "coinsurance_pct": 0.0,
        "expected_student_version": expected_student_version,
    }
    defaults.update(overrides)
    return defaults


def create_immunization_requirement_payload(**overrides) -> dict:
    """PRD §3.3: requirement definition fields."""
    defaults = {
        "vaccine_code": DEFAULTS["VACCINE_CODE"],
        "required_doses": DEFAULTS["REQUIRED_DOSES"],
        "min_interval_days": DEFAULTS["MIN_INTERVAL_DAYS"],
        "deadline_date": DEFAULTS["DEADLINE_DATE"],
        "grace_period_days": DEFAULTS["GRACE_PERIOD_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_immunization_record_payload(student_id, requirement_id, **overrides) -> dict:
    defaults = {"student_id": student_id, "requirement_id": requirement_id}
    defaults.update(overrides)
    return defaults


def record_dose_payload(dose_date, expected_record_version, **overrides) -> dict:
    """PRD §3.3 / §2.8: dose recording carries dose_date + expected_record_version."""
    defaults = {
        "dose_date": dose_date,
        "expected_record_version": expected_record_version,
    }
    defaults.update(overrides)
    return defaults


def exempt_record_payload(exemption_reason=None, **overrides) -> dict:
    defaults = {
        "exemption_reason": exemption_reason or DEFAULTS["EXEMPTION_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PROVIDER_NAME"],
        "provider_type": DEFAULTS["PROVIDER_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_on_call_shift_payload(provider_id, shift_start, shift_end, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(student_id, provider_id, visit_type, start, end, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "provider_id": provider_id,
        "visit_type": visit_type,
        "scheduled_start": start,
        "scheduled_end": end,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(medication_stock_id, quantity, **overrides) -> dict:
    defaults = {
        "medication_stock_id": medication_stock_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def dispense_payload(quantity, **overrides) -> dict:
    defaults = {"quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_medication_stock_payload(**overrides) -> dict:
    defaults = {
        "medication_code": "MED-1",
        "medication_name": DEFAULTS["MEDICATION_NAME"],
        "initial_on_hand": 100,
        "reorder_threshold": 0,
    }
    defaults.update(overrides)
    return defaults


def restock_payload(quantity, **overrides) -> dict:
    defaults = {"quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_lab_order_payload(test_code=None, reportable_disease_code=None, **overrides) -> dict:
    """PRD §3.7: reportable_disease_code is optional on the order."""
    defaults = {"test_code": test_code or DEFAULTS["TEST_CODE"]}
    if reportable_disease_code is not None:
        defaults["reportable_disease_code"] = reportable_disease_code
    defaults.update(overrides)
    return defaults


def result_lab_order_payload(result_summary=None, flags_reportable=False, **overrides) -> dict:
    defaults = {
        "result_summary": result_summary or DEFAULTS["RESULT_SUMMARY"],
        "flags_reportable": flags_reportable,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(lines, **overrides) -> dict:
    """PRD §3.8: lines are [{service_category, charge_cents}] in request order."""
    defaults = {"lines": lines}
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, method="CARD", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "method": method}
    defaults.update(overrides)
    return defaults


def create_referral_payload(hospital_name=None, reason=None, **overrides) -> dict:
    defaults = {
        "hospital_name": hospital_name or DEFAULTS["HOSPITAL_NAME"],
        "reason": reason or DEFAULTS["REFERRAL_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_health_fee_pool_payload(**overrides) -> dict:
    defaults = {
        "term_code": DEFAULTS["TERM_CODE"],
        "budget_cents": DEFAULTS["TERM_BUDGET_CENTS"],
        "term_end_date": DEFAULTS["TERM_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}

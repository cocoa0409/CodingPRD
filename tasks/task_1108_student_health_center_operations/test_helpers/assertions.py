"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    """PRD §2.5: id (UUID), created_at/updated_at (ISO 8601), version (int)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}: created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}: updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}: version must be a 1-based integer"
    )


def assert_timestamp_prefix(actual: str, expected_prefix: str, label: str = "timestamp"):
    """Assert a logical-clock-stamped timestamp matches the expected UTC prefix.

    Prefix comparison keeps the check robust to fractional-second rendering
    while still pinning the exact logical second the PRD requires.
    """
    assert isinstance(actual, str), f"{label}: expected string, got {type(actual)}"
    assert actual.startswith(expected_prefix), (
        f"{label}: expected {actual!r} to start with {expected_prefix!r}"
    )


def assert_student(data: dict):
    _assert_common_fields(data, "Student")
    assert isinstance(data.get("external_ref"), str) and data["external_ref"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("enrollment_status") in ("ENROLLED", "LEAVE", "WITHDRAWN")
    assert data.get("compliance_posture") in (
        "CLEAR",
        "PROVISIONAL_HOLD",
        "REGISTRATION_HOLD",
    )
    assert isinstance(data.get("active_hold_types"), list)
    for hold in data["active_hold_types"]:
        assert hold in ("IMMUNIZATION", "FINANCIAL")


def assert_insurance_policy(data: dict):
    _assert_common_fields(data, "InsurancePolicy")
    assert isinstance(data.get("student_id"), str)
    assert data.get("payer_type") in ("STUDENT_PLAN", "EXTERNAL")
    assert isinstance(data.get("policy_number"), str)
    assert isinstance(data.get("copay_cents"), int) and data["copay_cents"] >= 0
    assert isinstance(data.get("deductible_cents"), int)
    assert isinstance(data.get("deductible_met_cents"), int)
    assert 0 <= data.get("coinsurance_pct", -1) <= 1
    assert data.get("status") in ("UNVERIFIED", "VERIFIED", "SUPERSEDED", "EXPIRED")


def assert_immunization_requirement(data: dict):
    _assert_common_fields(data, "ImmunizationRequirement")
    assert isinstance(data.get("vaccine_code"), str) and data["vaccine_code"]
    assert 1 <= data.get("required_doses", 0) <= 3
    assert data.get("min_interval_days", -1) >= 0
    assert isinstance(data.get("deadline_date"), str)
    assert data.get("grace_period_days", -1) >= 0


def assert_immunization_record(data: dict):
    _assert_common_fields(data, "ImmunizationRecord")
    assert isinstance(data.get("student_id"), str)
    assert isinstance(data.get("requirement_id"), str)
    assert isinstance(data.get("doses_received"), int) and data["doses_received"] >= 0
    assert isinstance(data.get("dose_dates"), list)
    assert data.get("status") in (
        "PENDING",
        "GRACE",
        "OVERDUE",
        "IN_COMPLIANCE",
        "EXEMPTED",
    )


def assert_provider(data: dict):
    _assert_common_fields(data, "Provider")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("provider_type") in ("CLINICIAN", "NURSE")
    assert isinstance(data.get("active"), bool)


def assert_on_call_shift(data: dict):
    _assert_common_fields(data, "OnCallShift")
    assert isinstance(data.get("provider_id"), str)
    assert is_iso8601_timestamp(data.get("shift_start", ""))
    assert is_iso8601_timestamp(data.get("shift_end", ""))


def assert_appointment(data: dict):
    _assert_common_fields(data, "Appointment")
    assert isinstance(data.get("student_id"), str)
    assert isinstance(data.get("provider_id"), str)
    assert data.get("visit_type") in (
        "PRIMARY_URGENT",
        "SAME_DAY_TRIAGE",
        "FOLLOW_UP",
        "SPORTS_PHYSICAL",
        "TRAVEL_CLINIC",
    )
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data.get("status") in (
        "BOOKED",
        "CHECKED_IN",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    )
    assert data.get("cancel_reason") in ("NONE", "HOLD", "CLIENT")


def assert_encounter(data: dict):
    _assert_common_fields(data, "Encounter")
    assert isinstance(data.get("appointment_id"), str)
    assert isinstance(data.get("student_id"), str)
    assert isinstance(data.get("provider_id"), str)
    assert data.get("status") in ("OPEN", "CLOSED")
    assert data.get("clearance_outcome") in ("NONE", "CLEARED", "NOT_CLEARED")
    assert isinstance(data.get("fee_covered"), bool)


def assert_prescription(data: dict):
    _assert_common_fields(data, "Prescription")
    assert isinstance(data.get("encounter_id"), str)
    assert isinstance(data.get("medication_stock_id"), str)
    assert isinstance(data.get("quantity_prescribed"), int)
    assert data["quantity_prescribed"] > 0
    assert isinstance(data.get("quantity_dispensed"), int)
    assert 0 <= data["quantity_dispensed"] <= data["quantity_prescribed"]
    assert data.get("status") in (
        "WRITTEN",
        "PARTIALLY_DISPENSED",
        "DISPENSED",
        "CANCELLED",
    )


def assert_medication_stock(data: dict):
    _assert_common_fields(data, "MedicationStock")
    assert isinstance(data.get("medication_code"), str) and data["medication_code"]
    assert isinstance(data.get("medication_name"), str)
    assert isinstance(data.get("initial_on_hand"), int) and data["initial_on_hand"] >= 0
    assert isinstance(data.get("on_hand"), int) and data["on_hand"] >= 0
    assert isinstance(data.get("reorder_threshold"), int)
    assert isinstance(data.get("needs_reorder"), bool)


def assert_lab_order(data: dict):
    _assert_common_fields(data, "LabOrder")
    assert isinstance(data.get("encounter_id"), str)
    assert isinstance(data.get("test_code"), str) and data["test_code"]
    assert data.get("status") in ("ORDERED", "SAMPLE_COLLECTED", "RESULTED", "REVIEWED")
    assert isinstance(data.get("flags_reportable"), bool)


def assert_disease_case(data: dict):
    _assert_common_fields(data, "DiseaseCase")
    assert isinstance(data.get("student_id"), str)
    assert isinstance(data.get("lab_order_id"), str)
    assert isinstance(data.get("disease_code"), str)
    assert data.get("status") in ("SUSPECTED", "CONFIRMED", "REPORTED", "RESOLVED")


def assert_outbreak_investigation(data: dict):
    _assert_common_fields(data, "OutbreakInvestigation")
    assert isinstance(data.get("disease_code"), str)
    assert data.get("status") in ("ACTIVE", "CONTAINED", "CLOSED")
    assert isinstance(data.get("opened_case_count"), int)


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert isinstance(data.get("encounter_id"), str)
    assert isinstance(data.get("student_id"), str)
    assert data.get("status") in (
        "DRAFT",
        "ISSUED",
        "PARTIALLY_PAID",
        "OVERDUE",
        "PAID",
    )
    assert data.get("variant") in ("PROVISIONAL", "FINAL")
    assert isinstance(data.get("charge_total_cents"), int)
    assert isinstance(data.get("subsidy_cents"), int)
    assert isinstance(data.get("insurer_pays_cents"), int)
    assert isinstance(data.get("patient_responsibility_cents"), int)
    assert isinstance(data.get("balance_cents"), int)


def assert_payment(data: dict):
    _assert_common_fields(data, "Payment")
    assert isinstance(data.get("invoice_id"), str)
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert data.get("method") in ("CARD", "CASH", "EXTERNAL_REMITTANCE")
    assert data.get("status") in ("POSTED", "VOIDED")


def assert_referral(data: dict):
    _assert_common_fields(data, "Referral")
    assert isinstance(data.get("encounter_id"), str)
    assert isinstance(data.get("hospital_name"), str)
    assert data.get("status") in ("INITIATED", "ACCEPTED")
    assert isinstance(data.get("after_hours"), bool)


def assert_health_fee_pool(data: dict):
    _assert_common_fields(data, "HealthFeePool")
    assert isinstance(data.get("term_code"), str)
    assert isinstance(data.get("budget_cents"), int) and data["budget_cents"] > 0
    assert isinstance(data.get("spent_cents"), int) and data["spent_cents"] >= 0
    assert data.get("status") in ("OPEN", "CLOSED")
    assert isinstance(data.get("exhausted"), bool)


def assert_invoice_money_conservation(invoice: dict, posted_payments_total: int):
    """PRD §3.8 invariant: patient responsibility == balance + posted payments."""
    assert invoice["patient_responsibility_cents"] == (
        invoice["balance_cents"] + posted_payments_total
    ), (
        "money conservation violated: "
        f"{invoice['patient_responsibility_cents']} != "
        f"{invoice['balance_cents']} + {posted_payments_total}"
    )

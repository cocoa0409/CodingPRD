"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_same_instant(actual: str, expected: str):
    """Two ISO 8601 UTC timestamps denote the same instant.

    PRD pins the instant of clock-stamped and computed fields (e.g.
    `discharged_at` "from the clock", `correction_plan_due_at` = decision +
    fourteen days) but does not pin a single string rendering for them, so
    compare parsed instants rather than raw strings.
    """
    def _parse(s):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    assert _parse(actual) == _parse(expected), (
        f"instant mismatch: expected {expected}, got {actual}"
    )


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def _assert_append_only(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_home(data: dict):
    _assert_common(data, "Home")
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["licensed_bed_capacity"], int)
    assert 2 <= data["licensed_bed_capacity"] <= 6
    assert data["status"] in ["PROVISIONAL", "LICENSED", "SUSPENDED", "CLOSED"]
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0
    assert isinstance(data["current_census"], int) and data["current_census"] >= 0


def assert_bed(data: dict):
    _assert_common(data, "Bed")
    assert isinstance(data["home_id"], str)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["medicaid_certified"], bool)
    assert data["status"] in ["AVAILABLE", "HELD", "OCCUPIED", "OUT_OF_SERVICE"]


def assert_resident(data: dict):
    _assert_common(data, "Resident")
    assert isinstance(data["home_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["payer_type"] in ["PRIVATE_PAY", "MEDICAID"]
    assert data["status"] in ["PROSPECT", "APPLICANT", "ADMITTED", "DISCHARGED"]


def assert_assessment(data: dict):
    _assert_common(data, "Assessment")
    assert isinstance(data["resident_id"], str)
    assert is_iso8601_timestamp(data.get("assessed_at", ""))
    assert 0 <= data["nursing_hours_per_week"] <= 40
    assert 0 <= data["adl_dependency_score"] <= 6
    assert isinstance(data["care_plan"], dict)
    assert data["status"] in ["DRAFT", "FINALIZED", "SUPERSEDED"]


def assert_admission(data: dict):
    _assert_common(data, "Admission")
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["bed_id"], str)
    assert isinstance(data["assessment_id"], str)
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED", "COMPLETED", "CANCELLED"]


def assert_medication_order(data: dict):
    _assert_common(data, "MedicationOrder")
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["drug_name"], str) and data["drug_name"]
    assert isinstance(data["dose"], str) and data["dose"]
    assert isinstance(data["schedule_times"], list)
    assert 1 <= len(data["schedule_times"]) <= 6
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_medication_log(data: dict):
    _assert_append_only(data, "MedicationLog")
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["order_id"], str)
    assert is_iso8601_timestamp(data.get("administered_at", ""))
    assert data["outcome"] in ["GIVEN", "REFUSED", "HELD", "SELF_ADMINISTERED"]
    assert isinstance(data["caregiver_id"], str)


def assert_adl_log(data: dict):
    _assert_append_only(data, "ADLLog")
    assert isinstance(data["resident_id"], str)
    assert data["adl_type"] in ["BATHING", "DRESSING", "GROOMING", "TOILETING",
                                "TRANSFERRING", "EATING"]
    assert data["assistance_level"] in ["INDEPENDENT", "SUPERVISION", "PARTIAL", "FULL"]
    assert is_iso8601_timestamp(data.get("performed_at", ""))
    assert isinstance(data["caregiver_id"], str)


def assert_caregiver(data: dict):
    _assert_common(data, "Caregiver")
    assert isinstance(data["home_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["credential_id"], str) and data["credential_id"]
    assert isinstance(data["awake_overnight_qualified"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_shift(data: dict):
    _assert_common(data, "Shift")
    assert isinstance(data["home_id"], str)
    assert isinstance(data["caregiver_id"], str)
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["status"] in ["SCHEDULED", "CANCELLED"]


def assert_incident(data: dict):
    _assert_common(data, "Incident")
    assert isinstance(data["resident_id"], str)
    assert data["incident_type"] in ["FALL", "MED_ERROR", "ELOPEMENT",
                                     "ABUSE_ALLEGATION", "INJURY"]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert data["status"] in ["REPORTED", "UNDER_REVIEW", "RESOLVED", "CLOSED"]


def assert_compliance_case(data: dict):
    _assert_common(data, "ComplianceCase")
    assert isinstance(data["home_id"], str)
    assert isinstance(data["incident_id"], str)
    assert data["status"] in ["OPEN", "SUBSTANTIATED", "UNFOUNDED", "CLOSED"]


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert isinstance(data["resident_id"], str)
    assert data["payer_type_snapshot"] in ["PRIVATE_PAY", "MEDICAID"]
    assert isinstance(data["line_items"], list)
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] + data["late_fee_cents"]
    assert data["status"] in ["DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "VOID"]


def assert_payment(data: dict):
    _assert_append_only(data, "Payment")
    assert isinstance(data["resident_id"], str)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ["CASH", "CHECK", "ACH", "CARD", "MEDICAID_REMIT"]
    assert is_iso8601_timestamp(data.get("received_at", ""))


def assert_rate_schedule(data: dict):
    _assert_common(data, "RateSchedule")
    assert isinstance(data["home_id"], str)
    assert data["payer_type"] in ["PRIVATE_PAY", "MEDICAID"]
    assert data["room_and_board_daily_cents"] > 0
    assert data["care_low_daily_cents"] >= 0
    assert data["care_medium_daily_cents"] >= data["care_low_daily_cents"]
    assert data["care_high_daily_cents"] >= data["care_medium_daily_cents"]


def assert_discharge_record(data: dict):
    _assert_append_only(data, "DischargeRecord")
    assert isinstance(data["resident_id"], str)
    assert data["reason"] in ["VOLUNTARY", "HOSPITALIZATION", "LEVEL_OF_CARE_EXCEEDED",
                              "NONPAYMENT", "DECEASED"]
    assert isinstance(data["notice_days"], int) and data["notice_days"] >= 0
    assert is_iso8601_timestamp(data.get("discharged_at", ""))
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 0


def assert_home_counters(home: dict, expected_census: int, expected_open_cases: int):
    """Derived-counter invariant: both home counters match the expected counts."""
    assert home["current_census"] == expected_census, (
        f"current_census drifted: expected {expected_census}, got {home['current_census']}"
    )
    assert home["open_case_count"] == expected_open_cases, (
        f"open_case_count drifted: expected {expected_open_cases}, "
        f"got {home['open_case_count']}"
    )

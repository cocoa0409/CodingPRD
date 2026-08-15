"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Per the PRD common-resource-properties
section, every resource carries id, created_at, updated_at, and version.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_timestamp_equals(actual: str, expected: str):
    """Compare two ISO 8601 timestamps by instant, tolerant of fractional-digit
    rendering differences (e.g. trailing .000Z)."""
    assert _parse_ts(actual) == _parse_ts(expected), (
        f"Expected timestamp {expected}, got {actual}"
    )


def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_payer_policy(data: dict):
    assert_common_fields(data)
    assert isinstance(data["payer_code"], str) and data["payer_code"]
    assert isinstance(data["drug_code"], str) and data["drug_code"]
    assert isinstance(data["regimen_name"], str) and data["regimen_name"]
    assert data["benefit_channel"] in ("MEDICAL", "PHARMACY", "EITHER")
    assert isinstance(data["requires_prior_auth"], bool)
    assert isinstance(data["buy_and_bill_required"], bool)
    assert isinstance(data["validity_days"], int)
    assert isinstance(data["pharmacy_validity_days"], int)
    assert isinstance(data["max_course_days"], int)
    assert isinstance(data["max_dose_mg"], int)
    assert isinstance(data["allowed_amount_known"], bool)
    assert data["site_policy"] in ("NO_STEERING", "STEER_TO_HOME", "STEER_TO_OFFICE")
    for field in ("deductible_cents", "oop_max_cents", "prepay_limit_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_patient(data: dict):
    assert_common_fields(data)
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["diagnosis_code"], str) and data["diagnosis_code"]
    assert isinstance(data["payer_code"], str) and data["payer_code"]
    assert isinstance(data["deductible_remaining_cents"], int)
    assert isinstance(data["oop_remaining_cents"], int)
    assert isinstance(data["rural_resident"], bool)
    assert isinstance(data["travel_minutes_to_hospital"], int)


def assert_authorization_request(data: dict):
    assert_common_fields(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["policy_id"], str)
    assert data["requested_site_type"] in ("HOME", "OFFICE", "HOSPITAL_OUTPATIENT")
    assert isinstance(data["requested_dose_mg"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "PENDED", "APPROVED", "DENIED",
        "SUPERSEDED", "EXPIRED", "DENIED_CLOSED",
    )
    assert isinstance(data["created_by_user_id"], str)


def assert_criteria_submission(data: dict):
    assert_common_fields(data)
    assert isinstance(data["authorization_request_id"], str)
    assert isinstance(data["criterion_code"], str) and data["criterion_code"]
    assert isinstance(data["response_value"], str)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["created_by_user_id"], str)


def assert_appeal(data: dict):
    assert_common_fields(data)
    assert isinstance(data["authorization_request_id"], str)
    assert isinstance(data["reason"], str)
    assert data["status"] in (
        "LEVEL_1", "LEVEL_1_DECIDED", "LEVEL_2", "LEVEL_2_DECIDED",
        "EXTERNAL_REVIEW", "CLOSED_UPHELD", "CLOSED_OVERTURNED",
    )


def assert_peer_to_peer_review(data: dict):
    assert_common_fields(data)
    assert isinstance(data["appeal_id"], str)
    assert isinstance(data["reviewer_user_id"], str)
    assert data["status"] in ("SCHEDULED", "NO_SHOW", "COMPLETED")
    assert isinstance(data["reschedule_count"], int)
    assert data.get("outcome") in (None, "UPHOLD", "OVERTURN")


def assert_site_of_care_determination(data: dict):
    assert_common_fields(data)
    assert isinstance(data["authorization_request_id"], str)
    for field in ("home_allowed_cents", "hospital_allowed_cents",
                  "home_billed_cents", "hospital_billed_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["score_variant"] in ("COST_RATIO", "TRAVEL_BURDEN")
    assert isinstance(data["steer_score"], (int, float))
    assert data["recommended_site_type"] in ("HOME", "OFFICE", "HOSPITAL_OUTPATIENT")
    assert isinstance(data["steered"], bool)


def assert_benefit_investigation(data: dict):
    assert_common_fields(data)
    assert isinstance(data["authorization_request_id"], str)
    assert data["status"] in ("INITIATED", "VERIFIED")
    assert data.get("determined_channel") in (None, "MEDICAL", "PHARMACY")
    assert data.get("routing") in (None, "BUY_AND_BILL", "SPECIALTY_PHARMACY")


def assert_financial_clearance(data: dict):
    assert_common_fields(data)
    assert isinstance(data["authorization_request_id"], str)
    assert data["method"] in ("ACCUMULATOR_METHOD", "BILLED_CHARGES_METHOD")
    assert data["status"] in ("ESTIMATED", "CLEARED", "ON_HOLD")
    assert isinstance(data["estimated_patient_responsibility_cents"], int)
    assert data["estimated_patient_responsibility_cents"] >= 0
    assert isinstance(data["estimated_by_user_id"], str)


def assert_line_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["financial_clearance_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["allowed_amount_cents"], int)
    assert isinstance(data["billed_charges_cents"], int)
    assert isinstance(data["patient_share_cents"], int)
    assert data["patient_share_cents"] >= 0
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_infusion_chair(data: dict):
    assert_common_fields(data)
    assert data["site_type"] in ("HOME", "OFFICE", "HOSPITAL_OUTPATIENT")
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["turnover_buffer_minutes"], int)


def assert_infusion_appointment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["authorization_request_id"], str)
    assert isinstance(data["chair_id"], str)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in (
        "SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED", "MISSED",
    )


def assert_dose_change_request(data: dict):
    assert_common_fields(data)
    assert isinstance(data["authorization_request_id"], str)
    assert isinstance(data["new_dose_mg"], int)
    assert isinstance(data["delta_pct"], (int, float))
    assert isinstance(data["reauth_required"], bool)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def chair_occupied_count(appointments: list) -> int:
    """The conserved chair-occupancy quantity (PRD chair-scheduling section):
    the number of the chair's appointments in SCHEDULED, CONFIRMED, or
    COMPLETED status."""
    return sum(
        1
        for appt in appointments
        if appt.get("status") in ("SCHEDULED", "CONFIRMED", "COMPLETED")
    )


def assert_clearance_invariants(clearance: dict, patient: dict):
    """The estimate never exceeds the patient's out-of-pocket remaining."""
    assert 0 <= clearance["estimated_patient_responsibility_cents"]
    assert (
        clearance["estimated_patient_responsibility_cents"]
        <= patient["oop_remaining_cents"]
    )

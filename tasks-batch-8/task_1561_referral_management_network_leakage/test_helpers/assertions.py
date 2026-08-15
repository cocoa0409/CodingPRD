"""Entity assertions and domain invariant checkers.

Timestamps are compared as parsed instants: the PRD pins the clock arithmetic
(§2.4, §3.3, §3.4) to the second, and also describes created_at as carrying
three fractional digits, so equality is judged on the instant, not the string.
"""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str), f"Expected timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 timestamps denote the same instant (to the second)."""
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601 UTC: {actual!r}"
    a = _parse_instant(actual)
    b = _parse_instant(expected_iso)
    delta = abs((a - b).total_seconds())
    assert delta < 0.001, f"{label}: expected instant {expected_iso}, got {actual}"


def assert_rate(actual, expected: float, label: str = "rate"):
    """Assert a 4-decimal round-half-up rate equals the expected value."""
    assert isinstance(actual, (int, float)), f"{label} must be numeric, got {actual!r}"
    assert actual == pytest.approx(expected, abs=1e-9), (
        f"{label}: expected {expected} (4dp round-half-up), got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer: {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only resource must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "append-only resource must not carry version (PRD §2.4)"


def assert_referring_provider(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["specialty"], str) and data["specialty"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["leakage_event_count"], int) and data["leakage_event_count"] >= 0
    assert isinstance(data["watch_flag"], bool)


def assert_specialist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["npi"], str) and data["npi"]
    assert data["specialty"] in (
        "CARDIOLOGY", "ORTHOPEDICS", "NEUROLOGY", "DERMATOLOGY", "ENDOCRINOLOGY"
    )
    assert isinstance(data["base_region"], str)
    assert isinstance(data["weekly_capacity"], int) and data["weekly_capacity"] >= 1
    assert isinstance(data["accepts_new_patients"], bool)
    assert isinstance(data["accepts_urgent"], bool)
    assert isinstance(data["booked_appointments_count"], int) and data["booked_appointments_count"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_insurance_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["payer_name"], str) and data["payer_name"]
    assert isinstance(data["payer_mix_factor"], (int, float)) and data["payer_mix_factor"] > 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["region"], str)
    assert isinstance(data["insurance_plan_id"], str) and data["insurance_plan_id"]
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert data["status"] in ("ACTIVE", "OUTREACH_REQUIRED")
    assert isinstance(data["no_show_risk_confirmed"], (int, float))
    assert isinstance(data["no_show_risk_forward"], (int, float))
    assert 0 <= data["no_show_risk_confirmed"] <= 100
    assert 0 <= data["no_show_risk_forward"] <= 100


def assert_participation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["specialist_id"], str) and data["specialist_id"]
    assert isinstance(data["insurance_plan_id"], str) and data["insurance_plan_id"]
    assert data["tier"] in ("PREFERRED", "STANDARD")
    assert isinstance(data["effective_from"], str) and data["effective_from"]
    assert isinstance(data["effective_to"], str) and data["effective_to"]
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_auth_rule(data: dict):
    _assert_common_fields(data)
    assert data["specialty"] in (
        "CARDIOLOGY", "ORTHOPEDICS", "NEUROLOGY", "DERMATOLOGY", "ENDOCRINOLOGY"
    )
    assert isinstance(data["insurance_plan_id"], str) and data["insurance_plan_id"]
    assert isinstance(data["requires_auth"], bool)
    assert isinstance(data["auth_validity_days"], int) and data["auth_validity_days"] >= 1
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["referring_provider_id"], str) and data["referring_provider_id"]
    assert isinstance(data["patient_id"], str) and data["patient_id"]
    assert data["specialty"] in (
        "CARDIOLOGY", "ORTHOPEDICS", "NEUROLOGY", "DERMATOLOGY", "ENDOCRINOLOGY"
    )
    assert isinstance(data["diagnosis_code"], str)
    assert data["urgency"] in ("STAT", "URGENT", "ROUTINE")
    assert data.get("insurance_plan_id") is None or isinstance(data["insurance_plan_id"], str)
    assert isinstance(data["in_network_preference"], bool)
    assert isinstance(data["patient_choice_documented"], bool)
    assert data["patient_choice_type"] in (
        "NONE", "IN_NETWORK_PREFERRED", "OUT_OF_NETWORK_PATIENT_REQUEST", "OUT_OF_NETWORK_CAPACITY"
    )
    assert isinstance(data["patient_choice_note"], str)
    assert data.get("target_specialist_id") is None or isinstance(data["target_specialist_id"], str)
    assert data.get("match_score") is None or isinstance(data["match_score"], int)
    assert data["status"] in (
        "PENDING_TRIAGE", "NEEDS_INFO", "REJECTED", "ACCEPTED", "SCHEDULED",
        "VISIT_COMPLETED", "PENDING_VERIFICATION", "CLOSED", "EXPIRED", "CANCELLED",
    )
    assert data["auth_status"] in (
        "NOT_EVALUATED", "NOT_REQUIRED", "AUTH_REQUIRED", "AUTH_PENDING",
        "AUTH_OBTAINED", "AUTH_DENIED", "AUTH_EXPIRED",
    )
    assert data.get("triaged_at") is None or is_iso8601_timestamp(data["triaged_at"])
    assert data.get("sla_due_at") is None or is_iso8601_timestamp(data["sla_due_at"])
    assert isinstance(data["age_days"], int) and data["age_days"] >= 0
    assert isinstance(data["ever_scheduled"], bool)
    assert isinstance(data["escalation_flag"], bool)
    assert isinstance(data["leaked"], bool)
    assert isinstance(data["out_of_network"], bool)
    assert data.get("cancel_reason") is None or data["cancel_reason"] in (
        "PATIENT_WENT_OUT_OF_NETWORK", "PATIENT_DECLINED", "CLINICAL_DUPLICATE", "OTHER"
    )
    assert isinstance(data["needs_info_note"], str)


def assert_authorization_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["referral_id"], str) and data["referral_id"]
    assert isinstance(data["auth_number"], str)
    assert is_iso8601_timestamp(data["obtained_at"])
    assert is_iso8601_timestamp(data["expires_on"])
    assert data["status"] in ("ACTIVE", "EXPIRED", "CONSUMED")


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["referral_id"], str) and data["referral_id"]
    assert isinstance(data["specialist_id"], str) and data["specialist_id"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in (
        "SCHEDULED", "CONFIRMED", "COMPLETED", "NO_SHOW", "EXCUSED", "CANCELLED"
    )
    assert data.get("confirmation_channel") is None or data["confirmation_channel"] in (
        "PHONE", "PORTAL", "LETTER"
    )
    assert data.get("confirmed_at") is None or is_iso8601_timestamp(data["confirmed_at"])
    assert data.get("completed_at") is None or is_iso8601_timestamp(data["completed_at"])
    assert isinstance(data["superseded"], bool)
    assert isinstance(data["excuse_reason"], str)
    assert isinstance(data["scheduled_by_user_id"], str) and data["scheduled_by_user_id"]


def assert_consult_note(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["referral_id"], str) and data["referral_id"]
    assert isinstance(data["appointment_id"], str) and data["appointment_id"]
    assert isinstance(data["author_specialist_id"], str) and data["author_specialist_id"]
    assert isinstance(data["findings_summary"], str)
    assert isinstance(data["follow_up_recommended"], bool)
    assert isinstance(data["note_sequence"], int) and data["note_sequence"] >= 1
    assert isinstance(data["returned_within_sla"], bool)


def assert_loop_closure(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["referral_id"], str) and data["referral_id"]
    assert data["outcome"] in ("VERIFIED_CLOSED", "REOPENED")
    assert isinstance(data["verification_note"], str)
    assert isinstance(data["verifier_user_id"], str) and data["verifier_user_id"]


def assert_leakage_record(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["referral_id"], str) and data["referral_id"]
    assert data["category"] in (
        "EXPIRED_UNRESOLVED", "PATIENT_CHOICE_OUT_OF_NETWORK", "CAPACITY_OUT_OF_NETWORK"
    )
    assert isinstance(data["attributed_referring_provider_id"], str) and data[
        "attributed_referring_provider_id"
    ]
    assert isinstance(data["estimated_value_cents"], int) and data["estimated_value_cents"] >= 0


def assert_period_snapshot(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["referring_provider_id"], str) and data["referring_provider_id"]
    assert isinstance(data["period_start"], str) and data["period_start"]
    assert isinstance(data["period_end"], str) and data["period_end"]
    assert isinstance(data["intake_count"], int) and data["intake_count"] >= 0
    assert isinstance(data["completed_count"], int) and data["completed_count"] >= 0
    assert isinstance(data["scheduled_basis_count"], int) and data["scheduled_basis_count"] >= 0
    assert isinstance(data["leaked_count"], int) and data["leaked_count"] >= 0
    for key in ("conversion_rate_intake", "conversion_rate_scheduled", "leakage_rate"):
        assert isinstance(data[key], (int, float)), f"{key} must be numeric"
        assert 0 <= data[key] <= 1, f"{key} must be within [0, 1]"
    assert isinstance(data["estimated_leakage_exposure_cents"], int)
    assert data["estimated_leakage_exposure_cents"] >= 0
    assert is_iso8601_timestamp(data["closed_at"])


def assert_patient_strike_ledger(patient: dict, appointments_of_patient: list):
    """Invariant: no_show_strikes == count of the patient's NO_SHOW appointments."""
    expected = sum(1 for a in appointments_of_patient if a.get("status") == "NO_SHOW")
    assert patient["no_show_strikes"] == expected, (
        f"Strike ledger drift: patient.no_show_strikes == {patient['no_show_strikes']} "
        f"but {expected} appointments are NO_SHOW"
    )


def assert_booked_count_reconciles(specialist: dict, appointments_of_specialist: list):
    """Invariant: booked_appointments_count == appointments in SCHEDULED or CONFIRMED."""
    expected = sum(
        1 for a in appointments_of_specialist if a.get("status") in ("SCHEDULED", "CONFIRMED")
    )
    assert specialist["booked_appointments_count"] == expected, (
        f"Slot ledger drift: booked_appointments_count == "
        f"{specialist['booked_appointments_count']} but {expected} appointments are active"
    )

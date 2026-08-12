"""Entity assertions and domain invariant checkers.

Each assert_* validates the response shape of one entity against the fields
the PRD enumerates. MedAdminEvent deliberately omits updated_at / version
(the single append-only exception in the PRD's common-fields rule).
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _parse_instant(s: str) -> datetime:
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 timestamps denote the same instant.

    The PRD pins instant arithmetic for computed timestamps (e.g.
    `report_due_at` = `discovered_at` + severity window; `review_due_at` =
    `approved_at` + 180/365d; adherence `window_start` = `as_of` - 30d) but
    pins the three-fractional-digit lexical format only for `created_at` /
    `updated_at` (PRD 2.4) and `api_request_timestamp` (PRD 2.2). Equality is
    therefore judged on the instant, not the lexical form.
    """
    assert is_iso8601_timestamp(actual), (
        f"{label} must be an ISO 8601 UTC timestamp, got {actual!r}"
    )
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_agency(data: dict):
    _assert_common(data, "ProviderAgency")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["day_staff_ratio"], int) and data["day_staff_ratio"] > 0
    assert isinstance(data["night_staff_ratio"], int) and data["night_staff_ratio"] > 0
    assert isinstance(data["evv_grace_minutes"], int)
    assert isinstance(data["cash_collected_cents"], int)
    assert isinstance(data["recoupment_balance_cents"], int)
    assert isinstance(data["held_claims_count"], int)


def assert_home(data: dict):
    _assert_common(data, "GroupHome")
    assert isinstance(data["name"], str)
    assert isinstance(data["license_number"], str)
    assert isinstance(data["certified_bed_count"], int) and data["certified_bed_count"] >= 1
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert data["compliance_posture"] in ["GOOD_STANDING", "PROVISIONAL", "CRITICAL"]
    assert isinstance(data["current_occupancy"], int) and data["current_occupancy"] >= 0


def assert_individual(data: dict):
    _assert_common(data, "Individual")
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["medicaid_id"], str)
    assert isinstance(data["date_of_birth"], str)
    assert data["mobility_level"] in ["AMBULATORY", "ASSIST", "WHEELCHAIR"]
    assert data["status"] in ["APPLICANT", "ENROLLED", "DISCHARGED"]


def assert_isp(data: dict):
    _assert_common(data, "ISP")
    assert data["status"] in [
        "DRAFT", "PENDING_REVIEW", "APPROVED", "ACTIVE",
        "AMENDMENT_DRAFT", "SUPERSEDED", "EXPIRED", "DISCONTINUED",
    ]
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0


def assert_authorization(data: dict):
    _assert_common(data, "ServiceAuthorization")
    assert data["service_code"] in ["RES_HAB", "DAY_PROG", "RESPITE", "SUPPORTED_EMPLOYMENT"]
    assert data["unit_type"] in ["FIFTEEN_MIN", "DAY"]
    assert isinstance(data["authorized_units"], int) and data["authorized_units"] >= 1
    assert isinstance(data["rate_cents"], int) and data["rate_cents"] >= 1
    assert isinstance(data["consumed_units"], int) and data["consumed_units"] >= 0
    assert data["remaining_units"] == data["authorized_units"] - data["consumed_units"], (
        "remaining_units must equal authorized_units - consumed_units"
    )
    assert data["status"] in [
        "PENDING", "APPROVED", "ACTIVE", "SUSPENDED",
        "EXHAUSTED", "EXPIRED", "CANCELLED",
    ]


def assert_staff(data: dict):
    _assert_common(data, "StaffMember")
    assert data["staff_role"] in ["DSP", "CASE_MANAGER", "QIDP"]
    assert isinstance(data["certifications"], list)
    for cert in data["certifications"]:
        assert cert in ["MED_CERT", "BEHAVIOR_CERT", "CPR", "CDL"]
    assert data["status"] in ["ACTIVE", "TERMINATED"]


def assert_shift(data: dict):
    _assert_common(data, "ShiftAssignment")
    assert data["shift_type"] in ["DAY", "NIGHT"]
    assert data["status"] in ["SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED"]


def assert_bed_assignment(data: dict):
    _assert_common(data, "BedAssignment")
    assert isinstance(data["bed_label"], str)
    assert isinstance(data["move_in_date"], str)
    assert data["status"] in ["PENDING", "ACTIVE", "ENDED", "CANCELLED"]


def assert_medication_order(data: dict):
    _assert_common(data, "MedicationOrder")
    assert isinstance(data["drug_name"], str)
    assert isinstance(data["schedule_times"], list) and len(data["schedule_times"]) >= 1
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_admin_event(data: dict):
    # Append-only MAR event: id + created_at ONLY; updated_at and version absent.
    assert is_valid_uuid(data.get("id", "")), "MedAdminEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "MedAdminEvent.created_at must be ISO 8601"
    )
    assert "version" not in data, "MedAdminEvent must not carry version"
    assert "updated_at" not in data, "MedAdminEvent must not carry updated_at"
    assert data["outcome"] in ["GIVEN", "REFUSED", "HELD", "MISSED"]
    assert isinstance(data["medication_order_id"], str)
    assert isinstance(data["administered_by_staff_id"], str)


def assert_behavior_plan(data: dict):
    _assert_common(data, "BehaviorSupportPlan")
    assert data["level"] in ["LEVEL_1", "LEVEL_2"]
    assert isinstance(data["restrictive_interventions"], list)
    assert data["status"] in [
        "DRAFT", "HRC_REVIEW", "APPROVED", "ACTIVE", "SUPERSEDED", "EXPIRED",
    ]


def assert_incident(data: dict):
    _assert_common(data, "Incident")
    assert data["category"] in [
        "MED_ERROR", "INJURY", "ABUSE_ALLEGATION", "BEHAVIOR", "ELOPEMENT",
    ]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "CLOSED",
    ]


def assert_evv_visit(data: dict):
    _assert_common(data, "EVVVisit")
    assert data["verification_status"] in ["PENDING", "EXCEPTION", "VERIFIED", "REJECTED"]
    assert data["billing_status"] in ["UNBILLED", "BILLED"]
    assert isinstance(data["provisional_units"], int)
    assert isinstance(data.get("allocated_units_entries", []), list)


def assert_transport_trip(data: dict):
    _assert_common(data, "TransportTrip")
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["legs"], list)
    assert isinstance(data["occupied_slots"], int) and data["occupied_slots"] >= 0
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_claim(data: dict):
    _assert_common(data, "BillingClaim")
    assert isinstance(data["lines"], list)
    assert isinstance(data["total_units"], int)
    assert isinstance(data["total_amount_cents"], int)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "DENIED", "CORRECTED",
        "PAID", "PARTIALLY_PAID", "HOLD", "VOIDED",
    ]

"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp ('Z' or offset form, with or without
    fractional digits) into an aware datetime for instant comparison."""
    assert isinstance(ts, str), f"expected ISO 8601 string, got {ts!r}"
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_common_fields(data: dict, context: str = "resource"):
    assert is_valid_uuid(data.get("id", "")), f"{context}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{context}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{context}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{context}: version must be a positive integer"
    )


def assert_airport(data: dict):
    assert_common_fields(data, "Airport")
    assert isinstance(data["airport_code"], str) and data["airport_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["escalation_policy"] in ("ANNIVERSARY_COMPOUND", "ANNIVERSARY_SIMPLE")
    assert data["offer_acceptance_window_hours"] > 0
    assert data["cure_window_days"] > 0
    assert isinstance(data["late_fee_grace_days"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_hangar(data: dict):
    assert_common_fields(data, "Hangar")
    assert isinstance(data["hangar_code"], str) and data["hangar_code"]
    assert data["size_class"] in ("T_HANGAR", "BOX", "EXECUTIVE", "CORPORATE")
    assert data["door_type"] in ("SLIDING", "BIFOLD", "HYDRAULIC")
    assert data["condition_rating"] in ("GOOD", "FAIR", "POOR", "OUT_OF_SERVICE")
    assert data["posture"] in ("AVAILABLE", "LEASED", "MAINTENANCE_HOLD", "OFFLINE")
    assert data["status"] in ("OPERATIONAL", "DECOMMISSIONED")


def assert_rate_schedule(data: dict):
    assert_common_fields(data, "RateSchedule")
    assert data["size_class"] in ("T_HANGAR", "BOX", "EXECUTIVE", "CORPORATE")
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] > 0
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["effective_to"] == "OPEN" or is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_application(data: dict):
    assert_common_fields(data, "WaitlistApplication")
    assert isinstance(data["applicant_name"], str) and data["applicant_name"]
    assert data["size_class_requested"] in ("T_HANGAR", "BOX", "EXECUTIVE", "CORPORATE")
    assert isinstance(data["aircraft_n_number"], str) and data["aircraft_n_number"]
    assert isinstance(data["is_based_tenant_transfer"], bool)
    assert isinstance(data["priority_score"], int)
    assert isinstance(data["decline_count"], int) and data["decline_count"] >= 0
    assert data["status"] in (
        "QUEUED", "OFFERED", "ACCEPTED", "LEASED", "WITHDRAWN", "EXPIRED_OFFER", "REJECTED",
    )


def assert_offer(data: dict):
    assert_common_fields(data, "HangarOffer")
    assert is_valid_uuid(data["hangar_id"])
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["quoted_monthly_rate_cents"], int)
    assert is_iso8601_timestamp(data["offer_sent_at"])
    assert is_iso8601_timestamp(data["acceptance_deadline"])
    assert data["status"] in ("OPEN", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED")


def assert_lease(data: dict):
    assert_common_fields(data, "Lease")
    assert is_valid_uuid(data["hangar_id"])
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["offer_id"])
    assert isinstance(data["tenant_name"], str) and data["tenant_name"]
    assert isinstance(data["base_monthly_rate_cents"], int)
    assert isinstance(data["current_monthly_rate_cents"], int)
    assert isinstance(data["last_escalation_anniversary"], int)
    assert isinstance(data["aeronautical_use_attested"], bool)
    assert isinstance(data["sublease_allowed"], bool)
    assert isinstance(data["days_delinquent"], int) and data["days_delinquent"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int) and data["outstanding_balance_cents"] >= 0
    assert data["status"] in (
        "ACTIVE", "DELINQUENT", "CURE_PERIOD", "EVICTION_PENDING", "EVICTED", "TERMINATED",
    )


def assert_lease_aircraft(data: dict):
    assert_common_fields(data, "LeaseAircraft")
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["n_number"], str) and data["n_number"]
    assert isinstance(data["is_primary"], bool)
    assert data["status"] in ("BASED", "REMOVED")


def assert_insurance_certificate(data: dict):
    assert_common_fields(data, "InsuranceCertificate")
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["liability_coverage_cents"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ("VALID", "EXPIRED")


def assert_environmental_record(data: dict):
    assert_common_fields(data, "EnvironmentalComplianceRecord")
    assert is_valid_uuid(data["lease_id"])
    assert data["record_type"] in ("FUEL_STORAGE_PERMIT", "STORMWATER_PLAN", "HAZMAT_DISCLOSURE")
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("PENDING_REVIEW", "APPROVED", "REJECTED", "EXPIRED")


def assert_inspection(data: dict):
    assert_common_fields(data, "HangarConditionInspection")
    assert is_valid_uuid(data["hangar_id"])
    assert data["condition_rating"] in ("GOOD", "FAIR", "POOR", "OUT_OF_SERVICE")
    assert data["maintenance_responsibility"] in ("TENANT", "AIRPORT", "SHARED")
    assert data["status"] in ("OPEN", "CLOSED")


def assert_audit_finding(data: dict):
    assert_common_fields(data, "UseAuditFinding")
    assert is_valid_uuid(data["lease_id"])
    assert data["finding_type"] in (
        "NON_AERONAUTICAL_USE", "UNAUTHORIZED_SUBLEASE", "INSURANCE_LAPSE", "ENVIRONMENTAL_LAPSE",
    )
    assert is_iso8601_timestamp(data["cure_deadline"])
    assert data["status"] in ("OPEN", "CURED", "ESCALATED_TO_EVICTION")


def assert_eviction_case(data: dict):
    assert_common_fields(data, "EvictionCase")
    assert is_valid_uuid(data["lease_id"])
    assert data["reason"] in ("UNCURED_AUDIT", "DELINQUENCY", "NON_AERONAUTICAL_USE")
    assert data["status"] in ("FILED", "EXECUTED", "CLOSED_AIRCRAFT_REMOVED", "CLOSED_AIRCRAFT_ABANDONED")


def assert_rent_charge(data: dict):
    assert_common_fields(data, "RentCharge")
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["base_amount_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in ("OPEN", "PAID", "PARTIALLY_PAID")


def assert_charge_ledger_identity(charge: dict):
    """PRD §3.5: a charge's `balance_cents` is always its `base_amount_cents`
    plus `late_fee_cents` minus `paid_cents`."""
    assert charge["balance_cents"] == charge["base_amount_cents"] + charge["late_fee_cents"] - charge["paid_cents"], (
        f"charge ledger identity violated: {charge}"
    )

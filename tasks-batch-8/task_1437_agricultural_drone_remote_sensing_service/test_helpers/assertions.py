"""Entity assertions and domain invariant checkers (PRD sections 2.4 and 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_GROWER_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
_PILOT_STATUSES = ["ACTIVE", "SUSPENDED"]
_AUTH_STATUSES = ["ACTIVE", "REVOKED", "EXPIRED"]
_AIRSPACE_CLASSES = ["G", "E", "D", "C", "B"]
_MISSION_TYPES = ["SCOUT", "SPRAY"]
_MISSION_STATUSES = [
    "PLANNED", "AUTHORIZED", "IN_FLIGHT", "CAPTURED", "COMPLETED",
    "WEATHER_ABORTED", "CANCELLED",
]
_DELIV_KINDS = ["NDVI", "PLANT_COUNT"]
_DELIV_STATUSES = ["PROCESSING", "READY", "DELIVERED", "EXPIRED"]
_ALERT_SEVERITIES = ["LOW", "MEDIUM", "HIGH"]
_ALERT_STATUSES = ["OPEN", "UNDER_REVIEW", "REVIEWED"]
_REVIEW_OUTCOMES = ["CONFIRMED", "DISMISSED", "NEEDS_REFLIGHT"]
_CLAIM_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED", "PAID"]


def _assert_common_fields(data: dict, entity: str):
    """PRD section 2.4 common fields: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def _assert_lean_fields(data: dict, entity: str):
    """PRD section 2.4: AirspaceAuthorization and SprayMissionRecord carry only
    id and created_at; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_subscription_plan(data: dict):
    _assert_common_fields(data, "SubscriptionPlan")
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["included_acres_per_year"], int)
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["overage_rate_cents_per_acre"], int)
    assert isinstance(data["spray_allowed"], bool)
    assert isinstance(data["ndvi_turnaround_hours"], int)
    assert isinstance(data["storage_retention_days"], int)


def assert_grower(data: dict):
    _assert_common_fields(data, "Grower")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["subscription_plan_id"], str)
    assert isinstance(data["subscription_started_on"], str)
    assert isinstance(data["acres_included_ytd"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["liability_coverage_cents"], int)
    assert data["status"] in _GROWER_STATUSES


def assert_field(data: dict):
    _assert_common_fields(data, "Field")
    assert isinstance(data["field_name"], str) and data["field_name"]
    assert isinstance(data["legal_acres"], int) and data["legal_acres"] > 0
    assert isinstance(data["surveyed_acres"], int)
    assert data["airspace_class"] in _AIRSPACE_CLASSES
    assert isinstance(data["laanc_required"], bool)
    # PRD section 2.7: health score is an integer bounded to [0, 100]
    assert isinstance(data["health_score"], int)
    assert 0 <= data["health_score"] <= 100
    assert isinstance(data["insurance_policy_no"], str)


def assert_pilot(data: dict):
    _assert_common_fields(data, "PilotProfile")
    assert isinstance(data["pilot_name"], str) and data["pilot_name"]
    assert isinstance(data["part107_certificate_no"], str)
    assert isinstance(data["part107_expires_on"], str)
    assert isinstance(data["applicator_license_no"], str)
    assert isinstance(data["applicator_license_expires_on"], str)
    assert isinstance(data["night_waiver"], bool)
    assert data["status"] in _PILOT_STATUSES


def assert_authorization(data: dict):
    _assert_lean_fields(data, "AirspaceAuthorization")
    assert isinstance(data["field_id"], str)
    assert isinstance(data["authorization_ref"], str)
    assert isinstance(data["max_altitude_ft"], int)
    assert data["max_altitude_ft"] <= 400
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_until"], str)
    assert data["status"] in _AUTH_STATUSES


def assert_mission(data: dict):
    _assert_common_fields(data, "FlightMission")
    assert data["mission_type"] in _MISSION_TYPES
    assert isinstance(data["pilot_id"], str)
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert isinstance(data["acres_planned"], int)
    assert isinstance(data["acres_flown"], int)
    assert isinstance(data["wind_kt_max_observed"], int)
    assert isinstance(data["chemical_product_label"], str)
    assert data["status"] in _MISSION_STATUSES


def assert_deliverable(data: dict):
    _assert_common_fields(data, "ImageryDeliverable")
    assert isinstance(data["mission_id"], str)
    assert data["kind"] in _DELIV_KINDS
    assert data["status"] in _DELIV_STATUSES


def assert_alert(data: dict):
    _assert_common_fields(data, "ScoutingAlert")
    assert isinstance(data["field_id"], str)
    assert isinstance(data["deliverable_id"], str)
    assert data["severity"] in _ALERT_SEVERITIES
    assert data["status"] in _ALERT_STATUSES


def assert_spray_record(data: dict):
    _assert_lean_fields(data, "SprayMissionRecord")
    assert isinstance(data["mission_id"], str)
    assert isinstance(data["applicator_license_no"], str)
    assert isinstance(data["chemical_product_label"], str)
    # PRD section 3.5: record_locked is always true
    assert data["record_locked"] is True


def assert_claim(data: dict):
    _assert_common_fields(data, "InsuranceClaim")
    assert isinstance(data["grower_id"], str)
    assert isinstance(data["mission_id"], str)
    assert isinstance(data["claim_amount_cents"], int)
    assert isinstance(data["approved_amount_cents"], int)
    assert data["status"] in _CLAIM_STATUSES

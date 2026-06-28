"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


AGENCY_DISCIPLINES = ["POLICE", "FIRE", "EMS"]
AGENCY_STATUSES = ["ONLINE", "MUTUAL_AID_ONLY", "OFFLINE"]
UNIT_CAPABILITIES = ["PATROL", "K9", "SUPERVISOR_UNIT", "ENGINE", "LADDER",
                     "MEDIC_ALS", "MEDIC_BLS"]
UNIT_STATUSES = ["AVAILABLE", "DISPATCHED", "ENROUTE", "ONSCENE", "CLEARING",
                 "OUT_OF_SERVICE"]
INCIDENT_LIFECYCLE_STATUSES = ["PENDING", "DISPATCHED", "ACTIVE", "HELD",
                               "CLOSED", "CANCELLED"]
ASSIGNMENT_STATUSES = ["DISPATCHED", "ENROUTE", "ONSCENE", "CLEARED", "CANCELLED"]
ALI_CONFIDENCES = ["HIGH", "LOW", "UNKNOWN"]
INCIDENT_TYPES = ["STRUCTURE_FIRE", "MEDICAL_EMERGENCY", "TRAFFIC_COLLISION",
                  "ASSAULT_IN_PROGRESS", "ALARM", "WELFARE_CHECK"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["discipline"] in AGENCY_DISCIPLINES
    assert isinstance(data["response_sla_seconds"], int) and data["response_sla_seconds"] >= 1
    assert data["status"] in AGENCY_STATUSES


def assert_station(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agency_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 0 <= data["grid_x"] <= 1000
    assert 0 <= data["grid_y"] <= 1000


def assert_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agency_id"])
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["call_sign"], str) and len(data["call_sign"]) > 0
    assert data["capability"] in UNIT_CAPABILITIES
    assert data["status"] in UNIT_STATUSES
    assert 0 <= data["grid_x"] <= 1000
    assert 0 <= data["grid_y"] <= 1000
    aid = data.get("active_incident_id")
    assert aid is None or is_valid_uuid(aid)


def assert_premise_alert(data: dict):
    _assert_common(data)
    assert 0 <= data["grid_x"] <= 1000
    assert 0 <= data["grid_y"] <= 1000
    assert 1 <= data["min_priority_floor"] <= 5
    assert isinstance(data["active"], bool)


def assert_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["incident_number"], str) and len(data["incident_number"]) > 0
    assert isinstance(data["ani"], str)
    assert 0 <= data["ali_grid_x"] <= 1000
    assert 0 <= data["ali_grid_y"] <= 1000
    assert data["ali_confidence"] in ALI_CONFIDENCES
    assert data["incident_type"] in INCIDENT_TYPES
    assert 1 <= data["priority_level"] <= 5
    assert 1 <= data["base_priority_level"] <= 5
    assert isinstance(data["required_disciplines"], list)
    assert data["lifecycle_status"] in INCIDENT_LIFECYCLE_STATUSES
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert isinstance(data["escalation_count"], int) and data["escalation_count"] >= 0
    assert isinstance(data["sla_breached"], bool)


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert is_valid_uuid(data["unit_id"])
    assert isinstance(data["recommended"], bool)
    assert isinstance(data["travel_distance"], int) and data["travel_distance"] >= 0
    assert data["status"] in ASSIGNMENT_STATUSES
    assert is_iso8601_timestamp(data.get("dispatched_at", ""))


def assert_disposition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert isinstance(data["narrative"], str)
    assert isinstance(data["requires_nfirs"], bool)


def assert_cfs_report(data: dict):
    """CfsReport is immutable/append-only: it carries id + created_at only,
    and must NOT carry version or updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "version" not in data, "CfsReport must not carry a version field"
    assert "updated_at" not in data, "CfsReport must not carry an updated_at field"

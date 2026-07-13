"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_incident(data: dict):
    _assert_common(data)
    assert data["status"] in {"DRAFT", "ACTIVE", "ALL_CLEAR", "STOOD_DOWN"}
    assert data["hazard_type"] in {"WILDFIRE", "FLOOD", "HURRICANE", "HAZMAT", "TSUNAMI"}
    assert isinstance(data["ipaws_daily_slot_budget"], int) and data["ipaws_daily_slot_budget"] >= 0
    assert isinstance(data["ipaws_slots_reserved"], int) and data["ipaws_slots_reserved"] >= 0


def assert_zone(data: dict):
    _assert_common(data)
    assert data["order_level"] in {"NONE", "VOLUNTARY", "MANDATORY", "RE_ENTRY_ALLOWED"}
    assert isinstance(data["population_at_risk"], int) and data["population_at_risk"] >= 0


def assert_shelter(data: dict):
    _assert_common(data)
    assert data["status"] in {"STANDBY", "OPEN", "FULL", "CLOSED"}
    for f in ("staffed_capacity_now", "effective_capacity", "reserved_beds",
              "occupied_beds", "provisional_available", "confirmed_available"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["effective_capacity"] >= 0
    assert data["reserved_beds"] >= 0
    assert data["occupied_beds"] >= 0


def assert_staff_shift(data: dict):
    _assert_common(data)
    assert data["status"] in {"SCHEDULED", "CANCELLED"}
    assert isinstance(data["staffed_beds"], int) and data["staffed_beds"] >= 0


def assert_route(data: dict):
    _assert_common(data)
    assert data["status"] in {"PLANNED", "OPEN", "CONGESTED", "CLOSED"}
    assert isinstance(data["throughput_vph"], int) and data["throughput_vph"] >= 1


def assert_contraflow(data: dict):
    _assert_common(data)
    assert data["status"] in {"SCHEDULED", "ACTIVE", "CANCELLED", "COMPLETED"}
    assert data["direction"] in {"INBOUND_REVERSED", "OUTBOUND"}


def assert_registrant(data: dict):
    _assert_common(data)
    assert data["status"] in {"REGISTERED", "ADVISED", "ORDERED", "SHELTERED", "CLEARED_FOR_REENTRY"}
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["functional_needs"] in {"NONE", "MOBILITY", "MEDICAL_ELECTRICITY", "OXYGEN", "COGNITIVE"}


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in {"RESERVED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"}
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1


def assert_credential(data: dict):
    _assert_common(data)
    assert data["status"] in {"ISSUED", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED"}
    assert data["credential_type"] in {"RESIDENT", "ESSENTIAL_WORKER", "UTILITY"}


def assert_alert(data: dict):
    _assert_common(data)
    assert data["overall_status"] in {"DRAFT", "QUEUED", "SENT", "PARTIAL", "FAILED", "CANCELLED"}
    for f in ("wea_status", "eas_status", "ipaws_status", "sms_status"):
        assert data[f] in {"NA", "PENDING", "SENT", "FAILED"}, f"{f} out of range: {data.get(f)!r}"


def assert_shelter_bed_invariants(data: dict):
    """Bed conservation invariants that must always hold on a shelter read (PRD 2.7)."""
    assert data["provisional_available"] == data["effective_capacity"] - data["reserved_beds"] - data["occupied_beds"], \
        "provisional_available must equal effective_capacity - reserved_beds - occupied_beds"
    assert data["confirmed_available"] == data["effective_capacity"] - data["occupied_beds"], \
        "confirmed_available must equal effective_capacity - occupied_beds"

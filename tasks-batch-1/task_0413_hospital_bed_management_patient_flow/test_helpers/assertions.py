"""Entity assertions and domain invariant checkers for the Hospital Bed Flow API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

UNIT_TYPES = ["MEDSURG", "TELEMETRY", "ICU", "ED"]
POSTURES = ["GREEN", "YELLOW", "RED", "CLOSED"]
BED_STATUSES = ["CLEAN", "DIRTY", "OCCUPIED", "BLOCKED", "RETIRED"]
ROOM_TYPES = ["PRIVATE", "SEMIPRIVATE"]
SEX_COHORTS = ["NONE", "MALE", "FEMALE"]
ENCOUNTER_STATUSES = [
    "REGISTERED", "ADMIT_PENDING", "BOARDING", "PLACED",
    "DISCHARGE_ORDERED", "DISCHARGED", "CANCELLED",
]
BED_REQUEST_STATUSES = ["QUEUED", "ASSIGNED", "CONFIRMED", "CANCELLED", "EXPIRED"]
EVS_TASK_STATUSES = ["REQUESTED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
EVS_TASK_TYPES = ["STAT", "ISOLATION", "ROUTINE"]
BARRIER_STATUSES = ["OPEN", "RESOLVED"]
SURGE_STATUSES = ["OPEN", "STOOD_DOWN"]


def _assert_common(data: dict):
    """id/created_at/updated_at/version present (common_fields entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["unit_type"] in UNIT_TYPES
    assert isinstance(data["gmlos_days"], int)
    for cnt in ("total_bed_count", "staffed_bed_count",
                "occupied_bed_count", "clean_available_count"):
        assert isinstance(data[cnt], int) and data[cnt] >= 0, f"{cnt} must be >= 0"
    assert isinstance(data["occupancy_pct"], (int, float))
    assert data["occupancy_pct"] >= 0
    assert data["derived_posture"] in POSTURES
    assert data["declared_surge_level"] in ["GREEN", "YELLOW", "RED"]
    assert data["effective_posture"] in POSTURES


def assert_bed(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be a valid UUID"
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["room_type"] in ROOM_TYPES
    assert isinstance(data["isolation_capable"], bool)
    assert isinstance(data["telemetry_capable"], bool)
    assert data["status"] in BED_STATUSES
    assert data["sex_cohort"] in SEX_COHORTS


def assert_encounter(data: dict):
    _assert_common(data)
    assert isinstance(data["mrn"], str) and len(data["mrn"]) > 0
    assert data["sex"] in ["MALE", "FEMALE"]
    assert isinstance(data["requires_isolation"], bool)
    assert isinstance(data["requires_telemetry"], bool)
    assert data["origin"] in ["ED", "DIRECT", "TRANSFER_IN"]
    assert data["status"] in ENCOUNTER_STATUSES
    assert isinstance(data["boarding_hours"], (int, float))
    assert isinstance(data["boarding_breached"], bool)
    assert isinstance(data["length_of_stay_hours"], (int, float))
    assert isinstance(data["long_stay_flag"], bool)
    assert isinstance(data["open_barrier_count"], int)
    assert data["open_barrier_count"] >= 0


def assert_bed_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("encounter_id", "")), "encounter_id must be a valid UUID"
    assert isinstance(data["acceptable_unit_types"], list)
    assert data["priority"] in ["STAT", "URGENT", "ROUTINE"]
    assert data["status"] in BED_REQUEST_STATUSES


def assert_evs_task(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("bed_id", "")), "bed_id must be a valid UUID"
    assert data["task_type"] in EVS_TASK_TYPES
    assert data["status"] in EVS_TASK_STATUSES
    assert isinstance(data["priority_score"], int)


def assert_discharge_barrier(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("encounter_id", "")), "encounter_id must be a valid UUID"
    assert data["barrier_type"] in [
        "PLACEMENT_SNF", "TRANSPORT", "PHARMACY", "FAMILY", "EQUIPMENT"]
    assert data["status"] in BARRIER_STATUSES


def assert_surge_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be a valid UUID"
    assert data["level"] in ["YELLOW", "RED"]
    assert data["status"] in SURGE_STATUSES


def assert_capacity_huddle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    for cnt in ("total_staffed_beds", "total_occupied_beds",
                "boarding_encounter_count", "queued_request_count", "red_unit_count"):
        assert isinstance(data[cnt], int) and data[cnt] >= 0, f"{cnt} must be >= 0"
    assert isinstance(data["house_occupancy_pct"], (int, float))


def assert_adt_event(data: dict):
    """AdtEvent is append-only: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["event_type"] in [
        "ADMIT", "PLACE", "TRANSFER", "DISCHARGE_ORDER", "DISCHARGE", "CANCEL"]


# ─── Domain invariants ─────────────────────────────────────────────────────

def assert_unit_count_invariants(data: dict):
    """Counts must reconcile per PRD §2.8: counts are non-negative and
    occupied <= staffed <= total are consistent ordering relations."""
    assert data["occupied_bed_count"] <= data["staffed_bed_count"], \
        "occupied beds cannot exceed staffed beds"
    assert data["staffed_bed_count"] <= data["total_bed_count"], \
        "staffed beds cannot exceed total (non-retired) beds"
    assert data["clean_available_count"] <= data["staffed_bed_count"], \
        "clean beds are a subset of staffed beds"

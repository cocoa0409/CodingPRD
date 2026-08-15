"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_instant_equal(actual, expected):
    """Compare two ISO 8601 UTC timestamps by instant, not by string format.

    PRD §2.5 pins the three-fractional-digit serialization only for
    `created_at` / `updated_at` (and §2.2 for `api_request_timestamp`).
    Domain timestamps (`starts_at`, `expires_at`, `consult_deadline`,
    `cooling_until`, `next_elective_window_start`, ...) are pinned by the
    PRD's instant arithmetic ("thirty minutes after the dispatch time",
    "`starts_at` plus `ttl_minutes`", ...) with the serialization format
    left unspecified, so any faithful ISO 8601 rendering must compare equal.
    """
    def _parse(v):
        assert isinstance(v, str) and v.strip(), \
            f"expected an ISO 8601 timestamp string, got {v!r}"
        s = v.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    assert _parse(actual) == _parse(expected), \
        f"instant mismatch: {actual!r} != {expected!r}"


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert data["diversion_status"] in ("ACCEPTING", "DIVERT_FULL", "DIVERT_SERVICE")
    assert isinstance(data["diversion_recommended"], bool)
    for counter in ("staffed_beds", "occupied_beds", "held_beds", "available_beds",
                    "out_of_service_beds", "boarding_waiters",
                    "active_inbound_transfers"):
        assert isinstance(data[counter], int), f"{counter} must be an int"
    for score in ("load_score_raw", "load_score_weighted",
                  "service_weighted_occupancy_pct"):
        assert isinstance(data[score], (int, float)), f"{score} must be a number"


def assert_bed(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "HELD", "OCCUPIED", "OUT_OF_SERVICE")
    assert data["service"] in ("CARDIAC", "NEURO", "TRAUMA", "MEDICAL",
                               "SURGICAL", "ONCOLOGY")
    assert data["max_acuity"] in ("ACUITY_1_CRITICAL", "ACUITY_2_STEPDOWN",
                                  "ACUITY_3_MEDICAL_SURGICAL", "ACUITY_4_OBSERVATION")
    assert data["isolation_capability"] in ("NONE", "CONTACT", "DROPLET", "AIRBORNE")
    assert isinstance(data["staffed"], bool)
    assert isinstance(data["turnover_minutes"], int)
    assert is_valid_uuid(data.get("facility_id", ""))


def assert_physician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["services"], list)
    assert data["status"] in ("ON_CALL", "OFF_CALL")
    assert is_valid_uuid(data.get("facility_id", ""))


def assert_admission(data: dict):
    _assert_common(data)
    assert data["status"] in ("ADMITTED", "PENDING_DISCHARGE", "DISCHARGED")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("bed_id", ""))
    assert isinstance(data["patient_ref"], str) and data["patient_ref"]


def assert_transfer_request(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "INTAKE", "CONSULT_PENDING", "DECLINED", "EXPIRED", "ACCEPTED",
        "HOLD_PLACED", "ASSIGNED", "COMPLETED", "CANCELLED")
    assert data["priority"] in ("EMERGENT", "URGENT", "ELECTIVE")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["consult_count"], int) and data["consult_count"] >= 0


def assert_bed_hold(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CONSUMED", "RELEASED", "EXPIRED")
    assert is_valid_uuid(data.get("bed_id", ""))
    assert is_valid_uuid(data.get("transfer_request_id", ""))
    assert isinstance(data["ttl_minutes"], int)
    assert isinstance(data["extend_count"], int) and data["extend_count"] >= 0
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_bed_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLACED", "COMPLETED", "CANCELLED")
    assert is_valid_uuid(data.get("transfer_request_id", ""))
    assert is_valid_uuid(data.get("bed_hold_id", ""))
    assert is_valid_uuid(data.get("bed_id", ""))
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_diversion_event(data: dict):
    _assert_common(data)
    assert data["level"] in ("FULL", "SERVICE")
    assert data["status"] in ("ACTIVE", "LIFTED", "EXPIRED")
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data["declared_by_user_id"], str) and data["declared_by_user_id"]


def assert_boarding_record(data: dict):
    _assert_common(data)
    assert data["placement_status"] in ("WAITING", "OFFERED", "PLACED", "LEFT_AMA")
    assert data["escalation_status"] in ("NONE", "HUDDLE_CALLED", "HUDDLE_RESOLVED")
    assert isinstance(data["boarding_minutes"], int) and data["boarding_minutes"] >= 0
    assert isinstance(data["huddle_count_24h"], int) and data["huddle_count_24h"] >= 0
    assert isinstance(data["executive_escalation"], bool)
    assert is_valid_uuid(data.get("admission_id", ""))


def assert_escalation_huddle(data: dict):
    _assert_common(data)
    assert data["status"] in ("CALLED", "RESOLVED")
    assert data["trigger_reason"] in ("AUTO_THRESHOLD", "MANUAL")
    assert is_iso8601_timestamp(data.get("called_at", ""))
    assert is_valid_uuid(data.get("boarding_record_id", ""))


def assert_capacity_forecast(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROVISIONAL", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data["horizon_hours"], int) and 1 <= data["horizon_hours"] <= 72
    assert is_iso8601_timestamp(data.get("generated_at", ""))
    assert isinstance(data["stale"], bool)
    snapshots = data["variant_snapshots"]
    assert isinstance(snapshots, dict)
    assert isinstance(snapshots["committed"], list)
    assert isinstance(snapshots["provisional"], list)
    assert len(snapshots["committed"]) == data["horizon_hours"]
    assert len(snapshots["provisional"]) == data["horizon_hours"]
    for v in snapshots["committed"] + snapshots["provisional"]:
        assert isinstance(v, int), f"census values must be integers, got {v!r}"
    for pct in ("occupancy_pct_committed", "occupancy_pct_provisional"):
        assert isinstance(data[pct], (int, float)), f"{pct} must be a number"


def assert_facility_bed_count_conservation(facility: dict):
    """Bed-status census conservation: every staffed bed is in exactly one
    status bucket, and out-of-service beds are counted separately."""
    total = (facility["available_beds"] + facility["held_beds"]
             + facility["occupied_beds"])
    assert total <= facility["staffed_beds"], (
        "available + held + occupied may not exceed staffed_beds; "
        f"got {total} > {facility['staffed_beds']}"
    )

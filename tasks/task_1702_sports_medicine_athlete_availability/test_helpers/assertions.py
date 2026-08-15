"""Entity assertions and small value helpers (field presence per PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp ('...Z' suffix tolerated)."""
    assert isinstance(ts, str) and ts, f"expected ISO timestamp string, got {ts!r}"
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int), "version must be an integer"
    else:
        assert "updated_at" not in data, "append-only entity must not expose updated_at"
        assert "version" not in data, "append-only entity must not expose version"


def assert_team(data: dict):
    _assert_common(data)
    assert data["sport"] in ["FOOTBALL", "BASKETBALL", "SOCCER", "HOCKEY", "BASEBALL"]
    assert data["hipaa_mode"] in ["STRICT", "STANDARD"]
    assert data["acwr_variant"] in ["ROLLING", "EWMA"]


def assert_athlete(data: dict):
    _assert_common(data)
    assert data["roster_status"] in ["ACTIVE", "INACTIVE", "RELEASED"]
    assert data["availability_tier"] in ["FULL", "MODIFIED", "LIMITED", "OUT"]
    assert data["load_flag"] in ["NONE", "ELEVATED", "SPIKE"]
    ratio = data.get("acute_chronic_workload_ratio")
    assert ratio is None or isinstance(ratio, (int, float)), "ACWR must be null or numeric"


def assert_diagnosis_code(data: dict):
    _assert_common(data, with_version=False)
    assert data["body_region"] in [
        "HEAD_NECK", "SHOULDER", "ARM", "HAND", "TRUNK",
        "HIP", "KNEE", "LOWER_LEG", "ANKLE_FOOT", "SYSTEMIC",
    ]
    assert data["severity_class"] in ["MINOR", "MODERATE", "SEVERE"]
    assert isinstance(data["is_concussion"], bool)


def assert_injury_case(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "REHAB", "RTP", "LONG_TERM", "CLEARED", "CLOSED"]
    assert data["surface"] in ["GRASS", "TURF", "COURT", "ICE", "TRAINING_ROOM"]
    assert data["mechanism"] in ["CONTACT", "NON_CONTACT", "OVERUSE", "UNKNOWN"]
    assert data["severity_class_snapshot"] in ["MINOR", "MODERATE", "SEVERE"]
    assert isinstance(data["is_concussion_snapshot"], bool)


def assert_treatment_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "COMPLETED"]
    assert 1 <= data["planned_sessions_per_week"] <= 14
    assert 1 <= data["estimated_duration_weeks"] <= 52


def assert_daily_status_entry(data: dict):
    _assert_common(data, with_version=False)
    assert data["designation"] in ["OUT", "LIMITED", "MODIFIED", "FULL"]
    assert isinstance(data["symptom_free"], bool)
    assert 0 <= data["functional_test_score"] <= 100
    assert isinstance(data["is_current"], bool)


def assert_rtp_protocol(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "NOT_STARTED", "IN_PROGRESS", "AWAITING_CLEARANCE",
        "REGRESSED", "SUSPENDED_CONCUSSION", "CLEARED",
    ]
    assert 3 <= data["total_stages"] <= 7
    assert isinstance(data["current_stage_index"], int)
    assert isinstance(data["regression_count"], int)


def assert_stage_advance(data: dict):
    _assert_common(data, with_version=False)
    assert data["kind"] in ["ADVANCE", "REGRESSION"]
    assert isinstance(data["from_stage_index"], int)
    assert isinstance(data["to_stage_index"], int)


def assert_clearance(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "GRANTED", "RETURNED_FOR_REVIEW", "EXPIRED"]


def assert_workload_session(data: dict):
    _assert_common(data, with_version=False)
    assert data["session_type"] in ["PRACTICE", "GAME", "CONDITIONING", "REHAB_SESSION"]
    assert data["surface"] in ["GRASS", "TURF", "COURT", "ICE", "TRAINING_ROOM"]
    assert 0 <= data["duration_minutes"] <= 600
    assert 0 <= data["rpe"] <= 10


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "CANCELLED"]
    assert data["deductible_cents"] >= 0
    assert 0 <= data["coinsurance_pct"] <= 100
    assert data["oop_max_cents"] >= data["deductible_cents"]


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "ADJUDICATED", "PAID", "DENIED", "APPEALED", "VOID",
    ]
    assert data["billed_amount_cents"] > 0
    assert isinstance(data["appeals_count"], int)


def assert_disclosure_grant(data: dict):
    _assert_common(data)
    assert data["grantee_role"] in ["COACHING", "FRONT_OFFICE"]
    assert data["scope"] in ["TIER_ONLY", "GENERAL", "FULL"]
    assert data["status"] in ["ACTIVE", "REVOKED", "EXPIRED"]


def assert_availability_report(data: dict):
    _assert_common(data, with_version=False)
    assert data["generated_for_role"] in ["COACHING", "FRONT_OFFICE", "MEDICAL"]
    assert isinstance(data["rows"], list)
    for row in data["rows"]:
        assert "athlete_id" in row, "each report row must carry athlete_id"
        assert "availability_tier" in row, "each report row must carry availability_tier"

"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, with or without fractional seconds."""
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    return datetime.fromisoformat(v)


def assert_instant_equals(actual: str, expected: str, label: str = "timestamp"):
    """Assert two ISO 8601 timestamps denote the same instant.

    The PRD pins the instant each time rule lands on (for example an expiry
    'at the stroke of 00:00:00Z that day'), so tests compare instants.
    """
    assert is_iso8601_timestamp(actual), f"{label} not ISO 8601: {actual!r}"
    assert parse_iso8601(actual) == parse_iso8601(expected), (
        f"{label}: expected instant {expected}, got {actual}")


def _assert_common_fields(data: dict):
    """Standard system-managed fields of a primary resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_staff(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_type"] in [
        "ATHLETIC_TRAINER", "TEAM_COACH", "PHYSICIAN", "ATHLETIC_DIRECTOR",
        "SCHOOL_NURSE",
    ]
    assert isinstance(data["sport_certifications"], list)
    assert isinstance(data["is_active"], bool)


def assert_athlete(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["grade"], int) and 9 <= data["grade"] <= 12
    assert data["sex"] in ["M", "F"]
    assert data["primary_sport"] in [
        "FOOTBALL", "SOCCER", "BASKETBALL", "BASEBALL", "SOFTBALL",
        "VOLLEYBALL", "WRESTLING", "LACROSSE", "FIELD_HOCKEY",
        "CROSS_COUNTRY", "TRACK", "SWIMMING", "TENNIS", "GOLF",
    ]
    assert data["team_level"] in ["VARSITY", "JV", "FRESHMAN"]
    assert isinstance(data["guardian_name"], str)
    assert isinstance(data["guardian_user_id"], str)
    assert data["participation_posture"] in [
        "NOT_CLEARED", "INELIGIBLE", "MEDICAL_HOLD",
        "CLEARED_WITH_RESTRICTIONS", "CLEARED",
    ]
    assert isinstance(data["posture_reasons"], list)


def assert_physical(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert data["outcome"] in [
        "CLEARED", "CLEARED_WITH_RESTRICTIONS", "NOT_CLEARED", "DEFERRED",
    ]
    assert data["validity_policy"] in ["DISTRICT_13MO", "STATE_SCHOOL_YEAR"]
    assert data["status"] in ["RECORDED", "VERIFIED", "EXPIRED", "VOIDED"]
    assert isinstance(data["recorded_by_staff_id"], str)
    assert is_iso8601_timestamp(data.get("expires_on", ""))


def assert_baseline(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert data["instrument"] in ["SCAT6", "IMPACT", "SWAY"]
    assert isinstance(data["symptom_score"], int)
    assert 0 <= data["symptom_score"] <= 132
    assert isinstance(data["balance_errors"], int)
    assert 0 <= data["balance_errors"] <= 60
    assert data["status"] in ["CURRENT", "SUPERSEDED", "EXPIRED"]
    assert isinstance(data["administered_by_staff_id"], str)
    assert is_iso8601_timestamp(data.get("valid_until", ""))


def assert_venue(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["venue_name"], str) and data["venue_name"]
    assert data["venue_type"] in ["INDOOR", "OUTDOOR"]
    assert data["surface"] in [
        "GRASS", "TURF", "COURT", "TRACK", "POOL", "GYM_FLOOR",
    ]
    assert isinstance(data["is_active"], bool)
    assert "active_eap_id" in data


def assert_eap(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("venue_id", ""))
    assert isinstance(data["version_label"], str) and data["version_label"]
    assert data["status"] in [
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "ACTIVE", "SUPERSEDED",
    ]
    assert isinstance(data["authored_by_staff_id"], str)


def assert_event(data: dict):
    _assert_common_fields(data)
    assert data["sport"] in [
        "FOOTBALL", "SOCCER", "BASKETBALL", "BASEBALL", "SOFTBALL",
        "VOLLEYBALL", "WRESTLING", "LACROSSE", "FIELD_HOCKEY",
        "CROSS_COUNTRY", "TRACK", "SWIMMING", "TENNIS", "GOLF",
    ]
    assert data["team_level"] in ["VARSITY", "JV", "FRESHMAN"]
    assert data["event_type"] in [
        "PRACTICE", "SCRIMMAGE", "HOME_GAME", "AWAY_GAME", "TOURNAMENT",
    ]
    assert data["status"] in [
        "SCHEDULED", "COVERED", "IN_PROGRESS", "SUSPENDED_WEATHER",
        "COMPLETED", "CANCELLED",
    ]
    assert isinstance(data["required_trainer_count"], int)
    assert isinstance(data["active_assignment_count"], int)


def assert_coverage_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["staff_id"], str)
    assert data["coverage_role"] in ["PRIMARY", "SECONDARY"]
    assert data["status"] in [
        "ASSIGNED", "ACKNOWLEDGED", "ON_SITE", "ON_HOLD", "COMPLETED",
        "DECLINED", "CANCELLED",
    ]


def assert_weather_reading(data: dict):
    """Append-only observation: id + created_at only (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert "version" not in data, \
        "an EnvironmentalReading carries no version field"
    assert "updated_at" not in data, \
        "an EnvironmentalReading carries no updated_at field"
    assert data["reading_type"] in ["HEAT_WBGT", "LIGHTNING_STRIKE"]
    assert data["source"] in ["ON_SITE_SENSOR", "WEATHER_SERVICE", "MANUAL"]


def assert_injury(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert data["body_region"] in [
        "HEAD_NECK", "SHOULDER", "ARM_HAND", "TRUNK", "HIP_PELVIS", "KNEE",
        "LOWER_LEG", "ANKLE_FOOT", "SYSTEMIC",
    ]
    assert data["injury_type"] in [
        "CONCUSSION", "FRACTURE", "SPRAIN", "STRAIN", "LACERATION",
        "HEAT_ILLNESS", "CARDIAC", "OTHER",
    ]
    assert data["severity"] in ["MINOR", "MODERATE", "SEVERE", "CRITICAL"]
    assert data["status"] in [
        "OPEN", "UNDER_CARE", "REFERRED", "RTP_IN_PROGRESS", "RESOLVED",
        "CLOSED",
    ]
    assert isinstance(data["recurrence_count"], int)


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("injury_id", ""))
    assert data["urgency"] in ["ROUTINE", "URGENT", "EMERGENT"]
    assert data["status"] in [
        "REQUESTED", "SCHEDULED", "COMPLETED", "ADDENDUM_REQUESTED",
        "CLOSED", "CANCELLED", "EXPIRED",
    ]
    assert isinstance(data["physician_staff_id"], str)
    assert is_iso8601_timestamp(data.get("due_by", ""))


def assert_rtp_protocol(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("injury_id", ""))
    assert data["protocol_type"] == "GRADUATED_6_STAGE"
    assert isinstance(data["current_stage"], int)
    assert 1 <= data["current_stage"] <= 6
    assert data["status"] in ["ACTIVE", "CLEARED", "TERMINATED"]
    assert data["clearance_authority_required"] in ["PHYSICIAN", "TRAINER"]
    assert isinstance(data["stage_history"], list)
    assert isinstance(data["recurrence_count"], int)


def assert_guardian_notification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert data["notification_type"] in [
        "INJURY_INITIAL", "REFERRAL_REQUEST", "RTP_REGRESSION",
        "CLEARANCE_GRANTED", "EVENT_SUSPENSION",
    ]
    assert data["channel"] in ["EMAIL", "PHONE"]
    assert data["status"] in [
        "QUEUED", "SENT", "FAILED", "ACKNOWLEDGED", "ESCALATED",
    ]
    assert isinstance(data["attempts"], int)


def assert_supply_item(data: dict):
    _assert_common_fields(data)
    assert data["category"] in [
        "TAPE", "FIRST_AID", "HYDRATION", "EQUIPMENT", "MEDICATION",
    ]
    assert data["unit"] in ["ROLL", "EACH", "CASE", "LITER", "BOX"]
    assert isinstance(data["par_level"], int) and data["par_level"] >= 1
    assert isinstance(data["reorder_threshold"], int)
    assert 0 <= data["reorder_threshold"] < data["par_level"]
    assert isinstance(data["unit_cost_cents"], int)
    assert data["unit_cost_cents"] > 0
    assert isinstance(data["current_stock"], int)
    assert data["stock_status"] in ["OUT_OF_STOCK", "LOW_STOCK", "IN_STOCK"]


def assert_inventory_transaction(data: dict):
    """Append-only ledger entry: id + created_at only (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert "version" not in data, \
        "an InventoryTransaction carries no version field"
    assert "updated_at" not in data, \
        "an InventoryTransaction carries no updated_at field"
    assert data["txn_type"] in ["RESTOCK", "USAGE", "WASTE", "ADJUSTMENT"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0


def assert_restock_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("supply_item_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_cost_cents"], int)
    assert data["unit_cost_cents"] > 0
    assert isinstance(data["fiscal_year"], int)
    assert data["extended_cost_cents"] == data["quantity"] * data[
        "unit_cost_cents"], (
        "extended_cost_cents must be the plain integer product of quantity "
        "and unit cost (PRD §2.10)")
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "RECEIVED", "REJECTED", "CANCELLED",
    ]


def assert_supply_budget(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["total_budget_cents"], int)
    assert data["total_budget_cents"] > 0
    assert isinstance(data["realized_spend_cents"], int)
    assert isinstance(data["committed_spend_cents"], int)
    assert data["available_cents"] == (
        data["total_budget_cents"]
        - data["realized_spend_cents"]
        - data["committed_spend_cents"]
    ), "available_cents must equal total minus realized minus committed"


def assert_posture_reasons_consistent(posture: str, reasons: list):
    """The posture gate's machine-readable reasons align with the posture."""
    assert isinstance(reasons, list)
    if posture == "CLEARED":
        assert reasons == [], "a CLEARED athlete carries no posture reasons"
    if posture == "NOT_CLEARED":
        assert "NO_VERIFIED_PHYSICAL" in reasons

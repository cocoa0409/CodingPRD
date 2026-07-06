"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    """Common-fields check (PRD §2.4): every entity carries id, created_at,
    updated_at, and version >= 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_neighborhood(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["state_code"] in {"CA", "NY", "TX", "WA", "IL", "MA", "FL", "OR"}
    assert isinstance(data["center_lat"], (int, float))
    assert isinstance(data["center_lng"], (int, float))
    assert isinstance(data["radius_meters"], int) and 100 <= data["radius_meters"] <= 5000
    assert data["safety_posture"] in {"OPEN", "ELEVATED", "EMERGENCY"}
    assert isinstance(data["unresolved_critical_count"], int) and data["unresolved_critical_count"] >= 0
    assert isinstance(data["verified_resident_count"], int) and data["verified_resident_count"] >= 0


def assert_resident(data: dict):
    _common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["home_address_line"], str)
    assert isinstance(data["home_lat"], (int, float))
    assert isinstance(data["home_lng"], (int, float))
    assert isinstance(data["primary_neighborhood_id"], str)
    assert isinstance(data["is_moderator"], bool)
    assert isinstance(data["trust_score"], int) and data["trust_score"] >= 0
    assert data["verification_status"] in {"PENDING", "VERIFIED", "REJECTED"}
    assert isinstance(data["is_suspended"], bool)


def assert_verification_request(data: dict):
    _common(data)
    assert data["state"] in {"SUBMITTED", "IN_REVIEW", "RESUBMISSION_REQUIRED",
                             "APPROVED", "REJECTED", "EXPIRED"}
    assert data["proof_type"] in {"UTILITY_BILL", "LEASE", "POSTCARD_CODE", "GEOSTAMP_SELFIE"}


def assert_resident_membership(data: dict):
    _common(data)
    assert data["status"] in {"PENDING", "VERIFIED", "REVOKED"}


def assert_post(data: dict):
    _common(data)
    assert data["category"] in {"GENERAL", "SAFETY", "RECOMMENDATION",
                                "LOST_FOUND", "FREE_ITEM", "QUESTION", "ANNOUNCEMENT"}
    assert data["state"] in {"PUBLISHED", "FLAGGED", "HIDDEN", "REMOVED"}
    assert isinstance(data["flag_count"], int) and data["flag_count"] >= 0
    assert isinstance(data["local_relevance_score"], (int, float))


def assert_marketplace_listing(data: dict):
    _common(data)
    assert data["state"] in {"ACTIVE", "RESERVED", "SOLD", "WITHDRAWN", "SUSPENDED"}
    assert data["kind"] in {"FOR_SALE", "FREE", "WANTED", "RECOMMENDATION"}
    assert isinstance(data["price_cents"], int) and 0 <= data["price_cents"] <= 100_000_000


def assert_incident(data: dict):
    _common(data)
    assert data["severity"] in {"INFO", "WARNING", "CRITICAL"}
    assert data["status"] in {"OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"}
    assert data["category"] in {"SUSPICIOUS_ACTIVITY", "PROPERTY_CRIME", "TRAFFIC_HAZARD",
                                "ENVIRONMENTAL", "PERSON_MISSING", "ANIMAL"}


def assert_civic_notice(data: dict):
    _common(data)
    assert data["state"] in {"SCHEDULED", "ACTIVE", "RETRACTED", "EXPIRED"}
    assert data["notice_kind"] in {"POLICE", "FIRE", "PUBLIC_WORKS", "HEALTH", "ELECTION"}


def assert_flag_report(data: dict):
    _common(data)
    assert data["status"] in {"OPEN", "UPHELD", "DISMISSED", "REVERSED"}
    assert data["target_type"] in {"POST", "MARKETPLACE_LISTING", "INCIDENT",
                                   "CIVIC_NOTICE", "EVENT"}


def assert_moderation_decision(data: dict):
    _common(data)
    assert data["decision"] in {"UPHOLD", "DISMISS", "REVERSE"}


def assert_business(data: dict):
    _common(data)
    assert data["state"] in {"CLAIMED", "VERIFIED_BUSINESS", "DISPUTED", "DELISTED"}


def assert_local_ad(data: dict):
    _common(data)
    assert data["state"] in {"DRAFT", "RUNNING", "PAUSED", "EXHAUSTED", "ENDED"}
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 1000
    assert isinstance(data["bid_cents_per_impression"], int) and data["bid_cents_per_impression"] >= 1
    assert isinstance(data["spend_cents"], int)
    assert data["spend_cents"] <= data["budget_cents"], "spend_cents must not exceed budget_cents"


def assert_group(data: dict):
    _common(data)
    assert isinstance(data["is_private"], bool)


def assert_event(data: dict):
    _common(data)
    assert data["state"] in {"SCHEDULED", "CANCELLED", "COMPLETED"}
    assert isinstance(data["capacity"], int) and 1 <= data["capacity"] <= 500
    assert isinstance(data["rsvp_count"], int) and data["rsvp_count"] >= 0
    assert data["rsvp_count"] <= data["capacity"], "rsvp_count must not exceed capacity"


def assert_event_rsvp(data: dict):
    _common(data)
    assert data["rsvp_status"] in {"YES", "NO", "MAYBE"}

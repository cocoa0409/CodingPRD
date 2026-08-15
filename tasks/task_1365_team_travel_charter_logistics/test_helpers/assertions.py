"""Entity assertions and domain invariant checkers (PRD §2.4 common fields, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an aware datetime.

    The PRD pins instants, not a single string serialization, for domain
    timestamp fields (e.g. §2.8 `now_utc`, §3.4 `scheduled_arrive_utc`): both
    '2027-01-15T12:00:00Z' and '2027-01-15T12:00:00.000Z' denote the same
    instant. Compare instants, never raw strings.
    """
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str):
    """Two ISO 8601 timestamps must denote the same instant (format-agnostic)."""
    assert parse_instant(actual) == parse_instant(expected), \
        f"instants differ: {actual!r} != {expected!r}"


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


def assert_team(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["team_code"], str) and data["team_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["league_rest_policy"] in ("STANDARD", "STRINGENT")


def assert_season(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["travel_budget_cents"], int)
    assert isinstance(data["committed_cost_cents"], int)
    assert isinstance(data["projected_cost_cents"], int)


def assert_trip(data: dict):
    _assert_common_fields(data)
    assert data["posture"] in ("DRAFT", "LOCKED", "DISRUPTED", "IN_FLIGHT",
                               "RECOVERING", "CLOSED", "CANCELLED")
    assert isinstance(data["party_size"], int) and data["party_size"] >= 0
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["disruption_seq"], int) and data["disruption_seq"] >= 0


def assert_member(data: dict):
    _assert_common_fields(data)
    assert data["party_role"] in ("PLAYER", "COACH", "STAFF", "MEDICAL",
                                  "SECURITY", "EQUIPMENT", "EXECUTIVE")
    assert data["travel_class"] in ("CHARTER_FIRST", "CHARTER_STANDARD",
                                    "COMMERCIAL_PREMIUM", "COMMERCIAL_COACH")
    assert data["per_diem_tier"] in ("TIER_A", "TIER_B", "TIER_C")
    assert data["status"] in ("IN", "OUT", "SCRATCHED")


def assert_charter_contract(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "VENDOR_COUNTERSIGNED",
                              "TEAM_EXECUTED", "ACTIVE", "CANCELLED", "EXPIRED")
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["fuel_surcharge_cap_cents"], int)
    assert isinstance(data["seat_capacity"], int)
    assert isinstance(data["cargo_capacity_lb"], int)
    assert isinstance(data["penalty_bands"], list)


def assert_flight_leg(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PLANNED", "BOOKED", "DELAYED", "REBOOKING",
                              "DEPARTED", "ARRIVED", "CANCELLED")
    assert isinstance(data["leg_seq"], int)
    assert isinstance(data["rebook_generation"], int)


def assert_manifest_entry(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PENDING", "CONFIRMED", "BUMPED", "NO_SHOW", "FLOWN")
    assert isinstance(data["is_ticketed"], bool)


def assert_hotel_block(data: dict):
    _assert_common_fields(data)
    assert data["posture"] in ("HOLDING", "NAME_LIST_DUE", "LOCKED",
                               "ATTRITION_EXPOSED", "CLOSED")
    assert isinstance(data["room_count"], int)
    assert isinstance(data["rate_cents_per_night"], int)
    assert isinstance(data["night_count"], int)
    assert isinstance(data["rooms_released"], int)


def assert_room_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("RESERVED", "CONFIRMED", "CHECKED_IN",
                              "CHECKED_OUT", "CANCELLED")


def assert_per_diem_ledger(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "APPROVED", "PAID", "DISPUTED", "ADJUSTED")
    assert data["day_kind"] in ("TRAVEL_DAY", "GAME_DAY", "OFF_DAY", "PARTIAL_DAY")
    assert isinstance(data["base_amount_cents"], int)
    assert isinstance(data["deduction_cents"], int)
    assert isinstance(data["net_amount_cents"], int)


def assert_equipment_shipment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("STAGED", "LOADED", "IN_TRANSIT",
                              "DELIVERED", "DELAYED", "LOST")
    assert data["shipment_kind"] in ("TEAM_GEAR", "MEDICAL", "BROADCAST", "PERSONAL_BAGGAGE")
    assert isinstance(data["gross_weight_lb"], int)
    assert isinstance(data["chargeback_cents"], int)


def assert_contingency_event(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "MITIGATING", "RESOLVED", "CLOSED")
    assert data["kind"] in ("WEATHER", "MECHANICAL", "ATC_DELAY",
                            "VENUE_CHANGE", "SECURITY_INCIDENT")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")


def assert_credential_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "SECURITY_REVIEW", "APPROVED",
                              "DENIED", "REVOKED")
    assert data["access_level"] in ("FIELD", "LOCKER_ROOM", "PRESS",
                                    "BACK_OF_HOUSE", "ALL_ACCESS")


def assert_per_diem_money_invariants(ledger: dict):
    """PRD §3.8: net = max(0, base - deduction); deduction = meals * 2500."""
    assert ledger["deduction_cents"] == ledger["meals_provided_count"] * 2500
    assert ledger["net_amount_cents"] == max(
        0, ledger["base_amount_cents"] - ledger["deduction_cents"])
    assert ledger["net_amount_cents"] >= 0


def assert_season_budget_invariants(season: dict):
    """PRD §2.12: committed spend never exceeds the travel budget ceiling."""
    assert season["committed_cost_cents"] >= 0
    assert season["committed_cost_cents"] <= season["travel_budget_cents"]

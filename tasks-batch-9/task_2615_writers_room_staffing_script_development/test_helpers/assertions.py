"""Domain assertions for the writers-room staffing and script development API.

Structural helpers (identifier shape, timestamp shape, the common-field quartet)
plus the domain invariants the contract declares: seat-capacity conservation,
guarantee-slot conservation and the assignment ledger sum.
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# --- Structural --------------------------------------------------------------

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Assert the four common fields are present and well formed."""
    for field in COMMON_FIELDS:
        assert field in entity, f"Missing common field {field!r}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not ISO 8601: {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not ISO 8601: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, f"version must start at 1, got {entity['version']}"


def assert_ledger_common_fields(entry: Dict[str, Any]) -> None:
    """A fee ledger row carries id and created_at and nothing else from the quartet."""
    assert "id" in entry, f"Missing id: {entry}"
    assert "created_at" in entry, f"Missing created_at: {entry}"
    assert is_valid_uuid(entry["id"]), f"id is not a UUID: {entry['id']!r}"
    assert is_iso8601_timestamp(entry["created_at"]), (
        f"created_at is not ISO 8601: {entry['created_at']!r}"
    )
    assert "updated_at" not in entry, "A fee ledger row must not carry updated_at"
    assert "version" not in entry, "A fee ledger row must not carry a version field"


def assert_fields_absent(entity: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert field not in entity, f"Field {field!r} should be absent: {entity}"


def assert_field_values(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert each named field carries exactly the expected value."""
    for field, value in expected.items():
        assert field in entity, f"Missing field {field!r}: {entity}"
        assert entity[field] == value, (
            f"{field}: expected {value!r}, got {entity[field]!r}"
        )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating both the bare and the
    three-fractional-digit spelling of the same moment."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Assert a stamped timestamp field names the same instant as `expected`.

    The contract pins stored timestamps to three fractional digits while writing
    the logical clock's own landmarks without them, so the comparison is on the
    instant rather than on its spelling.
    """
    assert is_iso8601_timestamp(actual), f"{label} is not ISO 8601: {actual!r}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected the instant {expected}, got {actual!r}"
    )


def assert_end_of_day_stamp(value: str, expected_date: str) -> None:
    """Assert an ISO 8601 stamp is the end-of-day instant of `expected_date`."""
    assert value == f"{expected_date}T23:59:59.999Z", (
        f"Expected {expected_date}T23:59:59.999Z, got {value!r}"
    )


# --- Money ------------------------------------------------------------------

def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a money field is an integer count of cents equal to `expected`."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_seat_pricing(
    seat: Dict[str, Any],
    guild_floor_weekly_cents: int,
    weekly_compensation_cents: int,
    diversity_subsidy_weekly_cents: int,
    studio_charge_weekly_cents: int,
    prorated_commitment_cents: Optional[int] = None,
) -> None:
    """Assert the five derived money fields of a seat."""
    assert_cents(seat["guild_floor_weekly_cents"], guild_floor_weekly_cents, "guild_floor_weekly_cents")
    assert_cents(seat["weekly_compensation_cents"], weekly_compensation_cents, "weekly_compensation_cents")
    assert_cents(
        seat["diversity_subsidy_weekly_cents"],
        diversity_subsidy_weekly_cents,
        "diversity_subsidy_weekly_cents",
    )
    assert_cents(
        seat["studio_charge_weekly_cents"],
        studio_charge_weekly_cents,
        "studio_charge_weekly_cents",
    )
    if prorated_commitment_cents is not None:
        assert_cents(
            seat["prorated_commitment_cents"],
            prorated_commitment_cents,
            "prorated_commitment_cents",
        )


def assert_room_burn(
    room: Dict[str, Any],
    seat_subtotal_weekly_cents: int,
    facility_tier: str,
    facility_surcharge_weekly_cents: int,
    weekly_burn_cents: int,
) -> None:
    """Assert the four derived figures of the room weekly burn."""
    assert_cents(
        room["seat_subtotal_weekly_cents"],
        seat_subtotal_weekly_cents,
        "seat_subtotal_weekly_cents",
    )
    assert room["facility_tier"] == facility_tier, (
        f"facility_tier: expected {facility_tier}, got {room['facility_tier']}"
    )
    assert_cents(
        room["facility_surcharge_weekly_cents"],
        facility_surcharge_weekly_cents,
        "facility_surcharge_weekly_cents",
    )
    assert_cents(room["weekly_burn_cents"], weekly_burn_cents, "weekly_burn_cents")


def assert_assignment_settlement(
    assignment: Dict[str, Any],
    gross_fee_cents: int,
    guarantee_slot_applied: bool,
    guarantee_offset_cents: int,
    payable_fee_cents: int,
) -> None:
    """Assert the four guarantee-settlement outputs of an assignment."""
    assert_cents(assignment["gross_fee_cents"], gross_fee_cents, "gross_fee_cents")
    assert assignment["guarantee_slot_applied"] is guarantee_slot_applied, (
        f"guarantee_slot_applied: expected {guarantee_slot_applied}, "
        f"got {assignment['guarantee_slot_applied']!r}"
    )
    assert_cents(
        assignment["guarantee_offset_cents"],
        guarantee_offset_cents,
        "guarantee_offset_cents",
    )
    assert_cents(assignment["payable_fee_cents"], payable_fee_cents, "payable_fee_cents")


# --- Declared invariants ----------------------------------------------------

def assert_seat_capacity_conserved(room: Dict[str, Any]) -> None:
    """open_seat_count + filled_seat_count must equal seat_capacity."""
    assert room["open_seat_count"] + room["filled_seat_count"] == room["seat_capacity"], (
        "seat capacity identity violated: "
        f"open={room['open_seat_count']} filled={room['filled_seat_count']} "
        f"capacity={room['seat_capacity']}"
    )


def assert_guarantee_slots_conserved(seat: Dict[str, Any]) -> None:
    """consumed + remaining must equal the seat's episodic_guarantee_count."""
    assert (
        seat["guarantee_slots_consumed"] + seat["guarantee_slots_remaining"]
        == seat["episodic_guarantee_count"]
    ), (
        "guarantee slots identity violated: "
        f"consumed={seat['guarantee_slots_consumed']} "
        f"remaining={seat['guarantee_slots_remaining']} "
        f"count={seat['episodic_guarantee_count']}"
    )


def ledger_sum(entries: Iterable[Dict[str, Any]]) -> int:
    """Signed sum of amount_cents over the supplied ledger rows."""
    return sum(entry["amount_cents"] for entry in entries)


def assert_ledger_sum(entries: Iterable[Dict[str, Any]], expected: int) -> None:
    rows = list(entries)
    total = ledger_sum(rows)
    assert total == expected, (
        f"Ledger sum: expected {expected}, got {total} from "
        f"{[(e['entry_type'], e['amount_cents']) for e in rows]}"
    )


def entry_types(entries: Iterable[Dict[str, Any]]) -> List[str]:
    return [entry["entry_type"] for entry in entries]


# --- Pagination -------------------------------------------------------------

def assert_pagination_meta(
    meta: Dict[str, Any], total_count: int, has_more: bool, limit: int, offset: int
) -> None:
    assert meta["total_count"] == total_count, (
        f"total_count: expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"has_more: expected {has_more}, got {meta['has_more']!r}"
    )
    assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"


def assert_ordered_by(rows: List[Dict[str, Any]], field: str, descending: bool = False) -> None:
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"Rows are not ordered by {field} "
        f"{'descending' if descending else 'ascending'}: {values}"
    )


# --- Date helpers -----------------------------------------------------------

def iso_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def shift_date(value: str, days: int) -> str:
    """Return `value` shifted by `days` whole days, as a bare calendar date."""
    return (iso_date(value) + timedelta(days=days)).isoformat()


def shift_stamp(value: str, days: int) -> str:
    """Return `value` shifted by `days` whole days, as a midnight ISO 8601 instant."""
    return f"{shift_date(value, days)}T00:00:00Z"


def end_of_day(value: str) -> str:
    """Return the end-of-day ISO 8601 instant of the calendar day of `value`."""
    return f"{value[:10]}T23:59:59.999Z"


def day_span(start: str, end: str) -> int:
    """Whole days in the half-open interval [start, end)."""
    return (iso_date(end) - iso_date(start)).days


def find_by(rows: List[Dict[str, Any]], **match: Any) -> Dict[str, Any]:
    """Return the single row matching every key/value pair."""
    hits = [row for row in rows if all(row.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, f"Expected exactly one row matching {match}, got {len(hits)}"
    return hits[0]


def find_all(rows: List[Dict[str, Any]], **match: Any) -> List[Dict[str, Any]]:
    return [row for row in rows if all(row.get(k) == v for k, v in match.items())]

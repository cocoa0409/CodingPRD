"""Domain assertions and comparison helpers.

Numeric comparisons go through the approx helpers so that a value the PRD pins to
two or four decimal places is compared at that width rather than as an exact
float. Timestamps are compared as instants, so an implementation that renders
three fractional digits and one that renders none both satisfy the same
assertion.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CONSENT_CHANNELS,
    HOUSEHOLD_MAX_MEMBERS,
    SENSITIVE_SEGMENT_ATTRIBUTES,
)


# ----------------------------------------------------------------- numerics
def approx2(value: float):
    """A figure the PRD rounds half up to two decimal places."""
    return pytest.approx(value, abs=5e-3)


def approx4(value: float):
    """A figure the PRD rounds half up to four decimal places."""
    return pytest.approx(value, abs=5e-5)


def assert_json_number(value: Any, field: str) -> None:
    """The PRD requires every numeric to be a JSON number, never a string."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {type(value).__name__} {value!r}"
    )


def assert_decimal_width(value: float, places: int, field: str) -> None:
    """The stored figure must not carry more precision than the PRD allows."""
    assert_json_number(value, field)
    assert round(float(value), places) == pytest.approx(float(value), abs=1e-9), (
        f"{field} must carry at most {places} decimal places, got {value!r}"
    )


def assert_whole_cents(value: Any, field: str) -> None:
    """Money is carried as an exact integer count of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {type(value).__name__} {value!r}"
    )


# --------------------------------------------------------------- timestamps
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any fractional-second width."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str, field: str = "instant") -> None:
    """Two instants are equal regardless of how many fractional digits are rendered."""
    assert actual is not None, f"{field}: expected {expected}, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_utc_millisecond_timestamp(value: str, field: str = "timestamp") -> None:
    """The envelope timestamp is rendered in UTC with exactly three fractional digits."""
    assert is_iso8601_timestamp(value), f"{field} is not an ISO 8601 instant: {value!r}"
    assert value.endswith("Z"), f"{field} must end in Z: {value!r}"
    parts = value[:-1].split(".")
    assert len(parts) == 2 and len(parts[1]) == 3, (
        f"{field} must carry exactly three fractional digits: {value!r}"
    )


def plus_hours(instant: str, hours: int) -> str:
    return (parse_instant(instant) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_minutes(instant: str, minutes: int) -> str:
    return (parse_instant(instant) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_days(instant: str, days: int) -> str:
    return (parse_instant(instant) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_date_of(instant: str) -> str:
    """The UTC calendar date of an instant in year-month-day form."""
    return parse_instant(instant).strftime("%Y-%m-%d")


# ------------------------------------------------------------- common fields
def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries a UUID id, two UTC instants and an integer version."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID without a prefix: {row['id']!r}"
    assert_utc_millisecond_timestamp(row["created_at"], "created_at")
    assert_utc_millisecond_timestamp(row["updated_at"], "updated_at")
    assert isinstance(row["version"], int) and not isinstance(row["version"], bool), (
        f"version must be an integer, got {row['version']!r}"
    )
    assert row["version"] >= 1, f"version starts at 1, got {row['version']}"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """meta.api_request_id is prefixed req_ and the timestamp is a UTC instant."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert_utc_millisecond_timestamp(meta["api_request_timestamp"], "api_request_timestamp")


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str) -> None:
    """A refused call must leave these fields exactly as they were."""
    for field in fields:
        assert after.get(field) == before.get(field), (
            f"{field} changed from {before.get(field)!r} to {after.get(field)!r}"
        )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} on a call "
        "that should not have mutated the resource"
    )


# ------------------------------------------------------------------ ordering
def assert_ids_in_order(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"expected order {expected_ids}, got {actual}"


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """List results are ordered `created_at` ascending.

    The secondary key is deliberately not asserted here. The PRD's own rationale
    for the tie-break is "so that the profiles minted by a single promotion
    appear in the record processing order described in §3.3", and a server-minted
    UUID carries no ordering, so a faithful implementation cannot deliver both
    readings of that sentence at once. Only the `created_at` ordering the PRD
    states unconditionally is asserted.
    """
    stamps = [parse_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), (
        f"rows are not ordered created_at ASC: {stamps}"
    )


def assert_created_at_descending(rows: List[Dict[str, Any]]) -> None:
    stamps = [parse_instant(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps, reverse=True), (
        f"rows are not ordered created_at DESC: {stamps}"
    )


# ------------------------------------------------------------- source systems
def assert_new_source_system(row: Dict[str, Any], clock: str) -> None:
    """A freshly registered feed is REGISTERED with an untouched quality window."""
    assert_common_fields(row, expected_version=1)
    assert row["status"] == "REGISTERED"
    assert row["submitted_record_total"] == 0
    assert row["valid_record_total"] == 0
    assert row["dq_pass_rate"] == approx4(1.0)
    assert row["quarantine_count"] == 0
    assert row["last_reinstated_at"] is None
    assert_instant_equals(row["dq_window_start_at"], clock, "dq_window_start_at")


# ------------------------------------------------------------------- profiles
def assert_profile_axes(
    profile: Dict[str, Any], resolution_status: str, privacy_status: str
) -> None:
    """The two profile state axes are independent and are asserted together."""
    assert profile["resolution_status"] == resolution_status, (
        f"expected resolution_status {resolution_status}, got {profile['resolution_status']}"
    )
    assert profile["privacy_status"] == privacy_status, (
        f"expected privacy_status {privacy_status}, got {profile['privacy_status']}"
    )


def assert_activatable(profile: Dict[str, Any], channels: List[str]) -> None:
    """activatable_channels is sorted alphabetically ascending; the score is count/5."""
    expected = sorted(channels)
    assert profile["activatable_channels"] == expected, (
        f"expected activatable_channels {expected}, got {profile['activatable_channels']}"
    )
    assert profile["channel_engagement_score"] == approx2(len(expected) / 5), (
        f"expected channel_engagement_score {len(expected) / 5:.2f}, "
        f"got {profile['channel_engagement_score']}"
    )


def assert_tombstoned_identifiers(profile: Dict[str, Any]) -> None:
    """The seven fields an erasure nulls on the subject."""
    for field in (
        "email_norm",
        "phone_norm",
        "first_name",
        "last_name",
        "inferred_health_interest",
        "inferred_ethnicity_affinity",
        "precise_geolocation_grid",
    ):
        assert profile[field] is None, f"{field} must be nulled by the tombstone"


# ----------------------------------------------------------------- households
def assert_household_capacity(household: Dict[str, Any]) -> None:
    assert household["member_count"] <= HOUSEHOLD_MAX_MEMBERS, (
        f"a household holds at most {HOUSEHOLD_MAX_MEMBERS} members, "
        f"got {household['member_count']}"
    )


# --------------------------------------------------------------- match rules
def expected_precision(confirmed: int, rejected: int) -> float:
    """confirmed / (confirmed + rejected), held at exactly 1.0 while the denominator is 0."""
    denominator = confirmed + rejected
    if denominator == 0:
        return 1.0
    return round(confirmed / denominator + 1e-12, 4)


def assert_new_match_rule(row: Dict[str, Any]) -> None:
    assert_common_fields(row, expected_version=1)
    assert row["status"] == "ENABLED"
    assert row["confirmed_count"] == 0
    assert row["rejected_count"] == 0
    assert row["precision_estimate"] == approx4(1.0)


# -------------------------------------------------------------------- consent
def channel_resolution(state: Dict[str, Any], channel: str) -> Dict[str, Any]:
    """One channel's entry out of the computed consent-state read."""
    matches = [c for c in state["channels"] if c["channel"] == channel]
    assert len(matches) == 1, f"expected exactly one entry for {channel}, got {matches}"
    return matches[0]


def assert_all_five_channels_present(state: Dict[str, Any]) -> None:
    reported = sorted(c["channel"] for c in state["channels"])
    assert reported == sorted(CONSENT_CHANNELS), (
        f"the read must resolve all five channels, got {reported}"
    )


# ------------------------------------------------------------------- segments
def expected_uses_sensitive(criteria: List[Dict[str, Any]]) -> bool:
    return any(c["attribute"] in SENSITIVE_SEGMENT_ATTRIBUTES for c in criteria)


def assert_new_segment(row: Dict[str, Any]) -> None:
    assert_common_fields(row, expected_version=1)
    assert row["status"] == "DRAFT"
    assert row["sensitive_use_approved"] is False
    assert row["rejection_count"] == 0
    assert row["active_activation_count"] == 0
    assert row["submitted_by_user_id"] is None
    assert row["decided_by_user_id"] is None
    assert row["approved_at"] is None
    assert row["governance_expires_at"] is None


# ---------------------------------------------------------------- activations
def assert_draft_activation(row: Dict[str, Any]) -> None:
    """A new activation is DRAFT with every audience and rate field at its default."""
    assert_common_fields(row, expected_version=1)
    assert row["status"] == "DRAFT"
    assert row["candidate_count"] == 0
    assert row["audience_size"] == 0
    assert row["suppressed_count"] == 0
    assert row["dispatched_hash_count"] == 0
    assert row["vendor_matched_count"] == 0
    assert row["unusable_hash_count"] == 0
    assert row["gross_match_rate"] is None
    assert row["net_match_rate"] is None
    assert row["effective_match_rate"] is None
    assert row["dispatched_at"] is None
    assert row["paused_reason"] is None
    assert row["terminated_at"] is None
    assert row["attributed_conversions"] == []
    assert row["attributed_conversion_count"] == 0


def expected_gross_rate(vendor_matched: int, dispatched: int) -> float:
    """vendor_matched / dispatched, exactly 0.0000 where nothing was dispatched."""
    if dispatched == 0:
        return 0.0
    return round(vendor_matched / dispatched + 1e-12, 4)


def expected_net_rate(vendor_matched: int, dispatched: int, unusable: int) -> float:
    """vendor_matched / (dispatched - unusable), exactly 0.0000 where that is not positive."""
    usable = dispatched - unusable
    if usable <= 0:
        return 0.0
    return round(vendor_matched / usable + 1e-12, 4)


def assert_quota_conserved(
    destination: Dict[str, Any], consumed_by_delivering_activations: int
) -> None:
    """remaining == daily_hash_quota less the hashes held by delivering activations."""
    expected = destination["daily_hash_quota"] - consumed_by_delivering_activations
    assert destination["remaining_daily_hash_quota"] == expected, (
        f"expected remaining_daily_hash_quota {expected}, "
        f"got {destination['remaining_daily_hash_quota']}"
    )


# ------------------------------------------------------------------- erasure
def assert_task_counters(request_row: Dict[str, Any], **expected: int) -> None:
    """The five counters are derived from the request's children at all times."""
    for field, value in expected.items():
        assert request_row[field] == value, (
            f"expected {field} {value}, got {request_row[field]}"
        )
    derived = (
        request_row["pending_vendor_task_count"]
        + request_row["acknowledged_vendor_task_count"]
        + request_row["failed_vendor_task_count"]
        + request_row["timed_out_vendor_task_count"]
    )
    assert derived == request_row["total_vendor_task_count"], (
        "the four per-status counters must sum to total_vendor_task_count: "
        f"{derived} != {request_row['total_vendor_task_count']}"
    )


def sum_lifetime_value(profiles: List[Dict[str, Any]]) -> int:
    """The visible money total: cents over profiles that are not merged away."""
    return sum(
        p["lifetime_value_cents"] for p in profiles if p["resolution_status"] != "MERGED_AWAY"
    )

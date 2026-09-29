"""Domain assertions layered over the framework validators.

These helpers exist so that a repeated contract obligation — the shape of the
common field block, the precision of a score, the ordering of a listing — is
stated once and referenced everywhere.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from . import constants as C


# --------------------------------------------------------------------------
# Common field block
# --------------------------------------------------------------------------

def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Assert the id / created_at / updated_at / version block.

    Identifiers are bare UUIDs with no prefix, timestamps are ISO 8601 in UTC
    with exactly three fractional-second digits, and version is an integer.
    """
    assert "id" in entity, "entity is missing id"
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert_utc_millis_timestamp(entity["created_at"])
    assert_utc_millis_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"


def assert_consent_event_fields(event: Dict[str, Any]) -> None:
    """Assert the reduced field block an immutable consent event carries.

    A consent event is never updated after it is appended, so it exposes only
    an identifier and a creation timestamp.
    """
    assert is_valid_uuid(event["id"]), f"id is not a bare UUID: {event['id']!r}"
    assert_utc_millis_timestamp(event["created_at"])
    assert "updated_at" not in event, "an immutable event must not carry updated_at"
    assert "version" not in event, "an immutable event must not carry version"


def assert_utc_millis_timestamp(value: Any) -> None:
    """Assert a timestamp is ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    assert value.endswith("Z"), f"timestamp must be expressed in UTC: {value!r}"
    assert "." in value, f"timestamp must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"timestamp must carry exactly three fractional digits: {value!r}")


def assert_version_is(entity: Dict[str, Any], expected: int) -> None:
    """Assert a row sits at an exact version."""
    assert entity["version"] == expected, (
        f"expected version {expected}, got {entity['version']}")


def assert_version_advanced_by_one(before: Dict[str, Any],
                                   after: Dict[str, Any]) -> None:
    """Assert exactly one increment separates two observations of a row."""
    assert after["version"] == before["version"] + 1, (
        f"expected version {before['version'] + 1}, got {after['version']}")


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """Assert a read or a refused write left the version alone."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']}")


# --------------------------------------------------------------------------
# Numeric precision
# --------------------------------------------------------------------------

def assert_score(actual: Any, expected: float) -> None:
    """Assert a two-decimal score."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"expected score {expected}, got {actual}")


def assert_cents(actual: Any, expected: int) -> None:
    """Assert a whole-cent money amount, carried as an integer."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"money must be an integer count of cents, got {actual!r}")
    assert actual == expected, f"expected {expected} cents, got {actual}"


def assert_bps(actual: Any, expected: int) -> None:
    """Assert a rate expressed in integer basis points."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"a basis-point rate must be an integer, got {actual!r}")
    assert actual == expected, f"expected {expected} bps, got {actual}"


def assert_count(actual: Any, expected: int) -> None:
    """Assert an integer tally."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"a count must be an integer, got {actual!r}")
    assert actual == expected, f"expected {expected}, got {actual}"


# --------------------------------------------------------------------------
# Listings
# --------------------------------------------------------------------------

def assert_page(response, expected_total: Optional[int] = None,
                expected_len: Optional[int] = None,
                expected_has_more: Optional[bool] = None,
                expected_limit: Optional[int] = None,
                expected_offset: Optional[int] = None):
    """Validate a listing envelope and optionally pin its window figures."""
    items, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"expected total_count {expected_total}, got {meta['total_count']}")
    if expected_len is not None:
        assert len(items) == expected_len, (
            f"expected {expected_len} rows on the page, got {len(items)}")
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"expected has_more {expected_has_more}, got {meta['has_more']}")
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"expected limit {expected_limit}, got {meta['limit']}")
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"expected offset {expected_offset}, got {meta['offset']}")
    return items, meta


def assert_single_read_omits_page_meta(response) -> Dict[str, Any]:
    """Assert a single-resource read carries no pagination figures."""
    body = response.json()
    meta = body.get("meta", {})
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in meta, (
            f"a single-resource read must not report {key}")
    return validate_success(response)


def assert_ordered_by_created_at(items: List[Dict[str, Any]]) -> None:
    """Assert a listing is oldest-first by creation timestamp."""
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), (
        f"listing is not ascending by created_at: {stamps}")


def assert_consent_log_order(events: List[Dict[str, Any]]) -> None:
    """Assert a consent log is ordered by creation then sequence number."""
    keys = [(event["created_at"], event["sequence_no"]) for event in events]
    assert keys == sorted(keys), (
        f"consent log is not ordered by created_at then sequence_no: {keys}")


def assert_ids_equal(items: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    """Assert a listing holds exactly these rows, in this order."""
    actual = [item["id"] for item in items]
    assert actual == expected_ids, f"expected rows {expected_ids}, got {actual}"


def assert_id_set(items: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    """Assert a listing holds exactly these rows, order irrelevant."""
    assert set(item["id"] for item in items) == set(expected_ids)


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------

def assert_envelope_metadata(response) -> None:
    """Assert the correlation block every response carries."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
    assert isinstance(meta["api_request_timestamp"], str)
    assert body["response_type"] in ("object", "array")


def assert_created(response) -> Dict[str, Any]:
    """Validate a creation response and its common field block."""
    data = validate_success(response, expected_status=201)
    assert_common_fields(data)
    return data


def assert_ok(response) -> Dict[str, Any]:
    """Validate a plain success response."""
    return validate_success(response, expected_status=200)


# --------------------------------------------------------------------------
# Domain shorthands
# --------------------------------------------------------------------------

def assert_field(entity: Dict[str, Any], field: str, expected: Any) -> None:
    assert entity[field] == expected, (
        f"expected {field} {expected!r}, got {entity[field]!r}")


def assert_instant_field(entity: Dict[str, Any], field: str,
                         expected_iso: str) -> None:
    """Assert a timestamp field denotes the expected instant.

    The PRD pins the *instant* a window bound carries, not the lexical form the
    server echoes it back in: rung 5 accepts any body timestamp "parseable as
    ISO 8601 UTC", so `...:00Z` and `...:00.000Z` are the same accepted input and
    either is a faithful rendering on the way out. Compare the parsed instants.
    """
    actual = entity[field]
    assert isinstance(actual, str), f"{field} must be a string, got {actual!r}"

    def _parse(value: str) -> datetime:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)

    assert _parse(actual) == _parse(expected_iso), (
        f"expected {field} at instant {expected_iso}, got {actual}")


def assert_absent_or_none(entity: Dict[str, Any], field: str) -> None:
    assert entity.get(field) is None, (
        f"expected {field} to be unset, got {entity.get(field)!r}")


def assert_touch_ledger(supporter: Dict[str, Any], consumed: int,
                        reserved: int) -> None:
    """Assert a supporter's touch ledger sits at exact consumed/reserved counts."""
    assert_count(supporter["touches_consumed"], consumed)
    assert_count(supporter["touches_reserved"], reserved)


def assert_within_cap(value: float, cap: float) -> None:
    """Assert a clamped figure did not exceed its ceiling."""
    assert value <= cap, f"{value} exceeds the ceiling {cap}"


def assert_channel_consent_states(supporter: Dict[str, Any], email: str, sms: str,
                                 phone: str) -> None:
    """Assert the replayed consent state of all three channels at once."""
    assert_field(supporter, "email_consent_state", email)
    assert_field(supporter, "sms_consent_state", sms)
    assert_field(supporter, "phone_consent_state", phone)


def assert_unknown_uuid_shape() -> None:
    """Assert the probe identifier the suite uses really is a well-formed UUID."""
    assert is_valid_uuid(C.UNKNOWN_UUID)

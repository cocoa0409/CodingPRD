"""Domain assertion helpers for the Cosmetics API.

Every helper here checks something the PRD states about a resource shape, a
derived number or a ledger sequence, so individual tests can stay focused on
the rule they exist to prove.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as K

MONEY_TOLERANCE = 0.01


def assert_two_decimal_value(actual: Any, expected: float, label: str = "value") -> None:
    """A score-style quantity is carried to two decimal places."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_identity_fields(resource: Dict[str, Any], label: str = "resource") -> None:
    """The id is a server-minted UUID with no type prefix, plus audit columns."""
    assert is_valid_uuid(resource["id"]), f"{label}.id must be a UUID: {resource['id']}"
    assert is_iso8601_timestamp(resource["created_at"]), (
        f"{label}.created_at must be an ISO 8601 timestamp: {resource['created_at']}"
    )
    assert is_iso8601_timestamp(resource["updated_at"]), (
        f"{label}.updated_at must be an ISO 8601 timestamp: {resource['updated_at']}"
    )
    assert isinstance(resource["version"], int), f"{label}.version must be an integer"


def assert_fresh_resource(resource: Dict[str, Any], label: str = "resource") -> None:
    """A brand-new resource starts at version 1."""
    assert_identity_fields(resource, label)
    assert resource["version"] == 1, f"{label}.version must start at 1"


def assert_version_is(resource: Dict[str, Any], expected: int, label: str = "resource") -> None:
    assert resource["version"] == expected, (
        f"{label}.version: expected {expected}, got {resource['version']}"
    )


def assert_ledger_entry_shape(entry: Dict[str, Any]) -> None:
    """Ledger entries carry only id and created_at from the audit columns."""
    assert is_valid_uuid(entry["id"]), "ledger entry id must be a UUID"
    assert "updated_at" not in entry, "a ledger entry must not carry updated_at"
    assert "version" not in entry, "a ledger entry must not carry version"
    assert entry["entry_type"] in K.LEDGER_ENTRY_TYPES, (
        f"unknown ledger entry_type {entry['entry_type']}"
    )
    assert entry["subject_entity"] in K.SUBJECT_ENTITIES, (
        f"unknown ledger subject_entity {entry['subject_entity']}"
    )
    assert isinstance(entry["sequence_no"], int) and entry["sequence_no"] >= 1


def assert_ledger_sequence_numbers(entries: List[Dict[str, Any]]) -> None:
    """sequence_no is a 1-based monotonic counter per establishment."""
    numbers = [e["sequence_no"] for e in entries]
    assert numbers == sorted(numbers), f"ledger must read back in append order: {numbers}"
    if numbers:
        assert numbers[0] >= 1


def assert_entry_types_in_order(entries: List[Dict[str, Any]],
                                expected_types: List[str]) -> None:
    """The ledger's entry types appear in exactly the given order."""
    actual = [e["entry_type"] for e in entries]
    assert actual == expected_types, (
        f"expected ledger order {expected_types}, got {actual}"
    )


def assert_posture_change_entry(entry: Dict[str, Any], before: str, after: str) -> None:
    assert entry["entry_type"] == K.ENTRY_TYPE_POSTURE_CHANGE
    assert entry["posture_before"] == before, (
        f"posture_before: expected {before}, got {entry['posture_before']}"
    )
    assert entry["posture_after"] == after, (
        f"posture_after: expected {after}, got {entry['posture_after']}"
    )


def assert_non_posture_entry_nulls(entry: Dict[str, Any]) -> None:
    """Outside a POSTURE_CHANGE entry both posture fields are null."""
    assert entry["posture_before"] is None
    assert entry["posture_after"] is None


def assert_unit_movement_delta(entry: Dict[str, Any], expected_delta: int) -> None:
    assert entry["entry_type"] == K.ENTRY_TYPE_UNIT_MOVEMENT
    assert entry["signed_units_delta"] == expected_delta, (
        f"signed_units_delta: expected {expected_delta}, got {entry['signed_units_delta']}"
    )


def assert_facility_defaults(facility: Dict[str, Any]) -> None:
    """Every declared default of a newly created establishment."""
    assert facility["registration_status"] == K.REGISTRATION_STATUS_DRAFT
    assert facility["compliance_posture"] == K.POSTURE_OPEN
    assert_two_decimal_value(facility["serious_event_points"], 0.00, "serious_event_points")
    assert facility["registration_cycle_count"] == 0
    assert facility["abbreviated_renewal_eligible"] is True
    assert facility["listed_product_count"] == 0
    assert facility["open_serious_event_count"] == 0
    for field in (
        "facility_fei",
        "gmp_readiness_score",
        "last_inspection_outcome",
        "current_period_start",
        "current_period_end",
        "renewal_window_open_date",
        "grace_end_date",
    ):
        assert facility[field] is None, f"facility.{field} must start null"
    assert facility["version"] == 1


def assert_listing_defaults(listing: Dict[str, Any]) -> None:
    """Every declared default of a freshly created listing."""
    assert listing["listing_status"] == K.LISTING_STATUS_DRAFT
    assert listing["safety_status"] == K.SAFETY_STATUS_UNSUBSTANTIATED
    assert listing["listing_number"] is None
    assert listing["suspension_reason"] is None
    assert listing["allergen_disclosure_complete"] is True
    assert listing["undisclosed_allergen_count"] == 0
    assert listing["distributed_units_total"] == 0
    assert listing["open_recall_count"] == 0
    assert listing["open_serious_event_count"] == 0
    assert listing["marketable"] is False
    assert listing["version"] == 1


def assert_fei_format(facility_fei: str, ordinal: int) -> None:
    """facility_fei is FEI- plus a six-digit zero-padded ordinal."""
    expected = f"{K.FEI_PREFIX}{ordinal:06d}"
    assert facility_fei == expected, f"expected {expected}, got {facility_fei}"


def assert_listing_number_format(listing_number: str, ordinal: int) -> None:
    """listing_number is CPL- plus a six-digit zero-padded ordinal."""
    expected = f"{K.LISTING_NUMBER_PREFIX}{ordinal:06d}"
    assert listing_number == expected, f"expected {expected}, got {listing_number}"


def assert_period_bounds(period: Dict[str, Any], start: str, end: str,
                         renewal_open: str, grace_end: str) -> None:
    assert period["period_start"] == start
    assert period["period_end"] == end
    assert period["renewal_window_open_date"] == renewal_open
    assert period["grace_end_date"] == grace_end


def assert_facility_period_mirror(facility: Dict[str, Any], start: str, end: str,
                                  renewal_open: str, grace_end: str) -> None:
    assert facility["current_period_start"] == start
    assert facility["current_period_end"] == end
    assert facility["renewal_window_open_date"] == renewal_open
    assert facility["grace_end_date"] == grace_end


def assert_deadline_at_end_of_day(deadline_at: str, expected_date: str) -> None:
    """A deadline derived from a calendar date is pinned to 23:59:59.999Z."""
    assert deadline_at == f"{expected_date}T23:59:59.999Z", (
        f"expected {expected_date}T23:59:59.999Z, got {deadline_at}"
    )


def assert_category_subscores(subscores: Dict[str, Any], expected: Dict[str, float]) -> None:
    """All five categories are scored, including those with no findings."""
    assert set(subscores.keys()) == set(K.OBSERVATION_CATEGORIES), (
        f"category_subscores must key all five categories, got {sorted(subscores)}"
    )
    for category, value in expected.items():
        assert_two_decimal_value(subscores[category], value, f"category_subscores.{category}")


def assert_record_unit_balance(record: Dict[str, Any]) -> None:
    """units_verified_returned + units_verified_destroyed + units_outstanding == units_shipped."""
    total = (
        record["units_verified_returned"]
        + record["units_verified_destroyed"]
        + record["units_outstanding"]
    )
    assert total == record["units_shipped"], (
        "record out of balance: verified + outstanding "
        f"({total}) != units_shipped ({record['units_shipped']})"
    )


def assert_no_pagination_fields(meta: Dict[str, Any]) -> None:
    """Single-resource responses omit the four pagination fields."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"single-resource meta must omit {field}"


def assert_sweep_counters(result: Dict[str, Any], **expected: int) -> None:
    """Assert named sweep counters, defaulting every unnamed counter to 0."""
    for key in K.SWEEP_COUNTER_KEYS:
        want = expected.get(key, 0)
        assert result[key] == want, f"{key}: expected {want}, got {result[key]}"


def find_entries(entries: List[Dict[str, Any]], entry_type: str) -> List[Dict[str, Any]]:
    return [e for e in entries if e["entry_type"] == entry_type]


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def find_by_id(rows: List[Dict[str, Any]], target_id: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row["id"] == target_id:
            return row
    return None

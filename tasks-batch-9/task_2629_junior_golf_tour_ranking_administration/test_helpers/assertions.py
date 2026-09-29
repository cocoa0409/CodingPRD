"""Domain assertions expressed in the language of the junior golf tour."""

from decimal import Decimal

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ------------------------------------------------------- identity and stamps
def assert_identity_fields(entity, expected_version=None):
    """Every entity carries an id, creation and update stamps, and a row version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO-8601 instant: {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not an ISO-8601 instant: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_version_is(entity, expected_version):
    assert entity["version"] == expected_version, (
        f"expected version {expected_version}, got {entity['version']}"
    )


# ------------------------------------------------------------------- money
def assert_cents(actual, expected, label="amount"):
    """Money is carried in whole cents, so the comparison is exact."""
    assert isinstance(actual, int), f"{label} must be whole cents, got {actual!r}"
    assert actual == expected, f"expected {label} {expected}, got {actual}"


def assert_ledger(season, available=None, committed=None, disbursed=None):
    if available is not None:
        assert_cents(season["assistance_available_cents"], available, "available")
    if committed is not None:
        assert_cents(season["assistance_committed_cents"], committed, "committed")
    if disbursed is not None:
        assert_cents(season["assistance_disbursed_cents"], disbursed, "disbursed")


def assert_ledger_conserved(season, budget):
    """The three buckets always add back up to the seeded budget."""
    total = (
        season["assistance_available_cents"]
        + season["assistance_committed_cents"]
        + season["assistance_disbursed_cents"]
    )
    assert total == budget, (
        f"assistance buckets sum to {total}, not the seeded budget {budget}"
    )


# ---------------------------------------------------------------- precision
def assert_two_decimals(value, expected, label="value"):
    """Ranking and field-quality figures are carried to two decimal places."""
    assert value == pytest.approx(expected, abs=0.005), (
        f"expected {label} {expected}, got {value}"
    )
    quantised = Decimal(str(value))
    assert -quantised.as_tuple().exponent <= 2, (
        f"{label} carries more than two decimals: {value}"
    )


def assert_one_decimal(value, expected, label="differential"):
    """Scoring differentials are carried to one decimal place."""
    assert value == pytest.approx(expected, abs=0.005), (
        f"expected {label} {expected}, got {value}"
    )
    quantised = Decimal(str(value))
    assert -quantised.as_tuple().exponent <= 1, (
        f"{label} carries more than one decimal: {value}"
    )


# ------------------------------------------------------------------ statuses
def assert_tournament_status(tournament, expected):
    assert tournament["status"] == expected, (
        f"expected tournament status {expected}, got {tournament['status']}"
    )


def assert_entry_status(entry, expected):
    assert entry["entry_status"] == expected, (
        f"expected entry status {expected}, got {entry['entry_status']}"
    )


def assert_fee_status(entry, expected):
    assert entry["fee_status"] == expected, (
        f"expected fee status {expected}, got {entry['fee_status']}"
    )


def assert_round_status(round_row, expected):
    assert round_row["status"] == expected, (
        f"expected round status {expected}, got {round_row['status']}"
    )


def assert_member_eligibility(member, expected):
    assert member["eligibility_status"] == expected, (
        f"expected eligibility {expected}, got {member['eligibility_status']}"
    )


def assert_grant_status(grant, expected):
    assert grant["status"] == expected, (
        f"expected grant status {expected}, got {grant['status']}"
    )


# -------------------------------------------------------------- slot census
def assert_slot_census(tournament, entry_count=None, applied_count=None,
                       accepted_count=None, waitlist_count=None, closed_count=None,
                       finished_count=None, open_slot_count=None):
    checks = {
        "entry_count": entry_count,
        "applied_count": applied_count,
        "accepted_count": accepted_count,
        "waitlist_count": waitlist_count,
        "closed_count": closed_count,
        "finished_count": finished_count,
        "open_slot_count": open_slot_count,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert tournament[field] == expected, (
                f"expected {field} {expected}, got {tournament[field]}"
            )


def assert_slot_census_balances(tournament):
    """Applied, accepted, waitlisted and closed entries account for every entry."""
    parts = (
        tournament["applied_count"]
        + tournament["accepted_count"]
        + tournament["waitlist_count"]
        + tournament["closed_count"]
    )
    assert parts == tournament["entry_count"], (
        f"census parts sum to {parts} but entry_count is {tournament['entry_count']}"
    )


def assert_open_slots(tournament):
    """Open slots are the field cap less the entries holding a playing slot."""
    expected = tournament["field_size_limit"] - tournament["accepted_count"]
    expected = max(0, expected)
    assert tournament["open_slot_count"] == expected, (
        f"expected open_slot_count {expected}, got {tournament['open_slot_count']}"
    )


# ------------------------------------------------------------------ listings
def assert_pagination_meta(meta, limit=None, offset=None, total_count=None,
                           has_more=None):
    checks = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert meta[field] == expected, (
                f"expected meta.{field} {expected}, got {meta[field]}"
            )


def assert_ordered_by_created_at(rows):
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at order: {stamps}"

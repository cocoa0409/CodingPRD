"""
Domain assertions for the standards-development consensus API.

These wrap the rules the PRD states once and every test then relies on: the four
common fields, one-decimal percentage rounding, the two conserved quantities (the
ballot seat ledger and the comment disposition ledger), the balance triple and the
window arithmetic.
"""

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import RESOURCE_FIELDS


# --------------------------------------------------------------- representations
def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None):
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource.get('id')}"
    assert is_iso8601_timestamp(resource["created_at"]), (
        f"created_at is not ISO 8601: {resource.get('created_at')}"
    )
    assert is_iso8601_timestamp(resource["updated_at"]), (
        f"updated_at is not ISO 8601: {resource.get('updated_at')}"
    )
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"Expected version {expected_version}, got {resource['version']}"
        )


def assert_has_fields(resource: Dict[str, Any], resource_type: str):
    """The representation exposes every field the PRD lists for this resource."""
    missing = [f for f in RESOURCE_FIELDS[resource_type] if f not in resource]
    assert not missing, f"{resource_type} representation missing fields: {missing}"


# -------------------------------------------------------------------- arithmetic
def round_half_up(value, places: int = 1) -> float:
    """Round half-up to the given number of decimals, as the PRD prescribes."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def assert_pct(actual, expected, places: int = 1):
    """A percentage is reported rounded half-up to one decimal place."""
    assert actual is not None, "Expected a percentage, got null"
    assert round_half_up(actual, places) == round_half_up(expected, places), (
        f"Expected {expected} at {places} decimals, got {actual}"
    )


def assert_ratio(actual, expected):
    """substantive_change_ratio is reported to four decimal places."""
    assert actual is not None, "Expected a ratio, got null"
    assert round_half_up(actual, 4) == round_half_up(expected, 4), (
        f"Expected ratio {expected}, got {actual}"
    )


# ------------------------------------------------------------ conserved quantity
def assert_seat_conservation(ballot: Dict[str, Any]):
    """
    The four position buckets always account for every eligible seat, and
    returned_count is the three cast buckets summed.
    """
    affirmative = ballot["affirmative_count"]
    negative = ballot["negative_count"]
    abstain = ballot["abstain_count"]
    returned = ballot["returned_count"]
    not_returned = ballot["not_returned_count"]
    eligible = ballot["eligible_voter_count"]
    assert affirmative + negative + abstain == returned, (
        f"returned_count {returned} != {affirmative}+{negative}+{abstain}"
    )
    assert returned + not_returned == eligible, (
        f"returned_count + not_returned_count ({returned}+{not_returned}) "
        f"!= eligible_voter_count {eligible}"
    )


def assert_seat_ledger(
    ballot: Dict[str, Any],
    affirmative: int,
    negative: int,
    abstain: int,
    returned: int,
    not_returned: int,
    eligible: int,
):
    """Assert every seat counter at once, then the conservation identity."""
    assert ballot["affirmative_count"] == affirmative, (
        f"affirmative_count expected {affirmative}, got {ballot['affirmative_count']}"
    )
    assert ballot["negative_count"] == negative, (
        f"negative_count expected {negative}, got {ballot['negative_count']}"
    )
    assert ballot["abstain_count"] == abstain, (
        f"abstain_count expected {abstain}, got {ballot['abstain_count']}"
    )
    assert ballot["returned_count"] == returned, (
        f"returned_count expected {returned}, got {ballot['returned_count']}"
    )
    assert ballot["not_returned_count"] == not_returned, (
        f"not_returned_count expected {not_returned}, got {ballot['not_returned_count']}"
    )
    assert ballot["eligible_voter_count"] == eligible, (
        f"eligible_voter_count expected {eligible}, got {ballot['eligible_voter_count']}"
    )
    assert_seat_conservation(ballot)


def assert_comment_ledger_conservation(review: Dict[str, Any]):
    """disposed_count + unresolved_comment_count always equals comment_count."""
    disposed = review["disposed_count"]
    unresolved = review["unresolved_comment_count"]
    total = review["comment_count"]
    assert disposed + unresolved == total, (
        f"disposed_count + unresolved_comment_count ({disposed}+{unresolved}) "
        f"!= comment_count {total}"
    )


def assert_comment_ledger(
    review: Dict[str, Any],
    comment_count: int,
    disposed_count: int,
    unresolved_count: int,
    completeness_pct: float,
):
    """Assert the whole disposition ledger plus its conservation identity."""
    assert review["comment_count"] == comment_count, (
        f"comment_count expected {comment_count}, got {review['comment_count']}"
    )
    assert review["disposed_count"] == disposed_count, (
        f"disposed_count expected {disposed_count}, got {review['disposed_count']}"
    )
    assert review["unresolved_comment_count"] == unresolved_count, (
        f"unresolved_comment_count expected {unresolved_count}, "
        f"got {review['unresolved_comment_count']}"
    )
    assert_pct(review["disposition_completeness_pct"], completeness_pct)
    assert_comment_ledger_conservation(review)


# ----------------------------------------------------------------------- balance
def assert_voting_balance(
    committee: Dict[str, Any],
    balance_status: str,
    active_member_count: int,
    distinct_category_count: int,
    dominance_pct: float,
    category_counts: Optional[Dict[str, int]] = None,
):
    """The voting-basis balance triple plus its status."""
    assert committee["balance_status"] == balance_status, (
        f"balance_status expected {balance_status}, got {committee['balance_status']}"
    )
    assert committee["active_member_count"] == active_member_count, (
        f"active_member_count expected {active_member_count}, "
        f"got {committee['active_member_count']}"
    )
    assert committee["distinct_category_count"] == distinct_category_count, (
        f"distinct_category_count expected {distinct_category_count}, "
        f"got {committee['distinct_category_count']}"
    )
    assert_pct(committee["dominance_pct"], dominance_pct)
    if category_counts is not None:
        assert committee["category_counts"] == category_counts, (
            f"category_counts expected {category_counts}, got {committee['category_counts']}"
        )


def assert_roster_balance(
    committee: Dict[str, Any],
    roster_balance_status: str,
    roster_member_count: int,
    roster_dominance_pct: float,
):
    """The roster-basis balance triple plus its status."""
    assert committee["roster_balance_status"] == roster_balance_status, (
        f"roster_balance_status expected {roster_balance_status}, "
        f"got {committee['roster_balance_status']}"
    )
    assert committee["roster_member_count"] == roster_member_count, (
        f"roster_member_count expected {roster_member_count}, "
        f"got {committee['roster_member_count']}"
    )
    assert_pct(committee["roster_dominance_pct"], roster_dominance_pct)


# ------------------------------------------------------------------------- dates
def iso_date(value: str) -> date:
    """Parse a plain calendar date."""
    return date.fromisoformat(value)


def iso_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant written with a trailing Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def inclusive_day_span(start: str, end: str) -> int:
    """Days in a closed inclusive calendar window, counting both endpoints."""
    return (iso_date(end) - iso_date(start)).days + 1


def shift_date(value: str, days: int) -> str:
    """A calendar date shifted by whole days, rendered back to ISO."""
    return (iso_date(value) + timedelta(days=days)).isoformat()


def shift_instant(value: str, days: int) -> str:
    """A UTC instant shifted by whole days, rendered back with a trailing Z."""
    moved = iso_instant(value) + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def assert_same_instant(actual: str, expected: str):
    """Two ISO 8601 instants denote the same moment."""
    assert actual is not None, f"Expected instant {expected}, got null"
    assert iso_instant(actual) == iso_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_date_equals(actual: str, expected: str):
    """Two calendar dates are the same day."""
    assert actual is not None, f"Expected date {expected}, got null"
    assert iso_date(actual) == iso_date(expected), (
        f"Expected date {expected}, got {actual}"
    )


# ------------------------------------------------------------------ misc helpers
def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], fields: Iterable[str]):
    """A rejected write left the named fields exactly as they were."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{field} changed from {before.get(field)} to {after.get(field)}"
        )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]):
    """A rejected write did not consume a version."""
    assert before["version"] == after["version"], (
        f"version moved from {before['version']} to {after['version']} "
        "on a request that should have changed nothing"
    )


def assert_total_count(meta: Dict[str, Any], expected: int):
    """A list response reports the expected total_count."""
    assert meta["total_count"] == expected, (
        f"Expected total_count {expected}, got {meta['total_count']}"
    )

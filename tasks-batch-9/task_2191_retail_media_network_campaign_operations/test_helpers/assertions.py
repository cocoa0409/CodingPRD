"""Domain assertions and arithmetic helpers for the retail media network API.

Two families live here.

The first is the invariant assertions. The PRD states two conservation ledgers and a
set of derived counts that must always equal the population they are defined over, so
a test asserts the identity itself rather than a snapshot of numbers.

The second is arithmetic that mirrors the PRD's own rules: round-half-up at a stated
number of decimals, whole-hour gaps between half-open windows, and UTC day truncation.
Reimplementing these inline in each test invites the test to round differently from the
PRD, so they are written once here.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    assert_timestamp_format,
    assert_version_incremented,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)

from .api_errors import ERROR_HTTP_STATUS, error_priority
from .constants import (
    OCCUPYING_LINE_ITEM_STATUSES,
    RELEVANCE_SCORE_MAX,
    RELEVANCE_SCORE_MIN,
    RESERVING_DELIVERY_STATUSES,
)

__all__ = [
    "assert_cost_precision",
    "assert_timestamp_format",
    "assert_version_incremented",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "round_half_up",
    "round_half_up_int",
    "parse_utc",
    "iso_utc",
    "hours_between",
    "days_between",
    "whole_day_periods",
    "shift_hours",
    "shift_days",
    "floor_to_utc_day",
    "assert_budget_plan_identity",
    "assert_trade_fund_identity",
    "assert_plan_reservation_matches_campaigns",
    "assert_slot_occupancy_matches_line_items",
    "assert_occupancy_count",
    "assert_no_drift",
    "assert_campaign_dimensions",
    "assert_line_item_paused",
    "assert_common_fields",
    "assert_append_only_record",
    "assert_version_unchanged",
    "assert_refusal_beats",
    "assert_error_status_is_canonical",
    "assert_relevance_score_in_range",
    "assert_ranked_in_order",
    "assert_integer_cents",
    "assert_decimal_places",
]


# ---------------------------------------------------------------------------
# Arithmetic that mirrors the PRD's rounding and interval rules
# ---------------------------------------------------------------------------


def round_half_up(value, decimals: int) -> float:
    """Round to `decimals` places with ties going away from zero.

    Every fractional figure in this API rounds half-up at a stated precision, which
    differs from Python's built-in banker's rounding on exact halves.
    """
    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_half_up_int(value) -> int:
    """Round to whole cents with ties going away from zero."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_utc(timestamp: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating a trailing Z and fractions."""
    text = timestamp.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(moment: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with a trailing Z."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_between(earlier: str, later: str) -> int:
    """Whole hours from `earlier` to `later`, which is how gaps are measured."""
    delta = parse_utc(later) - parse_utc(earlier)
    return int(delta.total_seconds() // 3600)


def days_between(earlier: str, later: str) -> float:
    """Fractional days from `earlier` to `later`."""
    delta = parse_utc(later) - parse_utc(earlier)
    return delta.total_seconds() / 86400.0


def whole_day_periods(start: str, end: str, floor_at: int = 1) -> int:
    """Count whole twenty-four-hour periods in a window, floored at `floor_at`.

    This is the day count a line item's reservation is built from: a flight shorter
    than a day still reserves exactly one day of budget.
    """
    periods = int((parse_utc(end) - parse_utc(start)).total_seconds() // 86400)
    return max(floor_at, periods)


def shift_hours(timestamp: str, hours: int) -> str:
    """Return `timestamp` moved by a whole number of hours."""
    return iso_utc(parse_utc(timestamp) + timedelta(hours=hours))


def shift_days(timestamp: str, days: int) -> str:
    """Return `timestamp` moved by a whole number of days."""
    return iso_utc(parse_utc(timestamp) + timedelta(days=days))


def floor_to_utc_day(timestamp: str) -> str:
    """Truncate an instant down to the start of its UTC day."""
    moment = parse_utc(timestamp)
    return iso_utc(moment.replace(hour=0, minute=0, second=0, microsecond=0))


# ---------------------------------------------------------------------------
# Conservation ledgers
# ---------------------------------------------------------------------------


def assert_budget_plan_identity(plan: dict) -> None:
    """Assert the budget identity holds on a plan read.

    `committed_total_cents` plus `top_up_total_cents` always equals `available_cents`
    plus `reserved_cents` plus `consumed_cents`.
    """
    left = plan["committed_total_cents"] + plan["top_up_total_cents"]
    right = plan["available_cents"] + plan["reserved_cents"] + plan["consumed_cents"]
    assert left == right, (
        "budget identity broken: committed %d + top_up %d = %d but available %d + "
        "reserved %d + consumed %d = %d"
        % (
            plan["committed_total_cents"],
            plan["top_up_total_cents"],
            left,
            plan["available_cents"],
            plan["reserved_cents"],
            plan["consumed_cents"],
            right,
        )
    )


def assert_trade_fund_identity(pool: dict) -> None:
    """Assert the trade fund identity holds on a pool read.

    `accrued_cents` always equals `available_cents` plus `reserved_cents` plus
    `deducted_cents`.
    """
    right = pool["available_cents"] + pool["reserved_cents"] + pool["deducted_cents"]
    assert pool["accrued_cents"] == right, (
        "trade fund identity broken: accrued %d but available %d + reserved %d + "
        "deducted %d = %d"
        % (
            pool["accrued_cents"],
            pool["available_cents"],
            pool["reserved_cents"],
            pool["deducted_cents"],
            right,
        )
    )


def assert_plan_reservation_matches_campaigns(plan: dict, campaigns: list) -> None:
    """Assert a plan's `reserved_cents` equals the population it is derived from.

    `reserved_cents` is the sum of `allocated_budget_cents` over the plan's campaigns
    whose delivery status is scheduled, delivering or paused; every other delivery
    status reserves nothing.
    """
    expected = sum(
        c["allocated_budget_cents"]
        for c in campaigns
        if c["delivery_status"] in RESERVING_DELIVERY_STATUSES
    )
    assert plan["reserved_cents"] == expected, (
        "plan reserved_cents %d does not equal the %d reserved by its campaigns in %s"
        % (plan["reserved_cents"], expected, ", ".join(RESERVING_DELIVERY_STATUSES))
    )


def assert_slot_occupancy_matches_line_items(slot: dict, line_items: list) -> None:
    """Assert a slot's `occupancy_count` equals the population it is derived from.

    Occupancy is the number of line items on the slot whose status is one of the
    occupying statuses; draft, pending-eligibility, rejected and ended rows are
    excluded.
    """
    occupants = [
        li
        for li in line_items
        if li["placement_slot_id"] == slot["id"]
        and li["line_item_status"] in OCCUPYING_LINE_ITEM_STATUSES
    ]
    assert slot["occupancy_count"] == len(occupants), (
        "slot occupancy_count %d does not equal the %d line items on the slot in %s"
        % (
            slot["occupancy_count"],
            len(occupants),
            ", ".join(OCCUPYING_LINE_ITEM_STATUSES),
        )
    )


def assert_occupancy_count(slot: dict, expected: int) -> None:
    """Assert a slot carries exactly `expected` occupants."""
    assert slot["occupancy_count"] == expected, "occupancy_count %d, expected %d" % (
        slot["occupancy_count"],
        expected,
    )


def assert_no_drift(before, after, label: str) -> None:
    """Assert a compensated figure returned to exactly where it started."""
    assert before == after, "%s drifted: %r before, %r after" % (label, before, after)


# ---------------------------------------------------------------------------
# Parallel status dimensions
# ---------------------------------------------------------------------------


def assert_campaign_dimensions(
    campaign: dict, delivery_status: str, billing_status: str
) -> None:
    """Assert both of a campaign's independent status dimensions at once."""
    assert campaign["delivery_status"] == delivery_status, (
        "delivery_status %s, expected %s"
        % (campaign["delivery_status"], delivery_status)
    )
    assert campaign["billing_status"] == billing_status, (
        "billing_status %s, expected %s"
        % (campaign["billing_status"], billing_status)
    )


def assert_line_item_paused(line_item: dict, status: str, pause_reason: str) -> None:
    """Assert a line item's paused status together with the reason stamped on it."""
    assert line_item["line_item_status"] == status, (
        "line_item_status %s, expected %s"
        % (line_item["line_item_status"], status)
    )
    assert line_item["pause_reason"] == pause_reason, (
        "pause_reason %s, expected %s" % (line_item["pause_reason"], pause_reason)
    )
    assert line_item["last_pause_at"] is not None, "last_pause_at was not stamped"


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------


def assert_common_fields(resource: dict) -> None:
    """Assert an amendable resource carries an id, both timestamps and a version."""
    assert is_valid_uuid(resource["id"]), "id %r is not a UUID" % (resource["id"],)
    assert_timestamp_format(resource["created_at"])
    assert_timestamp_format(resource["updated_at"])
    assert isinstance(resource["version"], int), "version is not an integer"
    assert resource["version"] >= 1, "version %r is below 1" % (resource["version"],)


def assert_append_only_record(record: dict) -> None:
    """Assert an append-only record carries an id and a creation time and nothing more.

    Auction bids and engagement events are written once and never amended, so they
    have no `updated_at` and no `version` to advance.
    """
    assert is_valid_uuid(record["id"]), "id %r is not a UUID" % (record["id"],)
    assert_timestamp_format(record["created_at"])
    assert "version" not in record, "an append-only record carries no version"
    assert "updated_at" not in record, "an append-only record carries no updated_at"


def assert_version_unchanged(before: dict, after: dict) -> None:
    """Assert a resource's version did not move."""
    assert before["version"] == after["version"], (
        "version moved from %d to %d when it should have stood still"
        % (before["version"], after["version"])
    )


# ---------------------------------------------------------------------------
# Refusal ordering
# ---------------------------------------------------------------------------


def assert_refusal_beats(response, expected_error_id: str, *lower_priority: str):
    """Assert a request was refused with `expected_error_id` and that it outranks others.

    Used where more than one refusal condition is true at once: the assertion pins
    both the reported identifier and its position ahead of every condition named in
    `lower_priority`, so an implementation that reports a later condition fails.
    """
    body = validate_error(response, expected_error_id)
    winner = error_priority(expected_error_id)
    for other in lower_priority:
        assert winner < error_priority(other), (
            "%s should be reported ahead of %s but sits behind it in the refusal order"
            % (expected_error_id, other)
        )
    return body


def assert_error_status_is_canonical(response, expected_error_id: str) -> None:
    """Assert the HTTP status accompanying an error is the one the PRD assigns it."""
    expected_status = ERROR_HTTP_STATUS[expected_error_id]
    assert response.status_code == expected_status, (
        "%s came back with HTTP %d, expected %d"
        % (expected_error_id, response.status_code, expected_status)
    )


# ---------------------------------------------------------------------------
# Auction ranking
# ---------------------------------------------------------------------------


def assert_relevance_score_in_range(score) -> None:
    """Assert a relevance score sits inside its clamped range."""
    assert RELEVANCE_SCORE_MIN <= score <= RELEVANCE_SCORE_MAX, (
        "relevance_score %r is outside [%s, %s]"
        % (score, RELEVANCE_SCORE_MIN, RELEVANCE_SCORE_MAX)
    )


def assert_ranked_in_order(bids: list, expected_line_item_ids: list) -> None:
    """Assert the unfiltered bids of an auction rank in exactly the expected order."""
    ranked = sorted(
        [b for b in bids if b.get("rank") is not None], key=lambda b: b["rank"]
    )
    actual = [b["line_item_id"] for b in ranked]
    assert actual == expected_line_item_ids, (
        "ranking order %r, expected %r" % (actual, expected_line_item_ids)
    )
    assert [b["rank"] for b in ranked] == list(
        range(1, len(ranked) + 1)
    ), "ranks are not a dense sequence starting at 1"


# ---------------------------------------------------------------------------
# Precision
# ---------------------------------------------------------------------------


def assert_integer_cents(value, label: str = "amount") -> None:
    """Assert a money figure is whole cents and not a float."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        "%s is %r, which is not integer cents" % (label, value)
    )


def assert_decimal_places(value, decimals: int, label: str = "value") -> None:
    """Assert a fractional figure carries no more precision than the PRD allows."""
    quantum = Decimal(1).scaleb(-decimals)
    as_decimal = Decimal(str(value))
    assert as_decimal == as_decimal.quantize(quantum, rounding=ROUND_HALF_UP), (
        "%s is %r, which carries more than %d decimal places"
        % (label, value, decimals)
    )


def assert_success_shape(response, expected_status: int = 200) -> dict:
    """Validate a success envelope and return its data payload."""
    return validate_success(response, expected_status=expected_status)

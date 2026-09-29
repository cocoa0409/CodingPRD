"""Domain assertions shared across the suite.

Each helper checks one contract the PRD states once and relies on everywhere:
the identity-field shape, the fixed decimal places of the rate families, the
three ledger conservation identities, and the exact key set of the immutable
point-of-sale basket.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    IMMUTABLE_COMMON_FIELDS,
    PURCHASE_RECORD_FIELDS,
    VALUATION_FIELDS,
    VERSIONED_COMMON_FIELDS,
)

_ISO_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UUID_PLAIN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


# ---------------------------------------------------------------------------
# Identity, timestamps and versioning
# ---------------------------------------------------------------------------

def assert_bare_uuid(value: Any, field: str = "id") -> None:
    """An id is a UUID string with no type prefix and no domain encoding."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _UUID_PLAIN.match(value), (
        f"{field} must be a bare UUID with no prefix, got {value!r}"
    )
    assert is_valid_uuid(value), f"{field} must be a valid UUID, got {value!r}"


def assert_millis_timestamp(value: Any, field: str) -> None:
    """Timestamps are ISO 8601 UTC instants with exactly three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _ISO_MILLIS.match(value), (
        f"{field} must be an ISO 8601 UTC instant with exactly three "
        f"fractional digits, got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{field} must parse as ISO 8601: {value!r}"


def assert_calendar_date(value: Any, field: str) -> None:
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _ISO_DATE.match(value), (
        f"{field} must be a bare calendar date, got {value!r}"
    )


def assert_versioned_identity(row: Dict, expected_version: Optional[int] = None
                              ) -> None:
    """A versioned resource carries id, created_at, updated_at and version."""
    for field in VERSIONED_COMMON_FIELDS:
        assert field in row, f"missing identity field {field!r}"
    assert_bare_uuid(row["id"])
    assert_millis_timestamp(row["created_at"], "created_at")
    assert_millis_timestamp(row["updated_at"], "updated_at")
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_freshly_created(row: Dict) -> None:
    """A row nobody has mutated yet: version 1 and updated_at == created_at."""
    assert_versioned_identity(row, expected_version=1)
    assert row["updated_at"] == row["created_at"], (
        "a freshly created row has not been mutated, so updated_at must still "
        f"equal created_at: {row['updated_at']} vs {row['created_at']}"
    )


def assert_immutable_identity(row: Dict) -> None:
    """A point-of-sale basket carries only id and created_at."""
    for field in IMMUTABLE_COMMON_FIELDS:
        assert field in row, f"missing identity field {field!r}"
    assert_bare_uuid(row["id"])
    assert_millis_timestamp(row["created_at"], "created_at")
    assert "updated_at" not in row, (
        "updated_at must be absent from a purchase-data record payload"
    )
    assert "version" not in row, (
        "version must be absent from a purchase-data record payload"
    )


def assert_purchase_record_exact_keys(row: Dict) -> None:
    """The basket payload carries exactly the seven documented keys."""
    assert set(row.keys()) == set(PURCHASE_RECORD_FIELDS), (
        f"expected exactly {sorted(PURCHASE_RECORD_FIELDS)}, "
        f"got {sorted(row.keys())}"
    )


def assert_version_bumped(before: Dict, after: Dict, by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version'] + by}, got {after['version']}"
    )


def assert_version_unchanged(before: Dict, after: Dict) -> None:
    assert after["version"] == before["version"], (
        f"version must not move: was {before['version']}, "
        f"now {after['version']}"
    )


# ---------------------------------------------------------------------------
# Decimal discipline
# ---------------------------------------------------------------------------

def _as_decimal(value: Any, field: str) -> Decimal:
    assert value is not None, f"{field} must not be null"
    return Decimal(str(value))


def assert_decimal_places(value: Any, places: int, field: str) -> None:
    """A rate field renders with exactly `places` decimal places."""
    text = str(value)
    assert "." in text, f"{field} must carry {places} decimal places, got {value!r}"
    fraction = text.split(".", 1)[1]
    assert len(fraction) == places, (
        f"{field} must carry exactly {places} decimal places, got {value!r}"
    )


def assert_rate_equals(value: Any, expected: str, field: str) -> None:
    """A two-decimal rate or score equals the expected value exactly."""
    actual = _as_decimal(value, field)
    assert actual == Decimal(expected), (
        f"{field} must be {expected}, got {value!r}"
    )


def assert_holdback_pct(value: Any, expected: str) -> None:
    """holdback_pct is stored to four decimal places."""
    actual = _as_decimal(value, "holdback_pct")
    assert actual == Decimal(expected), (
        f"holdback_pct must be {expected}, got {value!r}"
    )


def assert_whole_cents(value: Any, field: str) -> None:
    """Every monetary field is an integer number of whole cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )


def assert_money(row: Dict, field: str, expected: int) -> None:
    assert field in row, f"missing money field {field!r}"
    assert_whole_cents(row[field], field)
    assert row[field] == expected, (
        f"{field} must be {expected} cents, got {row[field]}"
    )


def assert_money_fields(row: Dict, expected: Dict[str, int]) -> None:
    for field, value in expected.items():
        assert_money(row, field, value)


# ---------------------------------------------------------------------------
# Ledger conservation identities
# ---------------------------------------------------------------------------

def assert_manufacturer_ledger(manufacturer: Dict, funded_total: int,
                               disbursed_total: int) -> None:
    """funding_balance_cents always equals funded minus disbursed."""
    assert_money(manufacturer, "funded_total_cents", funded_total)
    assert_money(manufacturer, "disbursed_total_cents", disbursed_total)
    assert_money(manufacturer, "funding_balance_cents",
                 funded_total - disbursed_total)
    assert manufacturer["funding_balance_cents"] >= 0, (
        "funding_balance_cents is never negative by construction"
    )


def assert_retailer_unpaid(retailer: Dict, expected: int) -> None:
    """unpaid_balance_cents sums net_payable over SCHEDULED statements only."""
    assert_money(retailer, "unpaid_balance_cents", expected)


def assert_adjudicated_face_conserved(submission: Dict, expected: int) -> None:
    """adjudicated_face_value_cents is the conserved quantity of adjudication."""
    assert_money(submission, "adjudicated_face_value_cents", expected)
    assert (submission["accepted_item_face_value_cents"]
            + submission["rejected_item_face_value_cents"]) == expected, (
        "accepted plus rejected item face value must equal the conserved "
        f"adjudicated total {expected}: "
        f"{submission['accepted_item_face_value_cents']} + "
        f"{submission['rejected_item_face_value_cents']}"
    )


# ---------------------------------------------------------------------------
# Envelope-adjacent helpers
# ---------------------------------------------------------------------------

def assert_page(meta: Dict, total_count: int, limit: int, offset: int,
                has_more: bool) -> None:
    assert meta["total_count"] == total_count, (
        f"total_count must be {total_count}, got {meta['total_count']}"
    )
    assert meta["limit"] == limit, f"limit must be {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, (
        f"offset must be {offset}, got {meta['offset']}"
    )
    assert meta["has_more"] is has_more, (
        f"has_more must be {has_more}, got {meta['has_more']}"
    )


def assert_ordered_ascending(rows: Sequence[Dict], field: str = "created_at"
                             ) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), (
        f"rows must be ordered by {field} ascending, got {values}"
    )


def assert_ordered_descending(rows: Sequence[Dict], field: str = "created_at"
                              ) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values, reverse=True), (
        f"rows must be ordered by {field} descending, got {values}"
    )


def assert_ids_in_order(rows: Sequence[Dict], expected_ids: Sequence[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"expected ids in order {list(expected_ids)}, got {actual}"
    )


def assert_nulls(row: Dict, fields: Iterable[str]) -> None:
    for field in fields:
        assert field in row, f"missing field {field!r}"
        assert row[field] is None, f"{field} must be null, got {row[field]!r}"


def assert_fields(row: Dict, expected: Dict[str, Any]) -> None:
    """Assert a batch of plain field equalities with one readable message each."""
    for field, value in expected.items():
        assert field in row, f"missing field {field!r}"
        assert row[field] == value, (
            f"{field} must be {value!r}, got {row[field]!r}"
        )


def assert_sweep_counters(data: Dict, current_utc: str,
                          expired_offer_count: int, expired_clip_count: int,
                          withdrawn_dispute_count: int) -> None:
    """A clock advance echoes current_utc and the three sweep counts."""
    assert data["current_utc"].startswith(current_utc[:19]), (
        f"current_utc must echo {current_utc}, got {data['current_utc']}"
    )
    assert_fields(data, {
        "expired_offer_count": expired_offer_count,
        "expired_clip_count": expired_clip_count,
        "withdrawn_dispute_count": withdrawn_dispute_count,
    })


def assert_valuation_shape(data: Dict) -> None:
    for field in VALUATION_FIELDS:
        assert field in data, f"valuation read must carry {field!r}"


def assert_lot_valuation(lot: Dict, status: str, accepted_qty: int,
                         rejected_qty: int, projected_accepted_units: int,
                         gross_face_value_cents: int,
                         handling_fee_cents: int) -> None:
    """The six numbers a finalized lot must carry."""
    assert_fields(lot, {
        "status": status,
        "accepted_qty": accepted_qty,
        "rejected_qty": rejected_qty,
        "projected_accepted_units": projected_accepted_units,
    })
    assert_money(lot, "gross_face_value_cents", gross_face_value_cents)
    assert_money(lot, "handling_fee_cents", handling_fee_cents)


def assert_statement_waterfall(statement: Dict, gross: int, fee_total: int,
                               offset: int, provisional_net: int,
                               holdback_pct: str, holdback: int,
                               net_payable: int) -> None:
    """The six-step waterfall, checked end to end on one statement."""
    assert_money(statement, "gross_face_value_cents", gross)
    assert_money(statement, "handling_fee_total_cents", fee_total)
    assert_money(statement, "prior_chargeback_offset_cents", offset)
    assert_money(statement, "provisional_net_cents", provisional_net)
    assert_holdback_pct(statement["holdback_pct"], holdback_pct)
    assert_money(statement, "misredemption_holdback_cents", holdback)
    assert_money(statement, "net_payable_cents", net_payable)
    assert provisional_net == gross + fee_total - offset, (
        "provisional_net_cents is gross plus handling fee minus the offset"
    )
    assert net_payable == provisional_net - holdback, (
        "net_payable_cents is provisional_net_cents minus the holdback"
    )

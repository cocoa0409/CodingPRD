"""Domain assertions: envelope shape, common fields, page partition, money partition."""

import re
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z$")


def _canonical_instant(value: Any) -> Any:
    """Reduce an ISO 8601 UTC instant to (seconds-text, microseconds)."""
    if not isinstance(value, str):
        return value
    match = _INSTANT_RE.match(value)
    if match is None:
        return value
    fraction = match.group(2) or ""
    micro = int((fraction + "000000")[:6]) if fraction else 0
    return (match.group(1), micro)


class Instant:
    """An expected instant, compared by the instant it denotes.

    PRD §2.2 and §2.4 pin exactly three fractional digits for
    `meta.api_request_timestamp`, `created_at` and `updated_at`; for every other
    datetime field — `received_at`, `statutory_due_at`, `released_at`,
    `settled_at`, `review_due_at`, `legacy_job_end_at` and their siblings — the
    PRD fixes the *instant* the field must hold and says nothing about how many
    fractional-second digits render it.  Equality is therefore taken on the
    instant, so `2026-08-31T00:00:00Z` and `2026-08-31T00:00:00.000Z` are the
    same expected value while a different second is still a failure.
    """

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        assert _INSTANT_RE.match(text), f"not an ISO 8601 UTC instant literal: {text!r}"
        self.text = text

    def __eq__(self, other: Any) -> bool:
        return _canonical_instant(other) == _canonical_instant(self.text)

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(_canonical_instant(self.text))

    def __repr__(self) -> str:
        return f"Instant({self.text!r})"


# ---------------------------------------------------------------- envelope
def assert_envelope(response, expected_status: int = 200, expected_type: str = "object") -> Any:
    """Full envelope check: meta.api_request_id prefix, timestamp precision, response_type."""
    body = response.json()
    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert _TS_RE.match(meta["api_request_timestamp"]), (
        "meta.api_request_timestamp must be ISO 8601 UTC with exactly three "
        f"fractional-second digits, got {meta['api_request_timestamp']!r}"
    )
    assert body["response_type"] == expected_type, (
        f"Expected response_type {expected_type!r}, got {body['response_type']!r}"
    )
    return body["data"]


def assert_error_envelope(response, expected_error_id: str, expected_status: int) -> dict:
    """Error envelope check including the meta block every error must still carry."""
    body = response.json()
    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status}, got {response.status_code}: {response.text}"
    )
    assert body["response_type"] == "error", f"Expected response_type 'error', got {body['response_type']!r}"
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert _TS_RE.match(meta["api_request_timestamp"])
    data = body["data"]
    assert data["error_id"] == expected_error_id, (
        f"Expected error_id {expected_error_id!r}, got {data['error_id']!r}"
    )
    assert isinstance(data["message"], str) and data["message"].strip()
    return data


# ---------------------------------------------------------------- common fields
def assert_common_fields(entity: dict, expected_version: Optional[int] = None) -> None:
    """id / created_at / updated_at / version, as carried by every versioned entity."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID with no prefix, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), f"bad created_at {entity['created_at']!r}"
    assert is_iso8601_timestamp(entity["updated_at"]), f"bad updated_at {entity['updated_at']!r}"
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_created_only_fields(entity: dict) -> None:
    """InvoiceLine and ComplianceEvent carry only id and created_at."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert "updated_at" not in entity, "this entity must not carry updated_at"
    assert "version" not in entity, "this entity must not carry version"


# ---------------------------------------------------------------- page ledger
#
# There is deliberately no partition assertion here.  PRD §3.4 computes
# `page_count_total` over every `RETRIEVED` segment, but `billable_page_count`
# and `redacted_page_count_total` only over the *releasable* ones
# (`NOT_SENSITIVE` or `AUTHORIZED_INCLUDE`) and `withheld_page_count` only over
# `WITHHELD` ones.  A retrieved segment sitting in `SEGREGATED_PENDING_REVIEW`
# is in none of those three populations, so the four fields are not required to
# sum, and the PRD never states that they do.
def assert_page_ledger(
    request_data: dict, total: int, billable: int, withheld: int, redacted: int
) -> None:
    assert request_data["page_count_total"] == total, (
        f"page_count_total {request_data['page_count_total']} != {total}"
    )
    assert request_data["billable_page_count"] == billable, (
        f"billable_page_count {request_data['billable_page_count']} != {billable}"
    )
    assert request_data["withheld_page_count"] == withheld, (
        f"withheld_page_count {request_data['withheld_page_count']} != {withheld}"
    )
    assert request_data["redacted_page_count_total"] == redacted, (
        f"redacted_page_count_total {request_data['redacted_page_count_total']} != {redacted}"
    )


# ---------------------------------------------------------------- facility ledger
def assert_facility_money(
    facility: dict, receivable: int, collected: int, written_off: int
) -> None:
    assert facility["receivable_cents"] == receivable, (
        f"receivable_cents {facility['receivable_cents']} != {receivable}"
    )
    assert facility["collected_cents"] == collected, (
        f"collected_cents {facility['collected_cents']} != {collected}"
    )
    assert facility["written_off_cents"] == written_off, (
        f"written_off_cents {facility['written_off_cents']} != {written_off}"
    )


def money_partition_sum(facility: dict) -> int:
    """receivable + collected + written_off."""
    return (
        facility["receivable_cents"] + facility["collected_cents"] + facility["written_off_cents"]
    )


# ---------------------------------------------------------------- invoice lines
def assert_line_sequence_contiguous(lines: List[dict]) -> None:
    """sequence is 1-based, contiguous, and the sole ordering key."""
    sequences = [line["sequence"] for line in lines]
    assert sequences == list(range(1, len(lines) + 1)), (
        f"sequences must run 1..{len(lines)} with no gap, got {sequences}"
    )


def assert_line(line: dict, line_type: str, quantity: int, unit_millicents: int, amount_cents: int) -> None:
    assert line["line_type"] == line_type, f"expected line_type {line_type!r}, got {line['line_type']!r}"
    assert line["quantity"] == quantity, f"{line_type} quantity {line['quantity']} != {quantity}"
    assert line["unit_millicents"] == unit_millicents, (
        f"{line_type} unit_millicents {line['unit_millicents']} != {unit_millicents}"
    )
    assert line["amount_cents"] == amount_cents, (
        f"{line_type} amount_cents {line['amount_cents']} != {amount_cents}"
    )


def line_types(lines: List[dict]) -> List[str]:
    return [line["line_type"] for line in lines]


def assert_no_line_type(lines: List[dict], line_type: str) -> None:
    assert line_type not in line_types(lines), (
        f"{line_type} line must be omitted entirely, got {line_types(lines)}"
    )


def assert_subtotal_reconciles(invoice: dict, lines: List[dict]) -> None:
    """subtotal excludes the two adjustment line types; gross adds the cap adjustment."""
    priced = sum(
        line["amount_cents"]
        for line in lines
        if line["line_type"] not in ("CAP_ADJUSTMENT", "LATE_FEE_FORFEITURE")
    )
    assert invoice["subtotal_cents"] == priced, (
        f"subtotal_cents {invoice['subtotal_cents']} != sum of priced lines {priced}"
    )
    assert invoice["gross_total_cents"] == invoice["subtotal_cents"] + invoice["cap_adjustment_cents"]
    assert invoice["amount_due_cents"] == invoice["gross_total_cents"] - invoice["forfeiture_cents"]


# ---------------------------------------------------------------- compliance events
def event_types(events: List[dict]) -> List[str]:
    return [event["event_type"] for event in events]


def count_events(events: List[dict], event_type: str) -> int:
    return sum(1 for event in events if event["event_type"] == event_type)


def assert_event_count(events: List[dict], event_type: str, expected: int) -> None:
    actual = count_events(events, event_type)
    assert actual == expected, (
        f"expected exactly {expected} {event_type} event(s), got {actual}: {event_types(events)}"
    )


def assert_no_event(events: List[dict], event_type: str) -> None:
    assert_event_count(events, event_type, 0)


# ---------------------------------------------------------------- listing helpers
def assert_pagination_meta(meta: Dict[str, Any], total_count: int, has_more: bool) -> None:
    assert meta["total_count"] == total_count, f"total_count {meta['total_count']} != {total_count}"
    assert meta["has_more"] is has_more, f"has_more {meta['has_more']} != {has_more}"


def ids_of(rows: List[dict]) -> List[str]:
    return [row["id"] for row in rows]


def assert_ascending(values: List[Any]) -> None:
    assert values == sorted(values), f"expected ascending order, got {values}"


__all__ = [
    "assert_envelope",
    "assert_error_envelope",
    "assert_common_fields",
    "assert_created_only_fields",
    "Instant",
    "assert_page_ledger",
    "assert_facility_money",
    "money_partition_sum",
    "assert_line_sequence_contiguous",
    "assert_line",
    "line_types",
    "assert_no_line_type",
    "assert_subtotal_reconciles",
    "event_types",
    "count_events",
    "assert_event_count",
    "assert_no_event",
    "assert_pagination_meta",
    "ids_of",
    "assert_ascending",
    "validate_success",
    "validate_paginated",
]

"""Domain assertions for the Municipal Clerk API.

These wrap the repeated envelope and invariant checks the PRD declares, so tests
read as statements about clerk business rules rather than about dict keys.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import INITIAL_VERSION

# ---------------------------------------------------------------------------
# Instant comparison (PRD 2.5)
# ---------------------------------------------------------------------------
#
# PRD 2.5 fixes the rendering of exactly two timestamp fields: "a ``created_at``
# timestamp in ISO 8601 UTC form with three fractional digits", and
# ``updated_at`` "in the same timestamp format".  Every other instant the
# service exposes -- ``scheduled_start``, ``notice_deadline_at``, ``posted_at``,
# ``adjourned_at``, ``notice_posted_at`` -- is only ever described as an
# "ISO 8601 UTC" instant, with no fractional-digit rule stated anywhere.  A
# faithful implementation may therefore render ``2026-09-12T18:00:00Z`` or
# ``2026-09-12T18:00:00.000Z``; both name the same instant and the PRD does not
# choose between them.  These comparisons consequently assert the *instant*,
# which the PRD does fix, rather than its spelling, which it does not.

_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def _as_instant(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 *datetime* string into a UTC instant, else None."""
    if not isinstance(value, str) or not _ISO_DATETIME_RE.match(value.strip()):
        return None
    text = value.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def values_equal(actual: Any, expected: Any) -> bool:
    """Exact equality, except that two ISO 8601 datetime strings are compared as
    instants rather than as spellings (see the note above)."""
    if actual == expected:
        return True
    actual_instant = _as_instant(actual)
    expected_instant = _as_instant(expected)
    if actual_instant is not None and expected_instant is not None:
        return actual_instant == expected_instant
    return False

# ---------------------------------------------------------------------------
# Envelope and common fields (PRD 2.2, 2.5)
# ---------------------------------------------------------------------------


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """The envelope's ``meta`` block carries a ``req_``-prefixed id and a UTC
    timestamp with exactly three fractional-second digits (PRD 2.2)."""
    meta = body["meta"]
    request_id = meta["api_request_id"]
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"meta.api_request_id must begin with 'req_', got {request_id!r}"
    )
    timestamp = meta["api_request_timestamp"]
    assert isinstance(timestamp, str), "meta.api_request_timestamp must be a string"
    assert timestamp.endswith("Z"), (
        f"meta.api_request_timestamp must be UTC (trailing Z), got {timestamp!r}"
    )
    assert "." in timestamp, (
        f"meta.api_request_timestamp must carry fractional seconds, got {timestamp!r}"
    )
    fraction = timestamp.split(".", 1)[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"meta.api_request_timestamp must carry exactly three fractional digits, "
        f"got {timestamp!r}"
    )


def assert_response_type(body: Dict[str, Any], expected: str) -> None:
    actual = body.get("response_type")
    assert actual == expected, f"Expected response_type {expected!r}, got {actual!r}"


def assert_common_fields(entity: Dict[str, Any], *, versioned: bool = True) -> None:
    """Every entity carries a bare-UUID ``id`` and a ``created_at``; all but
    ``AgendaItem`` also carry ``updated_at`` and a ``version`` (PRD 2.5)."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID, got {entity['id']!r}"
    assert "prefix" not in str(entity["id"]).lower() or "-" in str(entity["id"])
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be an ISO 8601 timestamp, got {entity['created_at']!r}"
    )
    if versioned:
        assert "updated_at" in entity, "versioned entities must carry updated_at"
        assert is_iso8601_timestamp(entity["updated_at"]), (
            f"updated_at must be an ISO 8601 timestamp, got {entity['updated_at']!r}"
        )
        assert isinstance(entity["version"], int), "version must be an integer"
        assert entity["version"] >= INITIAL_VERSION
    else:
        assert "updated_at" not in entity, (
            "this entity is declared without updated_at (PRD 2.5)"
        )
        assert "version" not in entity, (
            "this entity is declared without version (PRD 2.5)"
        )


def assert_initial_version(entity: Dict[str, Any]) -> None:
    assert entity["version"] == INITIAL_VERSION, (
        f"a freshly created resource starts at version {INITIAL_VERSION}, "
        f"got {entity['version']}"
    )


def assert_version_advanced_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1
) -> None:
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']} + {delta}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Field-level helpers
# ---------------------------------------------------------------------------


def assert_fields(entity: Dict[str, Any], **expected: Any) -> None:
    """Assert several field values at once with a readable failure message."""
    for field, value in expected.items():
        assert field in entity, f"expected field {field!r} on the resource"
        assert values_equal(entity[field], value), (
            f"expected {field}={value!r}, got {entity[field]!r}"
        )


def assert_nulls(entity: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert field in entity, f"expected field {field!r} on the resource"
        assert entity[field] is None, f"expected {field} to be null, got {entity[field]!r}"


def assert_status(entity: Dict[str, Any], expected: str) -> None:
    assert entity["status"] == expected, (
        f"expected status {expected!r}, got {entity['status']!r}"
    )


# ---------------------------------------------------------------------------
# Money (PRD 2.9)
# ---------------------------------------------------------------------------


def assert_cents(entity: Dict[str, Any], field: str, expected: int) -> None:
    """Monetary fields are integer cents and never strings or floats."""
    actual = entity[field]
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer number of cents, got {type(actual).__name__}"
    )
    assert actual == expected, f"expected {field}={expected}, got {actual}"


def assert_all_cents_integers(entity: Dict[str, Any]) -> None:
    for field, value in entity.items():
        if field.endswith("_cents") and value is not None:
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{field} must be an integer number of cents, got {value!r}"
            )


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------


def assert_pagination_meta(
    meta: Dict[str, Any],
    *,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"


def assert_ascending_by(rows: Sequence[Dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), (
        f"rows must be ordered by {field} ascending, got {values}"
    )


def assert_ids_equal(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"expected ids {list(expected_ids)}, got {actual}"


def assert_contains_id(rows: Sequence[Dict[str, Any]], entity_id: str) -> None:
    ids = [row["id"] for row in rows]
    assert entity_id in ids, f"expected {entity_id} among {ids}"


def assert_excludes_id(rows: Sequence[Dict[str, Any]], entity_id: str) -> None:
    ids = [row["id"] for row in rows]
    assert entity_id not in ids, f"did not expect {entity_id} among {ids}"


# ---------------------------------------------------------------------------
# Custody ledger and fee ledger invariants (PRD 2.10, 3.8, 3.9)
# ---------------------------------------------------------------------------


def assert_custody_triple(
    series: Dict[str, Any],
    *,
    total: int,
    active: int,
    destroyed: int,
) -> None:
    """``total_accessioned_count`` always equals active + destroyed (PRD 2.10)."""
    assert series["total_accessioned_count"] == total, (
        f"expected total_accessioned_count {total}, "
        f"got {series['total_accessioned_count']}"
    )
    assert series["active_item_count"] == active, (
        f"expected active_item_count {active}, got {series['active_item_count']}"
    )
    assert series["destroyed_item_count"] == destroyed, (
        f"expected destroyed_item_count {destroyed}, got {series['destroyed_item_count']}"
    )
    assert series["total_accessioned_count"] == (
        series["active_item_count"] + series["destroyed_item_count"]
    ), "total_accessioned_count must equal active_item_count + destroyed_item_count"


def assert_fee_ledger(
    request: Dict[str, Any],
    *,
    assessed: int,
    waived: int,
    collected: int,
    refunded: int,
    balance: int,
    net_cash: int,
) -> None:
    """The two derived money fields are recomputed from the four counters and
    neither may go negative (PRD 3.8)."""
    assert_cents(request, "total_assessed_cents", assessed)
    assert_cents(request, "total_waived_cents", waived)
    assert_cents(request, "total_collected_cents", collected)
    assert_cents(request, "refunded_cents", refunded)
    assert_cents(request, "net_cash_cents", net_cash)
    assert_cents(request, "fee_balance_cents", balance)
    assert request["net_cash_cents"] == (
        request["total_collected_cents"] - request["refunded_cents"]
    ), "net_cash_cents must equal total_collected_cents minus refunded_cents"
    assert request["fee_balance_cents"] == (
        request["total_assessed_cents"]
        - request["total_waived_cents"]
        - request["net_cash_cents"]
    ), (
        "fee_balance_cents must equal total_assessed_cents minus total_waived_cents "
        "minus net cash"
    )
    assert request["fee_balance_cents"] >= 0, "fee_balance_cents may never go negative"
    assert request["net_cash_cents"] >= 0, "net_cash_cents may never go negative"


def assert_axes(
    request: Dict[str, Any], *, fulfillment_status: str, fee_status: str
) -> None:
    """The disclosure axis and the money axis move independently (PRD 3.8)."""
    assert request["fulfillment_status"] == fulfillment_status, (
        f"expected fulfillment_status {fulfillment_status!r}, "
        f"got {request['fulfillment_status']!r}"
    )
    assert request["fee_status"] == fee_status, (
        f"expected fee_status {fee_status!r}, got {request['fee_status']!r}"
    )


# ---------------------------------------------------------------------------
# Meeting notice mirroring (PRD 2.10)
# ---------------------------------------------------------------------------


def assert_meeting_notice_mirror(
    meeting: Dict[str, Any],
    *,
    posted_at: Optional[str],
    required_notice_hours: Optional[int],
    notice_compliant: bool,
) -> None:
    assert values_equal(meeting["notice_posted_at"], posted_at), (
        f"expected mirrored notice_posted_at {posted_at!r}, "
        f"got {meeting['notice_posted_at']!r}"
    )
    assert meeting["required_notice_hours"] == required_notice_hours, (
        f"expected mirrored required_notice_hours {required_notice_hours!r}, "
        f"got {meeting['required_notice_hours']!r}"
    )
    assert meeting["notice_compliant"] is notice_compliant, (
        f"expected mirrored notice_compliant {notice_compliant}, "
        f"got {meeting['notice_compliant']!r}"
    )


def assert_no_mirrored_notice(meeting: Dict[str, Any]) -> None:
    """A meeting with no posted packet mirrors null / null / false (PRD 2.10)."""
    assert_meeting_notice_mirror(
        meeting, posted_at=None, required_notice_hours=None, notice_compliant=False
    )


# ---------------------------------------------------------------------------
# Publication invoice (PRD 3.6)
# ---------------------------------------------------------------------------


def assert_invoice(
    notice: Dict[str, Any],
    *,
    gross_cost_cents: int,
    discount_pct: float,
    invoice_total_cents: int,
) -> None:
    assert_cents(notice, "gross_cost_cents", gross_cost_cents)
    assert notice["discount_pct"] == discount_pct, (
        f"expected discount_pct {discount_pct}, got {notice['discount_pct']}"
    )
    assert_cents(notice, "invoice_total_cents", invoice_total_cents)


# ---------------------------------------------------------------------------
# Vote arithmetic (PRD 3.3)
# ---------------------------------------------------------------------------


def assert_vote_arithmetic(
    motion: Dict[str, Any],
    *,
    effective_base: int,
    required_yes: int,
    outcome: str,
    tie_break_used: bool = False,
) -> None:
    assert motion["effective_base"] == effective_base, (
        f"expected effective_base {effective_base}, got {motion['effective_base']}"
    )
    assert motion["required_yes"] == required_yes, (
        f"expected required_yes {required_yes}, got {motion['required_yes']}"
    )
    assert motion["outcome"] == outcome, (
        f"expected outcome {outcome!r}, got {motion['outcome']!r}"
    )
    assert motion["tie_break_used"] is tie_break_used, (
        f"expected tie_break_used {tie_break_used}, got {motion['tie_break_used']!r}"
    )


# ---------------------------------------------------------------------------
# Code title section list (PRD 3.7)
# ---------------------------------------------------------------------------


def assert_section_refs(title: Dict[str, Any], expected: List[str]) -> None:
    actual = title["section_refs"]
    assert isinstance(actual, list), "section_refs must be a list"
    assert actual == expected, f"expected section_refs {expected}, got {actual}"

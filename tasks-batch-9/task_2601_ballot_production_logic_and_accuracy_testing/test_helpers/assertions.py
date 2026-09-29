"""Domain assertion helpers.

These wrap the repeated shape checks so an individual test asserts the rule it
is about rather than re-deriving the response contract. Nothing here computes a
domain figure on the service's behalf: expected numbers are always supplied by
the caller.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import CUSTODY_EVENT_TYPES, SYSTEM_ACTOR_USER_ID

_MILLIS_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ─── Timestamp helpers ───────────────────────────────────────────────────────

def assert_millisecond_timestamp(value: Any, label: str = "timestamp") -> None:
    """Assert an ISO 8601 UTC timestamp carrying exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _MILLIS_TIMESTAMP.match(value), (
        f"{label} must be ISO 8601 UTC with exactly three fractional digits, got {value!r}"
    )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    assert isinstance(value, str), f"instant must be a string, got {value!r}"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def assert_same_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment.

    The PRD pins the three-fractional-digit rendering for ``created_at`` and
    ``updated_at`` only, so instants that are read from the logical clock or
    echoed back from a client-supplied field are compared as moments in time
    rather than as byte strings.
    """
    assert isinstance(actual, str), f"{label} must be a string, got {actual!r}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} expected the instant {expected!r}, got {actual!r}"
    )


def shift_instant(value: str, minutes: int = 0, hours: int = 0, days: int = 0) -> str:
    """Return ``value`` shifted by the given offset, formatted without fractions."""
    moment = parse_instant(value) + timedelta(minutes=minutes, hours=hours, days=days)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days_to_date(date_text: str, days: int) -> str:
    """Return the calendar date ``days`` after ``date_text`` (YYYY-MM-DD)."""
    day = datetime.strptime(date_text, "%Y-%m-%d") + timedelta(days=days)
    return day.strftime("%Y-%m-%d")


# ─── Common resource fields ──────────────────────────────────────────────────

def assert_common_fields(entity: Dict[str, Any], label: str = "resource") -> None:
    """Assert the identity, timestamp and version fields carried by every resource."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id must be a UUID, got {entity.get('id')!r}"
    assert_millisecond_timestamp(entity.get("created_at"), f"{label}.created_at")
    assert_millisecond_timestamp(entity.get("updated_at"), f"{label}.updated_at")
    version = entity.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{label}.version must be an integer, got {version!r}"
    )
    assert version >= 1, f"{label}.version must start at 1 or more, got {version}"


def assert_created_at_only(entity: Dict[str, Any], label: str = "resource") -> None:
    """Assert an append-only record: an id and a creation stamp, no update or version."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id must be a UUID, got {entity.get('id')!r}"
    assert_millisecond_timestamp(entity.get("created_at"), f"{label}.created_at")
    assert "updated_at" not in entity, f"{label} must not carry updated_at"
    assert "version" not in entity, f"{label} must not carry version"


def assert_fields_absent(entity: Dict[str, Any], fields: Iterable[str],
                         label: str = "resource") -> None:
    for field in fields:
        assert field not in entity, f"{label} must not expose {field}"


def assert_fields_equal(entity: Dict[str, Any], expected: Dict[str, Any],
                        label: str = "resource") -> None:
    """Assert every expected key is present in ``entity`` with the expected value."""
    for key, value in expected.items():
        assert key in entity, f"{label} is missing {key}"
        assert entity[key] == value, (
            f"{label}.{key} expected {value!r}, got {entity[key]!r}"
        )


def assert_version_bumped_by(new_entity: Dict[str, Any], old_version: int,
                             increment: int = 1, label: str = "resource") -> None:
    actual = new_entity.get("version")
    assert actual == old_version + increment, (
        f"{label}.version expected {old_version + increment}, got {actual!r}"
    )


# ─── Envelope helpers ────────────────────────────────────────────────────────

def assert_envelope_meta(body: Dict[str, Any], expected_response_type: str) -> None:
    """Assert the envelope metadata block and the top-level response_type."""
    meta = body.get("meta")
    assert isinstance(meta, dict), f"meta must be an object, got {meta!r}"
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"meta.api_request_id must be a string beginning req_, got {request_id!r}"
    )
    assert_millisecond_timestamp(meta.get("api_request_timestamp"), "meta.api_request_timestamp")
    assert body.get("response_type") == expected_response_type, (
        f"response_type expected {expected_response_type!r}, "
        f"got {body.get('response_type')!r}"
    )


def assert_error_envelope(body: Dict[str, Any], expected_error_id: str) -> None:
    """Assert the error envelope: the error object sits in data beside the meta block."""
    error = body.get("data")
    assert isinstance(error, dict), f"data must carry the error object, got {error!r}"
    assert error.get("error_id") == expected_error_id, (
        f"error_id expected {expected_error_id!r}, got {error.get('error_id')!r}"
    )
    message = error.get("message")
    assert isinstance(message, str) and message, "the error message must be a non-empty string"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        f"an error response meta block must carry only the request id and timestamp, "
        f"got {sorted(body['meta'])}"
    )
    assert_envelope_meta(body, "error")


# ─── Ordering and pagination ─────────────────────────────────────────────────

def assert_ordered_by(rows: Sequence[Dict[str, Any]], field: str) -> None:
    """Assert ``rows`` is non-descending on ``field``."""
    values = [row.get(field) for row in rows]
    assert values == sorted(values), f"rows must be ordered by {field} ascending, got {values!r}"


def assert_sequence_indices_ascending(rows: Sequence[Dict[str, Any]]) -> None:
    """Assert a ledger's sequence_index values strictly increase."""
    values = [row.get("sequence_index") for row in rows]
    for value in values:
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"sequence_index must be an integer, got {value!r}"
        )
    for earlier, later in zip(values, values[1:]):
        assert later > earlier, f"sequence_index must strictly increase, got {values!r}"


def assert_pagination_meta(meta: Dict[str, Any], total_count: int, has_more: bool,
                           limit: Optional[int] = None,
                           offset: Optional[int] = None) -> None:
    assert meta.get("total_count") == total_count, (
        f"meta.total_count expected {total_count}, got {meta.get('total_count')!r}"
    )
    assert meta.get("has_more") is has_more, (
        f"meta.has_more expected {has_more}, got {meta.get('has_more')!r}"
    )
    if limit is not None:
        assert meta.get("limit") == limit, f"meta.limit expected {limit}, got {meta.get('limit')!r}"
    if offset is not None:
        assert meta.get("offset") == offset, (
            f"meta.offset expected {offset}, got {meta.get('offset')!r}"
        )


# ─── Custody ledger ─────────────────────────────────────────────────────────

def assert_custody_event(event: Dict[str, Any], event_type: str,
                         subject_type: Optional[str] = None,
                         subject_id: Optional[str] = None,
                         from_state: Optional[str] = None,
                         to_state: Optional[str] = None,
                         actor_user_id: Optional[str] = None,
                         seal_number: Optional[str] = None) -> None:
    """Assert one ledger entry: its type, its subject, and its recorded transition."""
    assert event.get("event_type") == event_type, (
        f"custody event expected type {event_type!r}, got {event.get('event_type')!r}"
    )
    assert event.get("event_type") in CUSTODY_EVENT_TYPES, (
        f"custody event type {event.get('event_type')!r} is not a declared event type"
    )
    if subject_type is not None:
        assert event.get("subject_type") == subject_type, (
            f"custody event subject_type expected {subject_type!r}, "
            f"got {event.get('subject_type')!r}"
        )
    if subject_id is not None:
        assert event.get("subject_id") == subject_id, (
            f"custody event subject_id expected {subject_id!r}, got {event.get('subject_id')!r}"
        )
    if from_state is not None:
        assert event.get("from_state") == from_state, (
            f"custody event from_state expected {from_state!r}, got {event.get('from_state')!r}"
        )
    if to_state is not None:
        assert event.get("to_state") == to_state, (
            f"custody event to_state expected {to_state!r}, got {event.get('to_state')!r}"
        )
    if actor_user_id is not None:
        assert event.get("actor_user_id") == actor_user_id, (
            f"custody event actor_user_id expected {actor_user_id!r}, "
            f"got {event.get('actor_user_id')!r}"
        )
    if seal_number is not None:
        assert event.get("seal_number") == seal_number, (
            f"custody event seal_number expected {seal_number!r}, "
            f"got {event.get('seal_number')!r}"
        )


def assert_system_actor(event: Dict[str, Any]) -> None:
    """Assert a cascade-written ledger entry attributes itself to the system."""
    assert event.get("actor_user_id") == SYSTEM_ACTOR_USER_ID, (
        f"a cascade-written custody event must record actor_user_id "
        f"{SYSTEM_ACTOR_USER_ID!r}, got {event.get('actor_user_id')!r}"
    )


def event_types(events: Sequence[Dict[str, Any]]) -> List[str]:
    return [event.get("event_type") for event in events]


def events_for_subject(events: Sequence[Dict[str, Any]],
                       subject_id: str) -> List[Dict[str, Any]]:
    return [event for event in events if event.get("subject_id") == subject_id]


# ─── Domain worksheets ───────────────────────────────────────────────────────

ACCOUNTABILITY_FIELDS = (
    "basis",
    "lot_count",
    "gross_issued",
    "allowance_bp",
    "spoilage_credit",
    "net_issued",
    "accounted",
    "gross_variance",
    "net_variance",
    "tolerance_bp",
    "tolerance_ballots",
    "ballot_accountability_status",
)


def assert_accountability_worksheet(worksheet: Dict[str, Any],
                                    expected: Dict[str, Any]) -> None:
    """Assert the whole accountability line, field by field, and that none is missing."""
    for field in ACCOUNTABILITY_FIELDS:
        assert field in worksheet, f"accountability worksheet is missing {field}"
    assert_fields_equal(worksheet, expected, "accountability worksheet")


def assert_lot_conservation(lot: Dict[str, Any]) -> None:
    """Assert the lot accounting identity: received equals issued plus unused."""
    received = lot.get("quantity_received")
    issued = lot.get("issued_quantity")
    unused = lot.get("unused_quantity")
    assert received is not None, "lot must expose quantity_received"
    assert issued is not None, "lot must expose issued_quantity"
    assert unused is not None, "lot must expose unused_quantity"
    assert received == issued + unused, (
        f"lot conservation broken: quantity_received {received} != "
        f"issued_quantity {issued} + unused_quantity {unused}"
    )


def assert_invoice_zeroed(job: Dict[str, Any]) -> None:
    """Assert every invoice figure of a rejected job has been zeroed."""
    for field in ("invoice_subtotal_cents", "defect_credit_cents",
                  "freight_cents", "invoice_total_cents"):
        assert job.get(field) == 0, (
            f"rejected print job {field} expected 0, got {job.get(field)!r}"
        )


def assert_printed_positions(layout: Dict[str, Any], contest_id: str,
                             expected_positions: Dict[str, Optional[int]]) -> None:
    """Assert the printed_position of each candidate in one contest of a layout.

    ``expected_positions`` maps candidate id to the expected printed_position; a
    candidate id mapped to ``None`` must be absent from the contest block.
    """
    contests = layout.get("contests")
    assert isinstance(contests, list), f"layout.contests must be a list, got {contests!r}"
    block = next((entry for entry in contests if entry.get("contest_id") == contest_id), None)
    assert block is not None, f"layout has no block for contest {contest_id}"
    candidates = block.get("candidates")
    assert isinstance(candidates, list), (
        f"layout contest block candidates must be a list, got {candidates!r}"
    )
    actual = {entry.get("candidate_id"): entry.get("printed_position") for entry in candidates}
    for candidate_id, position in expected_positions.items():
        if position is None:
            assert candidate_id not in actual, (
                f"candidate {candidate_id} must not appear in the layout"
            )
        else:
            assert candidate_id in actual, f"candidate {candidate_id} is missing from the layout"
            assert actual[candidate_id] == position, (
                f"candidate {candidate_id} printed_position expected {position}, "
                f"got {actual[candidate_id]!r}"
            )


def find_by(rows: Iterable[Dict[str, Any]], field: str, value: Any) -> Dict[str, Any]:
    """Return the single row whose ``field`` equals ``value``."""
    matches = [row for row in rows if row.get(field) == value]
    assert len(matches) == 1, (
        f"expected exactly one row with {field}={value!r}, found {len(matches)}"
    )
    return matches[0]


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row.get("id") for row in rows]


def assert_iso_timestamp(value: Any, label: str = "timestamp") -> None:
    assert is_iso8601_timestamp(value), f"{label} must be an ISO 8601 UTC instant, got {value!r}"

"""Domain assertions built on the PRD's invariants and precision rules."""

from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import TOTAL_UNDIVIDED_INTEREST_BP
from .types import JsonDict


def as_decimal(value: Any) -> Decimal:
    """Normalise a 2-decimal-place field that may arrive as a string or number."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def assert_decimal_equals(actual: Any, expected: str, label: str = "value") -> None:
    """Compare a percentage/score field against its exact 2-dp expected value."""
    assert as_decimal(actual) == Decimal(expected), (
        "%s: expected %s, got %r" % (label, expected, actual)
    )


def assert_cents(actual: Any, expected: int, label: str = "cents") -> None:
    """Cents are whole numbers; never compare them as floats."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        "%s must be an integer number of cents, got %r" % (label, actual)
    )
    assert actual == expected, "%s: expected %d, got %d" % (label, expected, actual)


def assert_common_fields(entity: JsonDict) -> None:
    """Every entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), "id must be a uuid, got %r" % (entity.get("id"),)
    assert is_iso8601_timestamp(entity["created_at"]), (
        "created_at must be ISO-8601, got %r" % (entity.get("created_at"),)
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        "updated_at must be ISO-8601, got %r" % (entity.get("updated_at"),)
    )
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        "version must be an integer >= 1, got %r" % (entity.get("version"),)
    )


def canonical_instant(value: Any) -> Any:
    """Canonicalise an ISO-8601 UTC instant to whole microseconds.

    The PRD pins the *value* of every derived instant — notice periods, vacate
    deadlines, rescission deadlines, warranty and remediation bounds are exact
    multiples of 86400 or of whole seconds (2.8) — but it only ever pins a
    rendered fractional-digit convention for `created_at`, `updated_at` (2.5)
    and `api_request_timestamp` (2.2).  For every other `*_at` field the
    document is silent, so `...T00:00:00Z` and `...T00:00:00.000Z` denote the
    same contractual instant and neither rendering is derivable from the PRD.
    These assertions therefore compare instants, not their spellings.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1]
    if "." in text:
        head, _, frac = text.partition(".")
        frac = (frac + "000000")[:6]
    else:
        head, frac = text, "000000"
    return "%s.%sZ" % (head, frac)


def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare a stamped instant against the exact logical-clock value.

    Equality is on the instant itself; the fractional-digit spelling of a
    non-`created_at`/`updated_at` timestamp is not fixed by the PRD.
    """
    assert canonical_instant(actual) == canonical_instant(expected), (
        "%s: expected %s, got %r" % (label, expected, actual)
    )


def assert_escrow_conserved(project: JsonDict) -> None:
    """Escrow cash is conserved: received == balance + refunded + disbursed."""
    assert project["escrow_reconciliation_delta_cents"] == 0, (
        "escrow_reconciliation_delta_cents must read 0, got %r"
        % (project["escrow_reconciliation_delta_cents"],)
    )
    assert project["escrow_deposits_received_cents"] == (
        project["escrow_balance_cents"]
        + project["escrow_refunded_cents"]
        + project["escrow_disbursed_cents"]
    ), "escrow buckets do not sum to the received total: %r" % (project,)


def assert_relocation_conserved(project: JsonDict) -> None:
    """The relocation obligation is conserved: accrued == paid + reversed + outstanding."""
    assert project["relocation_reconciliation_delta_cents"] == 0, (
        "relocation_reconciliation_delta_cents must read 0, got %r"
        % (project["relocation_reconciliation_delta_cents"],)
    )
    assert project["relocation_obligation_accrued_cents"] == (
        project["relocation_paid_cents"]
        + project["relocation_reversed_cents"]
        + project["relocation_outstanding_cents"]
    ), "relocation buckets do not sum to the accrued total: %r" % (project,)


def assert_bp_conserved(project: JsonDict) -> None:
    """The undivided interest of the included set totals exactly 10000 bp."""
    if project["included_unit_count"] >= 1:
        assert project["bp_conservation_total"] == TOTAL_UNDIVIDED_INTEREST_BP, (
            "bp_conservation_total must read %d, got %r"
            % (TOTAL_UNDIVIDED_INTEREST_BP, project["bp_conservation_total"])
        )
    else:
        assert project["bp_conservation_total"] == 0, (
            "a project with no included unit must read bp_conservation_total 0, got %r"
            % (project["bp_conservation_total"],)
        )


def assert_all_conserved(project: JsonDict) -> None:
    """All three conserved quantities hold on the same project snapshot."""
    assert_escrow_conserved(project)
    assert_relocation_conserved(project)
    assert_bp_conserved(project)


def assert_no_write(before: JsonDict, after: JsonDict, label: str = "entity") -> None:
    """A refused request must leave the target row byte-identical."""
    assert after["version"] == before["version"], (
        "%s.version changed from %r to %r on a refused request"
        % (label, before["version"], after["version"])
    )
    assert after["updated_at"] == before["updated_at"], (
        "%s.updated_at changed on a refused request" % label
    )
    assert after == before, "%s was modified by a refused request" % label


def assert_fields(entity: JsonDict, expected: JsonDict, label: str = "entity") -> None:
    """Assert a bundle of exact field values on one entity."""
    for field, want in expected.items():
        assert field in entity, "%s is missing field %s" % (label, field)
        assert entity[field] == want, (
            "%s.%s: expected %r, got %r" % (label, field, want, entity[field])
        )


def assert_page(
    meta: JsonDict,
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """Assert the pagination envelope of a list read."""
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            "total_count: expected %d, got %r" % (total_count, meta["total_count"])
        )
    if limit is not None:
        assert meta["limit"] == limit, "limit: expected %d, got %r" % (limit, meta["limit"])
    if offset is not None:
        assert meta["offset"] == offset, (
            "offset: expected %d, got %r" % (offset, meta["offset"])
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            "has_more: expected %r, got %r" % (has_more, meta["has_more"])
        )


def ids_of(rows: Iterable[JsonDict]) -> list:
    """The `id` of every row, in the order the list read returned them."""
    return [row["id"] for row in rows]


def assert_id_order(rows: Sequence[JsonDict], expected_ids: Sequence[str]) -> None:
    """A list read returned exactly these ids in exactly this order."""
    assert ids_of(rows) == list(expected_ids), (
        "expected ids %r, got %r" % (list(expected_ids), ids_of(rows))
    )


def assert_error_body_shape(error_data: JsonDict) -> None:
    """An error payload carries exactly an error_id and a message."""
    assert set(error_data.keys()) == {"error_id", "message"}, (
        "error payload must carry exactly error_id and message, got %r"
        % (sorted(error_data.keys()),)
    )

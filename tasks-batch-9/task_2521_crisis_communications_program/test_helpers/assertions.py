"""Domain assertion helpers layered over the framework validators."""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Numeric precision
# ---------------------------------------------------------------------------


def assert_two_decimals(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a two-decimal quantity equals ``expected`` exactly (PRD §2.7)."""
    assert actual is not None, f"{label} is null"
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_four_decimals(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a four-decimal quantity equals ``expected`` exactly (PRD §2.7)."""
    assert actual is not None, f"{label} is null"
    assert round(float(actual), 4) == round(float(expected), 4), (
        f"{label}: expected {expected:.4f}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Common fields carried by every resource (PRD §2.4)
# ---------------------------------------------------------------------------


def assert_common_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """Assert ``id``, ``created_at``, ``updated_at`` and ``version`` are present
    and well formed (PRD §2.4)."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id is not a UUID: {entity.get('id')}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{label}.created_at malformed: {entity.get('created_at')}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        f"{label}.updated_at malformed: {entity.get('updated_at')}"
    )
    assert isinstance(entity.get("version"), int), f"{label}.version is not an integer"
    assert entity["version"] >= 1, f"{label}.version must start at 1"


def assert_version(entity: Dict[str, Any], expected: int, label: str = "entity") -> None:
    """Assert an entity's ``version`` counter (PRD §2.4)."""
    assert entity.get("version") == expected, (
        f"{label}.version: expected {expected}, got {entity.get('version')}"
    )


def assert_state(entity: Dict[str, Any], expected: str, label: str = "entity") -> None:
    """Assert an entity's ``state`` field."""
    assert entity.get("state") == expected, (
        f"{label}.state: expected {expected}, got {entity.get('state')}"
    )


def assert_field(
    entity: Dict[str, Any], field: str, expected: Any, label: str = "entity"
) -> None:
    """Assert one named field equals ``expected``."""
    assert entity.get(field) == expected, (
        f"{label}.{field}: expected {expected!r}, got {entity.get(field)!r}"
    )


def assert_fields(entity: Dict[str, Any], expected: Dict[str, Any], label: str = "entity") -> None:
    """Assert every field in ``expected`` matches."""
    for field, value in expected.items():
        assert_field(entity, field, value, label)


def assert_unchanged(
    before: Dict[str, Any], after: Dict[str, Any], fields: Iterable[str]
) -> None:
    """Assert a rejected operation left the named fields untouched (PRD §2.9)."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{field} changed from {before.get(field)!r} to {after.get(field)!r} "
            "on a rejected request"
        )


def assert_no_write(before: Dict[str, Any], after: Dict[str, Any], label: str = "entity") -> None:
    """Assert a rejected operation performed no write at all: the ``version``
    and ``updated_at`` of the target are unchanged (PRD §2.9)."""
    assert before.get("version") == after.get("version"), (
        f"{label}.version advanced on a rejected request: "
        f"{before.get('version')} -> {after.get('version')}"
    )
    assert before.get("updated_at") == after.get("updated_at"), (
        f"{label}.updated_at advanced on a rejected request"
    )


# ---------------------------------------------------------------------------
# Incident-shaped assertions
# ---------------------------------------------------------------------------


def assert_posture(incident: Dict[str, Any], expected: str) -> None:
    """Assert the incident's ``comms_posture`` (PRD §2.6)."""
    assert incident.get("comms_posture") == expected, (
        f"comms_posture: expected {expected}, got {incident.get('comms_posture')}"
    )


def assert_severity(
    incident: Dict[str, Any],
    tier: str,
    score: float,
    basis: Optional[str] = None,
) -> None:
    """Assert the banded severity reading on an incident (PRD §3.3)."""
    assert incident.get("severity_tier") == tier, (
        f"severity_tier: expected {tier}, got {incident.get('severity_tier')}"
    )
    assert_two_decimals(incident.get("severity_score"), score, "severity_score")
    if basis is not None:
        assert incident.get("severity_basis") == basis, (
            f"severity_basis: expected {basis}, got {incident.get('severity_basis')}"
        )


def assert_final_severity(incident: Dict[str, Any], tier: str, score: float) -> None:
    """Assert the final severity reading on a resolved incident (PRD §3.9)."""
    assert incident.get("final_severity_tier") == tier, (
        f"final_severity_tier: expected {tier}, got {incident.get('final_severity_tier')}"
    )
    assert_two_decimals(
        incident.get("final_severity_score"), score, "final_severity_score"
    )


def assert_containment(
    incident: Dict[str, Any], base: float, rate: float, total: float
) -> None:
    """Assert the containment priority family (PRD §3.3)."""
    assert_two_decimals(
        incident.get("base_containment_score"), base, "base_containment_score"
    )
    assert_two_decimals(
        incident.get("amplification_rate_applied"), rate, "amplification_rate_applied"
    )
    assert_two_decimals(
        incident.get("containment_priority_score"), total, "containment_priority_score"
    )


def assert_ledger(entity: Dict[str, Any], field: str, expected: int) -> None:
    """Assert one of the three conserved ledgers holds its recomputed value
    (PRD §2.7)."""
    assert entity.get(field) == expected, (
        f"conserved ledger {field}: expected {expected}, got {entity.get(field)}"
    )


# ---------------------------------------------------------------------------
# Collection assertions
# ---------------------------------------------------------------------------


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """Assert the listing envelope's meta block (PRD §2.3)."""
    assert "total_count" in meta, "meta.total_count missing"
    assert "has_more" in meta, "meta.has_more missing"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more: expected {has_more}, got {meta['has_more']}"
        )


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Assert the default listing order, ``created_at`` ascending (PRD §2.3)."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"


def assert_ids_equal(rows: List[Dict[str, Any]], expected_ids: List[str]) -> None:
    """Assert a listing returned exactly these ids, in this order."""
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, f"expected ids {expected_ids}, got {actual}"


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    """Ids of a row list, in returned order."""
    return [row["id"] for row in rows]


def find_by(rows: List[Dict[str, Any]], **criteria: Any) -> Dict[str, Any]:
    """Return the single row matching every criterion; fail if not exactly one."""
    matches = [
        row for row in rows if all(row.get(k) == v for k, v in criteria.items())
    ]
    assert len(matches) == 1, (
        f"expected exactly one row matching {criteria}, found {len(matches)}"
    )
    return matches[0]


def filter_by(rows: List[Dict[str, Any]], **criteria: Any) -> List[Dict[str, Any]]:
    """Return every row matching every criterion, preserving order."""
    return [row for row in rows if all(row.get(k) == v for k, v in criteria.items())]

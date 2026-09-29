"""Domain assertion helpers built on the framework validators."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

SETTLEMENT_FIGURE_FIELDS = (
    "eligible_cost_cents",
    "indirect_cost_cents",
    "betterment_credit_cents",
    "net_allowable_cents",
    "participation_tier_pct",
    "state_share_cents",
    "owner_share_cents",
)

CLEARANCE_SUMMARY_FIELDS = (
    "clearance_posture",
    "open_conflict_count",
    "untriaged_conflict_count",
    "overdue_commitment_count",
    "at_risk_commitment_count",
    "estimated_state_liability_cents",
    "total_committed_reimbursement_cents",
    "reimbursement_authority_cents",
    "remaining_authority_cents",
)


def assert_common_fields(row: dict) -> None:
    """Every mutable row carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id is not a uuid: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int), row["version"]
    assert row["version"] >= 1, row["version"]


def assert_immutable_record_fields(row: dict) -> None:
    """The subsurface investigation carries only id and created_at."""
    assert is_valid_uuid(row["id"]), f"id is not a uuid: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert "updated_at" not in row, "immutable record must not expose updated_at"
    assert "version" not in row, "immutable record must not expose version"


def assert_fields(row: dict, **expected) -> None:
    """Assert an exact value for each named field, reporting the field on failure."""
    for field, value in expected.items():
        assert field in row, f"missing field {field!r} in {sorted(row)}"
        assert row[field] == value, f"{field}: expected {value!r}, got {row[field]!r}"


def assert_settlement_figures(row: dict, **expected) -> None:
    """Assert the settlement figures carried by an agreement or a preview."""
    for field in expected:
        assert (
            field in SETTLEMENT_FIGURE_FIELDS
            or field
            in (
                "cost_basis",
                "not_to_exceed_cents",
                "included_document_count",
                "excluded_document_count",
            )
        ), f"{field!r} is not a settlement figure"
    assert_fields(row, **expected)


def assert_clearance_summary(summary: dict, **expected) -> None:
    for field in CLEARANCE_SUMMARY_FIELDS:
        assert field in summary, f"clearance summary is missing {field!r}"
    assert_fields(summary, **expected)


def assert_version_unchanged(before: dict, after: dict) -> None:
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} "
        "on an operation that should not have mutated the row"
    )


def assert_version_advanced_by(before: dict, after: dict, steps: int = 1) -> None:
    assert after["version"] == before["version"] + steps, (
        f"expected version {before['version'] + steps}, got {after['version']}"
    )


def assert_unchanged(before: dict, after: dict, *fields: str) -> None:
    for field in fields:
        assert after[field] == before[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r}"
        )


def assert_ordered_by_created_at(rows: list) -> None:
    """Every list response is ordered by created_at ascending, oldest first."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not oldest-first: {stamps}"


def assert_conserved(label: str, before: int, after: int) -> None:
    assert after == before, f"{label} was not restored: before {before}, after {after}"


def assert_no_row_created(data_and_meta) -> None:
    rows, meta = data_and_meta
    assert meta["total_count"] == 0, f"expected an empty collection, got {meta}"
    assert rows == [], rows


def assert_meta_envelope(response) -> dict:
    """Every response carries the request metadata block."""
    meta = response.json()["meta"]
    assert isinstance(meta.get("api_request_id"), str), meta
    assert isinstance(meta.get("api_request_timestamp"), str), meta
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta
    return meta


def assert_error_envelope(response) -> dict:
    """The error envelope names itself; it is never an empty success page."""
    body = response.json()
    assert body["response_type"] == "error", body
    assert_meta_envelope(response)
    return body["data"]


def assert_object_envelope(response) -> dict:
    body = response.json()
    assert body["response_type"] == "object", body
    assert_meta_envelope(response)
    return body["data"]


def days_between(start: str, end: str) -> int:
    """Calendar days between two instants, the end being exclusive."""
    from datetime import datetime

    fmt = "%Y-%m-%dT%H:%M:%S%z"
    a = datetime.strptime(start.replace("Z", "+0000"), fmt)
    b = datetime.strptime(end.replace("Z", "+0000"), fmt)
    return (b - a).days


__all__ = [
    "SETTLEMENT_FIGURE_FIELDS",
    "CLEARANCE_SUMMARY_FIELDS",
    "assert_common_fields",
    "assert_immutable_record_fields",
    "assert_fields",
    "assert_settlement_figures",
    "assert_clearance_summary",
    "assert_version_unchanged",
    "assert_version_advanced_by",
    "assert_unchanged",
    "assert_ordered_by_created_at",
    "assert_conserved",
    "assert_no_row_created",
    "assert_meta_envelope",
    "assert_error_envelope",
    "assert_object_envelope",
    "days_between",
]

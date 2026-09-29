"""Domain assertions for the cloud cost allocation & chargeback API."""

from typing import Any, Dict, Iterable, List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# Percentages are carried to two decimal places (PRD §2.6), so an absolute
# tolerance of a hundredth of a point is the right comparison granularity.
PCT_TOLERANCE = 0.005
RATIO_TOLERANCE = 0.00005


# ─── Common fields (PRD §2.4) ─────────────────────────────────────────────
def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the four fields PRD §2.4 puts on every entity but AllocationLine."""
    assert "id" in entity and entity["id"], f"missing id: {entity}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not an ISO 8601 UTC timestamp: {entity.get('updated_at')!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_freshly_created(entity: Dict[str, Any]) -> None:
    """A newly created entity starts at version 1 (PRD §2.4)."""
    assert_common_fields(entity, expected_version=1)


def assert_no_version_surface(line: Dict[str, Any]) -> None:
    """Assert an AllocationLine carries neither `updated_at` nor `version`.

    PRD §2.4 states the exemption explicitly, so the *absence* of the keys is
    the contract — not merely a null value.
    """
    assert "id" in line and line["id"], "an allocation line still needs an id"
    assert is_iso8601_timestamp(line["created_at"]), (
        f"created_at is not an ISO 8601 UTC timestamp: {line.get('created_at')!r}"
    )
    assert "version" not in line, "an allocation line must expose no version field"
    assert "updated_at" not in line, "an allocation line must expose no updated_at field"


def assert_id_format(value: str) -> None:
    assert isinstance(value, str) and value, f"not an identifier: {value!r}"


def assert_uuid_like(value: str) -> None:
    assert is_valid_uuid(value), f"not a UUID: {value!r}"


# ─── Numeric comparisons ──────────────────────────────────────────────────
def assert_cents(actual: Any, expected: int, label: str = "cents") -> None:
    """Money is carried as a whole number of cents (PRD §2.6)."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_pct(actual: Any, expected: float, label: str = "percentage") -> None:
    """Percentages are carried to two decimal places (PRD §2.6)."""
    assert actual == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_ratio(actual: Any, expected: float, label: str = "ratio") -> None:
    """`spike_ratio` is carried to four decimal places (PRD §2.6)."""
    assert actual == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


# ─── Entity-level invariants ──────────────────────────────────────────────
def assert_business_unit_derived_fields(
    unit: Dict[str, Any],
    resource_count: int,
    tracked_run_rate_cents: int,
    direct_spend_cents: int,
    showback_total_cents: int,
    chargeback_balance_cents: int,
) -> None:
    """Pin all five derived figures PRD §3.1 declares on a business unit."""
    assert unit["resource_count"] == resource_count, unit
    assert_cents(unit["tracked_run_rate_cents"], tracked_run_rate_cents, "tracked_run_rate_cents")
    assert_cents(unit["direct_spend_cents"], direct_spend_cents, "direct_spend_cents")
    assert_cents(unit["showback_total_cents"], showback_total_cents, "showback_total_cents")
    assert_cents(
        unit["chargeback_balance_cents"], chargeback_balance_cents, "chargeback_balance_cents"
    )


def assert_invoice_ledger(
    invoice: Dict[str, Any],
    gross_amount_cents: int,
    credited_amount_cents: int,
    paid_amount_cents: int,
    net_due_cents: int,
) -> None:
    """Pin the four ledger figures and the identity that binds them.

    PRD §3.6 states the identity `gross_amount_cents == credited_amount_cents +
    paid_amount_cents + net_due_cents` holds after every ledger movement.
    """
    assert_cents(invoice["gross_amount_cents"], gross_amount_cents, "gross_amount_cents")
    assert_cents(
        invoice["credited_amount_cents"], credited_amount_cents, "credited_amount_cents"
    )
    assert_cents(invoice["paid_amount_cents"], paid_amount_cents, "paid_amount_cents")
    assert_cents(invoice["net_due_cents"], net_due_cents, "net_due_cents")
    assert invoice["gross_amount_cents"] == (
        invoice["credited_amount_cents"]
        + invoice["paid_amount_cents"]
        + invoice["net_due_cents"]
    ), f"settlement ledger identity broken: {invoice}"


def assert_invoice_dimensions(
    invoice: Dict[str, Any], settlement_status: str, dispute_status: str
) -> None:
    """The two independent state dimensions PRD §3.6 declares on an invoice."""
    assert invoice["settlement_status"] == settlement_status, invoice
    assert invoice["dispute_status"] == dispute_status, invoice


def assert_allocation_line(
    line: Dict[str, Any],
    line_kind: str,
    method_applied: str,
    allocated_cents: int,
    basis_value: Optional[float] = None,
    rounding_remainder_cents: Optional[int] = None,
) -> None:
    assert line["line_kind"] == line_kind, line
    assert line["method_applied"] == method_applied, line
    assert_cents(line["allocated_cents"], allocated_cents, "allocated_cents")
    if basis_value is not None:
        assert_pct(line["basis_value"], basis_value, "basis_value")
    if rounding_remainder_cents is not None:
        assert_cents(
            line["rounding_remainder_cents"],
            rounding_remainder_cents,
            "rounding_remainder_cents",
        )


def assert_shares_sum_to_pool(lines: Iterable[Dict[str, Any]], pooled_cost_cents: int) -> None:
    """PRD §3.5 requires the shared lines to sum to the pooled amount exactly."""
    total = sum(line["allocated_cents"] for line in lines)
    assert total == pooled_cost_cents, (
        f"shared lines sum to {total}, pool holds {pooled_cost_cents} — a cent was "
        f"created or lost"
    )


def assert_commitment_figures(
    commitment: Dict[str, Any],
    committed_capacity_cents: int,
    covered_spend_cents: int,
    total_discount_cents: int,
    waste_cents: int,
    coverage_pct: float,
    utilization_pct: float,
) -> None:
    assert_cents(
        commitment["committed_capacity_cents"],
        committed_capacity_cents,
        "committed_capacity_cents",
    )
    assert_cents(commitment["covered_spend_cents"], covered_spend_cents, "covered_spend_cents")
    assert_cents(
        commitment["total_discount_cents"], total_discount_cents, "total_discount_cents"
    )
    assert_cents(commitment["waste_cents"], waste_cents, "waste_cents")
    assert_pct(commitment["coverage_pct"], coverage_pct, "coverage_pct")
    assert_pct(commitment["utilization_pct"], utilization_pct, "utilization_pct")


def assert_budget_evaluation(
    budget: Dict[str, Any],
    actual_spend_cents: int,
    variance_cents: int,
    variance_pct: float,
    warning_flag: bool,
    status: str,
    forecast_accuracy_pct: Optional[float] = None,
    accuracy_basis_applied: Optional[str] = None,
) -> None:
    assert_cents(budget["actual_spend_cents"], actual_spend_cents, "actual_spend_cents")
    assert_cents(budget["variance_cents"], variance_cents, "variance_cents")
    assert_pct(budget["variance_pct"], variance_pct, "variance_pct")
    assert budget["warning_flag"] is warning_flag, budget
    assert budget["status"] == status, budget
    if forecast_accuracy_pct is not None:
        assert_pct(budget["forecast_accuracy_pct"], forecast_accuracy_pct, "forecast_accuracy_pct")
    if accuracy_basis_applied is not None:
        assert budget["accuracy_basis_applied"] == accuracy_basis_applied, budget


def assert_remediation_task(
    task: Dict[str, Any],
    kind: str,
    status: str,
    observed_utilization_pct: float,
    projected_savings_cents: int,
    waste_score: float,
    auto_remediation_eligible: bool,
) -> None:
    assert task["kind"] == kind, task
    assert task["status"] == status, task
    assert_pct(task["observed_utilization_pct"], observed_utilization_pct, "observed_utilization_pct")
    assert_cents(
        task["projected_savings_cents"], projected_savings_cents, "projected_savings_cents"
    )
    assert_pct(task["waste_score"], waste_score, "waste_score")
    assert task["auto_remediation_eligible"] is auto_remediation_eligible, task


def assert_tag_compliance(
    request: Dict[str, Any],
    missing_dimensions: List[str],
    compliance_score: float,
    projected_tag_state: str,
    status: Optional[str] = None,
) -> None:
    assert request["missing_dimensions"] == missing_dimensions, request
    assert_pct(request["compliance_score"], compliance_score, "compliance_score")
    assert request["projected_tag_state"] == projected_tag_state, request
    if status is not None:
        assert request["status"] == status, request


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: int,
    has_more: bool,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    assert meta["total_count"] == total_count, meta
    assert meta["has_more"] is has_more, meta
    if limit is not None:
        assert meta["limit"] == limit, meta
    if offset is not None:
        assert meta["offset"] == offset, meta


def assert_nulls(entity: Dict[str, Any], *field_names: str) -> None:
    for name in field_names:
        assert entity.get(name, "__missing__") is None, (
            f"expected {name} to be null, got {entity.get(name)!r}"
        )


def find_by(rows: Iterable[Dict[str, Any]], **criteria) -> Dict[str, Any]:
    """Return the single row matching every keyword criterion."""
    matches = [
        row for row in rows if all(row.get(key) == value for key, value in criteria.items())
    ]
    assert len(matches) == 1, (
        f"expected exactly one row matching {criteria}, found {len(matches)}"
    )
    return matches[0]

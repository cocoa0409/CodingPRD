"""
Domain assertions for the Individual Artist Fellowship Grants API.

These wrap the generic structural helpers with the field names and invariants
the PRD declares, so a failing test names the business rule it broke.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MONEY_TOLERANCE = 0
SCORE_TOLERANCE = 0.005
RATE_TOLERANCE = 0.00005


# ---------------------------------------------------------------------------
# Common envelope fields
# ---------------------------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """Every entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity.get("id", "")), f"{label}.id is not a UUID: {entity.get('id')!r}"
    for stamp in ("created_at", "updated_at"):
        assert is_iso8601_timestamp(entity.get(stamp, "")), (
            f"{label}.{stamp} is not an ISO 8601 UTC timestamp: {entity.get(stamp)!r}"
        )
    assert isinstance(entity.get("version"), int) and entity["version"] >= 1, (
        f"{label}.version must be a positive integer, got {entity.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Numeric precision
# ---------------------------------------------------------------------------
def assert_score(actual: Optional[float], expected: Optional[float], label: str) -> None:
    """Scores are carried to two decimal places."""
    if expected is None:
        assert actual is None, f"{label} should be null, got {actual!r}"
        return
    assert actual is not None, f"{label} should be {expected}, got null"
    assert actual == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"{label} should be {expected}, got {actual}"
    )


def assert_rate(actual: Optional[float], expected: Optional[float], label: str) -> None:
    """Rates such as region_hhi and funded_rate carry four decimal places."""
    if expected is None:
        assert actual is None, f"{label} should be null, got {actual!r}"
        return
    assert actual is not None, f"{label} should be {expected}, got null"
    assert actual == pytest.approx(expected, abs=RATE_TOLERANCE), (
        f"{label} should be {expected}, got {actual}"
    )


def assert_cents(actual: Any, expected: int, label: str) -> None:
    """Money is carried in whole cents, so equality must be exact."""
    assert actual == expected, f"{label} should be {expected} cents, got {actual}"


# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------
def assert_cycle_ledger(
    cycle: Dict[str, Any],
    funded_total_cents: int,
    admin_assessment_rate: float,
    admin_assessment_cents: int,
    reserve_cents: int,
    committed_cents: int,
    available_cents: int,
    posture: str,
) -> None:
    """All six derived fiscal fields plus the posture, checked together."""
    assert_cents(cycle["funded_total_cents"], funded_total_cents, "cycle.funded_total_cents")
    assert cycle["admin_assessment_rate"] == pytest.approx(
        admin_assessment_rate, abs=RATE_TOLERANCE
    ), (
        "cycle.admin_assessment_rate should be "
        f"{admin_assessment_rate}, got {cycle['admin_assessment_rate']}"
    )
    assert_cents(
        cycle["admin_assessment_cents"], admin_assessment_cents, "cycle.admin_assessment_cents"
    )
    assert_cents(cycle["reserve_cents"], reserve_cents, "cycle.reserve_cents")
    assert_cents(cycle["committed_cents"], committed_cents, "cycle.committed_cents")
    assert_cents(cycle["available_cents"], available_cents, "cycle.available_cents")
    assert cycle["posture"] == posture, (
        f"cycle.posture should be {posture}, got {cycle['posture']}"
    )


def assert_committed_identity(cycle: Dict[str, Any]) -> None:
    """committed_cents == funded_total_cents + admin_assessment_cents."""
    assert cycle["committed_cents"] == (
        cycle["funded_total_cents"] + cycle["admin_assessment_cents"]
    ), (
        "committed_cents must equal funded_total_cents + admin_assessment_cents: "
        f"{cycle['committed_cents']} != {cycle['funded_total_cents']} + "
        f"{cycle['admin_assessment_cents']}"
    )


def assert_available_identity(cycle: Dict[str, Any]) -> None:
    """available_cents == total_budget_cents - committed_cents - reserve_cents."""
    assert cycle["available_cents"] == (
        cycle["total_budget_cents"] - cycle["committed_cents"] - cycle["reserve_cents"]
    ), (
        "available_cents must equal total_budget_cents - committed_cents - reserve_cents: "
        f"got {cycle['available_cents']}"
    )


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def assert_application_scores(
    application: Dict[str, Any],
    valid_review_count: int,
    provisional_composite_score: Optional[float],
    final_composite_score: Optional[float],
    score_spread: Optional[float],
) -> None:
    assert application["valid_review_count"] == valid_review_count, (
        f"application.valid_review_count should be {valid_review_count}, "
        f"got {application['valid_review_count']}"
    )
    assert_score(
        application["provisional_composite_score"],
        provisional_composite_score,
        "application.provisional_composite_score",
    )
    assert_score(
        application["final_composite_score"],
        final_composite_score,
        "application.final_composite_score",
    )
    assert_score(application["score_spread"], score_spread, "application.score_spread")


def assert_frozen_snapshot(
    application: Dict[str, Any],
    applicant_legal_name: str,
    applicant_region: str,
    residency_months_at_deadline: int,
) -> None:
    """The applicant snapshot frozen at submission."""
    assert application["applicant_legal_name"] == applicant_legal_name, (
        f"application.applicant_legal_name should be {applicant_legal_name!r}, "
        f"got {application['applicant_legal_name']!r}"
    )
    assert application["applicant_region"] == applicant_region, (
        f"application.applicant_region should be {applicant_region!r}, "
        f"got {application['applicant_region']!r}"
    )
    assert application["residency_months_at_deadline"] == residency_months_at_deadline, (
        "application.residency_months_at_deadline should be "
        f"{residency_months_at_deadline}, got {application['residency_months_at_deadline']}"
    )


def assert_unsubmitted_draft(application: Dict[str, Any]) -> None:
    """A rejected submit must leave every submission-stamped field untouched."""
    assert application["status"] == "DRAFT", (
        f"application.status should stay DRAFT, got {application['status']}"
    )
    for field in ("submitted_at", "sealed_alias", "residency_months_at_deadline"):
        assert application[field] is None, (
            f"application.{field} should stay null on a rejected submit, "
            f"got {application[field]!r}"
        )


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
def assert_panel_readiness(
    panel: Dict[str, Any],
    seated_count: int,
    region_coverage_count: int,
    blocking_conflict_count: int,
    readiness_score: float,
) -> None:
    assert panel["seated_count"] == seated_count, (
        f"panel.seated_count should be {seated_count}, got {panel['seated_count']}"
    )
    assert panel["region_coverage_count"] == region_coverage_count, (
        f"panel.region_coverage_count should be {region_coverage_count}, "
        f"got {panel['region_coverage_count']}"
    )
    assert panel["blocking_conflict_count"] == blocking_conflict_count, (
        f"panel.blocking_conflict_count should be {blocking_conflict_count}, "
        f"got {panel['blocking_conflict_count']}"
    )
    assert_score(panel["readiness_score"], readiness_score, "panel.readiness_score")


# ---------------------------------------------------------------------------
# Award and installments
# ---------------------------------------------------------------------------
def assert_award_dimensions(
    award: Dict[str, Any], status: str, payment_status: str, reporting_status: str
) -> None:
    """The award's three independent state dimensions."""
    assert award["status"] == status, (
        f"award.status should be {status}, got {award['status']}"
    )
    assert award["payment_status"] == payment_status, (
        f"award.payment_status should be {payment_status}, got {award['payment_status']}"
    )
    assert award["reporting_status"] == reporting_status, (
        f"award.reporting_status should be {reporting_status}, got {award['reporting_status']}"
    )


def assert_award_ledger(
    award: Dict[str, Any],
    disbursed_gross_cents: int,
    disbursed_net_cents: int,
    total_withholding_cents: int,
    undisbursed_gross_cents: int,
) -> None:
    assert_cents(
        award["disbursed_gross_cents"], disbursed_gross_cents, "award.disbursed_gross_cents"
    )
    assert_cents(
        award["disbursed_net_cents"], disbursed_net_cents, "award.disbursed_net_cents"
    )
    assert_cents(
        award["total_withholding_cents"],
        total_withholding_cents,
        "award.total_withholding_cents",
    )
    assert_cents(
        award["undisbursed_gross_cents"],
        undisbursed_gross_cents,
        "award.undisbursed_gross_cents",
    )


def assert_gross_conservation(award: Dict[str, Any], installments: List[Dict[str, Any]]) -> None:
    """
    An award's gross must equal the sum of `gross_cents` over its installments in
    SCHEDULED, HELD, RELEASED and PAID.
    """
    live = [
        row
        for row in installments
        if row["status"] in ("SCHEDULED", "HELD", "RELEASED", "PAID")
    ]
    total = sum(row["gross_cents"] for row in live)
    assert total == award["gross_amount_cents"], (
        "sum of gross_cents over live installments must equal award.gross_amount_cents: "
        f"{total} != {award['gross_amount_cents']} "
        f"(statuses seen: {[row['status'] for row in installments]})"
    )


def assert_installment(
    installment: Dict[str, Any],
    installment_number: int,
    gross_cents: int,
    withholding_rate: float,
    withholding_cents: int,
    net_cents: int,
    scheduled_date: Optional[str] = None,
) -> None:
    assert installment["installment_number"] == installment_number, (
        f"installment_number should be {installment_number}, "
        f"got {installment['installment_number']}"
    )
    assert_cents(installment["gross_cents"], gross_cents, "installment.gross_cents")
    assert installment["withholding_rate"] == pytest.approx(
        withholding_rate, abs=RATE_TOLERANCE
    ), (
        f"installment.withholding_rate should be {withholding_rate}, "
        f"got {installment['withholding_rate']}"
    )
    assert_cents(
        installment["withholding_cents"], withholding_cents, "installment.withholding_cents"
    )
    assert_cents(installment["net_cents"], net_cents, "installment.net_cents")
    if scheduled_date is not None:
        assert str(installment["scheduled_date"]).startswith(scheduled_date), (
            f"installment.scheduled_date should be {scheduled_date}, "
            f"got {installment['scheduled_date']}"
        )


def assert_net_identity(installment: Dict[str, Any]) -> None:
    assert (
        installment["net_cents"] == installment["gross_cents"] - installment["withholding_cents"]
    ), (
        "net_cents must equal gross_cents minus withholding_cents: "
        f"{installment['net_cents']} != {installment['gross_cents']} - "
        f"{installment['withholding_cents']}"
    )


# ---------------------------------------------------------------------------
# Ordering helpers
# ---------------------------------------------------------------------------
def assert_ordered_by(rows: List[Dict[str, Any]], field: str, descending: bool = False) -> None:
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows should be ordered by {field} "
        f"{'DESC' if descending else 'ASC'}, got {values}"
    )


def assert_ledger_snapshot_equal(
    before: Dict[str, Any], after: Dict[str, Any], fields: List[str]
) -> None:
    """A compensating action must restore each named field to its earlier value."""
    for field in fields:
        assert after[field] == before[field], (
            f"{field} was not restored: before={before[field]!r} after={after[field]!r}"
        )

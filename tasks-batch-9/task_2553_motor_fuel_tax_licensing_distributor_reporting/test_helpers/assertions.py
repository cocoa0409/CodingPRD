"""Domain assertions for the Motor Fuel Tax API."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    REFUND_RATE_CENTS_PER_GALLON,
    TAX_RATES_CENTS_PER_GALLON,
)

Json = Dict[str, Any]

GALLONS_TOLERANCE = 0.005


# --------------------------------------------------------------------------
# Money and gallons arithmetic, mirroring the PRD's rounding discipline
# --------------------------------------------------------------------------


def cents_for(gallons: Any, product_code: str) -> int:
    """Gallons multiplied by the product rate once and rounded half up once."""
    quantity = Decimal(str(gallons))
    rate = TAX_RATES_CENTS_PER_GALLON[product_code]
    return int((quantity * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def refund_cents_for(gallons: Any) -> int:
    """Allowable gallons multiplied by 30.9 cents per gallon, rounded half up once."""
    quantity = Decimal(str(gallons))
    return int(
        (quantity * REFUND_RATE_CENTS_PER_GALLON).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def assert_gallons(actual: Any, expected: Any, label: str = "gallons") -> None:
    assert actual is not None, f"{label} is missing from the response"
    assert float(actual) == pytest.approx(
        float(expected), abs=GALLONS_TOLERANCE
    ), f"{label} should be {expected} at two decimals but was {actual}"


def assert_cents(actual: Any, expected: int, label: str = "amount_cents") -> None:
    assert actual == expected, f"{label} should be exactly {expected} cents but was {actual}"
    assert isinstance(actual, int), f"{label} must be an integer number of cents, got {actual!r}"


# --------------------------------------------------------------------------
# Common resource properties
# --------------------------------------------------------------------------


def assert_mutable_common_fields(row: Json, expected_version: Optional[int] = None) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row.get("id")), f"id should be a UUID, got {row.get('id')!r}"
    assert is_iso8601_timestamp(
        row.get("created_at")
    ), f"created_at should be an ISO 8601 UTC instant, got {row.get('created_at')!r}"
    assert is_iso8601_timestamp(
        row.get("updated_at")
    ), f"updated_at should be an ISO 8601 UTC instant, got {row.get('updated_at')!r}"
    assert isinstance(row.get("version"), int), "version should be an integer"
    if expected_version is not None:
        assert (
            row["version"] == expected_version
        ), f"version should be {expected_version} but was {row['version']}"


def assert_append_only_common_fields(row: Json) -> None:
    """An append-only observation carries only id and created_at."""
    assert is_valid_uuid(row.get("id")), f"id should be a UUID, got {row.get('id')!r}"
    assert is_iso8601_timestamp(
        row.get("created_at")
    ), f"created_at should be an ISO 8601 UTC instant, got {row.get('created_at')!r}"
    assert (
        "updated_at" not in row
    ), "an append-only record must not carry updated_at at all"
    assert "version" not in row, "an append-only record must not carry version at all"


def assert_starts_at(value: Any, prefix: str, label: str = "timestamp") -> None:
    assert value is not None, f"{label} is missing from the response"
    assert str(value).startswith(
        prefix
    ), f"{label} should be {prefix} but was {value}"


# --------------------------------------------------------------------------
# Licensees, bonding and the ledger
# --------------------------------------------------------------------------


def assert_zero_compliance_counters(licensee: Json) -> None:
    """Every compliance counter of a freshly registered licensee starts at 0."""
    assert_cents(licensee["balance_cents"], 0, "balance_cents")
    for field in (
        "dyed_violation_count",
        "late_filing_count",
        "open_audit_count",
        "open_discrepancy_count",
        "risk_score_variance_weighted",
        "risk_score_frequency_weighted",
    ):
        assert licensee[field] == 0, f"{field} should start at 0 but was {licensee[field]}"
    assert_gallons(licensee["unreported_gallons_total"], 0.00, "unreported_gallons_total")
    assert_gallons(
        licensee["effective_taxable_gallons_ytd"], 0.00, "effective_taxable_gallons_ytd"
    )


def assert_bond_position(
    row: Json,
    required_bond_cents: Optional[int] = None,
    posted_bond_cents: Optional[int] = None,
    bond_deficiency_cents: Optional[int] = None,
    avg_monthly_tax_liability_cents: Optional[int] = None,
    basis_return_count: Optional[int] = None,
) -> None:
    if required_bond_cents is not None:
        assert_cents(row["required_bond_cents"], required_bond_cents, "required_bond_cents")
    if posted_bond_cents is not None:
        assert_cents(row["posted_bond_cents"], posted_bond_cents, "posted_bond_cents")
    if bond_deficiency_cents is not None:
        assert_cents(
            row["bond_deficiency_cents"], bond_deficiency_cents, "bond_deficiency_cents"
        )
    if avg_monthly_tax_liability_cents is not None:
        assert_cents(
            row["avg_monthly_tax_liability_cents"],
            avg_monthly_tax_liability_cents,
            "avg_monthly_tax_liability_cents",
        )
    if basis_return_count is not None:
        assert (
            row["basis_return_count"] == basis_return_count
        ), f"basis_return_count should be {basis_return_count} but was {row['basis_return_count']}"


def assert_bond_instrument(
    bond: Json, status: str, release_reason: Optional[str], amount_cents: Optional[int] = None
) -> None:
    assert bond["status"] == status, f"bond status should be {status} but was {bond['status']}"
    assert (
        bond.get("release_reason") == release_reason
    ), f"release_reason should be {release_reason!r} but was {bond.get('release_reason')!r}"
    if amount_cents is not None:
        assert_cents(bond["amount_cents"], amount_cents, "bond amount_cents")


def assert_ledger_row(
    entry: Json,
    entry_type: str,
    amount_cents: int,
    source_entity_type: Optional[str] = None,
    source_entity_id: Optional[str] = None,
) -> None:
    assert (
        entry["entry_type"] == entry_type
    ), f"entry_type should be {entry_type} but was {entry['entry_type']}"
    assert_cents(entry["amount_cents"], amount_cents, f"{entry_type} amount_cents")
    if source_entity_type is not None:
        assert entry["source_entity_type"] == source_entity_type, (
            f"source_entity_type should be {source_entity_type} but was "
            f"{entry['source_entity_type']}"
        )
    if source_entity_id is not None:
        assert (
            entry["source_entity_id"] == source_entity_id
        ), "source_entity_id should point back at the row that caused the posting"


def assert_ledger_sequence(entries: List[Json], expected: List[Any]) -> None:
    """Assert the ledger is exactly the given (entry_type, amount_cents) sequence."""
    actual = [(e["entry_type"], e["amount_cents"]) for e in entries]
    assert actual == [tuple(item) for item in expected], (
        f"the ledger should read {expected} in created_at order but read {actual}"
    )


def assert_balance_matches_ledger(licensee: Json, entries: List[Json]) -> None:
    """Invariant M: balance_cents equals the signed sum of the ledger entries."""
    signed_sum = sum(e["amount_cents"] for e in entries)
    assert_cents(
        licensee["balance_cents"],
        signed_sum,
        "balance_cents (the signed sum of the ledger)",
    )


# --------------------------------------------------------------------------
# Rack removals
# --------------------------------------------------------------------------


def assert_imposition(
    removal: Json,
    basis_used: str,
    imposition_point: str,
    taxable_gallons: Any,
    tax_imposed: bool,
    tax_amount_cents: int,
    deferred_tax_cents: int,
) -> None:
    assert (
        removal["basis_used"] == basis_used
    ), f"basis_used should be {basis_used} but was {removal['basis_used']}"
    assert removal["imposition_point"] == imposition_point, (
        f"imposition_point should be {imposition_point} but was {removal['imposition_point']}"
    )
    assert_gallons(removal["taxable_gallons"], taxable_gallons, "taxable_gallons")
    assert (
        removal["tax_imposed"] is tax_imposed
    ), f"tax_imposed should be {tax_imposed} but was {removal['tax_imposed']}"
    assert_cents(removal["tax_amount_cents"], tax_amount_cents, "tax_amount_cents")
    assert_cents(removal["deferred_tax_cents"], deferred_tax_cents, "deferred_tax_cents")


# --------------------------------------------------------------------------
# Returns
# --------------------------------------------------------------------------


def assert_return_money(
    monthly_return: Json,
    taxable_gallons_total: Optional[Any] = None,
    tax_due_cents: Optional[int] = None,
    interest_cents: Optional[int] = None,
    penalty_cents: Optional[int] = None,
    total_remittance_cents: Optional[int] = None,
    days_late: Optional[int] = None,
    amendment_delta_cents: Optional[int] = None,
) -> None:
    if taxable_gallons_total is not None:
        assert_gallons(
            monthly_return["taxable_gallons_total"],
            taxable_gallons_total,
            "taxable_gallons_total",
        )
    if tax_due_cents is not None:
        assert_cents(monthly_return["tax_due_cents"], tax_due_cents, "tax_due_cents")
    if interest_cents is not None:
        assert_cents(monthly_return["interest_cents"], interest_cents, "interest_cents")
    if penalty_cents is not None:
        assert_cents(monthly_return["penalty_cents"], penalty_cents, "penalty_cents")
    if total_remittance_cents is not None:
        assert_cents(
            monthly_return["total_remittance_cents"],
            total_remittance_cents,
            "total_remittance_cents",
        )
    if days_late is not None:
        assert (
            monthly_return["days_late"] == days_late
        ), f"days_late should be {days_late} but was {monthly_return['days_late']}"
    if amendment_delta_cents is not None:
        assert_cents(
            monthly_return["amendment_delta_cents"],
            amendment_delta_cents,
            "amendment_delta_cents",
        )


def assert_return_statuses(
    monthly_return: Json, filing_status: str, match_status: Optional[str] = None
) -> None:
    assert monthly_return["filing_status"] == filing_status, (
        f"filing_status should be {filing_status} but was {monthly_return['filing_status']}"
    )
    if match_status is not None:
        assert monthly_return["match_status"] == match_status, (
            f"match_status should be {match_status} but was {monthly_return['match_status']}"
        )


# --------------------------------------------------------------------------
# Refund claims
# --------------------------------------------------------------------------


def assert_claim_money(
    claim: Json, allowable_gallons: Any, refund_amount_cents: int
) -> None:
    assert_gallons(claim["allowable_gallons"], allowable_gallons, "allowable_gallons")
    assert_cents(claim["refund_amount_cents"], refund_amount_cents, "refund_amount_cents")


def assert_claim_hold(claim: Json, hold_reason: str, status_before_hold: str) -> None:
    assert claim["status"] == "HELD", f"claim status should be HELD but was {claim['status']}"
    assert (
        claim["hold_reason"] == hold_reason
    ), f"hold_reason should be {hold_reason} but was {claim['hold_reason']}"
    assert claim["status_before_hold"] == status_before_hold, (
        f"status_before_hold should be {status_before_hold} but was "
        f"{claim['status_before_hold']}"
    )


def assert_claim_not_held(claim: Json, status: str) -> None:
    assert claim["status"] == status, f"claim status should be {status} but was {claim['status']}"
    assert claim["hold_reason"] is None, "hold_reason should be cleared back to null"
    assert claim["status_before_hold"] is None, "status_before_hold should be cleared back to null"


def assert_nulls(row: Json, fields: List[str]) -> None:
    for field in fields:
        assert row.get(field) is None, f"{field} should still be null but was {row.get(field)!r}"


# --------------------------------------------------------------------------
# Audit cases
# --------------------------------------------------------------------------


def assert_case_dimensions(
    case: Json, case_status: str, assessment_status: Optional[str] = None
) -> None:
    assert (
        case["case_status"] == case_status
    ), f"case_status should be {case_status} but was {case['case_status']}"
    if assessment_status is not None:
        assert case["assessment_status"] == assessment_status, (
            f"assessment_status should be {assessment_status} but was "
            f"{case['assessment_status']}"
        )


def assert_assessment_money(
    case: Json,
    additional_tax_cents: int,
    assessment_penalty_cents: int,
    assessment_interest_cents: int,
    assessed_total_cents: int,
) -> None:
    assert_cents(case["additional_tax_cents"], additional_tax_cents, "additional_tax_cents")
    assert_cents(
        case["assessment_penalty_cents"], assessment_penalty_cents, "assessment_penalty_cents"
    )
    assert_cents(
        case["assessment_interest_cents"], assessment_interest_cents, "assessment_interest_cents"
    )
    assert_cents(case["assessed_total_cents"], assessed_total_cents, "assessed_total_cents")


# --------------------------------------------------------------------------
# Lists
# --------------------------------------------------------------------------


def assert_total_count(meta: Json, expected: int, label: str = "total_count") -> None:
    assert (
        meta["total_count"] == expected
    ), f"{label} should be {expected} but was {meta['total_count']}"


def ids_of(rows: List[Json]) -> List[str]:
    return [row["id"] for row in rows]


__all__ = [
    "GALLONS_TOLERANCE",
    "cents_for",
    "refund_cents_for",
    "assert_gallons",
    "assert_cents",
    "assert_mutable_common_fields",
    "assert_append_only_common_fields",
    "assert_starts_at",
    "assert_zero_compliance_counters",
    "assert_bond_position",
    "assert_bond_instrument",
    "assert_ledger_row",
    "assert_ledger_sequence",
    "assert_balance_matches_ledger",
    "assert_imposition",
    "assert_return_money",
    "assert_return_statuses",
    "assert_claim_money",
    "assert_claim_hold",
    "assert_claim_not_held",
    "assert_nulls",
    "assert_case_dimensions",
    "assert_assessment_money",
    "assert_total_count",
    "ids_of",
]

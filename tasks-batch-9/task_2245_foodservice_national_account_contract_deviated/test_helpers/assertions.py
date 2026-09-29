"""Domain assertions: common property checks, per-entity shape checks and the
two ledger conservation identities the PRD declares.
"""
import re
from typing import Any, Dict, Iterable, List

import pytest

from prd_bench_local_runner.testing import is_valid_uuid

from . import types as t

# ISO-8601 UTC with exactly three fractional-second digits.
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_millisecond_timestamp(value: str, label: str = "timestamp") -> None:
    """A server-minted audit timestamp carries exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _TIMESTAMP_RE.match(value), (
        f"{label} must be ISO-8601 UTC with three fractional digits, got {value!r}"
    )


def assert_common_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """Every entity carries id, created_at, updated_at and version."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"{label} is missing '{field}'"
    assert is_valid_uuid(entity["id"]), f"{label}.id must be a UUID, got {entity['id']!r}"
    assert_millisecond_timestamp(entity["created_at"], f"{label}.created_at")
    assert_millisecond_timestamp(entity["updated_at"], f"{label}.updated_at")
    assert isinstance(entity["version"], int), f"{label}.version must be an integer"
    assert entity["version"] >= 1, f"{label}.version must start at 1"


def assert_fields_present(
    entity: Dict[str, Any], fields: Iterable[str], label: str = "entity"
) -> None:
    missing = [f for f in fields if f not in entity]
    assert not missing, f"{label} is missing declared fields: {missing}"


def _shape(entity: Dict[str, Any], typed_dict, label: str) -> Dict[str, Any]:
    assert_fields_present(entity, typed_dict.__annotations__.keys(), label)
    assert_common_fields(entity, label)
    return entity


def assert_operator(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.Operator, "operator")


def assert_manufacturer(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.Manufacturer, "manufacturer")


def assert_distribution_center(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.DistributionCenter, "distribution_center")


def assert_product(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.Product, "product")


def assert_contract(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.Contract, "contract")


def assert_contract_tier(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.ContractTier, "contract_tier")


def assert_dc_coverage(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.DcCoverage, "dc_coverage")


def assert_deviation_agreement(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.DeviationAgreement, "deviation_agreement")


def assert_substitution_rule(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.SubstitutionRule, "substitution_rule")


def assert_price_change_notice(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.PriceChangeNotice, "price_change_notice")


def assert_rebate_period(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.RebatePeriod, "rebate_period")


def assert_order_line(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.OrderLine, "order_line")


def assert_bill_back_claim(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.BillBackClaim, "bill_back_claim")


def assert_bill_back_remittance(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.BillBackRemittance, "bill_back_remittance")


def assert_pricing_dispute(data: Dict[str, Any]) -> Dict[str, Any]:
    return _shape(data, t.PricingDispute, "pricing_dispute")


# --------------------------------------------------------------------------
# Money and percentages
# --------------------------------------------------------------------------

def assert_pct(actual: Any, expected: float, label: str = "percentage") -> None:
    """Percentages are carried to two decimal places."""
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label} expected {expected}, got {actual}"
    )


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Money is an integer number of cents; no tolerance is allowed."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label} expected {expected} cents, got {actual}"


# --------------------------------------------------------------------------
# Ledger conservation
# --------------------------------------------------------------------------

def assert_rebate_liability_conserved(
    contract: Dict[str, Any], periods: List[Dict[str, Any]]
) -> None:
    """rebate_payable_cents + rebate_settled_total_cents equals the sum of
    operator_rebate_cents over the contract's CLOSED and SETTLED periods."""
    accrued = sum(
        period.get("operator_rebate_cents") or 0
        for period in periods
        if period.get("status") in ("CLOSED", "SETTLED")
    )
    total = contract["rebate_payable_cents"] + contract["rebate_settled_total_cents"]
    assert total == accrued, (
        "rebate_payable_cents + rebate_settled_total_cents must equal the accrued "
        f"rebate over closed and settled periods: {total} != {accrued}"
    )


def assert_manufacturer_cash_conserved(
    manufacturer: Dict[str, Any], claims: List[Dict[str, Any]]
) -> None:
    """total_remitted_cents equals the recovered amounts across all claims plus
    the manufacturer's unapplied credit."""
    recovered = sum(claim.get("recovered_amount_cents") or 0 for claim in claims)
    expected = recovered + manufacturer["unapplied_credit_cents"]
    assert manufacturer["total_remitted_cents"] == expected, (
        "total_remitted_cents must equal recovered claim cash plus unapplied "
        f"credit: {manufacturer['total_remitted_cents']} != {expected}"
    )


def assert_rebate_split(period: Dict[str, Any]) -> None:
    """The manufacturer and distributor shares add back to the operator rebate."""
    total = (
        period["manufacturer_funded_cents"] + period["distributor_funded_cents"]
    )
    assert total == period["operator_rebate_cents"], (
        "manufacturer_funded_cents + distributor_funded_cents must equal "
        f"operator_rebate_cents: {total} != {period['operator_rebate_cents']}"
    )

"""Domain assertion helpers layered on the framework validators."""
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)


def assert_money_cents(value: Any, expected: int, label: str = "amount") -> None:
    """Monetary quantities are whole-cent integers, never floats."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer count of cents, got {value!r}"
    )
    assert value == expected, f"{label} expected {expected} cents, got {value}"


def assert_non_negative_money(value: Any, label: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer count of cents, got {value!r}"
    )
    assert value >= 0, f"{label} must never go negative, got {value}"


def assert_ratio_4dp(value: Any, expected: float, label: str = "metric") -> None:
    """Rates and percentages carry four decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 4) == round(expected, 4), (
        f"{label} expected {expected} to four decimals, got {value}"
    )


def assert_score_2dp(value: Any, expected: float, label: str = "score") -> None:
    """Composite scores carry two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == round(expected, 2), (
        f"{label} expected {expected} to two decimals, got {value}"
    )


def assert_entity_envelope(entity: Dict[str, Any], *, versioned: bool = True) -> None:
    """Common identity and audit fields on a persisted row."""
    assert is_valid_uuid(entity.get("id")), f"id must be a UUID, got {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"created_at must be an ISO-8601 UTC instant, got {entity.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(entity.get("updated_at")), (
            f"updated_at must be an ISO-8601 UTC instant, got {entity.get('updated_at')!r}"
        )
        assert isinstance(entity.get("version"), int), (
            f"version must be an integer, got {entity.get('version')!r}"
        )


def assert_allocation_row(row: Dict[str, Any]) -> None:
    """An allocation line carries id and created_at and nothing else audit-wise."""
    assert is_valid_uuid(row.get("id")), f"id must be a UUID, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"created_at must be an ISO-8601 UTC instant, got {row.get('created_at')!r}"
    )
    assert "updated_at" not in row, "an allocation line must not carry updated_at"
    assert "version" not in row, "an allocation line must not carry a revision counter"


def assert_fee_basis(
    fee_basis: Dict[str, Any],
    *,
    tier_base_cents: Optional[int] = None,
    occupancy_multiplier: Optional[float] = None,
    non_ecv_surcharge_applied: Optional[bool] = None,
    unpermitted_multiplier_applied: Optional[bool] = None,
    aggravation_cents: Optional[int] = None,
    cap_applied: Optional[bool] = None,
) -> None:
    """Check the audit breakdown recorded alongside an assessed fee."""
    assert isinstance(fee_basis, dict), f"fee_basis must be an object, got {fee_basis!r}"
    if tier_base_cents is not None:
        assert_money_cents(fee_basis.get("tier_base_cents"), tier_base_cents, "fee_basis.tier_base_cents")
    if occupancy_multiplier is not None:
        assert float(fee_basis.get("occupancy_multiplier")) == occupancy_multiplier, (
            f"fee_basis.occupancy_multiplier expected {occupancy_multiplier}, "
            f"got {fee_basis.get('occupancy_multiplier')}"
        )
    if non_ecv_surcharge_applied is not None:
        assert fee_basis.get("non_ecv_surcharge_applied") is non_ecv_surcharge_applied, (
            f"fee_basis.non_ecv_surcharge_applied expected {non_ecv_surcharge_applied}, "
            f"got {fee_basis.get('non_ecv_surcharge_applied')!r}"
        )
    if unpermitted_multiplier_applied is not None:
        assert fee_basis.get("unpermitted_multiplier_applied") is unpermitted_multiplier_applied, (
            f"fee_basis.unpermitted_multiplier_applied expected {unpermitted_multiplier_applied}, "
            f"got {fee_basis.get('unpermitted_multiplier_applied')!r}"
        )
    if aggravation_cents is not None:
        assert_money_cents(fee_basis.get("aggravation_cents"), aggravation_cents, "fee_basis.aggravation_cents")
    if cap_applied is not None:
        assert fee_basis.get("cap_applied") is cap_applied, (
            f"fee_basis.cap_applied expected {cap_applied}, got {fee_basis.get('cap_applied')!r}"
        )


def assert_invoice_totals(
    invoice: Dict[str, Any],
    *,
    subtotal_cents: Optional[int] = None,
    admin_fee_cents: Optional[int] = None,
    assessed_cents: Optional[int] = None,
    paid_cents: Optional[int] = None,
    adjusted_cents: Optional[int] = None,
    outstanding_cents: Optional[int] = None,
    payment_status: Optional[str] = None,
    collections_stage: Optional[str] = None,
) -> None:
    if subtotal_cents is not None:
        assert_money_cents(invoice.get("subtotal_cents"), subtotal_cents, "subtotal_cents")
    if admin_fee_cents is not None:
        assert_money_cents(invoice.get("admin_fee_cents"), admin_fee_cents, "admin_fee_cents")
    if assessed_cents is not None:
        assert_money_cents(invoice.get("assessed_cents"), assessed_cents, "assessed_cents")
    if paid_cents is not None:
        assert_money_cents(invoice.get("paid_cents"), paid_cents, "paid_cents")
    if adjusted_cents is not None:
        assert_money_cents(invoice.get("adjusted_cents"), adjusted_cents, "adjusted_cents")
    if outstanding_cents is not None:
        assert_money_cents(invoice.get("outstanding_cents"), outstanding_cents, "outstanding_cents")
    if payment_status is not None:
        assert invoice.get("payment_status") == payment_status, (
            f"payment_status expected {payment_status}, got {invoice.get('payment_status')!r}"
        )
    if collections_stage is not None:
        assert invoice.get("collections_stage") == collections_stage, (
            f"collections_stage expected {collections_stage}, got {invoice.get('collections_stage')!r}"
        )


def assert_outstanding_identity(invoice: Dict[str, Any]) -> None:
    """Outstanding money is what was assessed less what was paid and adjusted."""
    expected = invoice["assessed_cents"] - invoice["paid_cents"] - invoice["adjusted_cents"]
    assert invoice["outstanding_cents"] == expected, (
        "outstanding_cents must equal assessed_cents - paid_cents - adjusted_cents; "
        f"got {invoice['outstanding_cents']} instead of {expected}"
    )


def assert_cash_conservation(payment: Dict[str, Any]) -> None:
    """A tendered amount is either allocated to invoices or held as credit."""
    total = payment["allocated_cents"] + payment["credited_cents"]
    assert total == payment["amount_cents"], (
        "allocated_cents + credited_cents must equal amount_cents; "
        f"got {payment['allocated_cents']} + {payment['credited_cents']} != {payment['amount_cents']}"
    )


def assert_status(entity: Dict[str, Any], expected: str, field: str = "status") -> None:
    assert entity.get(field) == expected, (
        f"{field} expected {expected}, got {entity.get(field)!r}"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"], (
        f"version must not move: was {before['version']}, now {after['version']}"
    )


def list_ids(response: Any) -> List[str]:
    """Ids of the rows in a paginated list response, in returned order."""
    data, _meta = validate_paginated(response)
    return [row["id"] for row in data]


def total_count(response: Any) -> int:
    _data, meta = validate_paginated(response)
    return meta["total_count"]


def assert_total_count(response: Any, expected: int) -> List[Dict[str, Any]]:
    data, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"total_count expected {expected}, got {meta['total_count']}"
    )
    return data


def assert_contains_ids(response: Any, expected_ids: Iterable[str]) -> None:
    got = set(list_ids(response))
    missing = [i for i in expected_ids if i not in got]
    assert not missing, f"listing omitted expected rows {missing}"


def assert_excludes_ids(response: Any, excluded_ids: Iterable[str]) -> None:
    got = set(list_ids(response))
    present = [i for i in excluded_ids if i in got]
    assert not present, f"listing returned rows it should have filtered out {present}"


def single(response: Any, expected_status: int = 200) -> Dict[str, Any]:
    """The one row of a filtered listing that must match exactly once."""
    validate_success(response, expected_status)
    data, meta = validate_paginated(response)
    assert meta["total_count"] == 1, f"expected exactly one row, got total_count {meta['total_count']}"
    return data[0]


def data_of(response: Any, expected_status: int = 200) -> Dict[str, Any]:
    """Envelope payload of a successful single-resource response."""
    validate_success(response, expected_status)
    return get_success_data(response)

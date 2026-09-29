"""Domain assertion helpers for the OTA administration API."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import Json

MONEY_FIELDS_OFFER = (
    "gross_cents",
    "marketplace_margin_cents",
    "taxes_fees_cents",
    "display_total_cents",
    "supplier_payable_cents",
)


def assert_score(actual: Any, expected: float) -> None:
    """A 2-decimal score comparison."""
    assert actual == pytest.approx(expected, abs=0.01), (actual, expected)


def assert_pct(actual: Any, expected: float) -> None:
    """A percentage-as-decimal-fraction comparison."""
    assert actual == pytest.approx(expected, abs=0.0001), (actual, expected)


def assert_uuid(value: Any) -> None:
    assert isinstance(value, str) and is_valid_uuid(value), value


def assert_timestamp(value: Any) -> None:
    assert isinstance(value, str) and is_iso8601_timestamp(value), value


def assert_instant_equals(value: Any, expected_instant: str) -> None:
    """Compare a stamped instant to an expected UTC instant, format-tolerantly."""
    assert isinstance(value, str), value
    normalised = value.replace("Z", "+00:00")
    expected = expected_instant.replace("Z", "+00:00")
    from datetime import datetime

    assert datetime.fromisoformat(normalised) == datetime.fromisoformat(expected), (
        value,
        expected_instant,
    )


def assert_mutable_common_fields(row: Json) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    assert_uuid(row["id"])
    assert_timestamp(row["created_at"])
    assert_timestamp(row["updated_at"])
    assert isinstance(row["version"], int) and row["version"] >= 1, row.get("version")


def assert_evidence_common_fields(row: Json) -> None:
    """An append-only evidence row carries only id and created_at."""
    assert_uuid(row["id"])
    assert_timestamp(row["created_at"])
    assert "updated_at" not in row, row
    assert "version" not in row, row


def assert_offer_display_identity(offer: Json) -> None:
    """display_total = supplier_payable + marketplace_margin + taxes_fees."""
    assert offer["display_total_cents"] == (
        offer["supplier_payable_cents"]
        + offer["marketplace_margin_cents"]
        + offer["taxes_fees_cents"]
    ), {k: offer[k] for k in MONEY_FIELDS_OFFER}


def assert_offer_money(
    offer: Json,
    *,
    gross_cents: Optional[int] = None,
    marketplace_margin_cents: Optional[int] = None,
    taxes_fees_cents: Optional[int] = None,
    display_total_cents: Optional[int] = None,
    supplier_payable_cents: Optional[int] = None,
) -> None:
    expected = {
        "gross_cents": gross_cents,
        "marketplace_margin_cents": marketplace_margin_cents,
        "taxes_fees_cents": taxes_fees_cents,
        "display_total_cents": display_total_cents,
        "supplier_payable_cents": supplier_payable_cents,
    }
    for field, want in expected.items():
        if want is not None:
            assert offer[field] == want, (field, offer[field], want)
    assert_offer_display_identity(offer)


def assert_allotment_invariant(offer: Json) -> None:
    """allotment_total = allotment_remaining + allotment_held + allotment_sold."""
    assert offer["allotment_total"] == (
        offer["allotment_remaining"] + offer["allotment_held"] + offer["allotment_sold"]
    ), offer


def assert_allotment(
    offer: Json, *, remaining: int, held: int, sold: int, total: Optional[int] = None
) -> None:
    assert offer["allotment_remaining"] == remaining, offer
    assert offer["allotment_held"] == held, offer
    assert offer["allotment_sold"] == sold, offer
    if total is not None:
        assert offer["allotment_total"] == total, offer
    assert_allotment_invariant(offer)


def assert_booking_conserved(booking: Json) -> None:
    """charged_total = supplier_payable + margin + taxes + refunded."""
    assert booking["charged_total_cents"] == (
        booking["supplier_payable_cents"]
        + booking["marketplace_margin_cents"]
        + booking["taxes_fees_cents"]
        + booking["refunded_cents"]
    ), booking


def assert_booking_state(
    booking: Json, *, payment_status: str, fulfillment_status: str
) -> None:
    assert booking["payment_status"] == payment_status, booking
    assert booking["fulfillment_status"] == fulfillment_status, booking


def assert_settlement_identity(dispute: Json) -> None:
    """settlement_total = refund_due + mediation_fee, and both splits sum to it."""
    assert dispute["settlement_total_cents"] == (
        dispute["refund_due_cents"] + dispute["mediation_fee_cents"]
    ), dispute
    assert (
        dispute["preliminary_marketplace_cents"] + dispute["preliminary_supplier_cents"]
    ) == dispute["settlement_total_cents"], dispute
    if dispute.get("binding_marketplace_cents") is not None:
        assert (
            dispute["binding_marketplace_cents"] + dispute["binding_supplier_cents"]
        ) == dispute["settlement_total_cents"], dispute


def assert_discount_allocation_exact(package: Json, components: Sequence[Json]) -> None:
    """The allocated discounts sum to the package discount, and prices to the total."""
    assert sum(c["discount_alloc_cents"] for c in components) == package[
        "discount_cents"
    ], (package, list(components))
    assert sum(c["allocated_cents"] for c in components) == package[
        "package_total_cents"
    ], (package, list(components))


def assert_ordered_by(rows: Iterable[Json], field: str, descending: bool = False) -> None:
    values: List[Any] = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (field, values)


def assert_field_absent_or_none(row: Json, field: str) -> None:
    assert row.get(field) is None, (field, row.get(field))


def assert_keys_present(mapping: Dict[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        assert key in mapping, (key, mapping)

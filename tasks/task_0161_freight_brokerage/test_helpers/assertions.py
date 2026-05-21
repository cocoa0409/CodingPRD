"""Per-entity assertions and domain invariant checkers.

These are read-only structural checks: they confirm that response
shapes conform to what the PRD promises, but they do not invent rules
absent from PRD prose.

Invoice and FactoringAdvance are append-only per PRD §2.4 — they carry
`id` and `created_at` only. The assertions deliberately do NOT require
`updated_at` or `version` on those rows.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field assertion — for entities with id + created_at + updated_at +
# version (PRD §2.4).
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: append-only rows carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_brokerage(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["mc_number"], str) and len(data["mc_number"]) > 0
    assert isinstance(data["factoring_reserve_pct"], (int, float))
    assert 0 <= float(data["factoring_reserve_pct"]) <= 100
    assert isinstance(data["detention_free_minutes"], int)
    assert data["detention_free_minutes"] >= 0
    assert isinstance(data["detention_rate_cents_per_15min"], int)
    assert data["detention_rate_cents_per_15min"] >= 0
    assert is_iso8601_timestamp(data["clock_now_iso"])


def assert_shipper(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["company_name"], str)
    assert isinstance(data["smartway_required"], bool)
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_invoiced_cents"], int)
    assert data["outstanding_invoiced_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert is_valid_uuid(data["brokerage_id"])


def assert_carrier(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["mc_number"], str)
    assert isinstance(data["usdot_number"], str)
    assert is_iso8601_timestamp(data["insurance_expires_on"])
    assert isinstance(data["smartway_certified"], bool)
    assert isinstance(data["safety_score"], int)
    assert data["safety_score"] >= 0
    assert data["status"] in (
        "PENDING_QUALIFICATION", "QUALIFIED", "SUSPENDED", "REVOKED",
    )
    assert is_valid_uuid(data["brokerage_id"])


def assert_rate_contract(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["shipper_id"], str)
    assert isinstance(data["lane_origin_zip"], str)
    assert isinstance(data["lane_destination_zip"], str)
    assert data["equipment_type"] in ("DRY_VAN", "REEFER", "FLATBED")
    assert isinstance(data["flat_rate_cents"], int)
    assert data["flat_rate_cents"] >= 0
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_quote_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["shipper_id"], str)
    assert isinstance(data["origin_zip"], str)
    assert isinstance(data["destination_zip"], str)
    assert data["equipment_type"] in ("DRY_VAN", "REEFER", "FLATBED")
    assert is_iso8601_timestamp(data["pickup_window_start"])
    assert is_iso8601_timestamp(data["pickup_window_end"])
    assert data["status"] in (
        "OPEN", "QUOTED", "ACCEPTED", "REJECTED", "EXPIRED",
    )
    # rate_source and quoted_linehaul_cents are populated only at QUOTED.
    if data["status"] in ("QUOTED", "ACCEPTED", "REJECTED"):
        assert data.get("rate_source") in ("SPOT", "CONTRACT")
        assert isinstance(data.get("quoted_linehaul_cents"), int)
        assert data["quoted_linehaul_cents"] >= 0


def assert_load(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["shipper_id"], str)
    assert isinstance(data["brokerage_id"], str)
    assert isinstance(data["quote_request_id"], str)
    assert isinstance(data["carrier_id"], str)
    assert data["status"] in (
        "TENDERED", "ACCEPTED", "IN_TRANSIT", "DELIVERED", "INVOICED",
        "SETTLED", "CANCELLED",
    )
    assert isinstance(data["linehaul_cents"], int) and data["linehaul_cents"] >= 0
    assert data["rate_source"] in ("SPOT", "CONTRACT")
    assert isinstance(data["provisional_detention_cents"], int)
    assert data["provisional_detention_cents"] >= 0
    assert isinstance(data["accessorial_total_cents"], int)
    assert data["accessorial_total_cents"] >= 0


def assert_accessorial_charge(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["load_id"], str)
    assert data["charge_type"] in ("LAYOVER", "TONU", "REWEIGH", "LUMPER")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_invoice(data: Dict[str, Any]) -> None:
    """PRD §2.4 — Invoice carries id + created_at only (no version/updated_at)."""
    assert_append_only_fields(data)
    assert isinstance(data["load_id"], str)
    assert isinstance(data["shipper_id"], str)
    assert isinstance(data["linehaul_cents"], int) and data["linehaul_cents"] >= 0
    assert isinstance(data["detention_cents"], int) and data["detention_cents"] >= 0
    assert isinstance(data["accessorial_cents"], int)
    assert data["accessorial_cents"] >= 0
    assert isinstance(data["invoice_total_cents"], int)
    assert data["invoice_total_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int)
    assert data["amount_paid_cents"] >= 0
    assert isinstance(data["amount_credited_cents"], int)
    assert data["amount_credited_cents"] >= 0
    assert isinstance(data["balance_due_cents"], int)
    assert data["balance_due_cents"] >= 0
    assert data["factoring_status"] in (
        "NOT_FACTORED", "FACTORED", "RECOURSED",
    )
    assert data["settlement_status"] in (
        "ISSUED", "PAID", "WRITTEN_OFF",
    )


def assert_factoring_advance(data: Dict[str, Any]) -> None:
    """PRD §2.4 — FactoringAdvance carries id + created_at only."""
    assert_append_only_fields(data)
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["invoice_total_at_advance_cents"], int)
    assert data["invoice_total_at_advance_cents"] >= 0
    assert isinstance(data["haircut_cents"], int) and data["haircut_cents"] >= 0
    assert isinstance(data["reserve_cents"], int) and data["reserve_cents"] >= 0
    assert isinstance(data["advanced_cents"], int) and data["advanced_cents"] >= 0
    assert isinstance(data["recourse_owed_cents"], int)
    assert data["recourse_owed_cents"] >= 0


def assert_dispute_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["invoice_id"], str)
    assert data["claim_type"] in (
        "DAMAGE", "SHORTAGE", "OVERCHARGE", "LATE_DELIVERY",
    )
    assert isinstance(data["claimed_cents"], int)
    assert data["claimed_cents"] > 0
    assert data["status"] in (
        "OPEN", "IN_REVIEW", "COUNTER_OFFERED",
        "RESOLVED", "ESCALATED", "WITHDRAWN",
    )


# ---------------------------------------------------------------------------
# Invariant checkers — PRD §3.7 / §3.9
# ---------------------------------------------------------------------------
def assert_invoice_balance_conservation(invoice: Dict[str, Any],
                                        original_total_cents: int) -> None:
    """PRD §3.9: "the pre-resolution `invoice_total_cents` equals the
    post-resolution `invoice_total_cents` plus the delta added to
    `amount_credited_cents`."

    Starting from issuance, where amount_credited_cents == 0 and
    invoice_total_cents == original frozen face value, the cumulative form
    of the invariant is:

        invoice_total_cents (current) + amount_credited_cents (cumulative)
        == original frozen invoice_total_cents

    every credit delta moves the same number of cents from invoice_total
    into amount_credited, so their sum is constant.
    """
    conserved = (
        invoice["invoice_total_cents"]
        + invoice["amount_credited_cents"]
    )
    assert conserved == original_total_cents, (
        f"invoice_total ({invoice['invoice_total_cents']}) "
        f"+ credited ({invoice['amount_credited_cents']}) "
        f"== {conserved}, expected original total {original_total_cents}"
    )


def assert_status(entity: Dict[str, Any], expected: str,
                  label: str = "entity") -> None:
    actual = entity.get("status")
    assert actual == expected, (
        f"Expected {label} status == {expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(new_entity: Dict[str, Any],
                                  old_version: int, delta: int = 1) -> None:
    """PRD §2.4: version increments by exactly 1 on every server-side
    mutation. Cascades that touch the same row each tick the counter."""
    assert new_entity["version"] == old_version + delta, (
        f"Expected version {old_version + delta}, "
        f"got {new_entity['version']} (old was {old_version})"
    )


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_brokerage",
    "assert_shipper",
    "assert_carrier",
    "assert_rate_contract",
    "assert_quote_request",
    "assert_load",
    "assert_accessorial_charge",
    "assert_invoice",
    "assert_factoring_advance",
    "assert_dispute_claim",
    "assert_invoice_balance_conservation",
    "assert_status",
    "assert_version_incremented_by",
]

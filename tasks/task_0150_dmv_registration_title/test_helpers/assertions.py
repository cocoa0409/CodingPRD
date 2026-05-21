"""Entity assertions and domain invariant checkers.

These check response shape and domain invariants required by the PRD
contract.

PRD §2.4 — entities split into two shapes:

    common-fields (Owner, Vehicle, LienRecord, EmissionsInspection,
    RealIDApplication, Plate, TransferApplication):
        id, created_at, updated_at, version

    lean (Title, FeeLedgerEntry):
        Title carries id and issued_at only;
        FeeLedgerEntry carries id and occurred_at only.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )


def _assert_created_at(data: Dict[str, Any]) -> None:
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'version field is an integer that starts at 1 on creation
    and increments by 1 on every mutation.'"""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 common-fields entities."""
    _assert_id(data)
    _assert_created_at(data)
    _assert_updated_at_and_version(data)


def assert_version_incremented_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1,
) -> None:
    """PRD §2.4: 'The version field is an integer that starts at 1 on
    creation and increments by 1 on every mutation.'"""
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']}+{delta} = "
        f"{before['version'] + delta}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_owner(data: Dict[str, Any]) -> None:
    """PRD §3.1 Owner fields."""
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 100
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) == 10
    assert isinstance(data["residency_state"], str) and len(data["residency_state"]) == 2
    assert data["real_id_status"] in (
        "NOT_APPLIED", "PENDING", "APPROVED", "REVOKED",
    )
    assert isinstance(data["is_resident"], bool)
    assert isinstance(data["outstanding_holds_count"], int)
    assert data["outstanding_holds_count"] >= 0
    # real_id_score and real_id_expires_at may be null per PRD §3.1
    assert "real_id_score" in data
    assert "real_id_expires_at" in data


def assert_vehicle(data: Dict[str, Any]) -> None:
    """PRD §3.2 Vehicle fields."""
    assert_common_fields(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert isinstance(data["make"], str) and 1 <= len(data["make"]) <= 50
    assert isinstance(data["model"], str) and 1 <= len(data["model"]) <= 50
    assert isinstance(data["model_year"], int)
    assert 1900 <= data["model_year"] <= 2100
    assert isinstance(data["curb_weight_lbs"], int)
    assert 200 <= data["curb_weight_lbs"] <= 40000
    assert data["fuel_type"] in ("GASOLINE", "DIESEL", "HYBRID", "ELECTRIC")
    assert data["vin_verification_status"] in (
        "UNVERIFIED", "VERIFIED", "MISMATCH", "HOLD",
    )
    assert data["title_status"] in (
        "CLEAN", "SALVAGE_PENDING_REBUILD", "REBUILT", "NON_REPAIRABLE",
    )
    assert data["lien_status"] in ("NONE", "ACTIVE", "RELEASED")
    assert "current_title_id" in data
    assert "emissions_expires_at" in data
    assert "vin_verified_at" in data


def assert_title(data: Dict[str, Any]) -> None:
    """PRD §2.4 lean entity — id + issued_at only. PRD §3.8 brand/owner."""
    _assert_id(data)
    assert "issued_at" in data, "missing issued_at"
    assert is_iso8601_timestamp(data["issued_at"])
    # PRD §2.4: 'Title rows carry only id and issued_at — they have no
    # updated_at and no version'
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "Title must not expose updated_at per PRD §2.4"
    )
    assert "version" not in data or data.get("version") is None, (
        "Title must not expose version per PRD §2.4"
    )
    # PRD §3.8 fields
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["owner_id"], str)
    assert data["brand"] in ("CLEAN", "SALVAGE", "REBUILT", "FLOOD", "LEMON")
    assert isinstance(data["is_active"], bool)
    assert "superseded_at" in data
    assert "source_application_id" in data


def assert_lien_record(data: Dict[str, Any]) -> None:
    """PRD §3.6 LienRecord fields."""
    assert_common_fields(data)
    assert isinstance(data["title_id"], str)
    assert isinstance(data["lienholder_name"], str)
    assert 1 <= len(data["lienholder_name"]) <= 120
    assert isinstance(data["principal_amount"], (int, float))
    assert 0.01 <= float(data["principal_amount"]) <= 2000000.00
    assert data["status"] in ("ACTIVE", "RELEASED")
    assert "released_at" in data
    assert "release_reference" in data


def assert_emissions_inspection(data: Dict[str, Any]) -> None:
    """PRD §3.5 EmissionsInspection fields."""
    assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["station_id"], str)
    assert 1 <= len(data["station_id"]) <= 40
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED", "CANCELLED",
    )
    assert "result_recorded_at" in data
    assert "odometer_reading" in data


def assert_real_id_application(data: Dict[str, Any]) -> None:
    """PRD §3.10 RealIDApplication fields."""
    assert_common_fields(data)
    assert isinstance(data["owner_id"], str)
    assert data["status"] in (
        "SUBMITTED", "DOC_REVIEW", "APPROVED", "DOC_REJECTED", "REVOKED",
    )
    assert isinstance(data["documents_proof_of_identity"], bool)
    assert isinstance(data["documents_proof_of_residency"], bool)
    assert isinstance(data["documents_proof_of_ssn"], bool)
    assert isinstance(data["revision_count"], int)
    assert data["revision_count"] >= 0
    assert "approved_at" in data


def assert_plate(data: Dict[str, Any]) -> None:
    """PRD §3.8, §3.9 Plate fields."""
    assert_common_fields(data)
    assert isinstance(data["plate_number"], str)
    assert 2 <= len(data["plate_number"]) <= 8
    assert isinstance(data["vehicle_id"], str)
    assert data["status"] in ("ISSUED", "ACTIVE", "SUSPENDED", "SURRENDERED")
    assert "activated_at" in data
    assert "suspended_at" in data
    assert "surrender_reason" in data


def assert_transfer_application(data: Dict[str, Any]) -> None:
    """PRD §3.4 TransferApplication fields."""
    assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["applicant_owner_id"], str)
    assert data["application_type"] in (
        "INITIAL_REGISTRATION", "TITLE_TRANSFER",
    )
    assert data["status"] in (
        "DRAFT", "VIN_VERIFIED", "SALVAGE_REVIEW", "SALVAGE_APPROVED",
        "EMISSIONS_PENDING", "EMISSIONS_PASSED", "TAX_ASSESSED",
        "PLATE_ISSUED", "COMPLETED", "REJECTED",
    )
    assert isinstance(data["salvage_branch_taken"], bool)
    assert isinstance(data["trade_in_value"], (int, float))
    assert isinstance(data["declared_sale_price"], (int, float))
    assert "fee_subtotal" in data
    assert "processing_fee" in data
    assert "total_due" in data
    assert "paid_at" in data
    assert "plate_id" in data
    assert "rejection_reason" in data


def assert_fee_ledger_entry(data: Dict[str, Any]) -> None:
    """PRD §2.4 lean entity — id + occurred_at only.

    PRD §2.4: 'FeeLedgerEntry rows carry only id and occurred_at; they
    are append-only, never edited, and have no updated_at and no version.'
    """
    _assert_id(data)
    assert "occurred_at" in data, "missing occurred_at"
    assert is_iso8601_timestamp(data["occurred_at"])
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "FeeLedgerEntry must not expose updated_at per PRD §2.4"
    )
    assert "version" not in data or data.get("version") is None, (
        "FeeLedgerEntry must not expose version per PRD §2.4"
    )
    assert isinstance(data["application_id"], str)
    assert data["kind"] in (
        "SALES_TAX", "REG_FEE", "PROCESSING_FEE",
        "REFUND_TAX", "REFUND_REG", "REFUND_PROCESSING",
    )
    assert isinstance(data["amount_cents"], int)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_money_precision(value: Any, *, name: str = "value") -> None:
    """PRD §2.6: 'All monetary amounts ... are stored and serialized as
    decimals with exactly two fractional digits.'"""
    if value is None:
        return
    rendered = f"{float(value):.2f}"
    assert abs(float(value) - float(rendered)) < 1e-9, (
        f"{name}={value!r} not rounded to 2 decimal places"
    )


def assert_ledger_sum_zero(entries: Iterable[Dict[str, Any]]) -> None:
    """PRD §2.6: 'The compensating-action invariant for any single
    TransferApplication is that the sum of all amount_cents values
    across its ledger is exactly zero once a refund cycle completes.'"""
    total = sum(int(e["amount_cents"]) for e in entries)
    assert total == 0, (
        f"compensating-action invariant violated: net cents = {total}, "
        f"expected 0"
    )


def assert_ledger_sum_equals(entries: Iterable[Dict[str, Any]],
                             expected_cents: int) -> None:
    total = sum(int(e["amount_cents"]) for e in entries)
    assert total == expected_cents, (
        f"ledger sum {total} != expected {expected_cents}"
    )


def assert_fee_ledger_has_kinds(entries: List[Dict[str, Any]],
                                expected_kinds: Iterable[str]) -> None:
    """PRD §3.7: 'three FeeLedgerEntry rows whose kind values are
    SALES_TAX, REG_FEE, and PROCESSING_FEE.'"""
    got_kinds = sorted(e["kind"] for e in entries)
    exp = sorted(expected_kinds)
    assert got_kinds == exp, f"ledger kinds {got_kinds} != expected {exp}"


__all__ = [
    "assert_common_fields",
    "assert_version_incremented_by",
    "assert_owner",
    "assert_vehicle",
    "assert_title",
    "assert_lien_record",
    "assert_emissions_inspection",
    "assert_real_id_application",
    "assert_plate",
    "assert_transfer_application",
    "assert_fee_ledger_entry",
    "assert_money_precision",
    "assert_ledger_sum_zero",
    "assert_ledger_sum_equals",
    "assert_fee_ledger_has_kinds",
]

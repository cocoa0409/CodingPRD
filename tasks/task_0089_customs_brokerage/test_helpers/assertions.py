"""Entity assertions and domain invariant checkers.

Per PRD §2.4: ClientCompany, CommissionAgreement, Declaration,
ShipmentDocument, Filing, InspectionCase, Settlement carry
id/created_at/updated_at/version. RejectionRecord, AuditLog,
ExternalEvent carry only id + created_at (no updated_at, no version).
"""
from __future__ import annotations

from typing import Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field assertion helpers
# ---------------------------------------------------------------------------
def _assert_mutable_common(data: dict, entity_label: str) -> None:
    """Assert id/created_at/updated_at/version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_label}.version must be integer, got {type(data.get('version'))}"
    )
    assert data["version"] >= 1, (
        f"{entity_label}.version must start at 1, got {data['version']}"
    )


def _assert_append_only_common(data: dict, entity_label: str) -> None:
    """Assert id + created_at present, and updated_at/version absent
    (or null) per PRD §2.4 minimal-record contract."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    # PRD §2.4: "Two resources are minimal records that omit updated_at and
    # version entirely: RejectionRecord and AuditLog."
    assert "updated_at" not in data or data.get("updated_at") is None, (
        f"{entity_label} must NOT carry updated_at (PRD §2.4)"
    )
    assert "version" not in data or data.get("version") is None, (
        f"{entity_label} must NOT carry version (PRD §2.4)"
    )


# ---------------------------------------------------------------------------
# ClientCompany
# ---------------------------------------------------------------------------
def assert_client_company(data: dict) -> None:
    _assert_mutable_common(data, "ClientCompany")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 200
    assert isinstance(data["tax_id"], str) and 1 <= len(data["tax_id"]) <= 40
    assert isinstance(data["country_code"], str)
    assert len(data["country_code"]) == 2 and data["country_code"].isupper()
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["default_settlement_currency"] in ("USD", "EUR", "CNY", "JPY", "GBP")
    assert data["status"] in ("ACTIVE", "ARCHIVED")


# ---------------------------------------------------------------------------
# CommissionAgreement
# ---------------------------------------------------------------------------
def assert_commission_agreement(data: dict) -> None:
    _assert_mutable_common(data, "CommissionAgreement")
    assert isinstance(data["client_id"], str) and data["client_id"]
    assert isinstance(data["scope_of_service"], list) and data["scope_of_service"]
    for s in data["scope_of_service"]:
        assert s in ("DECLARATION", "INSPECTION", "TARIFF_ADVANCE",
                     "RETURN_SHIP", "AMENDMENT"), (
            f"Invalid scope_of_service entry: {s!r}"
        )
    assert isinstance(data["fee_schedule"], dict)
    for k, v in data["fee_schedule"].items():
        assert isinstance(v, (int, float)) and v >= 0, (
            f"fee_schedule[{k!r}]={v!r} must be non-negative number"
        )
    assert data["agreement_currency"] in ("USD", "EUR", "CNY", "JPY", "GBP")
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_until"])
    assert isinstance(data["late_interest_daily_rate_bps"], int)
    assert 0 <= data["late_interest_daily_rate_bps"] <= 1000
    assert data["status"] in (
        "DRAFT", "AWAITING_SIGNATURE", "ACTIVE",
        "TERMINATED", "EXPIRED", "RENEWED",
    )


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------
def assert_declaration(data: dict) -> None:
    _assert_mutable_common(data, "Declaration")
    assert isinstance(data["agreement_id"], str)
    assert data["jurisdiction_code"] in ("CN", "US", "EU", "JP", "GB")
    assert isinstance(data["shipment_reference"], str)
    assert 1 <= len(data["shipment_reference"]) <= 60
    assert isinstance(data["hs_code"], str)
    assert data["hs_code"].isdigit() and len(data["hs_code"]) in (6, 8, 10)
    assert isinstance(data["country_of_origin"], str)
    assert len(data["country_of_origin"]) == 2
    assert data["trade_agreement_code"] in (
        "NONE", "RCEP", "USMCA", "EU_GSP", "CPTPP",
    )
    assert isinstance(data["declared_value_amount"], (int, float))
    assert data["declared_value_amount"] >= 0
    assert data["declared_currency"] in ("USD", "EUR", "CNY", "JPY", "GBP")
    assert data["declared_value_review_status"] in (
        "PENDING", "ACCEPTED", "FLAGGED",
    )
    assert data["status"] in (
        "DRAFT", "DOCS_PENDING", "PRE_VALIDATED", "FILED",
        "QUERIED", "INSPECTING", "RELEASED", "REJECTED",
        "WITHDRAWN", "AMENDING",
    )
    assert isinstance(data["amendment_count"], int)
    assert data["amendment_count"] >= 0


# ---------------------------------------------------------------------------
# ShipmentDocument
# ---------------------------------------------------------------------------
def assert_shipment_document(data: dict) -> None:
    _assert_mutable_common(data, "ShipmentDocument")
    assert isinstance(data["declaration_id"], str)
    assert data["doc_type"] in (
        "COMMERCIAL_INVOICE", "PACKING_LIST", "BILL_OF_LADING",
        "CONTRACT", "IMPORT_LICENSE", "INSPECTION_CERT",
        "DANGEROUS_GOODS_DECL",
    )
    assert isinstance(data["storage_uri"], str)
    assert 1 <= len(data["storage_uri"]) <= 500
    assert data["authenticity_status"] in ("UNSCREENED", "ACCEPTED", "FLAGGED")
    score = data.get("authenticity_score")
    if score is not None:
        assert isinstance(score, (int, float)) and 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Filing
# ---------------------------------------------------------------------------
def assert_filing(data: dict) -> None:
    _assert_mutable_common(data, "Filing")
    assert isinstance(data["declaration_id"], str)
    assert isinstance(data["single_window_ref"], str) and data["single_window_ref"]
    assert is_iso8601_timestamp(data["submitted_at"])
    assert data["response_type"] in (
        "AWAITING", "RELEASE", "QUERY", "INSPECT", "REJECT",
    )
    assert data["manifest_match_status"] in (
        "UNMATCHED", "MATCHED", "MISMATCHED",
    )
    assert isinstance(data["is_amendment"], bool)


# ---------------------------------------------------------------------------
# InspectionCase
# ---------------------------------------------------------------------------
def assert_inspection_case(data: dict) -> None:
    _assert_mutable_common(data, "InspectionCase")
    assert isinstance(data["filing_id"], str)
    assert isinstance(data["warehouse_code"], str)
    assert 1 <= len(data["warehouse_code"]) <= 40
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert isinstance(data["sample_required"], bool)
    assert data["outcome"] in ("PENDING", "RELEASE", "DETENTION", "PENALTY")
    p = data.get("penalty_amount", 0)
    assert isinstance(p, (int, float)) and p >= 0


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
def assert_settlement(data: dict) -> None:
    _assert_mutable_common(data, "Settlement")
    assert isinstance(data["declaration_id"], str)
    assert data["settlement_currency"] in ("USD", "EUR", "CNY", "JPY", "GBP")
    assert data["status"] in (
        "PROVISIONAL", "FINAL", "ADVANCED", "REIMBURSED", "VOIDED",
    )
    for f in ("tariff_amount", "vat_amount", "consumption_tax_amount",
              "penalty_amount", "broker_fee_amount", "advance_paid_amount",
              "late_interest_amount"):
        v = data.get(f)
        if v is not None:
            assert isinstance(v, (int, float)), (
                f"Settlement.{f} must be number, got {v!r}"
            )
            assert v >= 0, f"Settlement.{f} must be >=0, got {v}"
            # PRD §2.7: monetary fields are stored to two decimal places.
            rounded = round(float(v), 2)
            assert abs(rounded - float(v)) < 1e-9, (
                f"Settlement.{f}={v} must be 2dp precision"
            )


# ---------------------------------------------------------------------------
# RejectionRecord (append-only)
# ---------------------------------------------------------------------------
def assert_rejection_record(data: dict) -> None:
    _assert_append_only_common(data, "RejectionRecord")
    assert isinstance(data["declaration_id"], str)
    assert data["rejection_reason_code"] in (
        "HS_MISMATCH", "VALUE_UNDERSTATED", "MISSING_LICENSE",
        "INSPECTION_FAILED", "MANIFEST_MISMATCH", "OTHER",
    )
    assert is_iso8601_timestamp(data["archived_at"])
    assert isinstance(data["prior_amendment_count"], int)
    note = data.get("free_text_note")
    if note is not None:
        assert isinstance(note, str) and len(note) <= 500


# ---------------------------------------------------------------------------
# AuditLog (append-only)
# ---------------------------------------------------------------------------
def assert_audit_log(data: dict) -> None:
    _assert_append_only_common(data, "AuditLog")
    assert data["entity_type"] in (
        "DECLARATION", "SETTLEMENT", "FILING", "INSPECTION_CASE", "AGREEMENT",
    )
    assert isinstance(data["entity_id"], str)
    assert data["event_type"] in (
        "STATE_TRANSITION", "FIELD_CHANGE", "ADVANCE_PAID",
        "REIMBURSED", "AMENDMENT_FILED", "VOUCHER_DELIVERED",
    )
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def assert_version_increases(new_data: dict, old_data: dict) -> None:
    """OCC version monotonicity across one mutation (PRD §2.5)."""
    assert new_data["version"] > old_data["version"], (
        f"Version did not increase: {old_data['version']} → {new_data['version']}"
    )


def assert_updated_at_advanced(new_data: dict, old_data: dict) -> None:
    assert new_data["updated_at"] >= old_data["updated_at"], (
        f"updated_at did not refresh: {old_data['updated_at']} → "
        f"{new_data['updated_at']}"
    )


def assert_money_2dp(value: float, label: str = "value") -> None:
    """PRD §2.7: monetary fields are stored to two decimal places."""
    rounded = round(float(value), 2)
    assert abs(rounded - float(value)) < 1e-9, (
        f"{label}={value} must be 2dp precision"
    )


def select_rows(rows: Iterable[dict], **filters) -> list:
    out = []
    for r in rows:
        if all(r.get(k) == v for k, v in filters.items()):
            out.append(r)
    return out


def find_row(rows: Iterable[dict], **filters) -> Optional[dict]:
    matches = select_rows(rows, **filters)
    return matches[0] if matches else None


__all__ = [
    "assert_client_company",
    "assert_commission_agreement",
    "assert_declaration",
    "assert_shipment_document",
    "assert_filing",
    "assert_inspection_case",
    "assert_settlement",
    "assert_rejection_record",
    "assert_audit_log",
    "assert_version_increases",
    "assert_updated_at_advanced",
    "assert_money_2dp",
    "select_rows",
    "find_row",
]

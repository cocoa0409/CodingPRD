"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) checks the field set, types, and enum
membership the implementation MUST return per PRD §2.4 and §3.

Domain invariants:
  assert_emd_conservation       PRD §2.13: amount == forfeited + refunded
  assert_section_1031_invariant PRD §2.13: recognized + deferred == realized
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    AUDIT_SUBJECT_KINDS,
    BENEFICIARY_KINDS,
    CD_STATUSES,
    CD_TRIGGERING_CHANGE_KINDS,
    DISBURSEMENT_STATUSES,
    EMD_STATUSES,
    EMD_RELEASED_STATUSES,
    ESCROW_FILE_STATUSES,
    EXCHANGE_STATUSES,
    PARTY_KINDS,
    POLICY_KINDS,
    TITLE_POLICY_STATUSES,
    TITLE_SEARCH_STATUSES,
    WIRE_STATUSES,
)


def _has_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: id (UUID), created_at, updated_at (ISO 8601), version
    (int starting at 1)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID: {data.get('id')}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data.get('updated_at')}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int: {data.get('version')}"
    )


def _has_immutable_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: CCRDisclosure and AuditEvent carry only id and
    created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID: {data.get('id')}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_party(data: Dict[str, Any]) -> None:
    """PRD §3.1: full_name, party_kind, contact_email."""
    _has_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("party_kind") in PARTY_KINDS, (
        f"party_kind must be one of {PARTY_KINDS}: {data.get('party_kind')}"
    )
    assert isinstance(data.get("contact_email"), str)


def assert_property(data: Dict[str, Any]) -> None:
    """PRD §3.1: street_address, parcel_id, hoa_annual_dues,
    tax_annual."""
    _has_common_fields(data)
    assert isinstance(data.get("street_address"), str)
    assert isinstance(data.get("parcel_id"), str)
    assert isinstance(data.get("hoa_annual_dues"), (int, float))
    assert isinstance(data.get("tax_annual"), (int, float))


def assert_escrow_file(data: Dict[str, Any]) -> None:
    """PRD §3.2, §3.9: status closed set; FKs present."""
    _has_common_fields(data)
    assert data.get("status") in ESCROW_FILE_STATUSES, (
        f"status must be one of {ESCROW_FILE_STATUSES}: {data.get('status')}"
    )
    assert isinstance(data.get("property_id"), str)
    assert isinstance(data.get("buyer_party_id"), str)
    assert isinstance(data.get("seller_party_id"), str)
    assert isinstance(data.get("purchase_price"), (int, float))
    assert isinstance(data.get("closing_date_planned"), str)
    assert isinstance(data.get("is_1031_exchange"), bool)


def assert_emd(data: Dict[str, Any]) -> None:
    """PRD §3.2: amount, status, computed forfeited/refunded amounts."""
    _has_common_fields(data)
    assert data.get("status") in EMD_STATUSES, (
        f"status must be one of {EMD_STATUSES}: {data.get('status')}"
    )
    assert isinstance(data.get("amount"), (int, float))
    assert isinstance(data.get("forfeited_amount"), (int, float))
    assert isinstance(data.get("refunded_amount"), (int, float))
    assert_cost_precision(data["amount"])
    assert_cost_precision(data["forfeited_amount"])
    assert_cost_precision(data["refunded_amount"])


def assert_emd_conservation(data: Dict[str, Any]) -> None:
    """PRD §2.13: 'for any EarnestMoneyDeposit that has left
    PENDING_FUNDS or HELD, the sum of forfeited_amount and
    refunded_amount always equals the row's amount'."""
    if data.get("status") in EMD_RELEASED_STATUSES:
        total = round(
            data["forfeited_amount"] + data["refunded_amount"], 2,
        )
        assert abs(total - data["amount"]) < 1e-9, (
            f"EMD conservation violated: "
            f"forfeited={data['forfeited_amount']} + "
            f"refunded={data['refunded_amount']} != "
            f"amount={data['amount']} (status={data['status']})"
        )


def assert_title_search(data: Dict[str, Any]) -> None:
    _has_common_fields(data)
    assert data.get("status") in TITLE_SEARCH_STATUSES, (
        f"status must be one of {TITLE_SEARCH_STATUSES}: "
        f"{data.get('status')}"
    )
    assert isinstance(data.get("escrow_file_id"), str)


def assert_title_policy(data: Dict[str, Any]) -> None:
    """PRD §3.3: policy_kind ∈ {OWNERS, LENDERS}; status closed set;
    premium frozen at quote time."""
    _has_common_fields(data)
    assert data.get("status") in TITLE_POLICY_STATUSES, (
        f"status must be one of {TITLE_POLICY_STATUSES}: "
        f"{data.get('status')}"
    )
    assert data.get("policy_kind") in POLICY_KINDS, (
        f"policy_kind must be one of {POLICY_KINDS}: "
        f"{data.get('policy_kind')}"
    )
    assert isinstance(data.get("insured_amount"), (int, float))
    assert isinstance(data.get("premium"), (int, float))
    assert_cost_precision(data["premium"])


def assert_ccr_disclosure(data: Dict[str, Any]) -> None:
    """PRD §2.4 + §3.4: CCRDisclosure is immutable — no updated_at, no
    version. The buyer_acknowledged_at is server-stamped."""
    _has_immutable_fields(data)
    assert isinstance(data.get("escrow_file_id"), str)
    assert isinstance(data.get("ccr_document_hash"), str)
    assert isinstance(data.get("buyer_acknowledged_at"), str)
    assert is_iso8601_timestamp(data["buyer_acknowledged_at"])
    assert isinstance(data.get("material_restrictions"), list)
    # PRD §2.4: immutable resources do NOT carry updated_at / version.
    assert "updated_at" not in data, (
        "CCRDisclosure must NOT expose updated_at (PRD §2.4)"
    )
    assert "version" not in data, (
        "CCRDisclosure must NOT expose version (PRD §2.4)"
    )


def assert_closing_disclosure(data: Dict[str, Any]) -> None:
    """PRD §3.5: status closed set; version_number monotone; cash_to_close
    computed; triggering_change_kind closed set."""
    _has_common_fields(data)
    assert data.get("status") in CD_STATUSES, (
        f"status must be one of {CD_STATUSES}: {data.get('status')}"
    )
    assert isinstance(data.get("version_number"), int)
    assert data["version_number"] >= 1
    assert isinstance(data.get("cash_to_close"), (int, float))
    assert_cost_precision(data["cash_to_close"])
    assert isinstance(data.get("prorated_tax_credit"), (int, float))
    assert isinstance(data.get("prorated_hoa_credit"), (int, float))
    assert_cost_precision(data["prorated_tax_credit"])
    assert_cost_precision(data["prorated_hoa_credit"])
    if data.get("triggering_change_kind") is not None:
        assert data["triggering_change_kind"] in CD_TRIGGERING_CHANGE_KINDS


def assert_wire_instruction(data: Dict[str, Any]) -> None:
    _has_common_fields(data)
    assert data.get("status") in WIRE_STATUSES, (
        f"status must be one of {WIRE_STATUSES}: {data.get('status')}"
    )
    assert data.get("beneficiary_kind") in BENEFICIARY_KINDS, (
        f"beneficiary_kind must be one of {BENEFICIARY_KINDS}: "
        f"{data.get('beneficiary_kind')}"
    )


def assert_disbursement(data: Dict[str, Any]) -> None:
    _has_common_fields(data)
    assert data.get("status") in DISBURSEMENT_STATUSES, (
        f"status must be one of {DISBURSEMENT_STATUSES}: "
        f"{data.get('status')}"
    )
    assert isinstance(data.get("amount"), (int, float))
    assert_cost_precision(data["amount"])


def assert_exchange_1031(data: Dict[str, Any]) -> None:
    """PRD §3.8: status closed set; realized/recognized/deferred gain
    computed."""
    _has_common_fields(data)
    assert data.get("status") in EXCHANGE_STATUSES, (
        f"status must be one of {EXCHANGE_STATUSES}: {data.get('status')}"
    )
    assert isinstance(data.get("realized_gain"), (int, float))
    assert isinstance(data.get("recognized_gain"), (int, float))
    assert isinstance(data.get("deferred_gain"), (int, float))
    assert_cost_precision(data["realized_gain"])
    assert_cost_precision(data["recognized_gain"])
    assert_cost_precision(data["deferred_gain"])
    assert isinstance(data.get("identification_deadline_at"), str)
    assert isinstance(data.get("exchange_deadline_at"), str)
    assert is_iso8601_timestamp(data["identification_deadline_at"])
    assert is_iso8601_timestamp(data["exchange_deadline_at"])


def assert_section_1031_invariant(data: Dict[str, Any]) -> None:
    """PRD §2.13: 'for any Exchange1031, the sum of recognized_gain and
    deferred_gain always equals realized_gain'."""
    total = round(data["recognized_gain"] + data["deferred_gain"], 2)
    assert abs(total - data["realized_gain"]) < 1e-9, (
        f"§1031 gain invariant violated: "
        f"recognized={data['recognized_gain']} + "
        f"deferred={data['deferred_gain']} != "
        f"realized={data['realized_gain']}"
    )


def assert_audit_event(data: Dict[str, Any]) -> None:
    """PRD §2.4 + §2.14: AuditEvent is append-only — only id and
    created_at as common fields. Records subject_kind, subject_id,
    actor_user_id, actor_role, action, payload_hash."""
    _has_immutable_fields(data)
    assert data.get("subject_kind") in AUDIT_SUBJECT_KINDS, (
        f"subject_kind must be one of {AUDIT_SUBJECT_KINDS}: "
        f"{data.get('subject_kind')}"
    )
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("actor_user_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("action"), str)
    assert isinstance(data.get("payload_hash"), str)
    # PRD §2.4: AuditEvent does NOT expose updated_at / version.
    assert "updated_at" not in data, (
        "AuditEvent must NOT expose updated_at (PRD §2.4)"
    )
    assert "version" not in data, (
        "AuditEvent must NOT expose version (PRD §2.4)"
    )


def assert_version_incremented_by_one(
    before: Dict[str, Any], after: Dict[str, Any],
) -> None:
    """PRD §2.4: version 'increments by exactly one on every successful
    mutation'."""
    assert after["version"] == before["version"] + 1, (
        f"version must increment by exactly one: "
        f"before={before['version']}, after={after['version']}"
    )


def assert_error_envelope(body: Dict[str, Any]) -> None:
    """PRD §2.2: error envelope has meta + response_type='error' + data
    with error_id and message."""
    assert body.get("response_type") == "error"
    data = body.get("data", {})
    assert isinstance(data.get("error_id"), str)
    assert isinstance(data.get("message"), str)
    assert len(data["message"].strip()) > 0


__all__ = [
    "assert_party",
    "assert_property",
    "assert_escrow_file",
    "assert_emd",
    "assert_emd_conservation",
    "assert_title_search",
    "assert_title_policy",
    "assert_ccr_disclosure",
    "assert_closing_disclosure",
    "assert_wire_instruction",
    "assert_disbursement",
    "assert_exchange_1031",
    "assert_section_1031_invariant",
    "assert_audit_event",
    "assert_version_incremented_by_one",
    "assert_error_envelope",
]

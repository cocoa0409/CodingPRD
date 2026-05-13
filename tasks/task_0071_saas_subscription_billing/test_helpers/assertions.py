"""Per-entity assertions and domain invariant checkers.

PRD §2.4 splits entities into two field-shapes:

- Versioned (id + created_at + updated_at + version):
  Tenant, Subscription, Invoice.

- Append-only / immutable-config (id + created_at only):
  PackageVersion, SubscriptionChange, UsageRecord, Payment, CreditNote,
  Jurisdiction, SyncEvent, AuditLog.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shared shape checkers (PRD §2.4)
# ---------------------------------------------------------------------------
def _check_versioned_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4: 'Resources that represent ongoing state — Tenant,
    Subscription, Invoice — additionally expose an updated_at timestamp...
    and a monotonically increasing integer version (initialized at 1 on
    creation, incremented by exactly 1 on every mutation).'"""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" in data and is_iso8601_timestamp(
        data["updated_at"]
    ), f"{entity}.updated_at must be ISO 8601 UTC"
    assert "version" in data, f"{entity} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4: 'Resources that are immutable by construction... carry
    only id and created_at; both updated_at and version are absent on
    these entities.'"""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"


# ---------------------------------------------------------------------------
# Allowed enum sets (PRD §3.x)
# ---------------------------------------------------------------------------
TENANT_STATUS_SET = {"TRIAL", "ACTIVE", "SUSPENDED", "TERMINATED"}
RESTRICTION_LEVELS = {"NONE", "READ_ONLY", "FEATURE_RESTRICTED"}
BILLING_ENTITY_TYPES = {"INDEPENDENT", "PARENT", "SUBSIDIARY"}

PACKAGE_TYPES = {"TIERED", "USAGE_BASED", "HYBRID"}
BILLING_CYCLES = {"MONTHLY", "QUARTERLY", "ANNUAL"}
PRICING_MODELS = {"PREPAID", "POSTPAID"}

SUBSCRIPTION_STATES = {
    "PENDING", "TRIAL", "ACTIVE", "PENDING_DOWNGRADE", "CANCELLED",
}
PAYMENT_STATES = {
    "CURRENT", "DUE",
    "OVERDUE_TIER1", "OVERDUE_TIER2", "OVERDUE_TIER3",
}

SUBSCRIPTION_CHANGE_TYPES = {
    "UPGRADE", "DOWNGRADE_IMMEDIATE_REFUND", "DOWNGRADE_END_OF_CYCLE",
    "TRIAL_CONVERSION", "ADDON_ADD", "ADDON_REMOVE", "CANCEL",
}

USAGE_METRICS = {"API_CALL", "STORAGE_GB", "BANDWIDTH_GB", "ACTIVE_USER"}
INGESTION_MODES = {"REALTIME", "BATCH"}

INVOICE_STATES = {
    "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE", "WRITTEN_OFF",
}

PAYMENT_RECORD_STATES = {"RECEIVED", "REVERSED"}

CREDIT_NOTE_ORIGINS = {
    "REFUND_DOWNGRADE", "MANUAL_ADJUSTMENT", "TAX_CORRECTION",
}

ROUNDING_MODES = {"PER_LINE", "TOTAL"}

TARGET_SYSTEMS = {"PAYMENT_PAY", "ACCOUNTING", "CRM", "TAX_COMPLIANCE"}
SYNC_EVENT_TYPES = {
    "SUBSCRIPTION_CREATED", "SUBSCRIPTION_CHANGED", "INVOICE_ISSUED",
    "PAYMENT_RECEIVED", "TENANT_SUSPENDED", "TENANT_REACTIVATED",
}
DELIVERY_STATES = {"QUEUED", "DELIVERED", "FAILED"}

AUDIT_ACTIONS = {
    "SUBSCRIPTION_CREATE", "SUBSCRIPTION_UPGRADE", "SUBSCRIPTION_DOWNGRADE",
    "INVOICE_ADJUSTMENT", "CREDIT_ISSUE", "TENANT_STATUS_CHANGE",
}


# ---------------------------------------------------------------------------
# Tenant (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_tenant(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Tenant")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("contact_email"), str)
    assert isinstance(data.get("contact_phone"), str)
    assert data.get("billing_entity_type") in BILLING_ENTITY_TYPES
    parent_tenant_id = data.get("parent_tenant_id")
    if parent_tenant_id is not None:
        assert is_valid_uuid(parent_tenant_id), (
            f"Tenant.parent_tenant_id must be UUID or null, got "
            f"{parent_tenant_id!r}"
        )
    assert isinstance(data.get("currency"), str) and data["currency"]
    assert isinstance(data.get("jurisdiction_code"), str)
    assert data.get("tenant_status") in TENANT_STATUS_SET
    assert data.get("restriction_level") in RESTRICTION_LEVELS
    # outstanding_balance_cents is computed (PRD §3.11)
    obc = data.get("outstanding_balance_cents")
    assert isinstance(obc, int) and obc >= 0, (
        f"Tenant.outstanding_balance_cents must be non-negative int, "
        f"got {obc!r}"
    )


# ---------------------------------------------------------------------------
# Subscription (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_subscription(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Subscription")
    assert is_valid_uuid(data.get("tenant_id", ""))
    assert isinstance(data.get("package_code"), str)
    pkg_ver_id = data.get("package_version_id")
    if pkg_ver_id is not None:
        assert is_valid_uuid(pkg_ver_id), (
            f"Subscription.package_version_id must be UUID or null, got "
            f"{pkg_ver_id!r}"
        )
    selected_addons = data.get("selected_addons", [])
    assert isinstance(selected_addons, list)
    assert data.get("subscription_status") in SUBSCRIPTION_STATES
    assert data.get("payment_status") in PAYMENT_STATES
    if data.get("cycle_start") is not None:
        assert is_iso8601_timestamp(data["cycle_start"])
    if data.get("cycle_end") is not None:
        assert is_iso8601_timestamp(data["cycle_end"])


# ---------------------------------------------------------------------------
# Invoice (PRD §3.9)
# ---------------------------------------------------------------------------
def assert_invoice(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Invoice")
    assert is_valid_uuid(data.get("tenant_id", ""))
    if data.get("subscription_id") is not None:
        assert is_valid_uuid(data["subscription_id"])
    assert data.get("invoice_status") in INVOICE_STATES
    assert isinstance(data.get("currency"), str) and data["currency"]
    # Money fields (PRD §2.8 integer cents).
    for f in (
        "subtotal_cents", "discount_cents", "credit_applied_cents",
        "tax_cents", "late_fee_cents", "total_cents",
        "amount_paid_cents", "amount_due_cents",
    ):
        v = data.get(f)
        assert isinstance(v, int), (
            f"Invoice.{f} must be integer cents, got {v!r}"
        )
    assert data["discount_cents"] >= 0
    assert data["credit_applied_cents"] >= 0
    assert data["late_fee_cents"] >= 0
    # amount_due_cents = max(total - paid, 0) per PRD §3.9 step 10.
    assert data["amount_due_cents"] >= 0
    if data.get("cycle_start") is not None:
        assert is_iso8601_timestamp(data["cycle_start"])
    if data.get("cycle_end") is not None:
        assert is_iso8601_timestamp(data["cycle_end"])
    if data.get("due_at") is not None:
        assert is_iso8601_timestamp(data["due_at"])
    if data.get("pricing_model") is not None:
        assert data["pricing_model"] in PRICING_MODELS


# ---------------------------------------------------------------------------
# PackageVersion (PRD §3.1 — append-only)
# ---------------------------------------------------------------------------
def assert_package_version(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "PackageVersion")
    # PRD §3.1: append-only "carries only id, created_at, and the fields
    # above — no updated_at, no version."
    assert "updated_at" not in data, (
        "PackageVersion must not carry updated_at per PRD §2.4"
    )
    assert "version" not in data, (
        "PackageVersion must not carry version per PRD §2.4"
    )
    assert isinstance(data.get("package_code"), str) and data["package_code"]
    assert isinstance(data.get("version_number"), int)
    assert data["version_number"] >= 1, (
        "PRD §3.1: 'strictly monotonic version_number starting at 1'"
    )
    assert data.get("package_type") in PACKAGE_TYPES
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert isinstance(data.get("base_price_cents"), int)
    assert isinstance(data.get("currency"), str)
    assert data.get("billing_cycle") in BILLING_CYCLES
    assert data.get("pricing_model") in PRICING_MODELS


# ---------------------------------------------------------------------------
# SubscriptionChange (PRD §3.4 — append-only)
# ---------------------------------------------------------------------------
def assert_subscription_change(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "SubscriptionChange")
    assert "updated_at" not in data
    assert "version" not in data
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("tenant_id", ""))
    assert data.get("change_type") in SUBSCRIPTION_CHANGE_TYPES
    if data.get("effective_at") is not None:
        assert is_iso8601_timestamp(data["effective_at"])
    pcc = data.get("prorated_charge_cents")
    assert isinstance(pcc, int), (
        f"SubscriptionChange.prorated_charge_cents must be int (signed), "
        f"got {pcc!r}"
    )


# ---------------------------------------------------------------------------
# UsageRecord (PRD §3.7 — append-only)
# ---------------------------------------------------------------------------
def assert_usage_record(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "UsageRecord")
    assert "updated_at" not in data
    assert "version" not in data
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("tenant_id", ""))
    assert isinstance(data.get("idempotency_key"), str)
    assert data.get("metric") in USAGE_METRICS
    q = data.get("quantity")
    assert isinstance(q, int) and q >= 0, (
        "PRD §3.7: 'a non-negative integer quantity'"
    )
    assert is_iso8601_timestamp(data.get("event_timestamp", ""))
    assert data.get("ingestion_mode") in INGESTION_MODES
    # attributed_cycle_start is computed by usage_attribution
    if data.get("attributed_cycle_start") is not None:
        assert is_iso8601_timestamp(data["attributed_cycle_start"])
    if "archived" in data:
        assert isinstance(data["archived"], bool)


# ---------------------------------------------------------------------------
# Payment (PRD §3.11 — append-only)
# ---------------------------------------------------------------------------
def assert_payment(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "Payment")
    assert "updated_at" not in data
    assert "version" not in data
    assert is_valid_uuid(data.get("tenant_id", ""))
    assert is_valid_uuid(data.get("invoice_id", ""))
    amt = data.get("amount_cents")
    assert isinstance(amt, int) and amt > 0, (
        "PRD §3.11: 'a positive integer amount_cents'"
    )
    assert isinstance(data.get("currency"), str)
    assert isinstance(data.get("external_reference"), str)
    assert data.get("payment_status") in PAYMENT_RECORD_STATES


# ---------------------------------------------------------------------------
# CreditNote (PRD §3.11 — append-only)
# ---------------------------------------------------------------------------
def assert_credit_note(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "CreditNote")
    assert "updated_at" not in data
    assert "version" not in data
    assert is_valid_uuid(data.get("tenant_id", ""))
    assert data.get("origin") in CREDIT_NOTE_ORIGINS
    amt = data.get("amount_cents")
    assert isinstance(amt, int) and amt > 0, (
        "PRD §3.11: 'amount_cents (positive)'"
    )
    if data.get("applied_to_invoice_id") is not None:
        assert is_valid_uuid(data["applied_to_invoice_id"])
    applied = data.get("applied_cents", 0)
    assert isinstance(applied, int) and applied >= 0
    assert applied <= amt, (
        "PRD §3.11: 'applied_cents (the cents actually consumed; less "
        "than or equal to amount_cents)'"
    )


# ---------------------------------------------------------------------------
# Jurisdiction (PRD §3.13 — append-only)
# ---------------------------------------------------------------------------
def assert_jurisdiction(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "Jurisdiction")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data.get("jurisdiction_code"), str)
    rate = data.get("tax_rate_bps")
    assert isinstance(rate, int) and rate >= 0
    assert data.get("rounding_mode") in ROUNDING_MODES


# ---------------------------------------------------------------------------
# SyncEvent (PRD §2.13 — append-only)
# ---------------------------------------------------------------------------
def assert_sync_event(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "SyncEvent")
    assert "updated_at" not in data
    assert "version" not in data
    assert is_valid_uuid(data.get("tenant_id", ""))
    assert data.get("target_system") in TARGET_SYSTEMS
    assert data.get("event_type") in SYNC_EVENT_TYPES
    assert data.get("delivery_status") in DELIVERY_STATES


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.13 — append-only)
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "AuditLog")
    assert "updated_at" not in data
    assert "version" not in data
    if data.get("tenant_id") is not None:
        assert is_valid_uuid(data["tenant_id"])
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert data.get("action") in AUDIT_ACTIONS
    assert isinstance(data.get("target_entity_type"), str)


# ---------------------------------------------------------------------------
# Helpers for searching collections returned by listing endpoints
# ---------------------------------------------------------------------------
def find_first(items: Iterable[Dict[str, Any]],
               **filters: Any) -> Optional[Dict[str, Any]]:
    """Return the first item that matches every key=value filter."""
    for item in items:
        if all(item.get(k) == v for k, v in filters.items()):
            return item
    return None


def find_all(items: Iterable[Dict[str, Any]],
             **filters: Any) -> List[Dict[str, Any]]:
    """Return every item that matches every key=value filter."""
    return [
        item for item in items
        if all(item.get(k) == v for k, v in filters.items())
    ]


# ---------------------------------------------------------------------------
# Invariant cross-checks
# ---------------------------------------------------------------------------
def assert_invoice_totals_consistent(invoice: Dict[str, Any]) -> None:
    """PRD §3.9 step 10: 'total_cents is the taxable base plus tax_cents
    minus credit_applied_cents plus late_fee_cents.'

    PRD §3.9 also requires amount_due_cents = max(total - paid, 0).
    """
    subtotal = invoice["subtotal_cents"]
    discount = invoice["discount_cents"]
    credit = invoice["credit_applied_cents"]
    tax = invoice["tax_cents"]
    late_fee = invoice["late_fee_cents"]
    total = invoice["total_cents"]
    paid = invoice["amount_paid_cents"]
    due = invoice["amount_due_cents"]
    expected_total = (subtotal - discount) + tax - credit + late_fee
    assert total == expected_total, (
        f"Invoice total inconsistent: total={total}, expected "
        f"(subtotal-discount)+tax-credit+late_fee={expected_total} "
        f"(subtotal={subtotal}, discount={discount}, tax={tax}, "
        f"credit={credit}, late_fee={late_fee})"
    )
    assert due == max(total - paid, 0), (
        f"Invoice.amount_due_cents inconsistent: due={due}, "
        f"total={total}, paid={paid}"
    )


__all__ = [
    "TENANT_STATUS_SET", "RESTRICTION_LEVELS", "BILLING_ENTITY_TYPES",
    "PACKAGE_TYPES", "BILLING_CYCLES", "PRICING_MODELS",
    "SUBSCRIPTION_STATES", "PAYMENT_STATES",
    "SUBSCRIPTION_CHANGE_TYPES",
    "USAGE_METRICS", "INGESTION_MODES",
    "INVOICE_STATES",
    "PAYMENT_RECORD_STATES", "CREDIT_NOTE_ORIGINS",
    "ROUNDING_MODES",
    "TARGET_SYSTEMS", "SYNC_EVENT_TYPES", "DELIVERY_STATES",
    "AUDIT_ACTIONS",
    "assert_tenant", "assert_subscription", "assert_invoice",
    "assert_package_version", "assert_subscription_change",
    "assert_usage_record",
    "assert_payment", "assert_credit_note",
    "assert_jurisdiction",
    "assert_sync_event", "assert_audit_log",
    "find_first", "find_all",
    "assert_invoice_totals_consistent",
]

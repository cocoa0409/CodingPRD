"""Live Stream Schedule — per-entity assertions and domain invariants.

Field names and enum values come from PRD §3 and §1.1. Assertions stay close to
'shape + presence + range', and avoid asserting computed-field values that the
PRD does not explicitly require on the response (those are tested via dedicated
calculation tests in test_suite/).
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: Dict[str, Any]) -> None:
    """Per PRD §2.4 — heavyweight entities carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Per PRD §2.4 — log/snapshot entities carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # PRD: 'they have neither updated_at nor version' — do not assert absence,
    # just don't require their presence.


# ---------------------------------------------------------------------------
# Streamer
# ---------------------------------------------------------------------------

def assert_streamer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["id_card_number"], str) and data["id_card_number"]
    assert isinstance(data["real_name_verified"], bool)
    assert is_iso8601_timestamp(data.get("health_cert_expires_at", "")), \
        "health_cert_expires_at must be ISO 8601"
    assert isinstance(data["professional_cert_categories"], list)
    assert isinstance(data["content_category_tags"], list)
    assert data["tier"] in {"BRONZE", "SILVER", "GOLD", "PLATINUM"}
    assert isinstance(data["lifetime_gmv_cents"], int) and data["lifetime_gmv_cents"] >= 0
    assert isinstance(data["completed_broadcast_count"], int) and data["completed_broadcast_count"] >= 0
    assert isinstance(data["violation_score"], int) and data["violation_score"] >= 0
    assert data["status"] in {"ACTIVE", "SUSPENDED", "BLACKLISTED"}
    # suspension_until may be null
    if data.get("suspension_until") is not None:
        assert is_iso8601_timestamp(data["suspension_until"])


# ---------------------------------------------------------------------------
# Studio
# ---------------------------------------------------------------------------

def assert_studio(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["location"], str)
    assert isinstance(data["equipment_inventory"], list)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["studio_type"] in {"SELF_OPERATED", "PARTNER"}
    assert data["slot_tier"] in {"S", "A", "B", "C"}
    assert isinstance(data["base_hour_price_cents"], int) and data["base_hour_price_cents"] >= 0
    assert data["status"] in {"OPEN", "RESTRICTED", "UNDER_MAINTENANCE", "CLOSED"}


# ---------------------------------------------------------------------------
# TimeSlotConfig (append-only)
# ---------------------------------------------------------------------------

def assert_time_slot(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert data["kind"] in {"AVAILABLE", "MAINTENANCE"}
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data.get("weekday_mask", 0), int)


# ---------------------------------------------------------------------------
# Product & ProductAssociation
# ---------------------------------------------------------------------------

def assert_product(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in {"FOOD", "COSMETICS", "ELECTRONICS", "FASHION", "KIDS", "FINANCIAL"}
    assert isinstance(data["requires_professional_cert"], bool)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["available_stock"], int) and data["available_stock"] >= 0
    assert isinstance(data["reserved_stock"], int) and data["reserved_stock"] >= 0
    assert data["status"] in {"ON_SHELF", "OFF_SHELF"}


def assert_product_association(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["reserved_quantity"], int) and data["reserved_quantity"] >= 1
    assert data["association_phase"] in {"PRE_APPROVAL", "DURING_BROADCAST"}
    assert data["status"] in {"PENDING_MATCH", "APPROVED", "REJECTED", "RELEASED"}


# ---------------------------------------------------------------------------
# ScheduleApplication
# ---------------------------------------------------------------------------

def assert_application(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["streamer_id"])
    assert is_valid_uuid(data["studio_id"])
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["declared_content_categories"], list)
    assert isinstance(data["declared_product_categories"], list)
    assert data["package_code"] in {"STANDARD", "COMBO_HALF_DAY", "COMBO_FULL_DAY", "PEAK_BUNDLE"}
    assert data["review_status"] in {
        "DRAFT", "OPS_PENDING", "COMPLIANCE_PENDING", "APPROVED", "REJECTED", "WITHDRAWN"
    }
    assert data["operational_status"] in {
        "NOT_SCHEDULED", "SCHEDULED", "LIVE", "COMPLETED", "CANCELLED"
    }
    assert isinstance(data.get("deposit_paid", False), bool)


# ---------------------------------------------------------------------------
# Approval record (append-only)
# ---------------------------------------------------------------------------

def assert_approval_record(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data["level"] in {"OPS", "COMPLIANCE"}
    assert data["decision"] in {"APPROVE", "REJECT"}
    assert data["reviewer_role"] in {"OperationsReviewer", "ComplianceReviewer"}
    assert isinstance(data["reviewer_id"], str) and data["reviewer_id"]
    # snapshot_streamer_tier is pinned per PRD §3.4
    assert data["snapshot_streamer_tier"] in {"BRONZE", "SILVER", "GOLD", "PLATINUM"}
    assert isinstance(data["snapshot_provisional_fee_cents"], int)


# ---------------------------------------------------------------------------
# SlotFeeInvoice
# ---------------------------------------------------------------------------

def assert_invoice(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["peak_surcharge_cents"], int) and data["peak_surcharge_cents"] >= 0
    assert isinstance(data["package_discount_cents"], int) and data["package_discount_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["deposit_due_cents"], int) and data["deposit_due_cents"] >= 0
    assert data["status"] in {
        "ISSUED", "DEPOSIT_PAID", "SETTLED", "REFUNDED_FULL", "REFUNDED_PARTIAL", "VOIDED"
    }
    assert isinstance(data.get("refund_cents", 0), int) and data.get("refund_cents", 0) >= 0


# ---------------------------------------------------------------------------
# CommissionSettlement
# ---------------------------------------------------------------------------

def assert_settlement(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["gross_sales_cents"], int) and data["gross_sales_cents"] >= 0
    assert isinstance(data["returned_sales_cents"], int) and data["returned_sales_cents"] >= 0
    assert isinstance(data["commission_rate_bp"], int) and data["commission_rate_bp"] >= 0
    assert isinstance(data["tier_bonus_cents"], int) and data["tier_bonus_cents"] >= 0
    assert is_iso8601_timestamp(data["return_window_ends_at"])
    assert data["status"] in {"PENDING", "WINDOW_OPEN", "READY_FOR_PAYOUT", "PAID", "REVERSED"}


# ---------------------------------------------------------------------------
# Violation & Appeal
# ---------------------------------------------------------------------------

def assert_violation(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["streamer_id"])
    assert data["violation_type"] in {"FALSE_ADVERTISING", "WRONG_PRODUCT", "VIOLATING_CONTENT", "DATA_FRAUD"}
    assert isinstance(data["evidence_refs"], list)
    assert isinstance(data["severity"], int) and data["severity"] >= 1
    assert data["penalty_action"] in {"WARNING", "FINE", "SUSPENSION", "BLACKLIST"}
    assert isinstance(data.get("fine_cents", 0), int) and data.get("fine_cents", 0) >= 0
    assert isinstance(data.get("suspension_days", 0), int) and data.get("suspension_days", 0) >= 0
    assert data["status"] in {"OPEN", "APPEAL_PENDING", "UPHELD", "OVERTURNED", "ENFORCED"}


def assert_appeal(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["violation_id"])
    assert is_valid_uuid(data["streamer_id"])
    assert isinstance(data["argument"], str) and data["argument"]
    assert data["decision"] in {"PENDING", "UPHELD", "OVERTURNED"}


# ---------------------------------------------------------------------------
# Stock invariant (per PRD §3.3)
# ---------------------------------------------------------------------------

def assert_stock_conserved(product_before: Dict[str, Any], product_after: Dict[str, Any]) -> None:
    """PRD §3.3 — across create+release pairs, (available + reserved) is preserved."""
    before = product_before["available_stock"] + product_before["reserved_stock"]
    after = product_after["available_stock"] + product_after["reserved_stock"]
    assert before == after, (
        f"Stock invariant violated: before={before} (avail={product_before['available_stock']}, "
        f"reserved={product_before['reserved_stock']}), after={after} "
        f"(avail={product_after['available_stock']}, reserved={product_after['reserved_stock']})"
    )

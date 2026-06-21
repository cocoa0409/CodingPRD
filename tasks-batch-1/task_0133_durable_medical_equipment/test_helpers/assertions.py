"""Entity assertions and domain invariant checkers for the DME API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

_ORDER_STATES = [
    "DRAFT", "READY_FOR_DELIVERY", "DELIVERED", "ACTIVE",
    "CONVERTED_TO_PURCHASE", "CLOSED", "CANCELLED",
]


def _assert_common(data: dict):
    """id + created_at + updated_at + version (all entities carry common_fields)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["medicare_id"], str) and len(data["medicare_id"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["address_state"], str)


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["ptan"], str) and len(data["ptan"]) > 0
    assert isinstance(data["accreditation_active"], bool)


def assert_hcpcs_item(data: dict):
    _assert_common(data)
    assert isinstance(data["hcpcs_code"], str) and len(data["hcpcs_code"]) > 0
    assert data["billing_category"] in (
        "CAPPED_RENTAL", "INEXPENSIVE_ROUTINE", "PURCHASE_ONLY", "OXYGEN"
    )
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["monthly_rental_cents"], int)
    assert isinstance(data["requires_cmn"], bool)
    assert isinstance(data["requires_prior_auth"], bool)
    assert isinstance(data["is_cpap"], bool)


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["hcpcs_item_id"])
    assert data["acquisition_type"] in ("RENTAL", "PURCHASE")
    assert data["modifier"] in ("NONE", "NU", "KX")
    assert data["status"] in _ORDER_STATES
    assert isinstance(data["rental_months_billed"], int)
    assert isinstance(data["cap_reached"], bool)
    assert isinstance(data["total_allowed_cents"], int)


def assert_cmn(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["physician_npi"], str)
    assert isinstance(data["length_of_need_months"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "REVOKED")


def assert_prior_auth(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "EXPIRED")


def assert_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["pod_received"], bool)
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "FAILED", "CANCELLED")


def assert_rental_cycle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert isinstance(data["billed_amount_cents"], int)
    assert data["status"] in ("BILLED", "PAID", "RECOUPED")


def assert_claim_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["line_type"] in ("RENTAL_MONTH", "PURCHASE", "RECOUPMENT")
    assert isinstance(data["allowed_amount_cents"], int)
    assert data["status"] in ("POSTED", "SETTLED", "VOID")


def assert_resupply(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["supply_kind"] in ("MASK", "TUBING", "FILTER", "HEADGEAR")
    assert isinstance(data["quantity"], int)
    assert data["status"] in ("REQUESTED", "SHIPPED", "DENIED")


def assert_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["reason_code"] in (
        "NO_VALID_CMN", "NO_PROOF_OF_DELIVERY", "OVERBILLED_PAST_CAP", "NO_PRIOR_AUTH"
    )
    assert isinstance(data["recouped_total_cents"], int)
    assert isinstance(data["recouped_cycle_count"], int)
    assert data["status"] in ("OPEN", "UPHELD", "DISMISSED")


def assert_ledger_identity(order: dict, claim_lines: list):
    """PRD §2.7: order.total_allowed_cents == sum of allowed_amount_cents over
    non-VOID claim lines, with no drift."""
    live_sum = sum(
        cl["allowed_amount_cents"] for cl in claim_lines if cl["status"] != "VOID"
    )
    assert order["total_allowed_cents"] == live_sum, (
        f"Ledger drift: order.total_allowed_cents={order['total_allowed_cents']} "
        f"!= sum of non-VOID claim lines={live_sum}"
    )

"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_audit_only(data: dict):
    """For append-only records (FootMeasurement, LoyaltyLedgerEntry): id + created_at only."""
    _assert_common(data)


def assert_product(data: dict):
    _assert_versioned(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["brand"], str)
    assert data["category"] in {"THERAPEUTIC", "DIABETIC", "ORTHOTIC", "REGULAR", "INSERT"}
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["is_recalled"], bool)


def assert_inventory_item(data: dict):
    _assert_versioned(data)
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert isinstance(data["quantity_reserved"], int) and data["quantity_reserved"] >= 0
    assert data["quantity_available"] == data["quantity_on_hand"] - data["quantity_reserved"], \
        "quantity_available must equal on_hand - reserved"
    assert data["status"] in {"AVAILABLE", "QUARANTINED", "DISCONTINUED"}


def assert_customer(data: dict):
    _assert_versioned(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["is_pediatric"], bool)
    assert isinstance(data["loyalty_points_balance"], int)
    assert data["loyalty_tier"] in {"BRONZE", "SILVER", "GOLD"}


def assert_measurement(data: dict):
    _assert_audit_only(data)
    assert "updated_at" not in data, "FootMeasurement is an immutable audit record: no updated_at"
    assert "version" not in data, "FootMeasurement is an immutable audit record: no version"
    assert isinstance(data["recommended_mondo_mm"], int)
    assert isinstance(data["length_change_mm_from_prior"], int)


def assert_fitter(data: dict):
    _assert_versioned(data)
    assert isinstance(data["full_name"], str) and data["full_name"]


def assert_gait_lab(data: dict):
    _assert_versioned(data)
    assert isinstance(data["concurrent_capacity"], int) and data["concurrent_capacity"] >= 1


def assert_appointment(data: dict):
    _assert_versioned(data)
    assert data["appointment_type"] in {"FITTING", "GAIT", "DIABETIC_FITTING"}
    assert data["status"] in {"SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"}


def assert_sale(data: dict):
    _assert_versioned(data)
    assert data["payment_status"] in {"UNPAID", "PAID", "REFUNDED"}
    assert data["fulfillment_status"] in {
        "PENDING", "FULFILLED", "PARTIALLY_RETURNED", "RETURNED", "CANCELLED"}
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["loyalty_points_earned"], int)


def assert_sale_line(data: dict):
    _assert_versioned(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["line_total_cents"] == data["unit_price_cents"] * data["quantity"], \
        "line_total_cents must equal unit_price_cents * quantity"
    assert data["status"] in {"ACTIVE", "RETURNED", "EXCHANGED"}


def assert_certification(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"COMPLETE", "SUPERSEDED"}


def assert_claim(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"DRAFT", "SUBMITTED", "PAID", "DENIED", "VOIDED"}


def assert_claim_reimbursement_invariant(data: dict):
    """PRD §3.6: medicare_paid_cents + patient_responsibility_cents == allowed_amount_cents."""
    assert data["medicare_paid_cents"] + data["patient_responsibility_cents"] == data["allowed_amount_cents"], \
        "medicare_paid + patient_responsibility must equal allowed_amount"


def assert_return_request(data: dict):
    _assert_versioned(data)
    assert data["return_type"] in {"RETURN", "EXCHANGE"}
    assert data["status"] in {"REQUESTED", "APPROVED", "REJECTED", "REFUNDED", "EXCHANGED"}


def assert_special_order(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"DRAFT", "ORDERED", "RECEIVED", "FULFILLED", "CANCELLED"}


def assert_recall(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"DRAFT", "ISSUED", "CLOSED"}


def assert_ledger_entry(data: dict):
    _assert_audit_only(data)
    assert "updated_at" not in data, "LoyaltyLedgerEntry is an immutable audit record: no updated_at"
    assert "version" not in data, "LoyaltyLedgerEntry is an immutable audit record: no version"
    assert isinstance(data["points_delta"], int)
    assert data["reason"] in {"EARN", "REVERSAL", "REDEEM", "ADJUST"}

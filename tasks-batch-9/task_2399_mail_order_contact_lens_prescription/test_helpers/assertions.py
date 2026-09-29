"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CancellationReason,
    CaptureMode,
    ComplianceEventType,
    ContactChannel,
    DisputeStatus,
    OrderFulfillmentState,
    OrderVerificationState,
    PrescriptionStatus,
    ReimbursementClaimStatus,
    ReorderHoldStatus,
    ReturnRequestStatus,
    ScheduleStatus,
    SubstitutionType,
    VerificationRequestStatus,
)


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict, entity_name: str = "entity"):
    """Every non-append-only row carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid uuid"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_insurance_plan(data: dict):
    assert_common_fields(data, "InsurancePlan")
    assert isinstance(data["name"], str) and data["name"]
    assert data["network_status"] in ["IN_NETWORK", "OUT_OF_NETWORK"]
    assert isinstance(data["annual_allowance_cents"], int)
    assert data["annual_allowance_cents"] >= 0
    assert 0.0 <= float(data["coinsurance_rate"]) <= 1.0
    assert isinstance(data["requires_itemized_receipt"], bool)
    assert isinstance(data["covers_shipping"], bool)
    assert isinstance(data["claim_window_days"], int)
    assert isinstance(data["plan_year_start_month_day"], str)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_product(data: dict):
    assert_common_fields(data, "Product")
    assert isinstance(data["brand"], str) and data["brand"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["wear_schedule"] in ["DAILY_DISPOSABLE", "BIWEEKLY", "MONTHLY"]
    assert isinstance(data["lenses_per_box"], int) and data["lenses_per_box"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 1
    assert float(data["sphere_max"]) >= float(data["sphere_min"])
    assert isinstance(data["material_family"], str) and data["material_family"]
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_lens_equivalence(data: dict):
    assert_common_fields(data, "LensEquivalence")
    assert is_valid_uuid(data["from_product_id"])
    assert is_valid_uuid(data["to_product_id"])
    assert data["equivalence_class"] in ["EXACT", "CLINICAL", "MATERIAL_ONLY"]
    assert isinstance(data["requires_patient_consent"], bool)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_prescriber(data: dict):
    assert_common_fields(data, "Prescriber")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["license_state"], str) and data["license_state"]
    assert data["contact_channel"] in _enum_values(ContactChannel)
    assert isinstance(data["directory_verified"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_customer(data: dict):
    assert_common_fields(data, "Customer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    for field in (
        "store_credit_cents",
        "lifetime_charged_cents",
        "lifetime_refunded_cents",
        "net_cash_position_cents",
        "allowance_used_cents",
        "open_hold_count",
        "active_schedule_count",
    ):
        assert isinstance(data[field], int), f"Customer.{field} must be an integer"
        assert data[field] >= 0, f"Customer.{field} must never go negative"
    assert isinstance(data["auto_reorder_enabled"], bool)


def assert_customer_ledger(data: dict):
    assert is_valid_uuid(data["customer_id"])
    for field in (
        "lifetime_charged_cents",
        "lifetime_refunded_cents",
        "net_cash_position_cents",
        "store_credit_cents",
        "allowance_used_cents",
        "allowance_remaining_cents",
        "open_hold_count",
        "active_schedule_count",
    ):
        assert isinstance(data[field], int), f"ledger.{field} must be an integer"
        assert data[field] >= 0, f"ledger.{field} must never go negative"
    assert isinstance(data["auto_reorder_enabled"], bool)
    assert (
        data["net_cash_position_cents"]
        == data["lifetime_charged_cents"] - data["lifetime_refunded_cents"]
    ), "net_cash_position_cents must equal charged minus refunded"
    assert data["auto_reorder_enabled"] == (
        data["active_schedule_count"] > 0 and data["open_hold_count"] == 0
    ), "auto_reorder_enabled must follow schedule and hold counts"


def assert_prescription(data: dict):
    assert_common_fields(data, "Prescription")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["capture_mode"] in _enum_values(CaptureMode)
    assert data["status"] in _enum_values(PrescriptionStatus)
    assert isinstance(data["boxes_authorized_total"], int)
    assert data["boxes_authorized_total"] >= 1
    assert isinstance(data["boxes_consumed"], int) and data["boxes_consumed"] >= 0
    assert data["boxes_consumed"] <= data["boxes_authorized_total"], (
        "boxes_consumed may never exceed boxes_authorized_total"
    )
    assert isinstance(data["verification_rounds"], int)
    assert 0 <= data["verification_rounds"] <= 3
    assert data["expiry_date"] > data["issue_date"], (
        "expiry_date must be strictly after issue_date"
    )


def assert_verification_request(data: dict):
    assert_common_fields(data, "VerificationRequest")
    assert is_valid_uuid(data["prescription_id"])
    assert is_valid_uuid(data["prescriber_id"])
    assert data["channel"] in _enum_values(ContactChannel)
    assert is_iso8601_timestamp(data["sent_at"])
    assert is_iso8601_timestamp(data["passive_deadline_at"])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in _enum_values(VerificationRequestStatus)


def assert_order(data: dict):
    assert_common_fields(data, "Order")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["prescription_id"])
    assert is_valid_uuid(data["ordered_product_id"])
    assert isinstance(data["boxes_od"], int) and data["boxes_od"] >= 0
    assert isinstance(data["boxes_os"], int) and data["boxes_os"] >= 0
    assert data["boxes_od"] + data["boxes_os"] >= 1
    assert data["verification_state"] in _enum_values(OrderVerificationState)
    assert data["fulfillment_state"] in _enum_values(OrderFulfillmentState)
    assert data["substitution_type"] in _enum_values(SubstitutionType)
    assert isinstance(data["recall_flagged"], bool)
    if data.get("cancellation_reason") is not None:
        assert data["cancellation_reason"] in _enum_values(CancellationReason)
    assert_order_money(data)


def assert_order_money(data: dict):
    """The three money fields must be integer cents and internally consistent."""
    for field in ("unit_price_cents", "subtotal_cents", "shipping_cents", "total_cents"):
        assert isinstance(data[field], int), f"Order.{field} must be integer cents"
        assert data[field] >= 0, f"Order.{field} must not be negative"
    assert (
        data["subtotal_cents"]
        == data["unit_price_cents"] * (data["boxes_od"] + data["boxes_os"])
    ), "subtotal_cents must be unit_price_cents times total boxes"
    assert (
        data["total_cents"] == data["subtotal_cents"] + data["shipping_cents"]
    ), "total_cents must be subtotal_cents plus shipping_cents"


def assert_reorder_hold(data: dict):
    assert_common_fields(data, "ReorderHold")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["prescription_id"])
    assert data["reason"] in [
        "PRESCRIBER_DENIED",
        "PRESCRIPTION_EXPIRED",
        "DISPUTE_UPHELD",
        "MANUAL",
    ]
    assert data["status"] in _enum_values(ReorderHoldStatus)
    if data.get("released_by_user_id") is not None:
        assert data["released_by_user_id"] != data["opened_by_user_id"], (
            "released_by_user_id must differ from opened_by_user_id"
        )


def assert_auto_reorder_schedule(data: dict):
    assert_common_fields(data, "AutoReorderSchedule")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["prescription_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["boxes_per_run"], int) and data["boxes_per_run"] >= 1
    assert data["cadence_basis"] in ["NOMINAL", "USAGE_ADJUSTED"]
    assert isinstance(data["cadence_days"], int) and data["cadence_days"] >= 14
    assert is_iso8601_timestamp(data["next_run_at"])
    assert isinstance(data["consecutive_skip_count"], int)
    assert data["status"] in _enum_values(ScheduleStatus)


def assert_return_request(data: dict):
    assert_common_fields(data, "ReturnRequest")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["reason"] in ["TORN_LENS", "PRESCRIPTION_CHANGE", "WRONG_PARAMETER"]
    assert data["status"] in _enum_values(ReturnRequestStatus)
    assert data["settlement_mode"] in [
        "PER_BOX_ROUNDED",
        "POOLED_ROUNDED",
        "NO_PRORATION",
    ]
    assert isinstance(data["settlement_cents"], int) and data["settlement_cents"] >= 0
    assert data["settlement_channel"] in ["CASH_REFUND", "STORE_CREDIT"]
    if data.get("settled_by_user_id") is not None:
        assert data["settled_by_user_id"] != data["approved_by_user_id"], (
            "settled_by_user_id must differ from approved_by_user_id"
        )


def assert_reimbursement_claim(data: dict):
    assert_common_fields(data, "ReimbursementClaim")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["insurance_plan_id"])
    assert data["status"] in _enum_values(ReimbursementClaimStatus)
    assert isinstance(data["refund_offset_cents"], int)


def assert_generated_claim_money_chain(data: dict):
    """Once generated, the money fields must be integer cents and chain in the
    order the PRD lays out."""
    for field in (
        "base_eligible_cents",
        "applied_allowance_cents",
        "coinsurance_cents",
        "pre_fee_subtotal_cents",
        "processing_fee_cents",
        "reimbursable_cents",
    ):
        assert isinstance(data[field], int), f"claim.{field} must be integer cents"
        assert data[field] >= 0, f"claim.{field} must not be negative"
    assert (
        data["pre_fee_subtotal_cents"]
        == data["applied_allowance_cents"] + data["coinsurance_cents"]
    ), "pre_fee_subtotal_cents must be applied allowance plus coinsurance"
    assert (
        data["reimbursable_cents"]
        == data["pre_fee_subtotal_cents"] - data["processing_fee_cents"]
    ), "reimbursable_cents must be the pre-fee subtotal minus the processing fee"


def assert_prescriber_dispute(data: dict):
    assert_common_fields(data, "PrescriberDispute")
    assert is_valid_uuid(data["prescription_id"])
    assert is_valid_uuid(data["prescriber_id"])
    assert data["dispute_reason"] in [
        "NOT_MY_PATIENT",
        "PARAMETERS_ALTERED",
        "NEVER_ISSUED",
    ]
    assert data["status"] in _enum_values(DisputeStatus)


def assert_compliance_event(data: dict):
    """Compliance events are append-only: id and timestamps only, never a
    version and never an updated_at."""
    assert is_valid_uuid(data.get("id", "")), "ComplianceEvent.id must be a valid uuid"
    assert data["event_type"] in _enum_values(ComplianceEventType)
    assert isinstance(data["subject_type"], str) and data["subject_type"]
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert is_iso8601_timestamp(data["occurred_at"])
    assert "version" not in data, "ComplianceEvent must not expose a version"
    assert "updated_at" not in data, "ComplianceEvent must not expose an updated_at"


def assert_no_append_only_mutable_fields(data: dict):
    """Alias used by immutability tests."""
    assert "version" not in data, "append-only rows must not expose a version"
    assert "updated_at" not in data, "append-only rows must not expose an updated_at"


def assert_pagination_meta(meta: dict, limit, offset, total_count, has_more):
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_ledger_values(ledger: dict, **expected):
    """Assert a subset of the ledger's fields, with a readable message."""
    for field, value in expected.items():
        assert ledger[field] == value, (
            f"Expected ledger.{field} to be {value}, got {ledger[field]}"
        )


def assert_timestamp_equals(actual: str, expected: str):
    """Compare an emitted timestamp with a millisecond-precision literal."""
    assert actual == expected, f"Expected timestamp {expected}, got {actual}"

"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """Every entity carries id, created_at, updated_at, version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_test_offering(data: dict):
    _assert_common(data)
    assert isinstance(data["test_code"], str) and len(data["test_code"]) > 0
    assert isinstance(data["display_name"], str)
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert data["specimen_type"] in ("BLOOD", "URINE", "SALIVA")
    assert isinstance(data["home_kit_eligible"], bool)
    assert isinstance(data["requires_fasting"], bool)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_panel_bundle(data: dict):
    _assert_common(data)
    assert isinstance(data["bundle_code"], str) and len(data["bundle_code"]) > 0
    assert isinstance(data["member_test_codes"], list)
    assert isinstance(data["bundle_price_cents"], int) and data["bundle_price_cents"] > 0
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["hsa_balance_cents"], int) and data["hsa_balance_cents"] >= 0
    assert isinstance(data["consent_share_results"], bool)
    assert data["status"] == "ACTIVE"


def assert_cart(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert data["fund_source"] in ("CARD", "HSA_FSA")
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["estimated_total_cents"], int) and data["estimated_total_cents"] >= 0
    assert isinstance(data["estimated_hsa_applied_cents"], int) and data["estimated_hsa_applied_cents"] >= 0
    assert isinstance(data["estimated_patient_due_cents"], int) and data["estimated_patient_due_cents"] >= 0
    assert data["status"] in ("OPEN", "CHECKED_OUT")


def assert_cart_line(data: dict):
    _assert_common(data)
    assert isinstance(data["cart_id"], str)
    assert isinstance(data["test_offering_id"], str)
    assert isinstance(data["test_code"], str)
    assert isinstance(data["unit_list_price_cents"], int)
    assert isinstance(data["repeat_discount_applied"], bool)


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["cart_id"], str)
    assert data["fulfillment_mode"] in ("PSC", "HOME_KIT")
    assert data["fund_source"] in ("CARD", "HSA_FSA")
    assert isinstance(data["invoiced_total_cents"], int) and data["invoiced_total_cents"] >= 0
    assert isinstance(data["hsa_applied_cents"], int) and data["hsa_applied_cents"] >= 0
    assert isinstance(data["patient_due_cents"], int) and data["patient_due_cents"] >= 0
    assert data["payment_status"] in ("AUTH_PENDING", "AUTHORIZED", "CAPTURED", "REFUNDED")
    assert data["fulfillment_status"] in (
        "AWAITING_COLLECTION", "IN_PROCESSING", "PARTIALLY_RESULTED", "COMPLETED", "CANCELLED",
    )


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["test_code"], str)
    assert isinstance(data["unit_list_price_cents"], int)
    assert isinstance(data["repeat_discount_applied"], bool)
    assert isinstance(data["requires_physician_order"], bool)
    assert data["status"] in ("ORDERED", "COLLECTED", "RESULTED", "REJECTED", "CANCELLED")


def assert_physician_order(data: dict):
    _assert_common(data)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["patient_id"], str)
    assert data["status"] in ("SUBMITTED", "NEEDS_MORE_INFO", "APPROVED", "DECLINED")


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["psc_location_code"], str)
    assert is_iso8601_timestamp(data["slot_start"])
    assert is_iso8601_timestamp(data["slot_end"])
    assert isinstance(data["fasting_confirmed"], bool)
    assert data["status"] in ("BOOKED", "CHECKED_IN", "CANCELLED")


def assert_home_kit(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["shipping_state_code"], str)
    assert isinstance(data["tracking_code"], str) and len(data["tracking_code"]) > 0
    assert data["status"] == "SHIPPED"


def assert_specimen(data: dict):
    _assert_common(data)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["collected_by_user_id"], str) and len(data["collected_by_user_id"]) > 0
    assert isinstance(data["accession_code"], str) and len(data["accession_code"]) > 0
    assert data["status"] in ("COLLECTED", "IN_ANALYSIS", "RESULTED", "REJECTED")


def assert_lab_result(data: dict):
    _assert_common(data)
    assert isinstance(data["specimen_id"], str)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["test_code"], str)
    assert data["provisional_flag"] in ("NORMAL", "ABNORMAL", "CRITICAL")
    assert data["status"] in ("PROCESSING", "PENDING_CRITICAL_CALLBACK", "RELEASED", "AMENDED")


def assert_telehealth_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_result_id"], str)
    assert isinstance(data["patient_id"], str)
    assert data["referral_reason"] in ("ABNORMAL", "CRITICAL")
    assert data["status"] in ("OPEN", "SCHEDULED", "CLOSED")


def assert_analyzer_run(data: dict):
    _assert_common(data)
    assert isinstance(data["analyzer_code"], str)
    assert is_iso8601_timestamp(data["run_start"])
    assert is_iso8601_timestamp(data["run_end"])
    assert isinstance(data["buffer_minutes"], int)
    assert data["status"] in ("RESERVED", "RELEASED")


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert data["fund_source"] in ("CARD", "HSA_FSA")
    assert isinstance(data["authorized_amount_cents"], int) and data["authorized_amount_cents"] >= 0
    assert isinstance(data["captured_amount_cents"], int) and data["captured_amount_cents"] >= 0
    assert isinstance(data["hsa_drawn_cents"], int) and data["hsa_drawn_cents"] >= 0
    assert data["status"] in ("AUTHORIZED", "CAPTURED", "REFUNDED")

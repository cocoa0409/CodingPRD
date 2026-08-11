"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(str(data.get("id", ""))), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert data["copay_tier"] in ("STANDARD", "LOW_INCOME")
    assert data["status"] in ("INTAKE", "ACTIVE")


def assert_referral(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["client_id"]))
    assert data["source_type"] in ("PHYSICIAN", "VR_AGENCY", "INSURANCE", "SELF")
    assert isinstance(data["referring_party"], str)
    assert data["status"] in ("RECEIVED", "ACCEPTED", "DECLINED")


def assert_evaluation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["client_id"]))
    assert is_valid_uuid(str(data["referral_id"]))
    for f in ("acuity_score", "contrast_score", "field_loss_pct"):
        v = data.get(f)
        assert v is None or (isinstance(v, int) and 0 <= v <= 100), f"{f} out of range"
    assert data.get("recommended_category") in (None, "MAGNIFIER", "CCTV", "SCREEN_READER")
    assert data["status"] in ("DRAFT", "FINALIZED", "REVISED", "SUPERSEDED")


def assert_device_model(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ("MAGNIFIER", "CCTV", "SCREEN_READER")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["subscription_monthly_cents"], int) and data["subscription_monthly_cents"] >= 0
    assert isinstance(data["in_stock_count"], int) and data["in_stock_count"] >= 0
    assert isinstance(data["total_count"], int) and data["total_count"] >= 0


def assert_device_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["device_model_id"]))
    assert isinstance(data["serial_no"], str) and data["serial_no"]
    assert data["condition"] in ("NEW", "REFURB", "LOANER")
    assert data["status"] in ("IN_STOCK", "DEPLOYED", "ON_LOAN", "IN_REPAIR", "RETIRED")


def assert_device_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["client_id"]))
    assert is_valid_uuid(str(data["evaluation_id"]))
    assert is_valid_uuid(str(data["device_model_id"]))
    assert data["fulfillment_type"] in ("PURCHASE", "TRIAL", "LOANER")
    assert data["status"] in ("PLACED", "ACTIVE", "CONVERTED", "RETURNED", "EXPIRED")


def assert_loan_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["device_unit_id"]))
    assert is_iso8601_timestamp(str(data["loaned_at"]))
    assert is_iso8601_timestamp(str(data["due_at"]))
    assert isinstance(data["overdue_days"], int) and data["overdue_days"] >= 0
    assert data["status"] in ("ACTIVE", "OVERDUE", "RETURNED")


def assert_training_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["client_id"]))
    assert is_valid_uuid(str(data["device_order_id"]))
    assert isinstance(data["total_sessions"], int) and 1 <= data["total_sessions"] <= 20
    assert isinstance(data["completed_sessions"], int) and data["completed_sessions"] >= 0
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED", "SUSPENDED")


def assert_training_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["training_plan_id"]))
    assert isinstance(data["instructor_user_id"], str) and data["instructor_user_id"]
    assert is_iso8601_timestamp(str(data["scheduled_start"]))
    assert is_iso8601_timestamp(str(data["scheduled_end"]))
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_funding_authorization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["client_id"]))
    assert data["payer_type"] in ("VR", "INSURANCE")
    assert isinstance(data["authorized_amount_cents"], int) and data["authorized_amount_cents"] > 0
    assert isinstance(data["remaining_amount_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "DENIED", "APPEALED", "EXPIRED", "EXHAUSTED")


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["funding_authorization_id"]))
    assert is_valid_uuid(str(data["device_order_id"]))
    assert isinstance(data["provisional_total_cents"], int) and data["provisional_total_cents"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "PAID", "DENIED", "VOIDED")


def assert_repair_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["device_unit_id"]))
    assert isinstance(data["issue_description"], str)
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert data["status"] in ("INTAKE", "DIAGNOSED", "IN_REPAIR", "QA_CHECK", "RESOLVED")


def assert_subscription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["client_id"]))
    assert is_valid_uuid(str(data["device_model_id"]))
    assert isinstance(data["total_paid_cents"], int) and data["total_paid_cents"] >= 0
    assert isinstance(data["last_fee_cents"], int) and data["last_fee_cents"] >= 0
    assert data["status"] in ("ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED")


def assert_outcome_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data["client_id"]))
    assert data["kind"] in ("BASELINE", "FOLLOW_UP")
    assert isinstance(data["task_score"], int) and 0 <= data["task_score"] <= 100
    assert isinstance(data["satisfaction_score"], int) and 0 <= data["satisfaction_score"] <= 100
    assert isinstance(data["provisional_composite"], int)
    assert data["status"] in ("DRAFT", "SCORED")


def assert_model_counter_invariants(model: dict):
    """Catalog counter conservation: in_stock never exceeds total; both non-negative."""
    assert model["in_stock_count"] >= 0, "in_stock_count must be non-negative"
    assert model["total_count"] >= model["in_stock_count"], "total_count must cover in_stock_count"


def assert_funding_reconciliation(auth: dict, submitted_provisional_sum: int, paid_payer_sum: int):
    """Ledger invariant: remaining == authorized - reserved(SUBMITTED) - paid(PAID payer share)."""
    expected = auth["authorized_amount_cents"] - submitted_provisional_sum - paid_payer_sum
    assert auth["remaining_amount_cents"] == expected, (
        f"remaining {auth['remaining_amount_cents']} != authorized {auth['authorized_amount_cents']} "
        f"- submitted {submitted_provisional_sum} - paid {paid_payer_sum}"
    )

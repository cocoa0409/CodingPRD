"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_program(data: dict):
    _assert_common(data, "Program")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["fiscal_year"], str)
    assert isinstance(data["budget_total_cents"], int)
    assert isinstance(data["target_meter_count"], int)
    assert isinstance(data["rate_per_ccf_cents"], int)
    assert isinstance(data["default_unit_allowance_cents"], int)
    assert isinstance(data["notice_days"], int)
    assert isinstance(data["budget_committed_cents"], int)
    assert isinstance(data["budget_spent_cents"], int)
    assert isinstance(data["budget_available_cents"], int)
    assert data["budget_posture"] in ["FUNDED", "TIGHT", "OVERRUN"]
    assert isinstance(data["completed_meter_count"], int)
    assert data["status"] in ["PLANNING", "ACTIVE", "CLOSING", "CLOSED"]


def assert_program_budget_invariants(data: dict):
    """Budget identity that must hold on every program read."""
    assert data["budget_available_cents"] == (
        data["budget_total_cents"] - data["budget_committed_cents"] - data["budget_spent_cents"]
    ), (
        f"budget identity broken: available {data['budget_available_cents']} != "
        f"total {data['budget_total_cents']} - committed {data['budget_committed_cents']} "
        f"- spent {data['budget_spent_cents']}"
    )


def assert_contractor(data: dict):
    _assert_common(data, "Contractor")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["crew_capacity_per_window"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["quality_score_bp"], int)
    assert 0 <= data["quality_score_bp"] <= 10000
    assert isinstance(data["audits_failed_count"], int)
    assert isinstance(data["installs_completed_count"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_account(data: dict):
    _assert_common(data, "ServiceAccount")
    assert isinstance(data["account_number"], str)
    assert isinstance(data["service_address"], str)
    assert data["meter_location"] in ["INSIDE", "OUTSIDE"]
    assert isinstance(data["customer_name"], str)
    assert isinstance(data["customer_phone"], str)
    assert data["priority_tier"] in ["STANDARD", "SENSITIVE", "CRITICAL"]
    assert isinstance(data["avg_daily_usage_ccf"], (int, float))
    assert isinstance(data["last_billed_read_value"], int)
    assert is_iso8601_timestamp(data["last_billed_read_at"])
    assert data["status"] in ["ELIGIBLE", "IN_PROGRAM", "REPLACED", "EXEMPTED"]


def assert_meter(data: dict):
    _assert_common(data, "Meter")
    assert isinstance(data["serial_number"], str)
    assert data["size_code"] in ["S_5_8", "S_3_4", "S_1", "S_1_5", "S_2"]
    assert data["technology"] in ["LEGACY", "AMI"]
    assert data.get("service_account_id") is None or is_valid_uuid(data["service_account_id"])
    assert data["status"] in [
        "IN_STOCK", "INSTALLED", "REMOVED", "BENCH_PASSED",
        "BENCH_FAILED", "DISPOSED", "RETURNED_TO_VENDOR",
    ]


def assert_wave(data: dict):
    _assert_common(data, "Wave")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["wave_number"], int)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["committed_count"], int)
    assert isinstance(data["completed_count"], int)
    assert data["status"] in ["DRAFT", "OPEN", "LOCKED", "COMPLETE", "CANCELLED"]


def assert_work_order(data: dict):
    _assert_common(data, "WorkOrder")
    assert isinstance(data["wave_id"], str)
    assert isinstance(data["service_account_id"], str)
    assert data.get("contractor_id") is None or isinstance(data["contractor_id"], str)
    assert data.get("old_meter_id") is None or isinstance(data["old_meter_id"], str)
    assert data.get("new_meter_id") is None or isinstance(data["new_meter_id"], str)
    assert isinstance(data["committed_amount_cents"], int)
    assert isinstance(data["no_access_strikes"], int)
    assert data["lifecycle_status"] in [
        "CREATED", "NOTIFIED", "SCHEDULED", "ACCESS_FAILED", "SWAPPED", "RECONCILED",
        "AMI_VERIFIED", "QA_REVIEW", "QA_FAILED", "CLOSED", "CANCELLED",
    ]
    assert data["hold_status"] in ["CLEAR", "ON_HOLD"]


def assert_notification(data: dict):
    _assert_common(data, "CustomerNotification")
    assert isinstance(data["work_order_id"], str)
    assert data.get("no_access_case_id") is None or isinstance(data["no_access_case_id"], str)
    assert data["channel"] in ["USPS_MAIL", "CERTIFIED_MAIL", "DOOR_HANGER", "PHONE", "EMAIL"]
    assert data["status"] in ["SENT", "DELIVERED", "FAILED", "RETURNED"]


def assert_appointment(data: dict):
    _assert_common(data, "Appointment")
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["contractor_id"], str)
    assert isinstance(data["slot_date"], str)
    assert data["window"] in ["AM", "PM", "EVE"]
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert data["status"] in [
        "BOOKED", "CONFIRMED", "COMPLETED", "NO_ACCESS",
        "CANCELLED_BY_CUSTOMER", "SUPERSEDED",
    ]


def assert_no_access_case(data: dict):
    _assert_common(data, "NoAccessCase")
    assert isinstance(data["work_order_id"], str)
    assert data["stage"] in [
        "STAGE_1_DOOR_HANGER", "STAGE_2_CERTIFIED_MAIL",
        "STAGE_3_PHONE_CAMPAIGN", "STAGE_4_FIELD_VISIT",
    ]
    assert isinstance(data["strikes_at_open"], int)
    assert data["status"] in ["OPEN", "RESOLVED"]
    assert data.get("resolution") in [None, "ACCESS_GAINED", "ACCOUNT_EXEMPTED", "FORCED_ENTRY"]


def assert_meter_reading(data: dict):
    """Append-only reading: carries id + created_at but no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "MeterReading.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "MeterReading.created_at must be ISO 8601"
    assert "updated_at" not in data, "MeterReading must not carry updated_at (append-only)"
    assert "version" not in data, "MeterReading must not carry version (append-only)"
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["meter_id"], str)
    assert data["read_type"] in ["FINAL", "INITIAL", "VERIFICATION", "ESTIMATED"]
    assert isinstance(data["value"], int) and data["value"] >= 0
    assert data["source"] in ["FIELD_CREW", "AMI_NETWORK", "CUSTOMER", "SYSTEM_ESTIMATE"]


def assert_endpoint_registration(data: dict):
    _assert_common(data, "EndpointRegistration")
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["meter_id"], str)
    assert isinstance(data["endpoint_serial"], str)
    assert isinstance(data["reads_received_count"], int)
    assert isinstance(data["rssi_sum_dbm"], int)
    assert data["status"] in ["REGISTERED", "COMM_VERIFIED", "COMM_FAILED", "REPLACED"]


def assert_bench_test(data: dict):
    _assert_common(data, "BenchTest")
    assert isinstance(data["meter_id"], str)
    assert isinstance(data["measured_low_ccf"], (int, float))
    assert isinstance(data["measured_mid_ccf"], (int, float))
    assert isinstance(data["measured_high_ccf"], (int, float))
    assert isinstance(data["accuracy_low_pct"], (int, float))
    assert isinstance(data["accuracy_mid_pct"], (int, float))
    assert isinstance(data["accuracy_high_pct"], (int, float))
    assert isinstance(data["weighted_accuracy_pct"], (int, float))
    assert data["result"] in ["PASS", "FAIL"]


def assert_complaint(data: dict):
    _assert_common(data, "HighBillComplaint")
    assert isinstance(data["service_account_id"], str)
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["claimed_bill_cents"], int)
    assert isinstance(data["baseline_bill_cents"], int)
    assert isinstance(data["variance_pct"], (int, float))
    assert data.get("bench_test_id") is None or isinstance(data["bench_test_id"], str)
    assert data.get("adjustment_cents") is None or isinstance(data["adjustment_cents"], int)
    assert data.get("adjudication_variant") in [None, "REGISTRATION_ERROR", "GOODWILL_TIERED"]
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "BENCH_TEST_ORDERED",
        "ADJUSTED", "DENIED", "WITHDRAWN",
    ]


def assert_quality_audit(data: dict):
    _assert_common(data, "QualityAudit")
    assert isinstance(data["work_order_id"], str)
    assert isinstance(data["contractor_id"], str)
    assert data["audit_type"] in ["SAMPLED", "FOR_CAUSE"]
    assert data["result_status"] in ["PENDING", "PASS", "FAIL"]


def assert_invoice(data: dict):
    _assert_common(data, "ContractorInvoice")
    assert isinstance(data["contractor_id"], str)
    assert isinstance(data["program_id"], str)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "DISPUTED"]


def assert_invoice_settlement_invariants(data: dict):
    """net = gross + bonus - penalty - retainage on a submitted/approved invoice."""
    if data["status"] in ["SUBMITTED", "APPROVED", "DISPUTED"]:
        assert data["net_amount_cents"] == (
            data["gross_amount_cents"] + data["bonus_cents"]
            - data["penalty_cents"] - data["retainage_cents"]
        ), f"settlement identity broken: net {data['net_amount_cents']}"

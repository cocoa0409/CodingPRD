"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data, entity_name):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity_name}.version must be int >= 1"


def assert_school_year(data):
    _assert_common_fields(data, "SchoolYear")
    assert isinstance(data["label"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["refund_full_days"], int)
    assert isinstance(data["refund_partial_days"], int)
    assert isinstance(data["partial_refund_pct_bp"], int)
    assert isinstance(data["payment_plan_min_cents"], int)
    assert isinstance(data["payment_plan_max_installments"], int)
    assert isinstance(data["writeoff_max_cents"], int)
    assert isinstance(data["aging_interval_days"], int)
    assert isinstance(data["graduation_hold_threshold_cents"], int)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")


def assert_student(data):
    _assert_common_fields(data, "Student")
    assert isinstance(data["external_ref"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["grade_level"], int)
    assert isinstance(data["family_id"], str)
    assert data["status"] in ("ENROLLED", "WITHDRAWN", "GRADUATED")


def assert_student_account(data):
    _assert_common_fields(data, "StudentAccount")
    assert is_valid_uuid(data.get("school_year_id", "")), "school_year_id must be a UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    for f in ("assessed_cents", "waived_cents", "paid_cents", "balance_cents", "family_balance_cents"):
        assert isinstance(data[f], int), f"StudentAccount.{f} must be int"
    assert data["posture"] in ("CLEAR", "GRADUATION_HOLD", "COLLECTIONS", "WRITTEN_OFF")


def assert_department(data):
    _assert_common_fields(data, "Department")
    assert isinstance(data["code"], str)
    assert isinstance(data["name"], str)
    for f in ("distributed_cents", "reconciled_cents", "unreconciled_cents"):
        assert isinstance(data[f], int), f"Department.{f} must be int"


def assert_offering(data):
    _assert_common_fields(data, "Offering")
    assert data["kind"] in ("COURSE", "ACTIVITY")
    assert isinstance(data["title"], str)
    assert isinstance(data["capacity"], int)
    assert data["status"] in ("SCHEDULED", "IN_SESSION", "COMPLETED", "CANCELLED")


def assert_fee_catalog_item(data):
    _assert_common_fields(data, "FeeCatalogItem")
    assert isinstance(data["name"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_optional_purchase_item(data):
    _assert_common_fields(data, "OptionalPurchaseItem")
    assert isinstance(data["name"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["inventory_cap"], int)
    assert isinstance(data["sold_count"], int)


def assert_enrollment(data):
    _assert_common_fields(data, "Enrollment")
    assert data["status"] in ("ACTIVE", "WITHDRAWN", "COMPLETED", "DROPPED_BY_CANCELLATION")


def assert_fee_assessment(data):
    _assert_common_fields(data, "FeeAssessment")
    assert isinstance(data["assessed_amount_cents"], int)
    assert isinstance(data["waived_amount_cents"], int)
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert data["status"] in ("ASSESSED", "PARTIALLY_PAID", "PAID", "PAYMENT_PLAN",
                              "DELINQUENT", "REFUNDED", "WAIVED", "VOID")


def assert_purchase(data):
    _assert_common_fields(data, "Purchase")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "COMPLETED", "REFUNDED", "VOID")


def assert_waiver_program(data):
    _assert_common_fields(data, "WaiverProgram")
    assert isinstance(data["waiver_pct_bp"], int)
    assert isinstance(data["stacking_priority"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_waiver_application(data):
    _assert_common_fields(data, "WaiverApplication")
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "REVOKED")


def assert_payment(data):
    _assert_common_fields(data, "Payment")
    assert isinstance(data["amount_cents"], int)
    assert data["method"] in ("CARD", "ACH", "CASH", "CHECK")
    assert data["status"] in ("PENDING", "SUCCEEDED", "FAILED", "VOIDED")


def assert_payment_allocation(data):
    # Immutable ledger row: id + created_at only; NO updated_at/version (PRD §2.5)
    assert is_valid_uuid(data.get("id", "")), "PaymentAllocation.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "PaymentAllocation.created_at must be ISO 8601"
    assert "updated_at" not in data, "PaymentAllocation must not carry updated_at"
    assert "version" not in data, "PaymentAllocation must not carry version"
    assert isinstance(data["allocated_cents"], int)
    assert data["allocation_rule"] in ("INSTALLMENT_DUE", "OLDEST_OUTSTANDING")


def assert_payment_plan(data):
    _assert_common_fields(data, "PaymentPlan")
    assert isinstance(data["installment_count"], int)
    assert isinstance(data["covered_amount_cents"], int)
    assert isinstance(data["installment_amount_cents"], int)
    assert data["status"] in ("ACTIVE", "COMPLETED", "DEFAULTED", "CANCELLED")


def assert_installment(data):
    _assert_common_fields(data, "PaymentPlanInstallment")
    assert isinstance(data["sequence"], int)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["status"] in ("SCHEDULED", "DUE", "PAID", "PAST_DUE", "WAIVED_BY_DEFAULT")


def assert_refund(data):
    _assert_common_fields(data, "Refund")
    assert data["reason"] in ("WITHDRAWAL", "ACTIVITY_CANCELLATION",
                              "OVERPAYMENT_RETURN", "WRITE_OFF_REVERSAL")
    assert isinstance(data["refund_cents"], int)
    assert data["status"] in ("PENDING", "EXECUTED", "DENIED")


def assert_ledger_entry(data):
    # Immutable ledger row: id + created_at only; NO updated_at/version (PRD §2.5)
    assert is_valid_uuid(data.get("id", "")), "LedgerEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "LedgerEntry.created_at must be ISO 8601"
    assert "updated_at" not in data, "LedgerEntry must not carry updated_at"
    assert "version" not in data, "LedgerEntry must not carry version"
    assert data["entry_type"] in ("DISTRIBUTION_CREDIT", "DISTRIBUTION_REVERSAL",
                                  "WRITE_OFF_DEBIT", "WRITE_OFF_REVERSAL")
    assert isinstance(data["amount_cents"], int)


def assert_reconciliation_run(data):
    _assert_common_fields(data, "ReconciliationRun")
    assert isinstance(data["entries_reconciled"], int)
    assert isinstance(data["drift_detected"], bool)
    assert data["status"] == "COMPLETED"


def assert_collections_case(data):
    _assert_common_fields(data, "CollectionsCase")
    assert isinstance(data["principal_cents"], int)
    assert data["aging_bucket"] in ("CURRENT", "BUCKET_1", "BUCKET_2", "BUCKET_3")
    assert isinstance(data["written_off_cents"], int)
    assert isinstance(data["approved_writeoff_cents"], int)
    assert data["status"] in ("OPEN", "PAYMENT_PROMISED", "RESOLVED", "WRITTEN_OFF")


def assert_account_invariants(data):
    """Account decomposition invariant: balance == assessed - waived - paid (PRD §3.2)."""
    assert data["balance_cents"] == data["assessed_cents"] - data["waived_cents"] - data["paid_cents"], (
        f"balance_cents {data['balance_cents']} != assessed {data['assessed_cents']} "
        f"- waived {data['waived_cents']} - paid {data['paid_cents']}"
    )

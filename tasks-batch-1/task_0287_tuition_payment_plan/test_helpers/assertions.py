"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_institution(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["currency"], str) and len(data["currency"]) > 0
    assert data["refund_policy"] in ["DATE_BASED", "SCHEDULE_BASED"]


def assert_term(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["status"] in ["OPEN", "LOCKED", "CLOSED"]


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["external_ref"], str) and len(data["external_ref"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["has_active_hold"], bool)


def assert_plan_template(data: dict):
    _assert_common(data)
    assert isinstance(data["installment_count"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "ACTIVE", "COMPLETED", "WITHDRAWN"]
    for f in (
        "gross_charges_cents",
        "total_aid_cents",
        "net_after_aid_cents",
        "scheduled_balance_cents",
        "paid_principal_cents",
        "late_fee_balance_cents",
        "delinquent_installment_count",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_installment(data: dict):
    _assert_common(data)
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)
    assert data["status"] in ["SCHEDULED", "OVERDUE", "PAID"]


def assert_charge(data: dict):
    _assert_common(data)
    assert data["kind"] in ["TUITION", "FEE", "HOUSING"]
    assert data["status"] in ["POSTED", "REVERSED"]


def assert_aid(data: dict):
    _assert_common(data)
    assert data["source"] in ["GRANT", "SCHOLARSHIP", "LOAN"]
    assert data["status"] in ["APPLIED", "CANCELLED"]


def assert_payment(data: dict):
    _assert_common(data)
    assert data["purpose"] in ["DOWN_PAYMENT", "INSTALLMENT", "AUTOPAY"]
    assert data["status"] in ["PENDING", "SETTLED", "FAILED"]


def assert_late_fee(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["ASSESSED", "WAIVED"]


def assert_hold(data: dict):
    _assert_common(data)
    assert data["reason"] in ["DELINQUENCY_COUNT", "DELINQUENCY_AMOUNT"]
    assert data["status"] in ["ACTIVE", "RELEASED"]


def assert_withdrawal(data: dict):
    _assert_common(data)
    assert data["variant_used"] in ["DATE_BASED", "SCHEDULE_BASED"]
    assert isinstance(data["retained_charges_cents"], int)
    assert isinstance(data["net_owed_after_withdrawal_cents"], int)
    assert isinstance(data["refund_to_student_cents"], int)


def assert_principal_identity(enrollment: dict):
    """PRD Section 2.9 / 3.6: scheduled_balance + paid_principal == net_after_aid
    while the plan is being serviced (no overdue-but-unpaid leakage)."""
    lhs = enrollment["scheduled_balance_cents"] + enrollment["paid_principal_cents"]
    assert lhs == enrollment["net_after_aid_cents"], (
        f"principal identity broken: scheduled {enrollment['scheduled_balance_cents']} + "
        f"paid {enrollment['paid_principal_cents']} != net {enrollment['net_after_aid_cents']}"
    )

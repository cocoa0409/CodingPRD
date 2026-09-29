"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COURSE_STATUSES = ["ACTIVE", "RETIRED"]
OFFERING_STATUSES = [
    "DRAFT", "OPEN", "WAITLIST_ONLY", "CENSUS_LOCKED", "COMPLETED", "CANCELLED",
]
ENROLLMENT_STATUSES = [
    "PENDING", "ENROLLED", "WAITLISTED", "WITHDRAWN",
    "TRANSFERRED_OUT", "COMPLETED", "NO_SHOW",
]
PAYMENT_STATUSES = [
    "UNPAID", "VOUCHER_COMMITTED", "PAID", "PARTIALLY_REFUNDED", "REFUNDED",
]
VOUCHER_STATUSES = [
    "ISSUED", "ASSIGNED", "PARTIALLY_REDEEMED", "EXHAUSTED", "VOIDED",
]
CONTRACT_STATUSES = [
    "OFFERED", "SIGNED", "ACTIVE", "SETTLED", "DECLINED", "TERMINATED_NO_FAULT",
]
PETITION_STATUSES = [
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "DENIED",
]
REQUEST_STATUSES = [
    "SUBMITTED", "REFUND_APPROVED", "TRANSFER_APPROVED", "DENIED", "SETTLED",
]
LOYALTY_TIERS = ["NEW", "RETURNING", "LOYAL", "CHAMPION"]
SEGMENTS = ["PROSPECT", "FIRST_TIME", "REPEAT", "CORPORATE_SPONSORED", "LAPSED"]


def _assert_identity(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be an integer >= 1, got {data.get('version')!r}"
        )


def assert_course(data: dict):
    _assert_identity(data)
    assert isinstance(data["course_code"], str) and 1 <= len(data["course_code"]) <= 32
    assert isinstance(data["title"], str)
    assert data["status"] in COURSE_STATUSES
    assert data["delivery_mode"] in ["IN_PERSON", "ONLINE_SYNC", "ONLINE_ASYNC"]
    assert data["ceu_units"] > 0 and data["ceu_units"] <= 10.0
    assert data["contact_hours"] > 0
    assert data["list_price_cents"] >= 0
    assert data["cpl_credit_units"] > 0
    assert isinstance(data["active_offering_count"], int)
    assert data["active_offering_count"] >= 0


def assert_offering(data: dict):
    _assert_identity(data)
    assert data["status"] in OFFERING_STATUSES
    assert data["scheduling_mode"] in ["TERM", "ROLLING"]
    assert data["session_count"] >= 1
    assert data["min_enrollment"] >= 1
    assert data["max_enrollment"] >= data["min_enrollment"]
    assert data["tuition_cents"] >= 0
    assert data["end_date"] > data["start_date"]
    assert data["census_at"] <= data["start_date"]
    for counter in (
        "confirmed_enrollment_count", "paid_enrollment_count", "waitlist_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert isinstance(data["net_program_revenue_cents"], int)
    if data["status"] != "CANCELLED":
        assert data["cancellation_reason"] is None, (
            "cancellation_reason is null for any offering that is not CANCELLED"
        )


def assert_learner(data: dict):
    _assert_identity(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str)
    assert data["marketing_status"] in ["SUBSCRIBED", "UNSUBSCRIBED"]
    assert data["loyalty_tier"] in LOYALTY_TIERS
    assert isinstance(data["lifetime_completed_count"], int)
    assert data["lifetime_completed_count"] >= 0
    assert data["lifetime_ceu_total"] >= 0


def assert_instructor(data: dict):
    _assert_identity(data)
    assert data["credential_level"] in ["ADJUNCT", "SENIOR", "MASTER"]
    assert isinstance(data["active_contract_count"], int)
    assert data["active_contract_count"] >= 0


def assert_corporate_account(data: dict):
    _assert_identity(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    for bucket in (
        "funded_cents", "available_cents", "unallocated_voucher_cents",
        "committed_cents", "consumed_cents",
    ):
        assert isinstance(data[bucket], int), f"{bucket} must be whole cents"
        assert data[bucket] >= 0, f"{bucket} must not go negative"
    assert_sponsor_ledger_conserved(data)


def assert_sponsor_ledger_conserved(account: dict):
    """funded_cents equals available + unallocated + committed + consumed at all times."""
    total = (
        account["available_cents"]
        + account["unallocated_voucher_cents"]
        + account["committed_cents"]
        + account["consumed_cents"]
    )
    assert account["funded_cents"] == total, (
        f"Sponsor ledger identity broken: funded_cents {account['funded_cents']} != "
        f"available {account['available_cents']} + unallocated "
        f"{account['unallocated_voucher_cents']} + committed {account['committed_cents']} "
        f"+ consumed {account['consumed_cents']} = {total}"
    )


def assert_voucher(data: dict):
    _assert_identity(data)
    assert data["status"] in VOUCHER_STATUSES
    assert data["face_value_cents"] > 0
    for bucket in ("remaining_cents", "committed_cents", "consumed_cents"):
        assert isinstance(data[bucket], int) and data[bucket] >= 0
    if data["status"] != "VOIDED":
        assert_voucher_value_conserved(data)


def assert_voucher_value_conserved(voucher: dict):
    """face_value_cents always equals remaining + committed + consumed."""
    total = (
        voucher["remaining_cents"] + voucher["committed_cents"] + voucher["consumed_cents"]
    )
    assert voucher["face_value_cents"] == total, (
        f"Voucher value identity broken: face_value_cents {voucher['face_value_cents']} != "
        f"remaining {voucher['remaining_cents']} + committed {voucher['committed_cents']} "
        f"+ consumed {voucher['consumed_cents']} = {total}"
    )


def assert_registration(data: dict):
    _assert_identity(data)
    assert data["enrollment_status"] in ENROLLMENT_STATUSES
    assert data["payment_status"] in PAYMENT_STATUSES
    for field in (
        "list_tuition_cents", "loyalty_discount_cents", "processing_fee_cents",
        "total_due_cents", "amount_paid_cents", "amount_refunded_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"
    assert data["total_sessions"] >= 1
    assert data["sessions_attended"] >= 0
    assert (
        data["total_due_cents"]
        == data["list_tuition_cents"] - data["loyalty_discount_cents"] + data["processing_fee_cents"]
    ), "total_due_cents is the subtotal plus processing_fee_cents"


def assert_instructor_contract(data: dict):
    _assert_identity(data)
    assert data["status"] in CONTRACT_STATUSES
    assert data["pay_basis"] in ["CENSUS_LOCKED", "FINAL_COMPLETION"]
    for field in ("base_stipend_cents", "per_enrollment_cents", "enrollment_cap_for_pay"):
        assert data[field] >= 0


def assert_completion_record(data: dict):
    _assert_identity(data)
    assert data["status"] in ["ISSUED", "REVOKED"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert data["ceu_awarded"] > 0
    assert 0 <= data["attendance_ratio"] <= 1
    assert isinstance(data["certificate_number"], str)
    assert data["certificate_number"].startswith("CEU-")


def assert_certificate_number(record: dict, term_code, sequence: int):
    """Certificate identifiers read CEU-{term_code or ROLL}-{4-digit sequence}."""
    middle = term_code if term_code else "ROLL"
    expected = f"CEU-{middle}-{sequence:04d}"
    assert record["certificate_number"] == expected, (
        f"Expected certificate_number {expected}, got {record['certificate_number']}"
    )


def assert_petition(data: dict):
    _assert_identity(data)
    assert data["status"] in PETITION_STATUSES
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_citation(data: dict):
    """Citations carry only id and created_at: no updated_at and no version."""
    _assert_identity(data, versioned=False)
    assert "updated_at" not in data, "a citation has no updated_at field"
    assert "version" not in data, "a citation has no version field"
    assert data["weight"] > 0 and data["weight"] <= 1.0


def assert_refund_transfer_request(data: dict):
    _assert_identity(data)
    assert data["status"] in REQUEST_STATUSES
    assert data["request_type"] in ["REFUND", "TRANSFER"]
    assert data["refund_basis"] in ["POLICY_SCHEDULE", "PRO_RATA_ATTENDANCE"]
    assert isinstance(data["days_before_start"], int)
    assert isinstance(data["computed_refund_cents"], int)


def assert_marketing_membership(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["segment"] in SEGMENTS
    assert data["state"] in ["ACTIVE", "REMOVED"]
    assert is_iso8601_timestamp(data["recomputed_at"])


def memberships_by_segment(rows: list) -> dict:
    """Collapse a marketing membership listing into {segment: state}."""
    return {row["segment"]: row["state"] for row in rows}


def assert_learner_ceu_ledger(learner: dict, issued_records: list):
    """lifetime_ceu_total equals the sum of ceu_awarded over ISSUED records."""
    expected_count = len(issued_records)
    expected_total = round(sum(r["ceu_awarded"] for r in issued_records), 1)
    assert learner["lifetime_completed_count"] == expected_count, (
        f"lifetime_completed_count {learner['lifetime_completed_count']} != "
        f"{expected_count} issued completion records"
    )
    assert abs(learner["lifetime_ceu_total"] - expected_total) < 1e-9, (
        f"lifetime_ceu_total {learner['lifetime_ceu_total']} != {expected_total}"
    )

"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), \
        f"{label}.version must be an integer"


def _assert_immutable_fields(data: dict, label: str):
    """Scheduled breaks and account entries carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{label} must not expose updated_at"
    assert "version" not in data, f"{label} must not expose version"


def assert_academic_term(data: dict):
    _assert_common_fields(data, "AcademicTerm")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["attendance_taking_required"], bool)
    assert data["refund_method"] in ("TIERED", "PRO_RATA")
    assert isinstance(data["calendar_days"], int)
    assert isinstance(data["deductible_break_days"], int)
    assert isinstance(data["total_days"], int)
    assert data["calendar_days"] >= 1
    assert 0 <= data["deductible_break_days"] <= data["calendar_days"]
    assert data["total_days"] == \
        data["calendar_days"] - data["deductible_break_days"]


def assert_scheduled_break(data: dict):
    _assert_immutable_fields(data, "ScheduledBreak")
    assert is_valid_uuid(data.get("term_id", ""))
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["length_days"], int) and data["length_days"] >= 1
    assert isinstance(data["deductible_days"], int) and \
        data["deductible_days"] >= 0


def assert_student(data: dict):
    _assert_common_fields(data, "Student")
    assert isinstance(data["external_ref"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_enrollment(data: dict):
    _assert_common_fields(data, "Enrollment")
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    assert isinstance(data["institutional_charges_cents"], int)
    assert data["institutional_charges_cents"] >= 0
    assert data["status"] in ("ENROLLED", "WITHDRAWN", "COMPLETED")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["balance_notification_sent"], bool)
    assert data.get("balance_notified_at") is None or \
        is_iso8601_timestamp(data["balance_notified_at"])
    assert data.get("current_withdrawal_case_id") is None or \
        is_valid_uuid(data["current_withdrawal_case_id"])


def assert_aid_award(data: dict):
    _assert_common_fields(data, "AidAward")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["program"] in ("PELL_GRANT", "SUBSIDIZED_LOAN",
                               "UNSUBSIDIZED_LOAN", "PLUS_LOAN")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["is_grant"], bool)
    assert data["is_grant"] == (data["program"] == "PELL_GRANT")
    assert data["status"] in ("OFFERED", "ACCEPTED", "CANCELLED")
    assert isinstance(data["disbursed_amount_cents"], int)
    assert isinstance(data["scheduled_amount_cents"], int)


def assert_aid_disbursement(data: dict):
    _assert_common_fields(data, "AidDisbursement")
    assert is_valid_uuid(data.get("award_id", ""))
    assert data.get("pwd_offer_id") is None or \
        is_valid_uuid(data["pwd_offer_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("SCHEDULED", "DISBURSED", "CANCELLED")
    if data["status"] == "DISBURSED":
        assert isinstance(data.get("disbursed_on"), str) and \
            data["disbursed_on"]
    else:
        assert data.get("disbursed_on") is None


def assert_withdrawal_case(data: dict):
    _assert_common_fields(data, "WithdrawalCase")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["withdrawal_type"] in ("OFFICIAL", "UNOFFICIAL")
    assert isinstance(data["withdrawal_date"], str)
    assert isinstance(data["determination_date"], str)
    assert isinstance(data["total_days"], int) and data["total_days"] >= 1
    assert isinstance(data["completed_days"], int) and \
        0 <= data["completed_days"] <= data["total_days"]
    assert isinstance(data["percentage_completed"], (int, float))
    assert isinstance(data["earned_pct"], (int, float))
    assert data["status"] in ("OPEN", "CALCULATED", "CLOSED", "CANCELLED")
    if data["status"] in ("CALCULATED", "CLOSED"):
        for field in ("aid_disbursable_cents", "aid_disbursed_cents",
                      "aid_earned_cents", "aid_unearned_cents"):
            assert isinstance(data.get(field), int), \
                f"WithdrawalCase.{field} must be an integer once calculated"


def assert_return_obligation(data: dict):
    _assert_common_fields(data, "ReturnObligation")
    assert is_valid_uuid(data.get("withdrawal_case_id", ""))
    assert data["party"] in ("SCHOOL", "STUDENT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["due_date"], str)
    assert data["status"] in ("PENDING", "OVERDUE", "RETURNED", "VOIDED")


def assert_post_withdrawal_offer(data: dict):
    _assert_common_fields(data, "PostWithdrawalOffer")
    assert is_valid_uuid(data.get("withdrawal_case_id", ""))
    assert is_valid_uuid(data.get("award_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data.get("offered_at", ""))
    assert isinstance(data["response_deadline"], str)
    assert isinstance(data["late_offer"], bool)
    assert data["status"] in ("SENT", "ACCEPTED", "DECLINED", "EXPIRED",
                              "VOIDED")


def assert_student_account_entry(data: dict):
    _assert_immutable_fields(data, "StudentAccountEntry")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["entry_type"] in ("CHARGE", "REFUND_CREDIT",
                                  "R2T4_CHARGEBACK", "AID_CREDIT", "PAYMENT",
                                  "REVERSAL")
    assert isinstance(data["amount_cents"], int)
    if data["entry_type"] in ("CHARGE", "R2T4_CHARGEBACK"):
        assert data["amount_cents"] > 0
    elif data["entry_type"] in ("REFUND_CREDIT", "AID_CREDIT", "PAYMENT"):
        assert data["amount_cents"] < 0
    if data["entry_type"] == "REVERSAL":
        assert is_valid_uuid(data.get("reversal_of_entry_id", ""))
    assert "source_ref" in data
    assert is_iso8601_timestamp(data.get("posted_at", ""))

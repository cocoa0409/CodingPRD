"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

MEMBERSHIP_STATUSES = ["PENDING_PAYMENT", "ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED"]
PANEL_BUCKETS = ["UNDER_TARGET", "AT_TARGET", "FULL"]
SEAT_STATUSES = ["OPEN", "OCCUPIED", "RELEASED"]
SLOT_STATES = ["OPEN", "FULL"]
CLINICAL_STATUSES = ["BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"]
BILLING_STATUSES = ["NOT_BILLABLE", "BILLABLE", "INVOICED", "WRITTEN_OFF"]
PLAN_STATUSES = ["DRAFT", "ACTIVE", "UNDER_REVISION", "ARCHIVED"]
REFERRAL_STATUSES = ["REQUESTED", "AUTHORIZED", "SENT", "DENIED", "EXPIRED"]
THREAD_STATUSES = ["OPEN", "ANSWERED", "ESCALATED", "CLOSED"]
INVOICE_STATUSES = ["ISSUED", "PAID", "VOID"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_practice(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["panel_target"], int) and data["panel_target"] > 0
    assert isinstance(data["panel_hard_cap"], int)
    assert data["panel_hard_cap"] >= data["panel_target"]
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] > 0
    assert isinstance(data["dpc_covered_service_codes"], list)


def assert_provider(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["practice_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["active_panel_count"], int) and data["active_panel_count"] >= 0
    assert data["panel_load_bucket"] in PANEL_BUCKETS


def assert_employer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["practice_id"])
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["sponsored_seat_limit"], int) and data["sponsored_seat_limit"] > 0
    assert isinstance(data["occupied_seat_count"], int) and data["occupied_seat_count"] >= 0


def assert_member(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["practice_id"])
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["plan_type"] in ["MONTHLY", "ANNUAL_PREPAID"]
    assert data["membership_status"] in MEMBERSHIP_STATUSES
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["plan_type"] in ["MONTHLY", "ANNUAL_PREPAID"]
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["member_share_cents"], int) and data["member_share_cents"] >= 0


def assert_employer_seat(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["employer_id"])
    assert data["seat_status"] in SEAT_STATUSES


def assert_visit_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["provider_id"])
    assert data["slot_type"] in ["IN_PERSON", "VIRTUAL"]
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert data["slot_state"] in SLOT_STATES


def assert_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["slot_id"])
    assert data["visit_type"] in ["SAME_DAY", "VIRTUAL", "ANNUAL_PHYSICAL"]
    assert data["clinical_status"] in CLINICAL_STATUSES
    assert data["billing_status"] in BILLING_STATUSES


def assert_care_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["plan_status"] in PLAN_STATUSES
    assert isinstance(data["goal_count"], int) and data["goal_count"] >= 0
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0


def assert_referral(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["specialty"], str) and len(data["specialty"]) > 0
    assert data["referral_status"] in REFERRAL_STATUSES


def assert_message_thread(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["priority"] in ["ROUTINE", "AFTER_HOURS"]
    assert data["thread_status"] in THREAD_STATUSES
    assert is_iso8601_timestamp(data["response_deadline"])


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["visit_id"])
    assert isinstance(data["gross_charge_cents"], int) and data["gross_charge_cents"] >= 0
    assert isinstance(data["member_responsibility_cents"], int)
    assert data["member_responsibility_cents"] >= 0
    assert data["invoice_status"] in INVOICE_STATUSES


def assert_payment(data: dict):
    """Payment is immutable: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["charge_kind"] in ["MEMBERSHIP_FEE", "INVOICE"]
    assert data["outcome"] in ["SUCCEEDED", "FAILED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0

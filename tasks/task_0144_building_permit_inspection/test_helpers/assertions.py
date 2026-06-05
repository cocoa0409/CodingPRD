"""Entity assertions and domain invariant checkers.

Each assert_{entity} checks the structural shape the PRD promises in a response
envelope's data payload. Leaner resources (FeePayment, PermitEvent) carry only
id + created_at per PRD §2.4 and MUST NOT be asserted to carry version/updated_at.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

PERMIT_STATUSES = [
    "SUBMITTED", "UNDER_REVIEW", "CORRECTIONS_REQUIRED", "APPROVED",
    "ISSUED", "EXPIRED", "FINALED", "WITHDRAWN",
]
WORK_STATUSES = ["NOT_STARTED", "ACTIVE", "STOPPED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_full_common(data: dict):
    """For resources carrying the full common-field set (PRD §2.4)."""
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_jurisdiction(data: dict):
    _assert_full_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["code_edition"], str)
    assert isinstance(data["valuation_fee_rate_per_1000"], (int, float))
    assert isinstance(data["square_foot_rate"], (int, float))
    assert isinstance(data["plan_review_fee_pct"], (int, float))
    assert isinstance(data["minimum_permit_fee"], (int, float))
    assert isinstance(data["renewal_fee_pct"], (int, float))
    assert isinstance(data["permit_valid_days"], int)


def assert_contractor(data: dict):
    _assert_full_common(data)
    assert isinstance(data["business_name"], str)
    assert isinstance(data["license_number"], str)
    assert data["license_status"] in ["ACTIVE", "SUSPENDED", "EXPIRED"]
    assert is_iso8601_timestamp(data["license_expiry"]), "license_expiry must be ISO 8601"
    assert isinstance(data["bond_amount"], (int, float))
    assert data["bond_status"] in ["VERIFIED", "UNVERIFIED", "REVOKED"]
    assert data["verification_status"] in ["VERIFIED", "FAILED"]


def assert_permit(data: dict):
    _assert_full_common(data)
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["contractor_id"], str)
    assert data["work_class"] in ["NEW_CONSTRUCTION", "ADDITION", "ALTERATION", "REPAIR"]
    assert data["fee_method"] in ["VALUATION", "SQUARE_FOOT"]
    assert data["status"] in PERMIT_STATUSES, f"unexpected status {data['status']!r}"
    assert data["work_status"] in WORK_STATUSES, f"unexpected work_status {data['work_status']!r}"
    for f in ("assessed_valuation", "base_permit_fee", "plan_review_fee",
              "total_permit_fee", "amount_paid", "balance_due", "accrued_renewal_fees"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert isinstance(data["open_correction_count"], int)
    assert isinstance(data["review_cycle"], int)


def assert_permit_fee_precision(data: dict):
    """Every monetary field is carried at 2dp (PRD §2.8)."""
    for f in ("assessed_valuation", "base_permit_fee", "plan_review_fee",
              "total_permit_fee", "amount_paid", "balance_due", "accrued_renewal_fees"):
        assert_cost_precision(data[f])


def assert_plan_review(data: dict):
    _assert_full_common(data)
    assert isinstance(data["permit_id"], str)
    assert isinstance(data["reviewer_id"], str)
    assert isinstance(data["cycle_number"], int)
    assert data["decision"] in ["PENDING", "APPROVED", "CORRECTIONS"]
    assert data["review_status"] in ["OPEN", "COMPLETED"]


def assert_correction_notice(data: dict):
    _assert_full_common(data)
    assert isinstance(data["plan_review_id"], str)
    assert isinstance(data["permit_id"], str)
    assert isinstance(data["code_section"], str)
    assert isinstance(data["description"], str)
    assert data["item_status"] in ["OPEN", "RESOLVED"]


def assert_inspector(data: dict):
    _assert_full_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["badge_number"], str)


def assert_plan_reviewer(data: dict):
    _assert_full_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["cert_number"], str)


def assert_inspection_slot(data: dict):
    _assert_full_common(data)
    assert isinstance(data["inspector_id"], str)
    assert is_iso8601_timestamp(data["window_start"]), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data["window_end"]), "window_end must be ISO 8601"
    assert isinstance(data["max_inspections"], int)
    assert isinstance(data["booked_count"], int)


def assert_inspection(data: dict):
    _assert_full_common(data)
    assert isinstance(data["permit_id"], str)
    assert isinstance(data["slot_id"], str)
    assert isinstance(data["inspector_id"], str)
    assert data["inspection_type"] in ["ROUGH", "FINAL"]
    assert data["inspection_status"] in ["SCHEDULED", "PASSED", "FAILED", "CANCELLED"]


def assert_stop_work_order(data: dict):
    _assert_full_common(data)
    assert isinstance(data["permit_id"], str)
    assert isinstance(data["reason"], str)
    assert data["order_status"] in ["ACTIVE", "LIFTED"]


def assert_certificate(data: dict):
    _assert_full_common(data)
    assert isinstance(data["permit_id"], str)
    assert data["co_type"] == "FINAL"
    assert data["co_status"] in ["ISSUED", "REVOKED"]


def assert_fee_payment(data: dict):
    """FeePayment is append-only: id + created_at only, no version/updated_at."""
    _assert_common(data)
    assert isinstance(data["permit_id"], str)
    assert isinstance(data["amount"], (int, float))
    assert data["payment_status"] in ["CLEARED", "VOID"]


def assert_permit_event(data: dict):
    """PermitEvent is an immutable audit record: id + created_at only."""
    _assert_common(data)
    assert isinstance(data["permit_id"], str)
    assert isinstance(data["event_type"], str)

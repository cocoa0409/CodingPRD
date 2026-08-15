"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """PRD §2.5: primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_school_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["site_status"] in ("ACTIVE", "CLOSED")
    assert isinstance(data["rental_timezone"], str) and data["rental_timezone"]


def assert_facility(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert isinstance(data["facility_code"], str) and data["facility_code"]
    assert data["facility_tier"] in ("STANDARD", "PREMIUM", "ATHLETIC")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["setup_buffer_minutes"], int) and data["setup_buffer_minutes"] >= 0
    assert isinstance(data["teardown_buffer_minutes"], int) and data["teardown_buffer_minutes"] >= 0
    assert isinstance(data["requires_custodian"], bool)
    assert data["facility_status"] in ("AVAILABLE", "MAINTENANCE_HOLD", "RETIRED")


def assert_renter_org(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert data["rate_class"] in ("INTERNAL", "NONPROFIT", "FOR_PROFIT")
    assert data["org_standing"] in ("GOOD_STANDING", "SUSPENDED", "BARRED")
    assert isinstance(data["credit_balance_cents"], int) and data["credit_balance_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int) and data["outstanding_balance_cents"] >= 0
    assert isinstance(data["forfeiture_count"], int) and data["forfeiture_count"] >= 0


def assert_rate_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_code"], str) and data["policy_code"]
    assert data["rate_class"] in ("INTERNAL", "NONPROFIT", "FOR_PROFIT")
    assert data["facility_tier"] in ("STANDARD", "PREMIUM", "ATHLETIC")
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert isinstance(data["deposit_basis_points"], int) and 0 <= data["deposit_basis_points"] <= 10000
    assert isinstance(data["deposit_floor_cents"], int)
    assert isinstance(data["custodial_hourly_cents"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["policy_status"] in ("ACTIVE", "SUPERSEDED")


def assert_calendar_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert data.get("facility_id") is None or is_valid_uuid(data["facility_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["event_priority_tier"] in (0, 1)
    assert data["event_status"] in ("SCHEDULED", "CANCELLED")


def assert_rental_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("renter_org_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["event_title"], str) and data["event_title"]
    assert isinstance(data["headcount_estimate"], int) and data["headcount_estimate"] >= 1
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["request_status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "RESUBMITTED",
        "APPROVED", "DENIED", "WAITLISTED", "WITHDRAWN", "EXPIRED",
    )
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 3
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])
    assert data.get("denial_reason_code") in (
        None, "CAPACITY", "CALENDAR_CONFLICT", "INSURANCE", "POLICY", "DISCRETIONARY",
    )


def assert_insurance_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("renter_org_id", ""))
    assert isinstance(data["insurer_name"], str) and data["insurer_name"]
    assert isinstance(data["per_occurrence_limit_cents"], int) and data["per_occurrence_limit_cents"] > 0
    assert isinstance(data["aggregate_limit_cents"], int)
    assert data["aggregate_limit_cents"] >= data["per_occurrence_limit_cents"]
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["cert_status"] in ("VALID", "EXPIRED", "REVOKED")


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("rental_request_id", ""))
    assert is_valid_uuid(data.get("renter_org_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_iso8601_timestamp(data["occupancy_start"])
    assert is_iso8601_timestamp(data["occupancy_end"])
    assert is_iso8601_timestamp(data["blocked_start"])
    assert is_iso8601_timestamp(data["blocked_end"])
    assert data["lifecycle_status"] in (
        "ISSUED", "ACTIVE", "COMPLETED", "CANCELLED", "EXPIRED", "SUPERSEDED",
    )
    assert data["financial_status"] in (
        "DEPOSIT_PENDING", "SECURED", "INVOICED", "SETTLED",
        "REFUND_PENDING", "REFUNDED", "FORFEIT_PENDING", "FORFEITED",
    )
    assert isinstance(data["deposit_required_cents"], int) and data["deposit_required_cents"] >= 0
    assert isinstance(data["deposit_held_cents"], int) and data["deposit_held_cents"] >= 0
    assert data.get("seasonal_permit_id") is None or is_valid_uuid(data["seasonal_permit_id"])
    assert data.get("superseded_by_permit_id") is None or is_valid_uuid(data["superseded_by_permit_id"])


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("permit_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["estimated_hours"], (int, float))
    assert data.get("actual_hours") is None or data["actual_hours"] > 0
    assert isinstance(data["after_hours_flag"], bool)
    assert isinstance(data["weekend_flag"], bool)
    assert data["wo_status"] in ("SCHEDULED", "IN_PROGRESS", "VERIFIED", "BILLED", "CANCELLED")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("permit_id", ""))
    assert is_valid_uuid(data.get("renter_org_id", ""))
    assert data["invoice_kind"] in ("PROVISIONAL", "FINAL", "REFUND", "DAMAGE")
    for field in ("rental_fee_cents", "staffing_charge_cents", "after_hours_charge_cents",
                  "discount_cents", "total_cents", "amount_paid_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
        assert data[field] >= 0, f"{field} must be non-negative"
    assert data["invoice_status"] in (
        "DRAFT", "ISSUED", "PAID", "VOID", "REFUND_PENDING", "REFUNDED",
    )


def assert_damage_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("permit_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]
    assert isinstance(data["line_items"], list) and len(data["line_items"]) > 0
    assert isinstance(data["total_claimed_cents"], int) and data["total_claimed_cents"] > 0
    assert data.get("adjudicated_amount_cents") is None or (
        0 <= data["adjudicated_amount_cents"] <= data["total_claimed_cents"]
    )
    assert data["assessment_status"] in ("OPEN", "ADJUDICATED", "APPEALED", "FINAL")


def assert_payment_transaction(data: dict):
    """PRD §2.5: ledger rows carry id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "PaymentTransaction must not carry updated_at"
    assert "version" not in data, "PaymentTransaction must not carry version"
    assert is_valid_uuid(data.get("permit_id", ""))
    assert data.get("invoice_id") is None or is_valid_uuid(data["invoice_id"])
    assert data["txn_kind"] in (
        "DEPOSIT_CAPTURE", "FEE_PAYMENT", "DEPOSIT_REFUND",
        "DEPOSIT_FORFEIT", "FEE_REFUND", "DAMAGE_CHARGE",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["posted_at"])
    assert isinstance(data["idempotency_key"], str) and data["idempotency_key"]


def assert_seasonal_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("renter_org_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["series_name"], str) and data["series_name"]
    assert isinstance(data["recurrence_rule"], str) and data["recurrence_rule"]
    assert is_iso8601_timestamp(data["season_start"])
    assert is_iso8601_timestamp(data["season_end"])
    assert data.get("renewed_from_id") is None or is_valid_uuid(data["renewed_from_id"])
    assert is_iso8601_timestamp(data["seniority_key"])
    assert data["series_status"] in (
        "PENDING_GENERATION", "ACTIVE", "PARTIALLY_BLOCKED", "COMPLETED", "CANCELLED",
    )


def assert_invoice_conservation(invoice: dict):
    """PRD §3.6: total_cents == rental + staffing + after_hours - discount, floored at 0."""
    expected = max(
        0,
        invoice["rental_fee_cents"]
        + invoice["staffing_charge_cents"]
        + invoice["after_hours_charge_cents"]
        - invoice["discount_cents"],
    )
    assert invoice["total_cents"] == expected, (
        f"Invoice total {invoice['total_cents']} != subtotal-minus-discount {expected}"
    )


def sum_txns(payments: list, txn_kind: str) -> int:
    """Sum amount_cents over PaymentTransaction rows of one kind."""
    return sum(p["amount_cents"] for p in payments if p["txn_kind"] == txn_kind)


def txns_of_kind(payments: list, txn_kind: str) -> list:
    return [p for p in payments if p["txn_kind"] == txn_kind]


def invoice_of_kind(invoices: list, kind: str) -> dict:
    """Select the unique invoice of a kind from a permit's invoice list.
    List endpoints sort by creation timestamp ascending, so filtering by kind
    is the robust way to pick PROVISIONAL vs FINAL."""
    matches = [i for i in invoices if i["invoice_kind"] == kind]
    assert len(matches) == 1, f"Expected exactly one {kind} invoice, got {len(matches)}"
    return matches[0]

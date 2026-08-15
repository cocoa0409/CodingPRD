"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """PRD §2.4: every entity carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_subscription_plan(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["plan_type"] in ("PRINT", "DIGITAL", "BUNDLE")
    assert isinstance(data["issues_per_week"], int)
    assert isinstance(data["base_weekly_rate_cents"], int)
    assert data["base_weekly_rate_cents"] > 0
    assert isinstance(data["min_weekly_rate_cents"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_subscriber(data: dict):
    assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ("ACTIVE", "LAPSED", "CLOSED")
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["unapplied_cash_cents"], int)


def assert_subscription(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["subscriber_id"])
    assert is_valid_uuid(data["plan_id"])
    assert isinstance(data["start_date"], str)
    assert data["billing_status"] in (
        "PENDING_START", "ACTIVE", "GRACE", "SUSPENDED",
        "CANCEL_PENDING", "CANCELLED", "LAPSED",
    )
    assert data["delivery_status"] in ("NOT_DELIVERED", "DELIVERING", "HELD")


def assert_delivery_route(data: dict):
    assert_common_fields(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["max_stops"], int) and data["max_stops"] > 0
    assert isinstance(data["assigned_stop_count"], int)
    assert data["assigned_stop_count"] >= 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_carrier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["compensation_model"] in ("PER_COPY_GROSS", "PER_COPY_NET_OF_COMPLAINTS")
    assert isinstance(data["per_copy_rate_cents"], int) and data["per_copy_rate_cents"] > 0
    assert data["status"] == "ACTIVE"


def assert_route_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert is_valid_uuid(data["route_id"])
    assert isinstance(data["start_date"], str)
    assert data["status"] in ("ACTIVE", "ENDED")


def assert_vacation_hold(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["resolution"] in ("CREDIT", "REDELIVER")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_delivery_complaint(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert isinstance(data["service_date"], str)
    assert data["complaint_type"] in ("MISSED", "DAMAGED", "LATE", "OTHER")
    assert data["status"] in ("OPEN", "CREDITED", "DENIED")


def assert_credit_memo(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["subscriber_id"])
    assert data["source"] in ("GOODWILL", "COMPLAINT", "PRORATION")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["applied_cents"], int) and data["applied_cents"] >= 0
    assert data["status"] in ("ISSUED", "APPLIED", "VOIDED")


def assert_save_offer(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert data["offer_type"] == "DISCOUNT_RATE"
    assert data["origin"] in ("CANCEL_FLOW", "RETENTION_REP")
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED")


def assert_rack_location(data: dict):
    assert_common_fields(data)
    assert isinstance(data["location_name"], str) and data["location_name"]
    assert isinstance(data["price_per_copy_cents"], int) and data["price_per_copy_cents"] > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_rack_sales_report(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["rack_location_id"])
    assert isinstance(data["week_start_date"], str)
    assert isinstance(data["copies_delivered"], int) and data["copies_delivered"] >= 0
    assert isinstance(data["copies_returned"], int) and data["copies_returned"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "RECONCILED", "DISPUTED")


def assert_payment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["subscriber_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CARD", "CHECK", "CASH", "ACH")
    assert data["status"] in ("INITIATED", "CLEARED", "FAILED", "REVERSED")


def assert_billing_charge(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert is_valid_uuid(data["subscriber_id"])
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["due_date"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert data["status"] in ("OPEN", "PARTIALLY_PAID", "PAID", "WRITTEN_OFF")


def assert_audit_report(data: dict):
    assert_common_fields(data)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["paid_print_subscribers"], int)
    assert isinstance(data["paid_digital_subscribers"], int)
    assert isinstance(data["single_copy_copies"], int)
    assert data["status"] in ("DRAFT", "CERTIFIED", "SUBMITTED")


def assert_settlement(data: dict):
    """PRD §3.7: settlement response field set."""
    for field in (
        "week_start_date", "compensation_model", "delivered_copies",
        "complaint_count", "gross_cents", "bonus_cents", "deduction_cents",
        "net_cents",
    ):
        assert field in data, f"settlement missing field {field!r}"
    assert isinstance(data["delivered_copies"], int)
    assert isinstance(data["complaint_count"], int)
    for field in ("gross_cents", "bonus_cents", "deduction_cents", "net_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["net_cents"] >= 0, "net_cents is floored at zero (PRD §3.7)"


def assert_charge_outstanding(charge: dict) -> int:
    """PRD §2.6: outstanding = amount - paid - credit_applied."""
    outstanding = (
        charge["amount_cents"]
        - charge["paid_amount_cents"]
        - charge["credit_applied_cents"]
    )
    assert outstanding >= 0
    return outstanding

"""Entity assertions and domain invariant checkers (Bridal Gown Shop API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version for common_fields:true entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_stylist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert data["turnaround_buffer_minutes"] >= 0
    assert isinstance(data["active"], bool)


def assert_fitting_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["room_label"], str) and len(data["room_label"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["out_of_service"], bool)


def assert_bridal_party(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["party_name"], str) and len(data["party_name"]) > 0
    assert is_iso8601_timestamp(data["event_date"])
    assert data["coordination_status"] in ("FORMING", "LOCKED")
    assert isinstance(data["member_order_count"], int) and data["member_order_count"] >= 0


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["stylist_id"])
    assert data["appointment_type"] in ("CONSULTATION", "FITTING")
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in ("BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_fitting_room_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["fitting_room_id"])
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert is_iso8601_timestamp(data["slot_start_at"])
    assert is_iso8601_timestamp(data["slot_end_at"])
    assert data["status"] in ("HELD", "RELEASED")


def assert_gown_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["gown_style_code"], str) and len(data["gown_style_code"]) > 0
    assert isinstance(data["ordered_size"], int) and data["ordered_size"] >= 0
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["standard_lead_days"], int) and data["standard_lead_days"] >= 1
    assert isinstance(data["is_rush"], bool)
    assert isinstance(data["quoted_total_cents"], int)
    assert data["fulfillment_status"] in (
        "DRAFT", "ORDERED", "RECEIVED", "READY", "PICKED_UP", "CANCELLED"
    )
    assert data["payment_status"] in ("UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED")


def assert_accessory_addon(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["gown_order_id"])
    assert data["accessory_type"] in ("VEIL", "TIARA", "SASH", "SHOES")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_alteration_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["gown_order_id"])
    assert isinstance(data["estimated_labor_minutes"], int) and data["estimated_labor_minutes"] >= 0
    assert isinstance(data["actual_labor_minutes"], int) and data["actual_labor_minutes"] >= 0
    assert isinstance(data["refitting_count"], int) and data["refitting_count"] >= 0
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in ("QUEUED", "FITTING", "ADJUSTING", "COMPLETED", "CANCELLED")


def assert_payment_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["gown_order_id"])
    assert isinstance(data["plan_total_cents"], int) and data["plan_total_cents"] >= 0
    assert isinstance(data["term_installments"], int) and data["term_installments"] >= 1
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["installment_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert data["status"] in ("DEPOSIT_DUE", "ACTIVE", "PAID_IN_FULL", "CANCELLED")


def assert_payment(data: dict):
    """Payment is common_fields:false — only id + created_at + payment fields, NO version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["payment_plan_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["kind"] in ("DEPOSIT", "INSTALLMENT", "REFUND")
    assert data["settlement_status"] in ("SETTLED", "REVERSED")


# ─── Domain invariants ──────────────────────────────────────────────────────

def assert_plan_ledger_invariant(plan: dict):
    """PRD §3.7: amount_paid_cents always equals plan_total_cents minus balance_due_cents."""
    assert plan["amount_paid_cents"] == plan["plan_total_cents"] - plan["balance_due_cents"], (
        f"Ledger invariant broken: paid {plan['amount_paid_cents']} != "
        f"total {plan['plan_total_cents']} - balance {plan['balance_due_cents']}"
    )

"""Entity assertions and domain invariant checkers.

Each assert_<entity>() validates the response shape against the PRD contract:
identity is a UUID, created_at is ISO 8601, status is in the declared value set,
and monetary fields are integer cents. Append-only entities (Payment,
Notification) are checked to carry only id + created_at (no version/updated_at).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

REPAIR_STATUSES = [
    "INTAKE", "AWAITING_APPROVAL", "REVISION_REQUESTED", "APPROVED",
    "AWAITING_PARTS", "IN_REPAIR", "READY_FOR_PICKUP", "PICKED_UP",
    "UNCLAIMED", "DISPOSED", "CANCELLED",
]
NOTIFY_STATUSES = ["NONE", "READY_NOTIFIED", "UNCLAIMED_WARNED"]
ITEM_CATEGORIES = ["SHOE", "LEATHER", "WATCH"]
LINE_STATUSES = ["QUOTED", "COMPLETED", "VOIDED"]
ESTIMATE_STATUSES = ["DRAFT", "PRESENTED", "APPROVED", "REJECTED", "SUPERSEDED"]
PARTS_STATUSES = ["REQUESTED", "ORDERED", "RECEIVED", "CANCELLED"]
CLAIM_STATUSES = ["FILED", "APPROVED", "DENIED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["phone"], str)
    assert data["notify_channel"] in ("EMAIL", "SMS")
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_service_type(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["item_category"] in ITEM_CATEGORIES
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["standard_turnaround_days"], int) and data["standard_turnaround_days"] >= 1
    assert isinstance(data["warranty_days"], int) and data["warranty_days"] >= 0
    assert isinstance(data["rush_eligible"], bool)
    assert isinstance(data["active"], bool)


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["skills"], list)
    for s in data["skills"]:
        assert s in ITEM_CATEGORIES
    assert isinstance(data["active"], bool)


def assert_repair_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["priority"] in ("STANDARD", "RUSH")
    assert data["repair_status"] in REPAIR_STATUSES
    assert data["notify_status"] in NOTIFY_STATUSES
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    if data.get("final_charge_cents") is not None:
        assert isinstance(data["final_charge_cents"], int)
    if data.get("sla_breached") is not None:
        assert isinstance(data["sla_breached"], bool)


def assert_ticket_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ticket_id"])
    assert data["item_category"] in ITEM_CATEGORIES
    assert isinstance(data["description"], str)
    assert data["condition_grade"] in ("EXCELLENT", "GOOD", "FAIR", "POOR")
    assert isinstance(data.get("condition_notes", ""), str)


def assert_service_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ticket_id"])
    assert is_valid_uuid(data["ticket_item_id"])
    assert is_valid_uuid(data["service_type_id"])
    assert isinstance(data["quoted_price_cents"], int) and data["quoted_price_cents"] >= 0
    if data.get("adjusted_price_cents") is not None:
        assert isinstance(data["adjusted_price_cents"], int) and data["adjusted_price_cents"] >= 0
    assert data["status"] in LINE_STATUSES


def assert_estimate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ticket_id"])
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert is_valid_uuid(data["authored_by_technician_id"])
    for f in ("labor_subtotal_cents", "parts_subtotal_cents",
              "rush_surcharge_cents", "estimate_total_cents"):
        assert isinstance(data[f], int), f"{f} must be an int (integer cents)"
    assert data["status"] in ESTIMATE_STATUSES


def assert_parts_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ticket_id"])
    assert is_valid_uuid(data["service_line_id"])
    assert isinstance(data["part_name"], str)
    assert isinstance(data["supplier_cost_cents"], int) and data["supplier_cost_cents"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["marked_up_cost_cents"], int) and data["marked_up_cost_cents"] >= 0
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert data["status"] in PARTS_STATUSES


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ticket_id"])
    assert is_valid_uuid(data["service_line_id"])
    assert is_valid_uuid(data["reported_by_customer_id"])
    assert isinstance(data["defect_description"], str)
    assert data["status"] in CLAIM_STATUSES


def assert_payment(data: dict):
    """Payment is append-only: id + created_at only, NO version / updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Payment is append-only and must not carry version"
    assert "updated_at" not in data, "Payment is append-only and must not carry updated_at"
    assert is_valid_uuid(data["ticket_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CASH", "CARD", "STORE_CREDIT")
    assert data["state"] in ("CAPTURED", "REFUNDED")


def assert_notification(data: dict):
    """Notification is append-only: id + created_at only, NO version / updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Notification is append-only and must not carry version"
    assert "updated_at" not in data, "Notification is append-only and must not carry updated_at"
    assert is_valid_uuid(data["ticket_id"])
    assert data["kind"] in ("READY_FOR_PICKUP", "UNCLAIMED_WARNING", "ESTIMATE_PRESENTED")

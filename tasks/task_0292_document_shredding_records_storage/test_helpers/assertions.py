"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Append-only evidence
entities (WeightTicket, CustodyEvent) carry only id + created_at — their
assertions never demand updated_at or version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version for durable, mutable records."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """id + created_at only for append-only evidence (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["business_name"], str) and len(data["business_name"]) > 0
    assert data["compliance_regime"] in ("STANDARD", "FACTA", "HIPAA")
    assert isinstance(data["billing_email"], str)
    assert isinstance(data["current_period_index"], int)
    assert isinstance(data["storage_credit_cents"], int)
    assert data["storage_credit_cents"] >= 0, "storage_credit_cents is never negative"
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_location(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["address"], str)
    assert isinstance(data["secure_area"], bool)


def assert_rate_card(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    for fee in ("scheduled_purge_rate_cents_per_kg", "onetime_purge_rate_cents_per_kg",
                "onsite_trip_fee_cents", "console_swap_fee_cents",
                "storage_rate_cents_per_box_per_period", "retrieval_fee_cents"):
        assert isinstance(data[fee], int) and data[fee] >= 0, f"{fee} must be a non-negative int"
    assert isinstance(data["rush_retrieval_multiplier_bps"], int)
    assert data["rush_retrieval_multiplier_bps"] >= 10000
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_container(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["location_id"], str)
    assert data["container_type"] in ("CONSOLE", "BIN")
    assert isinstance(data["capacity_kg"], (int, float)) and data["capacity_kg"] > 0
    assert isinstance(data["tare_weight_kg"], (int, float)) and data["tare_weight_kg"] >= 0
    assert data["status"] in ("PLACED", "SCHEDULED_FOR_SERVICE", "IN_SERVICE", "RETIRED")


def assert_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["location_id"], str)
    assert data["service_mode"] in ("ON_SITE", "OFF_SITE_PICKUP", "DROP_OFF")
    assert data["cadence"] in ("SCHEDULED", "ONE_TIME")
    assert isinstance(data["billed_weight_kg"], (int, float))
    assert isinstance(data["order_charge_cents"], int)
    assert data["status"] in ("SCHEDULED", "EN_ROUTE", "ON_SITE_SHREDDED",
                              "PICKED_UP", "AT_PLANT", "DESTROYED", "CANCELLED")


def assert_weight_ticket(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "WeightTicket is append-only; no updated_at"
    assert "version" not in data, "WeightTicket is append-only; no version"
    assert isinstance(data["order_id"], str)
    assert isinstance(data["gross_weight_kg"], (int, float))
    assert isinstance(data["tare_total_kg"], (int, float))
    assert isinstance(data["net_weight_kg"], (int, float))
    assert data["net_weight_kg"] >= 0, "net_weight_kg is floored at zero"
    assert isinstance(data["captured_by"], str)


def assert_custody_event(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "CustodyEvent is append-only; no updated_at"
    assert "version" not in data, "CustodyEvent is append-only; no version"
    assert isinstance(data["order_id"], str)
    assert data["subject_type"] in ("CONTAINER", "RETENTION_BOX")
    assert data["event_type"] in ("SEALED", "COLLECTED", "IN_TRANSIT",
                                  "RECEIVED_AT_PLANT", "DESTROYED", "RETURNED")
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["certificate_no"], str)
    assert isinstance(data["destroyed_weight_kg"], (int, float))
    assert data["status"] in ("ISSUED", "VOIDED")


def assert_destruction_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["certificate_id"], str)
    assert isinstance(data["line_cents"], int)
    assert data["status"] in ("ISSUED", "PAID")


def assert_retention_box(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["location_id"], str)
    assert isinstance(data["barcode"], str)
    assert isinstance(data["stored_at_period"], int)
    assert isinstance(data["free_periods"], int) and data["free_periods"] >= 0
    assert data["status"] in ("INGESTED", "STORED", "OUT_FOR_RETRIEVAL", "DESTROYED")


def assert_retrieval_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["box_id"], str)
    assert isinstance(data["account_id"], str)
    assert data["priority"] in ("STANDARD", "RUSH")
    assert isinstance(data["retrieval_charge_cents"], int)
    assert isinstance(data["delivered_period"], int)
    assert isinstance(data["requested_by"], str)
    assert data["status"] in ("PENDING", "DELIVERED", "RETURN_PENDING",
                              "RETURNED", "REFUSED", "CANCELLED")


def assert_compliance_hold(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert data["subject_type"] in ("RETENTION_BOX", "SERVICE_ORDER")
    assert isinstance(data["subject_id"], str)
    assert data["reason"] in ("LITIGATION_HOLD", "AUDIT_HOLD", "REGULATORY_FREEZE")
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_storage_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["period_index"], int)
    assert isinstance(data["storage_line_cents"], int)
    assert isinstance(data["retrieval_line_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert data["amount_due_cents"] >= 0, "amount_due_cents is never negative"
    assert data["status"] in ("ISSUED", "PAID")

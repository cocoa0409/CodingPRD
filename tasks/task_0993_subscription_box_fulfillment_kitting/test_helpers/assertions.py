"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Assertions only demand fields the PRD guarantees on the resource
representation. KitBOMLine and InventoryEvent are wholesale/append-only:
they carry only id + created_at, and updated_at/version must be absent
(PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def _assert_append_only_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at (append-only / wholesale)"
    assert "version" not in data, f"{entity} must not carry version (append-only / wholesale)"


def assert_client(data: dict):
    _assert_common_fields(data, "Client")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert isinstance(data["credit_balance_cents"], int)


def assert_box_plan(data: dict):
    _assert_common_fields(data, "BoxPlan")
    assert isinstance(data["client_id"], str) and data["client_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["price_per_box_cents"], int) and data["price_per_box_cents"] > 0
    assert isinstance(data["shipping_weight_grams"], int) and data["shipping_weight_grams"] > 0
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]
    assert "active_revision_id" in data


def assert_kit_revision(data: dict):
    _assert_common_fields(data, "KitRevision")
    assert isinstance(data["plan_id"], str) and data["plan_id"]
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert data["status"] in ["DRAFT", "APPROVED", "RETIRED"]
    assert "supersedes_revision_id" in data
    assert "approved_at" in data


def assert_bom_line(data: dict):
    _assert_append_only_fields(data, "KitBOMLine")
    assert isinstance(data["revision_id"], str) and data["revision_id"]
    assert isinstance(data["component_id"], str) and data["component_id"]
    assert isinstance(data["qty_per_box"], int) and data["qty_per_box"] > 0


def assert_component(data: dict):
    _assert_common_fields(data, "Component")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["reorder_point_units"], int) and data["reorder_point_units"] >= 0
    assert isinstance(data["on_hand_units"], int)
    assert isinstance(data["reserved_units"], int)


def assert_component_read(data: dict):
    """GET /components/{id} additionally returns the availability figures and
    stock_status (PRD §2.6: 'Reading a component returns both figures
    alongside stock_status')."""
    assert_component(data)
    assert isinstance(data["available_units"], int)
    assert isinstance(data["projected_available_units"], int)
    assert data["stock_status"] in ["OK", "LOW"]


def assert_inventory_event(data: dict):
    _assert_append_only_fields(data, "InventoryEvent")
    assert isinstance(data["component_id"], str) and data["component_id"]
    assert "run_id" in data
    assert data["event_type"] in ["RECEIPT", "RESERVE", "RELEASE", "COMMIT"]
    assert isinstance(data["quantity_delta"], int)


def assert_import_batch(data: dict):
    _assert_common_fields(data, "ImportBatch")
    assert isinstance(data["plan_id"], str) and data["plan_id"]
    assert isinstance(data["total_rows"], int) and data["total_rows"] >= 0
    assert isinstance(data["accepted_count"], int) and data["accepted_count"] >= 0
    assert isinstance(data["rejected_count"], int) and data["rejected_count"] >= 0
    assert data["status"] in ["UPLOADED", "COMMITTED"]


def assert_subscriber(data: dict):
    _assert_common_fields(data, "Subscriber")
    assert isinstance(data["plan_id"], str) and data["plan_id"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["zone"], int) and 1 <= data["zone"] <= 8
    assert data["status"] in ["ACTIVE", "PAUSED", "CHURNED"]
    assert "churned_at" in data
    assert "churn_reason" in data


def assert_assembly_run(data: dict):
    _assert_common_fields(data, "AssemblyRun")
    assert isinstance(data["plan_id"], str) and data["plan_id"]
    assert isinstance(data["period"], str) and data["period"]
    assert isinstance(data["planned_box_count"], int) and data["planned_box_count"] >= 0
    assert isinstance(data["kitted_box_count"], int) and data["kitted_box_count"] >= 0
    assert isinstance(data["estimate_cents"], int) and data["estimate_cents"] >= 0
    assert data["status"] in ["DRAFT", "LOCKED", "KITTING", "KITTED", "CLOSED", "CANCELLED"]
    assert "locked_at" in data


def assert_shipment(data: dict):
    _assert_common_fields(data, "Shipment")
    assert isinstance(data["run_id"], str) and data["run_id"]
    assert isinstance(data["subscriber_id"], str) and data["subscriber_id"]
    assert "wave_id" in data
    assert data["fulfill_status"] in [
        "QUEUED", "STAGED", "ASSIGNED", "MANIFESTED",
        "SHIPPED", "DELIVERED", "RETURNED", "CANCELLED",
    ]
    assert data["label_status"] in ["NONE", "PURCHASED", "VOIDED"]
    assert isinstance(data["postage_cents"], int) and data["postage_cents"] >= 0
    assert "tracking_code" in data
    assert isinstance(data["is_replacement"], bool)
    assert "delivered_at" in data


def assert_shipping_wave(data: dict):
    _assert_common_fields(data, "ShippingWave")
    assert data["carrier"] in ["USPS", "UPS", "FEDEX"]
    assert data["service_level"] in ["GROUND", "EXPRESS"]
    assert is_iso8601_timestamp(data["pickup_start"])
    assert is_iso8601_timestamp(data["pickup_end"])
    assert data["status"] in ["SCHEDULED", "MANIFESTED", "TENDERED", "CANCELLED"]
    assert isinstance(data["assigned_count"], int) and data["assigned_count"] >= 0


def assert_return_case(data: dict):
    _assert_common_fields(data, "ReturnCase")
    assert isinstance(data["shipment_id"], str) and data["shipment_id"]
    assert data["reason"] in ["DAMAGED", "LOST", "WRONG_ITEM", "OTHER"]
    assert data["requested_resolution"] in ["REPLACE", "REFUND"]
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED", "RECEIVED", "RESOLVED"]
    assert "resolution_applied" in data
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0
    assert "replacement_shipment_id" in data


def assert_billing_statement(data: dict):
    _assert_common_fields(data, "BillingStatement")
    assert isinstance(data["client_id"], str) and data["client_id"]
    assert isinstance(data["period"], str) and data["period"]
    for field in ("box_charge_cents", "postage_cents", "refund_credit_cents",
                  "adjustment_credit_cents", "net_cents"):
        assert isinstance(data[field], int), f"BillingStatement.{field} must be integer cents"
    assert isinstance(data["discount_pct"], int) and data["discount_pct"] in (0, 5, 10)
    assert data["status"] in ["PROVISIONAL", "FINALIZED", "DISPUTED", "PAID"]


def assert_component_invariants(data: dict):
    """Component availability identity (PRD §2.6):
    available_units == on_hand_units - reserved_units."""
    assert data["available_units"] == data["on_hand_units"] - data["reserved_units"], (
        f"available_units {data['available_units']} != on_hand {data['on_hand_units']} "
        f"- reserved {data['reserved_units']}"
    )
    expected_stock = "LOW" if data["available_units"] <= data["reorder_point_units"] else "OK"
    assert data["stock_status"] == expected_stock, (
        f"stock_status {data['stock_status']} inconsistent with available "
        f"{data['available_units']} vs reorder_point {data['reorder_point_units']}"
    )

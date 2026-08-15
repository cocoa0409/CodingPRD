"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity_label: str):
    """Common fields per PRD §2.4: id UUID, ISO timestamps, integer version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), (
        f"{entity_label}.version must be int"
    )


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_exposure_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_project(data: dict):
    _assert_common(data, "Project")
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert data["health_jurisdiction"] in (
        "CITY_HEALTH",
        "COUNTY_HEALTH",
        "STATE_HEALTH",
    )
    assert isinstance(data["quote_baseline_cents"], int)
    assert isinstance(data["retainage_held_cents"], int)
    assert isinstance(data["warranty_registered_count"], int)
    assert data["status"] in (
        "DESIGN",
        "QUOTED",
        "CONTRACTED",
        "FABRICATION",
        "DELIVERED",
        "COMMISSIONED",
        "PUNCH_CLOSED",
        "COMPLETED",
        "CANCELLED",
    )


def assert_layout(data: dict):
    _assert_common(data, "KitchenLayout")
    assert isinstance(data["layout_label"], str) and data["layout_label"]
    assert isinstance(data["drawing_ref"], str) and data["drawing_ref"]
    assert isinstance(data["hood_required"], bool)
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "SUPERSEDED")


def assert_equipment_item(data: dict):
    _assert_common(data, "EquipmentItem")
    assert isinstance(data["model_no"], str) and data["model_no"]
    assert data["item_kind"] in ("STOCK", "CUSTOM_FABRICATION")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert isinstance(data["requires_hood"], bool)
    assert data["warranty_status"] in ("UNREGISTERED", "REGISTERED")
    assert data["status"] in (
        "SCHEDULED",
        "ORDERED",
        "RECEIVED",
        "INSTALLED",
        "STARTED",
        "CANCELLED",
    )


def assert_fabrication_order(data: dict):
    _assert_common(data, "FabricationOrder")
    assert data["status"] in (
        "PENDING_SHOP_DRAWING",
        "SHOP_DRAWING_APPROVED",
        "IN_PRODUCTION",
        "FAB_COMPLETE",
        "CANCELLED",
    )
    if data["status"] == "FAB_COMPLETE":
        assert isinstance(data["final_fab_cost_cents"], int)
    else:
        assert data.get("final_fab_cost_cents") in (None, 0) or isinstance(
            data.get("final_fab_cost_cents"), int
        )


def assert_quote(data: dict):
    _assert_common(data, "Quote")
    for field in (
        "equipment_subtotal_cents",
        "freight_cents",
        "installation_cents",
        "startup_cents",
        "grand_total_cents",
    ):
        assert isinstance(data[field], int), f"Quote.{field} must be int cents"
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert data["status"] in (
        "DRAFT",
        "PRESENTED",
        "ACCEPTED",
        "REJECTED",
        "SUPERSEDED",
    )


def assert_permit_filing(data: dict):
    _assert_common(data, "PermitFiling")
    assert data["authority"] in ("HEALTH_DEPT", "BUILDING_DEPT", "FIRE_MARSHAL")
    assert isinstance(data["review_cycle_no"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")


def assert_delivery_job(data: dict):
    _assert_common(data, "DeliveryJob")
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data["rigging_required"], bool)
    assert data["status"] in (
        "PLANNED",
        "DISPATCHED",
        "SITE_COMPLETE",
        "CANCELLED",
    )


def assert_startup_session(data: dict):
    _assert_common(data, "StartupSession")
    assert isinstance(data["technician_name"], str) and data["technician_name"]
    assert isinstance(data["demo_minutes"], int)
    assert isinstance(data["warranty_registered"], bool)
    assert data["status"] in ("SCHEDULED", "COMPLETE", "VOID")


def assert_service_agency(data: dict):
    _assert_common(data, "ServiceAgency")
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["covered_jurisdictions"], list)
    for j in data["covered_jurisdictions"]:
        assert j in ("CITY_HEALTH", "COUNTY_HEALTH", "STATE_HEALTH")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["open_assignment_count"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_service_assignment(data: dict):
    _assert_common(data, "ServiceAssignment")
    assert isinstance(data["agency_id"], str)
    assert data["status"] in ("OPEN", "CLOSED", "TRANSFERRED")


def assert_punch_list_item(data: dict):
    _assert_common(data, "PunchListItem")
    assert isinstance(data["description"], str)
    assert data["severity"] in ("COSMETIC", "FUNCTIONAL", "LIFE_SAFETY")
    assert data["status"] in ("OPEN", "VERIFIED", "VOID")


def assert_project_exposure_invariants(customer: dict, project: dict):
    """Domain invariants linking project financials to customer exposure."""
    assert customer["outstanding_exposure_cents"] >= 0
    assert project["retainage_held_cents"] >= 0
    if project["status"] in ("PUNCH_CLOSED", "COMPLETED", "CANCELLED"):
        assert project["retainage_held_cents"] == 0

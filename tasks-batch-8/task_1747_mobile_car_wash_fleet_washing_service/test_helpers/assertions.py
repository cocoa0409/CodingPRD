"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BillingStatus, CancelReason, ContainmentType, CustomerStatus, CustomerType,
    DamageArea, DamageClaimStatus, FleetContractStatus, HoldReason, IncidentStatus,
    IncidentType, InspectionReportStatus, InvoiceStatus, InvoiceVariant, AuditResult,
    ReclaimSystem, RouteCancelReason, RouteStatus, RouteStopStatus, SiteStatus,
    SubscriptionStatus, SuspensionReason, TechnicianStatus, Cadence, VanStatus,
    VehicleClass, WashOrderStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["customer_type"] in {e.value for e in CustomerType}
    assert data["status"] in {e.value for e in CustomerStatus}
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_site(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["lot_size_sqft"], int) and data["lot_size_sqft"] > 0
    assert data["containment_type"] in {e.value for e in ContainmentType}
    assert isinstance(data["water_reclaim_required"], bool)
    assert data["max_discharge_gal"] >= 0
    assert data["status"] in {e.value for e in SiteStatus}
    if data["status"] == "ACTIVE":
        assert data.get("suspension_reason") in (None, "")
    else:
        assert data.get("suspension_reason") in {e.value for e in SuspensionReason}


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert isinstance(data["plate"], str) and len(data["plate"]) > 0
    assert data["vehicle_class"] in {e.value for e in VehicleClass}


def assert_van(data: dict):
    _assert_common_fields(data)
    assert data["tank_capacity_gal"] > 0
    assert data["reclaim_system"] in {e.value for e in ReclaimSystem}
    assert data["status"] in {e.value for e in VanStatus}
    assert data["water_loaded_gal"] >= 0
    assert data["water_reserved_gal"] >= 0
    assert data["water_used_gal"] >= 0


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["water_reclaim_certified"], bool)
    assert data["status"] in {e.value for e in TechnicianStatus}


def assert_fleet_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["monthly_minimum_cents"] >= 0
    for field in (
        "sedan_rate_cents", "suv_pickup_rate_cents",
        "van_boxtruck_rate_cents", "heavy_fleet_rate_cents",
    ):
        assert isinstance(data[field], int) and data[field] > 0
    assert data["status"] in {e.value for e in FleetContractStatus}
    if data["status"] == "TERMINATED":
        assert isinstance(data["early_termination_fee_cents"], int)
    else:
        assert data.get("early_termination_fee_cents") is None


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert data["cadence"] in {e.value for e in Cadence}
    assert data["status"] in {e.value for e in SubscriptionStatus}
    assert isinstance(data["pauses"], list)
    assert isinstance(data["pause_count_365d"], int) and data["pause_count_365d"] >= 0
    assert isinstance(data["paused_days_365d"], int) and data["paused_days_365d"] >= 0


def assert_wash_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {e.value for e in WashOrderStatus}
    assert data["billing_status"] in {e.value for e in BillingStatus}
    assert isinstance(data["vehicle_ids"], list) and len(data["vehicle_ids"]) > 0
    assert data["vehicle_count"] == len(data["vehicle_ids"])
    assert isinstance(data["quote_cents"], int) and data["quote_cents"] >= 0
    assert isinstance(data["is_rewash"], bool)
    if data.get("hold_reason") is not None:
        assert data["hold_reason"] in {e.value for e in HoldReason}
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in {e.value for e in CancelReason}
    if data["status"] in ("COMPLETED", "REWASH_PENDING", "CLOSED"):
        assert data.get("final_cents") is not None or data.get("is_rewash")


def assert_route(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {e.value for e in RouteStatus}
    assert isinstance(data["assigned_vehicle_count"], int)
    assert data["assigned_vehicle_count"] >= 0
    assert data["reserved_water_gal"] >= 0
    if data.get("cancel_reason") is not None:
        assert data["cancel_reason"] in {e.value for e in RouteCancelReason}


def assert_route_stop(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("route_id", "")), "route_id must be a UUID"
    assert is_valid_uuid(data.get("wash_order_id", "")), "wash_order_id must be a UUID"
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert is_iso8601_timestamp(data.get("planned_start_at", ""))
    assert is_iso8601_timestamp(data.get("planned_end_at", ""))
    assert data["status"] in {e.value for e in RouteStopStatus}
    assert data["reserved_water_gal"] >= 0


def assert_inspection_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("wash_order_id", "")), "wash_order_id must be a UUID"
    assert isinstance(data["technician_id"], str) and len(data["technician_id"]) > 0
    assert isinstance(data["areas"], list) and len(data["areas"]) > 0
    areas_seen = set()
    for entry in data["areas"]:
        assert entry["area"] in {e.value for e in DamageArea}
        assert entry["area"] not in areas_seen, "each area at most once"
        areas_seen.add(entry["area"])
        assert isinstance(entry["pre_existing_damage"], bool)
    assert data["status"] in {e.value for e in InspectionReportStatus}


def assert_quality_audit(data: dict):
    # QualityAudit is the single exception to the common-fields convention:
    # only id and created_at are carried; version and updated_at are absent.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "QualityAudit must not carry version"
    assert "updated_at" not in data, "QualityAudit must not carry updated_at"
    for field in (
        "exterior_score", "wheels_score", "glass_score",
        "trim_score", "water_spotting_score",
    ):
        assert isinstance(data[field], int) and 0 <= data[field] <= 20
    assert data["total_score"] == (
        data["exterior_score"] + data["wheels_score"] + data["glass_score"]
        + data["trim_score"] + data["water_spotting_score"]
    )
    assert data["result"] in {e.value for e in AuditResult}
    assert (data["total_score"] >= 80) == (data["result"] == "PASS")


def assert_damage_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("wash_order_id", "")), "wash_order_id must be a UUID"
    assert data["area"] in {e.value for e in DamageArea}
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert data["status"] in {e.value for e in DamageClaimStatus}
    if data["status"] in ("FILED", "UNDER_REVIEW"):
        assert data.get("approved_amount_cents") is None


def assert_compliance_incident(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be a UUID"
    assert data["incident_type"] in {e.value for e in IncidentType}
    assert data["status"] in {e.value for e in IncidentStatus}


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert data["variant"] in {e.value for e in InvoiceVariant}
    assert data["status"] in {e.value for e in InvoiceStatus}
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    for field in (
        "charges_cents", "loyalty_credits_cents", "billed_cents",
        "claim_credits_cents", "net_due_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["minimum_applied"], bool)


def assert_van_water_budget(data: dict):
    """Conserved van water budget (PRD §2.8): loaded == used + reserved + free,
    free >= 0."""
    loaded = data["water_loaded_gal"]
    used = data["water_used_gal"]
    reserved = data["water_reserved_gal"]
    free = loaded - used - reserved
    assert free >= 0, (
        f"van free water must never be negative: loaded {loaded}, used {used}, reserved {reserved}"
    )

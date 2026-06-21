"""Entity factories, computed-field derivation, occupancy recompute, and
serialization. All entities live in db.* dicts keyed by id."""
from datetime import datetime, timezone

from db import db, now_iso
from services.calc import round2, tefap_eligible

# --- temp-zone derivation (PRD §2.5) -----------------------------------------
CATEGORY_TEMP_ZONE = {
    "PRODUCE": "REFRIGERATED",
    "DAIRY": "REFRIGERATED",
    "FROZEN_MEAT": "FROZEN",
    "DRY_GOODS": "DRY",
    "BAKERY": "DRY",
}

FOOD_CATEGORIES = set(CATEGORY_TEMP_ZONE.keys())
TEMP_ZONES = {"DRY", "REFRIGERATED", "FROZEN"}
SOURCE_TYPES = {"DONATION", "RESCUE", "TEFAP", "PURCHASED"}


def _common_create():
    ts = now_iso()
    return {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Bump version + updated_at on a mutation."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def current_clock_iso():
    """Format the logical "current UTC" clock (PRD §2.9) as an ISO 8601 UTC
    timestamp with three fractional digits. Certification timestamps and any
    time stamped "as of now" by the business clock use this, NOT wall-clock,
    so that the clock-advance certification-aging sweep measures against the
    same timeline that produced certified_at."""
    return (
        db.current_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        + "Z"
    )


# =============================================================================
# ColdStorageUnit
# =============================================================================
def recompute_unit_occupancy(unit):
    """stored_lbs = sum remaining_lbs over lots in {AVAILABLE, RESERVED} held by
    this unit. status FULL when == capacity else AVAILABLE (PRD §2.5)."""
    total = 0.0
    for lot in db.inventory_lots.values():
        if lot["cold_storage_unit_id"] == unit["id"] and lot["disposition"] in (
            "AVAILABLE",
            "RESERVED",
        ):
            total += lot["remaining_lbs"]
    unit["stored_lbs"] = round2(total)
    unit["status"] = "FULL" if unit["stored_lbs"] == unit["capacity_lbs"] else "AVAILABLE"


def serialize_unit(unit):
    return {
        "id": unit["id"],
        "name": unit["name"],
        "temp_zone": unit["temp_zone"],
        "capacity_lbs": unit["capacity_lbs"],
        "stored_lbs": unit["stored_lbs"],
        "status": unit["status"],
        "created_at": unit["created_at"],
        "updated_at": unit["updated_at"],
        "version": unit["version"],
    }


# =============================================================================
# InventoryLot
# =============================================================================
def serialize_lot(lot):
    return {
        "id": lot["id"],
        "cold_storage_unit_id": lot["cold_storage_unit_id"],
        "food_category": lot["food_category"],
        "required_temp_zone": lot["required_temp_zone"],
        "source_type": lot["source_type"],
        "intake_lbs": lot["intake_lbs"],
        "remaining_lbs": lot["remaining_lbs"],
        "expiration_date": lot["expiration_date"],
        "unit_cost_cents": lot["unit_cost_cents"],
        "disposition": lot["disposition"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


# =============================================================================
# Agency
# =============================================================================
def serialize_agency(agency):
    return {
        "id": agency["id"],
        "name": agency["name"],
        "service_area": agency["service_area"],
        "fair_share_weight": agency["fair_share_weight"],
        "status": agency["status"],
        "lifetime_distributed_lbs": agency["lifetime_distributed_lbs"],
        "created_at": agency["created_at"],
        "updated_at": agency["updated_at"],
        "version": agency["version"],
    }


# =============================================================================
# AllocationCycle
# =============================================================================
def serialize_cycle(cycle):
    return {
        "id": cycle["id"],
        "label": cycle["label"],
        "total_pool_lbs": cycle["total_pool_lbs"],
        "total_fair_share_weight": cycle["total_fair_share_weight"],
        "status": cycle["status"],
        "created_at": cycle["created_at"],
        "updated_at": cycle["updated_at"],
        "version": cycle["version"],
    }


# =============================================================================
# AgencyOrder + OrderLine
# =============================================================================
def order_lines_of(order_id):
    lines = [l for l in db.order_lines.values() if l["agency_order_id"] == order_id]
    lines.sort(key=lambda l: l["_seq"])
    return lines


def recompute_order_requested(order):
    total = 0.0
    for line in order_lines_of(order["id"]):
        total += line["requested_lbs"]
    order["requested_lbs"] = round2(total)


def serialize_order(order):
    return {
        "id": order["id"],
        "agency_id": order["agency_id"],
        "allocation_cycle_id": order["allocation_cycle_id"],
        "requested_lbs": order["requested_lbs"],
        "approved_lbs": order["approved_lbs"],
        "status": order["status"],
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
        "version": order["version"],
    }


def serialize_line(line):
    return {
        "id": line["id"],
        "agency_order_id": line["agency_order_id"],
        "food_category": line["food_category"],
        "requested_lbs": line["requested_lbs"],
        "reserved_lbs": line["reserved_lbs"],
        "reserved_lot_id": line["reserved_lot_id"],
        "line_status": line["line_status"],
        "created_at": line["created_at"],
        "updated_at": line["updated_at"],
        "version": line["version"],
    }


# =============================================================================
# ClientHousehold
# =============================================================================
def recompute_tefap_eligible(household):
    household["tefap_eligible"] = tefap_eligible(
        household["household_size"], household["monthly_income_cents"]
    )


def serialize_household(h):
    return {
        "id": h["id"],
        "agency_id": h["agency_id"],
        "household_size": h["household_size"],
        "monthly_income_cents": h["monthly_income_cents"],
        "tefap_eligible": h["tefap_eligible"],
        "certification_status": h["certification_status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


# =============================================================================
# DistributionEvent
# =============================================================================
def serialize_event(e):
    return {
        "id": e["id"],
        "agency_order_id": e["agency_order_id"],
        "client_household_id": e["client_household_id"],
        "planned_lbs": e["planned_lbs"],
        "actual_distributed_lbs": e["actual_distributed_lbs"],
        "tefap_lbs": e["tefap_lbs"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_poundage_report(report):
    return {
        "id": report["id"],
        "allocation_cycle_id": report["allocation_cycle_id"],
        "total_planned_lbs": report["total_planned_lbs"],
        "total_distributed_lbs": report["total_distributed_lbs"],
        "total_tefap_lbs": report["total_tefap_lbs"],
        "shrinkage_lbs": report["shrinkage_lbs"],
        "created_at": report["created_at"],
    }

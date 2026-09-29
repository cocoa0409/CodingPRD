"""Derived fields and row serialization.

Every `source: computed` field in the SCAFFOLD is recomputed from its inputs
whenever it is read or used in a gate (PRD 2.9: propagated, never patched).
Version bumps are applied explicitly by the write paths, per PRD 2.5.
"""

from datetime import timedelta
from decimal import Decimal

import db
from prec import dec, floor_div, q

TIER_MIN_FIELD = {
    "STANDARD": "min_seer2_standard",
    "HIGH": "min_seer2_high",
    "PREMIUM": "min_seer2_premium",
}

OPEN_PLATFORM_STATES = ("DRAFT", "ENG_REVIEW", "RELEASED", "RESTRICTED")


# ---------------------------------------------------------------- programs
def affected_platform_count(program):
    return len(
        [
            p
            for p in db.db.rows("platforms")
            if p["refrigerant_program_id"] == program["id"]
            and p["status"] in OPEN_PLATFORM_STATES
        ]
    )


def serialize_program(row):
    return {
        "id": row["id"],
        "refrigerant_code": row["refrigerant_code"],
        "gwp": row["gwp"],
        "flammability_class": row["flammability_class"],
        "manufacture_cutoff_utc": row["manufacture_cutoff_utc"],
        "sell_through_deadline_utc": row["sell_through_deadline_utc"],
        "status": row["status"],
        "sell_through_entered_at": row["sell_through_entered_at"],
        "expired_at": row["expired_at"],
        "affected_platform_count": affected_platform_count(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# --------------------------------------------------------------- standards
def serialize_standard(row):
    return {
        "id": row["id"],
        "region_code": row["region_code"],
        "min_seer2_standard": row["min_seer2_standard"],
        "min_seer2_high": row["min_seer2_high"],
        "min_seer2_premium": row["min_seer2_premium"],
        "prohibits_flammable_refrigerant": row["prohibits_flammable_refrigerant"],
        "effective_from_utc": row["effective_from_utc"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def active_standards():
    return [s for s in db.db.rows("standards") if s["status"] == "ACTIVE"]


def participating_standards():
    """ACTIVE standards whose effective_from_utc is at or before the clock."""
    now = db.db.now()
    result = []
    for standard in active_standards():
        if standard["_effective_from"] <= now:
            result.append(standard)
    return result


def tier_minimum(standard, tier):
    return standard[TIER_MIN_FIELD[tier]]


# --------------------------------------------------------------- platforms
def platform_program(platform):
    return db.db.get("programs", platform["refrigerant_program_id"])


def platform_is_a2l(platform):
    program = platform_program(platform)
    return bool(program) and program["flammability_class"] == "A2L"


def certified_regions(platform):
    return set(
        c["region_code"]
        for c in db.db.rows("certs")
        if c["platform_id"] == platform["id"] and c["status"] == "CERTIFIED"
    )


def blocked_region_codes(platform):
    certified = certified_regions(platform)
    a2l = platform_is_a2l(platform)
    retired = platform["status"] == "RETIRED"
    blocked = set()
    for standard in participating_standards():
        region = standard["region_code"]
        if region not in certified:
            blocked.add(region)
            continue
        if standard["prohibits_flammable_refrigerant"] and a2l:
            blocked.add(region)
            continue
        if dec(platform["rated_seer2"]) < dec(tier_minimum(standard, platform["efficiency_tier"])):
            blocked.add(region)
            continue
        if retired:
            blocked.add(region)
    return sorted(blocked)


def salable_region_count(platform):
    return len(participating_standards()) - len(blocked_region_codes(platform))


def units_built_released(platform):
    return sum(
        b["quantity_units"]
        for b in db.db.rows("builds")
        if b["platform_id"] == platform["id"] and b["status"] == "RELEASED_TO_STOCK"
    )


def units_shipped_total(platform):
    return sum(
        o["shipped_units"]
        for o in db.db.rows("orders")
        if o["platform_id"] == platform["id"] and o["fulfillment_status"] == "SHIPPED"
    )


def counted_claim_count(platform):
    return len(
        [
            c
            for c in db.db.rows("claims")
            if c["platform_id"] == platform["id"]
            and c["status"] in ("OPEN", "LINKED_TO_CAPA")
        ]
    )


def claim_rate(platform, basis="BUILT_BASIS"):
    counted = counted_claim_count(platform)
    if basis == "SHIPPED_BASIS":
        denominator = max(units_shipped_total(platform), 1)
    else:
        denominator = max(units_built_released(platform), 1)
    rate = q(Decimal(100) * Decimal(counted) / Decimal(denominator), 2)
    return rate, counted, denominator


def warranty_posture(platform):
    rate, counted, _ = claim_rate(platform, "BUILT_BASIS")
    if units_built_released(platform) < 20 or counted < 3:
        return "OK"
    if rate >= Decimal("10.00"):
        return "DESIGN_CHANGE_REQUIRED"
    if rate >= Decimal("5.00"):
        return "CAPA_REQUIRED"
    return "OK"


def serialize_platform(row):
    rate, _, _ = claim_rate(row, "BUILT_BASIS")
    return {
        "id": row["id"],
        "model_code": row["model_code"],
        "efficiency_tier": row["efficiency_tier"],
        "refrigerant_program_id": row["refrigerant_program_id"],
        "supersedes_platform_id": row["supersedes_platform_id"],
        "rated_capacity_btuh": row["rated_capacity_btuh"],
        "rated_eer": row["rated_eer"],
        "rated_seer2": row["rated_seer2"],
        "compressor_part_number": row["compressor_part_number"],
        "control_board_part_number": row["control_board_part_number"],
        "max_charge_grams": row["max_charge_grams"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "released_at": row["released_at"],
        "blocked_region_codes": blocked_region_codes(row),
        "salable_region_count": salable_region_count(row),
        "warranty_posture": warranty_posture(row),
        "rolling_claim_rate_pct": rate,
        "units_built_released": units_built_released(row),
        "units_shipped_total": units_shipped_total(row),
        "last_revision_notes": row["last_revision_notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------- certifications
def serialize_cert(row):
    return {
        "id": row["id"],
        "platform_id": row["platform_id"],
        "region_code": row["region_code"],
        "rated_seer2_submitted": row["rated_seer2_submitted"],
        "status": row["status"],
        "governing_standard_id": row["governing_standard_id"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "submitted_at": row["submitted_at"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decided_at": row["decided_at"],
        "rejection_reason": row["rejection_reason"],
        "withdrawn_at": row["withdrawn_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# -------------------------------------------------------- component supply
def supply_lines(supply, statuses):
    return [
        line
        for line in db.db.rows("lines")
        if line["component_supply_id"] == supply["id"] and line["status"] in statuses
    ]


def effective_allocatable_units(supply):
    return floor_div(supply["total_allocatable_units"] * (100 - supply["derate_pct"]), 100)


def reserved_units(supply):
    return sum(line["units"] for line in supply_lines(supply, ("RESERVED",)))


def committed_units(supply):
    return sum(line["units"] for line in supply_lines(supply, ("COMMITTED",)))


def available_units(supply):
    return (
        effective_allocatable_units(supply) - reserved_units(supply) - committed_units(supply)
    )


def serialize_supply(row):
    return {
        "id": row["id"],
        "component_type": row["component_type"],
        "part_number": row["part_number"],
        "supplier_lot_code": row["supplier_lot_code"],
        "supply_month": row["supply_month"],
        "total_allocatable_units": row["total_allocatable_units"],
        "allocation_policy": row["allocation_policy"],
        "derate_pct": row["derate_pct"],
        "effective_allocatable_units": effective_allocatable_units(row),
        "reserved_units": reserved_units(row),
        "committed_units": committed_units(row),
        "available_units": available_units(row),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_line(row):
    return {
        "id": row["id"],
        "distributor_order_id": row["distributor_order_id"],
        "component_supply_id": row["component_supply_id"],
        "component_type": row["component_type"],
        "units": row["units"],
        "status": row["status"],
        "closed_reason": row["closed_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ------------------------------------------------------- distributor order
def order_lines(order, statuses=None):
    lines = [
        line for line in db.db.rows("lines") if line["distributor_order_id"] == order["id"]
    ]
    if statuses is not None:
        lines = [line for line in lines if line["status"] in statuses]
    return lines


def allocated_units(order):
    return sum(
        line["units"]
        for line in order_lines(order, ("RESERVED", "COMMITTED"))
        if line["component_type"] == "COMPRESSOR"
    )


def serialize_order(row):
    return {
        "id": row["id"],
        "distributor_code": row["distributor_code"],
        "platform_id": row["platform_id"],
        "region_code": row["region_code"],
        "requested_units": row["requested_units"],
        "priority_score": row["priority_score"],
        "requested_delivery_month": row["requested_delivery_month"],
        "created_by_user_id": row["created_by_user_id"],
        "allocated_units": allocated_units(row),
        "allocation_status": row["allocation_status"],
        "fulfillment_status": row["fulfillment_status"],
        "shipped_units": row["shipped_units"],
        "staged_at": row["staged_at"],
        "shipped_at": row["shipped_at"],
        "cancelled_at": row["cancelled_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ------------------------------------------------------------- warehousing
def warehouse_reservations(warehouse, statuses=None):
    rows = [
        r for r in db.db.rows("reservations") if r["warehouse_id"] == warehouse["id"]
    ]
    if statuses is not None:
        rows = [r for r in rows if r["status"] in statuses]
    return rows


def occupies(reservation, day_iso):
    return reservation["start_date"] <= day_iso < reservation["end_date"]


def occupancy(warehouse, day_iso):
    return sum(
        r["pallet_units"]
        for r in warehouse_reservations(warehouse, ("ACTIVE",))
        if occupies(r, day_iso)
    )


def pallets_reserved_current(warehouse):
    return occupancy(warehouse, db.db.today().isoformat())


def serialize_warehouse(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "pallet_capacity": row["pallet_capacity"],
        "pallets_reserved_current": pallets_reserved_current(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_reservation(row):
    return {
        "id": row["id"],
        "warehouse_id": row["warehouse_id"],
        "build_order_id": row["build_order_id"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "pallet_units": row["pallet_units"],
        "status": row["status"],
        "released_at": row["released_at"],
        "release_reason": row["release_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def day_range(start_date, end_date):
    """Half-open [start, end) as a list of ISO day strings."""
    days = []
    current = start_date
    while current < end_date:
        days.append(current.isoformat())
        current = current + timedelta(days=1)
    return days


# ---------------------------------------------------------------- builds
def build_reservations(build, statuses=None):
    rows = [r for r in db.db.rows("reservations") if r["build_order_id"] == build["id"]]
    if statuses is not None:
        rows = [r for r in rows if r["status"] in statuses]
    return rows


def build_leak_tests(build):
    return [t for t in db.db.rows("leak_tests") if t["build_order_id"] == build["id"]]


def build_run_tests(build):
    return [t for t in db.db.rows("run_tests") if t["build_order_id"] == build["id"]]


def latest_leak_verdict(build):
    tests = build_leak_tests(build)
    return tests[-1]["verdict"] if tests else None


def latest_run_verdict(build):
    tests = build_run_tests(build)
    return tests[-1]["verdict"] if tests else None


def latest_passing_leak_test(build):
    passing = [t for t in build_leak_tests(build) if t["verdict"] == "PASS"]
    return passing[-1] if passing else None


def serialize_build(row):
    return {
        "id": row["id"],
        "platform_id": row["platform_id"],
        "quantity_units": row["quantity_units"],
        "is_preseason": row["is_preseason"],
        "scheduled_start_utc": row["scheduled_start_utc"],
        "status": row["status"],
        "rework_count": row["rework_count"],
        "charge_grams": row["charge_grams"],
        "hold_reason": row["hold_reason"],
        "closed_reason": row["closed_reason"],
        "released_to_stock_at": row["released_to_stock_at"],
        "latest_leak_verdict": latest_leak_verdict(row),
        "latest_run_verdict": latest_run_verdict(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_leak_test(row):
    return {
        "id": row["id"],
        "build_order_id": row["build_order_id"],
        "method": row["method"],
        "measured_leak_rate_g_per_year": row["measured_leak_rate_g_per_year"],
        "decay_kpa": row["decay_kpa"],
        "hold_minutes": row["hold_minutes"],
        "applied_limit": row["applied_limit"],
        "verdict": row["verdict"],
        "performed_by_user_id": row["performed_by_user_id"],
        "performed_at": row["performed_at"],
        "created_at": row["created_at"],
    }


def serialize_run_test(row):
    return {
        "id": row["id"],
        "build_order_id": row["build_order_id"],
        "test_cell_id": row["test_cell_id"],
        "window_start_utc": row["window_start_utc"],
        "window_end_utc": row["window_end_utc"],
        "measured_capacity_btuh": row["measured_capacity_btuh"],
        "measured_power_w": row["measured_power_w"],
        "measured_ambient_c": row["measured_ambient_c"],
        "corrected_capacity_btuh": row["corrected_capacity_btuh"],
        "capacity_ratio": row["capacity_ratio"],
        "efficiency_ratio": row["efficiency_ratio"],
        "applied_capacity_tolerance": row["applied_capacity_tolerance"],
        "applied_efficiency_tolerance": row["applied_efficiency_tolerance"],
        "verdict": row["verdict"],
        "performed_by_user_id": row["performed_by_user_id"],
        "performed_at": row["performed_at"],
        "created_at": row["created_at"],
    }


def serialize_cell(row):
    return {
        "id": row["id"],
        "cell_code": row["cell_code"],
        "cooldown_minutes": row["cooldown_minutes"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


# ---------------------------------------------------------------- warranty
def serialize_claim(row):
    return {
        "id": row["id"],
        "platform_id": row["platform_id"],
        "build_order_id": row["build_order_id"],
        "failure_code": row["failure_code"],
        "component_type": row["component_type"],
        "supplier_lot_code": row["supplier_lot_code"],
        "claim_cost_cents": row["claim_cost_cents"],
        "filed_by_user_id": row["filed_by_user_id"],
        "filed_at": row["filed_at"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_capa(row):
    return {
        "id": row["id"],
        "component_supply_id": row["component_supply_id"],
        "warranty_claim_id": row["warranty_claim_id"],
        "supplier_lot_code": row["supplier_lot_code"],
        "component_type": row["component_type"],
        "trigger_claim_rate_pct": row["trigger_claim_rate_pct"],
        "derate_pct": row["derate_pct"],
        "cited_claim_count": row["cited_claim_count"],
        "status": row["status"],
        "resolution": row["resolution"],
        "effectiveness_note": row["effectiveness_note"],
        "closed_by_user_id": row["closed_by_user_id"],
        "closed_at": row["closed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }

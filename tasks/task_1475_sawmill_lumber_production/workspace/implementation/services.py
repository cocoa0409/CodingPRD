"""Business logic: lookups, serializers, computed fields, cascades, calculations.

All formulas, constants, and precision tiers are pinned by SCAFFOLD.yaml
section 1.3 and PRD section 3. All rounding is round-half-up.
"""
from datetime import timedelta
from decimal import Decimal

from db import DB, now_dt, now_iso, next_seq
from errors import ApiError
from util import dec, round_cents, round_mbf, round_pct2, parse_ymd

# ---------------------------------------------------------------------------
# Vocabularies (PRD section 2.8)
# ---------------------------------------------------------------------------
SPECIES = ("DOUGLAS_FIR", "PONDEROSA_PINE", "HEMLOCK_FIR", "CEDAR")
LOG_GRADES = ("PEELER", "SAWLOG_1", "SAWLOG_2", "UTILITY")
SAW_LINES = ("LINE_A", "LINE_B")
SAWING_PATTERNS = ("DIMENSION_2X4", "STUD_MIX", "TIMBER_4X4")
CHAMBERS = ("KILN_1", "KILN_2", "KILN_3")
DIMENSIONS = ("2X4", "2X6", "4X4")
LENGTHS_FT = (8, 10, 12, 16)
STAMP_GRADES = ("SELECT_STRUCT", "NO_2", "NO_3", "ECONOMY")
LENGTH_SPECS = ("RL", "8", "10", "12", "16")
BYPRODUCTS = ("CHIP", "SAWDUST", "BARK")
INSPECTION_ACTIONS = ("STAMP", "RESTAMP")

LOAD_STATUSES = ("RECEIVED", "SCALED", "DISPUTED", "DECKED", "CONSUMED")
RUN_STATUSES = ("PLANNED", "COMPLETED")
CHARGE_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED")
PACKAGE_STATUSES = ("GREEN", "IN_KILN", "DRY", "STAMPED", "ALLOCATED", "SHIPPED")
CONTRACT_STATUSES = ("DRAFT", "ACTIVE", "CLOSED", "EXPIRED")
ORDER_STATUSES = ("PLACED", "ALLOCATED", "SHIPPED", "CANCELLED")

# ---------------------------------------------------------------------------
# Calculation constants (scaffold section 1.3)
# ---------------------------------------------------------------------------
FREE_DECK_DAYS = 14
DEGRADE_PCT_PER_WEEK = 3
MAX_DEGRADE_PCT = 15
DECK_CAPACITY_MBF = Decimal("500")

SHRINK_PCT = {
    "DOUGLAS_FIR": Decimal("0.06"),
    "PONDEROSA_PINE": Decimal("0.07"),
    "HEMLOCK_FIR": Decimal("0.08"),
    "CEDAR": Decimal("0.05"),
}

MOISTURE_TOLERANCE_PCT = Decimal("2.0")

LENGTH_MULT = {
    "RL": Decimal("0.96"),
    8: Decimal("0.95"),
    10: Decimal("0.97"),
    12: Decimal("1.00"),
    16: Decimal("1.08"),
}
VOLUME_TIER_1_MBF = Decimal("10")
VOLUME_TIER_1_DISCOUNT = Decimal("0.02")
VOLUME_TIER_2_MBF = Decimal("50")
VOLUME_TIER_2_DISCOUNT = Decimal("0.05")

KILN_TURNAROUND = timedelta(hours=4)
STAMPED_SET = ("STAMPED", "ALLOCATED", "SHIPPED")


# ---------------------------------------------------------------------------
# Common field helpers (PRD section 2.4)
# ---------------------------------------------------------------------------

def stamp(rec):
    """Initialize common fields at creation; version starts at 1."""
    t = now_iso()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1
    rec["_seq"] = next_seq()


def touch(rec):
    """Refresh updated_at to the current logical time and bump version by 1."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def ledger_stamp(rec):
    """Append-only ledger entries carry id + created_at only (no updated_at/version)."""
    rec["created_at"] = now_iso()
    rec["_seq"] = next_seq()


# ---------------------------------------------------------------------------
# Lookups (existence: ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def _lookup(store, rid, label):
    rec = DB[store].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found")
    return rec


def get_load(rid):
    return _lookup("log_loads", rid, "LogLoad")


def get_run(rid):
    return _lookup("sawing_runs", rid, "SawingRun")


def get_charge(rid):
    return _lookup("kiln_charges", rid, "KilnCharge")


def get_package(rid):
    return _lookup("lumber_packages", rid, "LumberPackage")


def get_contract(rid):
    return _lookup("sales_contracts", rid, "SalesContract")


def get_order(rid):
    return _lookup("sales_orders", rid, "SalesOrder")


# ---------------------------------------------------------------------------
# LogLoad derived values
# ---------------------------------------------------------------------------

def days_in_deck(load):
    """Whole days elapsed since decked_at while DECKED; 0 otherwise (live read)."""
    if load["status"] != "DECKED" or load["decked_at_dt"] is None:
        return 0
    elapsed = (now_dt() - load["decked_at_dt"]).total_seconds()
    if elapsed < 0:
        return 0
    return int(elapsed // 86400)


def degrade_for_days(days):
    """Deck degrade percent: free through day 14, then 3% per whole week, cap 15."""
    if days <= FREE_DECK_DAYS:
        return 0
    weeks = (days - FREE_DECK_DAYS) // 7
    return min(MAX_DEGRADE_PCT, DEGRADE_PCT_PER_WEEK * weeks)


def effective_mbf(load):
    """scaled_mbf * (1 - degrade_pct/100), half-up to 3 decimals; null until scaled."""
    if load["scaled_mbf"] is None:
        return None
    factor = Decimal("1") - Decimal(load["degrade_pct"]) / Decimal("100")
    return round_mbf(dec(load["scaled_mbf"]) * factor)


def refresh_degrade(load):
    """Ops-checkpoint refresh of a DECKED load's stored degrade_pct."""
    load["degrade_pct"] = degrade_for_days(days_in_deck(load))


def ser_load(load):
    return {
        "id": load["id"],
        "supplier_name": load["supplier_name"],
        "species": load["species"],
        "log_grade": load["log_grade"],
        "scaled_mbf": load["scaled_mbf"],
        "price_per_mbf_cents": load["price_per_mbf_cents"],
        "purchase_cost_cents": load["purchase_cost_cents"],
        "status": load["status"],
        "decked_at": load["decked_at"],
        "days_in_deck": days_in_deck(load),
        "degrade_pct": load["degrade_pct"],
        "effective_mbf": effective_mbf(load),
        "sawing_run_id": load["sawing_run_id"],
        "created_at": load["created_at"],
        "updated_at": load["updated_at"],
        "version": load["version"],
    }


# ---------------------------------------------------------------------------
# SawingRun
# ---------------------------------------------------------------------------

def run_packages(run):
    return [
        p
        for p in DB["lumber_packages"].values()
        if p["sawing_run_id"] == run["id"]
    ]


def recompute_certified_if_complete(run):
    """Certified recovery: computable only when every package of the run is in
    {STAMPED, ALLOCATED, SHIPPED}; recompute then and bump the run's version."""
    pkgs = run_packages(run)
    if not pkgs:
        return
    if not all(p["status"] in STAMPED_SET for p in pkgs):
        return
    total_dry = sum(dec(package_dry_mbf(p)) for p in pkgs)
    run["recovery_pct_certified"] = round_pct2(
        total_dry / dec(run["input_mbf"]) * Decimal("100")
    )
    touch(run)


def ser_run(run):
    return {
        "id": run["id"],
        "saw_line": run["saw_line"],
        "scheduled_date": run["scheduled_date"],
        "sawing_pattern": run["sawing_pattern"],
        "log_load_ids": list(run["log_load_ids"]),
        "status": run["status"],
        "input_mbf": run["input_mbf"],
        "output_green_mbf": run["output_green_mbf"],
        "recovery_pct_provisional": run["recovery_pct_provisional"],
        "recovery_pct_certified": run["recovery_pct_certified"],
        "completed_at": run["completed_at"],
        "chip_tons": run["chip_tons"],
        "sawdust_tons": run["sawdust_tons"],
        "bark_tons": run["bark_tons"],
        "created_at": run["created_at"],
        "updated_at": run["updated_at"],
        "version": run["version"],
    }


# ---------------------------------------------------------------------------
# KilnCharge
# ---------------------------------------------------------------------------

def ser_charge(charge):
    return {
        "id": charge["id"],
        "chamber": charge["chamber"],
        "species": charge["species"],
        "package_ids": list(charge["package_ids"]),
        "scheduled_start": charge["scheduled_start"],
        "scheduled_end": charge["scheduled_end"],
        "target_moisture_pct": charge["target_moisture_pct"],
        "status": charge["status"],
        "actual_start": charge["actual_start"],
        "actual_end": charge["actual_end"],
        "created_at": charge["created_at"],
        "updated_at": charge["updated_at"],
        "version": charge["version"],
    }


def chamber_conflict(chamber, new_start_dt, new_end_dt):
    """4h turnaround buffer, half-open windows, exactly-4h adjacency allowed."""
    for ch in DB["kiln_charges"].values():
        if ch["chamber"] != chamber:
            continue
        if ch["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        ex_start = ch["_scheduled_start_dt"]
        ex_end = ch["_scheduled_end_dt"]
        if new_start_dt >= ex_end + KILN_TURNAROUND:
            continue
        if new_end_dt + KILN_TURNAROUND <= ex_start:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# LumberPackage
# ---------------------------------------------------------------------------

def estimated_dry(green_mbf, species):
    """round(green_mbf * (1 - SHRINK_PCT[species]), 3), half-up."""
    return round_mbf(dec(green_mbf) * (Decimal("1") - SHRINK_PCT[species]))


def package_dry_mbf(pkg):
    """dry_mbf reconciles estimate -> actual once measured at kiln completion."""
    if pkg["actual_dry_mbf"] is not None:
        return pkg["actual_dry_mbf"]
    return pkg["estimated_dry_mbf"]


def ser_package(pkg):
    return {
        "id": pkg["id"],
        "sawing_run_id": pkg["sawing_run_id"],
        "species": pkg["species"],
        "dimension": pkg["dimension"],
        "length_ft": pkg["length_ft"],
        "pieces": pkg["pieces"],
        "green_mbf": pkg["green_mbf"],
        "estimated_dry_mbf": pkg["estimated_dry_mbf"],
        "actual_dry_mbf": pkg["actual_dry_mbf"],
        "dry_mbf": package_dry_mbf(pkg),
        "kiln_charge_id": pkg["kiln_charge_id"],
        "exit_moisture_pct": pkg["exit_moisture_pct"],
        "stamped_grade": pkg["stamped_grade"],
        "status": pkg["status"],
        "stamped_at": pkg["stamped_at"],
        "sales_order_id": pkg["sales_order_id"],
        "created_at": pkg["created_at"],
        "updated_at": pkg["updated_at"],
        "version": pkg["version"],
    }


def ser_inspection(insp):
    return {
        "id": insp["id"],
        "package_id": insp["package_id"],
        "inspector_grade": insp["inspector_grade"],
        "action": insp["action"],
        "note": insp["note"],
        "created_at": insp["created_at"],
    }


# ---------------------------------------------------------------------------
# SalesContract: drawdown (computed on read)
# ---------------------------------------------------------------------------

def contract_reserved_mbf(contract):
    """Sum of volume_mbf over the contract's PLACED or ALLOCATED orders."""
    total = Decimal("0")
    for o in DB["sales_orders"].values():
        if o["contract_id"] == contract["id"] and o["status"] in ("PLACED", "ALLOCATED"):
            total += dec(o["volume_mbf"])
    return round_mbf(total)


def contract_shipped_mbf(contract):
    """Sum of dry_mbf over SHIPPED packages whose order references the contract."""
    total = Decimal("0")
    for p in DB["lumber_packages"].values():
        if p["status"] != "SHIPPED" or p["sales_order_id"] is None:
            continue
        order = DB["sales_orders"].get(p["sales_order_id"])
        if order is not None and order["contract_id"] == contract["id"]:
            total += dec(package_dry_mbf(p))
    return round_mbf(total)


def ser_contract(contract):
    reserved = contract_reserved_mbf(contract)
    shipped = contract_shipped_mbf(contract)
    return {
        "id": contract["id"],
        "customer_name": contract["customer_name"],
        "species": contract["species"],
        "grade": contract["grade"],
        "committed_mbf": contract["committed_mbf"],
        "contract_price_per_mbf_cents": contract["contract_price_per_mbf_cents"],
        "start_date": contract["start_date"],
        "end_date": contract["end_date"],
        "status": contract["status"],
        "reserved_mbf": reserved,
        "shipped_mbf": shipped,
        "remaining_mbf": round_mbf(dec(contract["committed_mbf"]) - dec(reserved)),
        "created_at": contract["created_at"],
        "updated_at": contract["updated_at"],
        "version": contract["version"],
    }


def maybe_auto_close_contract(contract):
    """Auto-transition ACTIVE -> CLOSED when shipped_mbf reaches committed_mbf."""
    if contract["status"] != "ACTIVE":
        return
    if dec(contract_shipped_mbf(contract)) >= dec(contract["committed_mbf"]):
        contract["status"] = "CLOSED"
        touch(contract)


# ---------------------------------------------------------------------------
# SalesOrder
# ---------------------------------------------------------------------------

def order_packages(order):
    return [
        p
        for p in DB["lumber_packages"].values()
        if p["sales_order_id"] == order["id"] and p["status"] == "ALLOCATED"
    ]


def recompute_order_totals(order):
    """allocated_mbf and total_cents from currently ALLOCATED packages.

    total_cents: per-package round(dry_mbf * unit_price_cents, 0) FIRST, then sum.
    """
    pkgs = order_packages(order)
    total = 0
    alloc = Decimal("0")
    for p in pkgs:
        dry = dec(package_dry_mbf(p))
        alloc += dry
        total += round_cents(dry * Decimal(order["unit_price_cents"]))
    order["allocated_mbf"] = round_mbf(alloc)
    order["total_cents"] = total


def ser_order(order):
    return {
        "id": order["id"],
        "customer_name": order["customer_name"],
        "contract_id": order["contract_id"],
        "species": order["species"],
        "grade": order["grade"],
        "length_spec": order["length_spec"],
        "volume_mbf": order["volume_mbf"],
        "pricing_mode": order["pricing_mode"],
        "unit_price_cents": order["unit_price_cents"],
        "allocated_mbf": order["allocated_mbf"],
        "total_cents": order["total_cents"],
        "status": order["status"],
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
        "version": order["version"],
    }


def eligible_pool(order):
    """STAMPED packages matching species/grade/length_spec with no holding order."""
    pool = []
    for p in DB["lumber_packages"].values():
        if p["status"] != "STAMPED":
            continue
        if p["species"] != order["species"]:
            continue
        if p["stamped_grade"] != order["grade"]:
            continue
        if p["sales_order_id"] is not None:
            continue
        if order["length_spec"] != "RL" and p["length_ft"] != order["length_spec"]:
            continue
        pool.append(p)
    return pool


def spot_unit_price(species, grade, length_spec, volume_mbf):
    """Two-step pinned rounding: round(base * length_mult), then round(that *
    (1 - discount)); half-up both steps. Empty eligible pool -> ERR_NO_PRICE_LIST."""
    now = now_dt()
    eligible = [
        row
        for row in DB["price_lists"].values()
        if row["species"] == species
        and row["grade"] == grade
        and row["_effective_from_dt"] <= now
    ]
    if not eligible:
        raise ApiError(
            "ERR_NO_PRICE_LIST",
            422,
            "No effective price list row for this species and grade",
        )
    eligible.sort(key=lambda r: (r["_effective_from_dt"], r["_seq"]), reverse=True)
    base = Decimal(eligible[0]["base_price_per_mbf_cents"])
    step1 = Decimal(round_cents(base * LENGTH_MULT[length_spec]))
    volume = dec(volume_mbf)
    if volume >= VOLUME_TIER_2_MBF:
        discount = VOLUME_TIER_2_DISCOUNT
    elif volume >= VOLUME_TIER_1_MBF:
        discount = VOLUME_TIER_1_DISCOUNT
    else:
        discount = Decimal("0")
    return round_cents(step1 * (Decimal("1") - discount))


# ---------------------------------------------------------------------------
# Byproducts (computed read; sales are final)
# ---------------------------------------------------------------------------

def byproduct_on_hand(product):
    produced = Decimal("0")
    for r in DB["sawing_runs"].values():
        if r["status"] != "COMPLETED":
            continue
        tons = r[product.lower() + "_tons"]
        if tons is not None:
            produced += dec(tons)
    sold = Decimal("0")
    for s in DB["byproduct_sales"].values():
        if s["product"] == product:
            sold += dec(s["volume_tons"])
    return round_mbf(produced), round_mbf(sold), round_mbf(produced - sold)

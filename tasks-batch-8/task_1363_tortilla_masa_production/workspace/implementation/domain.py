"""Domain engine: derived fields, serializers, calculations, cascades."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from db import store, mint, touch, fmt_dt
from errors import err

# ---- constants (PRD section 3 / scaffold calculations table) ----
VARIETY_YIELD_FACTOR = {"WHITE_CORN": Decimal("1.70"), "YELLOW_CORN": Decimal("1.65"),
                        "BLUE_CORN": Decimal("1.60")}
TARGET_MASA_MOISTURE_PCT = Decimal("55")
MASA_LOSS_FACTOR = Decimal("1.05")
SHELF_LIFE_DAYS = {"NONE": 5, "PROPIONATE": 20, "FUMARIC_ACID": 45}
ALLERGEN_RANK = {"CORN_ONLY": 0, "WHEAT_FLOUR": 1, "SOY_BLENDED": 2}
LEVEL_BASE_MIN = {"FLUSH": 30, "WET_WASH": 60, "FULL_SANITATION": 120}
DIAMETER_PENALTY_MIN = 15
TIER_FACTOR = {"A": Decimal("1.0"), "B": Decimal("0.8"), "C": Decimal("0.6")}
TIER_ORDER = {"A": 0, "B": 1, "C": 2}
SPIKE_MULTIPLIER_THRESHOLD = Decimal("1.5")
SAMPLE_MIN = 3

CORN_VARIETIES = set(VARIETY_YIELD_FACTOR)
DIAMETERS = {"D6", "D8", "D10", "D12"}
PRODUCT_CHANNELS = {"RETAIL", "FOODSERVICE"}
PRESERVATIVE_SYSTEMS = set(SHELF_LIFE_DAYS)
ALLERGEN_CLASSES = set(ALLERGEN_RANK)
ALLERGEN_ZONES = {"DEDICATED_CORN", "SHARED"}
VERIFICATION_METHODS = {"AVERAGE_WEIGHT", "COUNT_VERIFY"}
CUSTOMER_CHANNELS = {"RETAIL_GROCERY", "TORTILLERIA", "FOODSERVICE_DIST"}
PRIORITY_TIERS = {"A", "B", "C"}
CREDIT_STANDINGS = {"GOOD", "HOLD"}
EVALUATE_DECISIONS = {"PASS", "RECOOK", "REJECT"}
LINE_STATUSES = {"ACTIVE", "DOWN"}

_D2 = Decimal("0.01")
_D1 = Decimal("0.1")


def r2(x):
    return x.quantize(_D2, rounding=ROUND_HALF_UP)


def r1(x):
    return x.quantize(_D1, rounding=ROUND_HALF_UP)


def ceil_int(x):
    return int(x.to_integral_value(rounding=ROUND_CEILING))


def num(x):
    return None if x is None else float(x)


# ---- lookups ----
def get(coll, oid):
    e = coll.get(oid)
    if e is None:
        err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return e


def get_lot(oid): return get(store.ingredient_lots, oid)
def get_batch(oid): return get(store.nixtamal_batches, oid)
def get_product(oid): return get(store.products, oid)
def get_line(oid): return get(store.lines, oid)
def get_run(oid): return get(store.runs, oid)
def get_allocation(oid): return get(store.allocations, oid)
def get_changeover(oid): return get(store.changeovers, oid)
def get_pack(oid): return get(store.pack_orders, oid)
def get_customer(oid): return get(store.customers, oid)
def get_window(oid): return get(store.windows, oid)
def get_allotment(oid): return get(store.allotments, oid)
def get_route(oid): return get(store.routes, oid)
def get_stop(oid): return get(store.stops, oid)


# ---- derived fields ----
def lot_drawn_kg(lot_id):
    total = Decimal("0")
    for b in store.nixtamal_batches.values():
        if b["ingredient_lot_id"] == lot_id and b["batch_status"] != "REJECTED":
            total += b["corn_kg"]
    return total


def lot_available_kg(lot):
    avail = lot["received_kg"] - lot_drawn_kg(lot["id"])
    return avail if avail > 0 else Decimal("0")


def batch_masa_available(batch):
    if batch["actual_masa_kg"] is None:
        return Decimal("0")
    used = Decimal("0")
    for a in store.allocations.values():
        if (a["nixtamal_batch_id"] == batch["id"]
                and a["allocation_status"] in ("RESERVED", "CONSUMED")):
            used += a["allocated_kg"]
    avail = batch["actual_masa_kg"] - used
    return avail if avail > 0 else Decimal("0")


def run_masa_reserved(run_id):
    total = Decimal("0")
    for a in store.allocations.values():
        if a["production_run_id"] == run_id and a["allocation_status"] == "RESERVED":
            total += a["allocated_kg"]
    return total


def run_produced_cases(run_id):
    total = 0
    for p in store.pack_orders.values():
        if p["production_run_id"] == run_id and p["pack_status"] == "SEALED":
            total += p["cases_packed"] or 0
    return total


def line_posture(line_id):
    for r in store.runs.values():
        if r["line_id"] == line_id and r["production_status"] == "IN_PROGRESS":
            return "RUNNING"
    for c in store.changeovers.values():
        if (c["line_id"] == line_id
                and c["changeover_status"] in ("REQUIRED", "IN_PROGRESS", "FAILED")):
            return "CHANGEOVER_PENDING"
    return "AVAILABLE"


def pack_cases_available(pack):
    if pack["pack_status"] != "SEALED":
        return 0
    used = 0
    for s in store.stops.values():
        if s["pack_order_id"] == pack["id"] and s["stop_status"] in ("ALLOCATED", "DELIVERED"):
            used += s["allocated_cases"]
    avail = (pack["cases_packed"] or 0) - used
    return avail if avail > 0 else 0


def route_committed_cases(route_id):
    total = 0
    for s in store.stops.values():
        if s["route_id"] == route_id and s["stop_status"] in ("ALLOCATED", "DELIVERED"):
            total += s["allocated_cases"]
    return total


def window_covers_date(window, d):
    return window["starts_on"] <= d <= window["ends_on"]


def allotment_consumed_cases(allotment):
    window = store.windows.get(allotment["seasonal_window_id"])
    if window is None:
        return 0
    total = 0
    for s in store.stops.values():
        if s["customer_id"] != allotment["customer_id"]:
            continue
        if s["stop_status"] not in ("ALLOCATED", "DELIVERED"):
            continue
        route = store.routes.get(s["route_id"])
        if route is not None and window_covers_date(window, route["route_date"]):
            total += s["allocated_cases"]
    return total


def active_strict_window_for_date(d):
    """At most one ACTIVE window may cover a date (overlap is rejected)."""
    for w in store.windows.values():
        if w["window_status"] == "ACTIVE" and w["is_strict"] and window_covers_date(w, d):
            return w
    return None


def find_allotment(window_id, customer_id):
    for a in store.allotments.values():
        if a["seasonal_window_id"] == window_id and a["customer_id"] == customer_id:
            return a
    return None


# ---- calculations ----
def changeover_requirement(from_p, to_p):
    """Returns (level, required_downtime_min) per PRD section 3.6."""
    if from_p["allergen_class"] == to_p["allergen_class"]:
        level = "FLUSH" if from_p["diameter_in"] == to_p["diameter_in"] else "WET_WASH"
    elif ALLERGEN_RANK[from_p["allergen_class"]] > ALLERGEN_RANK[to_p["allergen_class"]]:
        level = "FULL_SANITATION"          # allergen downgrade
    else:
        level = "WET_WASH"                 # allergen upgrade
    base = LEVEL_BASE_MIN[level]
    penalty = DIAMETER_PENALTY_MIN if (from_p["diameter_in"] != to_p["diameter_in"]
                                       and level != "FULL_SANITATION") else 0
    return level, base + penalty


def prev_run_on_line(line_id, start_at):
    """Immediately-preceding non-CANCELLED run ending at or before start_at."""
    best = None
    for r in store.runs.values():
        if r["line_id"] != line_id or r["production_status"] == "CANCELLED":
            continue
        if r["end_at"] <= start_at and (best is None or r["end_at"] > best["end_at"]):
            best = r
    return best


def masa_required_kg(product, planned_cases):
    raw = (Decimal(planned_cases) * Decimal(product["packs_per_case"])
           * Decimal(product["count_per_pack"]) * product["unit_weight_g"]
           / Decimal("1000") * MASA_LOSS_FACTOR)
    return r2(raw)


# ---- cascades ----
def cancel_gating_changeover(run):
    for c in store.changeovers.values():
        if (c["production_run_id"] == run["id"]
                and c["changeover_status"] in ("REQUIRED", "IN_PROGRESS", "FAILED")):
            c["changeover_status"] = "CANCELLED"
            touch(c)


def demote_run_if_uncovered(run):
    """SCHEDULED run whose RESERVED coverage fell below required -> PLANNED."""
    if (run["production_status"] == "SCHEDULED"
            and run_masa_reserved(run["id"]) < run["masa_required_kg"]):
        run["production_status"] = "PLANNED"
        cancel_gating_changeover(run)


def release_allocation(alloc):
    alloc["allocation_status"] = "RELEASED"
    touch(alloc)
    batch = store.nixtamal_batches.get(alloc["nixtamal_batch_id"])
    if batch is not None:
        touch(batch)  # masa_available_kg restored (derived)
    run = store.runs.get(alloc["production_run_id"])
    if run is not None:
        demote_run_if_uncovered(run)
        touch(run)  # masa_reserved_kg recomputed


def batch_quarantine_cascade(batch):
    """Release RESERVED allocations, demote uncovered SCHEDULED runs, cancel changeovers."""
    affected_runs = []
    for a in store.allocations.values():
        if a["nixtamal_batch_id"] == batch["id"] and a["allocation_status"] == "RESERVED":
            a["allocation_status"] = "RELEASED"
            touch(a)
            if a["production_run_id"] not in affected_runs:
                affected_runs.append(a["production_run_id"])
    for rid in affected_runs:
        run = store.runs.get(rid)
        if run is not None:
            demote_run_if_uncovered(run)
            touch(run)


def maybe_deplete_batch(batch):
    if (batch["batch_status"] == "MASA_AVAILABLE"
            and batch["actual_masa_kg"] is not None
            and batch["actual_masa_kg"] > 0
            and batch_masa_available(batch) == 0):
        batch["batch_status"] = "DEPLETED"
        touch(batch)


def short_stop(stop):
    """ALLOCATED -> SHORTED: restock pack, refund route (both derived)."""
    stop["stop_status"] = "SHORTED"
    touch(stop)
    pack = store.pack_orders.get(stop["pack_order_id"])
    if pack is not None:
        touch(pack)  # cases_available restored
    route = store.routes.get(stop["route_id"])
    if route is not None:
        touch(route)  # committed_cases reduced
        window = active_strict_window_for_date(route["route_date"])
        if window is not None:
            allot = find_allotment(window["id"], stop["customer_id"])
            if allot is not None:
                touch(allot)  # consumed_cases refunded (derived)


# ---- serializers ----
def lot_json(lot):
    return {
        "id": lot["id"], "lot_code": lot["lot_code"],
        "corn_variety": lot["corn_variety"],
        "received_kg": num(lot["received_kg"]),
        "moisture_pct": num(lot["moisture_pct"]),
        "drawn_kg": num(r2(lot_drawn_kg(lot["id"]))),
        "available_kg": num(r2(lot_available_kg(lot))),
        "lot_status": lot["lot_status"],
        "created_at": lot["created_at"], "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def batch_json(b):
    return {
        "id": b["id"], "ingredient_lot_id": b["ingredient_lot_id"],
        "corn_kg": num(b["corn_kg"]), "lime_pct": num(b["lime_pct"]),
        "cook_minutes": b["cook_minutes"], "steep_target_hours": b["steep_target_hours"],
        "cook_started_at": b["cook_started_at"],
        "steep_started_at": b["steep_started_at"],
        "recook_count": b["recook_count"],
        "theoretical_masa_kg": num(b["theoretical_masa_kg"]),
        "actual_masa_kg": num(b["actual_masa_kg"]),
        "masa_wasted_kg": num(b["masa_wasted_kg"]),
        "masa_available_kg": num(r2(batch_masa_available(b))),
        "yield_variance_pct": num(b["yield_variance_pct"]),
        "batch_status": b["batch_status"],
        "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
    }


def product_json(p):
    return {
        "id": p["id"], "sku_code": p["sku_code"], "diameter_in": p["diameter_in"],
        "count_per_pack": p["count_per_pack"], "packs_per_case": p["packs_per_case"],
        "unit_weight_g": num(p["unit_weight_g"]), "channel": p["channel"],
        "preservative_system": p["preservative_system"],
        "shelf_life_days": p["shelf_life_days"], "allergen_class": p["allergen_class"],
        "weight_tolerance_pct": num(p["weight_tolerance_pct"]),
        "declared_pack_net_g": num(p["declared_pack_net_g"]),
        "declared_case_net_g": num(p["declared_case_net_g"]),
        "product_status": p["product_status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def line_json(l):
    return {
        "id": l["id"], "line_code": l["line_code"], "allergen_zone": l["allergen_zone"],
        "cases_per_hour": l["cases_per_hour"], "current_product_id": l["current_product_id"],
        "line_posture": line_posture(l["id"]), "line_status": l["line_status"],
        "created_at": l["created_at"], "updated_at": l["updated_at"],
        "version": l["version"],
    }


def run_json(r):
    return {
        "id": r["id"], "product_id": r["product_id"], "line_id": r["line_id"],
        "planned_cases": r["planned_cases"],
        "start_at": fmt_dt(r["start_at"]), "end_at": fmt_dt(r["end_at"]),
        "masa_required_kg": num(r["masa_required_kg"]),
        "masa_reserved_kg": num(r2(run_masa_reserved(r["id"]))),
        "produced_cases": run_produced_cases(r["id"]),
        "production_status": r["production_status"], "qc_status": r["qc_status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def alloc_json(a):
    return {
        "id": a["id"], "nixtamal_batch_id": a["nixtamal_batch_id"],
        "production_run_id": a["production_run_id"],
        "allocated_kg": num(a["allocated_kg"]),
        "allocation_status": a["allocation_status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def changeover_json(c):
    return {
        "id": c["id"], "line_id": c["line_id"],
        "from_product_id": c["from_product_id"], "to_product_id": c["to_product_id"],
        "production_run_id": c["production_run_id"],
        "required_level": c["required_level"],
        "required_downtime_min": c["required_downtime_min"],
        "performed_by": c["performed_by"], "fail_count": c["fail_count"],
        "changeover_status": c["changeover_status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def pack_json(p):
    return {
        "id": p["id"], "production_run_id": p["production_run_id"],
        "cases_planned": p["cases_planned"],
        "verification_method": p["verification_method"],
        "cases_packed": p["cases_packed"],
        "avg_pack_weight_g": num(p["avg_pack_weight_g"]),
        "count_accuracy_pct": num(p["count_accuracy_pct"]),
        "cases_available": pack_cases_available(p),
        "sealed_at": p["sealed_at"], "expires_on": p["expires_on"],
        "pack_status": p["pack_status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def customer_json(c):
    return {
        "id": c["id"], "account_name": c["account_name"], "channel": c["channel"],
        "region": c["region"], "base_weekly_cases": c["base_weekly_cases"],
        "priority_tier": c["priority_tier"],
        "min_shelf_life_pct": c["min_shelf_life_pct"],
        "credit_standing": c["credit_standing"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def window_json(w):
    return {
        "id": w["id"], "window_name": w["window_name"],
        "starts_on": w["starts_on"].isoformat(), "ends_on": w["ends_on"].isoformat(),
        "demand_multiplier": num(w["demand_multiplier"]),
        "forecast_total_cases": w["forecast_total_cases"],
        "is_strict": w["is_strict"], "window_status": w["window_status"],
        "created_at": w["created_at"], "updated_at": w["updated_at"],
        "version": w["version"],
    }


def allotment_json(a):
    consumed = allotment_consumed_cases(a)
    return {
        "id": a["id"], "seasonal_window_id": a["seasonal_window_id"],
        "customer_id": a["customer_id"], "allotted_cases": a["allotted_cases"],
        "consumed_cases": consumed,
        "remaining_cases": a["allotted_cases"] - consumed,
        "allotment_status": a["allotment_status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def route_json(r):
    committed = route_committed_cases(r["id"])
    return {
        "id": r["id"], "route_code": r["route_code"],
        "route_date": r["route_date"].isoformat(), "region": r["region"],
        "vehicle_capacity_cases": r["vehicle_capacity_cases"],
        "committed_cases": committed,
        "open_cases": r["vehicle_capacity_cases"] - committed,
        "route_status": r["route_status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def stop_json(s):
    shortage = 0
    if s["stop_status"] == "DELIVERED" and s["delivered_cases"] is not None:
        shortage = s["allocated_cases"] - s["delivered_cases"]
    return {
        "id": s["id"], "route_id": s["route_id"], "customer_id": s["customer_id"],
        "pack_order_id": s["pack_order_id"], "requested_cases": s["requested_cases"],
        "allocated_cases": s["allocated_cases"], "delivered_cases": s["delivered_cases"],
        "shortage_cases": shortage, "stop_status": s["stop_status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }

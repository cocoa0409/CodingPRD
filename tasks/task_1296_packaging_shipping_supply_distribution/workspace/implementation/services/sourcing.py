"""Warehouse sourcing selector, allocation pass, promise dates, press occupancy,
restock-notification crossing checks (PRD §3.3/§3.4/§3.6/§3.9)."""
import db
from errors import (err_no_warehouse_capable, err_backorder_not_allowed)
from services.pricing import order_lines_of
from util import business_days_after_date, business_days_after_dt
from zoneinfo import ZoneInfo


# ---------------------------------------------------------------------------
# Sourcing selector (deterministic)
# ---------------------------------------------------------------------------
def candidate_warehouses(line, product):
    cands = []
    for w in db.warehouses.values():
        if w["status"] != "ACTIVE":
            continue
        if line["requested_warehouse_code"] is not None and w["code"] != line["requested_warehouse_code"]:
            continue
        if product["oversize"] and not w["oversize_capable"]:
            continue
        if not product["is_custom_print"]:
            if db.inventory_by_pair.get((product["id"], w["id"])) is None:
                continue
        cands.append(w)
    cands.sort(key=lambda w: w["_seq"])
    return cands


def _rank_stock(cands, line, order, account, avail_fn):
    def key(w):
        return (
            0 if avail_fn(w) >= line["qty"] else 1,          # full cover first
            abs(order["ship_zone"] - w["zone"]),             # nearest zone
            0 if w["code"] == account["default_warehouse_code"] else 1,
            w["code"],                                       # final tie-break: code
        )
    return sorted(cands, key=key)


def _rank_custom(cands, order, account):
    def key(w):
        return (
            abs(order["ship_zone"] - w["zone"]),
            0 if w["code"] == account["default_warehouse_code"] else 1,
            w["code"],
        )
    return sorted(cands, key=key)


def simulate_allocation(order, account):
    """Pure (no mutation) allocation pass. Returns a list of decisions:
    {line, warehouse, outcome} with outcome in
    ALLOCATED | BACKORDERED | CUSTOM | NO_CANDIDATES | SHORT_NO_BACKORDER.
    Sequential overlay: earlier reservations reduce later availability."""
    lines = [l for l in order_lines_of(order["id"]) if l["status"] in ("OPEN",)]
    overlay = {}  # inventory_id -> additional reserved qty within this pass
    decisions = []
    for line in lines:
        product = db.products[line["product_id"]]
        cands = candidate_warehouses(line, product)
        if not cands:
            decisions.append({"line": line, "warehouse": None, "outcome": "NO_CANDIDATES"})
            continue
        if product["is_custom_print"]:
            wh = _rank_custom(cands, order, account)[0]
            decisions.append({"line": line, "warehouse": wh, "outcome": "CUSTOM"})
            continue

        def avail(w):
            inv_id = db.inventory_by_pair.get((product["id"], w["id"]))
            inv = db.inventory[inv_id]
            return inv["on_hand_qty"] - inv["reserved_qty"] - overlay.get(inv_id, 0)

        wh = _rank_stock(cands, line, order, account, avail)[0]
        inv = db.inventory[db.inventory_by_pair[(product["id"], wh["id"])]]
        if avail(wh) >= line["qty"]:
            overlay[inv["id"]] = overlay.get(inv["id"], 0) + line["qty"]
            decisions.append({"line": line, "warehouse": wh, "outcome": "ALLOCATED"})
        elif inv["backorderable"]:
            decisions.append({"line": line, "warehouse": wh, "outcome": "BACKORDERED"})
        else:
            decisions.append({"line": line, "warehouse": wh, "outcome": "SHORT_NO_BACKORDER"})
    return decisions


def allocation_error(decisions):
    """Priority 13 (NO_WAREHOUSE_CAPABLE) fires before 14 (BACKORDER_NOT_ALLOWED)."""
    if any(d["outcome"] == "NO_CANDIDATES" for d in decisions):
        return err_no_warehouse_capable()
    if any(d["outcome"] == "SHORT_NO_BACKORDER" for d in decisions):
        return err_backorder_not_allowed()
    return None


def apply_allocation(order, decisions):
    """Commit a successful simulation: reservations, line statuses, print jobs."""
    now = db.now()
    for d in decisions:
        line = d["line"]
        wh = d["warehouse"]
        line["allocated_warehouse_id"] = wh["id"]
        if d["outcome"] == "ALLOCATED":
            inv = db.inventory[db.inventory_by_pair[(line["product_id"], wh["id"])]]
            inv["reserved_qty"] += line["qty"]
            db.touch(inv)
            line["status"] = "ALLOCATED"
        elif d["outcome"] == "BACKORDERED":
            line["status"] = "BACKORDERED"
        elif d["outcome"] == "CUSTOM":
            create_print_job(line, wh)
            line["status"] = "IN_PRODUCTION"
            line["_ready_date"] = business_days_after_date(now.date(),
                                                           db.products[line["product_id"]]["lead_time_days"])
        db.touch(line)


def create_print_job(line, warehouse):
    now = db.now()
    job = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "order_line_id": line["id"],
        "warehouse_id": warehouse["id"],
        "status": "QUEUED",
        "actual_qty": None,
        "receive_note": None,
        "started_at": None,
        "occupied_until": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.custom_print_jobs[job["id"]] = job
    return job


def live_job_for_line(line_id):
    """The most recently created job for a line (exactly one live at a time)."""
    jobs = [j for j in db.custom_print_jobs.values() if j["order_line_id"] == line_id]
    if not jobs:
        return None
    jobs.sort(key=lambda j: j["_seq"])
    return jobs[-1]


def derive_order_status(order):
    lines = order_lines_of(order["id"])
    if any(db.products[l["product_id"]]["is_custom_print"] for l in lines):
        return "CUSTOM_PRODUCTION"
    if any(l["status"] == "BACKORDERED" for l in lines):
        return "PARTIALLY_BACKORDERED"
    return "STOCK_RESERVED"


# ---------------------------------------------------------------------------
# Promise dates (calc_same_day_cutoff + calc_custom_lead_time)
# ---------------------------------------------------------------------------
def stock_promise_date(order):
    """Latest of the per-warehouse same-day/next-day promises (stock lines only;
    custom lines contribute their lead-time projection instead)."""
    dates = []
    now = db.now()
    for line in order_lines_of(order["id"]):
        if db.products[line["product_id"]]["is_custom_print"]:
            continue
        wid = line["allocated_warehouse_id"]
        if wid is None:
            continue
        w = db.warehouses[wid]
        local = now.astimezone(ZoneInfo(w["timezone"]))
        cutoff_h, cutoff_m = (int(x) for x in w["ship_cutoff_time"].split(":"))
        if (local.hour, local.minute) < (cutoff_h, cutoff_m):
            dates.append(local.date())
        else:
            dates.append(business_days_after_date(local.date(), 1))
    return max(dates) if dates else None


def compute_order_promise(order):
    """max(stock promise, per-custom-line lead-time ready dates)."""
    candidates = []
    if order.get("_stock_promise") is not None:
        candidates.append(order["_stock_promise"])
    for line in order_lines_of(order["id"]):
        if line.get("_ready_date") is not None:
            candidates.append(line["_ready_date"])
    return max(candidates) if candidates else None


# ---------------------------------------------------------------------------
# Restock notification crossing check
# ---------------------------------------------------------------------------
def fire_notifications_for_crossing(inv, available_before):
    """Fire ACTIVE subscriptions when available_qty crosses from strictly below
    reorder_point_qty to at or above it."""
    available_after = inv["on_hand_qty"] - inv["reserved_qty"]
    rp = inv["reorder_point_qty"]
    if available_before < rp <= available_after:
        product_id = inv["product_id"]
        for n in db.restock_notifications.values():
            if n["product_id"] == product_id and n["status"] == "ACTIVE":
                n["status"] = "NOTIFIED"
                n["notified_at"] = db.now()
                db.touch(n)


# ---------------------------------------------------------------------------
# Press occupancy (custom print job start)
# ---------------------------------------------------------------------------
def press_occupancy_conflict(job, warehouse, product):
    """True when starting would meet/exceed press_count overlapping occupancies."""
    now = db.now()
    new_start = now
    new_end = business_days_after_dt(now, product["lead_time_days"])
    count = 0
    for other in db.custom_print_jobs.values():
        if other["id"] == job["id"]:
            continue
        if other["warehouse_id"] != warehouse["id"]:
            continue
        if other["status"] not in ("PLATING", "PRINTING"):
            continue
        # half-open [started_at, occupied_until) intersect [new_start, new_end)
        if new_start < other["occupied_until"] and other["started_at"] < new_end:
            count += 1
    return count >= warehouse["press_count"]

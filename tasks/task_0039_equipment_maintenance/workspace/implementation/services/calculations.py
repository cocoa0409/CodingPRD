"""Calculation rules per SCAFFOLD §1.3 and PRD §3.5/§3.8/§3.9."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db


# --- priority_score ----------------------------------------------------

CRITICALITY_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 4}
TEMPLATE_PRIORITY_WEIGHT = {"P1": 8, "P2": 4, "P3": 2, "P4": 1}
SOURCE_BONUS = {"ALARM": 4, "PLAN_TRIGGER": 2, "PLAN_PERIODIC": 1, "AD_HOC": 1}


def compute_priority_score(equipment, template, source):
    cw = CRITICALITY_WEIGHT[equipment["criticality"]]
    tw = TEMPLATE_PRIORITY_WEIGHT[template["default_priority"]]
    sb = SOURCE_BONUS[source]
    return cw * tw + sb


def bucket_for_score(score):
    if score >= 30:
        return "P1"
    if score >= 20:
        return "P2"
    if score >= 8:
        return "P3"
    return "P4"


# --- sla_minutes_for_priority ------------------------------------------

SLA_MINUTES = {"P1": 240, "P2": 480, "P3": 1440, "P4": 4320}


def sla_due_at(opened_at, priority):
    minutes = SLA_MINUTES[priority]
    return opened_at + timedelta(seconds=minutes * 60)


def recompute_sla_breached(work_order, site_clock):
    if work_order["status"] in {"COMPLETED", "CLOSED", "CANCELLED"}:
        work_order["sla_breached"] = False
    else:
        work_order["sla_breached"] = site_clock > work_order["sla_due_at"]


# --- technician_selector -----------------------------------------------

def select_technician(site_id, required_skill, exclude_ids=None):
    """Return Technician.id of best candidate or None.

    Ranking: open_load ASC, created_at ASC, id ASC.
    """
    exclude_ids = set(exclude_ids or [])
    candidates = []
    for t in db.technicians_for_site(site_id):
        if t["status"] != "ACTIVE":
            continue
        if required_skill not in t["skills"]:
            continue
        if t["id"] in exclude_ids:
            continue
        candidates.append(t)
    if not candidates:
        return None
    # open_load is computed live
    candidates.sort(key=lambda t: (compute_open_load(t["id"]), t["created_at"], t["id"]))
    return candidates[0]["id"]


def compute_open_load(tech_id):
    return sum(
        1
        for w in db.work_orders.values()
        if w.get("assigned_technician_id") == tech_id
        and w["status"] in {"PENDING", "IN_PROGRESS", "PAUSED"}
    )


def refresh_technician_open_loads(site_id):
    for t in db.technicians_for_site(site_id):
        t["open_load"] = compute_open_load(t["id"])


# --- replenish_evaluator -----------------------------------------------

def replenish_eval(spare_part):
    available = spare_part["stock_on_hand"] - spare_part["stock_reserved"]
    if available <= spare_part["reorder_point"]:
        if not spare_part["replenish_pending"]:
            spare_part["replenish_pending"] = True
    else:
        if spare_part["replenish_pending"]:
            spare_part["replenish_pending"] = False


# --- parts_cost --------------------------------------------------------

def compute_parts_cost(work_order_id):
    """Sum line costs over ISSUED requisitions in created_at ASC order.

    Per-line, before sum: if qty_used >= 10, line_cost = floor(line_cost * 0.90).
    """
    requisitions = [
        r for r in db.requisitions.values()
        if r["work_order_id"] == work_order_id and r["status"] == "ISSUED"
    ]
    requisitions.sort(key=lambda r: (r["created_at"], r["id"]))
    total = 0
    for r in requisitions:
        qty_used = r["qty"] - r["returned_qty"]
        if qty_used <= 0:
            continue
        unit_cost = r.get("unit_cost_cents_at_issue") or 0
        line_cost = qty_used * unit_cost
        if qty_used >= 10:
            # floor of line_cost * 0.90, in integer cents
            # Use Decimal for exact arithmetic.
            line_cost = int((Decimal(line_cost) * Decimal("0.90")).to_integral_value(rounding="ROUND_FLOOR"))
        total += line_cost
    return total


# --- analytics rounding -----------------------------------------------

def round_half_up(value, places):
    if value is None:
        return None
    q = Decimal(10) ** -places
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def parts_replaced_snapshot(work_order_id):
    """Build the parts_replaced array at completion time."""
    rows = []
    requisitions = [
        r for r in db.requisitions.values()
        if r["work_order_id"] == work_order_id and r["status"] == "ISSUED"
    ]
    requisitions.sort(key=lambda r: (r["created_at"], r["id"]))
    for r in requisitions:
        qty_used = r["qty"] - r["returned_qty"]
        rows.append({
            "requisition_id": r["id"],
            "part_id": r["part_id"],
            "qty_used": qty_used,
            "unit_cost_cents": r.get("unit_cost_cents_at_issue"),
        })
    return rows

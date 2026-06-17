"""Domain helpers: entity touch/serialize, derived recomputation, cascades.

Storage is in-memory dicts in db.db. Money is stored on entities as floats
(2 dp values), recomputed from Decimal math on each mutation.
"""
from db import db, new_id, now_iso
from services import calc


# ---------------------------------------------------------------------------
# common system-field helpers
# ---------------------------------------------------------------------------
def stamp_create(entity, with_version=True):
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    """A mutation: refresh updated_at and bump version."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity["version"] + 1


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def order_lines(order_id):
    return [l for l in db.frame_lines.values() if l["order_id"] == order_id]


def non_void_lines_sorted(order_id):
    lines = [l for l in order_lines(order_id) if l["line_status"] != "VOID"]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    return lines


def measured_lines_sorted(order_id):
    lines = [l for l in order_lines(order_id) if l["line_status"] == "MEASURED"]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    return lines


def order_payments_applied_sorted(order_id):
    pays = [
        p
        for p in db.payments.values()
        if p["order_id"] == order_id and p["payment_status"] == "APPLIED"
    ]
    pays.sort(key=lambda p: (p["created_at"], p["id"]))
    return pays


def order_tasks(order_id):
    return [t for t in db.production_tasks.values() if t["order_id"] == order_id]


def customer_orders(customer_id):
    return [o for o in db.framing_orders.values() if o["customer_id"] == customer_id]


# ---------------------------------------------------------------------------
# fragility
# ---------------------------------------------------------------------------
def compute_has_fragile_line(order_id):
    for l in order_lines(order_id):
        if l["line_status"] == "VOID":
            continue
        if l["glass_type"] == "MUSEUM" or bool(l["is_fragile"]):
            return True
    return False


def recompute_has_fragile_line(order):
    order["has_fragile_line"] = compute_has_fragile_line(order["id"])


# ---------------------------------------------------------------------------
# ledger recompute (amount_paid, balance_due)
# ---------------------------------------------------------------------------
def recompute_ledger(order):
    applied = order_payments_applied_sorted(order["id"])
    amount_paid, balance_due = calc.order_ledger(
        applied, order["estimate_total"], order["final_invoice_total"]
    )
    order["amount_paid"] = calc.to_float(amount_paid)
    order["balance_due"] = calc.to_float(balance_due)


# ---------------------------------------------------------------------------
# Customer derived scores
# ---------------------------------------------------------------------------
def open_orders_for_customer(customer_id):
    return [
        o
        for o in customer_orders(customer_id)
        if o["production_status"] not in ("PICKED_UP", "CANCELLED")
    ]


def settled_outcomes_chronological(customer_id):
    """Replay terminal orders in terminal-transition created_at order.

    The terminal transition time is recorded on the order as
    _terminal_at when it reaches PICKED_UP or CANCELLED.
    """
    terminal = [
        o
        for o in customer_orders(customer_id)
        if o["production_status"] in ("PICKED_UP", "CANCELLED")
    ]
    terminal.sort(key=lambda o: (o.get("_terminal_at") or o["updated_at"], o["id"]))
    outcomes = []
    for o in terminal:
        if o["production_status"] == "PICKED_UP":
            outcomes.append("ONTIME")
        else:
            outcomes.append("ABANDON")
    return outcomes


def recompute_customer_open_and_risk(customer):
    opens = open_orders_for_customer(customer["id"])
    customer["open_order_count"] = len(opens)
    customer["no_show_risk_score"] = calc.forward_no_show_risk(opens)


def recompute_customer_reputation(customer):
    outcomes = settled_outcomes_chronological(customer["id"])
    customer["settled_reputation_score"] = calc.settled_reputation(outcomes)


def refresh_customer_derived(customer):
    """Recompute all derived customer fields (used on read)."""
    customer["loyalty_discount_pct"] = calc.to_float(calc.LOYALTY_DISCOUNT[customer["loyalty_tier"]])
    recompute_customer_open_and_risk(customer)
    recompute_customer_reputation(customer)


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------
def serialize_customer(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "full_name": c["full_name"],
        "email": c["email"],
        "phone": c["phone"],
        "loyalty_tier": c["loyalty_tier"],
        "loyalty_discount_pct": c["loyalty_discount_pct"],
        "open_order_count": c["open_order_count"],
        "no_show_risk_score": c["no_show_risk_score"],
        "settled_reputation_score": c["settled_reputation_score"],
    }


def serialize_workbench(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
        "bench_name": w["bench_name"],
        "bench_type": w["bench_type"],
        "clean_buffer_minutes": w["clean_buffer_minutes"],
    }


def serialize_order(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "customer_id": o["customer_id"],
        "reorder_of_order_id": o["reorder_of_order_id"],
        "rush_requested": o["rush_requested"],
        "deposit_pct": o["deposit_pct"],
        "production_status": o["production_status"],
        "payment_status": o["payment_status"],
        "has_fragile_line": o["has_fragile_line"],
        "estimate_total": o["estimate_total"],
        "deposit_required": o["deposit_required"],
        "final_invoice_total": o["final_invoice_total"],
        "amount_paid": o["amount_paid"],
        "balance_due": o["balance_due"],
        "turnaround_days": o["turnaround_days"],
    }


def serialize_line(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "order_id": l["order_id"],
        "artwork_label": l["artwork_label"],
        "nominal_width_in": l["nominal_width_in"],
        "nominal_height_in": l["nominal_height_in"],
        "measured_width_in": l["measured_width_in"],
        "measured_height_in": l["measured_height_in"],
        "mat_border_in": l["mat_border_in"],
        "mat_layers": l["mat_layers"],
        "glass_type": l["glass_type"],
        "molding_rate_per_ui": l["molding_rate_per_ui"],
        "mounting_type": l["mounting_type"],
        "conservation_package": l["conservation_package"],
        "is_fragile": l["is_fragile"],
        "line_status": l["line_status"],
        "estimate_subtotal": l["estimate_subtotal"],
        "final_subtotal": l["final_subtotal"],
    }


def serialize_task(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "order_id": t["order_id"],
        "workbench_id": t["workbench_id"],
        "start_minute": t["start_minute"],
        "end_minute": t["end_minute"],
        "task_status": t["task_status"],
    }


def serialize_payment(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "order_id": p["order_id"],
        "kind": p["kind"],
        "amount": p["amount"],
        "payment_status": p["payment_status"],
    }


def serialize_notification(n):
    # Notification carries only id and created_at (plus its data fields). No
    # version/updated_at per PRD §2.4.
    return {
        "id": n["id"],
        "created_at": n["created_at"],
        "order_id": n["order_id"],
        "channel": n["channel"],
        "kind": n["kind"],
        "sent_to": n["sent_to"],
    }

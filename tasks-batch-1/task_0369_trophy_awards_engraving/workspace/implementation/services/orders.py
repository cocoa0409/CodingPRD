"""Order-centric helpers: ownership, line lookup, cascades."""
from db import db
from errors import err


def get_order_or_404(order_id):
    o = db.orders.get(order_id)
    if o is None:
        raise err("ERR_NOT_FOUND", "Order not found")
    return o


def get_line_or_404(line_id):
    l = db.order_lines.get(line_id)
    if l is None:
        raise err("ERR_NOT_FOUND", "Order line not found")
    return l


def get_proof_or_404(proof_id):
    p = db.proofs.get(proof_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Proof not found")
    return p


def get_fulfillment_or_404(fid):
    f = db.fulfillments.get(fid)
    if f is None:
        raise err("ERR_NOT_FOUND", "Fulfillment not found")
    return f


def enforce_order_ownership(caller, order):
    """Customers may only act on orders they own (PRD §2.1)."""
    if caller.role == "Customer" and order["customer_id"] != caller.user_id:
        raise err("ERR_FORBIDDEN", "Customer does not own this order")


def lines_for_order(order_id):
    items = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    return sorted(items, key=lambda l: (l["created_at"], l["id"]))


def proofs_for_line(line_id):
    items = [p for p in db.proofs.values() if p["order_line_id"] == line_id]
    return sorted(items, key=lambda p: (p["created_at"], p["id"]))


def allocations_for_line(line_id):
    return [a for a in db.component_allocations.values() if a["order_line_id"] == line_id]


def line_has_approved_proof(line_id):
    return any(p["proof_status"] == "APPROVED" for p in db.proofs.values()
              if p["order_line_id"] == line_id)


def order_of_line(line):
    return db.orders.get(line["order_id"])

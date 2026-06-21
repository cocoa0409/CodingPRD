"""Serialization: strip internal fields, compute derived fields for output."""
from db import db


def _public(rec, fields):
    out = {}
    for f in fields:
        if f in rec:
            out[f] = rec[f]
    return out


RESORT_FIELDS = ["id", "name", "home_network", "status", "gate_count",
                 "created_at", "updated_at", "version"]

PASS_PRODUCT_FIELDS = ["id", "tier", "price_cents", "blackout_dates",
                       "buddy_ticket_allotment", "buddy_ticket_price_cents",
                       "ikon_interchange_enabled",
                       "created_at", "updated_at", "version"]

PASS_FIELDS = ["id", "pass_product_id", "holder_name", "magnetic_token",
               "status", "activated_on", "scan_count", "buddy_tickets_remaining",
               "refund_basis_cents", "created_at", "updated_at", "version"]

LIFT_SCAN_FIELDS = ["id", "pass_id", "resort_id", "presented_token",
                    "scan_at", "scan_date", "result", "denial_reason",
                    "created_at"]

BUDDY_TICKET_FIELDS = ["id", "pass_id", "resort_id", "guest_name", "valid_date",
                       "price_charged_cents", "status",
                       "created_at", "updated_at", "version"]

REFUND_REQUEST_FIELDS = ["id", "pass_id", "reason", "scan_count_at_request",
                         "refund_amount_cents", "status",
                         "created_at", "updated_at", "version"]

INTERCHANGE_FIELDS = ["id", "resort_id", "max_interchange_days", "status",
                      "created_at", "updated_at", "version"]


def resort_out(r):
    return _public(r, RESORT_FIELDS)


def pass_product_out(p):
    return _public(p, PASS_PRODUCT_FIELDS)


def pass_out(p):
    out = _public(p, PASS_FIELDS)
    out["scan_count"] = compute_scan_count(p["id"])
    # buddy_tickets_remaining is a stored field maintained by the mutation
    # routes (0 at issuance, allotment at activation, recomputed on
    # reservation/cancellation and pass cascades). It is NOT recomputed on
    # plain reads: an ISSUED pass reads 0 even though its product carries a
    # positive allotment (PRD §3.2 issuance defaults).
    out["buddy_tickets_remaining"] = p.get("buddy_tickets_remaining", 0)
    return out


def lift_scan_out(s):
    return _public(s, LIFT_SCAN_FIELDS)


def buddy_ticket_out(b):
    return _public(b, BUDDY_TICKET_FIELDS)


def refund_request_out(r):
    return _public(r, REFUND_REQUEST_FIELDS)


def interchange_out(a):
    return _public(a, INTERCHANGE_FIELDS)


# --- computed-field helpers (also used internally) ---

def compute_scan_count(pass_id):
    return sum(
        1 for s in db.lift_scans.values()
        if s["pass_id"] == pass_id and s["result"] == "GRANTED"
    )


def compute_buddy_remaining(pass_rec):
    product = db.pass_products.get(pass_rec["pass_product_id"])
    allotment = product["buddy_ticket_allotment"] if product else 0
    consumed = sum(
        1 for b in db.buddy_tickets.values()
        if b["pass_id"] == pass_rec["id"] and b["status"] in ("RESERVED", "REDEEMED")
    )
    return allotment - consumed

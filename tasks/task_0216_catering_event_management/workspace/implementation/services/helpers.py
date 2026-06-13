"""Shared service helpers: entity lookups, OCC checks, ledger balance,
route-posture recompute, staffing-reservation lookup.
"""
from common import touch
from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_STALE_ORDER_VERSION, ERR_INVALID_REQUEST,
)
from services import calculations


# ---------------------------------------------------------------------------
# Lookups (PRD §2.6: existence -> ERR_NOT_FOUND 404, left-to-right)
# ---------------------------------------------------------------------------
def get_or_404(table, _id):
    if _id not in table:
        raise err(ERR_NOT_FOUND, "resource not found: %s" % _id)
    return table[_id]


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def append_ledger(order_id, entry_type, amount_cents, reason=""):
    from common import stamp_create
    entry = {
        "order_id": order_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reason": reason,
    }
    stamp_create(entry, with_version=False)
    db.ledger_entries[entry["id"]] = entry
    return entry


def ledger_balance(order_id):
    """Running sum of an order's ledger entries in created_at ASC (PRD §2.8)."""
    entries = [e for e in db.ledger_entries.values() if e["order_id"] == order_id]
    entries.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return sum(e["amount_cents"] for e in entries)


# ---------------------------------------------------------------------------
# Route posture recompute (PRD §2.5 cascade; bumps route version)
# ---------------------------------------------------------------------------
def recompute_route(route):
    route["posture"] = calculations.route_posture(route["id"])
    route["dispatched_leg_count"] = calculations.dispatched_leg_count(route["id"])
    touch(route)


# ---------------------------------------------------------------------------
# Staffing reservation lookup
# ---------------------------------------------------------------------------
def order_reservation(order_id):
    for r in db.staffing_reservations.values():
        if r["order_id"] == order_id:
            return r
    return None


def staffing_demand(order_id):
    """Sum of STAFFING AddOnLine effective quantities at confirmation.

    At confirmation the effective quantity is the stored quantity (provisional
    semantics) — per_head scaling only recomputes at invoice (SCAFFOLD entity
    StaffingReservation.reserved_staff, PRD §3.5).
    """
    total = 0
    for a in db.add_ons.values():
        if a["order_id"] == order_id and a["kind"] == "STAFFING":
            total += a["quantity"]
    return total


# ---------------------------------------------------------------------------
# OCC against the parent Order (PRD §2.11)
# ---------------------------------------------------------------------------
def parse_order_version(body):
    """Body well-formedness for expected_order_version (PRD §3.12 body stage).

    Validates presence and type only; the value-mismatch check is a business
    rule that runs after the state check (see check_order_version).
    """
    if "expected_order_version" not in body or body["expected_order_version"] is None:
        raise err(ERR_INVALID_REQUEST, "expected_order_version is required")
    expected = body["expected_order_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, "expected_order_version must be an integer")
    return expected


def check_order_version(expected, order):
    """OCC mismatch check (PRD §2.11) — runs after the state check."""
    if expected != order["version"]:
        raise err(ERR_STALE_ORDER_VERSION,
                  "expected_order_version does not match order version")


def require_order_version(body, order):
    """Convenience: parse + check in one call (presence/type then mismatch)."""
    check_order_version(parse_order_version(body), order)

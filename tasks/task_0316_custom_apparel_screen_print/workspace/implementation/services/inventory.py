"""Blank inventory accounting and the conservation invariant (PRD §2.8, §3.4, §3.8).

For every BlankSku: on_hand_qty + sum(reserved_qty over ACTIVE reservations)
== total_stock_qty. A confirm moves units on_hand -> reserved; a cancel moves
them back (RELEASED); fulfillment CONSUMES, returning only the unused allowance.
Each mutated resource is touched (updated_at + version bump, PRD §2.4).
"""
from db import touch


def reserve(sku, qty):
    """Hold `qty` units on the SKU: reserved_qty += qty, on_hand_qty -= qty."""
    sku["reserved_qty"] += qty
    sku["on_hand_qty"] -= qty
    touch(sku)


def release(sku, qty):
    """Cancel path: return the full hold. reserved_qty -= qty, on_hand_qty += qty."""
    sku["reserved_qty"] -= qty
    sku["on_hand_qty"] += qty
    touch(sku)


def consume(sku, reserved_qty, released_units):
    """Fulfillment path: clear the hold; return only the unused allowance.

    on_hand_qty += released_units (leftover allowance not used by the run),
    reserved_qty -= reserved_qty (the entire hold clears). The blanks the run
    actually kept are a terminal sink and never return to on_hand (PRD §3.8).
    """
    sku["on_hand_qty"] += released_units
    sku["reserved_qty"] -= reserved_qty
    touch(sku)


def restock(sku, add_qty):
    """Grow the conserved total: total_stock_qty += add_qty, on_hand_qty += add_qty."""
    sku["total_stock_qty"] += add_qty
    sku["on_hand_qty"] += add_qty
    touch(sku)

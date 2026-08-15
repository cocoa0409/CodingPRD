"""Shared helpers: entity lookup, ownership, terminal-state guards, seal-kit
compatibility, and the stock reservation/cutting procedure."""

from db import DB, make_entity, touch
from calc import select_stock_piece, shop_config
from errors import (
    err_not_found,
    err_not_owner,
    err_invalid_state,
    err_already_terminal,
    err_seal_kit,
    err_no_stock,
)


def get_or_404(store_dict, entity_id):
    entity = store_dict.get(entity_id)
    if entity is None:
        raise err_not_found("Resource not found: %s" % entity_id)
    return entity


def check_customer_owns(actor, owner_customer_id):
    if actor.role == "Customer" and actor.user_id != owner_customer_id:
        raise err_not_owner("Customer does not own this resource")


def check_technician_assigned(actor, assigned_technician_id):
    if actor.user_id != assigned_technician_id:
        raise err_not_owner("Acting technician is not the assigned technician")


def reject_if_terminal(status, terminal_states):
    if status in terminal_states:
        raise err_already_terminal("Resource is in terminal state %s" % status)


# ---------------------------------------------------------------------------
# Terminal state sets (PRD 2.7)
# ---------------------------------------------------------------------------

WO_TERMINAL = ("CLOSED", "SCRAPPED", "CANCELLED")
QUOTE_TERMINAL = ("APPROVED", "EXPIRED", "SUPERSEDED", "REJECTED_SCRAP")
RESERVATION_TERMINAL = ("CONSUMED", "RELEASED")
PRESSURE_TEST_TERMINAL = ("PASSED", "FAILED", "VOIDED", "CANCELLED")
CERTIFICATE_TERMINAL = ("REVOKED",)
EXCHANGE_TERMINAL = ("SETTLED",)
FIELD_JOB_TERMINAL = ("COMPLETED", "CANCELLED")


# ---------------------------------------------------------------------------
# Seal-kit compatibility (safety gate, PRD 3.1)
# ---------------------------------------------------------------------------

_PRESSURE_CLASS_RANK = {"CLASS_3000": 1, "CLASS_5000": 2}


def check_seal_kit_compatible(kit, bore_mm, pressure_class, fluid_type):
    ok = (kit["bore_min_mm"] <= bore_mm <= kit["bore_max_mm"]
          and _PRESSURE_CLASS_RANK[pressure_class] <= _PRESSURE_CLASS_RANK[kit["pressure_class_max"]]
          and fluid_type in kit["fluid_compat"])
    if not ok:
        raise err_seal_kit()


# ---------------------------------------------------------------------------
# Stock reservation creation + cutting (PRD 3.5)
# ---------------------------------------------------------------------------

def create_reservation_with_cut(work_order_id, material, diameter_mm, cut_length_mm):
    """Runs stock_cut_allocation: selects the smallest sufficient piece, cuts
    cut_length_mm + kerf from it, and scraps/depletes the remainder when it
    falls below min_remnant_mm. Raises ERR_NO_STOCK_FITS when nothing fits.
    Returns the new OPEN StockReservation."""
    cfg = shop_config()
    kerf = cfg["kerf_mm"]
    required_mm = cut_length_mm + kerf
    item = select_stock_piece(material, diameter_mm, required_mm)
    if item is None:
        raise err_no_stock()
    reservation = make_entity({
        "work_order_id": work_order_id,
        "inventory_item_id": item["id"],
        "material": material,
        "diameter_mm": diameter_mm,
        "cut_length_mm": cut_length_mm,
        "kerf_mm": kerf,
        "scrap_length_mm": 0,
        "scrap_charge_cents": 0,
        "consumed_length_mm": None,
        "status": "OPEN",
    })
    item["length_mm"] -= required_mm
    if item["length_mm"] < cfg["min_remnant_mm"]:
        reservation["scrap_length_mm"] = item["length_mm"]
        reservation["scrap_charge_cents"] = item["length_mm"] * item["cost_per_mm_cents"]
        item["length_mm"] = 0
        item["status"] = "DEPLETED"
    touch(item)
    DB.stock_reservations[reservation["id"]] = reservation
    return reservation


def check_stock_available(material, diameter_mm, cut_length_mm):
    """Pre-flight availability probe (no mutation) used to validate the quote
    approval cascade before committing anything."""
    cfg = shop_config()
    required_mm = cut_length_mm + cfg["kerf_mm"]
    return select_stock_piece(material, diameter_mm, required_mm) is not None


# ---------------------------------------------------------------------------
# Work-order lookups used across routes
# ---------------------------------------------------------------------------

def quotes_for_work_order(work_order_id):
    return [q for q in DB.quotes.values() if q["work_order_id"] == work_order_id]


def active_quote_for(work_order_id):
    """The DRAFT-or-SENT quote of a work order, if any."""
    for q in quotes_for_work_order(work_order_id):
        if q["status"] in ("DRAFT", "SENT"):
            return q
    return None


def sent_quote_for(work_order_id):
    for q in quotes_for_work_order(work_order_id):
        if q["status"] == "SENT":
            return q
    return None


def draft_quote_for(work_order_id):
    for q in quotes_for_work_order(work_order_id):
        if q["status"] == "DRAFT":
            return q
    return None


def teardown_report_for(work_order_id):
    for r in DB.teardown_reports.values():
        if r["work_order_id"] == work_order_id:
            return r
    return None


def reservations_for(work_order_id):
    return [r for r in DB.stock_reservations.values() if r["work_order_id"] == work_order_id]


def exchange_unit_for(work_order_id):
    """The exchange unit linked to this work order's deal, if any."""
    for u in DB.exchange_units.values():
        if u.get("work_order_id") == work_order_id:
            return u
    return None

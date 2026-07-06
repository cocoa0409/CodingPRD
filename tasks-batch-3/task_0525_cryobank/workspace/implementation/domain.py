"""Shared domain computations: inventory availability, family limits, cascades."""

from db import db, touch

HOLD_TTL_DAYS = 5
ANNUAL_RATE_CENTS_PER_VIAL = 42000
BILLING_PERIOD_DAYS = 365
GRACE_DAYS = 30
SETTLE_BUFFER_HOURS = 24


# ---------------------------------------------------------------------------
# Inventory availability
# ---------------------------------------------------------------------------

def _reservations_for_inventory(inv_id):
    return [r for r in db.vial_reservations.values() if r["inventory_id"] == inv_id]


def compute_is_listed(inv):
    specimen = db.specimens.get(inv["specimen_id"])
    donor = db.donors.get(inv["donor_id"])
    return bool(
        specimen is not None
        and specimen["status"] == "RELEASED"
        and donor is not None
        and donor["status"] == "ACTIVE"
        and not donor["is_family_limit_reached"]
        and inv["hold_status"] == "OPEN"
        and inv["available_vials"] > 0
    )


def recompute_inventory(inv, bump=True):
    """Recompute reserved/shipped/available/committed/is_listed for an inventory lot.

    When bump is True the recompute is treated as a mutation (version + updated_at).
    """
    reservations = _reservations_for_inventory(inv["id"])
    reserved = sum(r["vial_count"] for r in reservations if r["status"] in ("HELD", "CONFIRMED"))
    shipped = sum(r["vial_count"] for r in reservations if r["status"] == "SHIPPED")
    committed = sum(r["vial_count"] for r in reservations if r["status"] in ("CONFIRMED", "SHIPPED"))
    total = inv["total_vials"]

    new_reserved = reserved
    new_shipped = shipped
    new_available = total - reserved - shipped
    new_committed = total - committed

    inv["reserved_vials"] = new_reserved
    inv["shipped_vials"] = new_shipped
    inv["available_vials"] = new_available
    inv["committed_available_vials"] = new_committed
    inv["is_listed"] = compute_is_listed(inv)

    if bump:
        touch(db, inv)


def recompute_all_inventories_for_donor(donor):
    for inv in db.donor_inventories.values():
        if inv["donor_id"] == donor["id"]:
            recompute_inventory(inv, bump=True)


# ---------------------------------------------------------------------------
# Family limit
# ---------------------------------------------------------------------------

def recompute_family_count(donor):
    distinct = set()
    for entry in db.sibling_registry.values():
        if entry["donor_id"] == donor["id"] and entry["status"] == "CONFIRMED":
            distinct.add(entry["recipient_id"])
    donor["reported_family_count"] = len(distinct)
    donor["is_family_limit_reached"] = donor["reported_family_count"] >= donor["family_limit"]
    touch(db, donor)
    # delist inventories if limit reached (recompute is_listed everywhere for this donor)
    recompute_all_inventories_for_donor(donor)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_shipment_cascade(shipment):
    if shipment["status"] in ("PREPARING", "DISPATCHED"):
        shipment["status"] = "CANCELLED"
        touch(db, shipment)


def void_reservation_cascade(reservation, cancel_shipments):
    """Void a HELD/CONFIRMED reservation -> CANCELLED, optionally cancel its shipment."""
    if reservation["status"] not in ("HELD", "CONFIRMED"):
        return
    reservation["status"] = "CANCELLED"
    touch(db, reservation)
    if cancel_shipments:
        for sh in db.shipments.values():
            if sh["reservation_id"] == reservation["id"]:
                cancel_shipment_cascade(sh)


def discard_specimen(specimen, cancel_shipments):
    """Drive a specimen to DISCARDED, voiding its inventory's HELD/CONFIRMED reservations."""
    specimen["status"] = "DISCARDED"
    touch(db, specimen)
    for inv in db.donor_inventories.values():
        if inv["specimen_id"] != specimen["id"]:
            continue
        for r in _reservations_for_inventory(inv["id"]):
            if r["status"] in ("HELD", "CONFIRMED"):
                void_reservation_cascade(r, cancel_shipments=cancel_shipments)
        recompute_inventory(inv, bump=True)

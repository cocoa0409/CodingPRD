"""Existence lookups that raise ERR_NOT_FOUND when missing (PRD §2.5)."""
import db
from errors import err


def _find(store, rid):
    if not isinstance(rid, str):
        return None
    return store.get(rid)


def require(store, rid, what="resource"):
    row = _find(store, rid)
    if row is None:
        raise err("ERR_NOT_FOUND", "%s not found." % what)
    return row


def require_location(rid):
    return require(db.locations, rid, "Location")


def require_class(rid):
    return require(db.equipment_classes, rid, "EquipmentClass")


def require_coverage(rid):
    return require(db.coverage_plans, rid, "CoveragePlan")


def require_supply(rid):
    return require(db.supplies, rid, "MovingSupply")


def require_customer(rid):
    return require(db.customers, rid, "Customer")


def require_reservation(rid):
    return require(db.reservations, rid, "Reservation")


def require_equipment(rid):
    return require(db.equipment, rid, "Equipment")


def require_contract(rid):
    return require(db.contracts, rid, "RentalContract")


def require_transfer(rid):
    return require(db.transfers, rid, "DropOffTransfer")

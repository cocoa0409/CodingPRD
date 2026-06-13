"""Common-field management and existence lookups (PRD §2.4, §2.6)."""
from __future__ import annotations

import db
from errors import err


def base_fields(common: bool = True) -> dict:
    """Mint id + created_at (+ updated_at + version when common=True).

    AllergenProfile is the lone lean entity: id + created_at only (PRD §2.4).
    """
    now = db.now_iso()
    rec = {
        "id": db.new_uuid(),
        "created_at": now,
        "_seq": db.next_seq(),
    }
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec: dict) -> None:
    """Refresh updated_at and increment version on a mutation (PRD §2.4, §2.5)."""
    rec["updated_at"] = db.now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ---- path-identifier existence checks (PRD §2.6) ---------------------------

def get_facility_or_404(fid: str) -> dict:
    rec = db.facilities.get(fid)
    if rec is None:
        raise err("ERR_FACILITY_NOT_FOUND", "Facility not found")
    return rec


def get_supplier_or_404(sid: str) -> dict:
    rec = db.suppliers.get(sid)
    if rec is None:
        raise err("ERR_SUPPLIER_NOT_FOUND", "Supplier not found")
    return rec


def get_ingredient_or_404(iid: str) -> dict:
    rec = db.ingredients.get(iid)
    if rec is None:
        raise err("ERR_INGREDIENT_NOT_FOUND", "Ingredient not found")
    return rec


def get_lot_or_404(lid: str) -> dict:
    rec = db.lots.get(lid)
    if rec is None:
        raise err("ERR_LOT_NOT_FOUND", "Lot not found")
    return rec


def get_coa_or_404(cid: str) -> dict:
    rec = db.coas.get(cid)
    if rec is None:
        raise err("ERR_COA_NOT_FOUND", "Certificate of Analysis not found")
    return rec


def get_run_or_404(rid: str) -> dict:
    rec = db.production_runs.get(rid)
    if rec is None:
        raise err("ERR_RUN_NOT_FOUND", "ProductionRun not found")
    return rec


def get_consumed_lot_or_404(clid: str) -> dict:
    rec = db.consumed_lots.get(clid)
    if rec is None:
        raise err("ERR_LOT_NOT_FOUND", "ConsumedLot not found")
    return rec


def get_hold_or_404(hid: str) -> dict:
    rec = db.hold_orders.get(hid)
    if rec is None:
        raise err("ERR_HOLD_NOT_FOUND", "HoldOrder not found")
    return rec


def get_zone_or_404(zid: str) -> dict:
    rec = db.zones.get(zid)
    if rec is None:
        raise err("ERR_ZONE_NOT_FOUND", "StorageZone not found")
    return rec


def get_booking_or_404(bid: str) -> dict:
    rec = db.bookings.get(bid)
    if rec is None:
        raise err("ERR_BOOKING_NOT_FOUND", "StorageBooking not found")
    return rec

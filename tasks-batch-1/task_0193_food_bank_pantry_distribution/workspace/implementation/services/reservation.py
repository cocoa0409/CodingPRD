"""FEFO reservation and release services (PRD §3.5, §3.6)."""
from db import db
from services import models
from services.calc import round2


def fefo_lots_for_category(food_category):
    """AVAILABLE lots matching category, not expired, with positive remaining,
    sorted ascending by (expiration_date, created_at). created_at tie-broken by
    the monotonic _seq, which is creation order."""
    now = db.current_utc
    candidates = []
    for lot in db.inventory_lots.values():
        if lot["food_category"] != food_category:
            continue
        if lot["disposition"] != "AVAILABLE":
            continue
        if lot["remaining_lbs"] <= 0:
            continue
        if models.parse_iso(lot["expiration_date"]) <= now:
            continue
        candidates.append(lot)
    candidates.sort(
        key=lambda l: (models.parse_iso(l["expiration_date"]), l["_seq"])
    )
    return candidates


def fefo_earliest_lot(order):
    """The FEFO-earliest AVAILABLE lot the approval would consume first across
    all of the order's lines — the lot the OCC version pins. Considers the
    union of candidate lots over every line's category, earliest first."""
    earliest = None
    for line in models.order_lines_of(order["id"]):
        lots = fefo_lots_for_category(line["food_category"])
        if lots:
            cand = lots[0]
            if earliest is None or (
                models.parse_iso(cand["expiration_date"]),
                cand["_seq"],
            ) < (
                models.parse_iso(earliest["expiration_date"]),
                earliest["_seq"],
            ):
                earliest = cand
    return earliest


def run_fefo_reservation(order):
    """Reserve inventory for each line. Mutates lines and lots. Returns approved
    total. Each reserved lot's version is bumped; AVAILABLE->RESERVED or DEPLETED."""
    touched_units = set()
    approved_total = 0.0
    for line in models.order_lines_of(order["id"]):
        need = line["requested_lbs"]
        reserved = 0.0
        first_lot_id = None
        # Re-fetch FEFO candidates each line (a prior line may have drained lots).
        while need > 1e-9:
            lots = fefo_lots_for_category(line["food_category"])
            if not lots:
                break
            lot = lots[0]
            take = min(need, lot["remaining_lbs"])
            take = round2(take)
            if take <= 0:
                break
            if first_lot_id is None:
                first_lot_id = lot["id"]
            lot["remaining_lbs"] = round2(lot["remaining_lbs"] - take)
            reserved = round2(reserved + take)
            need = round2(need - take)
            if lot["remaining_lbs"] <= 0:
                lot["remaining_lbs"] = 0
                lot["disposition"] = "DEPLETED"
            else:
                lot["disposition"] = "RESERVED"
            models.touch(lot)
            touched_units.add(lot["cold_storage_unit_id"])
        line["reserved_lbs"] = round2(reserved)
        line["reserved_lot_id"] = first_lot_id
        if line["reserved_lbs"] >= line["requested_lbs"] - 1e-9 and line["reserved_lbs"] > 0:
            line["line_status"] = "RESERVED"
        elif line["reserved_lbs"] > 0:
            line["line_status"] = "SHORT"
        else:
            # Nothing reserved at all — still SHORT per "reserved_lbs < requested".
            line["line_status"] = "SHORT"
        models.touch(line)
        approved_total = round2(approved_total + line["reserved_lbs"])

    for unit_id in touched_units:
        unit = db.cold_storage_units.get(unit_id)
        if unit is not None:
            models.recompute_unit_occupancy(unit)
    return approved_total


def release_reservations(order):
    """Release every line's reservation back to AVAILABLE lots. Conserves
    poundage. Resets lines to PENDING. Bumps versions of touched lots."""
    touched_units = set()
    for line in models.order_lines_of(order["id"]):
        amount = line["reserved_lbs"]
        lot_id = line["reserved_lot_id"]
        if amount and amount > 0 and lot_id:
            # Restore poundage to the recorded reserved lot. For multi-lot lines
            # the model records only the first lot; restore the whole reserved
            # amount there to conserve the order's poundage round-trip.
            lot = db.inventory_lots.get(lot_id)
            if lot is not None:
                lot["remaining_lbs"] = round2(lot["remaining_lbs"] + amount)
                lot["disposition"] = "AVAILABLE"
                models.touch(lot)
                touched_units.add(lot["cold_storage_unit_id"])
        line["reserved_lbs"] = 0
        line["reserved_lot_id"] = None
        line["line_status"] = "PENDING"
        models.touch(line)
    for unit_id in touched_units:
        unit = db.cold_storage_units.get(unit_id)
        if unit is not None:
            models.recompute_unit_occupancy(unit)

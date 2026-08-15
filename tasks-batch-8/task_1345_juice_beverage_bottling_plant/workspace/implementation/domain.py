"""Domain constants, computed-field derivations, and serializers."""
import math
from datetime import timedelta

from store import db
from util import pub

CONTAINER_TYPES = {"GLASS_355", "PET_473", "PET_1000", "CAN_330"}
PROCESS_TYPES = {"PASTEURIZATION", "HPP"}
ALLERGEN_GROUPS = {"NONE", "SULFITE", "TREE_NUT", "MILK"}
CLAIMS = {"ORGANIC", "NON_GMO", "NO_ADDED_SUGAR", "VITAMIN_C", "COLD_PRESSED"}
TEMP_CLASSES = {"AMBIENT", "CHILLED", "FROZEN"}
CHANNELS = {"DIRECT_RETAIL", "CLUB", "FOODSERVICE", "EXPORT"}

UNITS_PER_CASE = 12
UNITS_PER_PALLET = {"GLASS_355": 2016, "PET_473": 1440, "PET_1000": 960, "CAN_330": 2880}
MIN_SHELF_LIFE = {"DIRECT_RETAIL": 30, "CLUB": 45, "FOODSERVICE": 21, "EXPORT": 60}

TANK_GAP_HOURS = 3
ALLERGEN_CIP_HOURS = 6
STANDARD_CIP_HOURS = 2
REBLEND_LIMIT = 2
MIN_BATCH_LITERS = 500

CHANGEOVER_SAME_CONTAINER_MIN = 15
CHANGEOVER_DIFF_CONTAINER_MIN = 90
CHANGEOVER_ALLERGEN_WASHOUT_MIN = 60

PASTE_MINOR_TEMP_DROP_C = 2.0
PASTE_MINOR_TIME_S = 60
HPP_MINOR_PRESSURE_DROP_MPA = 20
HPP_MINOR_TIME_S = 30

GIVEAWAY_RATE_CENTS_PER_LITER = 140
PALLET_AGING_DAYS = 30
STALE_ORDER_GRACE_DAYS = 7

OPEN_RUN_STATES = {"QUOTED", "CONFIRMED", "SCHEDULED", "IN_PRODUCTION",
                   "BLOCKED_SUPPLY", "BLOCKED_LABEL"}
OPEN_ORDER_STATES = {"PLACED", "ALLOCATED", "PICKED", "BACKORDERED"}
TANK_OCCUPYING_BATCH_STATES = {"PLANNED", "BLENDING", "AWAITING_QA", "QA_PASSED",
                               "QA_FAILED", "PROCESSING"}


def reserve_units(planned_units):
    """ceil(planned_units * 1.05) with exact integer math."""
    return (planned_units * 105 + 99) // 100


def ceil_div(a, b):
    return -(-a // b)


def effective_expiry(lot, channel):
    if channel == "EXPORT":
        return lot.get("_expiry_stability_date") or lot["expiry_stability_date"]
    return lot.get("_expiry_label_date") or lot["expiry_label_date"]


# ------------------------------------------------------------ serializers
def ser_customer(c):
    return pub(c)


def ser_pallet_account(a):
    out = pub(a)
    customer = db.customers.get(a["customer_id"])
    deposit = customer["pallet_deposit_cents"] if customer else 0
    out["pallets_outstanding"] = (a["pallets_out_total"] - a["pallets_returned_total"]
                                  - a["pallets_converted_total"])
    out["escrow_balance_cents"] = out["pallets_outstanding"] * deposit
    return out


def ser_pallet_entry(e):
    return pub(e)


def ser_formula(f):
    return pub(f)


def ser_review(r):
    return pub(r)


def ser_tank(t):
    return pub(t)


def ser_batch(b):
    return pub(b)


def ser_process_run(p):
    return pub(p)


def ser_container_lot(l):
    out = pub(l)
    out["quantity_available"] = (l["quantity_received"] - l["quantity_reserved"]
                                 - l["quantity_consumed"])
    return out


def ser_line(l):
    return pub(l)


def ser_run(r):
    return pub(r)


def lot_pallet_count(lot):
    on_site = lot["units_total"] - lot["units_shipped"]
    if on_site <= 0:
        return 0
    return ceil_div(on_site, UNITS_PER_PALLET[lot["_container_type"]])


def ser_fg_lot(l):
    out = pub(l)
    out["units_available"] = l["units_total"] - l["units_allocated"] - l["units_shipped"]
    out["pallet_count"] = lot_pallet_count(l)
    return out


def zone_pallets_stored(zone):
    total = 0
    for lot in db.fg_lots.values():
        if lot["warehouse_zone_id"] == zone["id"] and (lot["units_total"] - lot["units_shipped"]) > 0:
            total += lot_pallet_count(lot)
    return total


def ser_zone(z):
    out = pub(z)
    out["pallets_stored"] = zone_pallets_stored(z)
    return out


def order_pallet_count(order):
    total = 0
    for alloc in order["allocations"]:
        lot = db.fg_lots.get(alloc["lot_id"])
        if lot is not None:
            total += ceil_div(alloc["units"], UNITS_PER_PALLET[lot["_container_type"]])
    return total


def ser_order(o):
    out = pub(o)
    out["allocations"] = [{"lot_id": a["lot_id"], "units": a["units"]} for a in o["allocations"]]
    out["allocated_units"] = sum(a["units"] for a in o["allocations"])
    out["pallet_count"] = order_pallet_count(o)
    return out


def ser_ops_run(o):
    return pub(o)

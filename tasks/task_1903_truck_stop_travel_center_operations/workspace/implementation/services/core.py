"""Core shared services: record lifecycle and derived-field recomputation."""
from datetime import timedelta

from db import db
from util import CLOCK, fmt_dt, fmt_dt_ms, new_id, next_seq, parse_dt, dec, rhu_float

FUEL_TYPES = ["DIESEL", "GAS_REGULAR", "GAS_PREMIUM", "DEF"]
TIER_MARGINS = {"T1": dec("0.02"), "T2": dec("0.05"), "T3": dec("0.09")}


def new_record(collection, fields, ledger=False):
    """Insert a record. Ledger-style records carry only id/created_at (PRD 2.4)."""
    rec = dict(fields)
    rec["id"] = new_id()
    now = CLOCK.now()
    rec["created_at"] = fmt_dt_ms(now)
    rec["_seq"] = next_seq()
    if not ledger:
        rec["updated_at"] = fmt_dt_ms(now)
        rec["version"] = 1
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and increment version by exactly 1 (PRD 2.4)."""
    rec["updated_at"] = fmt_dt_ms(CLOCK.now())
    rec["version"] = rec.get("version", 1) + 1


def stamp(rec, field):
    rec[field] = fmt_dt(CLOCK.now())


# ---------------------------------------------------------------------------
# Site retail mirrors (PRD 3.1)
# ---------------------------------------------------------------------------

def select_active_price(site_id, fuel_type, now=None):
    now = now or CLOCK.now()
    for p in db["fuel_prices"].values():
        if p["site_id"] != site_id or p["fuel_type"] != fuel_type or p["status"] != "ACTIVE":
            continue
        if parse_dt(p["effective_from"]) > now:
            continue
        if p["effective_to"] is not None and now >= parse_dt(p["effective_to"]):
            continue
        return p
    return None


MIRROR_FIELDS = {
    "DIESEL": "diesel_retail_cents_per_gallon",
    "GAS_REGULAR": "gas_regular_retail_cents_per_gallon",
    "DEF": "def_retail_cents_per_gallon",
}


def recompute_site_mirrors(site):
    for fuel_type, field in MIRROR_FIELDS.items():
        sel = select_active_price(site["id"], fuel_type)
        site[field] = sel["retail_cents_per_gallon"] if sel else None


# ---------------------------------------------------------------------------
# Stock / tank low flags
# ---------------------------------------------------------------------------

def recompute_stock_low(item):
    item["is_low_stock"] = item["on_hand_quantity"] <= item["reorder_point"]


def recompute_tank_low(tank):
    tank["is_low_stock"] = dec(tank["current_gallons"]) <= dec(tank["reorder_threshold_gallons"])


# ---------------------------------------------------------------------------
# Shift cash ledger and register posture (PRD 2.8)
# ---------------------------------------------------------------------------

def find_open_shift_for_register(register_id):
    for s in db["shifts"].values():
        if s["register_id"] == register_id and s["status"] == "OPEN":
            return s
    return None


def recompute_register_posture(register):
    shift = find_open_shift_for_register(register["id"])
    if shift is None:
        posture = "OK"
    else:
        expected = shift["expected_cash_cents"]
        float_cents = register["float_cents"]
        if expected > 5 * float_cents:
            posture = "NEEDS_DROP"
        elif expected < 1 * float_cents:
            posture = "LOW_FLOAT"
        else:
            posture = "OK"
    if register["posture"] != posture:
        register["posture"] = posture
        touch(register)


def adjust_shift_expected(shift, delta_cents):
    """Move a shift's book cash position and refresh register posture (PRD 2.8)."""
    if delta_cents == 0:
        return
    shift["expected_cash_cents"] += delta_cents
    touch(shift)
    register = db["registers"].get(shift["register_id"])
    if register is not None:
        recompute_register_posture(register)


# ---------------------------------------------------------------------------
# Fleet rolling volume and tier (calc fleet_tier_recompute)
# ---------------------------------------------------------------------------

def recompute_fleet_rolling_and_tier(fleet):
    now = CLOCK.now()
    lo = now - timedelta(days=30)
    total = dec("0")
    for sale in db["fuel_sales"].values():
        if sale["fleet_account_id"] != fleet["id"]:
            continue
        if sale["pricing_mode"] != "CONTRACT" or sale["status"] != "COMPLETED":
            continue
        fin = sale.get("finalized_at")
        if fin is None:
            continue
        fin_dt = parse_dt(fin)
        if lo <= fin_dt <= now:  # inclusive both ends
            total += dec(sale["dispensed_gallons"])
    rolling = float(total.quantize(dec("0.001")))
    tier = "T3" if rolling >= 20000 else ("T2" if rolling >= 5000 else "T1")
    if fleet["rolling_30d_gallons"] != rolling or fleet["pricing_tier"] != tier:
        fleet["rolling_30d_gallons"] = rolling
        fleet["pricing_tier"] = tier
        touch(fleet)


# ---------------------------------------------------------------------------
# Misc lookups
# ---------------------------------------------------------------------------

def diesel_tank_for_site(site_id):
    """The site's DIESEL bulk tank used for contract quoting (earliest created)."""
    tanks = [t for t in db["bulk_tanks"].values()
             if t["site_id"] == site_id and t["product_type"] == "DIESEL"]
    if not tanks:
        return None
    tanks.sort(key=lambda t: t["_seq"])
    for t in tanks:
        if t.get("rack_price_cents_per_gallon_4dp") is not None:
            return t
    return tanks[0]


def round_gallons(value, dp):
    return rhu_float(value, dp)

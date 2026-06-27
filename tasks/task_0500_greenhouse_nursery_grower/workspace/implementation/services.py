"""Business logic: derived-field reconciliation, calculations, cascades, auto-cull."""
import math
from decimal import Decimal, ROUND_HALF_UP

from core import store, touch, clock

# Constants
STANDARD_PLUG_COST_CENTS = 35
TIGHT_FRACTION_NUM = 15      # 0.15 expressed as 15/100
TIGHT_FRACTION_DEN = 100
AUTO_CULL_PCT = Decimal("0.50")

REBATE_TIER_1_UNITS = 2000
REBATE_TIER_1_PCT = Decimal("0.02")
REBATE_TIER_2_UNITS = 5000
REBATE_TIER_2_PCT = Decimal("0.05")

RACK_CAPACITY = 50
FREIGHT_BASE = {"IN_STATE": 2500, "NEIGHBOR": 4000, "FAR": 7000}
FREIGHT_PER_RACK = {"IN_STATE": 600, "NEIGHBOR": 1100, "FAR": 1900}
FREIGHT_FLOOR = {"IN_STATE": 2500, "NEIGHBOR": 4000, "FAR": 7000}
FREIGHT_CAP = {"IN_STATE": 9000, "NEIGHBOR": 16000, "FAR": 28000}
NEIGHBOR_CODES = {"WA", "CA", "ID", "NV"}
ORIGIN_STATE = "OR"

OCCUPYING_STATES = {"GROWING", "GRADING", "SALEABLE", "HELD"}


def round_half_up(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def variety_of(batch):
    return store.varieties.get(batch["variety_id"])


def footprint(batch):
    v = variety_of(batch)
    return v["container_footprint_units"] if v else 0


# ---------------------------------------------------------------------------
# Zone occupancy / fill state (full recompute, never incremental)
# ---------------------------------------------------------------------------
def recompute_zone(zone):
    occupied = 0
    reserved = 0
    for b in store.batches.values():
        if b["zone_id"] != zone["id"]:
            continue
        fp = footprint(b)
        if b["status"] in OCCUPYING_STATES:
            occupied += b["live_count"] * fp
        elif b["status"] == "PLANNED":
            reserved += b["sourced_count"] * fp
    zone["occupied_units"] = occupied
    zone["reserved_units"] = reserved
    zone["free_units"] = zone["capacity_units"] - occupied - reserved
    zone["fill_state"] = compute_fill_state(zone)


def compute_fill_state(zone):
    free = zone["free_units"]
    cap = zone["capacity_units"]
    tight_threshold = (cap * TIGHT_FRACTION_NUM) // TIGHT_FRACTION_DEN
    if free <= 0:
        return "FULL"
    if free <= tight_threshold:
        return "TIGHT"
    return "OPEN"


def tight_threshold(zone):
    return (zone["capacity_units"] * TIGHT_FRACTION_NUM) // TIGHT_FRACTION_DEN


def cascade_zone(zone):
    """Recompute derived occupancy figures and record the zone mutation (version++)."""
    recompute_zone(zone)
    touch(zone)


# ---------------------------------------------------------------------------
# Batch counts
# ---------------------------------------------------------------------------
def recompute_live(batch):
    batch["live_count"] = batch["started_count"] - batch["cull_count"] - batch["shipped_count"]


def provisional_saleable(batch):
    v = variety_of(batch)
    pct = Decimal(str(v["ship_ready_min_live_pct"]))
    return int(math.floor(Decimal(batch["live_count"]) * pct))


def final_saleable(batch):
    return batch["live_count"]


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------
def recompute_availability(entry):
    entry["available_quantity"] = entry["published_quantity"] - entry["committed_quantity"]


def open_entries_for_batch(batch_id):
    return [e for e in store.availability.values() if e["batch_id"] == batch_id and e["status"] == "OPEN"]


def entries_for_batch(batch_id):
    return [e for e in store.availability.values() if e["batch_id"] == batch_id]


def has_committed_draw(batch):
    entry_ids = {e["id"] for e in entries_for_batch(batch["id"])}
    for l in store.order_lines.values():
        if l["status"] == "COMMITTED" and l["availability_entry_id"] in entry_ids:
            return True
    return False


# ---------------------------------------------------------------------------
# Cull (shared by manual cull + auto-cull)
# ---------------------------------------------------------------------------
def do_full_cull(batch):
    """Cull the entire living stand, close availability, release zone footprint."""
    batch["cull_count"] += batch["live_count"]
    batch["live_count"] = 0
    batch["saleable_count"] = 0
    batch["status"] = "CULLED"
    for e in open_entries_for_batch(batch["id"]):
        e["status"] = "CLOSED"
        e["published_quantity"] = 0
        recompute_availability(e)
        touch(e)
    touch(batch)
    zone = store.zones.get(batch["zone_id"])
    if zone:
        cascade_zone(zone)


# ---------------------------------------------------------------------------
# Scouting / grade shrink + auto-cull threshold
# ---------------------------------------------------------------------------
def apply_shrink(batch, dead_observed):
    """Apply a SCOUTING/GRADE dead count to a GROWING/GRADING/HELD batch; auto-cull at >=50%."""
    if dead_observed <= 0:
        return
    if batch["status"] not in ("GROWING", "GRADING", "HELD"):
        return
    batch["cull_count"] += dead_observed
    recompute_live(batch)
    touch(batch)
    if batch["started_count"] > 0:
        cumulative = Decimal(batch["cull_count"]) / Decimal(batch["started_count"])
        if cumulative >= AUTO_CULL_PCT and batch["status"] in ("GROWING", "GRADING", "HELD"):
            do_full_cull(batch)
            return
    # zone occupancy changed due to reduced live_count even without auto-cull
    zone = store.zones.get(batch["zone_id"])
    if zone:
        cascade_zone(zone)


# ---------------------------------------------------------------------------
# Order pricing + freight
# ---------------------------------------------------------------------------
def freight_band(ship_to_state):
    if ship_to_state == ORIGIN_STATE:
        return "IN_STATE"
    if ship_to_state in NEIGHBOR_CODES:
        return "NEIGHBOR"
    return "FAR"


def freight_charge(total_units, ship_to_state):
    band = freight_band(ship_to_state)
    base = FREIGHT_BASE[band]
    per_rack = FREIGHT_PER_RACK[band]
    racks = math.ceil(total_units / RACK_CAPACITY) if total_units > 0 else 0
    raw = base + racks * per_rack
    return min(FREIGHT_CAP[band], max(FREIGHT_FLOOR[band], raw))


def active_lines(order):
    return [l for l in store.order_lines.values()
            if l["order_id"] == order["id"] and l["status"] in ("PENDING", "COMMITTED")]


def recompute_order(order):
    lines = active_lines(order)
    if not lines:
        order["order_subtotal_cents"] = 0
        order["freight_cents"] = 0
        order["order_total_cents"] = 0
        return
    subtotal = sum(l["extended_cents"] for l in lines)
    total_units = sum(l["quantity"] for l in lines)
    broker = store.brokers.get(order["broker_id"])
    ship_to_state = broker["ship_to_state"] if broker else ""
    freight = freight_charge(total_units, ship_to_state)
    if total_units >= REBATE_TIER_2_UNITS:
        rebate = round_half_up(Decimal(subtotal) * REBATE_TIER_2_PCT)
    elif total_units >= REBATE_TIER_1_UNITS:
        rebate = round_half_up(Decimal(subtotal) * REBATE_TIER_1_PCT)
    else:
        rebate = 0
    order["order_subtotal_cents"] = subtotal
    order["freight_cents"] = freight
    order["order_total_cents"] = subtotal - rebate + freight

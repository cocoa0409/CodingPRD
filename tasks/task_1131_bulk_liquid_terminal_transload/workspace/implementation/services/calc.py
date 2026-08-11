"""Calculation rules (SCAFFOLD 1.3). All money uses Decimal + ROUND_HALF_UP;
all custody volumes are whole barrels (0dp round-half-up)."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from clock import CLOCK
from db import STORE

# --- Constants pinned by the scaffold/PRD -----------------------------------
CTL_COEFF = Decimal("0.0006")
REF_TEMP_F = Decimal("60")
GRADE_STD_SG = {
    "GASOLINE": Decimal("0.74"),
    "DIESEL": Decimal("0.85"),
    "JET": Decimal("0.80"),
    "ETHANOL": Decimal("0.79"),
    "CRUDE": Decimal("0.87"),
}
FREE_HOURS_BY_MODE = {"VESSEL": 24, "RAIL": 48, "TRUCK": 4}
RATE_PER_HOUR_BY_MODE = {
    "VESSEL": Decimal("1200.00"),
    "RAIL": Decimal("85.00"),
    "TRUCK": Decimal("60.00"),
}
LATE_GRACE_MINUTES = 30
RETAIN_DAYS = 30
LOSS_CONTROL_CAP_BBL = Decimal("100")
TIER1_CAP = Decimal("50000")
TIER2_CAP = Decimal("200000")
TIER2_DISCOUNT = Decimal("0.90")
TIER3_DISCOUNT = Decimal("0.75")


def dec(value):
    return Decimal(str(value))


def round2(value):
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round0(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(value):
    """Normalize a user-supplied monetary amount to 2dp round-half-up."""
    return round2(dec(value))


# --- tank_working_capacity ----------------------------------------------------
def compute_working_capacity(capacity_bbl, safe_fill_pct, heel_bbl):
    """floor(capacity * safe_fill_pct) - heel; floor before heel subtraction."""
    cap = math.floor(dec(capacity_bbl) * dec(safe_fill_pct))
    return cap - dec(heel_bbl)


# --- allocation_capacity_sweep ------------------------------------------------
def capacity_sweep_ok(tank, candidate, candidate_status):
    """Aggregate-capacity overlap over CLOSED date ranges.

    For every date d in the candidate period, sum allocated_bbl of the tank's
    RESERVED/ACTIVE allocations covering d; reject when the sum plus the
    candidate exceeds working_capacity_bbl. Equality is allowed.
    Evaluated at period boundary dates only (sums are constant between them).
    """
    others = [
        a for a in STORE.allocations.values()
        if a["tank_id"] == tank["id"]
        and a["id"] != candidate["id"]
        and a["status"] in ("RESERVED", "ACTIVE")
    ]
    points = {candidate["_period_start"], candidate["_period_end"]}
    for a in others:
        points.add(a["_period_start"])
        points.add(a["_period_end"])
    candidate_bbl = dec(candidate["allocated_bbl"]) if candidate_status in ("RESERVED", "ACTIVE") else Decimal(0)
    for d in sorted(points):
        if d < candidate["_period_start"] or d > candidate["_period_end"]:
            continue
        total = candidate_bbl
        for a in others:
            if a["_period_start"] <= d <= a["_period_end"]:
                total += dec(a["allocated_bbl"])
        if total > dec(tank["working_capacity_bbl"]):
            return False
    return True


# --- demurrage_charge ---------------------------------------------------------
def demurrage_scheduled_estimate(movement):
    """Forward-looking: (window_hours - free_hours)+ * rate, 2dp round-half-up."""
    window_seconds = Decimal(str(
        (movement["window_end"] - movement["window_start"]).total_seconds()))
    window_hours = window_seconds / Decimal(3600)
    free = Decimal(FREE_HOURS_BY_MODE[movement["mode"]])
    rate = RATE_PER_HOUR_BY_MODE[movement["mode"]]
    chargeable = window_hours - free
    if chargeable < 0:
        chargeable = Decimal(0)
    return round2(chargeable * rate)


def demurrage_actual_settlement(movement):
    """Chronological: ceil(elapsed_seconds/3600) hours; elapsed == free yields 0."""
    elapsed_seconds = Decimal(str(
        (movement["actual_complete_at"] - movement["actual_arrival_at"]).total_seconds()))
    elapsed_hours = Decimal(math.ceil(elapsed_seconds / Decimal(3600)))
    free = Decimal(FREE_HOURS_BY_MODE[movement["mode"]])
    rate = RATE_PER_HOUR_BY_MODE[movement["mode"]]
    chargeable = elapsed_hours - free
    if chargeable < 0:
        chargeable = Decimal(0)
    return round2(chargeable * rate)


# --- custody_transfer_volume --------------------------------------------------
def _temperature_corrected(ticket):
    return (dec(ticket["observed_volume_bbl"])
            * (Decimal(1) - CTL_COEFF * (dec(ticket["observed_temp_f"]) - REF_TEMP_F)))


def transferred_volume(movement, opening, closing):
    """Temperature-corrected transfer volume (unrounded Decimal, >= 0)."""
    raw = _temperature_corrected(closing) - _temperature_corrected(opening)
    if movement["direction"] == "DISCHARGE":
        raw = -raw
    return abs(raw)


def provisional_volume(movement, opening, closing):
    """Provisional variant: round_half_up(transferred, 0)."""
    return round0(transferred_volume(movement, opening, closing))


def certified_volume(movement, opening, closing, sample):
    """Certified variant: transferred * (sample SG / grade standard SG), 0dp."""
    ratio = dec(sample["specific_gravity"]) / GRADE_STD_SG[movement["product_grade"]]
    return round0(transferred_volume(movement, opening, closing) * ratio)


# --- shrinkage_and_excess_loss ------------------------------------------------
def compute_loss_fields(movement, lease, certified_volume_bbl):
    declared = dec(movement["declared_volume_bbl"])
    shrinkage = declared - Decimal(certified_volume_bbl)
    allowed = Decimal(round0(declared * dec(lease["loss_allowance_pct"])))
    excess = shrinkage - allowed
    if excess < 0:
        excess = Decimal(0)
    charge = round2(excess * dec(lease["excess_loss_rate_per_bbl"]))
    return {
        "shrinkage_bbl": int(shrinkage),
        "allowed_loss_bbl": int(allowed),
        "excess_loss_bbl": int(excess),
        "excess_loss_charge": charge,
    }


# --- tank_inventory_reconciliation --------------------------------------------
def recompute_tank_inventory(tank):
    """current = signed CERTIFIED/DISPUTED certified volumes;
    provisional = current + signed PROVISIONAL provisional volumes.
    Then re-evaluate AVAILABLE <-> RESTRICTED posture."""
    current = Decimal(0)
    provisional_extra = Decimal(0)
    for ct in STORE.custody_transfers.values():
        movement = STORE.movements.get(ct["movement_id"])
        if movement is None or movement["tank_id"] != tank["id"]:
            continue
        sign = Decimal(1) if movement["direction"] == "RECEIPT" else Decimal(-1)
        if ct["status"] in ("CERTIFIED", "DISPUTED"):
            current += sign * Decimal(ct["certified_volume_bbl"] or 0)
        elif ct["status"] == "PROVISIONAL":
            provisional_extra += sign * Decimal(ct["provisional_volume_bbl"] or 0)
    tank["current_inventory_bbl"] = int(current)
    tank["provisional_inventory_bbl"] = int(current + provisional_extra)
    heel = dec(tank["heel_bbl"])
    working = dec(tank["working_capacity_bbl"])
    in_bounds = heel <= current <= working
    if tank["status"] == "AVAILABLE" and not in_bounds:
        tank["status"] = "RESTRICTED"
    elif tank["status"] == "RESTRICTED" and in_bounds:
        tank["status"] = "AVAILABLE"


# --- throughput_fee_tiered / minimum_commitment_shortfall ---------------------
def tiered_throughput_fee(total_throughput_bbl, base_fee_per_bbl):
    """Marginal half-open tiers: [0,50k) @1.00, [50k,200k) @0.90, [200k,inf) @0.75.
    Sum marginal tier amounts, then round once at the end (sum-then-round)."""
    total = Decimal(total_throughput_bbl)
    rate = dec(base_fee_per_bbl)
    t1 = min(total, TIER1_CAP)
    t2 = min(max(total - TIER1_CAP, Decimal(0)), TIER2_CAP - TIER1_CAP)
    t3 = max(total - TIER2_CAP, Decimal(0))
    amount = t1 * rate + t2 * rate * TIER2_DISCOUNT + t3 * rate * TIER3_DISCOUNT
    return round2(amount)


def shortfall_fields(lease, total_throughput_bbl):
    shortfall = dec(lease["min_monthly_throughput_bbl"]) - Decimal(total_throughput_bbl)
    if shortfall < 0:
        shortfall = Decimal(0)
    fee = round2(shortfall * dec(lease["shortfall_fee_per_bbl"]))
    return int(shortfall), fee


# --- resource_window_occupation ------------------------------------------------
def _occupied_windows(resource_id):
    return [
        m for m in STORE.movements.values()
        if m.get("resource_id") == resource_id and m["status"] in OCCUPIED_STATUSES
    ]


OCCUPIED_STATUSES = ("SCHEDULED", "ARRIVED", "IN_PROGRESS", "SUSPENDED")


def window_conflict(resource, candidate_start, candidate_end, exclude_movement_id=None):
    """Half-open [start, end) conflict evaluation against occupying movements.

    DOCK/RAIL_RACK (capacity 1): pairwise overlap test; adjacency allowed.
    TRUCK_BAY (capacity N): conflict iff max concurrent overlap + 1 > N.
    """
    existing = [
        m for m in STORE.movements.values()
        if m.get("resource_id") == resource["id"]
        and m["id"] != exclude_movement_id
        and m["status"] in OCCUPIED_STATUSES
    ]
    if resource["concurrent_capacity"] <= 1:
        for m in existing:
            if candidate_start < m["window_end"] and m["window_start"] < candidate_end:
                return True
        return False
    # Aggregate capacity: sweep event points.
    points = {candidate_start, candidate_end}
    for m in existing:
        points.add(m["window_start"])
        points.add(m["window_end"])
    capacity = resource["concurrent_capacity"]
    for p in sorted(points):
        if p < candidate_start or p >= candidate_end:
            continue
        count = 1  # the candidate itself occupies [candidate_start, candidate_end)
        for m in existing:
            if m["window_start"] <= p < m["window_end"]:
                count += 1
        if count > capacity:
            return True
    return False


# --- waitlist_promotion_selector ------------------------------------------------
def run_waitlist_promotion(resource):
    """After a SCHEDULED movement is cancelled, repeatedly promote the top-ranked
    fitting NOMINATED movement onto the freed resource until none fits.
    Ranking: created_at ASC, tie-break sequence_no ASC (never id)."""
    from services import lifecycle  # local import to avoid a cycle

    while True:
        candidates = []
        for m in STORE.movements.values():
            if m["status"] != "NOMINATED":
                continue
            if m["mode"] not in MODE_TO_RESOURCE_TYPE:
                continue
            if MODE_TO_RESOURCE_TYPE[m["mode"]] != resource["resource_type"]:
                continue
            if window_conflict(resource, m["window_start"], m["window_end"]):
                continue
            candidates.append(m)
        if not candidates:
            return
        candidates.sort(key=lambda m: (m["created_at"], m["sequence_no"]))
        lifecycle.promote_to_scheduled(candidates[0], resource)


MODE_TO_RESOURCE_TYPE = {"VESSEL": "DOCK", "RAIL": "RAIL_RACK", "TRUCK": "TRUCK_BAY"}


# --- vapor permit coverage ------------------------------------------------------
def vapor_permit_state(tank):
    """Returns (has_approved_covering_now) for a VRU_REQUIRED check.

    Applies lazy expiry first. Returns one of:
      ("OK", permit)          - an APPROVED VAPOR_CONTROL permit covers now
      ("NONE", None)          - no APPROVED VAPOR_CONTROL permit exists at all
      ("WINDOW", permit)      - approved permit(s) exist but none covers now
    """
    now = CLOCK.now()
    approved = []
    for p in STORE.permits.values():
        if p["tank_id"] != tank["id"] or p["permit_type"] != "VAPOR_CONTROL":
            continue
        from services.common import lazy_permit
        lazy_permit(p)
        if p["status"] != "APPROVED":
            continue
        approved.append(p)
    if not approved:
        return "NONE", None
    for p in approved:
        if p["valid_from"] <= now <= p["valid_until"]:
            return "OK", p
    return "WINDOW", approved[0]


def retain_deadline(created_at):
    return created_at + timedelta(days=RETAIN_DAYS)

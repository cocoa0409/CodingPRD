"""Business logic: calculations, derived fields, and cross-entity cascades.
All temporal rules read the logical clock (db.now())."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import db
from db import touch
from timeutil import add_months

# --- calculation constants (SCAFFOLD 1.3) ---
PITOT_K = 29.83
EXTRAPOLATION_EXPONENT = 0.54
REFERENCE_RESIDUAL_PSI = 20.0
LITERS_PER_GALLON = Decimal("3.785")
TABLET_NEUTRALIZES_MG = Decimal(8500)
DISCHARGE_LIMIT_MG_L = 0.1
MUNICIPAL_CYCLE_MONTHS = 12
PRIVATE_CYCLE_MONTHS = 6
DUE_SOON_DAYS = 30
CRITICAL_DAYS = 90
CLUSTER_THRESHOLD = 3
CLUSTER_WINDOW_HOURS = 72
AUTO_SEQUENCE_DELAY_HOURS = 24
AUTO_SEQUENCE_DURATION_HOURS = 4
DISCOUNT_TIER1_CENTS = 20000
DISCOUNT_TIER1_PCT = Decimal("0.05")
DISCOUNT_TIER2_CENTS = 100000
DISCOUNT_TIER2_PCT = Decimal("0.10")
HANDLING_FEE_THRESHOLD_CENTS = 25000
HANDLING_FEE_CENTS = 1500
FLOW_WEIGHT = 0.6
INSPECTION_WEIGHT = 0.4
ISO_FLOW_LOOKBACK_MONTHS = 60
PRIVATE_WEIGHT = 0.5
ACK_DEADLINE_HOURS = 2


def round_half_up(value, places):
    """Round half up to the given number of decimal places; returns Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def hydrant_of(entity):
    return db.store.hydrants.get(entity["hydrant_id"])


def program_hydrants(program_id):
    return [h for h in db.store.hydrants.values() if h["program_id"] == program_id]


# ---------------------------------------------------------------------------
# inspection_due_tier
# ---------------------------------------------------------------------------

def compute_inspection_tier(h):
    cycle = MUNICIPAL_CYCLE_MONTHS if h["ownership"] == "MUNICIPAL" else PRIVATE_CYCLE_MONTHS
    baseline = h["last_verified_inspection_date"] or h["created_at"]
    due = add_months(baseline, cycle)
    now = db.now()
    if now < due - timedelta(days=DUE_SOON_DAYS):
        return "CURRENT"
    if now < due:
        return "DUE_SOON"
    if now < due + timedelta(days=CRITICAL_DAYS):
        return "OVERDUE"
    return "CRITICAL"


def recompute_tier(h):
    """Recompute and store the tier; bump the hydrant version only on change."""
    new_tier = compute_inspection_tier(h)
    if new_tier != h["inspection_tier"]:
        h["inspection_tier"] = new_tier
        touch(h)


# ---------------------------------------------------------------------------
# pitot_flow / flow_at_20psi / classification
# ---------------------------------------------------------------------------

def compute_flow_results(h, static_psi, residual_psi, pitot_psi):
    """Returns (pitot_flow_gpm stored at 2dp, flow_at_20psi_gpm whole gpm).
    Evaluation order pinned: unrounded pitot -> unrounded Q20 -> round once."""
    pitot_unrounded = (
        PITOT_K
        * float(h["discharge_coefficient"])
        * (float(h["outlet_diameter_in"]) ** 2)
        * math.sqrt(float(pitot_psi))
    )
    pitot_stored = float(round_half_up(pitot_unrounded, 2))
    ratio = (float(static_psi) - REFERENCE_RESIDUAL_PSI) / (
        float(static_psi) - float(residual_psi)
    )
    q20 = pitot_unrounded * (ratio ** EXTRAPOLATION_EXPONENT)
    flow20 = int(round_half_up(q20, 0))
    return pitot_stored, flow20


def classify(flow_at_20psi_gpm, h):
    return "PASS" if flow_at_20psi_gpm >= h["required_fire_flow_gpm"] else "FAIL"


# ---------------------------------------------------------------------------
# hydrant_available_fire_flow (provisional / approved variants)
# ---------------------------------------------------------------------------

def recompute_provisional_flow(h):
    """provisional = flow_at_20psi_gpm of the latest RESULTS_SUBMITTED or
    APPROVED test (ordered by recorded_at, ties by created_at ascending);
    null when none."""
    cands = [
        t for t in db.store.flow_tests.values()
        if t["hydrant_id"] == h["id"] and t["status"] in ("RESULTS_SUBMITTED", "APPROVED")
    ]
    if not cands:
        h["provisional_fire_flow_gpm"] = None
        return
    cands.sort(key=lambda t: (t["recorded_at"], t["created_at"], t["_seq"]))
    h["provisional_fire_flow_gpm"] = cands[-1]["flow_at_20psi_gpm"]


# ---------------------------------------------------------------------------
# part_available_qty
# ---------------------------------------------------------------------------

def part_available_qty(part_id):
    part = db.store.parts[part_id]
    reserved = sum(
        line["qty"]
        for wo in db.store.work_orders.values()
        for line in wo["part_lines"]
        if line["part_id"] == part_id and line["status"] == "RESERVED"
    )
    return part["on_hand_qty"] - reserved


# ---------------------------------------------------------------------------
# work_order_total (quoted / actual variants share the pinned pipeline)
# ---------------------------------------------------------------------------

def work_order_total(unit_prices):
    """unit_prices: list of (qty, unit_price_cents) pairs. Returns
    (subtotal, discount, fee, total) in integer cents, pinned order:
    subtotal -> tiered discount -> discounted -> fee -> total."""
    subtotal = sum(qty * price for qty, price in unit_prices)
    if subtotal >= DISCOUNT_TIER2_CENTS:
        discount_pct = DISCOUNT_TIER2_PCT
    elif subtotal >= DISCOUNT_TIER1_CENTS:
        discount_pct = DISCOUNT_TIER1_PCT
    else:
        discount_pct = Decimal(0)
    discount = int(round_half_up(Decimal(subtotal) * discount_pct, 0))
    discounted = subtotal - discount
    fee = HANDLING_FEE_CENTS if discounted < HANDLING_FEE_THRESHOLD_CENTS else 0
    return subtotal, discount, fee, discounted + fee


def quoted_totals_at_current_prices(wo):
    """Quoted variant: snapshot Part.unit_price_cents at approve time."""
    pairs = [
        (line["qty"], db.store.parts[line["part_id"]]["unit_price_cents"])
        for line in wo["part_lines"]
    ]
    return work_order_total(pairs)


# ---------------------------------------------------------------------------
# flush_volume_total / dechlorination_tablets
# ---------------------------------------------------------------------------

def compute_flush_volume(steps):
    """Round each EXECUTED step's volume to whole gallons first, then sum."""
    total = 0
    for step in steps:
        if step["status"] != "EXECUTED":
            continue
        volume = float(step["flow_gpm"]) * float(step["duration_minutes"])
        total += int(round_half_up(volume, 0))
    return total


def compute_dechlorination_tablets(total_flushed_gallons, source_chlorine_residual_mg_L):
    mass_mg = (
        Decimal(total_flushed_gallons)
        * LITERS_PER_GALLON
        * Decimal(str(source_chlorine_residual_mg_L))
    )
    return int((mass_mg / TABLET_NEUTRALIZES_MG).to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# complaint_cluster
# ---------------------------------------------------------------------------

def evaluate_complaint_cluster(new_complaint):
    """After inserting a complaint: if >= 3 DISCOLORED_WATER complaints in
    {OPEN, LINKED} on this hydrant within the rolling 72h window, the hydrant is
    IN_SERVICE, and no COMPLAINT_AUTO sequence is PLANNED/IN_PROGRESS for it,
    auto-create a targeted flush sequence and link the whole cluster."""
    h = db.store.hydrants[new_complaint["hydrant_id"]]
    now = db.now()
    window_start = now - timedelta(hours=CLUSTER_WINDOW_HOURS)
    cluster = [
        c for c in db.store.complaints.values()
        if c["hydrant_id"] == h["id"]
        and c["category"] == "DISCOLORED_WATER"
        and c["status"] in ("OPEN", "LINKED")
        and window_start <= c["created_at"] <= now
    ]
    if len(cluster) < CLUSTER_THRESHOLD:
        return None
    if h["status"] != "IN_SERVICE":
        return None
    in_flight = any(
        s["hydrant_id"] == h["id"]
        and s["origin"] == "COMPLAINT_AUTO"
        and s["status"] in ("PLANNED", "IN_PROGRESS")
        for s in db.store.flush_sequences.values()
    )
    if in_flight:
        return None
    sequence = db.new_base()
    sequence.update({
        "program_id": h["program_id"],
        "zone_id": h["zone_id"],
        "hydrant_id": h["id"],
        "origin": "COMPLAINT_AUTO",
        "status": "PLANNED",
        "window_start": now + timedelta(hours=AUTO_SEQUENCE_DELAY_HOURS),
        "window_end": now + timedelta(hours=AUTO_SEQUENCE_DELAY_HOURS + AUTO_SEQUENCE_DURATION_HOURS),
        "steps": [{
            "step_index": 1,
            "valve_tag": "MAIN",
            "action": "OPEN",
            "status": "PENDING",
            "executed_at": None,
            "executed_by_user_id": None,
            "flow_gpm": None,
            "duration_minutes": None,
        }],
        "source_chlorine_residual_mg_L": None,
        "total_flushed_gallons": None,
        "dechlorination_tablets_required": None,
        "final_discharge_residual_mg_L": None,
    })
    db.store.flush_sequences[sequence["id"]] = sequence
    for c in cluster:
        c["status"] = "LINKED"
        c["flush_sequence_id"] = sequence["id"]
        touch(c)
    h["targeted_flush_pending"] = True
    touch(h)
    return sequence


# ---------------------------------------------------------------------------
# iso_rating_points
# ---------------------------------------------------------------------------

def compute_iso_metrics(snapshot):
    """Weighted coverage scoring over the program's non-DECOMMISSIONED hydrants."""
    profile = snapshot["weighting_profile"]
    now = db.now()
    flow_cutoff = add_months(now, -ISO_FLOW_LOOKBACK_MONTHS)

    approved_by_hydrant = {}
    for t in db.store.flow_tests.values():
        if t["status"] == "APPROVED" and t["reviewed_at"] is not None:
            approved_by_hydrant.setdefault(t["hydrant_id"], []).append(t)

    total_weight = 0.0
    flow_weight = 0.0
    insp_weight = 0.0
    for h in program_hydrants(snapshot["program_id"]):
        if h["status"] == "DECOMMISSIONED":
            continue
        if h["ownership"] == "PRIVATE":
            if profile == "MUNICIPAL_ONLY":
                continue
            w = PRIVATE_WEIGHT
        else:
            w = 1.0
        total_weight += w
        flow_current = any(
            flow_cutoff <= t["reviewed_at"] <= now
            for t in approved_by_hydrant.get(h["id"], [])
        )
        if flow_current:
            flow_weight += w
        cycle = MUNICIPAL_CYCLE_MONTHS if h["ownership"] == "MUNICIPAL" else PRIVATE_CYCLE_MONTHS
        last_verified = h["last_verified_inspection_date"]
        inspection_current = (
            last_verified is not None
            and add_months(now, -cycle) <= last_verified <= now
        )
        if inspection_current:
            insp_weight += w

    if total_weight > 0:
        flow_coverage = flow_weight / total_weight
        inspection_compliance = insp_weight / total_weight
    else:
        flow_coverage = 0.0
        inspection_compliance = 0.0
    iso_points = 100.0 * (FLOW_WEIGHT * flow_coverage + INSPECTION_WEIGHT * inspection_compliance)
    return {
        "total_hydrants_in_scope": total_weight,
        "flow_coverage_pct": float(round_half_up(100.0 * flow_coverage, 1)),
        "inspection_compliance_pct": float(round_half_up(100.0 * inspection_compliance, 1)),
        "iso_points": float(round_half_up(iso_points, 1)),
    }


# ---------------------------------------------------------------------------
# Shared cascade helpers
# ---------------------------------------------------------------------------

def cancel_scheduled_flow_tests_for_outage(hydrant_id):
    """CASCADE hop 3 of outage creation: every SCHEDULED FlowTest of this
    hydrant -> CANCELLED with cancel_reason OUTAGE_AUTO_CANCEL."""
    for t in db.store.flow_tests.values():
        if t["hydrant_id"] == hydrant_id and t["status"] == "SCHEDULED":
            t["status"] = "CANCELLED"
            t["cancel_reason"] = "OUTAGE_AUTO_CANCEL"
            touch(t)


def resolve_linked_complaints(sequence):
    """On sequence completion: every LINKED complaint pointing at it -> RESOLVED."""
    for c in db.store.complaints.values():
        if c["flush_sequence_id"] == sequence["id"] and c["status"] == "LINKED":
            c["status"] = "RESOLVED"
            touch(c)


def revert_linked_complaints(sequence):
    """On sequence abort (compensation): every complaint pointing at it reverts
    to OPEN with flush_sequence_id cleared."""
    for c in db.store.complaints.values():
        if c["flush_sequence_id"] == sequence["id"] and c["status"] == "LINKED":
            c["status"] = "OPEN"
            c["flush_sequence_id"] = None
            touch(c)


def open_work_orders_exist(hydrant_id):
    return any(
        wo["hydrant_id"] == hydrant_id and wo["status"] in ("DRAFT", "SUBMITTED", "APPROVED")
        for wo in db.store.work_orders.values()
    )


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; touching endpoints allowed."""
    return a_start < b_end and b_start < a_end


def scheduled_window_conflict(hydrant_id, window_start, window_end, exclude_id=None):
    for t in db.store.flow_tests.values():
        if t["hydrant_id"] != hydrant_id or t["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and t["id"] == exclude_id:
            continue
        if windows_overlap(window_start, window_end, t["window_start"], t["window_end"]):
            return True
    return False


def zone_cooldown_violation(zone, window_start, window_end):
    """Gap between the new window and any other PLANNED/IN_PROGRESS sequence in
    the zone must be at least zone.cooldown_minutes; adjacency violates."""
    cooldown = timedelta(minutes=zone["cooldown_minutes"])
    for s in db.store.flush_sequences.values():
        if s["zone_id"] != zone["id"] or s["status"] not in ("PLANNED", "IN_PROGRESS"):
            continue
        if window_end <= s["window_start"]:
            gap = s["window_start"] - window_end
        elif s["window_end"] <= window_start:
            gap = window_start - s["window_end"]
        else:
            gap = timedelta(days=-365000)  # overlapping windows: negative gap
        if gap < cooldown:
            return True
    return False

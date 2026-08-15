"""Domain logic: derived-field reconciliation, cascades, allocation, settlement math."""
from datetime import timedelta
from decimal import Decimal

from store import STORE, CLOCK
from util import TWO, FOUR, rhu, floor2, wall_now, new_uuid, parse_dt_value

# Constants (SCAFFOLD calculations)
DEFAULT_BLEND_PACKOUT_FRACTION = Decimal("0.75")
WASH_MAX_TURBIDITY_NTU = Decimal("4.0")
QUARANTINE_TURBIDITY_NTU = Decimal("8.0")
CHLORINE_MIN_PPM = Decimal("50")
CHLORINE_MAX_PPM = Decimal("200")
WASH_TEMP_MIN_F = Decimal("45")
WASH_TEMP_MAX_F = Decimal("60")
RESTRICTED_CONSECUTIVE_FAILS = 2
WASH_VALIDITY_HOURS_NORMAL = 12
WASH_VALIDITY_HOURS_RESTRICTED = 4
REMNANT_MAX_CWT = Decimal("5.0")
RETREAT_WINDOW_DAYS = 21
LINE_BUFFER_DIFFERENT_VARIETY = timedelta(hours=1)
STORAGE_FEE_CENTS_PER_CWT_WEEK = Decimal("12.5")
INHIBITOR_FEE_CENTS_PER_CWT = Decimal("8")
PROCESSING_CREDIT_CENTS_PER_CWT = Decimal("150")
WEEK_SECONDS = 7 * 86400

VARIETIES = [
    "RUSSET_BURBANK",
    "RUSSET_NORKOTAH",
    "RANGER_RUSSET",
    "YUKON_GOLD",
    "RED_LASODA",
]


# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------
def new_record(common=True):
    rec = {"id": new_uuid(), "created_at": wall_now()}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation of a versioned resource: refresh updated_at and bump version."""
    if "version" in rec:
        rec["version"] += 1
    if "updated_at" in rec:
        rec["updated_at"] = wall_now()


def clock_now():
    return CLOCK["dt"]


def clock_stamp():
    """Server stamps (binned_at, closed_at, completed_at, paid_at) come from the
    logical clock; echo its canonical raw representation."""
    return CLOCK["raw"]


# ---------------------------------------------------------------------------
# Derived-field reconciliation
# ---------------------------------------------------------------------------
def recompute_lot_available(lot):
    lot["available_cwt"] = (
        lot["original_weight_cwt"]
        - lot["shrink_cwt"]
        - lot["packed_total_cwt"]
        - lot["cull_total_cwt"]
        - lot["condemned_cwt"]
    )


def recompute_lot_reserved(lot):
    """reserved_cwt = sum of raw_cwt over reservations on this lot held by
    orders in ALLOCATED or PACKING."""
    total = Decimal("0")
    for order in STORE["orders"].values():
        if order["status"] not in ("ALLOCATED", "PACKING"):
            continue
        for r in order["reservations"]:
            if r["field_lot_id"] == lot["id"]:
                total += r["raw_cwt"]
    lot["reserved_cwt"] = total


def recompute_bin(b):
    """occupied_cwt = sum of available_cwt over BINNED lots in this bin;
    variety_lock clears when occupancy returns to 0."""
    occ = Decimal("0")
    for lot in STORE["lots"].values():
        if lot["bin_id"] == b["id"] and lot["storage_status"] == "BINNED":
            occ += lot["available_cwt"]
    changed = occ != b["occupied_cwt"]
    b["occupied_cwt"] = occ
    if occ == 0 and b["variety_lock"] is not None:
        b["variety_lock"] = None
        changed = True
    if changed:
        touch(b)


def recompute_contract(c):
    """Commitment ledger is derived from the contract's orders:
    allocated_active = sum of (requested - packed_to_date) over ALLOCATED/PACKING
    orders; packed_to_date = sum of packed actuals over all of its orders;
    remaining = committed - allocated_active - packed_to_date."""
    allocated = Decimal("0")
    packed = Decimal("0")
    for o in STORE["orders"].values():
        if o["contract_id"] != c["id"]:
            continue
        packed += o["packed_to_date_cwt"]
        if o["status"] in ("ALLOCATED", "PACKING"):
            allocated += o["requested_packed_cwt"] - o["packed_to_date_cwt"]
    remaining = c["committed_volume_cwt"] - allocated - packed
    if (
        allocated != c["allocated_active_cwt"]
        or packed != c["packed_to_date_cwt"]
        or remaining != c["remaining_committed_cwt"]
    ):
        c["allocated_active_cwt"] = allocated
        c["packed_to_date_cwt"] = packed
        c["remaining_committed_cwt"] = remaining
        touch(c)


def maybe_auto_close_lot(lot):
    """A BINNED lot whose available_cwt reaches zero auto-closes."""
    if lot["storage_status"] == "BINNED" and lot["available_cwt"] == 0:
        lot["storage_status"] = "CLOSED"
        lot["closed_at"] = clock_stamp()
        lot["_dt_closed_at"] = clock_now()
        b = STORE["bins"].get(lot["bin_id"])
        if b is not None:
            recompute_bin(b)


# ---------------------------------------------------------------------------
# Food-safety posture
# ---------------------------------------------------------------------------
def wash_result(turbidity_ntu, chlorine_ppm, water_temp_f):
    if (
        turbidity_ntu <= WASH_MAX_TURBIDITY_NTU
        and CHLORINE_MIN_PPM <= chlorine_ppm <= CHLORINE_MAX_PPM
        and WASH_TEMP_MIN_F <= water_temp_f <= WASH_TEMP_MAX_F
    ):
        return "PASS"
    return "FAIL"


def recompute_posture(shed):
    old = shed["posture"]
    if shed["wash_quarantine_flag"] or shed["audit_failed_flag"]:
        new = "QUARANTINED"
    elif shed["consecutive_wash_failures"] >= RESTRICTED_CONSECUTIVE_FAILS:
        new = "RESTRICTED"
    else:
        new = "NORMAL"
    if new != old:
        shed["posture"] = new
        touch(shed)
        if new == "QUARANTINED":
            quarantine_cascade(shed)


def quarantine_cascade(shed):
    """PRD 3.7: entering QUARANTINED aborts scheduled runs, holds CLEAR lots,
    and releases reservations on newly held lots with per-order coverage recheck."""
    # 1. Every SCHEDULED run whose order names this shed auto-aborts; its order
    #    drops PACKING -> ALLOCATED with reservations retained.
    for run in list(STORE["runs"].values()):
        if run["status"] != "SCHEDULED":
            continue
        order = STORE["orders"].get(run["pack_order_id"])
        if order is None or order["shed_id"] != shed["id"]:
            continue
        run["status"] = "ABORTED"
        touch(run)
        if order["status"] == "PACKING":
            order["status"] = "ALLOCATED"
            touch(order)
    # 2. Every CLEAR lot in this shed's bins transitions to ON_HOLD.
    bin_ids = {b["id"] for b in STORE["bins"].values() if b["shed_id"] == shed["id"]}
    held = [
        lot
        for lot in STORE["lots"].values()
        if lot["bin_id"] in bin_ids
        and lot["storage_status"] == "BINNED"
        and lot["quality_status"] == "CLEAR"
    ]
    for lot in held:
        lot["quality_status"] = "ON_HOLD"
        touch(lot)
    # 3. Reservation release + coverage recheck for each newly held lot.
    for lot in held:
        release_lot_reservations_and_recheck(lot)


def release_lot_reservations_and_recheck(lot):
    """Release every reservation held against `lot`; for each affected order,
    if remaining packed-equiv coverage falls below outstanding need, release ALL
    of the order's reservations and reset ALLOCATED|PACKING -> REQUESTED."""
    affected = [
        o
        for o in STORE["orders"].values()
        if any(r["field_lot_id"] == lot["id"] for r in o["reservations"])
    ]
    for order in affected:
        kept = [r for r in order["reservations"] if r["field_lot_id"] != lot["id"]]
        order["reservations"] = kept
        recompute_lot_reserved(lot)
        touch(lot)
        need = order["requested_packed_cwt"] - order["packed_to_date_cwt"]
        coverage = sum((r["packed_equiv_cwt"] for r in kept), Decimal("0"))
        if coverage < need and order["status"] in ("ALLOCATED", "PACKING"):
            # Full de-allocation reset: release every remaining reservation.
            remaining_lots = {r["field_lot_id"] for r in kept}
            order["reservations"] = []
            order["status"] = "REQUESTED"
            touch(order)
            for lid in remaining_lots:
                other = STORE["lots"].get(lid)
                if other is not None:
                    recompute_lot_reserved(other)
                    touch(other)
        else:
            touch(order)
        if order["contract_id"] is not None:
            c = STORE["contracts"].get(order["contract_id"])
            if c is not None:
                recompute_contract(c)


# ---------------------------------------------------------------------------
# Assessments / packout fractions
# ---------------------------------------------------------------------------
def latest_assessment(lot):
    """Latest by (assessment_date DESC, created_at DESC)."""
    best = None
    best_key = None
    for a in STORE["assessments"].values():
        if a["field_lot_id"] != lot["id"]:
            continue
        key = (a["_dt_assessment_date"], a["created_at"])
        if best is None or key > best_key:
            best = a
            best_key = key
    return best


def lot_packout_fraction(lot):
    a = latest_assessment(lot)
    if a is None:
        return DEFAULT_BLEND_PACKOUT_FRACTION
    return a["packable_fraction"]


def shed_blend_fraction(shed_id):
    """Realized shed-wide packout over COMPLETED runs (ABORTED excluded)."""
    packed = Decimal("0")
    raw = Decimal("0")
    for run in STORE["runs"].values():
        if run["status"] != "COMPLETED":
            continue
        order = STORE["orders"].get(run["pack_order_id"])
        if order is None or order["shed_id"] != shed_id:
            continue
        for d in STORE["draws"].values():
            if d["pack_run_id"] == run["id"]:
                packed += d["packed_cwt"]
                raw += d["raw_drawn_cwt"]
    if raw == 0:
        return DEFAULT_BLEND_PACKOUT_FRACTION
    return rhu(packed / raw, FOUR)


def order_fraction(order, lot):
    if order["allocation_policy"] == "SHED_BLEND":
        return shed_blend_fraction(order["shed_id"])
    return lot_packout_fraction(lot)


# ---------------------------------------------------------------------------
# Allocation (PRD 3.4)
# ---------------------------------------------------------------------------
def eligible_pool(order):
    """BINNED + CLEAR + variety match + bin in order's shed + shed not
    QUARANTINED + allocatable (available - reserved) > 0.
    Ranked harvest_date ASC, tie-break created_at ASC (never id)."""
    pool = []
    for lot in STORE["lots"].values():
        if lot["storage_status"] != "BINNED" or lot["quality_status"] != "CLEAR":
            continue
        if lot["variety"] != order["variety"]:
            continue
        b = STORE["bins"].get(lot["bin_id"])
        if b is None or b["shed_id"] != order["shed_id"]:
            continue
        shed = STORE["sheds"].get(b["shed_id"])
        if shed is None or shed["posture"] == "QUARANTINED":
            continue
        allocatable = lot["available_cwt"] - lot["reserved_cwt"]
        if allocatable <= 0:
            continue
        pool.append((lot, allocatable))
    pool.sort(key=lambda item: (item[0]["_dt_harvest_date"], item[0]["created_at"]))
    return pool


def open_market_cap(order):
    """max(0, sum over eligible lots of rhu(allocatable * f_lot_assessment, 2)
    - sum over ACTIVE contracts of the variety of remaining_committed_cwt).
    The cap ALWAYS uses the lot-assessment basis."""
    total = Decimal("0")
    for lot, allocatable in eligible_pool(order):
        f = lot_packout_fraction(lot)
        total += rhu(allocatable * f, TWO)
    for c in STORE["contracts"].values():
        if c["status"] == "ACTIVE" and c["variety"] == order["variety"]:
            total -= c["remaining_committed_cwt"]
    if total < 0:
        total = Decimal("0")
    return total


def allocation_need(order):
    covered = sum((r["packed_equiv_cwt"] for r in order["reservations"]), Decimal("0"))
    return order["requested_packed_cwt"] - order["packed_to_date_cwt"] - covered


def run_waterfall(order, need):
    """Walk the ranked pool writing reservations. Caller has already verified
    pool coverage (atomic pre-flight). NOTE: lot.reserved_cwt is reconciled by
    the caller after the order's status transition, because reserved_cwt only
    counts reservations on ALLOCATED/PACKING orders."""
    remaining = need
    for lot, allocatable in eligible_pool(order):
        if remaining <= 0:
            break
        f = order_fraction(order, lot)
        cover = floor2(allocatable * f)
        take = min(remaining, cover)
        if take <= 0 or f == 0:
            continue
        raw = min(allocatable, rhu(take / f, TWO))
        existing = next(
            (r for r in order["reservations"] if r["field_lot_id"] == lot["id"]), None
        )
        if existing is not None:
            existing["raw_cwt"] += raw
            existing["packed_equiv_cwt"] += take
        else:
            order["reservations"].append(
                {
                    "field_lot_id": lot["id"],
                    "raw_cwt": raw,
                    "packed_equiv_cwt": take,
                }
            )
        touch(lot)
        remaining -= take


def pool_covers(order, need):
    pool = eligible_pool(order)
    if not pool:
        return False
    total = Decimal("0")
    for lot, allocatable in pool:
        total += floor2(allocatable * order_fraction(order, lot))
    return total >= need


# ---------------------------------------------------------------------------
# Wash freshness gate for pack-run creation (PRD 3.5)
# ---------------------------------------------------------------------------
def shed_wash_fresh(shed):
    """The most recent PASS check (measured_at DESC, created_at DESC) must lie
    within 12h (NORMAL) or 4h (RESTRICTED) of the logical clock, inclusive.
    FAILs after the anchor do not extend or invalidate it; no PASS => stale."""
    passes = [
        c
        for c in STORE["checks"].values()
        if c["shed_id"] == shed["id"] and c["result"] == "PASS"
    ]
    if not passes:
        return False
    anchor = max(passes, key=lambda c: (c["_dt_measured_at"], c["created_at"]))
    hours = (
        WASH_VALIDITY_HOURS_RESTRICTED
        if shed["posture"] == "RESTRICTED"
        else WASH_VALIDITY_HOURS_NORMAL
    )
    return clock_now() - anchor["_dt_measured_at"] <= timedelta(hours=hours)


def line_schedule_conflict(order, new_start, new_end):
    """Conflict with another SCHEDULED run on the same shed iff
    new.start < other.end + buffer AND other.start < new.end + buffer,
    buffer = 1h when varieties differ else 0 (half-open adjacency allowed)."""
    for run in STORE["runs"].values():
        if run["status"] != "SCHEDULED":
            continue
        other_order = STORE["orders"].get(run["pack_order_id"])
        if other_order is None or other_order["shed_id"] != order["shed_id"]:
            continue
        buffer = (
            timedelta(0)
            if other_order["variety"] == order["variety"]
            else LINE_BUFFER_DIFFERENT_VARIETY
        )
        if new_start < run["_dt_scheduled_end"] + buffer and run[
            "_dt_scheduled_start"
        ] < new_end + buffer:
            return True
    return False


# ---------------------------------------------------------------------------
# Grower settlement math (PRD 3.9)
# ---------------------------------------------------------------------------
def compute_pool_price():
    """Volume-weighted realized price over SHIPPED orders; fallback blend over
    ACTIVE contracts; else 0."""
    shipped = [o for o in STORE["orders"].values() if o["status"] == "SHIPPED"]
    if shipped:
        num = Decimal("0")
        den = Decimal("0")
        for o in shipped:
            if o["order_type"] == "CONTRACT":
                c = STORE["contracts"].get(o["contract_id"])
                price = c["price_cents_per_cwt"] if c is not None else 0
            else:
                price = o["market_price_cents_per_cwt"] or 0
            num += o["packed_to_date_cwt"] * Decimal(price)
            den += o["packed_to_date_cwt"]
        if den > 0:
            return rhu(num / den, TWO)
    active = [c for c in STORE["contracts"].values() if c["status"] == "ACTIVE"]
    if active:
        num = sum(
            (c["committed_volume_cwt"] * Decimal(c["price_cents_per_cwt"]) for c in active),
            Decimal("0"),
        )
        den = sum((c["committed_volume_cwt"] for c in active), Decimal("0"))
        if den > 0:
            return rhu(num / den, TWO)
    return Decimal("0")


def grower_lots(grower_id):
    return [l for l in STORE["lots"].values() if l["grower_id"] == grower_id]


def whole_weeks(start_dt, end_dt):
    if start_dt is None or end_dt is None:
        return 0
    delta = end_dt - start_dt
    weeks = int(delta.total_seconds() // WEEK_SECONDS)
    return weeks if weeks > 0 else 0


def compute_settlement(grower_id, variant):
    """variant: 'provisional' (estimates for unclosed lots, clock-based weeks)
    or 'final' (actual packed totals, closed_at-based weeks). Per-lot money
    lines are rounded half-up to 2dp first, then summed (pinned order)."""
    lots = grower_lots(grower_id)
    basis = Decimal("0")
    for lot in lots:
        if variant == "final" or lot["storage_status"] == "CLOSED":
            term = lot["packed_total_cwt"]
        else:
            term = lot["packed_total_cwt"] + lot["available_cwt"] * lot_packout_fraction(lot)
        basis += rhu(term, TWO)

    pool_price = compute_pool_price()
    gross = rhu(basis * pool_price, TWO)

    storage_fees = Decimal("0")
    inhibitor_fees = Decimal("0")
    processing_credits = Decimal("0")
    for lot in lots:
        if variant == "final":
            weeks = whole_weeks(lot["_dt_binned_at"], lot["_dt_closed_at"])
        else:
            weeks = (
                whole_weeks(lot["_dt_binned_at"], clock_now())
                if lot["_dt_binned_at"] is not None
                else 0
            )
        storage_fees += rhu(
            STORAGE_FEE_CENTS_PER_CWT_WEEK * lot["original_weight_cwt"] * weeks, TWO
        )
        inhibitor_fees += rhu(
            INHIBITOR_FEE_CENTS_PER_CWT
            * lot["original_weight_cwt"]
            * lot["inhibitor_application_count"],
            TWO,
        )
        processing_credits += rhu(
            PROCESSING_CREDIT_CENTS_PER_CWT * lot["processing_credit_cwt"], TWO
        )

    net = gross - storage_fees - inhibitor_fees + processing_credits
    return {
        "packed_cwt_basis": basis,
        "pool_price_cents": pool_price,
        "gross_cents": gross,
        "storage_fees_cents": storage_fees,
        "inhibitor_fees_cents": inhibitor_fees,
        "processing_credits_cents": processing_credits,
        "net_payable_cents": net,
    }

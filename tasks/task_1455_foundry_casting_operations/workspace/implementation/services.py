"""Shared business logic: derived foundry state, ledgers, cascades, run-ops
sweep, casting apportionment, melt chemistry (PRD section 3)."""

from datetime import timedelta
from decimal import Decimal

from db import all_of, get, logical_now, new_record, touch
from util import D, q2, q4, ceil_int

CURTAIL_THRESHOLD_KG = Decimal("500")  # PRD 2.9 boundary: ==500 CURTAILED

SHRINK = {
    ("FERROUS", "SAND"): Decimal("0.0104"),
    ("FERROUS", "INVESTMENT"): Decimal("0.0120"),
    ("ALUMINUM", "SAND"): Decimal("0.0130"),
    ("ALUMINUM", "INVESTMENT"): Decimal("0.0110"),
}
MA_CAP = {"SAND": Decimal("6.0"), "INVESTMENT": Decimal("2.5")}
QUALIFY_TOL_MM = Decimal("0.3")
SCRAP_PROVISIONAL_YIELD = Decimal("0.85")
ADDITIVE_PURITY = Decimal("1.00")


# ---------------------------------------------------------------------------
# Foundry derivation helpers (cross-foundry rule PRD 2.11)
# ---------------------------------------------------------------------------

def foundry_id_of_mold(mold):
    order = get("orders", mold["order_id"])
    return order["foundry_id"] if order else None


def foundry_id_of_slot(slot):
    line = get("equipment", slot["molding_line_id"])
    return line["foundry_id"] if line else None


def foundry_id_of_casting(casting):
    mold = get("molds", casting["mold_id"])
    return foundry_id_of_mold(mold) if mold else None


# ---------------------------------------------------------------------------
# Derived foundry fields (PRD 2.9): recomputed on sand/alloy activity.
# ---------------------------------------------------------------------------

def recompute_posture(foundry, bump=True):
    avail = Decimal("0")
    for b in all_of("sand_batches"):
        if b["foundry_id"] == foundry["id"] and b["status"] == "IN_SERVICE":
            avail += b["current_weight_kg"]
    avail = q2(avail)
    if avail == 0:
        posture = "EMBARGO"
    elif avail <= CURTAIL_THRESHOLD_KG:
        posture = "CURTAILED"
    else:
        posture = "OPEN"
    changed = (foundry["sand_available_kg"] != avail or foundry["posture"] != posture)
    foundry["sand_available_kg"] = avail
    foundry["posture"] = posture
    if changed and bump:
        touch(foundry)


def recompute_alloy(foundry, bump=True):
    avail = Decimal("0")
    for lot in all_of("return_lots"):
        if lot["foundry_id"] == foundry["id"] and lot["status"] == "ASSAYED":
            avail += lot["remaining_weight_kg"]
    avail = q2(avail)
    changed = foundry["alloy_available_kg"] != avail
    foundry["alloy_available_kg"] = avail
    if changed and bump:
        touch(foundry)


def foundry_of(fid):
    return get("foundries", fid)


def recompute_posture_by_id(fid, bump=True):
    f = foundry_of(fid)
    if f:
        recompute_posture(f, bump=bump)


def recompute_alloy_by_id(fid, bump=True):
    f = foundry_of(fid)
    if f:
        recompute_alloy(f, bump=bump)


# ---------------------------------------------------------------------------
# Order derived counters (PRD 3.3 / 3.5)
# ---------------------------------------------------------------------------

def recompute_pipeline(order, bump=True):
    total = 0
    for m in all_of("molds"):
        if m["order_id"] == order["id"] and m["status"] != "SCRAPPED":
            pattern = get("patterns", m["pattern_id"])
            if pattern:
                total += pattern["impressions"]
    if order["pipeline_count"] != total:
        order["pipeline_count"] = total
        if bump:
            touch(order)


def pipeline_cap(order):
    return ceil_int(D(order["quantity"]) * (Decimal("1") + D(order["overage_pct"])))


def order_casting_accepted(order):
    """Casting quality -> ACCEPTED / USE_AS_IS side effects (PRD 3.3)."""
    order["accepted_count"] += 1
    if order["status"] == "IN_PRODUCTION" and order["accepted_count"] >= order["quantity"]:
        order["status"] = "FULFILLED"
        order["fulfilled_at"] = logical_now()
    touch(order)


def order_casting_scrapped(order):
    order["scrapped_count"] += 1
    touch(order)


# ---------------------------------------------------------------------------
# Casting creation at pour (PRD 3.5 casting_weight apportionment)
# ---------------------------------------------------------------------------

def create_castings_for_mold(mold, pattern):
    n = pattern["impressions"]
    metal = mold["metal_weight_kg"]
    base = q2(metal / n)
    for i in range(1, n + 1):
        if i < n:
            weight = base
        else:
            # per-mold remainder always to the LAST cavity
            weight = q2(metal - base * (n - 1))
        new_record("castings", {
            "mold_id": mold["id"],
            "order_id": mold["order_id"],
            "cavity_index": i,
            "casting_weight_kg": weight,
            "routing_status": "SHAKEOUT",
            "quality_status": "PENDING",
        })


# ---------------------------------------------------------------------------
# Sand quarantine cascade (PRD 3.8): RECLAIMING batch fails LOI test.
# ---------------------------------------------------------------------------

def quarantine_cascade(batch):
    affected_orders = set()
    for mold in list(all_of("molds")):
        if mold["sand_batch_id"] != batch["id"] or mold["status"] != "ASSEMBLED":
            continue
        # link 1: ASSEMBLED mold -> SCRAPPED
        mold["status"] = "SCRAPPED"
        slot_id = mold["pour_slot_id"]
        mold["pour_slot_id"] = None
        touch(mold)
        affected_orders.add(mold["order_id"])
        if slot_id:
            slot = get("pour_slots", slot_id)
            if slot and slot["status"] == "BOOKED":
                # link 2: the BOOKED slot is cancelled
                slot["status"] = "CANCELLED"
                touch(slot)
                # link 3: remaining ASSEMBLED molds on the slot are unlinked
                for mid in slot["mold_ids"]:
                    other = get("molds", mid)
                    if (other and other["id"] != mold["id"]
                            and other["status"] == "ASSEMBLED"
                            and other["pour_slot_id"] == slot["id"]):
                        other["pour_slot_id"] = None
                        touch(other)
                        affected_orders.add(other["order_id"])
    for oid in affected_orders:
        order = get("orders", oid)
        if order:
            recompute_pipeline(order)


# ---------------------------------------------------------------------------
# Melt chemistry (PRD 3.4)
# ---------------------------------------------------------------------------

def spec_elements(spec):
    """chemistry_spec: per-element {min,max} map plus optional ce_max."""
    if not isinstance(spec, dict):
        return {}
    if isinstance(spec.get("elements"), dict):
        return spec["elements"]
    return {k: v for k, v in spec.items() if k != "ce_max"}


def recompute_chemistry(heat):
    additions = heat["_additions"]
    total = Decimal("0")
    for a in additions:
        total += a["weight"]
    comp = {}
    if total > 0:
        elements = []
        for a in additions:
            for e in a["composition"]:
                if e not in elements:
                    elements.append(e)
        for e in elements:
            s = Decimal("0")
            for a in additions:
                s += a["weight"] * a["composition"].get(e, Decimal("0"))
            comp[e] = q4(s / total)
    heat["charge_total_kg"] = q2(total)
    heat["charge_composition"] = comp


def certifies(spec, reading):
    """spectro_certification: inclusive element bounds; CE = C + Si/3 + P/2."""
    if not isinstance(reading, dict):
        return False
    for e, rng in spec_elements(spec).items():
        if e not in reading or reading[e] is None:
            return False
        try:
            v = Decimal(str(reading[e]))
            lo = Decimal(str(rng.get("min")))
            hi = Decimal(str(rng.get("max")))
        except Exception:
            return False
        if not (lo <= v <= hi):
            return False
    ce_max = spec.get("ce_max") if isinstance(spec, dict) else None
    if ce_max is not None:
        def _rv(name):
            v = reading.get(name)
            return Decimal(str(v)) if v is not None else Decimal("0")
        try:
            ce = _rv("C") + _rv("Si") / Decimal("3") + _rv("P") / Decimal("2")
            if ce > Decimal(str(ce_max)):
                return False
        except Exception:
            return False
    return True


def auto_correct_masses(heat):
    """corrective_charge_masses: pinned frozen-baseline single pass."""
    spec = heat["chemistry_spec"]
    W0 = heat["charge_total_kg"]
    C0 = heat["charge_composition"] or {}
    masses = {}
    for e, rng in spec_elements(spec).items():
        try:
            lo = Decimal(str(rng.get("min")))
            hi = Decimal(str(rng.get("max")))
        except Exception:
            continue
        cur = C0.get(e, Decimal("0"))
        if cur < lo:
            target = (lo + hi) / Decimal("2")
            deficit = target - cur
            denom = ADDITIVE_PURITY - target / Decimal("100")
            if denom <= 0:
                continue
            mass = q2((deficit / Decimal("100")) * W0 / denom)
            if mass > 0:
                masses[e] = mass
    return masses


# ---------------------------------------------------------------------------
# Ops epoch sweep (PRD 3.1)
# ---------------------------------------------------------------------------

def run_ops_sweep(foundry):
    now = logical_now()
    fid = foundry["id"]

    # BOOKED slots past end_at -> EXPIRED (mold links cleared, molds stay ASSEMBLED)
    for slot in list(all_of("pour_slots")):
        if foundry_id_of_slot(slot) != fid:
            continue
        if slot["status"] == "BOOKED" and now > slot["_end_dt"]:
            slot["status"] = "EXPIRED"
            touch(slot)
            for mid in slot["mold_ids"]:
                mold = get("molds", mid)
                if mold and mold["pour_slot_id"] == slot["id"]:
                    mold["pour_slot_id"] = None
                    touch(mold)

    # POURED molds whose cooling fully elapsed -> COOLED
    for mold in list(all_of("molds")):
        if foundry_id_of_mold(mold) != fid:
            continue
        if (mold["status"] == "POURED" and mold["poured_at"] is not None
                and now >= mold["poured_at"] + timedelta(hours=mold["cooling_hours"])):
            mold["status"] = "COOLED"
            touch(mold)

    # SHAKEOUT molds whose castings are all terminal -> CLOSED
    for mold in list(all_of("molds")):
        if foundry_id_of_mold(mold) != fid:
            continue
        if mold["status"] == "SHAKEOUT":
            castings = [c for c in all_of("castings") if c["mold_id"] == mold["id"]]
            if all(c["routing_status"] == "COMPLETE" or c["quality_status"] == "SCRAPPED"
                   for c in castings):
                mold["status"] = "CLOSED"
                touch(mold)

    # TAPPED heats with no BOOKED slot -> POURED_OUT
    booked_heat_ids = {s["heat_id"] for s in all_of("pour_slots") if s["status"] == "BOOKED"}
    for heat in list(all_of("heats")):
        if heat["foundry_id"] != fid:
            continue
        if heat["status"] == "TAPPED" and heat["id"] not in booked_heat_ids:
            heat["status"] = "POURED_OUT"
            touch(heat)

    # FULFILLED orders with no open claims -> CLOSED
    open_states = {"FILED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED"}
    for order in list(all_of("orders")):
        if order["foundry_id"] != fid:
            continue
        if order["status"] == "FULFILLED":
            has_open = any(
                c["order_id"] == order["id"] and c["status"] in open_states
                for c in all_of("claims")
            )
            if not has_open:
                order["status"] = "CLOSED"
                touch(order)

    # posture recomputed; epoch + version increment exactly once
    recompute_posture(foundry, bump=False)
    foundry["ops_run_index"] += 1
    touch(foundry)

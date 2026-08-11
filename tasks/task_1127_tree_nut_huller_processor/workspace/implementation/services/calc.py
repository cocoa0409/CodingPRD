"""Calculation rules (SCAFFOLD §1.3 / PRD §2.6, §3).

All weight arithmetic uses Decimal with ROUND_HALF_UP at 2 decimal places;
all money is integer cents with per-component rounding at 0 decimal places.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

MOISTURE_STD_PCT = Decimal("8.0")
SHRINK_PER_MOISTURE_POINT = Decimal("0.01")
AFLATOXIN_LIMIT_PPB = Decimal("20.0")
PREMIUM_GRADE_PCT = Decimal("0.70")
DEDUCT_PER_MOISTURE_POINT = Decimal("0.005")

D2 = Decimal("0.01")
D0 = Decimal("1")
D1 = Decimal("0.1")


def D(x):
    return Decimal(str(x))


def round2(x):
    """Round-half-up to 2 dp; returns a float for JSON serialization."""
    return float(D(x).quantize(D2, rounding=ROUND_HALF_UP))


def round0(x):
    """Round-half-up to whole cents; returns an int."""
    return int(D(x).quantize(D0, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- aflatoxin

def aflatoxin_verdict(ppb):
    """1-decimal-place comparison; the boundary 20.0 itself is FAIL (>=)."""
    rounded = D(ppb).quantize(D1, rounding=ROUND_HALF_UP)
    return "FAIL" if rounded >= AFLATOXIN_LIMIT_PPB else "PASS"


# -------------------------------------------------------- kernel weight

def provisional_kernel_lbs(lot):
    """Forward-looking estimate from the intake MOISTURE_KERNEL test."""
    excess = max(Decimal(0), D(lot["intake_moisture_pct"]) - MOISTURE_STD_PCT)
    value = (
        D(lot["gross_weight_lbs"])
        * D(lot["intake_kernel_pct"])
        * (Decimal(1) - D(lot["intake_fm_pct"]))
        * (Decimal(1) - SHRINK_PER_MOISTURE_POINT * excess)
    )
    return round2(value)


def completed_runs(lot_id):
    return [r for r in db.store.runs.values()
            if r["lot_id"] == lot_id and r["status"] == "COMPLETED"]


def lot_outputs(lot_id):
    """Sum of outputs over the lot's COMPLETED runs only."""
    kernel = Decimal(0)
    shell = Decimal(0)
    hull = Decimal(0)
    for r in completed_runs(lot_id):
        kernel += D(r["kernel_out_lbs"])
        shell += D(r["shell_out_lbs"])
        hull += D(r["hull_out_lbs"])
    return round2(kernel), round2(shell), round2(hull)


def latest_test(lot_id, test_type):
    tests = [t for t in db.store.lab_tests.values()
             if t["lot_id"] == lot_id and t["test_type"] == test_type]
    if not tests:
        return None
    tests.sort(key=lambda t: (t["recorded_at"], t["_seq"]))
    return tests[-1]


def recompute_graded_kernel_weight(lot):
    """Final variant: completed-run kernel_out * latest KERNEL_GRADE edible pct."""
    grade = latest_test(lot["id"], "KERNEL_GRADE")
    if grade is None:
        return
    kernel, _, _ = lot_outputs(lot["id"])
    lot["graded_kernel_weight_lbs"] = round2(D(kernel) * D(grade["edible_kernel_pct"]))


# ------------------------------------------------------------- settlement

def settlement_components(lot, grower, graded_kernel_weight_lbs):
    """Component-rounded pricing: each component rounded half-up to whole
    cents BEFORE summation; total is the integer sum of rounded components."""
    effective = lot["post_dry_moisture_pct"]
    if effective is None:
        effective = lot["intake_moisture_pct"]
    excess = max(Decimal(0), D(effective) - MOISTURE_STD_PCT)
    base_cents = round0(D(graded_kernel_weight_lbs) * D(grower["base_price_cents_per_lb"]))
    if D(lot["edible_kernel_pct"]) >= PREMIUM_GRADE_PCT:
        premium_cents = round0(D(base_cents) * D(grower["premium_rate_pct"]))
    else:
        premium_cents = 0
    moisture_deduction_cents = round0(D(base_cents) * DEDUCT_PER_MOISTURE_POINT * excess)
    total_cents = base_cents + premium_cents - moisture_deduction_cents
    return base_cents, premium_cents, moisture_deduction_cents, total_cents


# ------------------------------------------------------------------- bins

OCCUPIED_PLACEMENT_STATUSES = ("STORED", "FUMIGATION_HOLD", "QUARANTINED")


def placement_allocated_planned_lbs(placement_id):
    total = Decimal(0)
    for s in db.store.shipments.values():
        if s["status"] in ("PLANNED", "BLOCKED"):
            for a in s["allocations"]:
                if a["placement_id"] == placement_id:
                    total += D(a["quantity_lbs"])
    return round2(total)


def bin_capacity(bin_rec):
    """Returns (occupied_lbs, available_now_lbs, projected_available_lbs)."""
    occupied = Decimal(0)
    allocated = Decimal(0)
    for p in db.store.placements.values():
        if p["bin_id"] == bin_rec["id"] and p["status"] in OCCUPIED_PLACEMENT_STATUSES:
            occupied += D(p["remaining_lbs"])
            allocated += D(placement_allocated_planned_lbs(p["id"]))
    available_now = D(bin_rec["capacity_lbs"]) - occupied
    projected = available_now - allocated
    return round2(occupied), round2(available_now), round2(projected)


# ----------------------------------------------------------- FIFO walking

def fifo_eligible(bin_id, product_form):
    elig = [p for p in db.store.placements.values()
            if p["bin_id"] == bin_id
            and p["product_form"] == product_form
            and p["status"] == "STORED"]
    # FIFO: placed_at ASC, created_at ASC tie-break, never id; _seq keeps
    # full ordering deterministic when the logical clock ties both fields.
    elig.sort(key=lambda p: (p["placed_at"], p["created_at"], p["_seq"]))
    return elig


def fifo_allocate(bin_id, product_form, quantity_lbs):
    """Walk eligible placements oldest-first, taking free weight from each.

    Returns (allocations, remaining_need). remaining_need > 0 means the
    free pool cannot cover the request.
    """
    need = D(quantity_lbs)
    allocations = []
    for p in fifo_eligible(bin_id, product_form):
        if need <= 0:
            break
        free = D(p["remaining_lbs"]) - D(placement_allocated_planned_lbs(p["id"]))
        if free <= 0:
            continue
        take = min(free, need)
        allocations.append({
            "placement_id": p["id"],
            "lot_id": p["lot_id"],
            "quantity_lbs": round2(take),
        })
        need -= take
    return allocations, need


# ------------------------------------------------------------ byproducts

def byproduct_available_stock(product_form):
    field = "hull_out_lbs" if product_form == "HULL" else "shell_out_lbs"
    produced = Decimal(0)
    for r in db.store.runs.values():
        if r["status"] == "COMPLETED":
            produced += D(r[field])
    sold = Decimal(0)
    for s in db.store.byproduct_sales.values():
        if s["product_form"] == product_form:
            sold += D(s["quantity_lbs"])
    return produced - sold


# ----------------------------------------------------------- scheduling

def dryer_conflict(dryer_id, start_dt, end_dt):
    """Half-open [start_at, end_at) overlap against SCHEDULED/DRYING batches."""
    for b in db.store.batches.values():
        if b["dryer_id"] != dryer_id or b["status"] not in ("SCHEDULED", "DRYING"):
            continue
        if start_dt < b["_end_dt"] and end_dt > b["_start_dt"]:
            return True
    return False


def fumigation_effective_end(event):
    if event["_cleared_dt"] is not None:
        return event["_cleared_dt"]
    return event["_start_dt"] + timedelta(hours=event["aeration_hours"])


def fumigation_conflict(bin_id, start_dt, aeration_hours):
    """Closed-interval overlap INCLUDING the aeration buffer; touching
    endpoints conflict (both endpoints inclusive)."""
    new_end = start_dt + timedelta(hours=aeration_hours)
    for e in db.store.fumigations.values():
        if e["bin_id"] != bin_id or e["status"] not in ("SCHEDULED", "ACTIVE", "AERATING"):
            continue
        e_end = fumigation_effective_end(e)
        if start_dt <= e_end and new_end >= e["_start_dt"]:
            return True
    return False


# -------------------------------------------------------------- lot output

def lot_output_for_form(lot_id, product_form):
    """Per-lot output ceiling for placements. IN_SHELL product carries the
    kernel still in its shell, so its output is kernel + shell weight."""
    kernel, shell, hull = lot_outputs(lot_id)
    if product_form == "KERNEL":
        return kernel
    if product_form == "SHELL":
        return shell
    if product_form == "HULL":
        return hull
    # IN_SHELL
    return round2(D(kernel) + D(shell))


def cumulative_placed(lot_id, product_form):
    total = Decimal(0)
    for p in db.store.placements.values():
        if p["lot_id"] == lot_id and p["product_form"] == product_form:
            total += D(p["quantity_lbs"])
    return total


def contract_reserved_delivered(contract_id):
    """reserved = sum over PLANNED/BLOCKED shipments; delivered = DELIVERED."""
    reserved = Decimal(0)
    delivered = Decimal(0)
    for s in db.store.shipments.values():
        if s["contract_id"] == contract_id:
            if s["status"] in ("PLANNED", "BLOCKED"):
                reserved += D(s["quantity_lbs"])
            elif s["status"] == "DELIVERED":
                delivered += D(s["quantity_lbs"])
    return round2(reserved), round2(delivered)

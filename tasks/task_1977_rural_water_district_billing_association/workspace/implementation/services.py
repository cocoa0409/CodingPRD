"""Business logic: calculations, cascades, serializers (PRD §3)."""
from decimal import Decimal, ROUND_HALF_UP

import db

# Constants (scaffold calculations)
NOTICE_DAY_THRESHOLD = 10
DISCONNECT_DAY_THRESHOLD = 45
NOTIFY_WINDOW_HOURS = 24
SAMPLING_WINDOW_HOURS = 72
REQUIRED_CLEAR_SAMPLES = 2
QUORUM_FOR = 3
QUORUM_AGAINST = 3
FEASIBILITY_FEE_FLOOR_CENTS = 25000
FEASIBILITY_FEE_PCT = Decimal("0.2")
WITHDRAWAL_FLOOR_NUM = 3   # 0.75 as exact rational 3/4
WITHDRAWAL_FLOOR_DEN = 4


# ---------------------------------------------------------------- helpers

def new_common():
    now = db.now_iso()
    return {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def new_ledger():
    return {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }


def touch(e):
    e["updated_at"] = db.now_iso()
    e["version"] = e.get("version", 1) + 1


def bump_district(d):
    touch(d)


def public(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


# ---------------------------------------------------------------- serializers

def ser_district(d):
    return public(d)


def ser_area(a):
    return public(a)


def ser_member(m):
    return public(m)


def ser_tap(t):
    return public(t)


def ser_schedule(s):
    return public(s)


def ser_reading(r):
    return public(r)


def ser_master(r):
    return public(r)


def ser_payment(p):
    return public(p)


def ser_reserve_entry(e):
    return public(e)


def ser_notification(n):
    return public(n)


def ser_sample(s):
    return public(s)


def ser_resolution(r):
    return public(r)


def ser_petition(p):
    return public(p)


def ser_boil_order(o):
    return public(o)


def invoice_dpd(inv):
    """days_past_due: live while unpaid; frozen at disconnect / once paid."""
    frozen = inv.get("_dpd_frozen")
    if frozen is not None:
        return frozen
    cycle = db.billing_cycles.get(inv["cycle_id"])
    if cycle is None:
        return 0
    delta = (db.now_dt() - cycle["_due_dt"]).total_seconds()
    days = int(delta // 86400)
    return max(0, days)


def ser_invoice(inv):
    out = public(inv)
    out["days_past_due"] = invoice_dpd(inv)
    return out


def ser_cycle(c):
    out = public(c)
    total = 0
    for inv in db.invoices.values():
        if inv["cycle_id"] == c["id"] and inv["billing_status"] != "VOID":
            total += inv["total_cents"]
    out["billed_total_cents"] = total
    return out


# ------------------------------------------------------- covenant (§3.8)

def recompute_reserve(d):
    d["reserve_deficit_cents"] = max(0, d["reserve_target_cents"] - d["reserve_balance_cents"])
    d["covenant_status"] = (
        "RESERVE_DEFICIENT" if d["reserve_deficit_cents"] > 0 else "IN_COMPLIANCE"
    )


def post_reserve_entry(district_id, entry_type, amount_cents, cycle_id):
    """Append a ledger row and move the balance. Does NOT bump the district
    version: that rides on the enclosing district-level event (cycle close,
    resolution adoption), each of which increments the version exactly once.
    """
    d = db.districts[district_id]
    d["reserve_balance_cents"] += amount_cents
    e = new_ledger()
    e.update({
        "district_id": district_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "cycle_id": cycle_id,
        "resulting_balance_cents": d["reserve_balance_cents"],
    })
    db.reserve_entries[e["id"]] = e
    recompute_reserve(d)
    return e


def monthly_deposit_cents(d):
    """ceil(annual_debt_service_cents / 120)."""
    annual = d["annual_debt_service_cents"]
    return -(-annual // 120)


# ------------------------------------------------- tiered charges (§3.4)

def ceil_div(a, b):
    return -(-a // b)


def tiered_usage_charge(usage_gallons, sched):
    billable = max(0, usage_gallons - sched["included_gallons"])
    tier2_gal = min(billable, sched["tier2_cap_gallons"] - sched["included_gallons"])
    tier3_gal = max(0, usage_gallons - sched["tier2_cap_gallons"])
    tier2_charge = ceil_div(tier2_gal, 1000) * sched["tier2_rate_cents_per_kgal"]
    tier3_charge = ceil_div(tier3_gal, 1000) * sched["tier3_rate_cents_per_kgal"]
    return tier2_charge + tier3_charge


def invoice_amounts(usage_gallons, sched, reconnect_fee):
    usage_charge = tiered_usage_charge(usage_gallons, sched)
    base = max(sched["base_minimum_cents"], sched["base_minimum_cents"] + usage_charge)
    total = base + reconnect_fee
    return usage_charge, sched["base_minimum_cents"], reconnect_fee, total


# ------------------------------------------------------ water loss (§3.5)

def round3_half_up(num, den):
    if den == 0:
        return 0.0
    val = (Decimal(num) * Decimal(100)) / Decimal(den)
    return float(val.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def cycle_readings(cycle_id):
    return [r for r in db.readings.values() if r["cycle_id"] == cycle_id]


def provisional_loss(cycle_id):
    masters = [m for m in db.master_readings.values() if m["cycle_id"] == cycle_id]
    sold = sum(r["usage_gallons"] for r in cycle_readings(cycle_id))
    if masters:
        masters.sort(key=lambda m: m["_seq"])
        master = masters[-1]["master_gallons"]
    else:
        master = sold  # PROVISIONAL_MASTER_FALLBACK: loss provisionally zero
    return round3_half_up(master - sold, master) if master > 0 else 0.0


def final_loss(cycle_id, master_gallons):
    readings = cycle_readings(cycle_id)
    readings.sort(key=lambda r: (r["created_at"], r["reading_gallons"]))
    by_tap = {}
    for r in readings:
        cur = by_tap.get(r["tap_id"])
        if cur is None or r["reading_type"] == "FINAL_OFF":
            # FINAL_OFF replaces (not adds to) the tap's earlier reading
            by_tap[r["tap_id"]] = r
    sold = sum(r["usage_gallons"] for r in by_tap.values())
    return (round3_half_up(master_gallons - sold, master_gallons) if master_gallons > 0 else 0.0), sold


# ---------------------------------------------- delinquency cascade (§3.6)

def escalate_invoice(inv, now):
    """Advance collection_status at most one rung, thresholds evaluated in the
    pinned order (45-day, then 10-day, then past-due)."""
    if inv["billing_status"] in ("PAID", "VOID"):
        return
    if inv["collection_status"] == "DISCONNECTED":
        return
    cycle = db.billing_cycles.get(inv["cycle_id"])
    if cycle is None:
        return
    dpd = invoice_dpd(inv)
    if inv["collection_status"] == "NOTICED" and dpd >= DISCONNECT_DAY_THRESHOLD:
        inv["collection_status"] = "DISCONNECT_ELIGIBLE"
        touch(inv)
    elif inv["collection_status"] == "DELINQUENT" and dpd >= NOTICE_DAY_THRESHOLD:
        inv["collection_status"] = "NOTICED"
        inv["_notice_issued"] = True
        touch(inv)
    elif inv["collection_status"] == "CURRENT" and now > cycle["_due_dt"]:
        inv["collection_status"] = "DELINQUENT"
        touch(inv)


def delinquency_cascade(district_id, exclude_cycle_id):
    now = db.now_dt()
    for inv in db.invoices.values():
        if inv["district_id"] != district_id:
            continue
        if inv["cycle_id"] == exclude_cycle_id:
            continue
        if inv["billing_status"] in ("PAID", "VOID"):
            continue
        escalate_invoice(inv, now)


# ------------------------------------------------- annexation fee (§3.10)

def annexation_fee_split(deposit_cents):
    pct = (Decimal(deposit_cents) * FEASIBILITY_FEE_PCT).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    fee = max(FEASIBILITY_FEE_FLOOR_CENTS, int(pct))
    return fee, deposit_cents - fee

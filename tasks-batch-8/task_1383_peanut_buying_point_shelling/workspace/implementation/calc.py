"""Calculation rules (scaffold §1.3). All money math uses Decimal with
ROUND_HALF_UP; tonnages are Decimal at 3 decimal places (PRD 2.6)."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store

# Pinned constants (scaffold §1.3)
MOISTURE_DRYING_REQUIRED_PCT = Decimal("10.49")
MOISTURE_REJECT_PCT = Decimal("15.00")
MOISTURE_STEP_RATE = Decimal("0.05")
AFLATOXIN_PASS_MAX_PPB = Decimal("15.00")
AFLATOXIN_SEGREGATE_MAX_PPB = Decimal("50.00")
LOAN_DAILY_INTEREST_BP = 2
MARGIN_FACTOR_NUM = 110   # 1.10 compared exactly via integer cross-multiply
MARGIN_FACTOR_DEN = 100
RESTRICTED_FREE_TONS = 500
RESTRICTED_MAX_LOAD_TONS = Decimal("50")
STRIKE_LIMIT = 2
CONTRACT_DEFAULT_LIMIT = 2
RETEST_MAX = 2
TURNAROUND_BUFFER = timedelta(minutes=120)
SHRINK_ALLOWANCE_PCT = Decimal("0.01")

_D3 = Decimal("0.001")
_D0 = Decimal("1")


def r3(x):
    """Round half up to 3 decimal places (tonnage)."""
    return Decimal(x).quantize(_D3, rounding=ROUND_HALF_UP)


def r0(x):
    """Round half up to whole cents, returned as int."""
    return int(Decimal(x).quantize(_D0, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Buying point posture (calculations.buying_point_posture)
# ---------------------------------------------------------------------------

def bp_for_crop_year(crop_year):
    """The buying point context for a crop year (first-created match)."""
    for bp in sorted_by_seq(store.buying_points.values()):
        if bp["crop_year"] == crop_year:
            return bp
    return None


def sorted_by_seq(items):
    return sorted(items, key=lambda e: e["_seq"])


def wh_stored_tons(warehouse_id):
    """Sum of tons_remaining over receipts with status IN {OPEN, PLEDGED}."""
    total = Decimal(0)
    for r in store.storage_receipts.values():
        if r["warehouse_id"] == warehouse_id and r["status"] in ("OPEN", "PLEDGED"):
            total += r["tons_remaining"]
    return total


def wh_reserved_tons(warehouse_id):
    """Sum of (allocated_tons - shipped_tons) over AllocationLines on OPEN
    receipts of this warehouse whose delivery call is ALLOCATED."""
    total = Decimal(0)
    for line in store.allocation_lines.values():
        call = store.delivery_calls.get(line["delivery_call_id"])
        if call is None or call["status"] != "ALLOCATED":
            continue
        r = store.storage_receipts.get(line["storage_receipt_id"])
        if r is None or r["warehouse_id"] != warehouse_id or r["status"] != "OPEN":
            continue
        total += line["allocated_tons"] - line["shipped_tons"]
    return total


def wh_free_tons(warehouse_id):
    wh = store.warehouses[warehouse_id]
    return Decimal(wh["capacity_tons"]) - wh_stored_tons(warehouse_id) - wh_reserved_tons(warehouse_id)


def aggregate_free_tons(bp_id):
    total = Decimal(0)
    for wh in store.warehouses.values():
        if wh["buying_point_id"] == bp_id:
            total += Decimal(wh["capacity_tons"]) - wh_stored_tons(wh["id"]) - wh_reserved_tons(wh["id"])
    return total


def intake_posture(bp_id):
    """Boundaries pinned: free_total == 0 => SUSPENDED; == 500 => RESTRICTED;
    == 501 => OPEN. No warehouses => free_total 0 => SUSPENDED."""
    free_total = aggregate_free_tons(bp_id)
    if free_total <= 0:
        return "SUSPENDED"
    if free_total <= RESTRICTED_FREE_TONS:
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# Grading (calculations.payable_tons, discount_cents_per_ton)
# ---------------------------------------------------------------------------

def compute_payable_tons(gross_tons, fm_pct, lsk_pct):
    """Each deduction component is rounded to 3 decimals FIRST, then
    subtracted; the result is rounded half up to 3 decimals."""
    fm_tons = r3(gross_tons * fm_pct / Decimal(100))
    lsk_tons = r3(gross_tons * lsk_pct / Decimal(100))
    return r3(gross_tons - fm_tons - lsk_tons)


def select_tier_cpt(tiers, pct):
    """First tier whose ceiling is at least pct wins; boundary INCLUSIVE;
    a null up_to_pct matches anything (unbounded final tier)."""
    for tier in tiers:
        up_to = tier.get("up_to_pct")
        if up_to is None:
            return tier["discount_cents_per_ton"]
        if pct <= Decimal(str(up_to)):
            return tier["discount_cents_per_ton"]
    return 0


def discount_cpts(sheet, schedule):
    """(moisture_cpt, fm_cpt, damage_cpt) in integer cents per ton."""
    moisture_cpt = select_tier_cpt(schedule["moisture_tiers"], sheet["moisture_pct"])
    fm_cpt = select_tier_cpt(schedule["foreign_material_tiers"], sheet["foreign_material_pct"])
    damage_cpt = r0(sheet["damage_pct"] * schedule["damage_rate_cents_per_pct"])
    return moisture_cpt, fm_cpt, damage_cpt


def active_schedule_covering(instant):
    """The ACTIVE schedule whose half-open [from, to) window covers instant."""
    for s in sorted_by_seq(store.discount_schedules.values()):
        if s["status"] != "ACTIVE":
            continue
        if s["effective_from"] <= instant < s["effective_to"]:
            return s
    return None


def sheet_of_record(load_id):
    """The FINALIZED grade sheet of a load (at most one at any time)."""
    for s in sorted_by_seq(store.grade_sheets.values()):
        if s["load_id"] == load_id and s["status"] == "FINALIZED":
            return s
    return None


def quota_history_for(grower_id, crop_year):
    for q in sorted_by_seq(store.quota_histories.values()):
        if q["grower_id"] == grower_id and q["crop_year"] == crop_year:
            return q
    return None


# ---------------------------------------------------------------------------
# Load net value (calculations.load_net_value) — pinned evaluation order:
# (1) quota split, (2) per-part gross, (3) per-line discounts rounded then
# summed, (4) net = gross - discounts.
# ---------------------------------------------------------------------------

def load_value(load, sheet, schedule, bp, quota_remaining_tons):
    payable = sheet["payable_tons"]
    quota_applied = min(payable, max(Decimal(0), quota_remaining_tons))
    additional_applied = payable - quota_applied
    gross = (r0(quota_applied * bp["quota_price_cents_per_ton"])
             + r0(additional_applied * bp["additional_price_cents_per_ton"]))
    moisture_cpt, fm_cpt, damage_cpt = discount_cpts(sheet, schedule)
    discount = (r0(payable * moisture_cpt)
                + r0(payable * fm_cpt)
                + r0(payable * damage_cpt))
    return {
        "quota_tons_applied": quota_applied,
        "additional_tons_applied": additional_applied,
        "gross_value_cents": gross,
        "discount_cents": discount,
        "net_cents": gross - discount,
    }


def moisture_multiplier(moisture_pct):
    """1 + 0.05 * floor(max(0, m - 10.49)) — per FULL pct point over threshold."""
    over = max(Decimal(0), moisture_pct - MOISTURE_DRYING_REQUIRED_PCT)
    return Decimal(1) + MOISTURE_STEP_RATE * math.floor(over)


def min_cycle_capacity(bp_id):
    """Minimum cycle_capacity_tons over the buying point's dryers; None if none."""
    caps = [d["cycle_capacity_tons"] for d in store.dryers.values()
            if d["buying_point_id"] == bp_id]
    return min(caps) if caps else None


def provisional_net_estimate(load, sheet, schedule, bp):
    """provisional variant of load_net_value: quota headroom = quota - used
    with NO intra-settlement consumption; minus estimated drying when REQUIRED;
    hull credit and loan offset are zero."""
    qh = quota_history_for(load["grower_id"], load["crop_year"])
    quota_tons = qh["quota_tons"] if qh else Decimal(0)
    used = qh["used_quota_tons"] if qh else Decimal(0)
    value = load_value(load, sheet, schedule, bp, quota_tons - used)
    net = value["net_cents"]
    if load["drying_status"] == "REQUIRED":
        cap = min_cycle_capacity(bp["id"])
        if cap is not None:
            cycles = math.ceil(load["gross_tons"] / Decimal(cap))
            mult = moisture_multiplier(sheet["moisture_pct"])
            net -= r0(Decimal(cycles * bp["drying_rate_per_cycle_cents"]) * mult)
    return net


def drying_charge_cents(booking, bp):
    """Settlement-time charge for one COMPLETED booking."""
    dryer = store.dryers[booking["dryer_id"]]
    cycles = math.ceil(booking["tons"] / Decimal(dryer["cycle_capacity_tons"]))
    mult = moisture_multiplier(booking["moisture_at_booking"])
    return r0(Decimal(cycles * bp["drying_rate_per_cycle_cents"]) * mult)


# ---------------------------------------------------------------------------
# Loans (calculations.loan_principal, loan_offset_with_interest,
# collateral_coverage)
# ---------------------------------------------------------------------------

def loan_days(as_of, pledged_at):
    """Whole-day floor; negative treated as zero."""
    delta = (as_of - pledged_at).total_seconds()
    return max(0, math.floor(delta / 86400))


def accrued_interest_cents(pledge, as_of):
    """Accrued interest balance at as_of: the stored balance plus accrual on
    the current outstanding principal for whole days elapsed since the last
    accrual event. With no intervening repayment this equals exactly
    round_half_up(outstanding * 2bp/10000 * days_since_pledge); the waterfall
    at each repay fixes the balance so retired interest is never re-charged."""
    days_now = loan_days(as_of, pledge["pledged_at"])
    extra_days = max(0, days_now - pledge["accrued_through_days"])
    extra = r0(Decimal(pledge["outstanding_principal_cents"])
               * Decimal(LOAN_DAILY_INTEREST_BP) / Decimal(10000) * extra_days)
    return pledge["accrued_balance_cents"] + extra


def fix_accrual(pledge, as_of):
    """Fold interest accrued up to as_of into the stored balance (waterfall
    anchor: 'accrued recomputed to payment date')."""
    pledge["accrued_balance_cents"] = accrued_interest_cents(pledge, as_of)
    pledge["accrued_through_days"] = loan_days(as_of, pledge["pledged_at"])


def compute_loan_principal(pledged_tons, bp, grower_id, crop_year):
    """Tier-split principal. The quota view RESERVES but does not consume:
    headroom = quota - used - quota parts of OTHER ACTIVE pledges of this
    grower for this crop year. Missing quota history => quota 0."""
    qh = quota_history_for(grower_id, crop_year)
    quota_tons = qh["quota_tons"] if qh else Decimal(0)
    used = qh["used_quota_tons"] if qh else Decimal(0)
    reserved = Decimal(0)
    for p in store.loan_pledges.values():
        if p["status"] != "ACTIVE" or p["grower_id"] != grower_id:
            continue
        r = store.storage_receipts.get(p["storage_receipt_id"])
        l = store.loads.get(r["load_id"]) if r else None
        if l is not None and l["crop_year"] == crop_year:
            reserved += p["quota_part_tons"]
    headroom = quota_tons - used - reserved
    quota_part = min(pledged_tons, max(Decimal(0), headroom))
    additional_part = pledged_tons - quota_part
    principal = (r0(quota_part * bp["loan_rate_quota_cents_per_ton"])
                 + r0(additional_part * bp["loan_rate_additional_cents_per_ton"]))
    return quota_part, additional_part, principal


def collateral_values(pledge, bp):
    standard = (r0(pledge["quota_part_tons"] * bp["quota_price_cents_per_ton"])
                + r0(pledge["additional_part_tons"] * bp["additional_price_cents_per_ton"]))
    conservative = r0(pledge["pledged_tons"] * bp["additional_price_cents_per_ton"])
    return standard, conservative


def margin_status(pledge, bp, as_of):
    """MARGIN_OK iff conservative value >= outstanding * 1.10, compared
    exactly (integer cross-multiplication, no rounding of the threshold)."""
    _, conservative = collateral_values(pledge, bp)
    outstanding = pledge["outstanding_principal_cents"] + accrued_interest_cents(pledge, as_of)
    if conservative * MARGIN_FACTOR_DEN >= outstanding * MARGIN_FACTOR_NUM:
        return "MARGIN_OK"
    return "MARGIN_CALL"


def pledge_bp(pledge):
    """Buying point anchoring a pledge: via receipt -> warehouse."""
    r = store.storage_receipts.get(pledge["storage_receipt_id"])
    wh = store.warehouses.get(r["warehouse_id"]) if r else None
    return store.buying_points.get(wh["buying_point_id"]) if wh else None


# ---------------------------------------------------------------------------
# Aflatoxin determination (calculations.aflatoxin_determination)
# ---------------------------------------------------------------------------

def aflatoxin_determination(result_ppb):
    """<= 15.00 PASS (inclusive); (15, 50] SEGREGATE; > 50 REJECT."""
    if result_ppb <= AFLATOXIN_PASS_MAX_PPB:
        return "PASS"
    if result_ppb <= AFLATOXIN_SEGREGATE_MAX_PPB:
        return "SEGREGATE"
    return "REJECT"


# ---------------------------------------------------------------------------
# Contracts / delivery calls
# ---------------------------------------------------------------------------

def contract_fulfilled_tons(contract_id):
    """Sum of delivered_tons over DELIVERED/RECONCILED delivery calls."""
    total = Decimal(0)
    for c in store.delivery_calls.values():
        if c["contract_id"] == contract_id and c["status"] in ("DELIVERED", "RECONCILED"):
            total += call_delivered_tons(c["id"])
    return total


def contract_remaining_tons(contract_id):
    """total - fulfilled - sum(requested of ISSUED/ALLOCATED calls)."""
    contract = store.sheller_contracts[contract_id]
    open_requested = Decimal(0)
    for c in store.delivery_calls.values():
        if c["contract_id"] == contract_id and c["status"] in ("ISSUED", "ALLOCATED"):
            open_requested += c["requested_tons"]
    return contract["total_units_tons"] - contract_fulfilled_tons(contract_id) - open_requested


def call_allocated_tons(call_id):
    total = Decimal(0)
    for line in store.allocation_lines.values():
        if line["delivery_call_id"] == call_id:
            total += line["allocated_tons"]
    return total


def call_delivered_tons(call_id):
    total = Decimal(0)
    for line in store.allocation_lines.values():
        if line["delivery_call_id"] == call_id:
            total += line["shipped_tons"]
    return total


def lines_of_call(call_id):
    return sorted_by_seq([l for l in store.allocation_lines.values()
                          if l["delivery_call_id"] == call_id])


def eligible_receipts(bp_id, accepts_segregated):
    """OPEN receipts with positive tons_remaining in warehouses of the buying
    point, excluding segregated receipts unless the contract accepts them.
    FIFO: stored_at ASC, tie-break created_at ASC, never id."""
    out = []
    for r in store.storage_receipts.values():
        if r["status"] != "OPEN" or r["tons_remaining"] <= 0:
            continue
        wh = store.warehouses.get(r["warehouse_id"])
        if wh is None or wh["buying_point_id"] != bp_id:
            continue
        if r["segregated"] and not accepts_segregated:
            continue
        out.append(r)
    out.sort(key=lambda r: (r["stored_at"], r["created_at"], r["_seq"]))
    return out


# ---------------------------------------------------------------------------
# Hull credit allocation (calculations.hull_credit_allocation)
# ---------------------------------------------------------------------------

def hull_credit_cents(bp, grower_id, as_of):
    """Grower's share of the sold-hull revenue pool. Pool = revenue of SOLD
    hull lots of this buying point with sold_at <= as_of. Shares floored;
    remainder dealt one cent at a time by earliest contributing line
    created_at ASC, tie-break Grower.created_at ASC."""
    pool = 0
    for lot in store.hull_lots.values():
        if lot["status"] != "SOLD" or lot["sold_at"] is None or lot["sold_at"] > as_of:
            continue
        call = store.delivery_calls.get(lot["delivery_call_id"])
        contract = store.sheller_contracts.get(call["contract_id"]) if call else None
        if contract is not None and contract["buying_point_id"] == bp["id"]:
            pool += lot["revenue_cents"]
    shelled = {}
    earliest_line = {}
    for call in store.delivery_calls.values():
        if call["status"] != "RECONCILED":
            continue
        contract = store.sheller_contracts.get(call["contract_id"])
        if contract is None or contract["buying_point_id"] != bp["id"]:
            continue
        for line in lines_of_call(call["id"]):
            if line["shelled_tons"] <= 0:
                continue
            receipt = store.storage_receipts.get(line["storage_receipt_id"])
            load = store.loads.get(receipt["load_id"]) if receipt else None
            if load is None:
                continue
            g = load["grower_id"]
            shelled[g] = shelled.get(g, Decimal(0)) + line["shelled_tons"]
            if g not in earliest_line or (line["created_at"], line["_seq"]) < (
                    earliest_line[g]["created_at"], earliest_line[g]["_seq"]):
                earliest_line[g] = line
    total_shelled = sum(shelled.values(), Decimal(0))
    if pool == 0 or total_shelled == 0 or grower_id not in shelled:
        return 0
    shares = {}
    for g, s in shelled.items():
        shares[g] = int((Decimal(pool) * s / total_shelled).to_integral_value(
            rounding="ROUND_FLOOR"))
    remainder = pool - sum(shares.values())
    # deterministic cent-by-cent remainder, never ordered by id
    def order_key(g):
        line = earliest_line[g]
        grower = store.growers.get(g)
        g_created = grower["created_at"] if grower else line["created_at"]
        g_seq = grower["_seq"] if grower else line["_seq"]
        return (line["created_at"], g_created, line["_seq"], g_seq)
    for g in sorted(shelled.keys(), key=order_key):
        if remainder <= 0:
            break
        shares[g] += 1
        remainder -= 1
    return shares.get(grower_id, 0)

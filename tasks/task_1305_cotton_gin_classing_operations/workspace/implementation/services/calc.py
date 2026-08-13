"""Calculation rules (SCAFFOLD §1.3, PRD §3). All money integer cents;
all rounding half-up via Decimal."""

from decimal import Decimal, ROUND_HALF_UP

from db import db


def round_half_up(value):
    """Round a Decimal/numeric to the nearest integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# estimated_turnout
# ---------------------------------------------------------------------------

def compute_estimates(net_weight_lbs, moisture_pct, foreign_matter_pct):
    if moisture_pct <= 8.0:
        moisture_adj = Decimal("0")
    else:
        moisture_adj = min(Decimal("0.020"), Decimal("0.004") * (Decimal(str(moisture_pct)) - Decimal("8.0")))
    if foreign_matter_pct <= 4.0:
        fm_adj = Decimal("0")
    else:
        fm_adj = min(Decimal("0.025"), Decimal("0.005") * (Decimal(str(foreign_matter_pct)) - Decimal("4.0")))
    est_lint_pct = max(Decimal("0.30"), Decimal("0.38") - moisture_adj - fm_adj)
    est_lint_lbs = round_half_up(Decimal(net_weight_lbs) * est_lint_pct)
    est_seed_lbs = round_half_up(Decimal(net_weight_lbs) * Decimal("0.55"))
    return est_lint_lbs, est_seed_lbs


# ---------------------------------------------------------------------------
# ginning_charge (tiered, marginal split, per-module round half-up)
# ---------------------------------------------------------------------------

def compute_ginning_charge_cents(grower_id, season, current_module):
    """Tiered ginning charge for the module just ginned.

    cumulative_before = SUM(actual_lint_lbs of grower's GINNED modules in season
    with ginned_at strictly earlier; ties by module created_at ASC).
    """
    others = [
        m for m in db.modules.values()
        if m["grower_id"] == grower_id
        and m["season"] == season
        and m["status"] == "GINNED"
        and m["id"] != current_module["id"]
        and m.get("ginned_at") is not None
    ]
    cur_key = (current_module["ginned_at"], current_module["created_at"])
    cumulative_before = 0
    for m in others:
        key = (m["ginned_at"], m["created_at"])
        if key < cur_key:
            cumulative_before += m.get("actual_lint_lbs", 0)

    L = current_module["actual_lint_lbs"]
    tier1_lbs = min(L, max(0, 100000 - cumulative_before))
    tier2_lbs = L - tier1_lbs
    charge = Decimal(tier1_lbs) * Decimal("11.5") + Decimal(tier2_lbs) * Decimal("9.5")
    return round_half_up(charge)


# ---------------------------------------------------------------------------
# quality_price_adjustment
# ---------------------------------------------------------------------------

def find_covering_schedule(grade_code, date_dt):
    """Return the GradeSchedule covering date_dt for grade_code, or None."""
    for s in db.grade_schedules.values():
        if s["grade_code"] != grade_code:
            continue
        frm = s["_effective_from_dt"]
        to = s["_effective_to_dt"]
        if frm <= date_dt < to:
            return s
    return None


def compute_quality_points(schedule_points, micronaire, strength_gpt):
    mic = float(micronaire)
    if 3.7 <= mic <= 4.2:
        mic_points = 25
    elif 3.5 <= mic <= 4.9:
        mic_points = 0
    else:
        mic_points = -50
    st = float(strength_gpt)
    if st >= 29.0:
        strength_points = 15
    elif st <= 26.0:
        strength_points = -30
    else:
        strength_points = 0
    return schedule_points + mic_points + strength_points


def compute_adjustment_cents(net_weight_lbs, quality_points):
    # signed; round half-up on the absolute value with sign preserved
    raw = Decimal(net_weight_lbs) * Decimal(quality_points) / Decimal(100)
    if raw >= 0:
        return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return -int((-raw).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# storage_charge
# ---------------------------------------------------------------------------

def compute_storage_charge_cents(receipt, end_date_dt):
    from db import parse_dt
    start = parse_dt(receipt["storage_start_date"])
    days = (end_date_dt.date() - start.date()).days
    chargeable = max(0, days - 15)
    return chargeable * 12


# ---------------------------------------------------------------------------
# shift_mass_balance_allocation (largest remainder)
# ---------------------------------------------------------------------------

def allocate_seed_largest_remainder(shift):
    """Set reconciled_seed_lbs on every GINNED module of the shift.

    Returns the list of affected modules (already mutated, version bumped).
    """
    from services.core import touch
    modules = [
        m for m in db.modules.values()
        if m.get("gin_shift_id") == shift["id"] and m["status"] == "GINNED"
    ]
    T = shift["actual_seed_scale_lbs"]
    total_est = sum(m["est_seed_lbs"] for m in modules)
    if not modules:
        return []
    shares = []
    for m in modules:
        if total_est == 0:
            raw = Decimal(0)
        else:
            raw = Decimal(T) * Decimal(m["est_seed_lbs"]) / Decimal(total_est)
        floor_share = int(raw)  # floor for non-negative values
        frac = raw - Decimal(floor_share)
        shares.append({"module": m, "floor": floor_share, "frac": frac})
    remainder = T - sum(s["floor"] for s in shares)
    # Order by frac DESC, tie-break created_at ASC
    shares.sort(key=lambda s: (-s["frac"], s["module"]["created_at"], s["module"]["id"]))
    for i in range(remainder):
        shares[i]["floor"] += 1
    for s in shares:
        m = s["module"]
        m["reconciled_seed_lbs"] = s["floor"]
        touch(m)
    return [s["module"] for s in shares]


# ---------------------------------------------------------------------------
# seed_proceeds_credit
# ---------------------------------------------------------------------------

def allocate_seed_pool(shift, price_cents_per_lb):
    """Compute SeedSale figures and per-grower credit map.

    Returns (sold_lbs, net_pool_cents, {grower_id: credit_cents}).
    """
    modules = [
        m for m in db.modules.values()
        if m.get("gin_shift_id") == shift["id"] and m["status"] == "GINNED"
    ]
    sold_lbs = sum(m.get("reconciled_seed_lbs") or 0 for m in modules)
    net_pool_cents = sold_lbs * price_cents_per_lb - 2500
    credits = {}
    if not modules or sold_lbs == 0:
        return sold_lbs, net_pool_cents, credits
    shares = []
    for m in modules:
        rec = m.get("reconciled_seed_lbs") or 0
        raw = Decimal(net_pool_cents) * Decimal(rec) / Decimal(sold_lbs)
        if raw >= 0:
            floor_share = int(raw)
            frac = raw - Decimal(floor_share)
        else:
            # floor for negatives
            floor_share = int(raw) if raw == int(raw) else int(raw) - 1
            frac = raw - Decimal(floor_share)
        shares.append({"module": m, "floor": floor_share, "frac": frac})
    remainder = net_pool_cents - sum(s["floor"] for s in shares)
    shares.sort(key=lambda s: (-s["frac"], s["module"]["created_at"], s["module"]["id"]))
    for i in range(remainder):
        shares[i]["floor"] += 1
    for s in shares:
        gid = s["module"]["grower_id"]
        credits[gid] = credits.get(gid, 0) + s["floor"]
    return sold_lbs, net_pool_cents, credits


# ---------------------------------------------------------------------------
# settlement_net
# ---------------------------------------------------------------------------

def compute_settlement_lines(grower, season, variant):
    """Compute all money lines for a (grower, season) settlement."""
    grower_id = grower["id"]
    # Season modules: any status except REJECTED contribute their bales
    modules = [
        m for m in db.modules.values()
        if m["grower_id"] == grower_id and m["season"] == season
    ]
    module_ids = {m["id"] for m in modules}
    bales = [b for b in db.bales.values() if b["module_id"] in module_ids]

    lint_value = sum(b["net_weight_lbs"] * 60 for b in bales)
    quality_adj = sum(b.get("adjustment_cents") or 0 for b in bales)

    # seed credit
    entries = [
        e for e in db.ledger_entries.values()
        if e["grower_id"] == grower_id and e["season"] == season
    ]
    seed_entries_sum = sum(e["amount_cents"] for e in entries if e["entry_type"] == "SEED_CREDIT")
    if variant == "PROVISIONAL":
        unsold_est = 0
        for m in modules:
            if m["status"] != "GINNED":
                continue
            shift_id = m.get("gin_shift_id")
            has_sale = any(s["gin_shift_id"] == shift_id for s in db.seed_sales.values())
            if not has_sale:
                unsold_est += m["est_seed_lbs"]
        seed_credit = seed_entries_sum + unsold_est * 25
    else:
        seed_credit = seed_entries_sum

    ginning_charge = sum(e["amount_cents"] for e in entries if e["entry_type"] == "GINNING_CHARGE")
    storage_charge = sum(e["amount_cents"] for e in entries if e["entry_type"] == "STORAGE_CHARGE")
    loan_net = sum(
        e["amount_cents"] for e in entries
        if e["entry_type"] in ("LOAN_ADVANCE", "LOAN_REPAYMENT")
    )
    adjustment_net = sum(e["amount_cents"] for e in entries if e["entry_type"] == "ADJUSTMENT")
    patronage = round_half_up(
        Decimal(str(grower.get("patronage_rate", 0.20))) * Decimal(abs(ginning_charge))
    )
    net_payable = (
        lint_value + quality_adj + seed_credit + ginning_charge
        + storage_charge + loan_net + adjustment_net + patronage
    )
    return {
        "lint_value_cents": lint_value,
        "quality_adjustment_cents": quality_adj,
        "seed_credit_cents": seed_credit,
        "ginning_charge_cents": ginning_charge,
        "storage_charge_cents": storage_charge,
        "loan_net_cents": loan_net,
        "adjustment_net_cents": adjustment_net,
        "patronage_cents": patronage,
        "net_payable_cents": net_payable,
    }


def recompute_draft_settlements(grower_id, season):
    """Recompute every DRAFT settlement for (grower, season) per settlement_net."""
    from services.core import touch
    for s in db.settlements.values():
        if s["grower_id"] == grower_id and s["season"] == season and s["status"] == "DRAFT":
            grower = db.growers[grower_id]
            lines = compute_settlement_lines(grower, season, s["computation_variant"])
            s.update(lines)
            touch(s)

"""Business logic: calculations, cascades, recomputation helpers."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import store, iso_format


def round2(value):
    """Round half-up to 2 decimal places, returned as float for JSON serialization."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def touch(rec):
    """Refresh updated_at and increment version on a common-fields record."""
    rec["updated_at"] = store.now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Recomputations
# ---------------------------------------------------------------------------

def recompute_plant_scores(plant_id):
    """plant_compliance_score calculation: provisional flat-count + official severity-weighted."""
    plant = store.plants[plant_id]
    open_count = 0
    official_weight = 0
    for dv in store.deviations.values():
        day = store.production_days.get(dv["production_day_id"])
        if not day or day["plant_id"] != plant_id:
            continue
        if dv["status"] in ("OPEN", "ACTION_LOGGED"):
            open_count += 1
        if dv["status"] == "VERIFIED":
            official_weight += 5 if dv["severity"] == "MAJOR" else 2
    new_prov = max(0, 100 - 2 * open_count)
    new_off = max(0, 100 - official_weight)
    if plant["provisional_compliance_score"] != new_prov or plant["official_compliance_score"] != new_off:
        plant["provisional_compliance_score"] = new_prov
        plant["official_compliance_score"] = new_off
        touch(plant)


def recompute_cooler(plant_id):
    """cooler_occupancy: sum of total_weight_lbs over PRODUCED/QUARANTINED/SPOILED finished lots."""
    plant = store.plants[plant_id]
    total = Decimal("0")
    for fl in store.finished_lots.values():
        day = store.production_days.get(fl["production_day_id"])
        if not day or day["plant_id"] != plant_id:
            continue
        if fl["status"] in ("PRODUCED", "QUARANTINED", "SPOILED"):
            total += Decimal(str(fl["total_weight_lbs"]))
    new_val = round2(total)
    if plant["cooler_occupied_lbs"] != new_val:
        plant["cooler_occupied_lbs"] = new_val
        touch(plant)


def recompute_day_posture(day_id):
    """posture: RESTRICTED while any lot HELD, any finished lot QUARANTINED, or any deviation OPEN/ACTION_LOGGED."""
    day = store.production_days[day_id]
    restricted = False
    for lot in store.carcass_lots.values():
        if lot["production_day_id"] == day_id and lot["status"] == "HELD":
            restricted = True
            break
    if not restricted:
        for fl in store.finished_lots.values():
            if fl["production_day_id"] == day_id and fl["status"] == "QUARANTINED":
                restricted = True
                break
    if not restricted:
        for dv in store.deviations.values():
            if dv["production_day_id"] == day_id and dv["status"] in ("OPEN", "ACTION_LOGGED"):
                restricted = True
                break
    new_posture = "RESTRICTED" if restricted else "CLEAR"
    if day["posture"] != new_posture:
        day["posture"] = new_posture
        touch(day)


def recompute_day_totals(day_id):
    """Ledger sync on complete-fabrication: sums over FABRICATED lots of the day.

    PRD §3.3/§3.5: the frozen totals are plain sums (no rounding is pinned on
    them); only `day_yield_pct` is rounded, exactly once at the end.
    """
    day = store.production_days[day_id]
    total_cut = Decimal("0")
    total_cold = Decimal("0")
    for lot in store.carcass_lots.values():
        if lot["production_day_id"] == day_id and lot["status"] == "FABRICATED":
            total_cut += Decimal(str(lot["total_cut_weight_lbs"]))
            total_cold += Decimal(str(lot["cold_carcass_weight_lbs"]))
    day["total_cut_weight_lbs"] = float(total_cut)
    day["total_cold_weight_lbs"] = float(total_cold)
    touch(day)


def recompute_operating_status(plant_id):
    """Plant ACTIVE unless any OPEN CRITICAL NoncomplianceRecord exists."""
    plant = store.plants[plant_id]
    has_open_critical = any(
        nr["plant_id"] == plant_id and nr["status"] == "OPEN" and nr["severity"] == "CRITICAL"
        for nr in store.noncompliance_records.values()
    )
    new_status = "SUSPENDED" if has_open_critical else "ACTIVE"
    if plant["operating_status"] != new_status:
        plant["operating_status"] = new_status
        touch(plant)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def suspend_open_days(plant_id):
    """Cascade: every OPEN ProductionDay of the plant -> SUSPENDED."""
    for day in store.production_days.values():
        if day["plant_id"] == plant_id and day["status"] == "OPEN":
            day["status"] = "SUSPENDED"
            touch(day)


def cascade_critical_nr(plant_id):
    """Noncompliance cascade link 1+2: plant SUSPENDED, OPEN days SUSPENDED."""
    recompute_operating_status(plant_id)
    if store.plants[plant_id]["operating_status"] == "SUSPENDED":
        suspend_open_days(plant_id)


def cascade_positive_sample(lot):
    """Pathogen cascade links 1-3: lot HELD/CONDEMNED, finished lots QUARANTINED, day RESTRICTED."""
    day_id = lot["production_day_id"]
    # Link 2: finished lots sourced from this lot, still PRODUCED -> QUARANTINED
    for fl in store.finished_lots.values():
        if fl["source_lot_id"] == lot["id"] and fl["status"] == "PRODUCED":
            fl["status"] = "QUARANTINED"
            touch(fl)
    # Cooler ledger sync (QUARANTINED still occupies cooler, but recompute for safety)
    day = store.production_days[day_id]
    recompute_cooler(day["plant_id"])
    # Link 3: posture recompute
    recompute_day_posture(day_id)


def create_noncompliance_record(plant_id, production_day_id, category, severity, created_by, description):
    """Create an NR with server-defaulted regulation cite per category."""
    from db import new_id
    cites = {
        "HUMANE_HANDLING": "9 CFR 313",
        "TRACEABILITY": "9 CFR 418",
        "PATHOGEN_CONTROL": "9 CFR 310.25",
        "SANITATION": "9 CFR 416",
    }
    now = store.now_iso()
    nr = {
        "id": new_id(),
        "plant_id": plant_id,
        "production_day_id": production_day_id,
        "category": category,
        "regulation_cite": cites[category],
        "description": description,
        "severity": severity,
        "created_by": created_by,
        "status": "OPEN",
        "appeal_note": None,
        "resolved_by": None,
        "resolution_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.noncompliance_records[nr["id"]] = nr
    # Noncompliance cascade link 1+2
    if severity == "CRITICAL":
        cascade_critical_nr(plant_id)
    return nr


# ---------------------------------------------------------------------------
# Shelf-life dating calculation
# ---------------------------------------------------------------------------

COLD_CHAIN_LIMIT_F = 40.0
TIER1_MAX_F = 45.0
TIER2_MAX_F = 50.0
TIER1_MULT = Decimal("1.0")
TIER2_MULT = Decimal("1.5")
TIER3_MULT = Decimal("2.0")


def recompute_shelf_life(fl):
    """shelf_life_dating: walk temperature_logs in recorded_at order (insertion order tie-break),
    accrue tiered penalty hours for entries strictly above 40F, recompute use_by_at."""
    from db import parse_iso
    logs = fl["temperature_logs"]  # already in insertion order == recorded_at order
    penalty = Decimal("0")
    now = store.now()
    for i, entry in enumerate(logs):
        temp = entry["temp_f"]
        if temp > COLD_CHAIN_LIMIT_F:
            t0 = parse_iso(entry["recorded_at"])
            if i + 1 < len(logs):
                t1 = parse_iso(logs[i + 1]["recorded_at"])
            else:
                t1 = now
            interval_h = Decimal(str((t1 - t0).total_seconds())) / Decimal("3600")
            if interval_h < 0:
                interval_h = Decimal("0")
            if temp <= TIER1_MAX_F:
                m = TIER1_MULT
            elif temp <= TIER2_MAX_F:
                m = TIER2_MULT
            else:
                m = TIER3_MULT
            penalty += interval_h * m
    fl["penalty_hours"] = round2(penalty)

    prod_dt = parse_iso(fl["production_date"])
    base_dt = parse_iso(fl["base_use_by_at"])
    penalty_delta = timedelta(seconds=float(penalty * Decimal("3600")))
    use_by = base_dt - penalty_delta
    if use_by < prod_dt:
        use_by = prod_dt
    fl["use_by_at"] = iso_format(use_by)
    return use_by

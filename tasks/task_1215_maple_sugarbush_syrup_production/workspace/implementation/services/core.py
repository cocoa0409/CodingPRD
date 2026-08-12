"""Entity construction, serialization, rollup/cascade helpers, and calculations."""

from datetime import timedelta
from decimal import Decimal

import db
from util import new_id, now_iso, clock_dt, clock_date, parse_dt, parse_date, d, round2, num_out


# ------------------------------------------------------------------
# Constants (SCAFFOLD §1.3 / PRD §2.5, §2.9)
# ------------------------------------------------------------------

CONTAINER_GALLONS = {
    "DRUM_55": Decimal("55.0"),
    "RETAIL_QUART": Decimal("0.25"),
    "RETAIL_PINT": Decimal("0.125"),
}

RULE_86 = Decimal("86")
RULE_88_2 = Decimal("88.2")

DETERIORATION_PER_DAY = Decimal("0.2")
MAX_DETERIORATION = Decimal("1.0")
BRIX_FLOOR = Decimal("0.5")

VARIANCE_HOLD_PCT = Decimal("15.0")

FLAVOR_MIN = 70
T_GOLDEN = Decimal("75.0")
T_AMBER = Decimal("50.0")
T_DARK = Decimal("25.0")

LEAK_DROP = Decimal("2.0")
REPAIR_HYSTERESIS = Decimal("0.5")

FREEZE_F = Decimal("32.0")
THAW_F = Decimal("38.0")

LEGAL_BRIX_MIN = Decimal("66.0")

AUDIT_SPACING_DAYS = 14


# ------------------------------------------------------------------
# Entity factories (all system/computed defaults applied here)
# ------------------------------------------------------------------

def _common():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def new_season(year, opens_on, closes_on, planned_taps):
    e = _common()
    e.update({
        "year": year,
        "opens_on": opens_on,
        "closes_on": closes_on,
        "planned_taps": planned_taps,
        "status": "PLANNED",
        "taps_live": 0,
        "total_sap_gallons": Decimal("0"),
        "total_syrup_gallons": Decimal("0"),
    })
    return e


def new_sugarbush(season_id, name, tap_capacity):
    e = _common()
    e.update({
        "season_id": season_id,
        "name": name,
        "tap_capacity": tap_capacity,
        "stand_type": "OWNED",
        "active_lease_id": None,
        "organic_certified": False,
        "taps_set": 0,
        "taps_live": 0,
        "status": "PREP",
    })
    return e


def new_lease(sugarbush_id, landowner_name, royalty_basis, per_tap_cents, share_pct,
              certified_organic_required, term_start, term_end):
    e = _common()
    e.update({
        "sugarbush_id": sugarbush_id,
        "landowner_name": landowner_name,
        "royalty_basis": royalty_basis,
        "per_tap_cents": per_tap_cents,
        "share_pct": share_pct,
        "certified_organic_required": certified_organic_required,
        "term_start": term_start,
        "term_end": term_end,
        "status": "DRAFT",
        "taps_snapshot": None,
        "accrued_royalty_cents": 0,
        "accrued_royalty_gallons": Decimal("0"),
        "settled_royalty_gallons": None,
    })
    return e


def new_tap_line(sugarbush_id, line_code, tap_count, vacuum_target_inhg):
    e = _common()
    e.update({
        "sugarbush_id": sugarbush_id,
        "line_code": line_code,
        "tap_count": tap_count,
        "vacuum_target_inhg": d(vacuum_target_inhg),
        "latest_vacuum_inhg": None,
        "status": "INSTALLING",
    })
    return e


def new_vacuum_reading(tap_line_id, inhg):
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "tap_line_id": tap_line_id,
        "inhg": d(inhg),
        "recorded_at": ts,
    }


def new_weather_window(season_id, opens_at, closes_at, forecast_min_f, forecast_max_f):
    e = _common()
    e.update({
        "season_id": season_id,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "forecast_min_f": d(forecast_min_f),
        "forecast_max_f": d(forecast_max_f),
        "status": "FORECAST",
    })
    return e


def new_crew_member(season_id, name, crew_role, cert_organic_handler):
    e = _common()
    e.update({
        "season_id": season_id,
        "name": name,
        "crew_role": crew_role,
        "cert_organic_handler": cert_organic_handler,
        "status": "HIRED",
    })
    return e


def new_sap_run(sugarbush_id, weather_window_id, collected_by, gallons_collected, measured_brix):
    e = _common()
    g = d(gallons_collected)
    e.update({
        "sugarbush_id": sugarbush_id,
        "weather_window_id": weather_window_id,
        "collected_by": collected_by,
        "gallons_collected": g,
        "measured_brix": d(measured_brix),
        "collected_at": now_iso(),
        "gallons_remaining": g,
        "status": "DRAFT",
    })
    return e


def new_batch(season_id, boiled_by, evaporator_capacity_gal):
    e = _common()
    e.update({
        "season_id": season_id,
        "boiled_by": boiled_by,
        "evaporator_capacity_gal": evaporator_capacity_gal,
        "sap_gallons_in": Decimal("0"),
        "input_brix": None,
        "estimated_syrup_gallons": None,
        "expected_syrup_gallons": None,
        "boil_started_at": None,
        "finished_brix": None,
        "measured_syrup_gallons": None,
        "yield_variance_pct": None,
        "status": "FILLING",
    })
    return e


def new_batch_intake(batch_id, sap_run_id, gallons_drawn, draw_sequence):
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "batch_id": batch_id,
        "sap_run_id": sap_run_id,
        "gallons_drawn": d(gallons_drawn),
        "draw_sequence": draw_sequence,
        "effective_brix": None,
    }


def new_syrup_lot(batch_id, season_id, measured_gallons, finished_brix, held_auto):
    e = _common()
    g = d(measured_gallons)
    e.update({
        "batch_id": batch_id,
        "season_id": season_id,
        "measured_gallons": g,
        "finished_brix": d(finished_brix),
        "light_transmittance_pct": None,
        "grade": None,
        "unpackaged_gallons": g,
        "quality_hold_auto": bool(held_auto),
        "status": "HELD" if held_auto else "UNGRADED",
    })
    return e


def new_flavor_evaluation(syrup_lot_id, evaluator_id, flavor_score, defect_flags):
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "syrup_lot_id": syrup_lot_id,
        "evaluator_id": evaluator_id,
        "flavor_score": flavor_score,
        "defect_flags": list(defect_flags),
        "evaluated_at": ts,
    }


def new_packaging_run(syrup_lot_id, container_type, units_planned):
    e = _common()
    e.update({
        "syrup_lot_id": syrup_lot_id,
        "container_type": container_type,
        "units_planned": units_planned,
        "units_filled": None,
        "filled_gallons": None,
        "status": "PLANNED",
    })
    return e


def new_cert_audit(sugarbush_id, audit_type, scheduled_for):
    e = _common()
    e.update({
        "sugarbush_id": sugarbush_id,
        "audit_type": audit_type,
        "scheduled_for": scheduled_for,
        "result": None,
        "status": "SCHEDULED",
    })
    return e


# ------------------------------------------------------------------
# Touch / version bump
# ------------------------------------------------------------------

def touch(entity):
    entity["updated_at"] = now_iso()


def bump(entity):
    entity["version"] += 1
    touch(entity)


# ------------------------------------------------------------------
# Rollups (SCAFFOLD §1.3 taps_rollup, season_aggregates; PRD §2.8)
# ------------------------------------------------------------------

def lines_of_bush(bush_id):
    return [l for l in db.tap_lines.values() if l["sugarbush_id"] == bush_id]


def recompute_bush_taps(bush):
    lines = lines_of_bush(bush["id"])
    bush["taps_set"] = sum(l["tap_count"] for l in lines if l["status"] in ("ACTIVE", "LEAK"))
    bush["taps_live"] = sum(l["tap_count"] for l in lines if l["status"] == "ACTIVE")
    touch(bush)


def recompute_season_taps_live(season):
    total = 0
    for b in db.sugarbushes.values():
        if b["season_id"] == season["id"] and b["status"] != "SHUTDOWN":
            total += b["taps_live"]
    season["taps_live"] = total
    touch(season)


def recompute_season_sap(season):
    total = Decimal("0")
    for r in db.sap_runs.values():
        b = db.sugarbushes.get(r["sugarbush_id"])
        if b and b["season_id"] == season["id"] and r["status"] == "CONFIRMED":
            total += d(r["gallons_collected"])
    season["total_sap_gallons"] = round2(total)
    touch(season)


def recompute_season_syrup(season):
    total = Decimal("0")
    for bt in db.batches.values():
        if bt["season_id"] == season["id"] and bt["status"] == "FINISHED":
            total += d(bt["measured_syrup_gallons"])
    season["total_syrup_gallons"] = round2(total)
    touch(season)


def recompute_run_gallons_remaining(run):
    """gallons_remaining = collected - sum(drawn over intakes whose batch in FILLING/BOILING/FINISHED)."""
    drawn = Decimal("0")
    for it in db.batch_intakes.values():
        if it["sap_run_id"] != run["id"]:
            continue
        bt = db.batches.get(it["batch_id"])
        if bt and bt["status"] in ("FILLING", "BOILING", "FINISHED"):
            drawn += d(it["gallons_drawn"])
    run["gallons_remaining"] = round2(d(run["gallons_collected"]) - drawn)
    touch(run)


def recompute_lot_unpackaged(lot):
    filled = Decimal("0")
    for pr in db.packaging_runs.values():
        if pr["syrup_lot_id"] == lot["id"] and pr["status"] == "FILLED":
            filled += d(pr["filled_gallons"])
    lot["unpackaged_gallons"] = round2(d(lot["measured_gallons"]) - filled)
    touch(lot)


def maybe_auto_regress_bush(bush):
    """If bush LIVE and taps_live == 0 -> TAPPING (auto regression)."""
    if bush["status"] == "LIVE" and bush["taps_live"] == 0:
        bush["status"] = "TAPPING"
        bump(bush)


def pull_line(line):
    """Pull a line and recompute rollups. No version bump on cascade pulls per
    state machine table (pull side_effects list only recomputes), but direct
    POST pull does bump. This helper is the shared cascade path: bump always,
    since every state transition increments version (PRD §2.4)."""
    if line["status"] == "PULLED":
        return
    line["status"] = "PULLED"
    bump(line)
    bush = db.sugarbushes.get(line["sugarbush_id"])
    if bush:
        recompute_bush_taps(bush)
        maybe_auto_regress_bush(bush)
        season = db.seasons.get(bush["season_id"])
        if season:
            recompute_season_taps_live(season)


def shutdown_bush_cascade(bush, bump_bush=True):
    """Pull every non-PULLED line, recompute rollups, mark SHUTDOWN."""
    for line in lines_of_bush(bush["id"]):
        if line["status"] in ("INSTALLING", "ACTIVE", "LEAK"):
            pull_line(line)
    recompute_bush_taps(bush)
    bush["status"] = "SHUTDOWN"
    if bump_bush:
        bump(bush)
    else:
        touch(bush)
    season = db.seasons.get(bush["season_id"])
    if season:
        recompute_season_taps_live(season)


# ------------------------------------------------------------------
# Calculations
# ------------------------------------------------------------------

def compute_start_boil(batch):
    """Stamp effective_brix per intake; compute input_brix, estimated, expected."""
    intakes = batch_intakes_of(batch["id"])
    boil_dt = clock_dt()
    total_drawn = Decimal("0")
    weighted = Decimal("0")
    for it in intakes:
        run = db.sap_runs[it["sap_run_id"]]
        collected_dt = parse_dt(run["collected_at"])
        delta_seconds = (boil_dt - collected_dt).total_seconds()
        if delta_seconds < 0:
            delta_seconds = 0
        hours_held = Decimal(str(delta_seconds)) / Decimal("3600")
        full_days = int(hours_held // 24)
        deterioration = DETERIORATION_PER_DAY * full_days
        if deterioration > MAX_DETERIORATION:
            deterioration = MAX_DETERIORATION
        eff = d(run["measured_brix"]) - deterioration
        if eff < BRIX_FLOOR:
            eff = BRIX_FLOOR
        it["effective_brix"] = eff
        drawn = d(it["gallons_drawn"])
        total_drawn += drawn
        weighted += drawn * eff
    if total_drawn > 0:
        batch["input_brix"] = round2(weighted / total_drawn)
    else:
        batch["input_brix"] = None
    sap_in = d(batch["sap_gallons_in"])
    batch["estimated_syrup_gallons"] = round2(sap_in * d(batch["input_brix"]) / RULE_86)
    batch["expected_syrup_gallons"] = round2(sap_in * d(batch["input_brix"]) / RULE_88_2)


def compute_yield_variance(measured, expected):
    measured = d(measured)
    expected = d(expected)
    return round2((measured - expected) / expected * Decimal("100"))


def classify_grade(light_transmittance_pct, latest_eval):
    """grade_classification (SCAFFOLD §1.3). latest_eval must exist."""
    if latest_eval["defect_flags"] or latest_eval["flavor_score"] < FLAVOR_MIN:
        return "PROCESSING"
    t = d(light_transmittance_pct)
    if t >= T_GOLDEN:
        return "GOLDEN"
    if t >= T_AMBER:
        return "AMBER"
    if t >= T_DARK:
        return "DARK"
    return "VERY_DARK"


def latest_evaluation(lot_id):
    evals = [e for e in db.flavor_evaluations.values() if e["syrup_lot_id"] == lot_id]
    if not evals:
        return None
    evals.sort(key=lambda e: (e["evaluated_at"], e["created_at"]))
    return evals[-1]


def batch_intakes_of(batch_id):
    rows = [i for i in db.batch_intakes.values() if i["batch_id"] == batch_id]
    rows.sort(key=lambda i: (i["created_at"], i["id"]))
    return rows


def bushes_contributing_to_batch(batch_id):
    """Return {sugarbush_id: Decimal(gallons_drawn)} for this batch's intakes."""
    out = {}
    for it in batch_intakes_of(batch_id):
        run = db.sap_runs.get(it["sap_run_id"])
        if not run:
            continue
        bid = run["sugarbush_id"]
        out[bid] = out.get(bid, Decimal("0")) + d(it["gallons_drawn"])
    return out


def accrue_provisional_royalty(batch):
    """SHARE_OF_SYRUP provisional: per-bush, per-batch double rounding (PRD §3.7)."""
    intakes = batch_intakes_of(batch["id"])
    # sum gallons_drawn * effective_brix per bush
    per_bush_attr = {}
    for it in intakes:
        run = db.sap_runs.get(it["sap_run_id"])
        if not run:
            continue
        bid = run["sugarbush_id"]
        per_bush_attr[bid] = per_bush_attr.get(bid, Decimal("0")) + (
            d(it["gallons_drawn"]) * d(it["effective_brix"])
        )
    for bush_id, attr_sum in per_bush_attr.items():
        for lease in db.leases.values():
            if (lease["sugarbush_id"] == bush_id
                    and lease["royalty_basis"] == "SHARE_OF_SYRUP"
                    and lease["status"] in ("ACTIVE", "TERMINATED", "EXPIRED")):
                attributable = round2(attr_sum / RULE_86)
                royalty = round2(attributable * d(lease["share_pct"]) / Decimal("100"))
                lease["accrued_royalty_gallons"] = round2(
                    d(lease["accrued_royalty_gallons"]) + royalty
                )
                touch(lease)


def settle_final_royalty(season):
    """Final SHARE_OF_SYRUP settlement at reconcile (PRD §3.7). Single rounding."""
    # finished batches of this season whose lot is NOT condemned
    batches = []
    for bt in db.batches.values():
        if bt["season_id"] != season["id"] or bt["status"] != "FINISHED":
            continue
        lot = lot_of_batch(bt["id"])
        if lot and lot["status"] == "CONDEMNED":
            continue
        batches.append(bt)
    # for each SHARE lease on a bush of this season
    for lease in db.leases.values():
        bush = db.sugarbushes.get(lease["sugarbush_id"])
        if not bush or bush["season_id"] != season["id"]:
            continue
        if lease["royalty_basis"] != "SHARE_OF_SYRUP":
            continue
        if lease["status"] not in ("ACTIVE", "TERMINATED", "EXPIRED"):
            continue
        total_attr = Decimal("0")
        for bt in batches:
            contrib = bushes_contributing_to_batch(bt["id"])
            bush_gallons = contrib.get(bush["id"], Decimal("0"))
            if bush_gallons <= 0:
                continue
            sap_in = d(bt["sap_gallons_in"])
            if sap_in <= 0:
                continue
            attr = (bush_gallons / sap_in) * d(bt["measured_syrup_gallons"])
            total_attr += attr
        settled = round2(d(lease["share_pct"]) / Decimal("100") * total_attr)
        lease["settled_royalty_gallons"] = settled
        touch(lease)


def lot_of_batch(batch_id):
    for lot in db.syrup_lots.values():
        if lot["batch_id"] == batch_id:
            return lot
    return None


# ------------------------------------------------------------------
# Organic certification recompute
# ------------------------------------------------------------------

def recompute_organic_certified(bush):
    audits = [a for a in db.cert_audits.values()
              if a["sugarbush_id"] == bush["id"]
              and a["audit_type"] == "ORGANIC"
              and a["status"] == "RECORDED"]
    if not audits:
        bush["organic_certified"] = False
    else:
        audits.sort(key=lambda a: (a["scheduled_for"], a["created_at"]))
        bush["organic_certified"] = (audits[-1]["result"] == "PASS")
    touch(bush)


def latest_organic_audit(bush_id):
    audits = [a for a in db.cert_audits.values()
              if a["sugarbush_id"] == bush_id and a["audit_type"] == "ORGANIC"]
    if not audits:
        return None
    audits.sort(key=lambda a: (a["scheduled_for"], a["created_at"]))
    return audits[-1]


# ------------------------------------------------------------------
# Serializers (Decimals -> JSON numbers)
# ------------------------------------------------------------------

def _ser_common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_season(e):
    out = _ser_common(e)
    out.update({
        "year": e["year"],
        "opens_on": e["opens_on"],
        "closes_on": e["closes_on"],
        "planned_taps": e["planned_taps"],
        "status": e["status"],
        "taps_live": e["taps_live"],
        "total_sap_gallons": num_out(e["total_sap_gallons"]),
        "total_syrup_gallons": num_out(e["total_syrup_gallons"]),
    })
    return out


def ser_sugarbush(e):
    out = _ser_common(e)
    out.update({
        "season_id": e["season_id"],
        "name": e["name"],
        "tap_capacity": e["tap_capacity"],
        "stand_type": e["stand_type"],
        "active_lease_id": e["active_lease_id"],
        "organic_certified": e["organic_certified"],
        "taps_set": e["taps_set"],
        "taps_live": e["taps_live"],
        "status": e["status"],
    })
    return out


def ser_lease(e):
    out = _ser_common(e)
    out.update({
        "sugarbush_id": e["sugarbush_id"],
        "landowner_name": e["landowner_name"],
        "royalty_basis": e["royalty_basis"],
        "per_tap_cents": e["per_tap_cents"],
        "share_pct": num_out(e["share_pct"]) if e["share_pct"] is not None else None,
        "certified_organic_required": e["certified_organic_required"],
        "term_start": e["term_start"],
        "term_end": e["term_end"],
        "status": e["status"],
        "taps_snapshot": e["taps_snapshot"],
        "accrued_royalty_cents": e["accrued_royalty_cents"],
        "accrued_royalty_gallons": num_out(e["accrued_royalty_gallons"]),
        "settled_royalty_gallons": (num_out(e["settled_royalty_gallons"])
                                    if e["settled_royalty_gallons"] is not None else None),
    })
    return out


def ser_tap_line(e):
    out = _ser_common(e)
    out.update({
        "sugarbush_id": e["sugarbush_id"],
        "line_code": e["line_code"],
        "tap_count": e["tap_count"],
        "vacuum_target_inhg": num_out(e["vacuum_target_inhg"]),
        "latest_vacuum_inhg": (num_out(e["latest_vacuum_inhg"])
                               if e["latest_vacuum_inhg"] is not None else None),
        "status": e["status"],
    })
    return out


def ser_vacuum_reading(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "tap_line_id": e["tap_line_id"],
        "inhg": num_out(e["inhg"]),
        "recorded_at": e["recorded_at"],
    }


def ser_weather_window(e):
    out = _ser_common(e)
    out.update({
        "season_id": e["season_id"],
        "opens_at": e["opens_at"],
        "closes_at": e["closes_at"],
        "forecast_min_f": num_out(e["forecast_min_f"]),
        "forecast_max_f": num_out(e["forecast_max_f"]),
        "status": e["status"],
    })
    return out


def ser_crew_member(e):
    out = _ser_common(e)
    out.update({
        "season_id": e["season_id"],
        "name": e["name"],
        "crew_role": e["crew_role"],
        "cert_organic_handler": e["cert_organic_handler"],
        "status": e["status"],
    })
    return out


def ser_sap_run(e):
    out = _ser_common(e)
    out.update({
        "sugarbush_id": e["sugarbush_id"],
        "weather_window_id": e["weather_window_id"],
        "collected_by": e["collected_by"],
        "gallons_collected": num_out(e["gallons_collected"]),
        "measured_brix": num_out(e["measured_brix"]),
        "collected_at": e["collected_at"],
        "gallons_remaining": num_out(e["gallons_remaining"]),
        "status": e["status"],
    })
    return out


def ser_batch(e):
    out = _ser_common(e)
    out.update({
        "season_id": e["season_id"],
        "boiled_by": e["boiled_by"],
        "evaporator_capacity_gal": e["evaporator_capacity_gal"],
        "sap_gallons_in": num_out(e["sap_gallons_in"]),
        "input_brix": num_out(e["input_brix"]) if e["input_brix"] is not None else None,
        "estimated_syrup_gallons": (num_out(e["estimated_syrup_gallons"])
                                    if e["estimated_syrup_gallons"] is not None else None),
        "expected_syrup_gallons": (num_out(e["expected_syrup_gallons"])
                                   if e["expected_syrup_gallons"] is not None else None),
        "boil_started_at": e["boil_started_at"],
        "finished_brix": (num_out(e["finished_brix"])
                          if e["finished_brix"] is not None else None),
        "measured_syrup_gallons": (num_out(e["measured_syrup_gallons"])
                                   if e["measured_syrup_gallons"] is not None else None),
        "yield_variance_pct": (num_out(e["yield_variance_pct"])
                               if e["yield_variance_pct"] is not None else None),
        "status": e["status"],
    })
    return out


def ser_batch_intake(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "batch_id": e["batch_id"],
        "sap_run_id": e["sap_run_id"],
        "gallons_drawn": num_out(e["gallons_drawn"]),
        "draw_sequence": e["draw_sequence"],
        "effective_brix": (num_out(e["effective_brix"])
                           if e["effective_brix"] is not None else None),
    }


def ser_syrup_lot(e):
    out = _ser_common(e)
    out.update({
        "batch_id": e["batch_id"],
        "season_id": e["season_id"],
        "measured_gallons": num_out(e["measured_gallons"]),
        "finished_brix": num_out(e["finished_brix"]),
        "light_transmittance_pct": (num_out(e["light_transmittance_pct"])
                                    if e["light_transmittance_pct"] is not None else None),
        "grade": e["grade"],
        "unpackaged_gallons": num_out(e["unpackaged_gallons"]),
        "quality_hold_auto": e["quality_hold_auto"],
        "status": e["status"],
    })
    return out


def ser_flavor_evaluation(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "syrup_lot_id": e["syrup_lot_id"],
        "evaluator_id": e["evaluator_id"],
        "flavor_score": e["flavor_score"],
        "defect_flags": list(e["defect_flags"]),
        "evaluated_at": e["evaluated_at"],
    }


def ser_packaging_run(e):
    out = _ser_common(e)
    out.update({
        "syrup_lot_id": e["syrup_lot_id"],
        "container_type": e["container_type"],
        "units_planned": e["units_planned"],
        "units_filled": e["units_filled"],
        "filled_gallons": (num_out(e["filled_gallons"])
                           if e["filled_gallons"] is not None else None),
        "status": e["status"],
    })
    return out


def ser_cert_audit(e):
    out = _ser_common(e)
    out.update({
        "sugarbush_id": e["sugarbush_id"],
        "audit_type": e["audit_type"],
        "scheduled_for": e["scheduled_for"],
        "result": e["result"],
        "status": e["status"],
    })
    return out

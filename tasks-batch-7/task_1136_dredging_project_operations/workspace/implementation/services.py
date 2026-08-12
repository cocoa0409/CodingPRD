"""Business logic: compliance posture, cascades, production estimate,
dual-quantity accounting, tiered quantity payment, settlement totals."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING

from db import store
from util import r2, r0, touch, fmt_dt, dec_to_num

# Calculation constants (scaffold section 1.3)
WEATHER_ALLOWANCE_PCT = Decimal("0.20")
MATERIAL_FACTOR = {
    "SAND": Decimal("1.00"),
    "SILT": Decimal("0.85"),
    "CLAY": Decimal("0.70"),
    "GRAVEL": Decimal("0.55"),
    "ROCK": Decimal("0.35"),
}
STANDBY_DEDUCTIBLE_HOURS = Decimal("4.0")
STANDBY_MULTIPLIER = {
    "WEATHER": Decimal("1.0"),
    "OWNER_DIRECTED": Decimal("1.0"),
    "SPECIES_SHUTDOWN": Decimal("0.5"),
    "EQUIPMENT_BREAKDOWN": Decimal("0"),
}
TIER1_PCT = Decimal("0.8")
TIER2_RATE = Decimal("0.90")
TIER3_RATE = Decimal("0.75")
RECON_TOLERANCE_PCT = Decimal("15")


# ---------------------------------------------------------------------------
# Compliance posture (PRD 2.6 / calculation compliance_posture)
# ---------------------------------------------------------------------------

def governing_permit(project_id, at=None):
    """The ISSUED permit whose CLOSED window contains the logical time."""
    now = at if at is not None else store.logical_now
    for p in store.permits.values():
        if (
            p["project_id"] == project_id
            and p["status"] == "ISSUED"
            and p["window_start_utc"] <= now <= p["window_end_utc"]
        ):
            return p
    return None


def derive_posture(project_id):
    """Fixed top-to-bottom precedence. Returns (posture, cause) where cause in
    WINDOW / SPECIES / TURBIDITY / AVERAGE / CLEAR."""
    permit = governing_permit(project_id)
    if permit is None:
        # No governing permit (incl. no ISSUED permit at all) -> SUSPENDED
        return "SUSPENDED", "WINDOW"
    for s in store.sightings.values():
        if s["project_id"] == project_id and s["status"] == "ACTIVE":
            return "SUSPENDED", "SPECIES"
    now = store.logical_now
    lo = now - timedelta(hours=permit["turbidity_averaging_hours"])
    # Trailing half-open window (now - averaging_hours, now] on taken_utc.
    window = [
        r
        for r in store.readings.values()
        if r["project_id"] == project_id and lo < r["taken_utc"] <= now
    ]
    if any(r["value_ntu"] >= permit["turbidity_ceiling_ntu"] for r in window):
        return "SUSPENDED", "TURBIDITY"
    if window:
        avg = sum(Decimal(r["value_ntu"]) for r in window) / Decimal(len(window))
        if avg >= Decimal(permit["turbidity_limit_ntu"]):
            return "RESTRICTED", "AVERAGE"
    return "CLEAR", "CLEAR"


def refresh_posture(project_id):
    """Recompute and store the project's posture; a genuine change of this
    computed field is a mutation (updated_at + version)."""
    project = store.projects[project_id]
    posture, cause = derive_posture(project_id)
    if project["compliance_posture"] != posture:
        project["compliance_posture"] = posture
        touch(project)
    return posture, cause


def shutdown_project_events(project_id, reason):
    """ACTIVE -> SHUTDOWN with reason, stamping last_shutdown_at with now."""
    for ev in store.events.values():
        if ev["_project_id"] == project_id and ev["status"] == "ACTIVE":
            ev["status"] = "SHUTDOWN"
            ev["shutdown_reason"] = reason
            ev["last_shutdown_at"] = store.logical_now
            touch(ev)


def advance_clock(to_dt):
    """PRD 2.4 cascade origin: permit expiry, posture recompute, window-exit
    auto-shutdown of ACTIVE events."""
    store.logical_now = to_dt
    for p in list(store.permits.values()):
        if p["status"] == "ISSUED" and to_dt > p["window_end_utc"]:
            p["status"] = "EXPIRED"
            touch(p)
    for project in list(store.projects.values()):
        posture, cause = refresh_posture(project["id"])
        if posture == "SUSPENDED":
            reason = {"SPECIES": "SPECIES", "TURBIDITY": "TURBIDITY"}.get(cause, "WINDOW")
            shutdown_project_events(project["id"], reason)


# ---------------------------------------------------------------------------
# Production estimate (calculation production_estimate)
# ---------------------------------------------------------------------------

def _ceil_div(total, daily):
    if daily <= 0:
        return 0
    return int((Decimal(total) / daily).quantize(Decimal("1"), rounding=ROUND_CEILING))


def compute_estimates(plan):
    reaches = [r for r in store.reaches.values() if r["project_id"] == plan["project_id"]]
    total_design = sum(Decimal(r["design_quantity_cy"]) for r in reaches)
    depths = [Decimal(r["required_depth_ft"]) for r in reaches]
    max_depth = max(depths) if depths else Decimal("0")
    if max_depth < 30:
        depth_factor = Decimal("1.00")
    elif max_depth < 50:
        depth_factor = Decimal("0.85")
    else:
        depth_factor = Decimal("0.70")
    material_factor = MATERIAL_FACTOR[plan["material_class"]]
    rated = Decimal(store.plants[plan["plant_id"]]["rated_daily_production_cy"])
    nominal = r2(rated * material_factor * depth_factor)
    risk = r2(nominal * (Decimal("1") - WEATHER_ALLOWANCE_PCT))
    plan["nominal_daily_production_cy"] = nominal
    plan["risk_adjusted_daily_production_cy"] = risk
    plan["nominal_duration_days"] = _ceil_div(total_design, nominal)
    plan["risk_adjusted_duration_days"] = _ceil_div(total_design, risk)


# ---------------------------------------------------------------------------
# Reach removed quantity (calculation reach_removed_quantity, INV-S)
# ---------------------------------------------------------------------------

def _latest_accepted(reach_id, kind):
    cands = [
        s
        for s in store.surveys.values()
        if s["reach_id"] == reach_id and s["kind"] == kind and s["status"] == "ACCEPTED"
    ]
    if not cands:
        return None
    cands.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return cands[-1]


def recompute_removed(reach):
    pre = _latest_accepted(reach["id"], "PRE_DREDGE")
    post = _latest_accepted(reach["id"], "POST_DREDGE")
    if post is None:
        reach["removed_in_place_cy"] = Decimal("0")
    else:
        pre_v = Decimal(pre["measured_volume_cy"]) if pre else Decimal("0")
        reach["removed_in_place_cy"] = r2(
            max(Decimal("0"), pre_v - Decimal(post["measured_volume_cy"]))
        )


# ---------------------------------------------------------------------------
# Dredge event shutdown accrual
# ---------------------------------------------------------------------------

def accrue_shutdown(ev):
    """Settle the open shutdown interval into shutdown_accumulated_hours
    (round half up, 2dp)."""
    if ev["status"] == "SHUTDOWN" and ev["last_shutdown_at"] is not None:
        seconds = Decimal(str((store.logical_now - ev["last_shutdown_at"]).total_seconds()))
        hours = r2(seconds / Decimal(3600))
        ev["shutdown_accumulated_hours"] = r2(ev["shutdown_accumulated_hours"] + hours)


# ---------------------------------------------------------------------------
# Payment certificate quantities (scow_derived_quantity, survey_derived_quantity,
# quantity_payment, final_settlement_total)
# ---------------------------------------------------------------------------

def scow_per_reach(reach_ids, period_start=None, period_end=None):
    """Per-ticket-rounded in_situ volumes summed per reach. Period filter is a
    CLOSED interval applied only when bounds are given (INTERIM sweep)."""
    per_reach = {rid: Decimal("0") for rid in dict.fromkeys(reach_ids)}
    wanted = set(reach_ids)
    for t in store.tickets.values():
        if t["status"] != "CONFIRMED":
            continue  # VOIDED excluded; REPORTED/REJECTED never counted
        ev = store.events[t["dredge_event_id"]]
        if ev["reach_id"] not in wanted:
            continue
        if period_start is not None and not (period_start <= t["placed_utc"] <= period_end):
            continue
        per_reach[ev["reach_id"]] += t["in_situ_volume_cy"]
    return per_reach


def waterfall_line(reach, q, base_rate):
    """Tiered waterfall for one reach line (per-tier rounding, then sum)."""
    zero = Decimal("0")
    C = reach["cumulative_certified_quantity_cy"]
    D = Decimal(reach["design_quantity_cy"])
    A = Decimal(reach["overdepth_allowance_cy"])
    base = Decimal(base_rate)
    tier1_cap = r2(TIER1_PCT * D)
    tier2_cap = D
    tier3_cap = D + A
    q1 = min(max(q, zero), max(zero, tier1_cap - C))
    q2 = min(max(q - q1, zero), max(zero, tier2_cap - C - q1))
    q3 = min(max(q - q1 - q2, zero), max(zero, tier3_cap - C - q1 - q2))
    amount1 = r0(q1 * base)
    amount2 = r0(q2 * base * TIER2_RATE)
    amount3 = r0(q3 * base * TIER3_RATE)
    return amount1 + amount2 + amount3


def compute_cert_snapshot(cert, submitted_by):
    """Compute and freeze every computed field (PRD 3.9, pinned evaluation
    order in final_settlement_total)."""
    project = store.projects[cert["project_id"]]
    reach_ids = cert["reach_ids"]
    is_final = cert["certificate_type"] == "FINAL"

    # Survey-derived total: all-time removed_in_place_cy over reach_ids.
    survey_total = sum(
        (store.reaches[rid]["removed_in_place_cy"] for rid in reach_ids), Decimal("0")
    )
    # Scow-derived total: period-bounded closed interval on INTERIM, all-time on FINAL.
    if is_final:
        per_reach_scow = scow_per_reach(reach_ids)
    else:
        per_reach_scow = scow_per_reach(
            reach_ids, cert["period_start_utc"], cert["period_end_utc"]
        )
    scow_total = sum(per_reach_scow.values(), Decimal("0"))

    # Line quantity per reach, in reach_ids order as given.
    line_qty = []
    for rid in reach_ids:
        if is_final and project["measurement_basis"] == "IN_PLACE":
            q = store.reaches[rid]["removed_in_place_cy"]
        else:
            q = per_reach_scow.get(rid, Decimal("0"))
        line_qty.append((rid, q))

    quantity_cy = sum((q for _, q in line_qty), Decimal("0"))
    quantity_amount = sum(
        waterfall_line(store.reaches[rid], q, project["base_rate_cents_per_cy"])
        for rid, q in line_qty
    )

    standby_amount = sum(
        store.claims[cid]["payable_amount_cents"] for cid in cert["standby_claim_ids"]
    )

    if is_final:
        span_seconds = Decimal(
            str((cert["period_end_utc"] - cert["period_start_utc"]).total_seconds())
        )
        actual_days = int(
            (span_seconds / Decimal(86400)).quantize(Decimal("1"), rounding=ROUND_CEILING)
        )
        allowed = project["allowed_days_frozen"] or 0
        overrun = max(0, actual_days - allowed)
        liquidated = project["liquidated_damages_cents_per_day"] * overrun
        if survey_total == 0:
            delta = Decimal("0") if scow_total == 0 else Decimal("100")
        else:
            delta = abs(survey_total - scow_total) / survey_total * Decimal("100")
    else:
        liquidated = 0
        delta = None

    total_amount = quantity_amount + standby_amount - liquidated

    cert["quantity_cy"] = quantity_cy
    cert["quantity_amount_cents"] = quantity_amount
    cert["standby_amount_cents"] = standby_amount
    cert["liquidated_damages_cents"] = liquidated
    cert["reconciliation_delta_pct"] = delta
    cert["survey_derived_total_cy"] = survey_total
    cert["scow_derived_total_cy"] = scow_total
    cert["total_amount_cents"] = total_amount
    cert["submitted_by_user_id"] = submitted_by
    cert["_line_qty"] = [[rid, q] for rid, q in line_qty]


def clear_cert_snapshot(cert):
    for f in (
        "quantity_cy",
        "quantity_amount_cents",
        "standby_amount_cents",
        "liquidated_damages_cents",
        "reconciliation_delta_pct",
        "survey_derived_total_cy",
        "scow_derived_total_cy",
        "total_amount_cents",
    ):
        cert[f] = None
    cert["_line_qty"] = []


# ---------------------------------------------------------------------------
# Serializers (exact scaffold field sets; internal "_" keys never leak)
# ---------------------------------------------------------------------------

def serialize_project(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "measurement_basis": p["measurement_basis"],
        "base_rate_cents_per_cy": p["base_rate_cents_per_cy"],
        "standby_rate_cents_per_hour": p["standby_rate_cents_per_hour"],
        "liquidated_damages_cents_per_day": p["liquidated_damages_cents_per_day"],
        "status": p["status"],
        "compliance_posture": p["compliance_posture"],
        "allowed_days_frozen": p["allowed_days_frozen"],
        "total_certified_cents": p["total_certified_cents"],
        "total_paid_cents": p["total_paid_cents"],
        "outstanding_payable_cents": p["total_certified_cents"] - p["total_paid_cents"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def serialize_permit(p):
    return {
        "id": p["id"],
        "project_id": p["project_id"],
        "permit_number": p["permit_number"],
        "window_start_utc": fmt_dt(p["window_start_utc"]),
        "window_end_utc": fmt_dt(p["window_end_utc"]),
        "turbidity_limit_ntu": p["turbidity_limit_ntu"],
        "turbidity_ceiling_ntu": p["turbidity_ceiling_ntu"],
        "turbidity_averaging_hours": p["turbidity_averaging_hours"],
        "species_standdown_hours": p["species_standdown_hours"],
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def serialize_reach(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "name": r["name"],
        "design_quantity_cy": r["design_quantity_cy"],
        "required_depth_ft": dec_to_num(r["required_depth_ft"]),
        "allowable_overdepth_ft": dec_to_num(r["allowable_overdepth_ft"]),
        "overdepth_allowance_cy": r["overdepth_allowance_cy"],
        "status": r["status"],
        "removed_in_place_cy": dec_to_num(r["removed_in_place_cy"]),
        "cumulative_certified_quantity_cy": dec_to_num(r["cumulative_certified_quantity_cy"]),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def serialize_plant(p):
    return {
        "id": p["id"],
        "contractor_ref": p["contractor_ref"],
        "plant_type": p["plant_type"],
        "rated_daily_production_cy": p["rated_daily_production_cy"],
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def serialize_plan(p):
    return {
        "id": p["id"],
        "project_id": p["project_id"],
        "plant_id": p["plant_id"],
        "material_class": p["material_class"],
        "planned_start_utc": fmt_dt(p["planned_start_utc"]),
        "planned_end_utc": fmt_dt(p["planned_end_utc"]),
        "revision": p["revision"],
        "nominal_daily_production_cy": dec_to_num(p["nominal_daily_production_cy"]),
        "risk_adjusted_daily_production_cy": dec_to_num(p["risk_adjusted_daily_production_cy"]),
        "nominal_duration_days": p["nominal_duration_days"],
        "risk_adjusted_duration_days": p["risk_adjusted_duration_days"],
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def serialize_survey(s):
    return {
        "id": s["id"],
        "reach_id": s["reach_id"],
        "kind": s["kind"],
        "measured_volume_cy": s["measured_volume_cy"],
        "min_sounding_depth_ft": dec_to_num(s["min_sounding_depth_ft"]),
        "supersedes_survey_id": s["supersedes_survey_id"],
        "submitted_by_user_id": s["submitted_by_user_id"],
        "status": s["status"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def serialize_event(e):
    return {
        "id": e["id"],
        "reach_id": e["reach_id"],
        "plant_id": e["plant_id"],
        "started_utc": fmt_dt(e["started_utc"]),
        "reduced_rate": e["reduced_rate"],
        "ended_utc": fmt_dt(e["ended_utc"]),
        "status": e["status"],
        "shutdown_reason": e["shutdown_reason"],
        "last_shutdown_at": fmt_dt(e["last_shutdown_at"]),
        "shutdown_accumulated_hours": dec_to_num(e["shutdown_accumulated_hours"]),
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def serialize_site(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "site_type": s["site_type"],
        "capacity_cy": s["capacity_cy"],
        "bulking_factor": dec_to_num(s["bulking_factor"]),
        "used_cy": dec_to_num(s["used_cy"]),
        "remaining_cy": dec_to_num(Decimal(s["capacity_cy"]) - s["used_cy"]),
        "status": s["status"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def serialize_ticket(t):
    return {
        "id": t["id"],
        "dredge_event_id": t["dredge_event_id"],
        "disposal_site_id": t["disposal_site_id"],
        "placed_utc": fmt_dt(t["placed_utc"]),
        "declared_volume_cy": t["declared_volume_cy"],
        "witnessed_volume_cy": t["witnessed_volume_cy"],
        "reported_by_user_id": t["reported_by_user_id"],
        "in_situ_volume_cy": dec_to_num(t["in_situ_volume_cy"]),
        "status": t["status"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def serialize_claim(c):
    return {
        "id": c["id"],
        "project_id": c["project_id"],
        "plant_id": c["plant_id"],
        "period_start_utc": fmt_dt(c["period_start_utc"]),
        "period_end_utc": fmt_dt(c["period_end_utc"]),
        "claimed_hours": dec_to_num(c["claimed_hours"]),
        "reason": c["reason"],
        "payable_hours": dec_to_num(c["payable_hours"]),
        "payable_amount_cents": c["payable_amount_cents"],
        "claimed_by_user_id": c["claimed_by_user_id"],
        "status": c["status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def serialize_sighting(s):
    return {
        "id": s["id"],
        "project_id": s["project_id"],
        "species_class": s["species_class"],
        "observed_utc": fmt_dt(s["observed_utc"]),
        "reported_by_user_id": s["reported_by_user_id"],
        "cleared_at": fmt_dt(s["cleared_at"]),
        "status": s["status"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def serialize_reading(r):
    # TurbidityReading is immutable: id + created_at only (PRD 2.5 exception).
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "value_ntu": r["value_ntu"],
        "taken_utc": fmt_dt(r["taken_utc"]),
        "recorded_by_user_id": r["recorded_by_user_id"],
        "created_at": fmt_dt(r["created_at"]),
    }


def serialize_cert(c):
    return {
        "id": c["id"],
        "project_id": c["project_id"],
        "certificate_type": c["certificate_type"],
        "period_start_utc": fmt_dt(c["period_start_utc"]),
        "period_end_utc": fmt_dt(c["period_end_utc"]),
        "reach_ids": list(c["reach_ids"]),
        "standby_claim_ids": list(c["standby_claim_ids"]),
        "quantity_cy": dec_to_num(c["quantity_cy"]),
        "quantity_amount_cents": c["quantity_amount_cents"],
        "standby_amount_cents": c["standby_amount_cents"],
        "liquidated_damages_cents": c["liquidated_damages_cents"],
        "reconciliation_delta_pct": dec_to_num(c["reconciliation_delta_pct"]),
        "survey_derived_total_cy": dec_to_num(c["survey_derived_total_cy"]),
        "scow_derived_total_cy": dec_to_num(c["scow_derived_total_cy"]),
        "total_amount_cents": c["total_amount_cents"],
        "submitted_by_user_id": c["submitted_by_user_id"],
        "override_note": c["override_note"],
        "status": c["status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }

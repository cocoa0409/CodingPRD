"""Derived-field recomputation and JSON serialisation.

Aggregate fields (the dairy counters, the facility mass-control and revenue
ledger, the pathway credit totals) are recomputed from the underlying rows
whenever they are read, so the two conserved quantities can never drift.  The
explicit `version` bumps the PRD names are still applied by the route code.
"""
from datetime import timezone
from decimal import Decimal

import config
from db import db, fmt_dt
from numeric import D, q, fnum
from services import calc
from validation import date_of

ZERO = Decimal("0")


# --------------------------------------------------------------- collections
def deliveries_of_day(day_id, statuses=("ACCEPTED",)):
    return [d for d in db.deliveries.values()
            if d["ops_day_id"] == day_id and d["status"] in statuses]


def days_of_facility(facility_id):
    return [d for d in db.ops_days.values() if d["facility_id"] == facility_id]


def agreements_of_dairy(dairy_id):
    return [a for a in db.agreements.values() if a["dairy_id"] == dairy_id]


def batches_of_pathway(pathway_id):
    return [b for b in db.batches.values() if b["pathway_id"] == pathway_id]


def active_interconnect(facility_id):
    rows = [i for i in db.interconnects.values()
            if i["facility_id"] == facility_id and i["status"] == "ACTIVE"]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["_created"], r["_seq"]))
    return rows[0]


# ------------------------------------------------------------------- dairy
def dairy_counts(dairy_id):
    active = 0
    contracted = 0
    for a in db.agreements.values():
        if a["dairy_id"] != dairy_id:
            continue
        if a["status"] == "ACTIVE":
            active += 1
            contracted += 1
        elif a["status"] == "SUSPENDED":
            contracted += 1
    return active, contracted


def dairy_status(active, contracted):
    if contracted == 0:
        return "PROSPECT"
    if active >= 1:
        return "CONTRACTED"
    return "SUSPENDED"


def dairy_pan_ytd(dairy_id):
    year = db.now_logical().astimezone(timezone.utc).year
    total = ZERO
    for a in db.applications.values():
        if a["dairy_id"] != dairy_id or a["status"] != "APPLIED":
            continue
        if date_of(a["application_start_date"]).year != year:
            continue
        total += D(a["plant_available_nitrogen_kg"] or 0)
    return q(total, 3)


# ---------------------------------------------------------------- facility
def facility_mass(facility_id):
    total_received = ZERO
    unseparated = ZERO
    solids_produced = ZERO
    liquid_produced = ZERO
    for day in days_of_facility(facility_id):
        day_net = sum((d["net_tonnes"] for d in deliveries_of_day(day["id"])), ZERO)
        total_received += day_net
        if day["separation_recorded"]:
            solids_produced += D(day["digestate_solids_tonnes"])
            liquid_produced += D(day["digestate_liquid_tonnes"])
        else:
            unseparated += day_net
    solids_applied = ZERO
    liquid_applied = ZERO
    for a in db.applications.values():
        if a["facility_id"] == facility_id and a["status"] == "APPLIED":
            solids_applied += D(a["solids_tonnes_applied"])
            liquid_applied += D(a["liquid_tonnes_applied"])
    out = {
        "total_manure_received_tonnes": q(total_received, 3),
        "unseparated_manure_tonnes": q(unseparated, 3),
        "digestate_solids_produced_tonnes": q(solids_produced, 3),
        "digestate_liquid_produced_tonnes": q(liquid_produced, 3),
        "digestate_solids_applied_tonnes": q(solids_applied, 3),
        "digestate_liquid_applied_tonnes": q(liquid_applied, 3),
        "digestate_solids_on_hand_tonnes": q(solids_produced - solids_applied, 3),
        "digestate_liquid_on_hand_tonnes": q(liquid_produced - liquid_applied, 3),
    }
    out["mass_control_residual_tonnes"] = q(
        out["total_manure_received_tonnes"]
        - out["unseparated_manure_tonnes"]
        - out["digestate_solids_produced_tonnes"]
        - out["digestate_liquid_produced_tonnes"], 3)
    return out


def facility_ledger(facility_id):
    gross = 0
    share_paid = 0
    retained = 0
    for s in db.statements.values():
        if s["facility_id"] != facility_id:
            continue
        if s["status"] in ("DRAFT", "APPROVED", "PAID"):
            gross += int(s["gross_revenue_cents"])
        if s["status"] == "PAID":
            share_paid += int(s["total_dairy_share_cents"])
            retained += int(s["retained_cents"])
    return {
        "gross_revenue_to_date_cents": gross,
        "dairy_share_paid_cents": share_paid,
        "retained_to_date_cents": retained,
    }


# ----------------------------------------------------------------- pathway
def pathway_totals(pathway_id):
    issued = ZERO
    reversed_ = ZERO
    outstanding = ZERO
    for b in batches_of_pathway(pathway_id):
        qty = D(b["credit_quantity_final"] or 0)
        if b.get("_ever_issued"):
            issued += qty
        if b["status"] == "REVERSED":
            reversed_ += qty
        if b["status"] == "ISSUED":
            outstanding += qty
    issued = q(issued, 3)
    reversed_ = q(reversed_, 3)
    outstanding = q(outstanding, 3)
    return {
        "credits_issued_total": issued,
        "credits_reversed_total": reversed_,
        "credits_outstanding": outstanding,
        "credit_control_residual": q(issued - reversed_ - outstanding, 3),
    }


# ------------------------------------------------------- recompute utilities
def recompute_day_olr(day):
    facility = db.facilities[day["facility_id"]]
    day["organic_loading_rate"] = calc.organic_loading_rate(
        deliveries_of_day(day["id"]), facility["digester_volume_m3"])


def dscr_driver(facility_id):
    """The statement with the latest created_at among DRAFT/APPROVED/PAID."""
    rows = [s for s in db.statements.values()
            if s["facility_id"] == facility_id
            and s["status"] in ("DRAFT", "APPROVED", "PAID")]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["_created"], r["_seq"]))
    return rows[-1]


def apply_distribution_posture(facility, dscr):
    """Writes dscr_current / distribution_posture; returns True if the posture moved."""
    facility["dscr_current"] = dscr
    new_posture = calc.distribution_posture_for(
        dscr, facility["dscr_minimum"], facility["posture_override_active"])
    changed = new_posture != facility["distribution_posture"]
    facility["distribution_posture"] = new_posture
    if new_posture == "OPEN" and changed:
        facility["posture_override_active"] = False
    return changed


def rederive_dscr_from_driver(facility):
    driver = dscr_driver(facility["id"])
    if driver is None:
        return False
    return apply_distribution_posture(facility, driver["dscr_at_close"])


# ------------------------------------------------- carbon intensity variants
def pipeline_days_in_window(facility_id, start, end):
    """Operations days that actually put gas on the pipeline inside a window."""
    rows = [d for d in days_of_facility(facility_id)
            if d["gas_state"] in ("PIPELINE_SPEC", "INJECTED")
            and start <= date_of(d["ops_date"]) <= end]
    rows.sort(key=lambda r: (r["_created"], r["_seq"]))
    return rows


def certified_ci_score(facility_id, start, end):
    """The CERTIFIED variant: every input is read off the plant's own records."""
    days = pipeline_days_in_window(facility_id, start, end)
    energy = ZERO
    haul = ZERO
    vs_by_baseline = {"LAGOON": ZERO, "SOLID_STORAGE": ZERO, "DAILY_SPREAD": ZERO}
    for day in days:
        energy += D(day["pipeline_gas_mmbtu"] or 0)
        for delivery in deliveries_of_day(day["id"]):
            haul += D(delivery["haul_tonne_km"] or 0)
            agreement = db.agreements.get(delivery["agreement_id"])
            dairy = db.dairies.get(agreement["dairy_id"]) if agreement else None
            if dairy is None:
                continue
            baseline = dairy["manure_management_baseline"]
            vs_by_baseline[baseline] = vs_by_baseline.get(baseline, ZERO) \
                + D(delivery["vs_tonnes"] or 0)
    return calc.pathway_ci_score(energy, vs_by_baseline, haul, config.PROCESS_G_PER_MJ)


def verified_ci_score(audit):
    """The VERIFIED variant: every input is replaced by the auditor's measurement."""
    return calc.pathway_ci_score(
        audit["actual_pipeline_mmbtu"],
        {
            "LAGOON": audit["actual_vs_tonnes_lagoon"],
            "SOLID_STORAGE": audit["actual_vs_tonnes_solid_storage"],
            "DAILY_SPREAD": audit["actual_vs_tonnes_daily_spread"],
        },
        audit["actual_haul_tonne_km"],
        audit["actual_process_g_per_mj"])


# --------------------------------------------------------------- serialisers
def _base(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["_created"]),
        "updated_at": fmt_dt(row["_updated"]),
        "version": row["version"],
    }


def ser_dairy(row):
    active, contracted = dairy_counts(row["id"])
    out = _base(row)
    out.update({
        "name": row["name"],
        "county": row["county"],
        "herd_size": row["herd_size"],
        "manure_management_baseline": row["manure_management_baseline"],
        "haul_distance_km": fnum(row["haul_distance_km"]),
        "annual_nitrogen_budget_kg": fnum(row["annual_nitrogen_budget_kg"]),
        "status": dairy_status(active, contracted),
        "active_agreement_count": active,
        "contracted_agreement_count": contracted,
        "pan_applied_ytd_kg": fnum(dairy_pan_ytd(row["id"])),
    })
    return out


def ser_facility(row):
    out = _base(row)
    out.update({
        "name": row["name"],
        "digester_volume_m3": fnum(row["digester_volume_m3"]),
        "hydraulic_capacity_tonnes_per_day": fnum(row["hydraulic_capacity_tonnes_per_day"]),
        "thermal_regime": row["thermal_regime"],
        "target_temperature_c": fnum(row["target_temperature_c"]),
        "design_max_olr": fnum(row["design_max_olr"]),
        "ops_posture": row["ops_posture"],
        "distribution_posture": row["distribution_posture"],
        "posture_override_active": row["posture_override_active"],
        "reserve_target_cents": row["reserve_target_cents"],
        "reserve_balance_cents": row["reserve_balance_cents"],
        "annual_debt_service_cents": row["annual_debt_service_cents"],
        "dscr_minimum": fnum(row["dscr_minimum"]),
        "dscr_current": fnum(row["dscr_current"]),
    })
    for k, v in facility_mass(row["id"]).items():
        out[k] = fnum(v)
    out.update(facility_ledger(row["id"]))
    return out


def ser_agreement(row):
    out = _base(row)
    out.update({
        "dairy_id": row["dairy_id"],
        "facility_id": row["facility_id"],
        "committed_tonnes_per_day": fnum(row["committed_tonnes_per_day"]),
        "minimum_total_solids_pct": fnum(row["minimum_total_solids_pct"]),
        "term_start_date": row["term_start_date"],
        "term_end_date": row["term_end_date"],
        "revenue_share_pct": fnum(row["revenue_share_pct"]),
        "revenue_share_basis": row["revenue_share_basis"],
        "curtailable": row["curtailable"],
        "status": row["status"],
        "negotiation_round": row["negotiation_round"],
        "countered_tonnes_per_day": fnum(row["countered_tonnes_per_day"]),
        "countered_revenue_share_pct": fnum(row["countered_revenue_share_pct"]),
        "suspension_reason": row["suspension_reason"],
        "signed_at": row["signed_at"],
    })
    return out


def ser_delivery(row):
    out = _base(row)
    out.update({
        "agreement_id": row["agreement_id"],
        "ops_day_id": row["ops_day_id"],
        "gross_tonnes": fnum(row["gross_tonnes"]),
        "tare_tonnes": fnum(row["tare_tonnes"]),
        "total_solids_pct": fnum(row["total_solids_pct"]),
        "volatile_solids_pct_of_ts": fnum(row["volatile_solids_pct_of_ts"]),
        "net_tonnes": fnum(row["net_tonnes"]),
        "vs_tonnes": fnum(row["vs_tonnes"]),
        "haul_tonne_km": fnum(row["haul_tonne_km"]),
        "status": row["status"],
        "rejection_reason": row["rejection_reason"],
    })
    return out


OPS_DAY_NUMERIC = (
    "avg_digester_temp_c", "vfa_mg_per_l", "alkalinity_mg_per_l",
    "organic_loading_rate", "vfa_alkalinity_ratio", "raw_biogas_scf",
    "raw_ch4_pct", "raw_co2_pct", "raw_h2s_ppm", "raw_moisture_lb_per_mmscf",
    "raw_gas_mmbtu", "raw_hhv_btu_per_scf", "treated_ch4_pct", "treated_co2_pct",
    "treated_h2s_ppm", "treated_moisture_lb_per_mmscf", "pipeline_hhv_btu_per_scf",
    "pipeline_gas_scf", "pipeline_gas_mmbtu", "solids_capture_pct",
    "bedding_recovery_pct", "digestate_solids_tonnes", "digestate_liquid_tonnes",
    "bedding_recovered_tonnes", "lab_total_nitrogen_mg_per_l",
)
OPS_DAY_PLAIN = (
    "facility_id", "ops_date", "status", "gas_state", "temp_excursion_minutes",
    "thermal_status", "stress_points", "stability_status", "conditioning_attempts",
    "offspec_reason", "separation_recorded", "reopen_count",
)


def ser_ops_day(row):
    out = _base(row)
    for k in OPS_DAY_PLAIN:
        out[k] = row[k]
    for k in OPS_DAY_NUMERIC:
        out[k] = fnum(row[k])
    return out


def ser_interconnect(row):
    out = _base(row)
    out.update({
        "facility_id": row["facility_id"],
        "pipeline_operator_name": row["pipeline_operator_name"],
        "max_h2s_ppm": fnum(row["max_h2s_ppm"]),
        "max_moisture_lb_per_mmscf": fnum(row["max_moisture_lb_per_mmscf"]),
        "max_co2_pct": fnum(row["max_co2_pct"]),
        "min_hhv_btu_per_scf": fnum(row["min_hhv_btu_per_scf"]),
        "max_hourly_injection_mmbtu": fnum(row["max_hourly_injection_mmbtu"]),
        "ramp_buffer_minutes": row["ramp_buffer_minutes"],
        "nomination_lead_hours": row["nomination_lead_hours"],
        "status": row["status"],
        "curtailment_count": row["curtailment_count"],
    })
    return out


def ser_nomination(row):
    out = _base(row)
    out.update({
        "interconnect_id": row["interconnect_id"],
        "ops_day_id": row["ops_day_id"],
        "window_start_utc": row["window_start_utc"],
        "window_end_utc": row["window_end_utc"],
        "nominated_mmbtu": fnum(row["nominated_mmbtu"]),
        "window_minutes": row["window_minutes"],
        "hourly_rate_mmbtu": fnum(row["hourly_rate_mmbtu"]),
        "status": row["status"],
        "confirmed_mmbtu": fnum(row["confirmed_mmbtu"]),
        "delivered_mmbtu": fnum(row["delivered_mmbtu"]),
    })
    return out


def ser_pathway(row):
    out = _base(row)
    out.update({
        "facility_id": row["facility_id"],
        "program": row["program"],
        "pathway_code": row["pathway_code"],
        "reference_start_date": row["reference_start_date"],
        "reference_end_date": row["reference_end_date"],
        "status": row["status"],
        "certified_ci_score": fnum(row["certified_ci_score"]),
        "verified_ci_score": fnum(row["verified_ci_score"]),
        "ci_adjustment": fnum(row["ci_adjustment"]),
    })
    for k, v in pathway_totals(row["id"]).items():
        out[k] = fnum(v)
    return out


def ser_batch(row):
    out = _base(row)
    out.update({
        "pathway_id": row["pathway_id"],
        "facility_id": row["facility_id"],
        "period_start_date": row["period_start_date"],
        "period_end_date": row["period_end_date"],
        "superseded_by_batch_id": row["superseded_by_batch_id"],
        "status": row["status"],
        "delivered_mmbtu": fnum(row["delivered_mmbtu"]),
        "ci_score_used": fnum(row["ci_score_used"]),
        "credit_quantity_provisional": fnum(row["credit_quantity_provisional"]),
        "credit_quantity_final": fnum(row["credit_quantity_final"]),
        "credit_value_cents": row["credit_value_cents"],
        "reversal_reason": row["reversal_reason"],
    })
    return out


def ser_audit(row):
    out = _base(row)
    out.update({
        "pathway_id": row["pathway_id"],
        "audit_year": row["audit_year"],
        "verifier_body_name": row["verifier_body_name"],
        "status": row["status"],
        "actual_pipeline_mmbtu": fnum(row["actual_pipeline_mmbtu"]),
        "actual_vs_tonnes_lagoon": fnum(row["actual_vs_tonnes_lagoon"]),
        "actual_vs_tonnes_solid_storage": fnum(row["actual_vs_tonnes_solid_storage"]),
        "actual_vs_tonnes_daily_spread": fnum(row["actual_vs_tonnes_daily_spread"]),
        "actual_haul_tonne_km": fnum(row["actual_haul_tonne_km"]),
        "actual_process_g_per_mj": fnum(row["actual_process_g_per_mj"]),
        "reported_ci_score": fnum(row["reported_ci_score"]),
        "ci_delta": fnum(row["ci_delta"]),
        "finding_severity": row["finding_severity"],
        "remediation_round": row["remediation_round"],
    })
    return out


def ser_application(row):
    out = _base(row)
    out.update({
        "dairy_id": row["dairy_id"],
        "facility_id": row["facility_id"],
        "ops_day_id": row["ops_day_id"],
        "land_unit_code": row["land_unit_code"],
        "application_start_date": row["application_start_date"],
        "application_end_date": row["application_end_date"],
        "solids_tonnes_applied": fnum(row["solids_tonnes_applied"]),
        "liquid_tonnes_applied": fnum(row["liquid_tonnes_applied"]),
        "pan_basis": row["pan_basis"],
        "liquid_total_nitrogen_kg": fnum(row["liquid_total_nitrogen_kg"]),
        "solids_total_nitrogen_kg": fnum(row["solids_total_nitrogen_kg"]),
        "plant_available_nitrogen_kg": fnum(row["plant_available_nitrogen_kg"]),
        "status": row["status"],
    })
    return out


def ser_statement(row):
    out = _base(row)
    out.update({
        "facility_id": row["facility_id"],
        "period_start_date": row["period_start_date"],
        "period_end_date": row["period_end_date"],
        "gas_revenue_cents": row["gas_revenue_cents"],
        "superseded_by_statement_id": row["superseded_by_statement_id"],
        "credit_revenue_cents": row["credit_revenue_cents"],
        "gross_revenue_cents": row["gross_revenue_cents"],
        "management_fee_rate": fnum(row["management_fee_rate"]),
        "management_fee_cents": row["management_fee_cents"],
        "after_fee_cents": row["after_fee_cents"],
        "reserve_sweep_cents": row["reserve_sweep_cents"],
        "net_distributable_cents": row["net_distributable_cents"],
        "share_lines": [
            {
                "agreement_id": l["agreement_id"],
                "dairy_id": l["dairy_id"],
                "revenue_share_basis": l["revenue_share_basis"],
                "revenue_share_pct": fnum(l["revenue_share_pct"]),
                "committed_tonnes_per_day": fnum(l["committed_tonnes_per_day"]),
                "floor_cents": l["floor_cents"],
                "residual_cents": l["residual_cents"],
                "share_cents": l["share_cents"],
            }
            for l in row["share_lines"]
        ],
        "total_dairy_share_cents": row["total_dairy_share_cents"],
        "retained_cents": row["retained_cents"],
        "dscr_at_close": fnum(row["dscr_at_close"]),
        "status": row["status"],
        "approved_by_user_id": row["approved_by_user_id"],
        "paid_by_user_id": row["paid_by_user_id"],
    })
    return out

"""Calculations (SCAFFOLD.yaml §1.3) and cascading side effects (§1.2, PRD §2.8)."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import constants as C
import db

S = db.STORE
set_fields = db.set_fields


# ------------------------------------------------------------------ queries

def variances_for_design(design_id):
    return [v for v in S["variance_requests"].values() if v["design_id"] == design_id]


def has_approved_variance_for_design(design_id, relief_kind):
    return any(v["relief_kind"] == relief_kind and v["status"] == "APPROVED"
               for v in variances_for_design(design_id))


def has_approved_variance_for_site(site_id, relief_kind):
    return any(v["site_id"] == site_id and v["relief_kind"] == relief_kind
               and v["status"] == "APPROVED"
               for v in S["variance_requests"].values())


def permits_of_site(site_id):
    return [p for p in S["permits"].values() if p["site_id"] == site_id]


def installations_of_site(site_id):
    return [i for i in S["installations"].values() if i["site_id"] == site_id]


def installations_of_permit(permit_id):
    return [i for i in S["installations"].values() if i["permit_id"] == permit_id]


def designs_of_site(site_id):
    return [d for d in S["designs"].values() if d["site_id"] == site_id]


def contracts_of_site(site_id):
    return [m for m in S["maintenance_contracts"].values() if m["site_id"] == site_id]


def inspections_of_installation(installation_id):
    return [i for i in S["inspections"].values() if i["installation_id"] == installation_id]


def design_descends_from(design, ancestor_id):
    """Amendment-chain membership (PRD §3.3): True when `design` IS
    `ancestor_id` or reaches it by following `supersedes_design_id` links.

    The replacement-estimate rules of §3.9 require this reading: the final
    estimate is computed "against the flow of the design row pinned at permit
    issuance, which may differ from the provisional figure whenever the
    replacement plan was amended between triage and issuance" — reachable only
    when a permit pinning an AMENDMENT of the case's replacement design
    satisfies the remediation gate.
    """
    d = design
    seen = set()
    while d is not None and d["id"] not in seen:
        if d["id"] == ancestor_id:
            return True
        seen.add(d["id"])
        parent = d.get("supersedes_design_id")
        d = S["designs"].get(parent) if parent else None
    return False


def materials_of_installation(installation_id):
    return [m for m in S["material_verifications"].values()
            if m["installation_id"] == installation_id]


# ------------------------------------------------------------- calculations

def compute_sizing(site, soil_eval, bedroom_count, design_id):
    """§1.3 design_daily_flow_gpd / required_absorption_area_sqft /
    tank_capacity_gal / reserve_area_sqft. Called at creation and re-run at
    submit time (variance context may have changed)."""
    hw = bool(site["high_water_table"])

    # design daily flow — ALWAYS the book figure (150 gpd/bedroom).
    book_base = Decimal(bedroom_count) * Decimal(C.GPD_PER_BEDROOM)
    flow = book_base * Decimal(C.HIGH_WATER_SURCHARGE) if hw else book_base
    flow = flow.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    # absorption-area leg — variant B substitutes 120 gpd/bedroom when an
    # APPROVED AREA_REDUCTION variance exists for this design.
    leg_gpd = (C.GPD_PER_BEDROOM_REDUCED
               if has_approved_variance_for_design(design_id, "AREA_REDUCTION")
               else C.GPD_PER_BEDROOM)
    leg = Decimal(bedroom_count) * Decimal(leg_gpd)
    if hw:
        leg = leg * Decimal(C.HIGH_WATER_SURCHARGE)
    rate = Decimal(C.SOIL_APPLICATION_RATE[soil_eval["soil_class"]])
    area = leg / rate
    if int(soil_eval["limiting_layer_inches"]) < C.MIN_LIMITING_LAYER_INCHES:
        area = area * Decimal(C.SHALLOW_LAYER_MULTIPLIER)
    area_sqft = int(area.to_integral_value(rounding=ROUND_CEILING))  # ceil once

    # tank capacity — always book flow; catalog step-up (exact multiples stay).
    raw_tank = book_base * Decimal(C.TANK_RETENTION_DAYS)
    tank = next(s for s in C.TANK_CATALOG_SIZES if Decimal(s) >= raw_tank)

    reserve = int((Decimal(area_sqft) * Decimal(C.RESERVE_FRACTION))
                  .quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    return {
        "design_daily_flow_gpd": float(flow),
        "required_absorption_area_sqft": area_sqft,
        "tank_capacity_gal": int(tank),
        "reserve_area_sqft": reserve,
    }


def permit_expires_period(issued_period):
    """Inclusive 6-period window: issued + 6 - 1."""
    return issued_period + C.PERMIT_VALIDITY_PERIODS - 1


def prorate_fee_cents(annual_fee_cents, start_period, end_period):
    """round_half_up applied exactly once on the contract-level product."""
    coverage = end_period - start_period + 1
    product = (Decimal(annual_fee_cents) * Decimal(coverage)
               / Decimal(C.PERIODS_PER_YEAR))
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def science_is_stale(site, date_period):
    return (site["current_period_index"] - date_period) > C.SCIENCE_MAX_AGE_PERIODS


def material_ceiling_cents(design):
    return Decimal(design["required_absorption_area_sqft"]) * Decimal(
        C.MATERIAL_BUDGET_PER_SQFT_CENTS)


def verified_material_total_cents(installation_id):
    total = Decimal(0)
    for mv in materials_of_installation(installation_id):
        if mv["verified"]:
            total += Decimal(str(mv["quantity"])) * Decimal(mv["unit_cost_cents"])
    return total


def delivery_cost_cents(mv):
    return Decimal(str(mv["quantity"])) * Decimal(mv["unit_cost_cents"])


def replacement_estimate_cents(flow_gpd):
    return int((Decimal(str(flow_gpd)) * Decimal(C.REPLACEMENT_COST_PER_GPD_CENTS))
               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------- cascades

def supersede_science(site, collection, new_rec):
    """A fresh RECORDED science row supersedes the prior RECORDED one (hop 1);
    every DRAFT design pinning it is auto-WITHDRAWN (hop 2)."""
    pin_field = ("soil_evaluation_id" if collection == "soil_evaluations"
                 else "percolation_test_id")
    for rec in list(S[collection].values()):
        if (rec["site_id"] == site["id"] and rec["status"] == "RECORDED"
                and rec["id"] != new_rec["id"]):
            set_fields(rec, status="SUPERSEDED", superseded_by_id=new_rec["id"])
            for d in designs_of_site(site["id"]):
                if d["status"] == "DRAFT" and d[pin_field] == rec["id"]:
                    set_fields(d, status="WITHDRAWN")


def _force_installations_to(installations, target, eligible):
    for inst in installations:
        if inst["status"] in eligible:
            set_fields(inst, status=target)


def suspend_permit(permit):
    """ISSUED -> SUSPENDED; non-terminal installations -> FAILED_HOLD."""
    if permit["status"] != "ISSUED":
        return
    set_fields(permit, status="SUSPENDED")
    _force_installations_to(installations_of_permit(permit["id"]), "FAILED_HOLD",
                            C.INSTALLATION_NON_TERMINAL)


def revoke_permit_cascade(permit):
    """Non-terminal installations of a revoked permit -> ABANDONED."""
    _force_installations_to(installations_of_permit(permit["id"]), "ABANDONED",
                            C.INSTALLATION_NON_TERMINAL)


def approve_design(site, design):
    """SUBMITTED -> APPROVED; approval supersession cascades hop-by-hop."""
    set_fields(design, status="APPROVED")
    for other in designs_of_site(site["id"]):
        if other["id"] != design["id"] and other["status"] == "APPROVED":
            set_fields(other, status="SUPERSEDED")
            for permit in permits_of_site(site["id"]):
                if permit["design_id"] == other["id"] and permit["status"] == "ISSUED":
                    suspend_permit(permit)


def complete_installation(site, installation):
    """READY_FOR_FINAL -> COMPLETED: finalize permit, resolve replacement
    repair cases, record the as-built absorption area."""
    permit = S["permits"][installation["permit_id"]]
    design = S["designs"][permit["design_id"]]
    set_fields(installation,
               status="COMPLETED",
               completed_period=site["current_period_index"],
               final_absorption_area_sqft=design["required_absorption_area_sqft"])
    if permit["status"] == "ISSUED":
        set_fields(permit, status="FINALIZED")
    for case in list(S["repair_cases"].values()):
        if (case["site_id"] == site["id"] and case["status"] == "IN_REMEDIATION"
                and case["remedy"] == "REPLACEMENT"
                and case["replacement_design_id"] is not None
                and design_descends_from(design, case["replacement_design_id"])):
            set_fields(case, status="RESOLVED")
            # Final replacement estimate: flow of the design row pinned at
            # permit issuance x REPLACEMENT_COST_PER_GPD_CENTS.
            set_fields(design, provisional_estimate_cents=
                       replacement_estimate_cents(design["design_daily_flow_gpd"]))


def advance_clock(site, by_periods):
    """Deterministic logical clock advance with cascading temporal effects."""
    new_index = site["current_period_index"] + by_periods
    set_fields(site, current_period_index=new_index)

    # Auto-unfreeze when the clock moves past the freeze window.
    if site["status"] == "FROZEN" and new_index > site["seasonal_freeze_until"]:
        set_fields(site, status="OPEN", seasonal_freeze_until=-1)

    # Permit expiry: ISSUED -> EXPIRED; non-terminal installations -> FAILED_HOLD.
    for permit in permits_of_site(site["id"]):
        if permit["status"] == "ISSUED" and permit["expires_period"] < new_index:
            set_fields(permit, status="EXPIRED")
            _force_installations_to(installations_of_permit(permit["id"]),
                                    "FAILED_HOLD", C.INSTALLATION_NON_TERMINAL)

    # Contract aging: ACTIVE -> LAPSED, then LAPSED -> EXPIRED past the grace
    # window (both rules evaluated against the new index).
    for mc in contracts_of_site(site["id"]):
        if mc["status"] == "ACTIVE" and mc["end_period"] < new_index:
            set_fields(mc, status="LAPSED")
    for mc in contracts_of_site(site["id"]):
        if (mc["status"] == "LAPSED"
                and mc["end_period"] + C.LAPSE_GRACE_PERIODS < new_index):
            set_fields(mc, status="EXPIRED")

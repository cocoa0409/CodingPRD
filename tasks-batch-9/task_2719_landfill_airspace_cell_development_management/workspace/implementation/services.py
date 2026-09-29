"""Derivations, calculations and shared cascade helpers."""
from decimal import Decimal

from core import (D, q2, q4, ceil_int, err, rows, table, touch, clock,
                  date_part, month_part)

# ------------------------------------------------------------- constants -----
CERTIFIED_CELL_STATES = ("QA_CERTIFIED", "READY_FOR_WASTE", "ACTIVE", "FULL", "CLOSED")
CLOSURE_BASIS_STATES = ("QA_CERTIFIED", "READY_FOR_WASTE", "ACTIVE", "FULL")

LINER_TYPES = ("SINGLE_COMPOSITE", "DOUBLE_COMPOSITE", "GCL_ONLY")
COVER_MATERIALS = ("SOIL_6IN", "ALTERNATIVE_TARP", "ADC_FOAM", "AUTO_SHRED_FINES")
COVER_FACTOR = {
    "SOIL_6IN": Decimal("0.92"),
    "ALTERNATIVE_TARP": Decimal("1.00"),
    "ADC_FOAM": Decimal("0.97"),
    "AUTO_SHRED_FINES": Decimal("0.88"),
}
WASTE_STREAMS = ("MSW", "CD", "INDUSTRIAL_SPECIAL", "ASBESTOS_SPECIAL")
SPECIAL_STREAMS = ("INDUSTRIAL_SPECIAL", "ASBESTOS_SPECIAL")
LOAD_CHECK_RESULTS = ("PASS", "PROHIBITED_FOUND", "UNMANIFESTED")
INSTRUMENT_TYPES = ("TRUST_FUND", "SURETY_BOND", "LETTER_OF_CREDIT", "INSURANCE")
OPERATING_STATUSES = ("OPEN", "RESTRICTED_AIRSPACE", "SUSPENDED_NO_AIRSPACE",
                      "SUSPENDED_FINANCIAL", "CLOSED")

SEAM_FT_PER_DESTRUCTIVE_TEST = Decimal("500")
DEFECT_DENSITY_FREE_ALLOWANCE = Decimal("0.05")
DEFECT_PENALTY_SLOPE = Decimal("4")
DEFECT_PENALTY_CAP = Decimal("30.0")
QA_APPROVAL_MIN_SCORE = Decimal("85.0")
DENSITY_FLOOR = Decimal("0.55")
TARGET_DENSITY = Decimal("0.85")
FACE_LARGE_SF = Decimal("15000")
FACE_MEDIUM_SF = Decimal("8000")
CELL_FULL_FRACTION = Decimal("0.98")
SITE_LIFE_RESTRICT_YEARS = Decimal("2.0")
SURVEY_MIN_SPACING_DAYS = 90
SEM_EXCEEDANCE_PPM = Decimal("500")
SURCHARGE_TIER1_CEILING = Decimal("500.00")
SURCHARGE_TIER2_CEILING = Decimal("1200.00")
WELL_OXYGEN_CRITICAL_PCT = Decimal("12.0")
WELL_SPEC_METHANE_MIN = Decimal("45.0")
WELL_SPEC_OXYGEN_MAX = Decimal("5.0")
WELL_SPEC_VACUUM_MIN = Decimal("10.0")


# ------------------------------------------------------------- lookups -------
def cells_of(landfill_id):
    return [c for c in rows("cell") if c["landfill_id"] == landfill_id]


def landfill_of(landfill_id):
    return table("landfill")[landfill_id]


def cell_of(cell_id):
    return table("cell")[cell_id]


def day_of(day_id):
    return table("operating_day")[day_id]


def loads_of_day(day_id):
    return [l for l in rows("waste_load") if l["operating_day_id"] == day_id]


def days_of_cell(cell_id):
    return [d for d in rows("operating_day") if d["active_cell_id"] == cell_id]


def wells_of_cell(cell_id):
    return [w for w in rows("gas_well") if w["cell_id"] == cell_id]


def wells_of_landfill(landfill_id):
    ids = set(c["id"] for c in cells_of(landfill_id))
    return [w for w in rows("gas_well") if w["cell_id"] in ids]


def scans_of_landfill(landfill_id):
    return [s for s in rows("surface_emission_scan")
            if s["landfill_id"] == landfill_id]


def surveys_of_landfill(landfill_id):
    return [s for s in rows("aerial_survey") if s["landfill_id"] == landfill_id]


def approvals_of_landfill(landfill_id):
    return [a for a in rows("special_waste_approval")
            if a["landfill_id"] == landfill_id]


def estimates_of_landfill(landfill_id):
    return [e for e in rows("closure_cost_estimate")
            if e["landfill_id"] == landfill_id]


def agreements_of_landfill(landfill_id):
    return [h for h in rows("host_community_agreement")
            if h["landfill_id"] == landfill_id]


def shipments_of_agreement(agreement_id):
    return [s for s in rows("leachate_shipment")
            if s["treatment_agreement_id"] == agreement_id]


def agreement_of(shipment):
    return table("treatment_agreement")[shipment["treatment_agreement_id"]]


def landfill_of_day(day):
    return landfill_of(day["landfill_id"])


def landfill_of_cell(cell):
    return landfill_of(cell["landfill_id"])


def recorded_survey(landfill_id):
    for s in surveys_of_landfill(landfill_id):
        if s["status"] == "RECORDED":
            return s
    return None


def live_host_agreement(landfill_id):
    for h in agreements_of_landfill(landfill_id):
        if h["status"] in ("EXECUTED", "UNDER_AMENDMENT"):
            return h
    return None


# -------------------------------------------------------- calculations -------
def qa_conformance_score(seam_length_ft, destructive, passing, panels, defects):
    """Weighted liner conformance figure out of 100."""
    pass_rate = D(passing) / D(destructive)
    required = ceil_int(D(seam_length_ft) / SEAM_FT_PER_DESTRUCTIVE_TEST)
    coverage = D(destructive) / D(required)
    if coverage > Decimal("1.0"):
        coverage = Decimal("1.0")
    density = D(defects) / D(panels)
    if density <= DEFECT_DENSITY_FREE_ALLOWANCE:
        penalty = Decimal("0")
    else:
        penalty = q2(D(100) * (density - DEFECT_DENSITY_FREE_ALLOWANCE)
                     * DEFECT_PENALTY_SLOPE)
        if penalty > DEFECT_PENALTY_CAP:
            penalty = DEFECT_PENALTY_CAP
    score = D(100) * pass_rate * coverage - penalty
    if score < Decimal("0"):
        score = Decimal("0")
    if score > Decimal("100"):
        score = Decimal("100")
    return float(q2(score))


def face_penalty_factor(working_face_area_sf):
    area = D(working_face_area_sf)
    if area > FACE_LARGE_SF:
        return Decimal("0.90")
    if area > FACE_MEDIUM_SF:
        return Decimal("0.96")
    return Decimal("1.00")


def effective_density(planned_density, cover_material_type, working_face_area_sf):
    raw = (D(planned_density) * COVER_FACTOR[cover_material_type]
           * face_penalty_factor(working_face_area_sf))
    if raw < DENSITY_FLOOR:
        raw = DENSITY_FLOOR
    if raw > TARGET_DENSITY:
        raw = TARGET_DENSITY
    return q4(raw)


def day_consumption(tons_placed, density):
    """Consumes the already-rounded 4-decimal density."""
    if D(tons_placed) == 0:
        return q2(Decimal("0"))
    return q2(D(tons_placed) / D(density))


def remaining_life_projection(lf):
    survey = recorded_survey(lf["id"])
    if survey is not None and D(survey["measured_density_tons_per_cy"]) > 0:
        variant = "survey_based"
        remaining = D(survey["measured_remaining_airspace_cy"])
        remaining_out = survey["measured_remaining_airspace_cy"]
        density = D(survey["measured_density_tons_per_cy"])
        source = survey["id"]
    else:
        variant = "ledger_based"
        remaining = q2(D(lf["certified_airspace_cy"]) - D(lf["consumed_airspace_cy"]))
        remaining_out = float(remaining)
        density = D(lf["planned_density_tons_per_cy"])
        source = None
    basis = remaining if remaining > 0 else Decimal("0")
    years = q2(basis * density / D(lf["annual_tonnage_forecast"]))
    return {
        "landfill_id": lf["id"],
        "variant": variant,
        "remaining_airspace_cy": remaining_out,
        "density_tons_per_cy": float(density),
        "annual_tonnage_forecast": lf["annual_tonnage_forecast"],
        "remaining_life_years": float(years),
        "source_survey_id": source,
    }


def gate_charge_amount(manifest_tons, hca):
    gross = q2(D(manifest_tons) * D(hca["posted_tipping_fee_per_ton"]))
    host = q2(D(manifest_tons) * D(hca["host_fee_per_ton"]))
    return float(q2(gross + host))


def royalty_amount(certified_tons, cumulative_tons, hca):
    room = D(hca["tier1_monthly_tons"]) - D(cumulative_tons)
    if room < 0:
        room = Decimal("0")
    tier1 = D(certified_tons)
    if tier1 > room:
        tier1 = room
    tier2 = D(certified_tons) - tier1
    fee = D(hca["posted_tipping_fee_per_ton"])
    comp1 = q2(tier1 * fee * D(hca["royalty_tier1_pct"]))
    comp2 = q2(tier2 * fee * D(hca["royalty_tier2_pct"]))
    return float(q2(comp1 + comp2))


def final_charge_amount(certified_tons, royalty, hca):
    gross = q2(D(certified_tons) * D(hca["posted_tipping_fee_per_ton"]))
    host = q2(D(certified_tons) * D(hca["host_fee_per_ton"]))
    return float(q2(gross + host + D(royalty)))


def closure_cost_figures(lf, unit_cost, annual_cost, inflation_pct, years, funded):
    total = Decimal("0")
    for c in cells_of(lf["id"]):
        if c["status"] in CLOSURE_BASIS_STATES:
            total += q2(D(c["design_area_sf"]) * D(unit_cost))
    closure_total = q2(total)
    base = Decimal("1") + D(inflation_pct)
    pc = Decimal("0")
    for k in range(0, int(years)):
        pc += q2(D(annual_cost) * (base ** k))
    post_closure_total = q2(pc)
    required = q2(closure_total + post_closure_total)
    shortfall = required - D(funded)
    if shortfall < 0:
        shortfall = Decimal("0")
    return (float(closure_total), float(post_closure_total), float(required),
            float(q2(shortfall)))


def leachate_pre_surcharge(gallons, agreement):
    treatment_fee = q2(D(gallons) / D(1000) * D(agreement["treatment_rate_per_kgal"]))
    haul = q2(D(agreement["base_haul_fee"]))
    return treatment_fee, q2(treatment_fee + haul)


def surcharge_for(pre_surcharge_subtotal):
    if pre_surcharge_subtotal < SURCHARGE_TIER1_CEILING:
        return Decimal("0.00")
    if pre_surcharge_subtotal < SURCHARGE_TIER2_CEILING:
        return Decimal("0.06")
    return Decimal("0.10")


def leachate_invoice_total(shipment, agreement):
    pre = q2(D(shipment["treatment_fee"]) + q2(D(agreement["base_haul_fee"])))
    surcharge = q2(pre * D(shipment["surcharge_pct"]))
    return float(q2(pre + surcharge))


# --------------------------------------------------------- derivations -------
def cell_consumed_airspace(cell):
    total = Decimal("0")
    for d in days_of_cell(cell["id"]):
        if d["status"] == "CLOSED":
            total += D(d["airspace_consumed_cy"])
    return q2(total)


def sync_cell(cell):
    """Recomputes (never increments) the cell fill ledger. Returns True when a
    stored value actually moved."""
    consumed = cell_consumed_airspace(cell)
    fill = q2(D(100) * consumed / D(cell["design_airspace_cy"]))
    before = (cell["consumed_airspace_cy"], cell["fill_pct"])
    cell["consumed_airspace_cy"] = float(consumed)
    cell["fill_pct"] = float(fill)
    return before != (cell["consumed_airspace_cy"], cell["fill_pct"])


def sync_landfill(lf):
    """Recomputes the four pure derivations plus the projected remaining life."""
    cs = cells_of(lf["id"])
    certified = Decimal("0")
    consumed = Decimal("0")
    active = 0
    for c in cs:
        if c["status"] in CERTIFIED_CELL_STATES:
            certified += D(c["design_airspace_cy"])
        consumed += D(c["consumed_airspace_cy"])
        if c["status"] == "ACTIVE":
            active += 1
    certified = q2(certified)
    consumed = q2(consumed)
    before = (lf["certified_airspace_cy"], lf["consumed_airspace_cy"],
              lf["remaining_airspace_cy"], lf["active_cell_count"],
              lf["remaining_life_years"])
    lf["certified_airspace_cy"] = float(certified)
    lf["consumed_airspace_cy"] = float(consumed)
    lf["remaining_airspace_cy"] = float(q2(certified - consumed))
    lf["active_cell_count"] = active
    lf["remaining_life_years"] = remaining_life_projection(lf)["remaining_life_years"]
    after = (lf["certified_airspace_cy"], lf["consumed_airspace_cy"],
             lf["remaining_airspace_cy"], lf["active_cell_count"],
             lf["remaining_life_years"])
    return before != after


def sync_remaining_life(lf):
    before = lf["remaining_life_years"]
    lf["remaining_life_years"] = remaining_life_projection(lf)["remaining_life_years"]
    return before != lf["remaining_life_years"]


def approval_consumed_tons(approval):
    total = Decimal("0")
    for l in rows("waste_load"):
        if l.get("special_waste_approval_id") != approval["id"]:
            continue
        if l["screening_status"] != "CLEARED":
            continue
        if l["billing_status"] == "FINALIZED" and l["certified_net_tons"] is not None:
            total += D(l["certified_net_tons"])
        else:
            total += D(l["manifest_tons"])
    return q2(total)


def sync_approval(approval):
    value = float(approval_consumed_tons(approval))
    before = approval["consumed_tons"]
    approval["consumed_tons"] = value
    return before != value


def scheduled_gallons_today(agreement):
    today = date_part(clock())
    total = Decimal("0")
    for s in shipments_of_agreement(agreement["id"]):
        if s["status"] in ("SCHEDULED", "DISPATCHED", "ACCEPTED") \
                and date_part(s["window_start"]) == today:
            total += D(s["gallons"])
    return float(q2(total))


def gas_corrective_open(landfill_id):
    for s in scans_of_landfill(landfill_id):
        if s["status"] == "EXCEEDANCE_OPEN":
            return True
    for w in wells_of_landfill(landfill_id):
        if w["status"] == "TUNING_REQUIRED":
            return True
    return False


# ------------------------------------------------------ cascade helpers ------
def restore_suspended_approvals(lf):
    for a in approvals_of_landfill(lf["id"]):
        if a["status"] == "SUSPENDED":
            a["status"] = "APPROVED"
            touch(a)


def suspend_approved_approvals(lf):
    for a in approvals_of_landfill(lf["id"]):
        if a["status"] == "APPROVED":
            a["status"] = "SUSPENDED"
            touch(a)


def lift_no_airspace_suspension(lf):
    """Lifts SUSPENDED_NO_AIRSPACE back to OPEN and, caused by that posture
    change, restores every SUSPENDED special-waste approval."""
    if lf["operating_status"] == "SUSPENDED_NO_AIRSPACE":
        lf["operating_status"] = "OPEN"
        restore_suspended_approvals(lf)
        return True
    return False


def apply_life_restriction(lf):
    if D(lf["remaining_life_years"]) < SITE_LIFE_RESTRICT_YEARS \
            and lf["operating_status"] == "OPEN":
        lf["operating_status"] = "RESTRICTED_AIRSPACE"
        return True
    return False


def restore_gas_compliance(lf):
    """Returns the site to COMPLIANT once neither condition holds anywhere."""
    if not gas_corrective_open(lf["id"]) and lf["gas_collection_status"] != "COMPLIANT":
        lf["gas_collection_status"] = "COMPLIANT"
        return True
    return False


def load_order_key(load):
    day = day_of(load["operating_day_id"])
    return (day["operating_date"], load["created_at"], load["_seq"])


def cumulative_month_tons(load):
    """Certified tonnage already FINALIZED for the same landfill and calendar
    month that precedes this load in the pinned order."""
    day = day_of(load["operating_day_id"])
    landfill_id = day["landfill_id"]
    month = month_part(day["operating_date"])
    key = load_order_key(load)
    total = Decimal("0")
    for other in rows("waste_load"):
        if other["id"] == load["id"]:
            continue
        if other["billing_status"] != "FINALIZED":
            continue
        if other["screening_status"] != "CLEARED":
            continue
        other_day = day_of(other["operating_day_id"])
        if other_day["landfill_id"] != landfill_id:
            continue
        if month_part(other_day["operating_date"]) != month:
            continue
        if load_order_key(other) >= key:
            continue
        if other["certified_net_tons"] is None:
            continue
        total += D(other["certified_net_tons"])
    return total


def scope(user_id, landfill_id):
    """Rung 6: entity-backed roles may only write inside their own site."""
    if user_id != landfill_id:
        raise err("ERR_SITE_SCOPE_VIOLATION",
                  "This write addresses a resource outside the acting site.")

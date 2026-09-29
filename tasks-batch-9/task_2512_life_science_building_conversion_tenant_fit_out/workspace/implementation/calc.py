"""The eight normative calculation rules (PRD 2.7, 3.1-3.9).

Every figure here is a Decimal rounded half up exactly where the rule says it is
rounded and nowhere else.
"""
from decimal import Decimal

import constants
import db
import queries
from util import dec, q1, q2, q4

ZERO = Decimal("0.00")


# ============================================================ control areas / MAQ
def control_area_row(floor_number):
    """(control_areas_allowed, percent_maq) for a floor number -- exactly one band matches."""
    for low, high, areas, percent in constants.CONTROL_AREA_TABLE:
        if floor_number >= low and (high is None or floor_number <= high):
            return areas, percent
    last = constants.CONTROL_AREA_TABLE[-1]
    return last[2], last[3]


def control_areas_allowed(floor):
    return control_area_row(floor["floor_number"])[0]


def percent_maq(floor):
    return control_area_row(floor["floor_number"])[1]


def allowance_per_control_area_gal(floor, hazard_class, use_condition):
    areas, percent = control_area_row(floor["floor_number"])
    base = constants.MAQ_BASE_GAL[hazard_class]
    sprinkler = constants.SPRINKLER_MULTIPLIER[bool(floor["sprinklered"])]
    use_factor = constants.USE_FACTOR[use_condition]
    return q2(base * percent * sprinkler * use_factor)


def aggregate_allowance_gal(floor, per_control_area):
    areas, _percent = control_area_row(floor["floor_number"])
    return q2(dec(per_control_area) * areas)


def hazmat_utilization(floor, hazard_class, control_area_index):
    """PRD 3.8 floor-level code report; use_condition is fixed at CLOSED_SYSTEM_USE."""
    per_ca_allowance = allowance_per_control_area_gal(floor, hazard_class, "CLOSED_SYSTEM_USE")
    aggregate_allowance = aggregate_allowance_gal(floor, per_ca_allowance)

    per_ca_basis = ZERO
    aggregate_basis = ZERO
    for permit in db.permits.values():
        if permit["floor_id"] != floor["id"] or permit["hazard_class"] != hazard_class:
            continue
        if permit["status"] in constants.PER_CONTROL_AREA_STATUSES \
                and permit["control_area_index"] == control_area_index:
            per_ca_basis = per_ca_basis + permit["quantity_gal"]
        if permit["status"] in constants.AGGREGATE_FLOOR_STATUSES:
            aggregate_basis = aggregate_basis + permit["quantity_gal"]

    return {
        "floor_id": floor["id"],
        "hazard_class": hazard_class,
        "control_area_index": control_area_index,
        "control_areas_allowed": control_area_row(floor["floor_number"])[0],
        "allowance_per_control_area_gal": per_ca_allowance,
        "aggregate_allowance_gal": aggregate_allowance,
        "per_control_area_basis_gal": q2(per_ca_basis),
        "aggregate_basis_gal": q2(aggregate_basis),
        "per_control_area_utilization_pct": q2(dec(100) * per_ca_basis / per_ca_allowance),
        "aggregate_utilization_pct": q2(dec(100) * aggregate_basis / aggregate_allowance),
    }


# ================================================================ suitability
MISSING = object()


def _effective(measured, published, basis):
    if measured is not None:
        return measured
    if basis == "SCREENING":
        return published
    return None


def score_assessment(assessment, building):
    """PRD 3.2 steps 1-5. Returns the frozen derived block."""
    basis = assessment["assessment_basis"]
    height = _effective(assessment["measured_floor_to_floor_ft"],
                        building["published_floor_to_floor_ft"], basis)
    live_load = _effective(assessment["measured_live_load_psf"],
                           building["published_live_load_psf"], basis)
    vibration = _effective(assessment["measured_vibration_class"],
                           building["published_vibration_class"], basis)

    if height is None:
        height_credit = constants.CREDIT_FAIL
    elif dec(height) >= constants.HEIGHT_PASS_FT:
        height_credit = constants.CREDIT_PASS
    elif dec(height) >= constants.HEIGHT_MARGINAL_FT:
        height_credit = constants.CREDIT_MARGINAL
    else:
        height_credit = constants.CREDIT_FAIL

    if live_load is None:
        structural_credit = constants.CREDIT_FAIL
    elif dec(live_load) >= constants.LIVE_LOAD_PASS_PSF:
        structural_credit = constants.CREDIT_PASS
    elif dec(live_load) >= constants.LIVE_LOAD_MARGINAL_PSF:
        structural_credit = constants.CREDIT_MARGINAL
    else:
        structural_credit = constants.CREDIT_FAIL

    required_rank = constants.VIBRATION_RANK[assessment["required_vibration_class"]]
    if vibration is None:
        vibration_credit = constants.CREDIT_FAIL
    else:
        rank = constants.VIBRATION_RANK[vibration]
        if rank >= required_rank:
            vibration_credit = constants.CREDIT_PASS
        elif rank == required_rank - 1:
            vibration_credit = constants.CREDIT_MARGINAL
        else:
            vibration_credit = constants.CREDIT_FAIL

    exhaust_ratio = dec(building["exhaust_riser_capacity_cfm"]) / dec(assessment["required_exhaust_cfm"])
    power_ratio = dec(building["emergency_power_capacity_kw"]) / dec(assessment["required_power_kw"])
    headroom = q4(min(exhaust_ratio, power_ratio))
    if headroom >= constants.UTILITY_PASS_RATIO:
        utility_credit = constants.CREDIT_PASS
    elif headroom >= constants.UTILITY_MARGINAL_RATIO:
        utility_credit = constants.CREDIT_MARGINAL
    else:
        utility_credit = constants.CREDIT_FAIL

    raw = q1(constants.WEIGHT_HEIGHT * height_credit
             + constants.WEIGHT_STRUCTURAL * structural_credit
             + constants.WEIGHT_VIBRATION * vibration_credit
             + constants.WEIGHT_UTILITY * utility_credit)

    lowest = min(height_credit, structural_credit, vibration_credit, utility_credit)
    hard_fail_capped = bool(lowest == 0 and raw > constants.HARD_FAIL_SCORE_CAP)
    score = constants.HARD_FAIL_SCORE_CAP if hard_fail_capped else raw

    if score >= constants.VERDICT_SUITABLE_MIN:
        verdict = "SUITABLE"
    elif score >= constants.VERDICT_CONDITIONAL_MIN:
        verdict = "SUITABLE_WITH_CONVERSION"
    else:
        verdict = "UNSUITABLE"

    return {
        "height_credit": height_credit,
        "structural_credit": structural_credit,
        "vibration_credit": vibration_credit,
        "utility_credit": utility_credit,
        "utility_headroom_ratio": headroom,
        "suitability_score": score,
        "hard_fail_capped": hard_fail_capped,
        "verdict": verdict,
    }


# ================================================================ TI economics
def volume_credit_psf(provisional):
    for floor_usd, credit in constants.VOLUME_CREDIT_TIERS:
        if provisional >= floor_usd:
            return credit
    return Decimal("0.00")


def ti_economics(tenant, premises_floor, rentable_sf, accepted_allowance_psf):
    """PRD 3.3 steps 1-7; the tier is selected from the PRE-credit authorisation."""
    premium = constants.LAB_PREMIUM_BY_RESEARCH_TYPE[tenant["research_type"]]
    if premises_floor["floor_number"] >= constants.HIGH_FLOOR_MIN_FLOOR_NUMBER:
        premium = premium + constants.HIGH_FLOOR_UPLIFT_PSF
    lab_premium_psf_applied = q2(premium)
    subtotal_psf = q2(dec(accepted_allowance_psf) + lab_premium_psf_applied)
    provisional = q2(subtotal_psf * rentable_sf)
    credit = volume_credit_psf(provisional)
    final_psf = q2(subtotal_psf - credit)
    authorized = q2(final_psf * rentable_sf)
    escrow_required = min(q2(constants.RESTORATION_ESCROW_PCT * authorized),
                         constants.RESTORATION_ESCROW_CAP_USD)
    return {
        "lab_premium_psf_applied": lab_premium_psf_applied,
        "provisional_authorized_ti_usd": provisional,
        "volume_credit_psf": q2(credit),
        "final_allowance_psf": final_psf,
        "ti_authorized_usd": authorized,
        "restoration_escrow_required_usd": q2(escrow_required),
    }


def phase_ti_eligible(phase):
    share = constants.TI_ELIGIBLE_SHARE[phase["premium_class"]]
    multiplier = constants.TI_PREMIUM_MULTIPLIER[phase["premium_class"]]
    return q2(dec(phase["hard_cost_usd"]) * share * multiplier)


def draw_cap_usd(lease):
    return q2(constants.DRAW_CAP_PCT * dec(lease["ti_authorized_usd"]))


def draw_allocation(lease, requested_usd):
    """PRD 3.4: per-line half-up rounding, then the signed residual to the largest line."""
    disbursed = min(dec(requested_usd), draw_cap_usd(lease), dec(lease["ti_committed_usd"]))
    disbursed = q2(disbursed)

    eligible = [p for p in queries.phases_of_lease(lease["id"])
                if p["status"] == "COMPLETE" and p["ti_committed_usd"] > p["ti_disbursed_usd"]]
    if not eligible:
        return disbursed, {}

    total_committed = sum((p["ti_committed_usd"] for p in eligible), Decimal("0"))
    allocations = {}
    for phase in eligible:
        share = disbursed * dec(phase["ti_committed_usd"]) / total_committed
        allocations[phase["id"]] = q2(share)

    residual = disbursed - sum(allocations.values(), Decimal("0"))
    if residual != 0:
        target = eligible[0]
        for phase in eligible[1:]:
            if phase["ti_committed_usd"] > target["ti_committed_usd"]:
                target = phase
        allocations[target["id"]] = q2(allocations[target["id"]] + residual)
    return disbursed, allocations


# ========================================================== base-building pools
def building_pools(building):
    items = queries.scope_items_of(building["id"])
    exhaust_total = dec(building["exhaust_riser_capacity_cfm"])
    power_total = dec(building["emergency_power_capacity_kw"])
    for item in items:
        if item["status"] != "COMPLETE":
            continue
        if item["discipline"] == "LAB_EXHAUST":
            exhaust_total = exhaust_total + dec(item["capacity_delta_cfm"])
        elif item["discipline"] == "EMERGENCY_POWER":
            power_total = power_total + dec(item["capacity_delta_kw"])

    exhaust_reserved = Decimal("0")
    exhaust_committed = Decimal("0")
    power_reserved = Decimal("0")
    power_committed = Decimal("0")
    for reservation in db.reservations.values():
        if reservation["building_id"] != building["id"]:
            continue
        if reservation["status"] == "RESERVED":
            exhaust_reserved = exhaust_reserved + dec(reservation["exhaust_cfm"])
            power_reserved = power_reserved + dec(reservation["power_kw"])
        elif reservation["status"] == "COMMITTED":
            exhaust_committed = exhaust_committed + dec(reservation["exhaust_cfm"])
            power_committed = power_committed + dec(reservation["power_kw"])

    exhaust_total = q2(exhaust_total)
    power_total = q2(power_total)
    exhaust_reserved = q2(exhaust_reserved)
    exhaust_committed = q2(exhaust_committed)
    power_reserved = q2(power_reserved)
    power_committed = q2(power_committed)
    return {
        "exhaust_capacity_total_cfm": exhaust_total,
        "exhaust_reserved_cfm": exhaust_reserved,
        "exhaust_committed_cfm": exhaust_committed,
        "exhaust_available_cfm": q2(exhaust_total - exhaust_reserved - exhaust_committed),
        "power_capacity_total_kw": power_total,
        "power_reserved_kw": power_reserved,
        "power_committed_kw": power_committed,
        "power_available_kw": q2(power_total - power_reserved - power_committed),
    }


def scope_discipline_lists(building):
    items = queries.scope_items_of(building["id"])
    covered = sorted({i["discipline"] for i in items})
    complete = sorted({i["discipline"] for i in items if i["status"] == "COMPLETE"})
    return covered, complete


# ============================================================ restoration value
def restoration_liability(lease):
    phase_component = Decimal("0")
    for phase in queries.phases_of_lease(lease["id"]):
        if phase["status"] != "COMPLETE":
            continue
        if phase["premium_class"] in constants.RESTORATION_EXEMPT_PREMIUM_CLASSES:
            continue
        phase_component = phase_component + dec(phase["restoration_cost_usd"])

    permit_component = Decimal("0")
    for permit in queries.permits_of_lease(lease["id"]):
        if permit["status"] not in constants.PERMIT_DECOMMISSION_STATUSES:
            continue
        permit_component = permit_component + constants.PERMIT_DECOMMISSION_FEE_USD \
            + constants.PERMIT_DECOMMISSION_PER_GALLON_USD * dec(permit["quantity_gal"])

    return q2(phase_component + permit_component)


# ================================================================ project reads
def delivery_risk(project):
    for phase in queries.phases_of_project(project["id"]):
        if phase["status"] in ("VIBRATION_HOLD", "BLOCKED"):
            return "AT_RISK"
    return "ON_TRACK"


def passed_script_count(project):
    required = set(project["required_commissioning_scripts"])
    passed = {r["script_type"] for r in queries.records_of_project(project["id"])
              if r["status"] == "PASSED" and r["script_type"] in required}
    return len(passed)

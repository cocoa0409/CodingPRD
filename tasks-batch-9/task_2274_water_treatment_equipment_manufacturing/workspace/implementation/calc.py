"""Deterministic calculations (PRD section 3 / SCAFFOLD calculations).

Every function here is pure with respect to the store except where noted: it
reads rows and returns numbers, leaving persistence and version bumps to the
callers in :mod:`domain` and the route modules.
"""
from decimal import Decimal

import clock
import constants as C
import db
from errors import fail
from util import (D, ceil_int, dt_of, rhu_int, round_half_up,
                  whole_30_day_months, whole_days)


# ------------------------------------------------- 1. governing influent ----

def governing_influent_profile_id(project, raise_when_draft=True):
    """Pick the governing profile: highest accepted design flow, earliest wins."""
    candidates = [
        p for p in db.all_rows("influent_profiles")
        if p["project_id"] == project["id"] and p["qa_status"] == "ACCEPTED"
    ]
    if not candidates:
        if raise_when_draft and project["status"] == "DRAFT":
            fail("ERR_NO_ACCEPTED_INFLUENT_PROFILE",
                 "project has no ACCEPTED influent profile")
        return None
    best = None
    for row in candidates:
        flow = round_half_up(row["design_flow_mgd"], 3)
        key = (-flow, dt_of(row["created_at"]), row["_seq"])
        if best is None or key < best[0]:
            best = (key, row)
    return best[1]["id"]


# ------------------------------------------------------ 2. stage design flow --

def stage_design_flow(role, profile):
    flow = D(profile["design_flow_mgd"])
    if role in C.PEAK_ROLES:
        flow = flow * D(profile["peak_factor"])
    return round_half_up(flow, 3)


# ------------------------------------------------- 3. process train selection --

def required_roles(project):
    """Roles implied by the project's ACTIVE objectives, in canonical order."""
    roles = set()
    for obj in db.all_rows("treatment_objectives"):
        if obj["project_id"] != project["id"] or obj["status"] != "ACTIVE":
            continue
        roles.add(C.OBJECTIVE_ROLE_MAP[obj["parameter"]])
    return [r for r in C.STAGE_ORDER if r in roles]


def technology_candidates(role, profile, flow):
    pool = []
    for tech in db.all_rows("process_technologies"):
        if tech["role"] != role:
            continue
        if tech["status"] != "ACTIVE":
            continue
        if D(tech["max_feed_turbidity_ntu"]) < D(profile["turbidity_ntu"]):
            continue
        if D(tech["max_feed_tds_mg_l"]) < D(profile["tds_mg_l"]):
            continue
        if D(tech["min_design_flow_mgd"]) > flow:
            continue
        if D(tech["max_design_flow_mgd"]) < flow:
            continue
        pool.append(tech)
    return pool


def technology_cost_terms(tech, flow, allowance_sf):
    capex = ceil_int(D(tech["unit_capex_cents_per_mgd"]) * flow)
    annual_energy = ceil_int(
        D(tech["energy_kwh_per_mg"]) * flow * D(365) * C.ENERGY_COST_CENTS_PER_KWH
    )
    energy = C.LIFECYCLE_YEARS * annual_energy
    footprint_sf = round_half_up(D(tech["footprint_sf_per_mgd"]) * flow, 3)
    excess = footprint_sf - D(allowance_sf)
    if excess < 0:
        excess = D(0)
    penalty = ceil_int(excess * C.FOOTPRINT_PENALTY_CENTS_PER_SF)
    return {
        "equipment_base_cost_cents": capex,
        "energy_cents": energy,
        "footprint_penalty_cents": penalty,
        "evaluated_cost_cents": capex + energy + penalty,
    }


def select_technology(role, project, profile):
    """Lowest evaluated cost, then smallest footprint rate, then oldest row."""
    flow = stage_design_flow(role, profile)
    pool = technology_candidates(role, profile, flow)
    if not pool:
        fail("ERR_NO_ELIGIBLE_TECHNOLOGY",
             "no ACTIVE technology satisfies the %s stage duty" % role)
    best = None
    for tech in pool:
        terms = technology_cost_terms(
            tech, flow, project["footprint_allowance_sf_per_stage"])
        key = (
            terms["evaluated_cost_cents"],
            D(tech["footprint_sf_per_mgd"]),
            dt_of(tech["created_at"]),
            tech["_seq"],
        )
        if best is None or key < best[0]:
            best = (key, tech, terms)
    return {"role": role, "flow": flow, "technology": best[1], "terms": best[2]}


# ------------------------------------------------- 4. equipment package cost --

def pressure_factor(design_pressure_psig):
    return D(1) + C.PRESSURE_FACTOR_PER_100_PSIG * (D(design_pressure_psig) / D(100))


def stamp_factor(code_stamp_required):
    return D(1) + C.CODE_STAMP_SURCHARGE_PCT[code_stamp_required]


def budgetary_cost_cents(stage, package):
    base = D(stage["equipment_base_cost_cents"])
    return rhu_int(
        base
        * D(1)
        * pressure_factor(package["design_pressure_psig"])
        * stamp_factor(package["code_stamp_required"])
    )


def escalation_factor(stage):
    months = whole_30_day_months(dt_of(stage["created_at"]), clock.now())
    return D(1) + C.ESCALATION_PCT_PER_MONTH * D(months)


def firm_cost_cents(stage, package, material):
    base = D(stage["equipment_base_cost_cents"])
    return rhu_int(
        base
        * D(material["cost_index"])
        * pressure_factor(package["design_pressure_psig"])
        * stamp_factor(package["code_stamp_required"])
        * escalation_factor(stage)
    )


def cost_variance(firm, budgetary):
    if not budgetary:
        return D(0), False
    pct = round_half_up((D(firm) - D(budgetary)) / D(budgetary), 4)
    return pct, pct > C.VARIANCE_FLAG_THRESHOLD


# ------------------------------------------------ 5. or-equal compliance ------

def deviation_penalty_points(deviation):
    weight = C.DEVIATION_WEIGHTS[deviation["severity"]]
    multiplier = C.DISPOSITION_MULTIPLIER[deviation["disposition"]]
    return round_half_up(weight * multiplier, 2)


def submittal_deviations(submittal_id):
    return [
        d for d in db.all_rows("spec_deviations")
        if d["or_equal_submittal_id"] == submittal_id
    ]


def or_equal_compliance(submittal_id):
    total = D(0)
    open_fundamental = 0
    for dev in submittal_deviations(submittal_id):
        total += D(dev["weighted_penalty_points"])
        if dev["severity"] == "FUNDAMENTAL" and dev["disposition"] in ("PENDING", "REJECTED"):
            open_fundamental += 1
    penalty = round_half_up(total, 2)
    score = round_half_up(D(100) - penalty, 2)
    if score < 0:
        score = D("0.00")
    return score, open_fundamental


# ------------------------------------------------------ 6. bid evaluation -----

def bid_lines(project):
    stages = {
        s["id"]: s for s in db.all_rows("treatment_stages")
        if s["project_id"] == project["id"] and s["status"] != "SUPERSEDED"
    }
    lines = []
    for pkg in db.all_rows("equipment_packages"):
        stage = stages.get(pkg["treatment_stage_id"])
        if stage is None:
            continue
        if pkg["status"] not in C.BID_ELIGIBLE_PACKAGE_STATUSES:
            continue
        lines.append((stage, pkg))
    lines.sort(key=lambda pair: (pair[0]["stage_index"], pair[1]["_seq"]))
    return lines


def bond_rate(base_bid_amount_cents):
    for ceiling, rate in C.BOND_RATE_TIERS:
        if ceiling is None or base_bid_amount_cents <= ceiling:
            return rate
    return C.BOND_RATE_TIERS[-1][1]


def bid_evaluated_price(project):
    base = 0
    for _stage, pkg in bid_lines(project):
        base += rhu_int(D(pkg["firm_cost_cents"]) * (D(1) + C.OVERHEAD_PCT))
    bond = rhu_int(D(base) * bond_rate(base))
    contingency = rhu_int(
        D(base) * C.CONTINGENCY_PCT_BY_POSTURE[project["delivery_posture"]])
    return {
        "base_bid_amount_cents": base,
        "bond_premium_cents": bond,
        "contingency_cents": contingency,
        "evaluated_bid_price_cents": base + bond + contingency,
    }


def margin_ok(offered_price_cents, evaluated_bid_price_cents):
    """offered >= evaluated * 1.08, evaluated with integer arithmetic."""
    return D(offered_price_cents) * D(10000) >= D(evaluated_bid_price_cents) * D(10800)


# --------------------------------------------------------- 7. fat readiness ---

def fat_readiness(skid, package):
    if skid["mechanical_status"] == "REWORK":
        return "BLOCKED"
    if (skid["mechanical_status"] == "MECH_COMPLETE"
            and skid["controls_status"] == "CONTROLS_COMPLETE"
            and package["status"] == "RELEASED_FOR_FAB"):
        return "READY"
    return "NOT_READY"


def witnessed_result(requested, punchlist_item_count):
    if requested == "PASS" and punchlist_item_count > C.MAX_PASS_PUNCHLIST_ITEMS:
        return "CONDITIONAL"
    return {"PASS": "PASSED", "FAIL": "FAILED", "CONDITIONAL": "CONDITIONAL"}[requested]


# ---------------------------------------------------- 8. test bay ledger ------

def footprint_minutes(footprint_sf, duration_minutes):
    return round_half_up(D(footprint_sf) * D(duration_minutes), 2)


def overlapping_runs(bay, new_start, new_end, exclude_skid_id=None):
    """SCHEDULED runs in the bay whose buffered windows touch the new one."""
    from datetime import timedelta
    buffer = timedelta(minutes=int(bay["changeover_buffer_minutes"]))
    hits = []
    for run in db.all_rows("fat_runs"):
        if run["test_bay_id"] != bay["id"] or run["status"] != "SCHEDULED":
            continue
        if exclude_skid_id is not None and run["skid_id"] == exclude_skid_id:
            continue
        start = dt_of(run["scheduled_start_at"])
        end = dt_of(run["scheduled_end_at"])
        if new_start < end + buffer and start < new_end + buffer:
            hits.append(run)
    return hits


# ------------------------------------------------- 9. demo window occupancy ---

def conflicting_demos(skid_id, new_start, new_end):
    hits = []
    for demo in db.all_rows("performance_demos"):
        if demo["skid_id"] != skid_id or demo["result"] != "PENDING":
            continue
        start = dt_of(demo["window_start_at"])
        end = dt_of(demo["window_end_at"])
        if new_start <= end and start <= new_end:
            hits.append(demo)
    return hits


# ------------------------------------------- 10. performance guarantee --------

def active_objectives(project_id):
    rows = [
        o for o in db.all_rows("treatment_objectives")
        if o["project_id"] == project_id and o["status"] == "ACTIVE"
    ]
    rows.sort(key=lambda o: (o["parameter"], dt_of(o["created_at"]), o["_seq"]))
    return rows


def evaluate_guarantee(project_id, readings):
    objectives = active_objectives(project_id)
    if not objectives:
        fail("ERR_NO_TREATMENT_OBJECTIVES", "project has no ACTIVE treatment objectives")
    evaluation = []
    min_margin = None
    all_passed = True
    for obj in objectives:
        samples = [D(r["measured_value"]) for r in readings
                   if r["parameter"] == obj["parameter"]]
        if not samples:
            fail("ERR_DEMO_READING_MISSING",
                 "no reading supplied for objective %s" % obj["parameter"])
        if obj["basis"] == "MAX_DAY":
            compared = round_half_up(max(samples), 3)
        else:
            total = sum(samples, D(0))
            compared = round_half_up(total / D(len(samples)), 3)
        limit = D(obj["limit_value"])
        passed = compared <= limit
        margin = round_half_up((limit - compared) / limit * D(100), 2)
        if not passed:
            all_passed = False
        if min_margin is None or margin < min_margin:
            min_margin = margin
        evaluation.append({
            "parameter": obj["parameter"],
            "basis": obj["basis"],
            "limit_value": limit,
            "compared_value": compared,
            "margin_pct": margin,
            "passed": passed,
        })
    return evaluation, min_margin, all_passed


def demo_result(certification, all_passed, min_margin_pct):
    if certification == "FAIL" or not all_passed:
        return "FAILED"
    if min_margin_pct is not None and D(min_margin_pct) >= C.GUARANTEE_MARGIN_PCT:
        return "PASSED"
    return "CONDITIONAL_PASS"


# ----------------------------------------------- 11. liquidated damages -------

def liquidated_damages_cents(project):
    deadline = dt_of(project["guarantee_deadline_at"])
    ld_days = whole_days(deadline, clock.now())
    contract = D(project["contract_amount_cents"])
    daily = rhu_int(contract * C.LD_RATE_PER_DAY)
    cap = rhu_int(contract * C.LD_CAP_PCT)
    return min(daily * ld_days, cap)


# ------------------------------------------------ 12. service reserve ---------

def draw_amounts(agreement, draw_type, quantity, catalog_unit_cost_cents,
                 invoiced_unit_cost_cents):
    qty = D(quantity)
    accrual = rhu_int(qty * D(catalog_unit_cost_cents) * (D(1) + C.CONSUMABLE_MARKUP_PCT))
    warranty_credit = 0
    if draw_type == "MEMBRANE_REPLACEMENT":
        installed = dt_of(agreement["membrane_installed_at"])
        months_in_service = whole_30_day_months(installed, clock.now())
        months_remaining = C.MEMBRANE_WARRANTY_MONTHS - months_in_service
        if months_remaining < 0:
            months_remaining = 0
        warranty_credit = rhu_int(
            qty * D(invoiced_unit_cost_cents)
            * C.WARRANTY_CREDIT_PCT_PER_MONTH_REMAINING * D(months_remaining))
    settled = rhu_int(qty * D(invoiced_unit_cost_cents) * (D(1) + C.FREIGHT_PCT)) \
        - warranty_credit
    return accrual, settled, warranty_credit


def agreement_draws(agreement_id):
    return [d for d in db.all_rows("consumable_draws")
            if d["service_agreement_id"] == agreement_id]


def recompute_reserve(agreement):
    accrual_total = 0
    settled_total = 0
    for draw in agreement_draws(agreement["id"]):
        accrual_total += int(draw["accrual_amount_cents"])
        settled_total += int(draw["settled_amount_cents"])
    agreement["reserve_committed_accrual_cents"] = accrual_total
    agreement["reserve_committed_settled_cents"] = settled_total
    agreement["settlement_variance_cents"] = settled_total - accrual_total
    if agreement["status"] == "PENDING_ACTIVATION":
        agreement["reserve_available_cents"] = 0
    else:
        agreement["reserve_available_cents"] = (
            int(agreement["reserve_funded_cents"]) - accrual_total)
    return agreement


# ------------------------------------------------- 15. delivery posture -------

def project_packages(project_id, include_superseded=False):
    stages = {
        s["id"]: s for s in db.all_rows("treatment_stages")
        if s["project_id"] == project_id
        and (include_superseded or s["status"] != "SUPERSEDED")
    }
    return [(stages[p["treatment_stage_id"]], p)
            for p in db.all_rows("equipment_packages")
            if p["treatment_stage_id"] in stages]


def delivery_posture(project):
    pairs = project_packages(project["id"])
    packages = [p for _s, p in pairs]
    if any(p["status"] == "REWORK_HOLD" for p in packages):
        return "HELD"
    if any(p["variance_flag"] for p in packages):
        return "AT_RISK"
    package_ids = {p["id"] for p in packages}
    skid_ids = {s["id"] for s in db.all_rows("skids")
                if s["equipment_package_id"] in package_ids}
    for run in db.all_rows("fat_runs"):
        if run["skid_id"] in skid_ids and run["status"] in ("FAILED", "CONDITIONAL"):
            return "AT_RISK"
    for demo in db.all_rows("performance_demos"):
        if demo["project_id"] == project["id"] and demo["result"] in (
                "FAILED", "CONDITIONAL_PASS"):
            return "AT_RISK"
    return "ON_TRACK"

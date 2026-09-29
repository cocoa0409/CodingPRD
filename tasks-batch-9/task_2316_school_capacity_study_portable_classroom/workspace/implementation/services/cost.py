"""Calculations relocation_cost_estimate and alternative_cost_comparison."""

import constants as C
from db import db
from services.numbers import D, cents
from validation import parse_date_string


def inside_summer_window(start_text, end_text):
    """Both dates in the same calendar year, start >= 06-15, end <= 08-15."""
    start = parse_date_string(start_text)
    end = parse_date_string(end_text)
    if start is None or end is None:
        return False
    if start.year != end.year:
        return False
    if (start.month, start.day) < C.SUMMER_WINDOW_START:
        return False
    if (end.month, end.day) > C.SUMMER_WINDOW_END:
        return False
    return True


def relocation_estimate(req):
    """Seven ordered steps; two rounding points only (PRD 3.6)."""
    unit = db.units.get(req.get("portable_unit_id")) if req.get("portable_unit_id") else None
    site = db.sites.get(req.get("placement_site_id"))
    in_summer = inside_summer_window(
        req.get("requested_window_start"), req.get("requested_window_end")
    )
    off_summer_applied = not in_summer

    if unit is None or site is None:
        return {
            "mobilisation_cents": 0,
            "site_work_cents": 0,
            "rehab_cents": 0,
            "permit_fee_cents": 0,
            "direct_cost_cents": 0,
            "contingency_cents": 0,
            "off_summer_applied": off_summer_applied,
            "estimated_relocation_cost_cents": 0,
        }

    dims = C.UNIT_DIMS[unit["size_class"]]

    # step 1 - mobilisation
    mobilisation = D(C.MOVE_BASE_CENTS[unit["size_class"]]) + D(
        C.HAUL_RATE_CENTS_PER_MILE
    ) * D(req["haul_miles"])

    # step 2 - off-summer escalation, on mobilisation alone, rounded here
    if off_summer_applied:
        mobilisation = D(cents(mobilisation * C.OFF_SUMMER_MULTIPLIER))
    mobilisation_cents = int(mobilisation)

    # step 3 - site work, conditional on the actual unit/pad pair
    needs_electrical = D(site["electrical_drop_available_kw"]) < D(dims["service_kw"])
    needs_sewer_work = dims["needs_sewer"] and not site["sewer_connection_available"]
    needs_ada = (not unit["ada_ramp_installed"]) or (
        not site["ada_path_of_travel_compliant"]
    )
    site_work_cents = (
        (C.ELECTRICAL_UPGRADE_CENTS if needs_electrical else 0)
        + (C.SEWER_HOOKUP_CENTS if needs_sewer_work else 0)
        + (C.ADA_RETROFIT_CENTS if needs_ada else 0)
    )

    # step 4 - rehab keyed on condition grade
    rehab_cents = C.REHAB_CENTS_BY_GRADE.get(unit["condition_grade"], 0)

    # step 5 - permit fees over the required permit set
    permit_count = 3 + (1 if needs_sewer_work else 0) + (1 if needs_ada else 0)
    permit_fee_cents = C.PERMIT_FEE_CENTS_PER_TYPE * permit_count

    # steps 6/7 - direct cost then clamped contingency
    direct = mobilisation_cents + site_work_cents + rehab_cents + permit_fee_cents
    contingency = max(
        C.CONTINGENCY_FLOOR_CENTS,
        min(C.CONTINGENCY_CAP_CENTS, cents(C.CONTINGENCY_PCT * D(direct))),
    )
    return {
        "mobilisation_cents": mobilisation_cents,
        "site_work_cents": site_work_cents,
        "rehab_cents": rehab_cents,
        "permit_fee_cents": permit_fee_cents,
        "direct_cost_cents": direct,
        "contingency_cents": contingency,
        "off_summer_applied": off_summer_applied,
        "estimated_relocation_cost_cents": direct + contingency,
    }


def required_permit_types(unit, site):
    types = list(C.BASELINE_PERMIT_TYPES)
    dims = C.UNIT_DIMS[unit["size_class"]]
    if dims["needs_sewer"] and not site["sewer_connection_available"]:
        types.append("PLUMBING")
    if (not unit["ada_ramp_installed"]) or (not site["ada_path_of_travel_compliant"]):
        types.append("ADA_ACCESS")
    return types


def soft_cost_pct(direct_cents):
    if direct_cents < C.SOFT_COST_TIER_BREAKS_CENTS[0]:
        return C.SOFT_COST_PCTS[0]
    if direct_cents < C.SOFT_COST_TIER_BREAKS_CENTS[1]:
        return C.SOFT_COST_PCTS[1]
    return C.SOFT_COST_PCTS[2]


def total_program_cost(direct_cents):
    """Tier from direct, soft from direct, total last (never circular)."""
    pct = soft_cost_pct(direct_cents)
    soft = cents(pct * D(direct_cents))
    return soft, direct_cents + soft


def alternatives(req, estimate_cents, basis):
    study = db.studies.get(req.get("capacity_study_id"))
    school = db.schools.get(req.get("school_id"))
    unit = db.units.get(req.get("portable_unit_id")) if req.get("portable_unit_id") else None

    deficit = study["seat_deficit"] if study else 0
    units = study["required_portable_count"] if study else 0
    removal = C.REMOVAL_CENTS_BY_SIZE[unit["size_class"]] if unit else 0

    if basis == "IMMEDIATE_CAPITAL":
        relocation_direct = units * estimate_cents
    else:
        relocation_direct = units * (
            estimate_cents
            + C.ANNUAL_PORTABLE_OM_CENTS * C.RELIANCE_HORIZON_YEARS
            + removal
        )

    boundary_direct = (
        C.BOUNDARY_STUDY_FIXED_CENTS
        + C.BOUNDARY_TRANSPORT_CENTS_PER_SEAT_PER_YEAR * deficit * C.BOUNDARY_HORIZON_YEARS
    )
    addition_direct = C.ADDITION_CENTS_PER_SEAT * deficit

    relocation_soft, relocation_total = total_program_cost(relocation_direct)
    boundary_soft, boundary_total = total_program_cost(boundary_direct)
    addition_soft, addition_total = total_program_cost(addition_direct)

    excluded = bool(
        school and school["consecutive_reliance_years"] >= C.LONG_TERM_RELIANCE_YEARS
    )

    candidates = [
        ("RELOCATE", relocation_total),
        ("BOUNDARY_CHANGE", boundary_total),
        ("PERMANENT_ADDITION", addition_total),
    ]
    if excluded:
        candidates = [c for c in candidates if c[0] != "RELOCATE"]
    # ties broken by the fixed option order, which is the list order above
    recommendation = min(candidates, key=lambda c: c[1])[0]

    return {
        "relocation_direct_cents": relocation_direct,
        "relocation_soft_cost_cents": relocation_soft,
        "relocation_total_program_cost_cents": relocation_total,
        "boundary_change_direct_cents": boundary_direct,
        "boundary_change_soft_cost_cents": boundary_soft,
        "boundary_change_total_program_cost_cents": boundary_total,
        "permanent_addition_direct_cents": addition_direct,
        "permanent_addition_soft_cost_cents": addition_soft,
        "permanent_addition_total_program_cost_cents": addition_total,
        "relocate_excluded_for_reliance": excluded,
        "cost_recommendation": recommendation,
    }


def recompute_request_costs(req):
    """Stores estimated_relocation_cost_cents and the LIFECYCLE_20YR recommendation."""
    estimate = relocation_estimate(req)
    req["estimated_relocation_cost_cents"] = estimate["estimated_relocation_cost_cents"]
    alts = alternatives(req, estimate["estimated_relocation_cost_cents"], "LIFECYCLE_20YR")
    req["cost_recommendation"] = alts["cost_recommendation"]
    return estimate, alts

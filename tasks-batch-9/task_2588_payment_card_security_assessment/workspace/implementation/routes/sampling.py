"""Sampling plans: stratified component sampling, facility sampling, re-pricing."""

from flask import Blueprint

import middleware as mw
from db import db, ordered
from errors import ApiError
from response import collection, single
from services import calc, derive, serialize

bp = Blueprint("sampling", __name__)

PLAN_VARIANTS = ("PRELIMINARY", "FINAL")
ELIGIBLE_CLASSES = ("CDE", "CONNECTED")


def eligible_population(engagement_id, plan_variant):
    """PRELIMINARY reads declared_scope_class; FINAL reads scope_class."""
    field = "declared_scope_class" if plan_variant == "PRELIMINARY" else "scope_class"
    return [component for component in derive.components_of(engagement_id)
            if component.get(field) in ELIGIBLE_CLASSES]


@bp.post("/engagements/<engagement_id>/sampling-plans")
def create_sampling_plan(engagement_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    plan_variant = mw.v_enum(body, "plan_variant", PLAN_VARIANTS)
    justification_text = mw.v_str(body, "justification_text", allow_empty=False)
    expected_version = mw.v_int(body, "expected_engagement_version")

    engagement = mw.fetch(db.engagements, engagement_id, "ERR_ENGAGEMENT_NOT_FOUND")
    mw.require_lead(engagement, user_id)
    derive.guard_frozen(engagement)

    if expected_version != engagement.get("version"):
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION")

    eligible = eligible_population(engagement_id, plan_variant)
    if not eligible:
        raise ApiError("ERR_EMPTY_SAMPLE_POPULATION")

    population = {}
    for component in eligible:
        stratum = component.get("component_type")
        population[stratum] = population.get(stratum, 0) + 1
    allocations = calc.stratum_allocation(population)
    component_sample_size = 0
    for stratum in calc.STRATUM_ORDER:
        component_sample_size += allocations[stratum]

    facility_population_count, facility_sample_size, sampled_facility_names = \
        calc.facility_sample([component.get("facility_name") for component in eligible])

    # The fee ceiling is re-checked before anything is committed (atomicity).
    hours, total = calc.assessment_fee(
        engagement.get("merchant_level"), component_sample_size, facility_sample_size,
        derive.accepted_ccw_count(engagement_id))
    derive.enforce_budget(engagement, total)

    # --- commit ---------------------------------------------------------------
    for plan in derive.plans_of(engagement_id):
        if plan.get("status") != "SUPERSEDED":
            plan["status"] = "SUPERSEDED"
            plan["superseded_at"] = db.now_iso()
            db.touch(plan)

    row = {
        "engagement_id": engagement_id,
        "plan_variant": plan_variant,
        "justification_text": justification_text,
        "status": "ACTIVE",
        "eligible_component_count": len(eligible),
        "component_sample_size": component_sample_size,
        "stratum_allocations": dict((stratum, allocations[stratum])
                                    for stratum in calc.STRATUM_ORDER),
        "facility_population_count": facility_population_count,
        "facility_sample_size": facility_sample_size,
        "sampled_facility_names": sampled_facility_names,
        "coverage_ratio": calc.coverage_ratio(component_sample_size, len(eligible)),
        "superseded_at": None,
    }
    db.stamp_new(row)
    db.sampling_plans[row["id"]] = row

    _select_components(engagement_id, eligible, allocations)

    derive.store_fee(engagement, hours, total)
    db.touch(engagement)
    return single(serialize.sampling_plan(row), 201)


def _select_components(engagement_id, eligible, allocations):
    """Reset every flag, then walk the strata in the pinned order by hostname."""
    eligible_ids = set(component["id"] for component in eligible)
    for component in derive.components_of(engagement_id):
        changed = False
        if component.get("in_sample") is not False:
            component["in_sample"] = False
            changed = True
        wanted_stratum = component.get("component_type") \
            if component["id"] in eligible_ids else None
        if component.get("sampling_stratum") != wanted_stratum:
            component["sampling_stratum"] = wanted_stratum
            changed = True
        if changed:
            db.touch(component)

    for stratum in calc.STRATUM_ORDER:
        allocation = allocations.get(stratum, 0)
        if allocation <= 0:
            continue
        candidates = sorted(
            [component for component in eligible
             if component.get("component_type") == stratum],
            key=lambda component: component.get("hostname") or "",
        )
        for component in candidates[:allocation]:
            component["in_sample"] = True
            db.touch(component)


@bp.get("/sampling-plans")
def list_sampling_plans():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.sampling_plan(row) for row in ordered(db.sampling_plans.values())]
    payload = mw.apply_filters(payload, {
        "engagement_id": ("engagement_id", "str"),
        "plan_variant": ("plan_variant", "str"),
        "status": ("status", "str"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/sampling-plans/<row_id>")
def get_sampling_plan(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.sampling_plans, row_id, "ERR_SAMPLING_PLAN_NOT_FOUND")
    return single(serialize.sampling_plan(row))

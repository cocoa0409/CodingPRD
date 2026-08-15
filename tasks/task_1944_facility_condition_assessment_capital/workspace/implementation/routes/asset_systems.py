"""AssetSystem endpoints: inventory registration, reassessment workflow,
retirement cascade, and system-scoped reverse lookups."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REFERENCE_NOT_FOUND,
    ERR_REFERENTIAL_CONFLICT,
    raise_error,
)
from middleware import auth
from response import ok_object
from services.core import (
    append_snapshot,
    compute_rul,
    get_or_404,
    list_response,
    new_record,
    open_cycle_for,
    pub,
    recompute_bundle,
    recompute_facility,
    recompute_plan_total,
    touch,
)
from util import body, v_int, v_str

bp = Blueprint("asset_systems", __name__)

SYSTEM_CATEGORIES = (
    "HVAC",
    "ROOF",
    "ENVELOPE",
    "ELECTRICAL",
    "PLUMBING",
    "FIRE_PROTECTION",
    "CONVEYANCE",
    "INTERIOR",
    "SITE",
    "STRUCTURE",
)


@bp.post("/fca/asset-systems")
def create_asset_system():
    auth("Consultant")
    data = body()
    # Priority 4: body FK existence
    facility_id = data.get("facility_id")
    if facility_id is not None and facility_id not in db.facilities:
        raise_error(
            ERR_REFERENCE_NOT_FOUND,
            f"facility_id does not reference an existing facility: {facility_id}",
        )
    # Priority 10: field shape
    system_category = v_str(data, "system_category")
    if system_category not in SYSTEM_CATEGORIES:
        raise_error(
            ERR_INVALID_REQUEST,
            f"system_category must be one of {', '.join(SYSTEM_CATEGORIES)}",
        )
    name = v_str(data, "name")
    install_year = v_int(data, "install_year", minimum=1900, maximum=2100)
    design_life_years = v_int(data, "design_life_years", minimum=1)
    replacement_cost_cents = v_int(data, "replacement_cost_cents", minimum=0)
    condition_rating = v_int(data, "condition_rating", minimum=1, maximum=5)
    facility_id = v_str(data, "facility_id")
    rec = new_record()
    rec.update(
        {
            "facility_id": facility_id,
            "system_category": system_category,
            "name": name,
            "install_year": install_year,
            "design_life_years": design_life_years,
            "replacement_cost_cents": replacement_cost_cents,
            "condition_rating": condition_rating,
            "remaining_useful_life_years": compute_rul(
                install_year, design_life_years, condition_rating
            ),
            "status": "ACTIVE",
            "last_assessed_epoch": 0,
        }
    )
    db.asset_systems[rec["id"]] = rec
    recompute_facility(db.facilities[facility_id])
    return ok_object(pub(rec), 201)


@bp.get("/fca/asset-systems")
def list_asset_systems():
    auth()
    records = list(db.asset_systems.values())
    facility_id = request.args.get("facility_id")
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    return list_response(records)


@bp.get("/fca/asset-systems/<system_id>")
def get_asset_system(system_id):
    auth()
    return ok_object(pub(get_or_404(db.asset_systems, system_id, "AssetSystem")))


@bp.post("/fca/asset-systems/<system_id>/assess")
def assess_asset_system(system_id):
    auth("Consultant")
    system = get_or_404(db.asset_systems, system_id, "AssetSystem")
    fac = db.facilities[system["facility_id"]]
    # Priority 5: state legality — system must be ACTIVE and an OPEN
    # refresh cycle must exist for the owning facility
    if system["status"] != "ACTIVE":
        raise_error(
            ERR_INVALID_STATE,
            f"AssetSystem status {system['status']} does not permit assess",
        )
    cycle = open_cycle_for(fac["id"])
    if cycle is None:
        raise_error(
            ERR_INVALID_STATE,
            "No OPEN refresh cycle exists for the owning facility",
        )
    # Priority 10: field shape
    data = body()
    condition_rating = v_int(data, "condition_rating", minimum=1, maximum=5)
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        raise_error(ERR_INVALID_REQUEST, "Field note must be a string")
    # Retain pre-assessment values as reject-assessment fallback when no
    # prior ConditionSnapshot exists.
    system["_pre_assess_rating"] = system["condition_rating"]
    system["_pre_assess_rul"] = system["remaining_useful_life_years"]
    system["condition_rating"] = condition_rating
    system["remaining_useful_life_years"] = compute_rul(
        system["install_year"], system["design_life_years"], condition_rating
    )
    system["status"] = "REASSESSED"
    system["last_assessed_epoch"] = cycle["epoch"]
    snap = append_snapshot(system, cycle["epoch"], note)
    system["_pending_snapshot_id"] = snap["id"]
    touch(system)
    recompute_facility(fac)
    return ok_object(pub(system))


@bp.post("/fca/asset-systems/<system_id>/accept-assessment")
def accept_assessment(system_id):
    auth("FacilityManager")
    system = get_or_404(db.asset_systems, system_id, "AssetSystem")
    if system["status"] != "REASSESSED":
        raise_error(
            ERR_INVALID_STATE,
            f"AssetSystem status {system['status']} does not permit accept-assessment",
        )
    system["status"] = "ACTIVE"
    touch(system)
    return ok_object(pub(system))


@bp.post("/fca/asset-systems/<system_id>/reject-assessment")
def reject_assessment(system_id):
    auth("FacilityManager")
    system = get_or_404(db.asset_systems, system_id, "AssetSystem")
    if system["status"] != "REASSESSED":
        raise_error(
            ERR_INVALID_STATE,
            f"AssetSystem status {system['status']} does not permit reject-assessment",
        )
    # Compensation: revert rating and RUL to the most recent prior
    # ConditionSnapshot (i.e. the newest snapshot other than the one this
    # reassessment appended).
    pending_id = system.get("_pending_snapshot_id")
    prior = None
    for snap in db.condition_snapshots.values():
        if snap["asset_system_id"] == system_id and snap["id"] != pending_id:
            if prior is None or snap["created_at"] > prior["created_at"]:
                prior = snap
    if prior is not None:
        system["condition_rating"] = prior["condition_rating"]
        system["remaining_useful_life_years"] = prior["remaining_useful_life_years"]
    else:
        system["condition_rating"] = system.get(
            "_pre_assess_rating", system["condition_rating"]
        )
        system["remaining_useful_life_years"] = system.get(
            "_pre_assess_rul", system["remaining_useful_life_years"]
        )
    system["status"] = "ACTIVE"
    touch(system)
    return ok_object(pub(system))


@bp.post("/fca/asset-systems/<system_id>/retire")
def retire_asset_system(system_id):
    auth("FacilityManager")
    system = get_or_404(db.asset_systems, system_id, "AssetSystem")
    # Priority 5: state legality
    if system["status"] != "ACTIVE":
        raise_error(
            ERR_INVALID_STATE,
            f"AssetSystem status {system['status']} does not permit retire",
        )
    # Priority 12: may not retire while OPEN / IN_PROGRESS deficiencies exist
    for d in db.deficiencies.values():
        if d["asset_system_id"] == system_id and d["remediation_status"] in (
            "OPEN",
            "IN_PROGRESS",
        ):
            raise_error(
                ERR_REFERENTIAL_CONFLICT,
                "AssetSystem has OPEN or IN_PROGRESS deficiencies",
            )
    system["status"] = "RETIRED"
    touch(system)
    recompute_facility(db.facilities[system["facility_id"]])
    # Transitive cascade AssetSystem -> PlanLineItem -> CapitalPlan: FUNDED
    # line items referencing this system's deficiencies on DRAFT plans move
    # to REMOVED; the plan totals (and any bundle costs holding those items)
    # are recomputed.
    affected_plans = set()
    affected_bundles = set()
    for item in db.plan_line_items.values():
        if item["funding_status"] != "FUNDED":
            continue
        d = db.deficiencies.get(item["deficiency_id"])
        if d is None or d["asset_system_id"] != system_id:
            continue
        plan = db.capital_plans.get(item["capital_plan_id"])
        if plan is None or plan["status"] != "DRAFT":
            continue
        item["funding_status"] = "REMOVED"
        touch(item)
        affected_plans.add(plan["id"])
        if item.get("project_bundle_id"):
            affected_bundles.add(item["project_bundle_id"])
    for plan_id in affected_plans:
        recompute_plan_total(db.capital_plans[plan_id])
    for bundle_id in affected_bundles:
        recompute_bundle(db.project_bundles[bundle_id])
    return ok_object(pub(system))


@bp.get("/fca/asset-systems/<system_id>/deficiencies")
def list_system_deficiencies(system_id):
    auth()
    get_or_404(db.asset_systems, system_id, "AssetSystem")
    records = [
        d for d in db.deficiencies.values() if d["asset_system_id"] == system_id
    ]
    return list_response(records)


@bp.get("/fca/asset-systems/<system_id>/condition-snapshots")
def list_system_snapshots(system_id):
    auth()
    get_or_404(db.asset_systems, system_id, "AssetSystem")
    records = [
        s
        for s in db.condition_snapshots.values()
        if s["asset_system_id"] == system_id
    ]
    return list_response(records)

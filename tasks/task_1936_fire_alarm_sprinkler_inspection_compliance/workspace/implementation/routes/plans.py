"""InspectionPlan endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, MARSHAL_AND_ADMIN, ROLE_CONTRACTOR_ADMIN
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_int
from errors import (
    invalid_state, duplicate_constraint, stale_version,
    posture_blocked, empty_plan,
)
from services.core import (
    base_record, public, touch,
    get_property, get_plan,
    contractor_of_property, require_contractor_active, require_property_active,
)
from services import calc

bp = Blueprint("plans", __name__)


@bp.route("/fire-compliance/properties/<pid>/inspection-plans", methods=["POST"])
def create_plan(pid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    prop = get_property(pid)
    body = get_body()
    check_unknown_fields(body, {"plan_year", "expected_property_version"})
    plan_year = req_int(body, "plan_year")
    expected_version = req_int(body, "expected_property_version")
    con = contractor_of_property(prop)
    require_contractor_active(con)
    require_property_active(prop)
    # uniqueness (13): plan_year unique per property
    for p in store.plans.values():
        if p["property_id"] == prop["id"] and p["plan_year"] == plan_year:
            raise duplicate_constraint("plan_year must be unique per property")
    # OCC (17): expected_property_version must equal the property's version
    if expected_version != prop["version"]:
        raise stale_version("expected_property_version does not match the property's current version")

    creation_date = store.today()
    rec = base_record()
    rec.update({
        "property_id": prop["id"],
        "plan_year": plan_year,
        "total_events_required": 0,
        "events_completed": 0,
        "plan_posture": "DRAFT",
        "provisional_fee_cents": 0,
        "final_fee_cents": None,
    })
    store.plans[rec["id"]] = rec
    calc.recompute_plan_totals(rec)
    rec["provisional_fee_cents"] = calc.provisional_fee_cents(
        prop["id"], plan_year, creation_date)
    # creation itself increments the parent property's version
    touch(prop)
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/properties/<pid>/inspection-plans", methods=["GET"])
def list_plans(pid):
    require_roles(MARSHAL_AND_ADMIN)
    prop = get_property(pid)
    rows = [p for p in store.plans.values() if p["property_id"] == prop["id"]]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/inspection-plans/<pid>", methods=["GET"])
def fetch_plan(pid):
    require_roles(MARSHAL_AND_ADMIN)
    return success_object(public(get_plan(pid)))


@bp.route("/fire-compliance/inspection-plans/<pid>/publish", methods=["POST"])
def publish_plan(pid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    plan = get_plan(pid)
    if plan["plan_posture"] != "DRAFT":
        raise invalid_state("Plan is not DRAFT")
    prop = store.properties.get(plan["property_id"])
    con = contractor_of_property(prop) if prop else None
    require_contractor_active(con)
    require_property_active(prop)
    if plan["total_events_required"] <= 0:
        raise empty_plan("Plan requires at least one inspection event")
    if con is None or con["posture"] != "GOOD_STANDING":
        raise posture_blocked("Plan publication requires GOOD_STANDING posture")

    creation_date = plan["created_at"]  # ISO string; take the date portion
    from db import parse_iso
    creation_dt = parse_iso(creation_date)
    plan["final_fee_cents"] = calc.final_fee_cents(
        plan["property_id"], plan["plan_year"], creation_dt.date())
    plan["plan_posture"] = "SCHEDULED"
    touch(plan)
    # posture re-eval in case children already moved (events on a DRAFT plan)
    calc.derive_plan_posture(plan)
    return success_object(public(plan))

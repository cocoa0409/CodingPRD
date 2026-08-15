"""PM plans and budget ledger reads (PRD §3.2, §2.8)."""
from flask import Blueprint, request

import errors as E
from errors import ApiError
from db import store, new_common_fields, touch
from middleware import (auth, require_role, body, v_str, v_int, paginate,
                        LEDGER_READ_ROLES)
from response import ok_object, ok_list
from services.core import get_property, get_plan, require_active_property
from services.compliance import committed_cents
from services.serializers import plan_view, ledger_view

bp = Blueprint("plans", __name__)

PM = ("PropertyManager",)
ALL = ("PropertyManager", "Technician", "ComplianceAuditor")
OPEN_WO_STATES = ("OPEN", "IN_REVIEW", "APPROVED", "IN_PROGRESS")
OPEN_VISIT_STATES = ("SCHEDULED", "NOTIFIED", "IN_PROGRESS")


@bp.route("/pm/plans", methods=["POST"])
def create_plan():
    _, role = auth()
    require_role(role, PM)
    data = body()
    prop = None
    if data.get("property_id") is not None:
        prop = get_property(data["property_id"])
        require_active_property(prop)
    pid = v_str(data, "property_id")
    year = v_int(data, "plan_year")
    budget = v_int(data, "budget_cents", minv=1)
    if prop is None:
        prop = get_property(pid)
        require_active_property(prop)
    rec = new_common_fields()
    rec.update({
        "property_id": prop["id"],
        "plan_year": year,
        "budget_cents": budget,
        "status": "DRAFT",
    })
    store.plans[rec["id"]] = rec
    return ok_object(plan_view(rec), 201)


@bp.route("/pm/plans/<plan_id>", methods=["GET"])
def get_plan_route(plan_id):
    _, role = auth()
    require_role(role, ALL)
    plan = get_plan(plan_id)
    return ok_object(plan_view(plan), 200)


@bp.route("/pm/properties/<property_id>/plans", methods=["GET"])
def list_plans(property_id):
    _, role = auth()
    require_role(role, ALL)
    prop = get_property(property_id)
    rows = [p for p in store.plans.values() if p["property_id"] == prop["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    year = request.args.get("plan_year")
    if year is not None:
        try:
            y = int(year)
            rows = [p for p in rows if p["plan_year"] == y]
        except (TypeError, ValueError):
            rows = []
    page, limit, offset, total = paginate(rows)
    return ok_list([plan_view(p) for p in page], limit, offset, total)


@bp.route("/pm/plans/<plan_id>/adopt", methods=["POST"])
def adopt_plan(plan_id):
    _, role = auth()
    require_role(role, PM)
    plan = get_plan(plan_id)
    prop = store.properties.get(plan["property_id"])
    require_active_property(prop)
    if plan["status"] != "DRAFT":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Plan in %s cannot be adopted" % plan["status"])
    for p in store.plans.values():
        if (p["id"] != plan["id"] and p["property_id"] == plan["property_id"]
                and p["plan_year"] == plan["plan_year"] and p["status"] == "ADOPTED"):
            raise ApiError(E.ERR_DUPLICATE_ACTIVE_PLAN, 409,
                           "Another ADOPTED plan exists for this property and year")
    plan["status"] = "ADOPTED"
    touch(plan)
    return ok_object(plan_view(plan), 200)


@bp.route("/pm/plans/<plan_id>/close", methods=["POST"])
def close_plan(plan_id):
    _, role = auth()
    require_role(role, PM)
    plan = get_plan(plan_id)
    prop = store.properties.get(plan["property_id"])
    require_active_property(prop)
    if plan["status"] != "ADOPTED":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "Plan in %s cannot be closed" % plan["status"])
    for wo in store.work_orders.values():
        if wo["plan_id"] == plan["id"] and wo["status"] in OPEN_WO_STATES:
            raise ApiError(E.ERR_PLAN_HAS_OPEN_WORK, 409,
                           "Plan has an open corrective work order")
    for v in store.visits.values():
        if v["plan_id"] == plan["id"] and v["visit_status"] in OPEN_VISIT_STATES:
            raise ApiError(E.ERR_PLAN_HAS_OPEN_WORK, 409,
                           "Plan has an open visit")
    if committed_cents(plan["id"]) != 0:
        raise ApiError(E.ERR_PLAN_HAS_OPEN_WORK, 409,
                       "Plan has outstanding committed cents")
    plan["status"] = "CLOSED"
    touch(plan)
    return ok_object(plan_view(plan), 200)


@bp.route("/pm/plans/<plan_id>/ledger", methods=["GET"])
def plan_ledger(plan_id):
    _, role = auth()
    require_role(role, LEDGER_READ_ROLES)
    plan = get_plan(plan_id)
    rows = [e for e in store.ledger.values() if e["plan_id"] == plan["id"]]
    kind = request.args.get("entry_kind")
    if kind is not None:
        rows = [e for e in rows if e["entry_kind"] == kind]
    page, limit, offset, total = paginate(rows)
    return ok_list([ledger_view(e) for e in page], limit, offset, total)

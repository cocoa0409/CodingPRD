from flask import Blueprint, request

from db import db, common_create_fields, touch
from errors import ApiError
from middleware import get_identity, require_role
from response import success, list_response
from services import serialize
from services.common import (
    get_body, require_fields, as_int, parse_iso,
    get_property, get_quote, get_plan,
    get_pagination, paginate, sorted_by_creation,
)
from services.domain import release_visit_assignments

bp = Blueprint("plans", __name__)


@bp.post("/recurring-plans")
def create_plan():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["property_id", "source_quote_id", "cadence_days", "start_utc"])
    prop = get_property(body["property_id"])
    quote = get_quote(body["source_quote_id"])
    cadence = as_int(body["cadence_days"], "cadence_days", minimum=1)
    start = parse_iso(body["start_utc"], "start_utc")  # validates ISO8601

    if quote["status"] != "ACCEPTED":
        raise ApiError("ERR_QUOTE_NOT_ACCEPTED", "source_quote is not ACCEPTED")

    p = common_create_fields()
    p.update({
        "property_id": prop["id"],
        "source_quote_id": quote["id"],
        "cadence_days": cadence,
        "next_due_utc": body["start_utc"],
        "visits_generated_count": 0,
        "status": "ACTIVE",
    })
    db.recurring_plans[p["id"]] = p
    return success(serialize.plan_view(p), 201)


@bp.get("/recurring-plans")
def list_plans():
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer"})
    property_id = request.args.get("property_id")
    source_quote_id = request.args.get("source_quote_id")
    limit, offset = get_pagination()
    items = []
    for p in db.recurring_plans.values():
        if property_id is not None and p["property_id"] != property_id:
            continue
        if source_quote_id is not None and p["source_quote_id"] != source_quote_id:
            continue
        if role == "Customer":
            prop = db.properties.get(p["property_id"])
            if prop is None or prop["customer_id"] != user_id:
                continue
        items.append(p)
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.plan_view(p) for p in page], limit, offset, total)


@bp.get("/recurring-plans/<pid>")
def get_one_plan(pid):
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer"})
    p = get_plan(pid)
    if role == "Customer":
        prop = db.properties.get(p["property_id"])
        if prop is None or prop["customer_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    return success(serialize.plan_view(p), 200)


@bp.post("/recurring-plans/<pid>/cancel")
def cancel_plan(pid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    p = get_plan(pid)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE plan can be cancelled")
    # Depth-3 cascade: plan -> REQUESTED/SCHEDULED visits -> assignments -> tech minutes.
    p["status"] = "CANCELLED"
    touch(p)
    for v in db.visits.values():
        if v["plan_id"] == p["id"] and v["status"] in ("REQUESTED", "SCHEDULED"):
            release_visit_assignments(v)
            v["status"] = "CANCELLED"
            touch(v)
    return success(serialize.plan_view(p), 200)


@bp.post("/recurring-plans/<pid>/generate-visit")
def generate_visit(pid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    p = get_plan(pid)
    body = get_body()
    duration = 120
    if "duration_minutes" in body and body["duration_minutes"] is not None:
        duration = as_int(body["duration_minutes"], "duration_minutes", minimum=1)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE plan can generate visits")
    prop = db.properties.get(p["property_id"])
    v = common_create_fields()
    v.update({
        "property_id": p["property_id"],
        "quote_id": p["source_quote_id"],
        "plan_id": p["id"],
        "route_id": prop["route_id"],
        "scheduled_date": p["next_due_utc"][:10],
        "duration_minutes": duration,
        "provisional_cost_cents": None,
        "final_cost_cents": None,
        "reclean_of_visit_id": None,
        "billing_status": "UNBILLED",
        "status": "REQUESTED",
    })
    db.visits[v["id"]] = v
    p["visits_generated_count"] = p["visits_generated_count"] + 1
    touch(p)
    return success(serialize.visit_view(v), 201)


# serialize.visit_view is used above to return the generated Visit.

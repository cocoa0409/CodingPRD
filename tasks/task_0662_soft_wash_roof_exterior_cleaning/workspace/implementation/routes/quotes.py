from flask import Blueprint, request

from db import db, common_create_fields, append_only_fields, touch
from errors import ApiError
from middleware import get_identity, require_role
from response import success, list_response
from services import serialize
from services import calc
from services.common import (
    get_body, require_fields, as_int, as_enum,
    get_property, get_quote, get_customer,
    get_pagination, paginate, sorted_by_creation,
)

bp = Blueprint("quotes", __name__)

SOILING_VALUES = {"LIGHT", "MODERATE", "HEAVY"}
SURFACE_VALUES = {"ROOF", "SIDING", "CONCRETE"}
SERVICE_VALUES = {"ROOF_SOFT_WASH", "HOUSE_WASH", "CONCRETE_CLEAN"}
NON_TERMINAL = {"DRAFT", "SENT", "ACCEPTED"}


def _line_items_for(quote_id):
    items = [li for li in db.quote_line_items.values() if li["quote_id"] == quote_id]
    return sorted_by_creation(items)


@bp.post("/quotes")
def create_quote():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["property_id", "expected_property_version"])
    prop = get_property(body["property_id"])
    # body well-formedness
    soiling = "MODERATE"
    if "soiling_level" in body and body["soiling_level"] is not None:
        soiling = as_enum(body["soiling_level"], "soiling_level", SOILING_VALUES)
    expected = as_int(body["expected_property_version"], "expected_property_version", minimum=0)

    # SUSPENDED customer blocks new quote creation (§3.1).
    customer = get_customer(prop["customer_id"])
    if customer["status"] == "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Customer is SUSPENDED")

    # OCC: expected_property_version must equal current Property.version.
    if expected != prop["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_property_version is stale")

    # Supersede the prior non-terminal quote on this property and bump version.
    # touch(prop) increments Property.version by 1 (PRD §2.4 / §3.3).
    for q in db.quotes.values():
        if q["property_id"] == prop["id"] and q["status"] in NON_TERMINAL:
            q["status"] = "SUPERSEDED"
            touch(q)
    touch(prop)

    q = common_create_fields()
    q.update({
        "property_id": prop["id"],
        "soiling_level": soiling,
        "subtotal_cents": None,
        "travel_surcharge_cents": None,
        "total_cents": None,
        "status": "DRAFT",
    })
    db.quotes[q["id"]] = q
    return success(serialize.quote_view(q), 201)


@bp.get("/quotes")
def list_quotes():
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer"})
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    limit, offset = get_pagination()
    items = []
    for q in db.quotes.values():
        if property_id is not None and q["property_id"] != property_id:
            continue
        if status is not None and q["status"] != status:
            continue
        if role == "Customer":
            prop = db.properties.get(q["property_id"])
            if prop is None or prop["customer_id"] != user_id:
                continue
        items.append(q)
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.quote_view(q) for q in page], limit, offset, total)


@bp.get("/quotes/<qid>")
def get_one_quote(qid):
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer"})
    q = get_quote(qid)
    if role == "Customer":
        prop = db.properties.get(q["property_id"])
        if prop is None or prop["customer_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    return success(serialize.quote_view(q), 200)


@bp.post("/quotes/<qid>/line-items")
def add_line_item(qid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    q = get_quote(qid)
    body = get_body()
    require_fields(body, ["surface_type", "service_type", "measured_sqft"])
    surface = as_enum(body["surface_type"], "surface_type", SURFACE_VALUES)
    service = as_enum(body["service_type"], "service_type", SERVICE_VALUES)
    measured = as_int(body["measured_sqft"], "measured_sqft", minimum=1)
    # Line items are added to a DRAFT quote (§3.2).
    if q["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Line items can only be added to a DRAFT quote")
    prop = db.properties.get(q["property_id"])
    stories = prop["stories"]
    dose = calc.chemical_dose_oz(measured, service, q["soiling_level"])
    total = calc.line_total_cents(measured, surface, service, stories)
    li = append_only_fields()
    li.update({
        "quote_id": q["id"],
        "surface_type": surface,
        "service_type": service,
        "measured_sqft": measured,
        "chemical_dose_oz": dose,
        "line_total_cents": total,
    })
    db.quote_line_items[li["id"]] = li
    return success(serialize.line_item_view(li), 201)


@bp.get("/quotes/<qid>/line-items")
def list_line_items(qid):
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "Customer"})
    q = get_quote(qid)
    if role == "Customer":
        prop = db.properties.get(q["property_id"])
        if prop is None or prop["customer_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    limit, offset = get_pagination()
    items = _line_items_for(qid)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.line_item_view(li) for li in page], limit, offset, total)


@bp.post("/quotes/<qid>/send")
def send_quote(qid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    q = get_quote(qid)
    # State precedence (priority 6) before empty-set check (priority 7).
    if q["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT quote can be sent")
    items = _line_items_for(qid)
    if len(items) == 0:
        raise ApiError("ERR_QUOTE_EMPTY", "Quote has no line items")
    # Freeze totals in pinned order: subtotal -> travel -> total.
    subtotal = sum(li["line_total_cents"] for li in items)
    travel = calc.travel_surcharge_cents(subtotal)
    q["subtotal_cents"] = subtotal
    q["travel_surcharge_cents"] = travel
    q["total_cents"] = subtotal + travel
    q["status"] = "SENT"
    touch(q)
    return success(serialize.quote_view(q), 200)


@bp.post("/quotes/<qid>/revise")
def revise_quote(qid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    q = get_quote(qid)
    if q["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", "Only a SENT quote can be revised")
    q["status"] = "DRAFT"
    q["subtotal_cents"] = None
    q["travel_surcharge_cents"] = None
    q["total_cents"] = None
    touch(q)
    return success(serialize.quote_view(q), 200)


@bp.post("/quotes/<qid>/accept")
def accept_quote(qid):
    user_id, role = get_identity()
    require_role(role, {"Customer"})
    q = get_quote(qid)
    # Ownership (priority 4) before state (priority 6).
    prop = db.properties.get(q["property_id"])
    if prop is None or prop["customer_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    if q["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", "Only a SENT quote can be accepted")
    q["status"] = "ACCEPTED"
    touch(q)
    return success(serialize.quote_view(q), 200)


@bp.post("/quotes/<qid>/decline")
def decline_quote(qid):
    user_id, role = get_identity()
    require_role(role, {"Customer"})
    q = get_quote(qid)
    prop = db.properties.get(q["property_id"])
    if prop is None or prop["customer_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    if q["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", "Only a SENT quote can be declined")
    q["status"] = "DECLINED"
    touch(q)
    return success(serialize.quote_view(q), 200)

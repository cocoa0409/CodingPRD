"""Pantry catalog, visits, and line items (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_DUPLICATE_ITEM,
    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_CLIENT_NOT_ACTIVE, ERR_ASSESSMENT_REQUIRED,
    ERR_VISIT_LIMIT_EXCEEDED, ERR_VISIT_ALREADY_OPEN, ERR_VISIT_NOT_OPEN,
    ERR_EMPTY_CHECKOUT, ERR_ITEM_NOT_AVAILABLE, ERR_ITEM_LIMIT_EXCEEDED,
    ERR_POINTS_BALANCE_EXCEEDED,
)
from middleware import authenticate, authorize, check_client_scope
from response import success_object
from routes.helpers import list_response
from services import calculations as calc
from services.core import new_record, touch, public, verified_assessment
from util import CLOCK, fmt_ts, week_start_of
from validate import (
    get_body, req_int, opt_int, req_enum, req_str, require_path_resource, require_body_ref,
)

bp = Blueprint("pantry", __name__)

CATEGORIES = ["PERISHABLE", "SHELF_STABLE", "HYGIENE", "BABY_CARE"]
CATALOG_READ_ROLES = ["Client", "IntakeCoordinator", "PantryStaff", "BenefitsCounselor",
                      "GrantReviewer", "ShelterCoordinator", "HubAdmin"]
VISIT_READ_ROLES = ["Client", "PantryStaff", "HubAdmin"]


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

@bp.post("/pantry-items")
def create_item():
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    body = get_body()
    item_name = req_str(body, "item_name")
    category = req_enum(body, "category", CATEGORIES)
    point_cost = req_int(body, "point_cost", minimum=1)
    quantity_on_hand = req_int(body, "quantity_on_hand", minimum=0)
    reorder_threshold = req_int(body, "reorder_threshold", minimum=0)
    per_visit_limit = req_int(body, "per_visit_limit", minimum=1)
    # item_name unique among non-DISCONTINUED items
    for item in db["pantry_items"].values():
        if item["item_name"] == item_name and item["status"] == "ACTIVE":
            raise_error(ERR_DUPLICATE_ITEM, "item_name already used by an ACTIVE PantryItem")
    rec = new_record("pantry_items", {
        "item_name": item_name,
        "category": category,
        "point_cost": point_cost,
        "quantity_on_hand": quantity_on_hand,
        "reorder_threshold": reorder_threshold,
        "per_visit_limit": per_visit_limit,
        "restock_flag": quantity_on_hand <= reorder_threshold,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/pantry-items")
def list_items():
    caller = authenticate()
    authorize(caller, CATALOG_READ_ROLES)
    filters = {
        "category": request.args.get("category"),
        "status": request.args.get("status"),
    }
    return list_response("pantry_items", filters)


@bp.patch("/pantry-items/<iid>")
def patch_item(iid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    item = require_path_resource("pantry_items", iid, "pantry item")
    body = get_body()
    # OCC on PantryItem.version (expected_item_version is non-optional)
    expected = body.get("expected_item_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_item_version is required")
    if expected != item["version"]:
        raise_error(ERR_STALE_VERSION, "expected_item_version does not match the item's current version")
    if "point_cost" in body and body["point_cost"] is not None:
        item["point_cost"] = req_int(body, "point_cost", minimum=1)
    if "reorder_threshold" in body and body["reorder_threshold"] is not None:
        item["reorder_threshold"] = req_int(body, "reorder_threshold", minimum=0)
    if "per_visit_limit" in body and body["per_visit_limit"] is not None:
        item["per_visit_limit"] = req_int(body, "per_visit_limit", minimum=1)
    # point_cost changes never retro-edit pinned VisitLineItem.points_charged
    item["restock_flag"] = item["quantity_on_hand"] <= item["reorder_threshold"]
    touch(item)
    return success_object(public(item))


@bp.post("/pantry-items/<iid>/restock")
def restock_item(iid):
    caller = authenticate()
    authorize(caller, ["PantryStaff", "HubAdmin"])
    item = require_path_resource("pantry_items", iid, "pantry item")
    body = get_body()
    quantity = req_int(body, "quantity", minimum=1)
    item["quantity_on_hand"] += quantity
    item["restock_flag"] = item["quantity_on_hand"] <= item["reorder_threshold"]
    touch(item)
    return success_object(public(item))


@bp.post("/pantry-items/<iid>/discontinue")
def discontinue_item(iid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    item = require_path_resource("pantry_items", iid, "pantry item")
    if item["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE item can be discontinued")
    item["status"] = "DISCONTINUED"
    touch(item)
    return success_object(public(item))


# ---------------------------------------------------------------------------
# Visits
# ---------------------------------------------------------------------------

@bp.post("/clients/<cid>/pantry-visits")
def check_in_visit(cid):
    caller = authenticate()
    authorize(caller, ["PantryStaff"])
    client = require_path_resource("clients", cid, "client")
    if client["status"] != "ACTIVE":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "pantry check-in requires an ACTIVE client")
    if verified_assessment(client["id"]) is None:
        raise_error(ERR_ASSESSMENT_REQUIRED, "client must hold a VERIFIED assessment")
    # Rolling 168h window rule (strict edge), then the one-open-visit rule
    if calc.visits_in_window(client["id"]) >= calc.MAX_VISITS_PER_168H:
        raise_error(ERR_VISIT_LIMIT_EXCEEDED, "two visits already inside the trailing 168h")
    if calc.open_visit(client["id"]) is not None:
        raise_error(ERR_VISIT_ALREADY_OPEN, "client already has a CHECKED_IN visit")
    now = CLOCK.now()
    rec = new_record("pantry_visits", {
        "client_id": client["id"],
        "visit_date": CLOCK.now_iso(),
        "week_start": fmt_ts(week_start_of(now)),
        "status": "CHECKED_IN",
        "provisional_points": 0,
        "points_spent": 0,
    })
    return success_object(public(rec), status=201)


@bp.get("/pantry-visits")
def list_visits():
    caller = authenticate()
    authorize(caller, VISIT_READ_ROLES)
    filters = {
        "client_id": request.args.get("client_id"),
        "status": request.args.get("status"),
    }
    scope = None
    if caller.role == "Client":
        scope = lambda rec: rec["client_id"] == caller.user_id
    return list_response("pantry_visits", filters, scope_fn=scope)


@bp.get("/pantry-visits/<vid>")
def get_visit(vid):
    caller = authenticate()
    authorize(caller, VISIT_READ_ROLES)
    visit = require_path_resource("pantry_visits", vid, "pantry visit")
    check_client_scope(caller, visit["client_id"])
    return success_object(public(visit))


@bp.post("/pantry-visits/<vid>/line-items")
def add_line_item(vid):
    caller = authenticate()
    authorize(caller, ["PantryStaff"])
    visit = require_path_resource("pantry_visits", vid, "pantry visit")
    if visit["status"] != "CHECKED_IN":
        raise_error(ERR_VISIT_NOT_OPEN, "line items can only be added to a CHECKED_IN visit")
    body = get_body()
    item_id = req_str(body, "item_id")
    quantity = req_int(body, "quantity", minimum=1)
    item = require_body_ref("pantry_items", item_id, "item_id")
    if item["status"] != "ACTIVE" or item["quantity_on_hand"] < quantity:
        raise_error(ERR_ITEM_NOT_AVAILABLE, "item is DISCONTINUED or lacks stock coverage")
    # Cumulative units of this item across the visit must not exceed per_visit_limit
    cumulative = sum(
        li["quantity"] for li in db["visit_line_items"].values()
        if li["visit_id"] == visit["id"] and li["item_id"] == item["id"]
    )
    if cumulative + quantity > item["per_visit_limit"]:
        raise_error(ERR_ITEM_LIMIT_EXCEEDED, "cumulative units would exceed per_visit_limit")
    # points_charged pinned at add time; later price changes do not retro-edit
    points_charged = quantity * item["point_cost"]
    rec = new_record("visit_line_items", {
        "visit_id": visit["id"],
        "item_id": item["id"],
        "quantity": quantity,
        "points_charged": points_charged,
    }, with_version=False)
    visit["provisional_points"] += points_charged
    touch(visit)
    # Derived reserved-basis recompute on the client is itself a mutation (PRD 2.5)
    client = db["clients"].get(visit["client_id"])
    if client is not None:
        touch(client)
    return success_object(public(rec), status=201)


@bp.get("/visit-line-items")
def list_line_items():
    caller = authenticate()
    authorize(caller, ["PantryStaff", "HubAdmin"])
    filters = {
        "visit_id": request.args.get("visit_id"),
        "item_id": request.args.get("item_id"),
    }
    return list_response("visit_line_items", filters)


@bp.get("/visit-line-items/<liid>")
def get_line_item(liid):
    caller = authenticate()
    authorize(caller, ["PantryStaff", "HubAdmin"])
    rec = require_path_resource("visit_line_items", liid, "visit line item")
    return success_object(public(rec))


@bp.post("/pantry-visits/<vid>/checkout")
def checkout_visit(vid):
    caller = authenticate()
    authorize(caller, ["PantryStaff"])
    visit = require_path_resource("pantry_visits", vid, "pantry visit")
    # Checks in PRD 3.3's pinned order
    if visit["status"] != "CHECKED_IN":
        raise_error(ERR_VISIT_NOT_OPEN, "only a CHECKED_IN visit can be checked out")
    lines = [li for li in db["visit_line_items"].values() if li["visit_id"] == visit["id"]]
    if not lines:
        raise_error(ERR_EMPTY_CHECKOUT, "cannot check out a visit with zero line items")
    for li in lines:
        item = db["pantry_items"].get(li["item_id"])
        if item is None or item["quantity_on_hand"] < li["quantity"]:
            raise_error(ERR_ITEM_NOT_AVAILABLE, "stock no longer covers a pinned line")
    client = db["clients"].get(visit["client_id"])
    # Reserved-basis points admission (inclusive: exactly hitting the cap passes)
    settled = calc.points_settled(visit["client_id"])
    va = verified_assessment(visit["client_id"])
    allotment = calc.compute_allotment(va["household_size"] if va else None)
    if settled + visit["provisional_points"] > allotment:
        raise_error(ERR_POINTS_BALANCE_EXCEEDED, "weekly points allotment would be exceeded")
    if client is None or client["status"] != "ACTIVE":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "client must still be ACTIVE at checkout")
    visit["points_spent"] = visit["provisional_points"]
    visit["provisional_points"] = 0
    visit["status"] = "COMPLETED"
    touch(visit)
    for li in lines:
        item = db["pantry_items"][li["item_id"]]
        item["quantity_on_hand"] -= li["quantity"]
        item["restock_flag"] = item["quantity_on_hand"] <= item["reorder_threshold"]
        touch(item)
    if client is not None:
        touch(client)  # settled/reserved recomputed (PRD 2.5)
    return success_object(public(visit))


@bp.post("/pantry-visits/<vid>/void")
def void_visit_endpoint(vid):
    from services.core import void_visit
    caller = authenticate()
    authorize(caller, ["PantryStaff", "HubAdmin"])
    visit = require_path_resource("pantry_visits", vid, "pantry visit")
    if visit["status"] not in ("CHECKED_IN", "COMPLETED"):
        raise_error(ERR_VISIT_NOT_OPEN, "only a CHECKED_IN or COMPLETED visit can be voided")
    void_visit(visit)
    client = db["clients"].get(visit["client_id"])
    if client is not None:
        touch(client)  # spent totals recomputed (PRD 2.5)
    return success_object(public(visit))

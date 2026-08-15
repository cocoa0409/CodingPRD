"""Taxonomy categories (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import authenticate, ALL_ROLES
from response import ok_object, ok_list
from services import (new_entity, touch, serialize_category, serialize_risk,
                      serialize_appetite, serialize_kri, serialize_emerging,
                      sorted_by_creation)
from util import json_body, req_str, opt_num, paginate

bp = Blueprint("categories", __name__)


def get_category_or_404(cid):
    c = store["categories"].get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Category not found")
    return c


@bp.post("/categories")
def create_category():
    authenticate(("RiskManager",))
    data = json_body()
    name = req_str(data, "name")
    parent = data.get("parent_category_id")
    if parent is not None and not isinstance(parent, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'parent_category_id' must be a string")
    weight = opt_num(data, "weight_factor")
    if weight is None:
        weight = Decimal("1.0")
    # PRD 2.6: 0 < weight_factor <= 10, up to 3 decimals; violations are 400
    if weight <= 0 or weight > 10:
        raise ApiError("ERR_INVALID_REQUEST", 400, "weight_factor must be > 0 and <= 10")
    if weight != weight.quantize(Decimal("0.001")):
        raise ApiError("ERR_INVALID_REQUEST", 400, "weight_factor may carry up to 3 decimals")
    if parent is not None and parent not in store["categories"]:
        raise ApiError("ERR_NOT_FOUND", 404, "parent_category_id does not exist")
    c = new_entity()
    c.update({"name": name, "parent_category_id": parent, "weight_factor": weight})
    store["categories"][c["id"]] = c
    return ok_object(serialize_category(c), 201)


@bp.get("/categories")
def list_categories():
    authenticate(ALL_ROLES)
    items = list(store["categories"].values())
    if "parent_category_id" in request.args:
        want = request.args.get("parent_category_id")
        items = [c for c in items if c["parent_category_id"] == want]
    items = sorted_by_creation(items)
    page, meta = paginate(items)
    return ok_list([serialize_category(c) for c in page], meta)


@bp.get("/categories/<cid>")
def get_category(cid):
    authenticate(ALL_ROLES)
    return ok_object(serialize_category(get_category_or_404(cid)))


@bp.patch("/categories/<cid>")
def reparent_category(cid):
    authenticate(("RiskManager",))
    data = json_body()
    if "parent_category_id" not in data:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field 'parent_category_id'")
    parent = data["parent_category_id"]
    if parent is not None and not isinstance(parent, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'parent_category_id' must be a string")
    cat = get_category_or_404(cid)
    if parent is not None and parent not in store["categories"]:
        raise ApiError("ERR_NOT_FOUND", 404, "parent_category_id does not exist")
    # Cycle check: walking up from the new parent must not reach this category
    # (covers self-parenting and reparenting under a descendant).
    node = parent
    while node is not None:
        if node == cid:
            raise ApiError("ERR_CATEGORY_CYCLE", 422,
                           "parent chain would contain the category itself")
        node = store["categories"][node]["parent_category_id"]
    cat["parent_category_id"] = parent
    touch(cat)
    return ok_object(serialize_category(cat))


@bp.get("/categories/<cid>/subcategories")
def list_subcategories(cid):
    authenticate(ALL_ROLES)
    get_category_or_404(cid)
    items = sorted_by_creation(
        c for c in store["categories"].values() if c["parent_category_id"] == cid)
    page, meta = paginate(items)
    return ok_list([serialize_category(c) for c in page], meta)


@bp.get("/categories/<cid>/risks")
def list_category_risks(cid):
    authenticate(ALL_ROLES)
    get_category_or_404(cid)
    items = [r for r in store["risks"].values() if r["category_id"] == cid]
    if "status" in request.args:
        items = [r for r in items if r["status"] == request.args["status"]]
    items = sorted_by_creation(items)
    page, meta = paginate(items)
    return ok_list([serialize_risk(r) for r in page], meta)


@bp.get("/categories/<cid>/appetite-statements")
def list_category_appetite(cid):
    authenticate(ALL_ROLES)
    get_category_or_404(cid)
    items = sorted_by_creation(
        a for a in store["appetite_statements"].values() if a["category_id"] == cid)
    page, meta = paginate(items)
    return ok_list([serialize_appetite(a) for a in page], meta)


@bp.get("/categories/<cid>/kris")
def list_category_kris(cid):
    authenticate(ALL_ROLES)
    get_category_or_404(cid)
    items = sorted_by_creation(
        k for k in store["kris"].values() if k["category_id"] == cid)
    page, meta = paginate(items)
    return ok_list([serialize_kri(k) for k in page], meta)


@bp.get("/categories/<cid>/emerging-risks")
def list_category_emerging(cid):
    authenticate(ALL_ROLES)
    get_category_or_404(cid)
    items = sorted_by_creation(
        e for e in store["emerging_risks"].values() if e["category_id"] == cid)
    page, meta = paginate(items)
    return ok_list([serialize_emerging(e) for e in page], meta)

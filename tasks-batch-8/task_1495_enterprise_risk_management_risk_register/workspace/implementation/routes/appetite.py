"""Appetite statements (PRD 3.1): half-open windows, SoD, coverage guard."""
from flask import Blueprint

from db import store, clock_now
from errors import ApiError
from middleware import authenticate, ALL_ROLES
from response import ok_object, ok_list
from services import (new_entity, touch, serialize_appetite, serialize_breach,
                      sorted_by_creation)
from util import json_body, req_str, req_int, req_dt, paginate

bp = Blueprint("appetite", __name__)


def get_appetite_or_404(aid):
    a = store["appetite_statements"].get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Appetite statement not found")
    return a


def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap; adjacency (from == other.to) is allowed."""
    return a_from < b_to and b_from < a_to


def _check_window_overlap(category_id, new_from, new_to, exclude_id=None):
    for a in store["appetite_statements"].values():
        if a["category_id"] != category_id or a["status"] != "APPROVED":
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if _windows_overlap(new_from, new_to, a["effective_from"], a["effective_to"]):
            raise ApiError("ERR_WINDOW_OVERLAP", 409,
                           "Window overlaps another APPROVED statement for this category")


@bp.post("/appetite-statements")
def create_appetite():
    uid = authenticate(("RiskManager",))
    data = json_body()
    category_id = req_str(data, "category_id")
    tolerance = req_int(data, "tolerance_score")
    cap = req_int(data, "acceptance_cap_score")
    eff_from = req_dt(data, "effective_from")
    eff_to = req_dt(data, "effective_to")
    if category_id not in store["categories"]:
        raise ApiError("ERR_NOT_FOUND", 404, "category_id does not exist")
    if not (1 <= tolerance <= 25) or not (1 <= cap <= 25) or cap < tolerance:
        raise ApiError("ERR_TOLERANCE_OUT_OF_RANGE", 422,
                       "tolerance_score and acceptance_cap_score must be in 1..25 "
                       "with tolerance_score <= acceptance_cap_score")
    if not eff_to > eff_from:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "effective_to must be strictly after effective_from")
    _check_window_overlap(category_id, eff_from, eff_to)
    a = new_entity()
    a.update({"category_id": category_id, "tolerance_score": tolerance,
              "acceptance_cap_score": cap, "effective_from": eff_from,
              "effective_to": eff_to, "status": "DRAFT", "created_by": uid})
    store["appetite_statements"][a["id"]] = a
    return ok_object(serialize_appetite(a), 201)


@bp.get("/appetite-statements/<aid>")
def get_appetite(aid):
    authenticate(ALL_ROLES)
    return ok_object(serialize_appetite(get_appetite_or_404(aid)))


@bp.post("/appetite-statements/<aid>/approve")
def approve_appetite(aid):
    uid = authenticate(("RiskManager",))
    a = get_appetite_or_404(aid)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT statement can be approved")
    if uid == a["created_by"]:
        raise ApiError("ERR_SOD_VIOLATION", 422,
                       "Approver must differ from the statement's creator")
    _check_window_overlap(a["category_id"], a["effective_from"], a["effective_to"],
                          exclude_id=a["id"])
    a["status"] = "APPROVED"
    touch(a)
    return ok_object(serialize_appetite(a))


@bp.post("/appetite-statements/<aid>/retire")
def retire_appetite(aid):
    authenticate(("RiskManager",))
    a = get_appetite_or_404(aid)
    if a["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an APPROVED statement can be retired")
    now = clock_now()
    covered = any(
        o for o in store["appetite_statements"].values()
        if o["id"] != a["id"] and o["category_id"] == a["category_id"]
        and o["status"] == "APPROVED"
        and o["effective_from"] <= now < o["effective_to"])
    if not covered:
        raise ApiError("ERR_NO_APPETITE_COVERAGE", 409,
                       "Retiring would leave the category with no APPROVED appetite "
                       "effective at the current clock")
    a["status"] = "RETIRED"
    touch(a)
    return ok_object(serialize_appetite(a))


@bp.get("/appetite-statements/<aid>/tolerance-breaches")
def list_appetite_breaches(aid):
    authenticate(ALL_ROLES)
    get_appetite_or_404(aid)
    items = sorted_by_creation(
        b for b in store["breaches"].values() if b["appetite_statement_id"] == aid)
    page, meta = paginate(items)
    return ok_list([serialize_breach(b) for b in page], meta)

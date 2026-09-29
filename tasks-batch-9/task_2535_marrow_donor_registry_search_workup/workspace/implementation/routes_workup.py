"""Workup cases, the clearance ladder and the collection-method decision
(PRD 3.6, 2.11)."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascades
import serializers
import validate as v
from auth import (ROLE_CENTER, ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS,
                  authenticate)
from envelope import read_pagination, success
from errors import ApiError
from guards import find, render_list
from store import db, touch

bp = Blueprint("registry_workups", __name__)

METHODS = ("PBSC", "MARROW")


@bp.get("/registry/workup-cases/<wid>")
def get_case(wid):
    authenticate(ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_OPS, ROLE_CENTER)
    row = find(db.workup_cases, wid, "ERR_WORKUP_CASE_NOT_FOUND")
    return success(serializers.workup_dict(row))


@bp.get("/registry/workup-cases/<wid>/clearance-items")
def list_clearance_items(wid):
    authenticate(ROLE_DIRECTOR, ROLE_COORDINATOR, ROLE_OPS)
    limit, offset = read_pagination()
    find(db.workup_cases, wid, "ERR_WORKUP_CASE_NOT_FOUND")
    rows = [c for c in db.clearance_items.values() if c["workup_case_id"] == wid]
    return render_list(rows, serializers.clearance_dict, limit, offset)


@bp.get("/registry/clearance-items/<iid>")
def get_clearance_item(iid):
    authenticate(ROLE_DIRECTOR, ROLE_COORDINATOR, ROLE_OPS)
    row = find(db.clearance_items, iid, "ERR_CLEARANCE_ITEM_NOT_FOUND")
    return success(serializers.clearance_dict(row))


@bp.post("/registry/clearance-items/<iid>/result")
def record_clearance_result(iid):
    actor = authenticate(ROLE_DIRECTOR)
    body = v.read_body()
    result = v.req_enum(body, "result", ("PASS", "FAIL"))
    note = v.opt_str(body, "note", 0, 400)

    item = find(db.clearance_items, iid, "ERR_CLEARANCE_ITEM_NOT_FOUND")
    case = db.workup_cases.get(item["workup_case_id"])
    if case is None or case["case_status"] != "OPEN":
        raise ApiError("ERR_WORKUP_CASE_NOT_OPEN")
    if item["result"] != "PENDING":
        raise ApiError("ERR_CLEARANCE_ITEM_ALREADY_RESULTED")

    physical = cascades.clearance_item(case["id"], "PHYSICAL_EXAM")
    panel = cascades.clearance_item(case["id"], "IDM_PANEL")
    if item["item_type"] == "IDM_PANEL":
        if physical is None or physical["result"] != "PASS":
            raise ApiError("ERR_CLEARANCE_ORDER_VIOLATION")
    elif item["item_type"] == "CONSENT":
        if physical is None or physical["result"] != "PASS" or \
                panel is None or panel["result"] != "PASS":
            raise ApiError("ERR_CLEARANCE_ORDER_VIOLATION")

    item["result"] = result
    item["resulted_at"] = db.now()
    item["resulted_by_user_id"] = actor.user_id
    if note is not None:
        item["note"] = note
    if item["item_type"] == "IDM_PANEL" and result == "PASS":
        item["expires_at"] = item["resulted_at"] + timedelta(
            days=calc.IDM_VALIDITY_DAYS)
    touch(item)

    if item["item_type"] == "PHYSICAL_EXAM" and result == "PASS":
        case["physical_cleared_by_user_id"] = actor.user_id
        touch(case)
    cascades.refresh_idm_resulted_at(case)
    cascades.rederive_clearance_status(case)

    if result == "FAIL":
        cascades.clearance_fail_cascade(case, item)

    return success(serializers.clearance_dict(item))


@bp.post("/registry/workup-cases/<wid>/collection-method")
def decide_collection_method(wid):
    actor = authenticate(ROLE_DIRECTOR)
    body = v.read_body()
    method = v.req_enum(body, "method", METHODS)
    v.req_str(body, "rationale", 1)

    case = find(db.workup_cases, wid, "ERR_WORKUP_CASE_NOT_FOUND")

    if case["physical_cleared_by_user_id"] is not None and \
            case["physical_cleared_by_user_id"] == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if case["case_status"] != "OPEN":
        raise ApiError("ERR_WORKUP_CASE_NOT_OPEN")
    if case["collection_method"] is not None or \
            case["logistics_status"] != "UNSCHEDULED":
        raise ApiError("ERR_METHOD_ALREADY_DECIDED")

    candidate = cascades.candidate_of(case)
    donor = cascades.donor_of_candidate(candidate) if candidate else None
    if donor is None or method not in donor["consented_methods"]:
        raise ApiError("ERR_DONOR_METHOD_NOT_CONSENTED")

    case["collection_method"] = method
    case["method_decided_by_user_id"] = actor.user_id
    case["logistics_status"] = "METHOD_SET"
    case["planned_window_days"] = calc.PLANNED_WINDOW_DAYS[method]
    touch(case)
    return success(serializers.workup_dict(case))

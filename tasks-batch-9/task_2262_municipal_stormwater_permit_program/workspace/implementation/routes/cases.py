"""Illicit discharge cases: the cyclic tracing machine."""

from flask import Blueprint

import enums
import middleware as mw
from db import DB, CLOCK, touch
from errors import ApiError
from middleware import body, get_enum, get_str, require
from routes.common import find, listing, one, require_active, settle, snapshot
from services import derive

bp = Blueprint("cases", __name__)

READERS = mw.OPERATIONAL_ROLES
MAX_REOPENS = 3


@bp.get("/illicit-discharge-cases")
def list_cases():
    require(READERS)
    spec = {
        "outfall_id": ("outfall_id", None),
        "origin_observation_id": ("origin_observation_id", None),
        "status": ("status", enums.CASE_STATUS),
    }
    return listing(spec, lambda: list(DB.cases.values()))


@bp.get("/illicit-discharge-cases/<case_id>")
def read_case(case_id):
    require(READERS)
    return one(find("cases", case_id))


@bp.post("/illicit-discharge-cases/<case_id>/start-tracing")
def start_tracing(case_id):
    require([mw.IDDE])
    payload = body()
    method = get_enum(payload, "trace_method", enums.TRACE_METHOD)
    case = find("cases", case_id)
    if case["status"] != "OPEN":
        raise ApiError("ERR_CASE_INVALID_STATE")
    term = derive.term_of_case(case)
    require_active(term)

    case["status"] = "TRACING"
    case["trace_method"] = method
    case["tracing_attempt_count"] = int(case.get("tracing_attempt_count") or 0) + 1
    touch(case)
    settle(term)
    return one(case)


@bp.post("/illicit-discharge-cases/<case_id>/identify-source")
def identify_source(case_id):
    require([mw.IDDE])
    payload = body()
    description = get_str(payload, "source_description")
    party = get_str(payload, "responsible_party")
    case = find("cases", case_id)
    if case["status"] != "TRACING":
        raise ApiError("ERR_CASE_INVALID_STATE")

    case["status"] = "SOURCE_IDENTIFIED"
    case["source_description"] = description
    case["responsible_party"] = party
    touch(case)
    settle(derive.term_of_case(case))
    return one(case)


@bp.post("/illicit-discharge-cases/<case_id>/reopen-tracing")
def reopen_tracing(case_id):
    require([mw.IDDE])
    payload = body()
    get_str(payload, "reason")
    case = find("cases", case_id)
    if case["status"] not in ("SOURCE_IDENTIFIED", "ENFORCEMENT"):
        raise ApiError("ERR_CASE_INVALID_STATE")
    if case["status"] == "ENFORCEMENT":
        live = [
            a
            for a in derive.actions_of_case(case["id"])
            if a["status"] in enums.ENFORCEMENT_LIVE
        ]
        if live:
            raise ApiError("ERR_CASE_HAS_OPEN_ENFORCEMENT")
    if int(case.get("reopen_count") or 0) >= MAX_REOPENS:
        raise ApiError("ERR_REOPEN_LIMIT_REACHED")

    case["status"] = "TRACING"
    case["source_description"] = None
    case["responsible_party"] = None
    case["reopen_count"] = int(case.get("reopen_count") or 0) + 1
    case["tracing_attempt_count"] = int(case.get("tracing_attempt_count") or 0) + 1
    touch(case)
    settle(derive.term_of_case(case))
    return one(case)


@bp.post("/illicit-discharge-cases/<case_id>/resolve")
def resolve_case(case_id):
    require([mw.IDDE])
    payload = body()
    note = get_str(payload, "resolution_note")
    case = find("cases", case_id)
    if case["status"] not in ("SOURCE_IDENTIFIED", "ENFORCEMENT"):
        raise ApiError("ERR_CASE_INVALID_STATE")

    actions = derive.actions_of_case(case["id"])
    if case["status"] == "ENFORCEMENT":
        if any(a["status"] not in ("CLOSED", "RESCINDED") for a in actions):
            raise ApiError("ERR_CASE_HAS_OPEN_ENFORCEMENT")
    else:
        if any(a["status"] in enums.ENFORCEMENT_LIVE for a in actions):
            raise ApiError("ERR_CASE_HAS_OPEN_ENFORCEMENT")

    term = derive.term_of_case(case)
    before = snapshot(term)
    case["status"] = "RESOLVED"
    case["resolved_at"] = CLOCK.stamp()
    case["resolution_note"] = note
    touch(case)
    settle(term, before, CLOCK.now())
    return one(case)

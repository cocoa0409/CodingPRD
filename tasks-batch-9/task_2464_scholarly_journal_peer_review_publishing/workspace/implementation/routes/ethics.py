"""Publication-ethics cases: opening, investigation path, correction and retraction."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
import validate as v
from auth import authorise
from db import now_iso, ordered, store, touch
from errors import ApiError
from response import list_response, object_response
from routes.manuscripts import find_manuscript

bp = Blueprint("ethics", __name__)

CASE_TYPES = ("AUTHORSHIP_DISPUTE", "DATA_AVAILABILITY", "IMAGE_INTEGRITY", "PLAGIARISM")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
# every declared EthicsCase state: a member that is simply not reachable from the
# case's current state is a state error (409), not a body-shape error (400).
ADVANCE_STATES = (
    "OPEN",
    "INVESTIGATION",
    "AUTHOR_RESPONSE_REQUESTED",
    "COMMITTEE_REVIEW",
    "RESOLVED_NO_ACTION",
    "CORRECTION_ISSUED",
    "RETRACTION_APPROVED",
)
RESOLUTIONS = ("NO_ACTION", "CORRECTION", "RETRACTION")
EDITORIAL_ROLES = ("SystemAdmin", "EditorInChief", "HandlingEditor")

# from-state -> permitted to_state values (SCAFFOLD Section 1.2 EthicsCase)
ADVANCE_MAP = {
    "OPEN": ("INVESTIGATION",),
    "INVESTIGATION": ("AUTHOR_RESPONSE_REQUESTED", "COMMITTEE_REVIEW"),
    "AUTHOR_RESPONSE_REQUESTED": ("COMMITTEE_REVIEW",),
}


def find_case(cid):
    case = store.ethics_cases.get(cid)
    if case is None:
        raise ApiError("ERR_ETHICS_CASE_NOT_FOUND")
    return case


@bp.post("/manuscripts/<mid>/ethics-cases")
def open_case(mid):
    actor = authorise("EditorInChief", "SystemAdmin")
    manuscript = find_manuscript(mid)
    data = v.body()
    case_type = v.req_enum(data, "case_type", CASE_TYPES)
    severity = v.req_enum(data, "severity", SEVERITIES)
    description = v.req_string(data, "description")

    if calc.has_unresolved_case(mid, case_type):
        raise ApiError(
            "ERR_DUPLICATE_KEY",
            "This manuscript already has an unresolved %s ethics case." % case_type,
        )

    row = svc.open_ethics_case(manuscript, case_type, severity, description, "MANUAL", actor.user_id)
    return object_response(ser.ethics_case_out(row), 201)


@bp.get("/manuscripts/<mid>/ethics-cases")
def list_manuscript_cases(mid):
    authorise(*EDITORIAL_ROLES)
    find_manuscript(mid)
    limit, offset = v.pagination()
    state = v.query_str("state")
    rows = [
        c
        for c in calc.ethics_cases_of_manuscript(mid)
        if state is None or c["state"] == state
    ]
    rows = ordered(rows)
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.ethics_case_out), limit, offset, len(rows))


@bp.post("/ethics-cases/<cid>/advance")
def advance_case(cid):
    authorise("EditorInChief")
    case = find_case(cid)
    data = v.body()
    to_state = v.req_enum(data, "to_state", ADVANCE_STATES)
    v.opt_string(data, "note")

    svc.guard_ethics_terminal(case)
    if to_state not in ADVANCE_MAP.get(case["state"], ()):
        raise ApiError("ERR_INVALID_ETHICS_CASE_STATE")

    case["state"] = to_state
    touch(case)
    return object_response(ser.ethics_case_out(case), 200)


@bp.post("/ethics-cases/<cid>/resolution")
def resolve_case(cid):
    actor = authorise("EditorInChief")
    case = find_case(cid)
    data = v.body()
    resolution = v.req_enum(data, "resolution", RESOLUTIONS)
    statement = v.req_string(data, "resolution_statement")

    if case.get("_opened_by_user_id") is not None and (
        case["_opened_by_user_id"] == actor.user_id
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    svc.guard_ethics_terminal(case)
    if case["state"] != "COMMITTEE_REVIEW":
        raise ApiError("ERR_INVALID_ETHICS_CASE_STATE")

    manuscript = store.manuscripts.get(case["manuscript_id"])
    if resolution == "CORRECTION":
        if manuscript is None or manuscript["status"] != "PUBLISHED":
            raise ApiError("ERR_RETRACTION_NOT_SUPPORTED")
    elif resolution == "RETRACTION":
        if manuscript is None or manuscript["status"] not in ("PUBLISHED", "CORRECTED"):
            raise ApiError("ERR_RETRACTION_NOT_SUPPORTED")

    if resolution == "NO_ACTION":
        case["state"] = "RESOLVED_NO_ACTION"
    elif resolution == "CORRECTION":
        case["state"] = "CORRECTION_ISSUED"
    else:
        case["state"] = "RETRACTION_APPROVED"
    case["resolution_statement"] = statement
    case["resolved_at"] = now_iso()
    touch(case)

    if resolution == "CORRECTION":
        manuscript["status"] = "CORRECTED"
        touch(manuscript)
    elif resolution == "RETRACTION":
        svc.retraction_cascade(manuscript)
    return object_response(ser.ethics_case_out(case), 200)


@bp.get("/ethics-cases/<cid>")
def get_case(cid):
    authorise(*EDITORIAL_ROLES)
    return object_response(ser.ethics_case_out(find_case(cid)), 200)

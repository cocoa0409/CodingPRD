"""Suspect-product investigations (PRD §3.6).

OPEN -> QUARANTINED -> CLEARED -> OPEN cyclic with a reopen cap of 3;
CONFIRMED_ILLEGITIMATE is terminal. Quarantine/clear/confirm cascade to the
linked case and its units and append QUARANTINE / RELEASE / DECOMMISSION
ledger events. Segregation of duties: the user clearing or confirming must
differ from the user who quarantined.
"""
from flask import Blueprint, g

import db
import errors
from db import store
from errors import ApiError
from middleware import endpoint, ALL_ROLES
from response import ok, created, Paginator
from services import events as event_service
from validation import get_body, req_str, body_fk, path_entity

bp = Blueprint("investigations", __name__)

REOPEN_LIMIT = 3


def _investigation(investigation_id):
    return path_entity(store.suspect_investigations, investigation_id,
                       "SuspectInvestigation")


@bp.route("/wholesale/suspect-investigations", methods=["POST"])
@endpoint(["QualityAssuranceLead"])
def create_investigation():
    body = get_body()
    case = body_fk(body, "case_id", store.serialized_cases, "SerializedCase")
    reason = req_str(body, "opened_reason")
    investigation = {
        "id": db.new_id(),
        "case_id": case["id"],
        "opened_reason": reason,
        "investigation_status": "OPEN",
        "reopen_count": 0,
        "quarantined_by_user_id": None,
    }
    db.new_common(investigation)
    store.suspect_investigations[investigation["id"]] = investigation
    return created(investigation)


@bp.route("/wholesale/suspect-investigations", methods=["GET"])
@endpoint(ALL_ROLES)
def list_investigations():
    pg = Paginator()
    rows = list(store.suspect_investigations.values())
    rows = pg.filter(rows, "case_id")
    rows = pg.filter(rows, "investigation_status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/suspect-investigations/<investigationId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_investigation(investigationId):
    return ok(_investigation(investigationId))


@bp.route("/wholesale/suspect-investigations/<investigationId>/quarantine", methods=["POST"])
@endpoint(["QualityAssuranceLead"])
def quarantine_investigation(investigationId):
    inv = _investigation(investigationId)
    get_body(required=False)
    if inv["investigation_status"] != "OPEN":
        raise ApiError(errors.ERR_INVESTIGATION_NOT_OPEN[0], errors.ERR_INVESTIGATION_NOT_OPEN[1],
                       "Investigation must be OPEN to quarantine")
    case = store.serialized_cases[inv["case_id"]]
    if case["case_status"] not in ("COMMISSIONED", "SHIPPED", "RECEIVED"):
        raise ApiError(errors.ERR_CASE_NOT_QUARANTINABLE[0], errors.ERR_CASE_NOT_QUARANTINABLE[1],
                       "Case must be COMMISSIONED, SHIPPED, or RECEIVED to quarantine")
    inv["investigation_status"] = "QUARANTINED"
    inv["quarantined_by_user_id"] = g.user_id
    db.touch(inv)
    event_service.quarantine_case(case, inv["id"])
    return ok(inv)


def _disposition_gate(inv):
    """Shared gates for clear / confirm-illegitimate: investigation QUARANTINED,
    then segregation of duties, then the linked case actually QUARANTINED."""
    if inv["investigation_status"] != "QUARANTINED":
        raise ApiError(errors.ERR_INVESTIGATION_NOT_QUARANTINED[0],
                       errors.ERR_INVESTIGATION_NOT_QUARANTINED[1],
                       "Investigation must be QUARANTINED to clear or confirm")
    if g.user_id == inv["quarantined_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES[0], errors.ERR_SEGREGATION_OF_DUTIES[1],
                       "The same user may not quarantine and clear/confirm the same investigation")
    case = store.serialized_cases[inv["case_id"]]
    if case["case_status"] != "QUARANTINED":
        raise ApiError(errors.ERR_CASE_NOT_QUARANTINED[0], errors.ERR_CASE_NOT_QUARANTINED[1],
                       "Case must be QUARANTINED for release or decommission cascade")
    return case


@bp.route("/wholesale/suspect-investigations/<investigationId>/clear", methods=["POST"])
@endpoint(["QualityAssuranceLead"])
def clear_investigation(investigationId):
    inv = _investigation(investigationId)
    get_body(required=False)
    case = _disposition_gate(inv)
    inv["investigation_status"] = "CLEARED"
    db.touch(inv)
    event_service.release_case(case)
    return ok(inv)


@bp.route("/wholesale/suspect-investigations/<investigationId>/confirm-illegitimate", methods=["POST"])
@endpoint(["QualityAssuranceLead"])
def confirm_illegitimate(investigationId):
    inv = _investigation(investigationId)
    get_body(required=False)
    case = _disposition_gate(inv)
    inv["investigation_status"] = "CONFIRMED_ILLEGITIMATE"
    db.touch(inv)
    event_service.decommission_quarantined_case(case)
    return ok(inv)


@bp.route("/wholesale/suspect-investigations/<investigationId>/reopen", methods=["POST"])
@endpoint(["QualityAssuranceLead"])
def reopen_investigation(investigationId):
    inv = _investigation(investigationId)
    get_body(required=False)
    if inv["investigation_status"] != "CLEARED":
        raise ApiError(errors.ERR_INVESTIGATION_NOT_CLEARED[0], errors.ERR_INVESTIGATION_NOT_CLEARED[1],
                       "Investigation must be CLEARED to reopen")
    if inv["reopen_count"] >= REOPEN_LIMIT:
        raise ApiError(errors.ERR_REOPEN_LIMIT_REACHED[0], errors.ERR_REOPEN_LIMIT_REACHED[1],
                       "reopen_count has reached 3; investigation may not be reopened again")
    inv["investigation_status"] = "OPEN"
    inv["reopen_count"] += 1
    db.touch(inv)
    return ok(inv)

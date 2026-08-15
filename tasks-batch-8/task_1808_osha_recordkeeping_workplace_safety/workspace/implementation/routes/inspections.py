"""Inspection endpoints (PRD §3.8)."""
from flask import Blueprint

from db import STORE, now_dt
from errors import raise_error, ERR_INVALID_STATE, ERR_CITATIONS_EXIST
from middleware import get_auth, require_roles, RATES_READ_ROLES
from response import success_object, success_list
from services.core import (get_body, req_str, req_enum, req_date, base_fields,
                           bump, serialize, lookup, paginated, query_str)

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = ("PROGRAMMED", "COMPLAINT", "REFERRAL",
                    "FATALITY_CATASTROPHE", "FOLLOW_UP")
SCOPES = ("COMPREHENSIVE", "PARTIAL", "RECORDS_ONLY")


@bp.post("/safety/inspections")
def create_inspection():
    auth = get_auth()
    require_roles(auth, ("SafetyOfficer", "PlatformAdmin"))
    data = get_body()
    establishment_id = req_str(data, "establishment_id")
    opened_on = req_date(data, "opened_on")
    inspection_type = req_enum(data, "inspection_type", INSPECTION_TYPES)
    scope = req_enum(data, "scope", SCOPES)
    lookup(STORE.establishments, establishment_id)
    insp = base_fields()
    insp.update({
        "establishment_id": establishment_id,
        "opened_on": opened_on.isoformat(),
        "inspection_type": inspection_type,
        "scope": scope,
        "status": "OPEN",
        "closed_on": None,
        "_failure_to_abate_exposure": False,
    })
    STORE.inspections[insp["id"]] = insp
    return success_object(serialize(insp), status=201)


@bp.get("/safety/inspections/<inspectionId>")
def get_inspection(inspectionId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    insp = lookup(STORE.inspections, inspectionId)
    return success_object(serialize(insp))


@bp.post("/safety/inspections/<inspectionId>/close")
def close_inspection(inspectionId):
    auth = get_auth()
    require_roles(auth, ("SafetyOfficer",))
    insp = lookup(STORE.inspections, inspectionId)
    # PRD §3.8: once any citation exists the close fails with
    # ERR_CITATIONS_EXIST.
    if any(c["inspection_id"] == insp["id"] for c in STORE.citations.values()):
        raise_error(ERR_CITATIONS_EXIST,
                    "Citations have already been issued under this "
                    "inspection")
    if insp["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    insp["status"] = "CLOSED_NO_CITATION"
    insp["closed_on"] = now_dt().date().isoformat()
    bump(insp)
    return success_object(serialize(insp))


@bp.get("/safety/inspections/<inspectionId>/citations")
def list_inspection_citations(inspectionId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.inspections, inspectionId)
    status = query_str("status")
    items = [c for c in STORE.citations.values()
             if c["inspection_id"] == inspectionId
             and (status is None or c["status"] == status)]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(c) for c in page], limit, offset, total)

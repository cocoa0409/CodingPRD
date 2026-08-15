from flask import Blueprint, request

from db import STORE, CLOCK, bump
from errors import (ApiError, ERR_INVALID_REQUEST,
                    ERR_INCIDENT_INVALID_STATE, ERR_CAMPAIGN_ALREADY_EXISTS,
                    ERR_REKEY_REQUIRES_LOST_CREDENTIAL)
from middleware import authenticate, require_roles, body
from response import ok_object, paginate
from serializers import ser_incident
from validators import get_or_404, req_enum, opt_str
from services import create_campaign, deactivate_credential

bp = Blueprint("incidents", __name__)

STAFF_ROLES = ["SecurityAdmin", "SecurityOfficer", "FrontDesk"]
REVIEW_ROLES = ["SecurityOfficer", "SecurityAdmin"]
RESOLUTION_ACTIONS = ["NONE", "REQUEST_REKEY", "DEACTIVATE_CREDENTIAL"]


@bp.route("/incidents", methods=["GET"])
def list_incidents():
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    args = request.args
    rows = list(STORE["incidents"].values())
    for f in ("building_id", "type", "status", "credential_id", "door_id",
              "alert_id", "responsible_person_id", "campaign_id"):
        v = args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    return paginate(rows, args, ser_incident)


@bp.route("/incidents/<incidentId>", methods=["GET"])
def get_incident(incidentId):
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    inc = get_or_404("incidents", incidentId, "Incident")
    return ok_object(ser_incident(inc))


@bp.route("/incidents/<incidentId>/start-review", methods=["POST"])
def start_review(incidentId):
    ctx = authenticate()
    require_roles(ctx, REVIEW_ROLES)
    inc = get_or_404("incidents", incidentId, "Incident")
    if inc["status"] != "OPEN":
        raise ApiError(ERR_INCIDENT_INVALID_STATE, 409,
                       "Incident is not OPEN")
    inc["status"] = "UNDER_REVIEW"
    bump(inc)
    return ok_object(ser_incident(inc))


@bp.route("/incidents/<incidentId>/resolve", methods=["POST"])
def resolve_incident(incidentId):
    ctx = authenticate()
    require_roles(ctx, REVIEW_ROLES)
    inc = get_or_404("incidents", incidentId, "Incident")
    b = body()
    action = req_enum(b, "resolution_action", RESOLUTION_ACTIONS)
    note = opt_str(b, "resolution_note")
    if inc["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INCIDENT_INVALID_STATE, 409,
                       "Incident is not UNDER_REVIEW")
    # PRD-pinned precondition order for resolve:
    if action == "REQUEST_REKEY":
        if inc["type"] != "LOST_CREDENTIAL" or inc["credential_id"] is None:
            raise ApiError(ERR_REKEY_REQUIRES_LOST_CREDENTIAL, 422,
                           "REQUEST_REKEY requires a LOST_CREDENTIAL "
                           "incident with a credential")
        if inc["campaign_id"] is not None:
            raise ApiError(ERR_CAMPAIGN_ALREADY_EXISTS, 409,
                           "Incident already has a rekey campaign")
    if action == "DEACTIVATE_CREDENTIAL" and inc["credential_id"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "DEACTIVATE_CREDENTIAL requires a credential")
    inc["resolution_action"] = action
    inc["resolution_note"] = note
    if action == "REQUEST_REKEY":
        cred = STORE["credentials"].get(inc["credential_id"])
        building = STORE["buildings"][inc["building_id"]]
        responsible = inc["responsible_person_id"]
        campaign = create_campaign(
            building,
            key_node_id=cred["key_node_id"] if cred else None,
            incident_id=inc["id"],
            bill_to="PERSON" if responsible is not None else "BUILDING",
            bill_person_id=responsible)
        inc["campaign_id"] = campaign["id"]
    elif action == "DEACTIVATE_CREDENTIAL":
        cred = STORE["credentials"].get(inc["credential_id"])
        if cred is not None and cred["status"] in ("ISSUED", "LOST"):
            deactivate_credential(cred, "INCIDENT")
    inc["status"] = "RESOLVED"
    bump(inc)
    return ok_object(ser_incident(inc))


@bp.route("/incidents/<incidentId>/dismiss", methods=["POST"])
def dismiss_incident(incidentId):
    ctx = authenticate()
    require_roles(ctx, REVIEW_ROLES)
    inc = get_or_404("incidents", incidentId, "Incident")
    if inc["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INCIDENT_INVALID_STATE, 409,
                       "Incident is not UNDER_REVIEW")
    inc["status"] = "DISMISSED"
    bump(inc)
    return ok_object(ser_incident(inc))


@bp.route("/incidents/<incidentId>/reopen", methods=["POST"])
def reopen_incident(incidentId):
    ctx = authenticate()
    require_roles(ctx, REVIEW_ROLES)
    inc = get_or_404("incidents", incidentId, "Incident")
    if inc["status"] not in ("RESOLVED", "DISMISSED"):
        raise ApiError(ERR_INCIDENT_INVALID_STATE, 409,
                       "Incident is not RESOLVED or DISMISSED")
    inc["status"] = "UNDER_REVIEW"
    bump(inc)
    return ok_object(ser_incident(inc))

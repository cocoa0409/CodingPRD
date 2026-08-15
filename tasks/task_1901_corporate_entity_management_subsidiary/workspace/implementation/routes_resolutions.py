"""Routes: Resolution drafting, submission, adoption (OCC + SoD), rescission."""
from flask import Blueprint, request

import store
import services as svc
from errors import (
    ERR_INVALID_REQUEST, ERR_RESOLUTION_NOT_FOUND, ERR_ENTITY_NOT_FOUND,
    ERR_OFFICER_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND, ERR_JURISDICTION_NOT_FOUND,
    ERR_GRANT_NOT_FOUND, ERR_ENTITY_ALREADY_DISSOLVED, ERR_RESOLUTION_NOT_DRAFT,
    ERR_RESOLUTION_NOT_SUBMITTED, ERR_RESOLUTION_NOT_ADOPTED,
    ERR_RESOLUTION_NOT_RESCINDABLE, ERR_STALE_VERSION, ERR_SEGREGATION_OF_DUTIES,
    ERR_OFFICER_NOT_ACTIVE, ERR_OFFICE_OCCUPIED,
    raise_err,
)
from middleware import require_roles, get_body, ALL_ROLES
from response import ok_object, paginate, sort_records
from routes_entities import get_entity_or_404

bp = Blueprint("resolutions", __name__)

CS = ["CorporateSecretary"]
CS_FC = ["CorporateSecretary", "FilingCoordinator"]

RESOLUTION_TYPES = {
    "AUTHORIZE_FORMATION", "AUTHORIZE_DISSOLUTION", "REVOKE_DISSOLUTION",
    "AUTHORIZE_QUALIFICATION", "AUTHORIZE_WITHDRAWAL", "APPOINT_OFFICER",
    "REMOVE_OFFICER", "ACCEPT_RESIGNATION", "GRANT_SIGNATURE_AUTHORITY",
    "REVOKE_SIGNATURE_AUTHORITY",
}

_PAYLOAD_FK = {
    "officer_id": (store.officers, ERR_OFFICER_NOT_FOUND),
    "appointment_id": (store.officer_appointments, ERR_APPOINTMENT_NOT_FOUND),
    "jurisdiction_id": (store.jurisdictions, ERR_JURISDICTION_NOT_FOUND),
    "grant_id": (store.grants, ERR_GRANT_NOT_FOUND),
}


@bp.route("/api/entities/<entityId>/resolutions", methods=["POST"])
def create_resolution(entityId):
    user_id, _ = require_roles(CS_FC)
    entity = get_entity_or_404(entityId)
    body = get_body()
    payload = body.get("payload")
    if payload is not None and not isinstance(payload, dict):
        raise_err(ERR_INVALID_REQUEST, "payload must be an object")
    # Priority 3: FK existence (including ids inside payload)
    if isinstance(payload, dict):
        for key, (table, err) in _PAYLOAD_FK.items():
            v = payload.get(key)
            if v is not None and v not in table:
                raise_err(err)
    # Priority 4: schema
    rtype = body.get("resolution_type")
    if rtype not in RESOLUTION_TYPES:
        raise_err(ERR_INVALID_REQUEST, "resolution_type is invalid")
    effective_date = body.get("effective_date")
    if not svc.is_valid_date(effective_date):
        raise_err(ERR_INVALID_REQUEST, "effective_date must be an ISO date")
    payload = payload or {}
    if rtype == "APPOINT_OFFICER":
        if payload.get("officer_id") is None:
            raise_err(ERR_INVALID_REQUEST, "payload.officer_id is required")
        if payload.get("office_title") not in svc.OFFICE_TITLES:
            raise_err(ERR_INVALID_REQUEST, "payload.office_title is invalid")
        if not svc.is_valid_date(payload.get("start_date")):
            raise_err(ERR_INVALID_REQUEST, "payload.start_date must be an ISO date")
    elif rtype in ("REMOVE_OFFICER", "ACCEPT_RESIGNATION"):
        if payload.get("appointment_id") is None:
            raise_err(ERR_INVALID_REQUEST, "payload.appointment_id is required")
    elif rtype in ("AUTHORIZE_QUALIFICATION", "AUTHORIZE_WITHDRAWAL"):
        if payload.get("jurisdiction_id") is None:
            raise_err(ERR_INVALID_REQUEST, "payload.jurisdiction_id is required")
    elif rtype == "GRANT_SIGNATURE_AUTHORITY":
        if payload.get("officer_id") is None:
            raise_err(ERR_INVALID_REQUEST, "payload.officer_id is required")
        if payload.get("scope") not in svc.GRANT_SCOPES:
            raise_err(ERR_INVALID_REQUEST, "payload.scope is invalid")
    elif rtype == "REVOKE_SIGNATURE_AUTHORITY":
        if payload.get("grant_id") is None:
            raise_err(ERR_INVALID_REQUEST, "payload.grant_id is required")
    # Priority 5: parent entity not DISSOLVED
    if entity["status"] == "DISSOLVED":
        raise_err(ERR_ENTITY_ALREADY_DISSOLVED)
    rec = store.new_record()
    rec.update({
        "entity_id": entity["id"],
        "resolution_type": rtype,
        "payload": payload,
        "effective_date": effective_date,
        "drafted_by_user_id": user_id,
        "adopted_by_user_id": None,
        "status": "DRAFT",
    })
    store.resolutions[rec["id"]] = rec
    return ok_object(svc.serialize(rec), 201)


@bp.route("/api/resolutions", methods=["GET"])
def list_resolutions():
    require_roles(ALL_ROLES)
    records = sort_records(list(store.resolutions.values()))
    for param, field in (("entity_id", "entity_id"),
                         ("resolution_type", "resolution_type"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return paginate([svc.serialize(r) for r in records], request.args)


def get_resolution_or_404(resolutionId):
    rec = store.resolutions.get(resolutionId)
    if rec is None:
        raise_err(ERR_RESOLUTION_NOT_FOUND)
    return rec


@bp.route("/api/resolutions/<resolutionId>", methods=["GET"])
def get_resolution(resolutionId):
    require_roles(ALL_ROLES)
    rec = get_resolution_or_404(resolutionId)
    svc.apply_resolution_eval(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/resolutions/<resolutionId>/submit", methods=["POST"])
def submit_resolution(resolutionId):
    require_roles(CS_FC)
    rec = get_resolution_or_404(resolutionId)
    get_body()
    svc.apply_resolution_eval(rec)
    if rec["status"] != "DRAFT":
        raise_err(ERR_RESOLUTION_NOT_DRAFT, "submit requires status == DRAFT")
    entity = store.entities[rec["entity_id"]]
    if entity["status"] == "DISSOLVED":
        raise_err(ERR_ENTITY_ALREADY_DISSOLVED)
    rec["status"] = "SUBMITTED"
    store.touch(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/resolutions/<resolutionId>/return", methods=["POST"])
def return_resolution(resolutionId):
    require_roles(CS)
    rec = get_resolution_or_404(resolutionId)
    get_body()  # optional reason
    svc.apply_resolution_eval(rec)
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_RESOLUTION_NOT_SUBMITTED, "return requires status == SUBMITTED")
    rec["status"] = "DRAFT"
    store.touch(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/resolutions/<resolutionId>/adopt", methods=["POST"])
def adopt_resolution(resolutionId):
    user_id, _ = require_roles(CS)
    rec = get_resolution_or_404(resolutionId)
    body = get_body()
    svc.apply_resolution_eval(rec)
    # Priority 4: body schema
    expected = body.get("expected_entity_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_entity_version is required")
    entity = store.entities[rec["entity_id"]]
    # Priority 5: state gate
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_RESOLUTION_NOT_SUBMITTED, "adopt requires status == SUBMITTED")
    # OCC on the parent entity
    if expected != entity["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_entity_version does not match the entity's current version")
    # Priority 6: segregation of duties
    if user_id == rec["drafted_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Adopter must differ from drafter")
    # Priority 7/8: APPOINT_OFFICER checks
    if rec["resolution_type"] == "APPOINT_OFFICER":
        payload = rec.get("payload") or {}
        officer = store.officers.get(payload.get("officer_id"))
        if officer is None:
            raise_err(ERR_OFFICER_NOT_FOUND)
        if officer["status"] != "ACTIVE":
            raise_err(ERR_OFFICER_NOT_ACTIVE, "Officer is not ACTIVE")
        title = payload.get("office_title")
        if title in svc.SINGLE_HOLDER_TITLES:
            occupied = any(
                a for a in svc.officer_appts_of(entity["id"])
                if a["office_title"] == title and a["status"] == "APPOINTED")
            if occupied:
                raise_err(ERR_OFFICE_OCCUPIED,
                          "Single-holder office is already occupied")
    rec["status"] = "ADOPTED"
    rec["adopted_by_user_id"] = user_id
    store.touch(rec)
    store.touch(entity)  # increments LegalEntity.version by 1
    return ok_object(svc.serialize(rec))


@bp.route("/api/resolutions/<resolutionId>/withdraw", methods=["POST"])
def withdraw_resolution(resolutionId):
    require_roles(CS_FC)
    rec = get_resolution_or_404(resolutionId)
    get_body()
    svc.apply_resolution_eval(rec)
    if rec["status"] != "DRAFT":
        raise_err(ERR_RESOLUTION_NOT_DRAFT, "withdraw requires status == DRAFT")
    rec["status"] = "WITHDRAWN"
    store.touch(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/resolutions/<resolutionId>/rescind", methods=["POST"])
def rescind_resolution(resolutionId):
    require_roles(CS)
    rec = get_resolution_or_404(resolutionId)
    get_body()  # optional reason
    svc.apply_resolution_eval(rec)
    if rec["status"] not in ("ADOPTED", "EFFECTIVE"):
        raise_err(ERR_RESOLUTION_NOT_ADOPTED,
                  "rescind requires status IN {ADOPTED, EFFECTIVE}")
    rtype = rec["resolution_type"]
    if rec["status"] == "EFFECTIVE" and rtype not in ("APPOINT_OFFICER", "GRANT_SIGNATURE_AUTHORITY"):
        raise_err(ERR_RESOLUTION_NOT_RESCINDABLE,
                  "EFFECTIVE resolution of this type is not rescindable")
    entity = store.entities[rec["entity_id"]]
    today_str = svc.fmt_date(store.today())
    if rec["status"] == "EFFECTIVE" and rtype == "APPOINT_OFFICER":
        for appt in svc.officer_appts_of(entity["id"]):
            if appt["resolution_id"] == rec["id"] and appt["status"] == "APPOINTED":
                appt["status"] = "REMOVED"
                appt["end_date"] = today_str
                store.touch(appt)
                svc.append_event(entity["id"], "OFFICER_REMOVED",
                                 {"appointment_id": appt["id"]})
                svc.revoke_officer_grants(entity["id"], appt["officer_id"])
    if rtype == "GRANT_SIGNATURE_AUTHORITY":
        for g in list(store.grants.values()):
            if (g.get("source_resolution_id") == rec["id"]
                    and g["status"] in ("ACTIVE", "SUSPENDED")):
                svc.revoke_grant(g)
    rec["status"] = "RESCINDED"
    store.touch(rec)
    store.touch(entity)  # increments LegalEntity.version by 1
    return ok_object(svc.serialize(rec))

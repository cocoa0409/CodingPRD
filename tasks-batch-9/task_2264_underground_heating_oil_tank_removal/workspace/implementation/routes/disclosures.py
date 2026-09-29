"""Homeowner disclosure notices and the homeowner response."""

from datetime import timedelta

from flask import Blueprint

import calculations as calc
from db import assign, commit, create, db
from errors import ApiError
from middleware import (authenticate, body, filter_arg, opt_id, pagination, req_enum,
                        require_project_owner, resolve)
from response import entity_response, list_response
from services import project as svc

bp = Blueprint("disclosures", __name__)

READ_ROLES = ("ProjectCoordinator", "LicensedSiteProfessional", "ComplianceOfficer",
              "Homeowner")


@bp.post("/disclosures")
def create_disclosure():
    authenticate(("ProjectCoordinator",))
    payload = body()
    project_id = opt_id(payload, "tank_project_id")
    project = resolve("tank_projects", project_id) if project_id else None
    if project is None:
        raise ApiError("ERR_INVALID_REQUEST", "tank_project_id is required.")
    kind = req_enum(payload, "disclosure_kind", calc.DISCLOSURE_KINDS)

    outstanding = [d for d in svc.children("disclosures", project["id"])
                   if d["disclosure_kind"] == kind and d["status"] == "PENDING"]
    if outstanding:
        raise ApiError("ERR_DUPLICATE_DISCLOSURE")

    sent_at = db.now()
    disclosure = create("disclosures", {
        "tank_project_id": project["id"],
        "disclosure_kind": kind,
        "sent_at": sent_at,
        "expires_at": sent_at + timedelta(hours=calc.DISCLOSURE_RESPONSE_WINDOW_HOURS),
        "responded_at": None,
        "response_channel": None,
        "status": "PENDING",
    })
    return entity_response(disclosure, 201)


@bp.get("/disclosures")
def list_disclosures():
    user_id, role = authenticate(READ_ROLES)
    project_id = filter_arg("tank_project_id")
    if role == "Homeowner" and project_id is not None:
        filtered = db.tank_projects.get(project_id)
        if filtered is not None:
            require_project_owner(filtered, user_id, role)
    limit, offset = pagination()
    kind = filter_arg("disclosure_kind")
    status = filter_arg("status")
    rows = list(db.disclosures.values())
    if role == "Homeowner":
        owned = {p["id"] for p in db.tank_projects.values()
                 if p["property_id"] == user_id}
        rows = [r for r in rows if r["tank_project_id"] in owned]
    if project_id is not None:
        rows = [r for r in rows if r["tank_project_id"] == project_id]
    if kind is not None:
        rows = [r for r in rows if r["disclosure_kind"] == kind]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, limit, offset)


@bp.get("/disclosures/<disclosure_id>")
def read_disclosure(disclosure_id):
    user_id, role = authenticate(READ_ROLES)
    disclosure = resolve("disclosures", disclosure_id)
    project = db.tank_projects.get(disclosure["tank_project_id"])
    if project is not None:
        require_project_owner(project, user_id, role)
    return entity_response(disclosure)


@bp.post("/disclosures/<disclosure_id>/respond")
def respond(disclosure_id):
    user_id, role = authenticate(("Homeowner",))
    disclosure = resolve("disclosures", disclosure_id)
    project = db.tank_projects.get(disclosure["tank_project_id"])
    if project is not None:
        require_project_owner(project, user_id, role)

    payload = body()
    response = req_enum(payload, "response", ("ACKNOWLEDGED", "DECLINED"))
    channel = req_enum(payload, "response_channel", calc.RESPONSE_CHANNELS)

    if disclosure["status"] != "PENDING":
        raise ApiError("ERR_DISCLOSURE_STATE_INVALID")

    now = db.now()
    if now > disclosure["expires_at"]:
        # Persist-then-reject: the lapse is recorded before the refusal.
        assign(disclosure, "status", "EXPIRED")
        commit()
        raise ApiError("ERR_DISCLOSURE_EXPIRED")

    assign(disclosure, "responded_at", now)
    assign(disclosure, "response_channel", channel)

    if response == "ACKNOWLEDGED":
        assign(disclosure, "status", "ACKNOWLEDGED")
        if project is not None:
            if (disclosure["disclosure_kind"] == "SWEEP_FINDINGS"
                    and project["status"] == "SURVEYED"):
                assign(project, "status", "DISCLOSED")
            svc.recompute_blockers(project)
    else:
        assign(disclosure, "status", "DECLINED")
        if project is not None:
            if (disclosure["disclosure_kind"] == "SWEEP_FINDINGS"
                    and project["status"] == "SURVEYED"):
                svc.void_project(project)
            else:
                svc.recompute_blockers(project)
    return entity_response(disclosure)

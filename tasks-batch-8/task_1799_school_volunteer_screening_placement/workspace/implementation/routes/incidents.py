"""Incident report endpoints: file, list, read, adjudicate."""

from flask import request

import db
import clock
import services
from errors import (
    APIError, not_found, invalid_request,
    ERR_VOLUNTEER_INVALID_STATE, ERR_INCIDENT_INVALID_STATE,
)
from middleware import require_roles
from pagination import parse_pagination, paginate
from response import success_object, success_list

SEVERITIES = ("LOW", "MEDIUM", "HIGH")
OUTCOMES = ("SUBSTANTIATED", "UNFOUNDED")


def register(app):
    @app.route("/incident-reports", methods=["POST"])
    def create_incident():
        require_roles("CampusAdmin", "DistrictCoordinator")
        body = request.get_json(silent=True) or {}

        # p3 existence: volunteer_id, placement_id
        vid = body.get("volunteer_id")
        if vid is not None and vid not in db.volunteers:
            raise not_found("volunteer_id does not resolve")
        pid = body.get("placement_id")
        if pid is not None and pid not in db.placements:
            raise not_found("placement_id does not resolve")

        # p4 state: volunteer in {ACTIVE, RESCREEN_REQUIRED, CLEARANCE_GRANTED, SUSPENDED}
        if vid is not None:
            vol = db.volunteers[vid]
            if vol["status"] not in ("ACTIVE", "RESCREEN_REQUIRED", "CLEARANCE_GRANTED", "SUSPENDED"):
                raise APIError(ERR_VOLUNTEER_INVALID_STATE,
                               "incident filing requires volunteer in {ACTIVE, RESCREEN_REQUIRED, CLEARANCE_GRANTED, SUSPENDED}", 409)

        # p10 shape
        if vid is None:
            raise invalid_request("volunteer_id is required")
        severity = body.get("severity")
        if severity not in SEVERITIES:
            raise invalid_request("severity must be LOW, MEDIUM, or HIGH")
        description = body.get("description")
        if not isinstance(description, str):
            raise invalid_request("description is required")

        incident = {
            "id": db.new_id(),
            "created_at": clock.now_iso(),
            "updated_at": clock.now_iso(),
            "version": 1,
            "volunteer_id": vid,
            "placement_id": pid,
            "severity": severity,
            "description": description,
            "status": "OPEN",
        }
        db.incident_reports[incident["id"]] = incident

        # HIGH severity auto-suspends volunteers in ACTIVE / RESCREEN_REQUIRED / CLEARANCE_GRANTED
        vol = db.volunteers[vid]
        if severity == "HIGH" and vol["status"] in ("ACTIVE", "RESCREEN_REQUIRED", "CLEARANCE_GRANTED"):
            vol["prior_status"] = vol["status"]
            vol["suspension_incident_id"] = incident["id"]
            vol["status"] = "SUSPENDED"
            services.suspension_cascade(vol)
            services.touch(vol)

        return success_object(incident, 201)

    @app.route("/incident-reports", methods=["GET"])
    def list_incidents():
        require_roles("DistrictCoordinator", "CampusAdmin")
        limit, offset = parse_pagination()
        items = list(db.incident_reports.values())
        vid = request.args.get("volunteer_id")
        pid = request.args.get("placement_id")
        status = request.args.get("status")
        if vid is not None:
            items = [i for i in items if i["volunteer_id"] == vid]
        if pid is not None:
            items = [i for i in items if i["placement_id"] == pid]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)

    @app.route("/incident-reports/<iid>", methods=["GET"])
    def get_incident(iid):
        require_roles("DistrictCoordinator", "CampusAdmin")
        incident = db.incident_reports.get(iid)
        if incident is None:
            raise not_found()
        return success_object(incident, 200)

    @app.route("/incident-reports/<iid>/adjudicate", methods=["POST"])
    def adjudicate_incident(iid):
        require_roles("DistrictCoordinator")
        incident = db.incident_reports.get(iid)
        if incident is None:
            raise not_found()

        # p4 state
        if incident["status"] != "OPEN":
            raise APIError(ERR_INCIDENT_INVALID_STATE,
                           "Adjudication attempted on an incident not in OPEN", 409)

        # p10 shape
        body = request.get_json(silent=True) or {}
        outcome = body.get("outcome")
        if outcome not in OUTCOMES:
            raise invalid_request("outcome must be SUBSTANTIATED or UNFOUNDED")

        vol = db.volunteers[incident["volunteer_id"]]
        now = clock.now()

        if outcome == "SUBSTANTIATED":
            # full removal cascade regardless of whether volunteer was suspended
            if vol["status"] not in ("DENIED", "REMOVED"):
                vol["status"] = "REMOVED"
                services.removal_cascade(vol)
                vol["prior_status"] = None
                vol["suspension_incident_id"] = None
                services.touch(vol)
        else:  # UNFOUNDED
            # reinstate only when this incident caused the current suspension
            if vol["status"] == "SUSPENDED" and vol["suspension_incident_id"] == incident["id"]:
                prior = vol["prior_status"]
                if prior == "ACTIVE":
                    cea = vol["clearance_expires_at"]
                    if cea is not None and clock.parse_iso(cea) > now:
                        vol["status"] = "ACTIVE"
                    else:
                        vol["status"] = "RESCREEN_REQUIRED"
                elif prior == "CLEARANCE_GRANTED":
                    vol["status"] = "CLEARANCE_GRANTED"
                elif prior == "RESCREEN_REQUIRED":
                    vol["status"] = "RESCREEN_REQUIRED"
                else:
                    vol["status"] = prior if prior else vol["status"]
                vol["prior_status"] = None
                vol["suspension_incident_id"] = None
                services.touch(vol)
            # else: volunteer record left unchanged

        incident["status"] = outcome
        services.touch(incident)
        return success_object(incident, 200)

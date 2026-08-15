"""Incidents: report, escalate, resolve — kind-keyed roles and SoD."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES, ERR_VALIDATION,
)
from flask import Blueprint, g, request
from response import respond, respond_list
from services import ser_incident
from util import body, paginate, req_enum, req_int, req_str, touch

bp = Blueprint("incidents", __name__)

KINDS = ("MEDICAL", "BEHAVIORAL")
KIND_ROLE = {"MEDICAL": "MedicalResponder", "BEHAVIORAL": "SiteLead"}
REPORT_ROLES = ("SiteLead", "IntakeStaff", "OutreachWorker", "MedicalResponder")


def get_incident(incident_id):
    i = db.store["incidents"].get(incident_id)
    if i is None:
        raise_err(ERR_NOT_FOUND, f"Incident {incident_id} not found")
    return i


def _check_kind_role(incident):
    expected = KIND_ROLE[incident["kind"]]
    if g.user_role != expected:
        raise_err(
            ERR_FORBIDDEN,
            f"{incident['kind']} incidents are handled only by {expected}",
        )


@bp.route("/incidents", methods=["POST"])
@require_roles(*REPORT_ROLES)
def report_incident():
    b = body()
    act = None
    if b.get("site_activation_id") is not None:
        act = db.store["activations"].get(b["site_activation_id"])
        if act is None:
            raise_err(
                ERR_NOT_FOUND,
                f"SiteActivation {b['site_activation_id']} not found",
            )
    guest = None
    if b.get("guest_id") is not None:
        guest = db.store["guests"].get(b["guest_id"])
        if guest is None:
            raise_err(ERR_NOT_FOUND, f"Guest {b['guest_id']} not found")
    if act is None:
        req_str(b, "site_activation_id")  # raises ERR_VALIDATION when absent
    kind = req_enum(b, "kind", KINDS)
    severity = req_int(b, "severity", min_value=1)
    if severity > 3:
        raise_err(ERR_VALIDATION, "severity must be between 1 and 3")
    now = clock.now()
    i = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "site_activation_id": act["id"],
        "guest_id": guest["id"] if guest else None,
        "kind": kind,
        "severity": severity,
        "reporter_user_id": g.user_id,
        "status": "REPORTED",
        "resolved_by_user_id": None,
        "resolution_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["incidents"][i["id"]] = i
    return respond(ser_incident(i), 201)


@bp.route("/incidents", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_incidents():
    items = list(db.store["incidents"].values())
    act_id = request.args.get("site_activation_id")
    guest_id = request.args.get("guest_id")
    status = request.args.get("status")
    kind = request.args.get("kind")
    if act_id is not None:
        items = [i for i in items if i["site_activation_id"] == act_id]
    if guest_id is not None:
        items = [i for i in items if i["guest_id"] == guest_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if kind is not None:
        items = [i for i in items if i["kind"] == kind]
    items.sort(key=lambda i: (i["created_at"], i["_seq"]))
    page, pagination = paginate([ser_incident(i) for i in items])
    return respond_list(page, pagination)


@bp.route("/incidents/<incident_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_incident(incident_id):
    return respond(ser_incident(get_incident(incident_id)), 200)


@bp.route("/incidents/<incident_id>/escalate", methods=["POST"])
@require_roles("MedicalResponder", "SiteLead")
def escalate_incident(incident_id):
    i = get_incident(incident_id)
    _check_kind_role(i)
    if i["status"] != "REPORTED":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot escalate an incident in status {i['status']}",
        )
    i["status"] = "ESCALATED"
    touch(i)
    if i["kind"] == "BEHAVIORAL" and i["severity"] == 3 and i["guest_id"]:
        for s in db.store["stays"].values():
            if (s["site_activation_id"] == i["site_activation_id"]
                    and s["guest_id"] == i["guest_id"]
                    and s["status"] == "CHECKED_IN"):
                s["status"] = "CHECKED_OUT"
                s["checked_out_at"] = clock.now()
                touch(s)
    return respond(ser_incident(i), 200)


@bp.route("/incidents/<incident_id>/resolve", methods=["POST"])
@require_roles("MedicalResponder", "SiteLead")
def resolve_incident(incident_id):
    i = get_incident(incident_id)
    _check_kind_role(i)
    if i["status"] not in ("REPORTED", "ESCALATED"):
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot resolve an incident in status {i['status']}",
        )
    b = body()
    note = req_str(b, "resolution_note")
    if g.user_id == i["reporter_user_id"]:
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "The reporter cannot resolve their own incident",
        )
    i["status"] = "RESOLVED"
    i["resolved_by_user_id"] = g.user_id
    i["resolution_note"] = note
    touch(i)
    return respond(ser_incident(i), 200)

"""Incidents: report, review fork (dismiss / substantiate cascade), close."""
from flask import Blueprint, request

from db import DB, touch
from errors import ApiError
from middleware import ANY_ROLE, auth
from response import ok, ok_list
from services import base_entity, incident_view, pilot_rotation_entry
from util import body, pagination_args, paginate, req_enum, req_str

bp = Blueprint("incidents", __name__)

INCIDENT_TYPES = ("GROUNDING", "COLLISION", "NEAR_MISS", "EQUIPMENT", "CONDUCT")


def _get_incident(iid):
    inc = DB["incidents"].get(iid)
    if inc is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Incident does not exist")
    return inc


@bp.post("/pilotage/incidents")
def create_incident():
    user_id, role = auth(["Pilot", "Dispatcher"])
    data = body()

    # Body-referenced existence (priority 3) is needed before the pilot
    # ownership check can be evaluated.
    assignment_id = data.get("assignment_id")
    assignment = None
    if isinstance(assignment_id, str):
        assignment = DB["assignments"].get(assignment_id)
    if assignment is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Assignment does not exist")

    # A pilot may report incidents only on their own assignments.
    if role == "Pilot" and assignment["pilot_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN",
            403,
            "Pilot may report incidents only on their own assignments",
        )

    incident_type = req_enum(data, "incident_type", INCIDENT_TYPES)
    description = req_str(data, "description")

    incident = base_entity()
    incident.update(
        {
            "assignment_id": assignment["id"],
            "pilot_id": assignment["pilot_id"],
            "incident_type": incident_type,
            "description": description,
            "corrective_note": None,
            "status": "REPORTED",
        }
    )
    DB["incidents"][incident["id"]] = incident
    return ok(incident_view(incident), status=201)


@bp.get("/pilotage/incidents")
def list_incidents():
    auth(ANY_ROLE)
    limit, offset = pagination_args()
    items = list(DB["incidents"].values())
    for field in ("assignment_id", "pilot_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [i for i in items if i.get(field) == v]
    items.sort(key=lambda i: (i["created_at"], i["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list([incident_view(i) for i in page], total, limit, offset)


@bp.get("/pilotage/incidents/<iid>")
def get_incident(iid):
    auth(ANY_ROLE)
    return ok(incident_view(_get_incident(iid)))


@bp.post("/pilotage/incidents/<iid>/open-review")
def open_review(iid):
    auth(["Investigator"])
    incident = _get_incident(iid)
    if incident["status"] != "REPORTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Incident cannot move to UNDER_REVIEW from {incident['status']}",
        )
    incident["status"] = "UNDER_REVIEW"
    touch(incident)
    return ok(incident_view(incident))


@bp.post("/pilotage/incidents/<iid>/dismiss")
def dismiss(iid):
    auth(["Investigator"])
    incident = _get_incident(iid)
    if incident["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Incident cannot be dismissed from {incident['status']}",
        )
    # Dismissal is terminal and deliberately touches nothing else: pilot,
    # rotation entry, and assignments are left exactly as they stand.
    incident["status"] = "DISMISSED"
    touch(incident)
    return ok(incident_view(incident))


@bp.post("/pilotage/incidents/<iid>/substantiate")
def substantiate(iid):
    auth(["Investigator"])
    incident = _get_incident(iid)
    if incident["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Incident cannot be substantiated from {incident['status']}",
        )
    incident["status"] = "SUBSTANTIATED"
    touch(incident)

    # Suspension cascade.
    # Hop 1: Pilot ACTIVE -> SUSPENDED.
    pilot = DB["pilots"].get(incident["pilot_id"])
    if pilot is not None and pilot["status"] == "ACTIVE":
        pilot["status"] = "SUSPENDED"
        touch(pilot)
    # Hop 2 (caused by the suspension): the pilot's entry -> OFF_BOARD.
    entry = pilot_rotation_entry(incident["pilot_id"])
    if entry is not None and entry["status"] == "IN_ROTATION":
        entry["status"] = "OFF_BOARD"
        touch(entry)
    # Hop 3 (caused by the board removal): every ASSIGNED assignment of the
    # pilot -> RECALLED (recall_count incremented; boat intervals released
    # implicitly as the rows leave the open-state set). In-progress work
    # (EN_ROUTE/ABOARD) is not recalled.
    for a in DB["assignments"].values():
        if a["pilot_id"] == incident["pilot_id"] and a["service_status"] == "ASSIGNED":
            a["service_status"] = "RECALLED"
            a["recall_count"] += 1
            touch(a)
    return ok(incident_view(incident))


@bp.post("/pilotage/incidents/<iid>/close")
def close(iid):
    auth(["Investigator"])
    incident = _get_incident(iid)
    # State guard (priority 5) precedes the structural note requirement.
    if incident["status"] != "SUBSTANTIATED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Incident cannot be closed from {incident['status']}",
        )
    data = body()
    note = data.get("corrective_note")
    if not isinstance(note, str) or not note.strip():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "corrective_note is required and must be non-empty",
        )
    incident["corrective_note"] = note
    incident["status"] = "CLOSED"
    touch(incident)
    return ok(incident_view(incident))

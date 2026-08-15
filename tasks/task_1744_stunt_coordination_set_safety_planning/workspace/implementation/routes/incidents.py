"""Incident: report (with stoppage cascade), investigate, close."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_sequence,
    get_incident,
    gate_posture_incident_report,
    stop_production,
    serialize_incident,
    stamp_new,
    stamp_mutable,
    touch,
    INCIDENT_SEVERITIES,
    default_sort_key,
)
from errors import (
    err,
    ERR_INCIDENT_INVALID_STATE,
    ERR_CROSS_PRODUCTION_REFERENCE,
)
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_nonempty_string,
    v_nullable_id,
    v_enum,
    v_datetime,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("incidents", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
REPORTERS = ["SafetyOfficer", "StuntCoordinator", "DepartmentHead", "ProductionExecutive"]
SAFETY = ["SafetyOfficer"]


def create_incident_record(production_id, sequence_id, severity, occurred_at,
                           description, reporter_user_id):
    incident = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": production_id,
                "sequence_id": sequence_id,
                "severity": severity,
                "occurred_at": occurred_at,
                "description": description,
                "reporter_user_id": reporter_user_id,
                "status": "REPORTED",
                "corrective_action": None,
            }
        )
    )
    store.incidents[incident["id"]] = incident
    # SERIOUS / CRITICAL while ACTIVE stops the production with the full cascade
    prod = store.productions.get(production_id)
    if (
        prod is not None
        and severity in ("SERIOUS", "CRITICAL")
        and prod["posture"] == "ACTIVE"
    ):
        stop_production(prod, incident["id"])
    return incident


@bp.post("/api/incidents")
def create_incident():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "sequence_id": (v_nullable_id, False, None),
            "severity": (v_enum(INCIDENT_SEVERITIES), True, None),
            "occurred_at": (v_datetime, True, None),
            "description": (v_string, True, None),
        },
    )
    user_id, role = auth()
    require_role(role, REPORTERS)

    prod = get_production(data["production_id"])
    seq = None
    if data["sequence_id"] is not None:
        seq = get_sequence(data["sequence_id"])

    gate_posture_incident_report(prod)

    if seq is not None and seq["production_id"] != prod["id"]:
        raise err(ERR_CROSS_PRODUCTION_REFERENCE,
                  "sequence_id must reference a sequence of the same production", 422)

    incident = create_incident_record(
        prod["id"],
        seq["id"] if seq is not None else None,
        data["severity"],
        data["occurred_at"],
        data["description"],
        user_id,
    )
    return ok(serialize_incident(incident), 201)


@bp.get("/api/incidents")
def list_incidents():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    sequence_id = request.args.get("sequence_id")
    severity = request.args.get("severity")
    status = request.args.get("status")
    items = []
    for i in store.incidents.values():
        if production_id is not None and i["production_id"] != production_id:
            continue
        if sequence_id is not None and i["sequence_id"] != sequence_id:
            continue
        if severity is not None and i["severity"] != severity:
            continue
        if status is not None and i["status"] != status:
            continue
        items.append(i)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_incident(i) for i in page], total, limit, offset)


@bp.get("/api/incidents/<iid>")
def get_one_incident(iid):
    _, role = auth()
    require_role(role, READ_ROLES)
    incident = get_incident(iid)
    return ok(serialize_incident(incident), 200)


@bp.post("/api/incidents/<iid>/open-investigation")
def open_investigation(iid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, SAFETY)
    incident = get_incident(iid)
    if incident["status"] != "REPORTED":
        raise err(ERR_INCIDENT_INVALID_STATE,
                  "open-investigation requires status REPORTED", 409)
    incident["status"] = "UNDER_INVESTIGATION"
    touch(incident)
    return ok(serialize_incident(incident), 200)


@bp.post("/api/incidents/<iid>/close")
def close_incident(iid):
    body = get_body()
    data = validate_payload(
        body, {"corrective_action": (v_nonempty_string, True, None)}
    )
    _, role = auth()
    require_role(role, SAFETY)
    incident = get_incident(iid)
    if incident["status"] != "UNDER_INVESTIGATION":
        raise err(ERR_INCIDENT_INVALID_STATE,
                  "close requires status UNDER_INVESTIGATION", 409)
    incident["status"] = "CLOSED"
    incident["corrective_action"] = data["corrective_action"]
    touch(incident)
    return ok(serialize_incident(incident), 200)

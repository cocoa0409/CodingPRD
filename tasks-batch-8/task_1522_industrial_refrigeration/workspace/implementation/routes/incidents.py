"""Incidents and corrective actions: the segregation-of-duties workflow
(PRPR 3.6)."""
from flask import Blueprint

import envelope
from errors import ApiError
from guards import (
    ALL_ROLES,
    apply_filters,
    body_row,
    endpoint,
    operator_employee,
    opt_present,
    paginate,
    pagination,
    path_row,
    req_enum,
    req_instant,
    req_string,
)
from serialize import action_out, has_unverified_actions, incident_out
from store import db, sorted_rows, touch

bp = Blueprint("incidents", __name__)

INCIDENT_SCHEMA = (
    frozenset(["facility_id", "equipment_id", "severity", "description", "reported_by_employee_id"]),
    frozenset(["facility_id", "severity", "description", "reported_by_employee_id"]),
)
ASSIGN_SCHEMA = (
    frozenset(["investigator_employee_id"]),
    frozenset(["investigator_employee_id"]),
)
REOPEN_SCHEMA = (frozenset(["reason"]), frozenset(["reason"]))
ACTION_SCHEMA = (
    frozenset(["incident_id", "description", "assignee_employee_id", "due_at"]),
    frozenset(["incident_id", "description", "assignee_employee_id", "due_at"]),
)
EMPTY_SCHEMA = (frozenset(), frozenset())

INCIDENT_STATUS_VALUES = (
    "REPORTED",
    "UNDER_INVESTIGATION",
    "ACTIONS_ASSIGNED",
    "CLOSED",
    "REOPENED",
)
ACTION_STATUS_VALUES = ("OPEN", "COMPLETED", "VERIFIED")


def _active_employee_of_facility(employee, facility_id):
    return (
        employee is not None
        and employee["facility_id"] == facility_id
        and employee["employment_status"] == "ACTIVE"
    )


@bp.post("/psm/incidents")
@endpoint(["Operator", "ComplianceOfficer"], schema=INCIDENT_SCHEMA)
def report_incident(ctx):
    # step 0 -- payload values
    severity = req_enum(ctx.body, "severity")
    description = req_string(ctx.body, "description")
    # step 2 -- Operator self-attribution pin (and entity-backed identity)
    if ctx.role == "Operator":
        operator_employee(ctx)
        if ctx.body.get("reported_by_employee_id") != ctx.user_id:
            raise ApiError(
                "ERR_FORBIDDEN",
                "An Operator's report must be self-attributed: reported_by_employee_id "
                "must equal X-User-ID.",
            )
    # step 3 -- existence
    facility = body_row(ctx.body, "facilities", "facility_id")
    equipment = None
    if opt_present(ctx.body, "equipment_id"):
        equipment = body_row(ctx.body, "equipment", "equipment_id")
    reporter = body_row(ctx.body, "employees", "reported_by_employee_id")
    # step 9 -- cross-facility referential integrity (and ACTIVE employment)
    if equipment is not None:
        system = db.systems.get(equipment["system_id"])
        if system is None or system["facility_id"] != facility["id"]:
            raise ApiError("ERR_CROSS_FACILITY_REFERENCE")
    if not _active_employee_of_facility(reporter, facility["id"]):
        raise ApiError("ERR_CROSS_FACILITY_REFERENCE")
    row = db.create(
        "incidents",
        {
            "facility_id": facility["id"],
            "equipment_id": equipment["id"] if equipment else None,
            "severity": severity,
            "description": description,
            "reported_by_employee_id": reporter["id"],
            "investigator_employee_id": None,
            "status": "REPORTED",
            "reopen_count": 0,
            "source_leak_event_id": None,
        },
    )
    return envelope.created(incident_out(row))


@bp.get("/psm/incidents/<incident_id>")
@endpoint(ALL_ROLES)
def get_incident(ctx, incident_id):
    return envelope.ok(incident_out(path_row("incidents", incident_id)))


@bp.get("/psm/incidents")
@endpoint(ALL_ROLES)
def list_incidents(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.incidents.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("facility_id", "facility_id", None),
            ("equipment_id", "equipment_id", None),
            ("reported_by_employee_id", "reported_by_employee_id", None),
            ("investigator_employee_id", "investigator_employee_id", None),
            ("source_leak_event_id", "source_leak_event_id", None),
            ("status", "status", INCIDENT_STATUS_VALUES),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [incident_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )


@bp.post("/psm/incidents/<incident_id>/assign-investigator")
@endpoint(["ComplianceOfficer"], schema=ASSIGN_SCHEMA)
def assign_investigator(ctx, incident_id):
    incident = path_row("incidents", incident_id)
    investigator = body_row(ctx.body, "employees", "investigator_employee_id")
    # step 5 -- REPORTED or REOPENED only
    if incident["status"] not in ("REPORTED", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE")
    # step 6 -- segregation of duties: investigator != reporter
    if (
        incident["reported_by_employee_id"] is not None
        and investigator["id"] == incident["reported_by_employee_id"]
    ):
        raise ApiError("ERR_INVESTIGATOR_IS_REPORTER")
    # step 9 -- ACTIVE employee of the incident's facility
    if not _active_employee_of_facility(investigator, incident["facility_id"]):
        raise ApiError("ERR_CROSS_FACILITY_REFERENCE")
    incident["investigator_employee_id"] = investigator["id"]
    incident["status"] = "UNDER_INVESTIGATION"
    touch(incident)
    return envelope.ok(incident_out(incident))


@bp.post("/psm/incidents/<incident_id>/close")
@endpoint(["ComplianceOfficer"], schema=EMPTY_SCHEMA)
def close_incident(ctx, incident_id):
    incident = path_row("incidents", incident_id)
    # step 5 -- close is declared from UNDER_INVESTIGATION or ACTIONS_ASSIGNED
    if incident["status"] not in ("UNDER_INVESTIGATION", "ACTIONS_ASSIGNED"):
        raise ApiError("ERR_INVALID_STATE")
    # step 10 -- a clean sheet: every corrective action VERIFIED
    if has_unverified_actions(incident["id"]):
        raise ApiError("ERR_ACTIONS_OPEN")
    incident["status"] = "CLOSED"
    touch(incident)
    return envelope.ok(incident_out(incident))


@bp.post("/psm/incidents/<incident_id>/reopen")
@endpoint(["ComplianceOfficer"], schema=REOPEN_SCHEMA)
def reopen_incident(ctx, incident_id):
    req_string(ctx.body, "reason")
    incident = path_row("incidents", incident_id)
    # step 5 -- CLOSED only
    if incident["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE")
    incident["status"] = "REOPENED"
    incident["reopen_count"] += 1
    touch(incident)
    return envelope.ok(incident_out(incident))


# ---------------------------------------------------------------------------
# corrective actions
# ---------------------------------------------------------------------------
@bp.post("/psm/corrective-actions")
@endpoint(["ComplianceOfficer"], schema=ACTION_SCHEMA)
def create_action(ctx):
    description = req_string(ctx.body, "description")
    due_at = req_instant(ctx.body, "due_at")
    incident = body_row(ctx.body, "incidents", "incident_id")
    assignee = body_row(ctx.body, "employees", "assignee_employee_id")
    # step 9 -- assignee is an ACTIVE employee of the incident's facility
    if not _active_employee_of_facility(assignee, incident["facility_id"]):
        raise ApiError("ERR_CROSS_FACILITY_REFERENCE")
    row = db.create(
        "corrective_actions",
        {
            "incident_id": incident["id"],
            "description": description,
            "assignee_employee_id": assignee["id"],
            "due_at": due_at,
            "status": "OPEN",
        },
    )
    # first action moves UNDER_INVESTIGATION -> ACTIONS_ASSIGNED automatically
    if incident["status"] == "UNDER_INVESTIGATION":
        incident["status"] = "ACTIONS_ASSIGNED"
        touch(incident)
    return envelope.created(action_out(row))


@bp.get("/psm/corrective-actions/<action_id>")
@endpoint(ALL_ROLES)
def get_action(ctx, action_id):
    return envelope.ok(action_out(path_row("corrective_actions", action_id)))


@bp.get("/psm/corrective-actions")
@endpoint(ALL_ROLES)
def list_actions(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.corrective_actions.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("incident_id", "incident_id", None),
            ("assignee_employee_id", "assignee_employee_id", None),
            ("status", "status", ACTION_STATUS_VALUES),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [action_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )


def _action_and_incident(action_id):
    action = path_row("corrective_actions", action_id)
    incident = db.incidents.get(action["incident_id"])
    return action, incident


@bp.post("/psm/corrective-actions/<action_id>/complete")
@endpoint(["Operator"], schema=EMPTY_SCHEMA)
def complete_action(ctx, action_id):
    # step 2 -- entity-backed identity, then the assignee pin
    operator_employee(ctx)
    action, incident = _action_and_incident(action_id)
    if ctx.user_id != action["assignee_employee_id"]:
        raise ApiError("ERR_FORBIDDEN", "Only the assignee may complete this action.")
    # step 5 -- OPEN only
    if action["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    action["status"] = "COMPLETED"
    touch(action)
    return envelope.ok(action_out(action))


@bp.post("/psm/corrective-actions/<action_id>/verify")
@endpoint(["Operator"], schema=EMPTY_SCHEMA)
def verify_action(ctx, action_id):
    operator_employee(ctx)
    action, incident = _action_and_incident(action_id)
    # step 2 -- the investigator pin
    if incident is None or ctx.user_id != incident["investigator_employee_id"]:
        raise ApiError("ERR_FORBIDDEN", "Only the incident's investigator may verify.")
    # step 5 -- COMPLETED only
    if action["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE")
    # step 6 -- segregation of duties: verifier != completer
    if incident["investigator_employee_id"] == action["assignee_employee_id"]:
        raise ApiError("ERR_VERIFIER_IS_COMPLETER")
    action["status"] = "VERIFIED"
    touch(action)
    return envelope.ok(action_out(action))


@bp.post("/psm/corrective-actions/<action_id>/reject")
@endpoint(["Operator"], schema=EMPTY_SCHEMA)
def reject_action(ctx, action_id):
    operator_employee(ctx)
    action, incident = _action_and_incident(action_id)
    # step 2 -- the investigator pin
    if incident is None or ctx.user_id != incident["investigator_employee_id"]:
        raise ApiError("ERR_FORBIDDEN", "Only the incident's investigator may reject.")
    # step 5 -- COMPLETED only
    if action["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE")
    action["status"] = "OPEN"
    touch(action)
    return envelope.ok(action_out(action))

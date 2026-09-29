"""Subaward proposal, counterparty screening and officer decisions (PRD 3.6)."""

from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import RSO, require, require_any
from routes.common import must_exist, render_list
from services import cascade, enums as E, present, screening

bp = Blueprint("subawards", __name__)

SUBAWARD_TRANSITIONS = (
    ("FLAGGED", "MITIGATED"),
    ("BLOCKED", "MITIGATED"),
    ("CLEARED", "EXECUTED"),
    ("MITIGATED", "EXECUTED"),
    ("PENDING", "TERMINATED"),
    ("CLEARED", "TERMINATED"),
    ("FLAGGED", "TERMINATED"),
    ("BLOCKED", "TERMINATED"),
    ("MITIGATED", "TERMINATED"),
    ("EXECUTED", "TERMINATED"),
)


@bp.post("/subawards")
def create_subaward():
    require(RSO)
    data = validate.body()

    # step 5 — body foreign keys in declaration order
    project = must_exist("project", data.get("project_id"))
    organization = must_exist("organization", data.get("organization_id"))

    scope = validate.req_string(data, "scope")
    amount_cents = validate.req_int(data, "amount_cents")
    if amount_cents <= 0:
        validate.bad("Field 'amount_cents' must be strictly greater than 0.")

    record = db.base_record()
    record.update({
        "project_id": project["id"],
        "organization_id": organization["id"],
        "scope": scope,
        "amount_cents": amount_cents,
        "status": "PENDING",
        "applied_screening_variant": None,
        "screening_designation": None,
        "screening_matched_organization_id": None,
        "screening_match_depth": None,
        "screening_risk_points": None,
        "mitigation_justification": None,
        "executed_at": None,
        "terminated_at": None,
    })
    db.subawards[record["id"]] = record
    cascade.recompute_project(project)
    return response.object_response(present.subaward(record), 201)


@bp.get("/subawards/<subaward_id>")
def read_subaward(subaward_id):
    require_any()
    record = must_exist("subaward", subaward_id)
    return response.object_response(present.subaward(record))


@bp.get("/subawards")
def list_subawards():
    require_any()
    project_id = validate.filter_value("project_id")
    organization_id = validate.filter_value("organization_id")
    status = validate.filter_enum("status", E.SUBAWARD_STATUSES)

    rows = []
    for record in db.ordered(db.subawards.values()):
        if project_id and record["project_id"] != project_id:
            continue
        if organization_id and record["organization_id"] != organization_id:
            continue
        if status and record["status"] != status:
            continue
        rows.append(record)
    return render_list(rows, present.subaward)


@bp.post("/subawards/<subaward_id>/screen")
def screen_subaward(subaward_id):
    require(RSO)
    data = validate.body()
    record = must_exist("subaward", subaward_id)

    variant = validate.req_enum(data, "variant", E.SCREENING_VARIANTS)

    if record["status"] != "PENDING":
        raise ApiError("ERR_INVALID_SUBAWARD_TRANSITION",
                       "Only a PENDING subaward may be screened.")

    outcome = screening.apply_screening(record, variant)
    record["status"] = outcome
    db.touch(record)

    project = db.projects.get(record["project_id"])
    cascade.recompute_project(project)
    if outcome == "BLOCKED" and project is not None:
        cascade.suspend_project_security(project, "SUBAWARD_BLOCKED")
    return response.object_response(present.subaward(record))


@bp.post("/subawards/<subaward_id>/status")
def set_subaward_status(subaward_id):
    require(RSO)
    data = validate.body()
    record = must_exist("subaward", subaward_id)

    to_status = validate.req_enum(data, "to_status", E.SUBAWARD_STATUSES)
    justification = validate.opt_string(data, "mitigation_justification")

    current = record["status"]
    if (current, to_status) not in SUBAWARD_TRANSITIONS:
        raise ApiError("ERR_INVALID_SUBAWARD_TRANSITION",
                       "Subaward status cannot move %s -> %s."
                       % (current, to_status))

    project = db.projects.get(record["project_id"])

    if to_status == "MITIGATED":
        # step 12 — a specially designated national is never mitigable
        if record["screening_designation"] == "SDN":
            raise ApiError("ERR_RESTRICTED_ENTITY_BLOCKED",
                           "An SDN counterparty can only be terminated.")
        if not justification:
            validate.bad("Field 'mitigation_justification' is required to "
                         "mitigate a subaward.")
        record["status"] = "MITIGATED"
        record["mitigation_justification"] = justification
        db.touch(record)
        cascade.recompute_project(project)

    elif to_status == "EXECUTED":
        if project is None or project["security_status"] != "CLEARED":
            raise ApiError("ERR_PROJECT_NOT_CLEARED",
                           "The project's security_status must be CLEARED.")
        record["status"] = "EXECUTED"
        record["executed_at"] = db.clock_str()
        db.touch(record)
        cascade.recompute_project(project)

    else:  # TERMINATED
        record["status"] = "TERMINATED"
        record["terminated_at"] = db.clock_str()
        db.touch(record)
        cascade.recompute_project(project)

    return response.object_response(present.subaward(record))

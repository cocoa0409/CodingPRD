"""Inspection resource: schedule, read, list, complete (PASS/FAIL)."""
from flask import Blueprint, request

import errors
from errors import ApiError
from db import db, common_create_fields, touch
from middleware import require_role, get_json_body
from response import success, list_response
from timeutil import parse_iso8601
import validators as V

bp = Blueprint("inspections", __name__)

ROLE_ALL = {"FieldAdjuster", "Estimator", "ProductionManager"}
KINDS = {"DAMAGE_ASSESSMENT", "PERMIT_FINAL"}
SEVERITIES = {"MINOR", "MODERATE", "TOTAL_LOSS"}
OUTCOMES = {"PASS", "FAIL"}
BUFFER_HOURS = 24


@bp.route("/inspections", methods=["POST"])
def create_inspection():
    require_role({"FieldAdjuster"})
    body = get_json_body()
    job_id = V.require_field(body, "job_id")
    kind = V.require_field(body, "kind")
    scheduled_start = V.require_field(body, "scheduled_start")
    scheduled_end = V.require_field(body, "scheduled_end")
    if not isinstance(job_id, str):
        V.missing_field("job_id")

    # FK resolution (priority 4)
    V.resolve_fk(db.jobs, job_id)
    permit_id = body.get("permit_id")
    if permit_id is not None:
        V.resolve_fk(db.permits, permit_id)

    # enum / range / interval (priority 6)
    V.validate_enum(kind, KINDS, "kind")
    start_dt = parse_iso8601(scheduled_start)
    end_dt = parse_iso8601(scheduled_end)
    if start_dt is None or end_dt is None:
        V.invalid_request("scheduled_start/scheduled_end must be ISO 8601")
    if not (end_dt > start_dt):
        V.invalid_request("scheduled_end must be after scheduled_start")

    # PERMIT_FINAL requires permit_id; DAMAGE_ASSESSMENT must not carry one.
    if kind == "PERMIT_FINAL" and permit_id is None:
        raise ApiError(errors.ERR_PERMIT_FINAL_NEEDS_PERMIT, 422,
                       "PERMIT_FINAL inspection requires permit_id")
    if kind == "DAMAGE_ASSESSMENT" and permit_id is not None:
        raise ApiError(errors.ERR_PERMIT_FINAL_NEEDS_PERMIT, 422,
                       "DAMAGE_ASSESSMENT must not carry permit_id")

    with db.lock:
        # temporal (priority 9): permit-final buffer on the same job
        if kind == "PERMIT_FINAL":
            _check_buffer(job_id, start_dt, end_dt)

        ent = common_create_fields(versioned=True)
        ent.update({
            "job_id": job_id,
            "kind": kind,
            "permit_id": permit_id,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "damage_severity": None,
            "status": "SCHEDULED",
            "outcome": None,
        })
        db.inspections[ent["id"]] = ent
    return success(ent, status=201)


def _check_buffer(job_id, new_start, new_end):
    """Reject if within BUFFER_HOURS of an existing SCHEDULED/PASSED
    PERMIT_FINAL inspection on the same job (closed interval + buffer)."""
    for ins in db.inspections.values():
        if (ins["job_id"] != job_id or ins["kind"] != "PERMIT_FINAL"
                or ins["status"] not in ("SCHEDULED", "PASSED")):
            continue
        e_start = parse_iso8601(ins["scheduled_start"])
        e_end = parse_iso8601(ins["scheduled_end"])
        # order by start; gap_hours = (later.start - earlier.end) in whole hours
        if new_start <= e_start:
            earlier_end, later_start = new_end, e_start
        else:
            earlier_end, later_start = e_end, new_start
        gap_hours = (later_start - earlier_end).total_seconds() / 3600.0
        # exactly BUFFER_HOURS apart is allowed; conflict when gap < BUFFER_HOURS
        if gap_hours < BUFFER_HOURS:
            raise ApiError(errors.ERR_INSPECTION_BUFFER_CONFLICT, 409,
                           "Permit-final inspection buffer conflict")


@bp.route("/inspections/<entity_id>", methods=["GET"])
def get_inspection(entity_id):
    require_role(ROLE_ALL)
    ent = V.find_or_404(db.inspections, entity_id)
    return success(ent, status=200)


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    require_role(ROLE_ALL)
    limit, offset = V.parse_pagination()
    items = list(db.inspections.values())
    for key in ("job_id", "permit_id", "kind", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    items = V.sort_by_created(items)
    page, total = V.paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/inspections/<entity_id>/complete", methods=["POST"])
def complete_inspection(entity_id):
    require_role({"FieldAdjuster"})
    with db.lock:
        ins = V.find_or_404(db.inspections, entity_id)
        body = get_json_body()
        outcome = V.require_field(body, "outcome")
        # enum (priority 6)
        V.validate_enum(outcome, OUTCOMES, "outcome")
        # state (priority 7)
        if ins["status"] != "SCHEDULED":
            raise ApiError(errors.ERR_INVALID_STATE, 409,
                           "Inspection not SCHEDULED")
        if outcome == "PASS":
            if ins["kind"] == "DAMAGE_ASSESSMENT":
                severity = body.get("damage_severity")
                if severity is None:
                    raise ApiError(errors.ERR_SEVERITY_REQUIRED, 422,
                                   "damage_severity required for DAMAGE_ASSESSMENT PASS")
                V.validate_enum(severity, SEVERITIES, "damage_severity")
                ins["damage_severity"] = severity
            else:
                # severity may be supplied for PERMIT_FINAL too; validate if present
                severity = body.get("damage_severity")
                if severity is not None:
                    V.validate_enum(severity, SEVERITIES, "damage_severity")
                    ins["damage_severity"] = severity
            ins["status"] = "PASSED"
            ins["outcome"] = "PASS"
            touch(ins)
            # cascade: PERMIT_FINAL PASS closes an ISSUED permit
            if ins["kind"] == "PERMIT_FINAL" and ins.get("permit_id"):
                permit = db.permits.get(ins["permit_id"])
                if permit is not None and permit["status"] == "ISSUED":
                    permit["status"] = "CLOSED"
                    touch(permit)
        else:  # FAIL
            ins["status"] = "FAILED"
            ins["outcome"] = "FAIL"
            touch(ins)
        return success(ins, status=200)

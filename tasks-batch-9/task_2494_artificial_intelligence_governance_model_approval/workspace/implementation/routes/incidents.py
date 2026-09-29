"""Monitoring incidents: reporting, containment and resolution."""
from flask import Blueprint

import clock
import constants
import db
import errors
import response
import validators as v
from errors import ApiError
from middleware import authorize, current_role, current_user_id
from services import calc, cascades, guards, queries

bp = Blueprint("incidents", __name__)


def _check_regulator_report(incident, use_case):
    """Step 37: SEV1 on a use case that affects individuals must be filed."""
    if incident["severity"] != "SEV1":
        return
    if use_case is None or not use_case["affects_individuals"]:
        return
    if not incident["reported_to_regulator"]:
        raise ApiError(
            errors.ERR_REGULATOR_REPORT_REQUIRED,
            "a SEV1 incident on a use case that affects individuals requires "
            "reported_to_regulator to be true",
        )


# --- 37. POST /monitoring-incidents ------------------------------------
@bp.post("/monitoring-incidents")
@authorize(
    constants.GOVERNANCE_OFFICER,
    constants.SECURITY_REVIEWER,
    constants.PRIVACY_REVIEWER,
    constants.REQUESTER,
)
def report_incident():
    body = v.get_body()
    use_case = guards.resolve_use_case_fk(body)                      # step 7
    use_case_id = v.as_str(body, "use_case_id", required=True)        # step 8
    severity = v.as_enum(body, "severity", constants.SEVERITIES, required=True)
    category = v.as_enum(body, "category", constants.INCIDENT_CATEGORIES, required=True)
    detected_at = v.as_datetime(body, "detected_at", required=True)
    summary = v.as_str(body, "summary", required=True, min_len=1, max_len=1000)
    reported_to_regulator = v.as_bool(body, "reported_to_regulator", default=False)
    guards.check_not_terminal(use_case)                              # step 10

    hours = calc.containment_hours(severity, queries.effective_tier(use_case))
    record = {
        "use_case_id": use_case_id,
        "severity": severity,
        "category": category,
        "detected_at": detected_at,
        "summary": summary,
        "reported_to_regulator": reported_to_regulator,
        "status": "OPEN",
        "containment_hours": hours,
        "containment_deadline_at": clock.plus_hours(detected_at, hours),
        "contained_at": None,
        "resolved_at": None,
        "updated_at": clock.now(),
        "version": 1,
    }
    db.insert(db.monitoring_incidents, record)
    cascades.rederive_monitoring_posture(use_case, current_user_id())
    return response.object_response(record, 201)


# --- 38. GET /monitoring-incidents ------------------------------------
@bp.get("/monitoring-incidents")
@authorize(*constants.ALL_ROLES)
def list_incidents():
    use_case_id = v.query_str("use_case_id")
    status = v.query_str("status")
    severity = v.query_str("severity")
    limit, offset = v.pagination_params()
    records = db.all_of(db.monitoring_incidents)
    if use_case_id is not None:
        records = [r for r in records if r["use_case_id"] == use_case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if severity is not None:
        records = [r for r in records if r["severity"] == severity]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 39. GET /monitoring-incidents/{id} -------------------------------
@bp.get("/monitoring-incidents/<incident_id>")
@authorize(*constants.ALL_ROLES)
def read_incident(incident_id):
    return response.object_response(
        guards.get_record(db.monitoring_incidents, incident_id, "monitoring incident")
    )


# --- 40. POST /monitoring-incidents/{id}/contain ---------------------
@bp.post("/monitoring-incidents/<incident_id>/contain")
@authorize(constants.GOVERNANCE_OFFICER, constants.SECURITY_REVIEWER)
def contain_incident(incident_id):
    incident = guards.get_record(                                    # step 6
        db.monitoring_incidents, incident_id, "monitoring incident"
    )
    body = v.get_body()                                              # step 8
    reported_to_regulator = v.as_bool(body, "reported_to_regulator")
    use_case = db.use_cases.get(incident["use_case_id"])
    guards.check_not_terminal(use_case)                              # step 10
    if incident["status"] not in ("OPEN", "ESCALATED"):                # step 17
        raise ApiError(
            errors.ERR_INCIDENT_NOT_ACTIONABLE,
            "incident %s is %s and cannot be contained"
            % (incident_id, incident["status"]),
        )
    if incident["status"] == "ESCALATED" and current_role() != constants.GOVERNANCE_OFFICER:
        raise ApiError(
            errors.ERR_UNAUTHORIZED,
            "only a GovernanceOfficer may contain an ESCALATED incident",
        )

    # the optional filing update is recorded before the reporting duty is tested
    if reported_to_regulator is not None:
        incident["reported_to_regulator"] = reported_to_regulator

    now = clock.now()
    if incident["status"] == "ESCALATED":
        _check_regulator_report(incident, use_case)                   # step 37
        incident["status"] = "CONTAINED"
        incident["contained_at"] = now
    elif now <= incident["containment_deadline_at"]:
        incident["status"] = "CONTAINED"
        incident["contained_at"] = now
    else:
        incident["status"] = "ESCALATED"
    db.touch(incident)

    if use_case is not None:
        cascades.rederive_monitoring_posture(use_case, current_user_id())
    return response.object_response(incident)


# --- 41. POST /monitoring-incidents/{id}/resolve --------------------
@bp.post("/monitoring-incidents/<incident_id>/resolve")
@authorize(constants.GOVERNANCE_OFFICER)
def resolve_incident(incident_id):
    incident = guards.get_record(                                    # step 6
        db.monitoring_incidents, incident_id, "monitoring incident"
    )
    body = v.get_body()                                              # step 8
    reported_to_regulator = v.as_bool(body, "reported_to_regulator")
    use_case = db.use_cases.get(incident["use_case_id"])
    guards.check_not_terminal(use_case)                              # step 10
    if incident["status"] != "CONTAINED":                              # step 17
        raise ApiError(
            errors.ERR_INCIDENT_NOT_ACTIONABLE,
            "incident %s is %s and cannot be resolved" % (incident_id, incident["status"]),
        )
    if reported_to_regulator is not None:
        incident["reported_to_regulator"] = reported_to_regulator
    _check_regulator_report(incident, use_case)                       # step 37

    incident["status"] = "RESOLVED"
    incident["resolved_at"] = clock.now()
    db.touch(incident)

    if use_case is not None:
        actor = current_user_id()
        posture = cascades.rederive_monitoring_posture(use_case, actor)
        expires_at = use_case["approval_expires_at"]
        if (
            posture == "HEALTHY"
            and use_case["status"] == "SUSPENDED"
            and expires_at is not None
            and clock.now() < expires_at
        ):
            cascades.reinstate_use_case(use_case, actor)
    return response.object_response(incident)

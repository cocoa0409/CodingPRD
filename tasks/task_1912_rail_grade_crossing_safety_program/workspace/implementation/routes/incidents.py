"""Incident report endpoints (PRD §3.3)."""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import (
    ApiError,
    ERR_CROSSING_NOT_FOUND,
    ERR_FRA_NOT_REPORTABLE,
    ERR_INCIDENT_IN_FUTURE,
    ERR_INCIDENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SEVERITY_REQUIRES_FIELD_INVESTIGATION,
)
from helpers import (
    body_or_empty,
    get_or_404,
    opt_int,
    opt_str,
    paginate,
    query_filter,
    reject_unknown,
    req_enum,
    req_instant,
    req_str,
)
from middleware import auth
from response import ok, ok_list
from services import calcs, domain

bp = Blueprint("incident_reports", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")

SEVERITIES = ("CASUALTY", "INJURY", "PROPERTY_DAMAGE", "NEAR_MISS")

INCIDENT_STATUSES = (
    "REPORTED",
    "SCREENED",
    "FIELD_INVESTIGATION",
    "DESK_REVIEW",
    "FINDINGS_ISSUED",
    "FRA_SUBMITTED",
    "CLOSED",
    "REJECTED",
)

CREATE_FIELDS = (
    "crossing_id",
    "occurred_at",
    "severity",
    "fatalities",
    "injuries",
    "property_damage_cents",
    "train_speed_at_impact_mph",
    "narrative",
)


def serialize_incident(r):
    return {
        "id": r["id"],
        "crossing_id": r["crossing_id"],
        "occurred_at": r["occurred_at"],
        "severity": r["severity"],
        "fatalities": r["fatalities"],
        "injuries": r["injuries"],
        "property_damage_cents": r["property_damage_cents"],
        "train_speed_at_impact_mph": r["train_speed_at_impact_mph"],
        "narrative": r["narrative"],
        "fra_reportable": r["fra_reportable"],
        "investigation_track": r["investigation_track"],
        "findings_summary": r["findings_summary"],
        "warning_devices_functioning": r["warning_devices_functioning"],
        "fra_submitted_at": r["fra_submitted_at"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.post("/incident-reports")
def create_incident():
    auth(ALL_ROLES)
    body = body_or_empty()

    # Priority 3: body FK crossing_id.
    crossing_id = body.get("crossing_id")
    if isinstance(crossing_id, str) and crossing_id and crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")

    # Priority 7: request shape.
    reject_unknown(body, CREATE_FIELDS)
    crossing_id = req_str(body, "crossing_id")
    if crossing_id not in store.crossings:
        raise ApiError(ERR_CROSSING_NOT_FOUND, 404, f"Crossing {crossing_id} does not exist")
    occurred_raw, occurred_dt = req_instant(body, "occurred_at")
    severity = req_enum(body, "severity", SEVERITIES)
    fatalities = opt_int(body, "fatalities")
    injuries = opt_int(body, "injuries")
    property_damage_cents = opt_int(body, "property_damage_cents")
    for name, value in (("fatalities", fatalities), ("injuries", injuries),
                        ("property_damage_cents", property_damage_cents)):
        if value is not None and value < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be non-negative")
    fatalities = fatalities if fatalities is not None else 0
    injuries = injuries if injuries is not None else 0
    property_damage_cents = property_damage_cents if property_damage_cents is not None else 0
    train_speed_at_impact_mph = opt_int(body, "train_speed_at_impact_mph")
    narrative = opt_str(body, "narrative")

    # Priority 9 (temporal): occurred_at must not be after the logical clock.
    if occurred_dt > store.clock:
        raise ApiError(ERR_INCIDENT_IN_FUTURE, 422,
                       "occurred_at is after the current logical clock")

    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "crossing_id": crossing_id,
        "occurred_at": occurred_raw,
        "_occurred_dt": occurred_dt,
        "severity": severity,
        "fatalities": fatalities,
        "injuries": injuries,
        "property_damage_cents": property_damage_cents,
        "train_speed_at_impact_mph": train_speed_at_impact_mph,
        "narrative": narrative,
        "fra_reportable": calcs.fra_reportable(fatalities, injuries, property_damage_cents),
        "investigation_track": None,
        "findings_summary": None,
        "warning_devices_functioning": None,
        "fra_submitted_at": None,
        "status": "REPORTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.incidents[rec["id"]] = rec
    return ok(serialize_incident(rec), 201)


@bp.get("/incident-reports")
def list_incidents():
    auth(ALL_ROLES)
    crossing_f = query_filter("crossing_id")
    status_f = query_filter("status")
    items = []
    for r in store.incidents.values():
        if crossing_f is not None and r["crossing_id"] != crossing_f:
            continue
        if status_f is not None and r["status"] != status_f:
            continue
        items.append(r)
    items = sorted(items, key=lambda r: r["created_at"])
    page, meta = paginate([serialize_incident(r) for r in items])
    return ok_list(page, meta)


@bp.get("/incident-reports/<incident_id>")
def get_incident(incident_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.incidents, incident_id, ERR_INCIDENT_NOT_FOUND,
                     f"Incident report {incident_id} does not exist")
    return ok(serialize_incident(rec))


@bp.post("/incident-reports/<incident_id>/transition")
def transition_incident(incident_id):
    auth(["RailSafetyOfficer"])
    rec = get_or_404(store.incidents, incident_id, ERR_INCIDENT_NOT_FOUND,
                     f"Incident report {incident_id} does not exist")
    body = body_or_empty()
    reject_unknown(body, ("to_status",))
    to_status = body.get("to_status")
    if not isinstance(to_status, str) or to_status not in INCIDENT_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"to_status must be one of: {', '.join(INCIDENT_STATUSES)}")

    if to_status == "SCREENED":
        if rec["status"] != "REPORTED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to SCREENED from {rec['status']}")
        rec["status"] = "SCREENED"
    elif to_status == "REJECTED":
        if rec["status"] != "REPORTED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to REJECTED from {rec['status']}")
        rec["status"] = "REJECTED"
    elif to_status == "FIELD_INVESTIGATION":
        if rec["status"] != "SCREENED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to FIELD_INVESTIGATION from {rec['status']}")
        rec["status"] = "FIELD_INVESTIGATION"
        rec["investigation_track"] = "FIELD_INVESTIGATION"
        # Branch side effect: the crossing's diagnostic_review_due flips true.
        crossing = store.crossings.get(rec["crossing_id"])
        if crossing is not None and not crossing["diagnostic_review_due"]:
            crossing["diagnostic_review_due"] = True
            crossing["updated_at"] = now_iso()
    elif to_status == "DESK_REVIEW":
        if rec["status"] != "SCREENED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to DESK_REVIEW from {rec['status']}")
        if rec["severity"] == "CASUALTY":
            raise ApiError(ERR_SEVERITY_REQUIRES_FIELD_INVESTIGATION, 422,
                           "CASUALTY incidents must be assigned FIELD_INVESTIGATION")
        rec["status"] = "DESK_REVIEW"
        rec["investigation_track"] = "DESK_REVIEW"
    elif to_status == "FRA_SUBMITTED":
        if rec["status"] != "FINDINGS_ISSUED":
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to FRA_SUBMITTED from {rec['status']}")
        if not rec["fra_reportable"]:
            raise ApiError(ERR_FRA_NOT_REPORTABLE, 409,
                           "Only FRA-reportable incidents may be submitted to the FRA")
        rec["status"] = "FRA_SUBMITTED"
        rec["fra_submitted_at"] = now_iso()
    elif to_status == "CLOSED":
        if rec["status"] == "FRA_SUBMITTED":
            rec["status"] = "CLOSED"
        elif rec["status"] == "FINDINGS_ISSUED" and not rec["fra_reportable"]:
            rec["status"] = "CLOSED"
        else:
            raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                           f"Cannot move to CLOSED from {rec['status']}")
    else:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Cannot move to {to_status} from {rec['status']}")

    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return ok(serialize_incident(rec))


@bp.post("/incident-reports/<incident_id>/issue-findings")
def issue_findings(incident_id):
    auth(["RailSafetyOfficer"])
    rec = get_or_404(store.incidents, incident_id, ERR_INCIDENT_NOT_FOUND,
                     f"Incident report {incident_id} does not exist")
    if rec["status"] not in ("FIELD_INVESTIGATION", "DESK_REVIEW"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"Findings can be issued only from FIELD_INVESTIGATION or DESK_REVIEW "
                       f"(current: {rec['status']})")
    body = body_or_empty()
    reject_unknown(body, ("findings_summary", "warning_devices_functioning"))
    findings_summary = body.get("findings_summary")
    if not isinstance(findings_summary, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'findings_summary' is required and must be a string")
    warning_devices_functioning = body.get("warning_devices_functioning")
    if not isinstance(warning_devices_functioning, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'warning_devices_functioning' is required and must be a boolean")

    rec["findings_summary"] = findings_summary
    rec["warning_devices_functioning"] = warning_devices_functioning
    rec["status"] = "FINDINGS_ISSUED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()

    # Three-link cascade (PRD §3.3): crossing counts/hazard -> ELIGIBLE project
    # staleness -> program eligible demand.
    crossing = store.crossings.get(rec["crossing_id"])
    if crossing is not None:
        old_hazard = crossing["hazard_score"]
        crossing["hazard_score"] = calcs.hazard_score(
            crossing["exposure_index"],
            domain.live_incident_count_5yr(crossing["id"]),
            crossing["school_bus_count"],
            crossing["sight_distance_rating"],
            crossing["warning_device_class"],
        )
        crossing["updated_at"] = now_iso()
        domain.run_hazard_staleness_cascade(crossing, old_hazard)
    return ok(serialize_incident(rec))

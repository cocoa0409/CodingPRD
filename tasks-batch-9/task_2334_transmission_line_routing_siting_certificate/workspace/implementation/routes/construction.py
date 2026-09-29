"""Construction activities and compliance monitoring (PRD §3.9)."""

from flask import Blueprint, g

import response as resp
from db import insert, store
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import calc, derive
from validation import (
    collection_list,
    find_path,
    fk,
    get_body,
    opt_bool,
    opt_id,
    opt_str,
    req_dt,
    req_enum,
    req_id,
    req_int,
    req_str,
)

bp = Blueprint("construction", __name__)

ACTIVITY_KINDS = ("CLEARING", "FOUNDATION", "STRINGING")
SEVERITIES = ("MINOR", "MAJOR", "SEVERE")
ACTIVITY_TERMINAL = ("COMPLETE", "CANCELLED")
BLOCKING_PERMIT_STATUSES = ("REQUIRED", "APPLIED", "DENIED")


# ------------------------------------------------------------ reads ----
@bp.get("/siting/construction-activities")
@endpoint(ALL_ROLES)
def list_activities():
    rows, pagination = collection_list(
        store.construction_activities,
        ["certificate_id", "segment_id", "status", "activity_kind"],
    )
    return resp.listing(rows, pagination)


@bp.get("/siting/construction-activities/<activity_id>")
@endpoint(ALL_ROLES)
def read_activity(activity_id):
    return resp.ok(find_path(store.construction_activities, activity_id))


@bp.get("/siting/nonconformances")
@endpoint(ALL_ROLES)
def list_nonconformances():
    rows, pagination = collection_list(
        store.nonconformances,
        ["certificate_id", "condition_id", "activity_id", "severity", "status"],
    )
    return resp.listing(rows, pagination)


@bp.get("/siting/nonconformances/<nonconformance_id>")
@endpoint(ALL_ROLES)
def read_nonconformance(nonconformance_id):
    return resp.ok(find_path(store.nonconformances, nonconformance_id))


# ----------------------------------------------------- scheduling ----
@bp.post("/siting/construction-activities")
@endpoint(["Developer"])
def create_activity():
    body = get_body()
    certificate = fk(body, "certificate_id", store.certificates)
    segment = fk(body, "segment_id", store.route_segments)
    certificate_id = req_id(body, "certificate_id")
    segment_id = req_id(body, "segment_id")
    activity_kind = req_enum(body, "activity_kind", ACTIVITY_KINDS)
    crew_count = req_int(body, "crew_count", minimum=1)
    window_start_at = req_dt(body, "window_start_at")
    window_end_at = req_dt(body, "window_end_at")
    if window_end_at <= window_start_at:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'window_end_at' must be after 'window_start_at'.")

    if certificate["posture"] != "ACTIVE":
        raise ApiError(
            "ERR_CERTIFICATE_NOT_ACTIVE", "The certificate's posture is %s." % certificate["posture"]
        )

    if derive.blackout_violation(certificate, segment, window_start_at, window_end_at):
        raise ApiError(
            "ERR_SEASONAL_BLACKOUT_VIOLATION",
            "The window falls inside an active seasonal blackout on a sensitive-habitat segment.",
        )

    limit = derive.effective_crew_limit(certificate, segment)
    committed = derive.overlapping_crew(segment_id, window_start_at, window_end_at)
    if committed + crew_count > limit:
        raise ApiError(
            "ERR_CREW_CAPACITY_EXCEEDED",
            "Peak crew %d exceeds the effective limit of %d." % (committed + crew_count, limit),
        )

    if segment["route_id"] != certificate["certified_route_id"]:
        raise ApiError(
            "ERR_SEGMENT_ROUTE_MISMATCH", "The segment does not belong to the certified route."
        )

    row = insert(
        store.construction_activities,
        {
            "certificate_id": certificate_id,
            "segment_id": segment_id,
            "activity_kind": activity_kind,
            "crew_count": crew_count,
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "status": "SCHEDULED",
            "suspension_reason": None,
            "started_at": None,
            "completed_at": None,
        },
    )
    derive.recompute_segment_crew(segment)
    return resp.created(row)


@bp.post("/siting/construction-activities/<activity_id>/start")
@endpoint(["Developer"])
def start_activity(activity_id):
    activity = find_path(store.construction_activities, activity_id)
    body = get_body()
    opt_str(body, "start_note")

    if activity["status"] in ACTIVITY_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The activity is already %s." % activity["status"])
    if activity["status"] not in ("SCHEDULED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", "No start transition leaves %s." % activity["status"])

    certificate = store.certificates.get(activity["certificate_id"])
    if certificate is None or certificate["posture"] != "ACTIVE":
        posture = certificate["posture"] if certificate else "UNKNOWN"
        raise ApiError("ERR_CERTIFICATE_NOT_ACTIVE", "The certificate's posture is %s." % posture)

    if store.now() < activity["window_start_at"]:
        raise ApiError("ERR_INVALID_STATE", "The activity window has not begun.")

    segment = store.route_segments.get(activity["segment_id"])
    if segment is not None and segment["federal_permit_status"] in BLOCKING_PERMIT_STATUSES:
        raise ApiError(
            "ERR_FEDERAL_PERMIT_MISSING",
            "The segment's federal permit is %s." % segment["federal_permit_status"],
        )

    tracts = derive.tracts_of_segment(activity["segment_id"])
    if not tracts or any(t["acquisition_status"] not in ("AGREED", "AWARDED") for t in tracts):
        raise ApiError(
            "ERR_EASEMENT_NOT_ACQUIRED",
            "Every easement tract on the segment must be AGREED or AWARDED.",
        )

    application = store.applications.get(certificate["application_id"])
    project = store.projects.get(application["project_id"]) if application else None
    funded = project["escrow_funded_cents"] if project is not None else 0
    if funded < certificate["escrow_required_cents"]:
        raise ApiError(
            "ERR_ESCROW_UNDERFUNDED",
            "Project escrow funded %d is below the required %d."
            % (funded, certificate["escrow_required_cents"]),
        )

    fields = {"status": "IN_PROGRESS", "suspension_reason": None}
    if activity["started_at"] is None:
        fields["started_at"] = store.now()
    derive.apply(activity, **fields)

    if segment is not None and segment["construction_state"] in ("PENDING", "HALTED"):
        derive.update(segment, construction_state="ACTIVE")
    if project is not None and project["stage"] == "CERTIFICATED":
        derive.update(project, stage="CONSTRUCTION")
    return resp.created(activity)


@bp.post("/siting/construction-activities/<activity_id>/completion")
@endpoint(["Developer"])
def complete_activity(activity_id):
    activity = find_path(store.construction_activities, activity_id)
    body = get_body()
    opt_str(body, "completion_note")

    if activity["status"] in ACTIVITY_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The activity is already %s." % activity["status"])
    if activity["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS activity may be completed.")

    for finding in store.nonconformances.values():
        if finding["activity_id"] == activity_id and finding["status"] == "OPEN":
            raise ApiError(
                "ERR_OPEN_NONCONFORMANCE", "An open nonconformance references this activity."
            )

    derive.apply(activity, status="COMPLETE", completed_at=store.now())
    segment = store.route_segments.get(activity["segment_id"])
    if segment is not None:
        derive.recompute_segment_crew(segment)
        derive.bubble_segment_completion(segment)
    return resp.created(activity)


@bp.post("/siting/construction-activities/<activity_id>/cancellation")
@endpoint(["Developer"])
def cancel_activity(activity_id):
    activity = find_path(store.construction_activities, activity_id)
    body = get_body()
    req_str(body, "cancellation_reason")

    if activity["status"] in ACTIVITY_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE", "The activity is already %s." % activity["status"])
    if activity["status"] not in ("SCHEDULED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", "No cancellation transition leaves %s." % activity["status"])

    derive.apply(activity, status="CANCELLED")
    segment = store.route_segments.get(activity["segment_id"])
    if segment is not None:
        derive.recompute_segment_crew(segment)
        derive.bubble_segment_completion(segment)
    return resp.created(activity)


# ------------------------------------------------- nonconformances ----
@bp.post("/siting/nonconformances")
@endpoint(["ComplianceMonitor"])
def create_nonconformance():
    body = get_body()
    certificate = fk(body, "certificate_id", store.certificates)
    condition = fk(body, "condition_id", store.certificate_conditions)
    activity = fk(body, "activity_id", store.construction_activities)
    certificate_id = req_id(body, "certificate_id")
    condition_id = req_id(body, "condition_id")
    severity = req_enum(body, "severity", SEVERITIES)
    observation = req_str(body, "observation")
    activity_id = opt_id(body, "activity_id")

    if condition["certificate_id"] != certificate_id or (
        activity is not None and activity["certificate_id"] != certificate_id
    ):
        raise ApiError(
            "ERR_CONDITION_CERTIFICATE_MISMATCH",
            "The condition and any named activity must belong to the named certificate.",
        )

    row = insert(
        store.nonconformances,
        {
            "certificate_id": certificate_id,
            "condition_id": condition_id,
            "activity_id": activity_id,
            "severity": severity,
            "observation": observation,
            "deduction_points": calc.deduction_points(severity, condition["severity_weight"]),
            "status": "OPEN",
            "corrective_action": None,
            "observed_at": store.now(),
        },
    )
    derive.refresh_condition_status(condition)
    derive.refresh_certificate_compliance(certificate)
    _ = g.user_id
    return resp.created(row)


@bp.post("/siting/nonconformances/<nonconformance_id>/correction")
@endpoint(["ComplianceMonitor", "CommissionStaff"])
def correct_nonconformance(nonconformance_id):
    finding = find_path(store.nonconformances, nonconformance_id)
    body = get_body()
    void_finding = opt_bool(body, "void_finding", False)
    corrective_action = opt_str(body, "corrective_action")
    if not void_finding and (corrective_action is None or corrective_action.strip() == ""):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'corrective_action' is required.")

    if finding["status"] in ("CORRECTED", "VOIDED"):
        raise ApiError("ERR_TERMINAL_STATE", "The finding is already %s." % finding["status"])
    if finding["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN finding may be resolved.")

    derive.apply(
        finding,
        status="VOIDED" if void_finding else "CORRECTED",
        corrective_action=corrective_action,
    )

    condition = store.certificate_conditions.get(finding["condition_id"])
    if condition is not None:
        derive.refresh_condition_status(condition)
    certificate = store.certificates.get(finding["certificate_id"])
    if certificate is not None:
        derive.refresh_certificate_compliance(certificate)
    return resp.created(finding)

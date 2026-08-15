"""SupportRequest endpoints and the auto-match selector."""

from flask import Blueprint

import db
import services as svc
from errors import (
    ERR_HOURS_UNRESOLVED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_ELIGIBLE_PLACEMENTS,
    ERR_OPEN_ASSIGNMENTS,
    ERR_STALE_VERSION,
    raise_error,
)
from middleware import ALL_ROLES, authenticate, authorize
from response import success_object
from validation import (
    CRITICALITIES,
    CREDENTIAL_CLASSES,
    SKILL_CODES,
    check_unknown_fields,
    get_body,
    opt_datetime,
    opt_enum,
    req_datetime,
    req_enum,
    req_int,
    req_string,
)
from validators import (
    get_request_or_404,
    incident_gate,
    load_fk_string,
    posture_gate,
)

bp = Blueprint("requests", __name__)

_EDITABLE = {"expected_support_request_version", "headcount_needed", "window_start", "window_end", "criticality", "min_credential_class"}


@bp.post("/vrc/support-requests")
def create_support_request():
    authenticate()
    authorize(["AgencyCoordinator"])
    body = get_body()
    incident_id = load_fk_string(body, "incident_id", db.incidents, "Incident")
    check_unknown_fields(body, {"incident_id", "requesting_agency", "site_name", "required_skill",
                                "min_credential_class", "headcount_needed", "criticality",
                                "window_start", "window_end"})
    if not isinstance(incident_id, str) or not incident_id:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: incident_id")
    requesting_agency = req_string(body, "requesting_agency")
    site_name = req_string(body, "site_name")
    required_skill = req_enum(body, "required_skill", SKILL_CODES)
    min_class = req_enum(body, "min_credential_class", CREDENTIAL_CLASSES)
    headcount = req_int(body, "headcount_needed", minimum=1)
    criticality = req_enum(body, "criticality", CRITICALITIES)
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    if window_end <= window_start:
        raise_error(ERR_INVALID_REQUEST, "window_end must be strictly after window_start")
    incident_gate(db.incidents[incident_id], "support request creation")
    rec = svc.create_record(db.support_requests, {
        "incident_id": incident_id,
        "requesting_agency": requesting_agency,
        "site_name": site_name,
        "required_skill": required_skill,
        "min_credential_class": min_class,
        "headcount_needed": headcount,
        "criticality": criticality,
        "window_start": window_start,
        "window_end": window_end,
        "status": "DRAFT",
    })
    return success_object(svc.support_request_view(rec), 201)


@bp.get("/vrc/support-requests/<requestId>")
def get_support_request(requestId):
    authenticate()
    authorize(ALL_ROLES)
    req = get_request_or_404(requestId)
    return success_object(svc.support_request_view(req))


@bp.put("/vrc/support-requests/<requestId>")
def edit_support_request(requestId):
    authenticate()
    authorize(["AgencyCoordinator"])
    req = get_request_or_404(requestId)
    body = get_body()
    check_unknown_fields(body, _EDITABLE)
    expected = req_int(body, "expected_support_request_version")
    headcount = req_int(body, "headcount_needed", minimum=1) if "headcount_needed" in body else None
    window_start = opt_datetime(body, "window_start")
    window_end = opt_datetime(body, "window_end")
    criticality = opt_enum(body, "criticality", CRITICALITIES)
    min_class = opt_enum(body, "min_credential_class", CREDENTIAL_CLASSES)
    # Shape-level: merged window must keep end strictly after start, and the
    # headcount may never be lowered below the current filled_count.
    merged_start = window_start if window_start is not None else req["window_start"]
    merged_end = window_end if window_end is not None else req["window_end"]
    if merged_end <= merged_start:
        raise_error(ERR_INVALID_REQUEST, "window_end must be strictly after window_start")
    if headcount is not None and headcount < svc.filled_count(req):
        raise_error(ERR_INVALID_REQUEST, "headcount_needed may not be lowered below the current filled_count")
    incident_gate(db.incidents[req["incident_id"]], "support request edit")
    if req["status"] not in ("DRAFT", "OPEN"):
        raise_error(ERR_INVALID_STATE, f"Support request may only be edited from DRAFT or OPEN (current: {req['status']})")
    if expected != req["version"]:
        raise_error(ERR_STALE_VERSION, "expected_support_request_version does not match the request's current version")
    if headcount is not None:
        req["headcount_needed"] = headcount
    if window_start is not None:
        req["window_start"] = window_start
    if window_end is not None:
        req["window_end"] = window_end
    if criticality is not None:
        req["criticality"] = criticality
    if min_class is not None:
        req["min_credential_class"] = min_class
    svc.touch(req)
    svc.recompute_posture(db.incidents[req["incident_id"]])
    return success_object(svc.support_request_view(req))


@bp.post("/vrc/support-requests/<requestId>/publish")
def publish_support_request(requestId):
    authenticate()
    authorize(["AgencyCoordinator"])
    req = get_request_or_404(requestId)
    get_body()
    incident = db.incidents[req["incident_id"]]
    incident_gate(incident, "support request publication")
    if req["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"Support request must be DRAFT to publish (current: {req['status']})")
    req["status"] = "OPEN"
    svc.touch(req)
    svc.recompute_posture(incident)
    return success_object(svc.support_request_view(req))


@bp.post("/vrc/support-requests/<requestId>/auto-match")
def auto_match(requestId):
    authenticate()
    authorize(["IntakeCoordinator"])
    req = get_request_or_404(requestId)
    get_body()
    incident = db.incidents[req["incident_id"]]
    incident_gate(incident, "auto-match")
    posture_gate(incident, allow_restricted=False)
    if req["status"] not in ("OPEN", "MATCHING"):
        raise_error(ERR_INVALID_STATE, f"Auto-match requires an OPEN or MATCHING request (current: {req['status']})")

    live_states = ("PROPOSED", "ACCEPTED", "CONFIRMED", "CHECKED_IN", "COMPLETED")
    live_count = sum(1 for a in svc.assignments_of_request(req["id"]) if a["status"] in live_states)
    need = req["headcount_needed"] - live_count

    # Eligibility filter + candidate ranking
    candidates = []
    for v in db.volunteers.values():
        if v["incident_id"] != incident["id"] or v["status"] != "READY":
            continue
        if any(a["volunteer_id"] == v["id"] and a["support_request_id"] == req["id"]
               and a["status"] in ("PROPOSED", "ACCEPTED", "CONFIRMED", "CHECKED_IN")
               for a in db.assignments.values()):
            continue
        best = None
        for c in db.credentials.values():
            if c["volunteer_id"] == v["id"] and c["skill_code"] == req["required_skill"] and c["status"] == "VERIFIED":
                if best is None or svc.CLASS_RANK[c["credential_class"]] > svc.CLASS_RANK[best]:
                    best = c["credential_class"]
        if best is None or svc.CLASS_RANK[best] < svc.CLASS_RANK[req["min_credential_class"]]:
            continue
        if not svc.has_fresh_cleared_bg(v["id"]):
            continue
        if not svc.has_current_briefing(v["id"]) or not svc.has_active_waiver(v["id"]):
            continue
        candidates.append((v, best))

    def name_key(full_name):
        tokens = full_name.split()
        first = tokens[0] if tokens else ""
        last = tokens[-1] if tokens else ""
        return (last, first)

    # Ranking: verified_hours_total ASC, then created_at ASC, then
    # (last_name, first_name) ASC lexicographic. Entity ids are never consulted.
    candidates.sort(key=lambda pair: (
        svc.verified_hours_total(pair[0]["id"]),
        pair[0]["created_at_dt"],
        name_key(pair[0]["full_name"]),
    ))

    created_ids = []
    pending_per_shift = {}
    if need > 0:
        for v, best in candidates:
            if len(created_ids) >= need:
                break
            eligible = []
            for s in db.shifts.values():
                if s["incident_id"] != incident["id"]:
                    continue
                if s["site_name"] != req["site_name"] or s["status"] != "OPEN_FOR_ROSTER":
                    continue
                if s["start_at"] < req["window_start"] or s["end_at"] > req["window_end"]:
                    continue
                if s["hazard_level"] == "RED" and best != "ADVANCED":
                    continue
                remaining = s["capacity"] - svc.rostered_count(s) - pending_per_shift.get(s["id"], 0)
                if remaining <= 0:
                    continue
                if svc.committed_hours(v["id"]) + svc.hours2(str(s["duration_hours"])) > svc.COMMITTED_HOUR_CAP:
                    continue
                if svc.shift_conflict(v["id"], s):
                    continue
                eligible.append(s)
            if not eligible:
                continue
            eligible.sort(key=lambda s: (s["start_at"], s["created_at_dt"], s["_seq"]))
            chosen = eligible[0]
            rec = svc.create_record(db.assignments, {
                "incident_id": incident["id"],
                "volunteer_id": v["id"],
                "support_request_id": req["id"],
                "site_shift_id": chosen["id"],
                "status": "PROPOSED",
                "origin": "AUTO_MATCH",
                "checked_in_at": None,
                "completed_at": None,
            })
            pending_per_shift[chosen["id"]] = pending_per_shift.get(chosen["id"], 0) + 1
            created_ids.append(rec["id"])

    if not created_ids:
        raise_error(ERR_NO_ELIGIBLE_PLACEMENTS, "Auto-match found zero placeable candidates")

    svc.recompute_request_status(req)  # OPEN -> MATCHING on at least one placement
    svc.recompute_posture(incident)
    remaining_need = req["headcount_needed"] - sum(
        1 for a in svc.assignments_of_request(req["id"]) if a["status"] in live_states
    )
    return success_object({
        "created_assignment_ids": created_ids,
        "proposed_count": len(created_ids),
        "remaining_need": remaining_need,
        "request_status": req["status"],
    }, 201)


@bp.post("/vrc/support-requests/<requestId>/cancel")
def cancel_support_request(requestId):
    authenticate()
    authorize(["AgencyCoordinator"])
    req = get_request_or_404(requestId)
    get_body()
    incident = db.incidents[req["incident_id"]]
    incident_gate(incident, "support request cancellation", demob_allowed=True)
    if req["status"] not in ("OPEN", "MATCHING", "FILLED"):
        raise_error(ERR_INVALID_STATE, f"Support request must be OPEN, MATCHING or FILLED to cancel (current: {req['status']})")
    svc.request_cancel_cascade(req)
    req["status"] = "CANCELLED"
    svc.touch(req)
    svc.recompute_posture(incident)
    return success_object(svc.support_request_view(req))


@bp.post("/vrc/support-requests/<requestId>/complete")
def complete_support_request(requestId):
    authenticate()
    authorize(["AgencyCoordinator"])
    req = get_request_or_404(requestId)
    get_body()
    incident = db.incidents[req["incident_id"]]
    incident_gate(incident, "support request completion", demob_allowed=True)
    if req["status"] not in ("MATCHING", "FILLED"):
        raise_error(ERR_INVALID_STATE, f"Support request must be MATCHING or FILLED to complete (current: {req['status']})")
    mine = svc.assignments_of_request(req["id"])
    if any(a["status"] in ("PROPOSED", "ACCEPTED", "CONFIRMED", "CHECKED_IN") for a in mine):
        raise_error(ERR_OPEN_ASSIGNMENTS, "Request has assignments in non-terminal states")
    for a in mine:
        for e in svc.hour_entries_of_assignment(a["id"]):
            if e["status"] in ("SUBMITTED", "DISPUTED"):
                raise_error(ERR_HOURS_UNRESOLVED, "Request has hour entries still SUBMITTED or DISPUTED")
    req["status"] = "COMPLETED"
    svc.touch(req)
    svc.recompute_posture(incident)
    return success_object(svc.support_request_view(req))

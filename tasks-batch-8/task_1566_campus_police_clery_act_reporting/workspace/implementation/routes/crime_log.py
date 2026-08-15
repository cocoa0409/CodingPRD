"""Daily crime log, public access, and log inspection requests."""

from datetime import timedelta

from flask import Blueprint, g, request

from core import (add_business_days, business_days_between, clock, db,
                  enum_or_422, err, fmt_dt, fmt_dt_short, get_body, get_or_404,
                  mint, now_iso, now_iso_short, paginate, parse_date, pub,
                  require_roles, success, touch, _MISSING)

bp = Blueprint("crime_log", __name__)

DISPOSITIONS = {"OPEN", "INVESTIGATION_PENDING", "CLEARED_BY_ARREST",
                "CLEARED_EXCEPTIONAL", "UNFOUNDED"}

ALLOWED_TRANSITIONS = {
    ("OPEN", "INVESTIGATION_PENDING"),
    ("INVESTIGATION_PENDING", "CLEARED_BY_ARREST"),
    ("INVESTIGATION_PENDING", "CLEARED_EXCEPTIONAL"),
    ("INVESTIGATION_PENDING", "OPEN"),
    ("CLEARED_BY_ARREST", "OPEN"),
    ("CLEARED_EXCEPTIONAL", "OPEN"),
}

INSPECTION_IMMEDIATE_WINDOW_DAYS = 60
INSPECTION_FULFILL_BUSINESS_DAYS = 2
NON_PUBLIC_INCIDENT_STATUSES = {"DRAFT", "WITHDRAWN", "UNFOUNDED"}


def _entry_is_public(entry):
    inc = db.incidents.get(entry["incident_id"])
    if inc is None:
        return False
    return inc["status"] not in NON_PUBLIC_INCIDENT_STATUSES


def _serialize_entry(entry):
    out = pub(entry)
    out["is_public"] = _entry_is_public(entry)
    return out


def _truthy(v):
    return isinstance(v, str) and v.strip().lower() in ("true", "1", "yes")


@bp.get("/daily-crime-log")
@require_roles("Anonymous", "SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def list_log():
    items = list(db.log_entries.values())
    include_unfounded = (g.user_role != "Anonymous"
                         and _truthy(request.args.get("include_unfounded",
                                                      "")))
    if not include_unfounded:
        items = [e for e in items if _entry_is_public(e)]
    fd = request.args.get("from_date")
    if fd is not None:
        fd_d = parse_date(fd)
        items = [e for e in items
                 if e["_date_occurred_dt"].date() >= fd_d]
    td = request.args.get("to_date")
    if td is not None:
        td_d = parse_date(td)
        items = [e for e in items
                 if e["_date_occurred_dt"].date() <= td_d]
    disp = request.args.get("disposition")
    if disp is not None:
        items = [e for e in items if e["disposition"] == disp]
    inc_id = request.args.get("incident_id")
    if inc_id is not None:
        items = [e for e in items if e["incident_id"] == inc_id]
    window, page = paginate(items)
    return success([_serialize_entry(e) for e in window], 200, page)


@bp.get("/daily-crime-log/<eid>")
@require_roles("Anonymous", "SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def get_log_entry(eid):
    entry = get_or_404(db.log_entries, eid)
    if g.user_role == "Anonymous" and not _entry_is_public(entry):
        err("ERR_ENTRY_NOT_PUBLIC", 403,
            "Anonymous access to a non-public crime log entry")
    return success(_serialize_entry(entry), 200)


@bp.patch("/daily-crime-log-entries/<eid>/disposition")
@require_roles("PoliceChief")
def patch_disposition(eid):
    data = get_body()
    target = data.get("disposition", _MISSING)
    if target is _MISSING or not isinstance(target, str):
        err("ERR_INVALID_REQUEST", 400, "Field disposition must be a string")
    entry = get_or_404(db.log_entries, eid)
    if target in DISPOSITIONS:
        if target == "UNFOUNDED":
            err("ERR_INVALID_STATE", 409,
                "UNFOUNDED is set only by the incident unfound cascade")
        if (entry["disposition"], target) not in ALLOWED_TRANSITIONS:
            err("ERR_INVALID_STATE", 409,
                "Disposition transition %s -> %s not allowed"
                % (entry["disposition"], target))
    else:
        err("ERR_VALIDATION_FAILED", 422, "Invalid disposition value")
    entry["disposition"] = target
    entry["last_disposition_change_at"] = now_iso_short()
    # Manual updates use the PATCH time as the decision instant: never
    # self-overdue.
    entry["disposition_update_overdue"] = (
        business_days_between(clock.current, clock.current) > 2)
    touch(entry)
    return success(_serialize_entry(entry), 200)


# ---------------------------------------------------- inspection requests ---

def _due_plus_two_business_days(dt):
    return add_business_days(dt, INSPECTION_FULFILL_BUSINESS_DAYS)


def _serialize_request(req):
    out = pub(req)
    out["is_overdue"] = (req["status"] == "PENDING"
                         and clock.current > req["_due_dt"])
    return out


@bp.post("/daily-crime-log/inspection-requests")
@require_roles("Anonymous")
def create_inspection_request():
    data = get_body()
    for field in ("requester_name", "requester_contact", "from_date",
                  "to_date"):
        v = data.get(field)
        if v is None or not isinstance(v, str):
            err("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % field)
    from_d = parse_date(data["from_date"])
    to_d = parse_date(data["to_date"])
    if to_d < from_d:
        err("ERR_VALIDATION_FAILED", 422, "to_date must be >= from_date")
    requested = clock.current
    matching = [e for e in db.log_entries.values()
                if from_d <= e["_date_occurred_dt"].date() <= to_d]
    # Authoritative CALENDAR_DATE variant.
    threshold = requested.date() - timedelta(
        days=INSPECTION_IMMEDIATE_WINDOW_DAYS)
    if not matching:
        immediate = True
    else:
        earliest = min(e["_date_occurred_dt"].date() for e in matching)
        immediate = earliest >= threshold
    if immediate:
        status = "FULFILLED"
        due_dt = requested
        fulfilled_at = now_iso_short()
    else:
        status = "PENDING"
        due_dt = _due_plus_two_business_days(requested)
        fulfilled_at = None
    # Informational ELAPSED_HOURS variant.
    if not matching:
        prov_all_within = True
    else:
        prov_all_within = all(
            (requested - e["_date_occurred_dt"]).total_seconds() / 3600.0
            <= INSPECTION_IMMEDIATE_WINDOW_DAYS * 24
            for e in matching)
    prov_due_dt = requested if prov_all_within else \
        _due_plus_two_business_days(requested)
    rec = mint({"requester_name": data["requester_name"],
                "requester_contact": data["requester_contact"],
                "from_date": data["from_date"],
                "to_date": data["to_date"],
                "requested_at": now_iso_short(),
                "due_at": fmt_dt_short(due_dt),
                "provisional_due_at": fmt_dt_short(prov_due_dt),
                "fulfilled_at": fulfilled_at,
                "is_overdue": False,
                "status": status,
                "_due_dt": due_dt})
    db.inspection_requests[rec["id"]] = rec
    return success(_serialize_request(rec), 201)


@bp.get("/log-inspection-requests/<rid>")
@require_roles("Anonymous", "CleryCoordinator", "PoliceChief")
def get_inspection_request(rid):
    rec = get_or_404(db.inspection_requests, rid)
    return success(_serialize_request(rec), 200)


@bp.post("/log-inspection-requests/<rid>/fulfill")
@require_roles("CleryCoordinator")
def fulfill_inspection_request(rid):
    rec = get_or_404(db.inspection_requests, rid)
    if rec["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409,
            "Only a PENDING inspection request may be fulfilled")
    rec["status"] = "FULFILLED"
    rec["fulfilled_at"] = now_iso_short()
    touch(rec)
    return success(_serialize_request(rec), 200)

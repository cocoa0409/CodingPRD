import os

from flask import Flask, request, g

from db import db
from errors import ApiError, err
from util import (new_id, new_request_id, iso_ms, parse_iso,
                  success, error_response)
from models import (_base, touch, serialize, FACILITY_TYPES, HIGH_PRIORITY_TYPES)
from auth import get_user_context, require_roles
import services as svc

app = Flask(__name__)

ALL_READ_ROLES = ["CallCenter", "Admin", "Excavator", "LocateTech", "FacilityOwner"]

PAG_DEFAULT_LIMIT = 10
PAG_MIN_LIMIT = 1
PAG_MAX_LIMIT = 100
PAG_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Request lifecycle: stamp a request id/timestamp; parse body.
# ---------------------------------------------------------------------------
@app.before_request
def _before():
    g.request_id = new_request_id()
    g.request_timestamp = db.clock.get()


def _ok(data, status=200, is_array=False, pagination=None):
    return success(data, g.request_id, g.request_timestamp, status=status,
                   is_array=is_array, pagination=pagination)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e.error_id, e.message, g.request_id,
                          db.clock.get(), e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return error_response("ERR_INVALID_REQUEST", "Not found",
                          getattr(g, "request_id", new_request_id()),
                          db.clock.get(), 400)


@app.errorhandler(405)
def _handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed",
                          getattr(g, "request_id", new_request_id()),
                          db.clock.get(), 400)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", str(e),
                          getattr(g, "request_id", new_request_id()),
                          db.clock.get(), 400)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_json():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def paginate(items):
    """items must be pre-sorted. Returns (page, pagination_meta)."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else PAG_DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(offset) if offset is not None else PAG_DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < PAG_MIN_LIMIT:
        limit = PAG_MIN_LIMIT
    if limit > PAG_MAX_LIMIT:
        limit = PAG_MAX_LIMIT
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_created(items):
    return sorted(items, key=lambda r: r["_seq"])


def list_response(store, predicate=None):
    items = [r for r in store.values() if (predicate is None or predicate(r))]
    items = sort_created(items)
    page, meta = paginate(items)
    return _ok([serialize(r) for r in page], is_array=True, pagination=meta)


# --- Existence lookups (raise the right not-found error) ---
def find_excavator(eid):
    r = db.excavators.get(eid)
    if r is None:
        raise err("ERR_EXCAVATOR_NOT_FOUND", "Excavator not found")
    return r


def find_member(mid):
    r = db.member_utilities.get(mid)
    if r is None:
        raise err("ERR_MEMBER_UTILITY_NOT_FOUND", "MemberUtility not found")
    return r


def find_tech(tid):
    r = db.locate_techs.get(tid)
    if r is None:
        raise err("ERR_LOCATE_TECH_NOT_FOUND", "LocateTech not found")
    return r


def find_ticket(tid):
    r = db.locate_tickets.get(tid)
    if r is None:
        raise err("ERR_TICKET_NOT_FOUND", "LocateTicket not found")
    return r


def find_notification(nid):
    r = db.utility_notifications.get(nid)
    if r is None:
        raise err("ERR_NOTIFICATION_NOT_FOUND", "UtilityNotification not found")
    return r


def find_assignment(aid):
    r = db.locate_assignments.get(aid)
    if r is None:
        raise err("ERR_ASSIGNMENT_NOT_FOUND", "LocateAssignment not found")
    return r


def find_markout(mid):
    r = db.mark_outs.get(mid)
    if r is None:
        raise err("ERR_MARKOUT_NOT_FOUND", "MarkOut not found")
    return r


def find_meet(mid):
    r = db.meet_requests.get(mid)
    if r is None:
        raise err("ERR_MEET_REQUEST_NOT_FOUND", "MeetRequest not found")
    return r


def find_damage(did):
    r = db.damage_reports.get(did)
    if r is None:
        raise err("ERR_DAMAGE_REPORT_NOT_FOUND", "DamageReport not found")
    return r


def rectangles_overlap(dig, service):
    return (dig["min_x"] < service["max_x"] and service["min_x"] < dig["max_x"]
            and dig["min_y"] < service["max_y"] and service["min_y"] < dig["max_y"])


def valid_box(box):
    if not isinstance(box, dict):
        return False
    for k in ("min_x", "min_y", "max_x", "max_y"):
        if k not in box or not isinstance(box[k], (int, float)) or isinstance(box[k], bool):
            return False
    return box["max_x"] > box["min_x"] and box["max_y"] > box["min_y"]


# ===========================================================================
# Excavators
# ===========================================================================
@app.route("/excavators", methods=["POST"])
def create_excavator():
    _, role = get_user_context()
    require_roles(role, ["CallCenter", "Admin"])
    body = get_json()
    require_fields(body, ["company_name", "contact_email", "state_code"])
    rec = _base()
    rec.update({
        "company_name": body["company_name"],
        "contact_email": body["contact_email"],
        "state_code": body["state_code"],
        "status": "ACTIVE",
    })
    db.excavators[rec["id"]] = rec
    return _ok(serialize(rec), status=201)


@app.route("/excavators", methods=["GET"])
def list_excavators():
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return list_response(db.excavators)


@app.route("/excavators/<eid>", methods=["GET"])
def get_excavator(eid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return _ok(serialize(find_excavator(eid)))


@app.route("/excavators/<eid>/suspend", methods=["POST"])
def suspend_excavator(eid):
    _, role = get_user_context()
    require_roles(role, ["Admin"])
    rec = find_excavator(eid)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return _ok(serialize(rec))


# ===========================================================================
# Member Utilities
# ===========================================================================
@app.route("/member-utilities", methods=["POST"])
def create_member():
    _, role = get_user_context()
    require_roles(role, ["CallCenter", "Admin"])
    body = get_json()
    require_fields(body, ["name", "facility_type", "service_polygon"])
    if body["facility_type"] not in FACILITY_TYPES:
        raise err("ERR_INVALID_REQUEST", "Invalid facility_type")
    if not valid_box(body["service_polygon"]):
        raise err("ERR_INVALID_GEOMETRY", "Invalid service_polygon")
    emc = body.get("emergency_contact_minutes", 60)
    if emc is None:
        emc = 60
    rec = _base()
    rec.update({
        "name": body["name"],
        "facility_type": body["facility_type"],
        "service_polygon": body["service_polygon"],
        "emergency_contact_minutes": emc,
        "status": "ACTIVE",
    })
    db.member_utilities[rec["id"]] = rec
    return _ok(serialize(rec), status=201)


@app.route("/member-utilities", methods=["GET"])
def list_members():
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return list_response(db.member_utilities)


@app.route("/member-utilities/<mid>", methods=["GET"])
def get_member(mid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return _ok(serialize(find_member(mid)))


@app.route("/member-utilities/<mid>/deactivate", methods=["POST"])
def deactivate_member(mid):
    _, role = get_user_context()
    require_roles(role, ["Admin"])
    rec = find_member(mid)
    rec["status"] = "INACTIVE"
    touch(rec)
    return _ok(serialize(rec))


# ===========================================================================
# Locate Techs
# ===========================================================================
@app.route("/locate-techs", methods=["POST"])
def create_tech():
    _, role = get_user_context()
    require_roles(role, ["CallCenter", "Admin"])
    body = get_json()
    require_fields(body, ["full_name", "member_utility_id", "certified_facility_types"])
    find_member(body["member_utility_id"])
    cft = body["certified_facility_types"]
    if not isinstance(cft, list) or any(t not in FACILITY_TYPES for t in cft):
        raise err("ERR_INVALID_REQUEST", "Invalid certified_facility_types")
    rec = _base()
    rec.update({
        "full_name": body["full_name"],
        "member_utility_id": body["member_utility_id"],
        "certified_facility_types": cft,
        "active_assignment_count": 0,
        "status": "AVAILABLE",
    })
    db.locate_techs[rec["id"]] = rec
    return _ok(serialize(rec), status=201)


@app.route("/locate-techs", methods=["GET"])
def list_techs():
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    muid = request.args.get("member_utility_id")
    pred = (lambda r: r["member_utility_id"] == muid) if muid else None
    return list_response(db.locate_techs, pred)


@app.route("/locate-techs/<tid>", methods=["GET"])
def get_tech(tid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return _ok(serialize(find_tech(tid)))


@app.route("/locate-techs/<tid>/set-off-duty", methods=["POST"])
def set_off_duty(tid):
    _, role = get_user_context()
    require_roles(role, ["Admin", "CallCenter"])
    rec = find_tech(tid)
    rec["status"] = "OFF_DUTY"
    touch(rec)
    return _ok(serialize(rec))


# ===========================================================================
# Locate Tickets
# ===========================================================================
@app.route("/locate-tickets", methods=["POST"])
def create_ticket():
    _, role = get_user_context()
    require_roles(role, ["Excavator", "CallCenter"])
    body = get_json()
    require_fields(body, ["excavator_id", "ticket_type", "dig_polygon", "work_description"])
    find_excavator(body["excavator_id"])
    if body["ticket_type"] not in ("NORMAL", "EMERGENCY"):
        raise err("ERR_INVALID_REQUEST", "Invalid ticket_type")
    if not valid_box(body["dig_polygon"]):
        raise err("ERR_INVALID_GEOMETRY", "Invalid dig_polygon")
    is_white = body.get("is_white_lined", False)
    if is_white is None:
        is_white = False
    rec = _base()
    rec.update({
        "excavator_id": body["excavator_id"],
        "ticket_type": body["ticket_type"],
        "dig_polygon": body["dig_polygon"],
        "work_description": body["work_description"],
        "is_white_lined": bool(is_white),
        "sla_due_at": None,
        "dig_window_opens_at": None,
        "dig_window_expires_at": None,
        "notified_member_count": 0,
        "open_response_count": 0,
        "response_posture": "INTAKE",
        "markout_completed_at": None,
        "status": "INTAKE",
    })
    db.locate_tickets[rec["id"]] = rec
    return _ok(serialize(rec), status=201)


@app.route("/locate-tickets", methods=["GET"])
def list_tickets():
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    exid = request.args.get("excavator_id")
    pred = (lambda r: r["excavator_id"] == exid) if exid else None
    return list_response(db.locate_tickets, pred)


@app.route("/locate-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return _ok(serialize(find_ticket(tid)))


@app.route("/locate-tickets/<tid>/submit", methods=["POST"])
def submit_ticket(tid):
    _, role = get_user_context()
    require_roles(role, ["Excavator", "CallCenter"])
    ticket = find_ticket(tid)
    # precondition order (PRD §3.2)
    if ticket["status"] != "INTAKE":
        raise err("ERR_TICKET_NOT_IN_INTAKE", "Ticket not in INTAKE")
    excavator = db.excavators.get(ticket["excavator_id"])
    if excavator is None:
        raise err("ERR_EXCAVATOR_NOT_FOUND", "Excavator not found")
    if excavator["status"] != "ACTIVE":
        raise err("ERR_EXCAVATOR_SUSPENDED", "Excavator is suspended")
    # intersecting active members
    dig = ticket["dig_polygon"]
    members = [m for m in db.member_utilities.values()
               if m["status"] == "ACTIVE" and rectangles_overlap(dig, m["service_polygon"])]
    if not members:
        raise err("ERR_NO_MEMBERS_IN_AREA", "No active members in dig area")
    # meet request requirement
    if ticket["ticket_type"] == "NORMAL" and not ticket["is_white_lined"]:
        has_meet = any(
            mr["ticket_id"] == tid and mr["status"] in ("REQUESTED", "SCHEDULED", "COMPLETED")
            for mr in db.meet_requests.values())
        if not has_meet:
            raise err("ERR_MEET_REQUEST_REQUIRED", "Meet request required before submit")

    base = db.clock.get()
    sla_due = svc.compute_sla_due_at(ticket["ticket_type"], base)
    ticket["sla_due_at"] = sla_due
    ticket["dig_window_opens_at"] = sla_due

    members = sorted(members, key=lambda m: m["_seq"])
    count = 0
    for m in members:
        note = _base(with_version=False)
        note.update({
            "ticket_id": tid,
            "member_utility_id": m["id"],
            "response_status": "PENDING",
            "due_at": sla_due,
            "is_high_priority": m["facility_type"] in HIGH_PRIORITY_TYPES,
        })
        # Notifications can be mutated (response_status), so give version/updated_at.
        note["updated_at"] = note["created_at"]
        note["version"] = 1
        db.utility_notifications[note["id"]] = note
        count += 1

    ticket["notified_member_count"] = count
    ticket["open_response_count"] = count
    ticket["status"] = "SUBMITTED"
    ticket["response_posture"] = svc.compute_posture(ticket)
    touch(ticket)
    return _ok(serialize(ticket))


@app.route("/locate-tickets/<tid>/close", methods=["POST"])
def close_ticket(tid):
    _, role = get_user_context()
    require_roles(role, ["Excavator"])
    ticket = find_ticket(tid)
    if ticket["status"] != "MARKED":
        raise err("ERR_TICKET_NOT_MARKED", "Ticket not in MARKED")
    if ticket["dig_window_expires_at"] is not None and db.clock.get() > ticket["dig_window_expires_at"]:
        raise err("ERR_DIG_WINDOW_EXPIRED", "Dig window expired")
    ticket["status"] = "CLOSED"
    touch(ticket)
    return _ok(serialize(ticket))


@app.route("/locate-tickets/<tid>/cancel", methods=["POST"])
def cancel_ticket(tid):
    _, role = get_user_context()
    require_roles(role, ["Excavator", "CallCenter"])
    ticket = find_ticket(tid)
    if ticket["status"] not in ("INTAKE", "SUBMITTED"):
        raise err("ERR_TICKET_NOT_CANCELLABLE", "Ticket not cancellable")
    if ticket["status"] == "SUBMITTED":
        active = any(a["ticket_id"] == tid and a["status"] in ("DISPATCHED", "EN_ROUTE")
                     for a in db.locate_assignments.values())
        if active:
            raise err("ERR_ASSIGNMENT_ACTIVE", "An assignment is active")
    ticket["status"] = "CANCELLED"
    touch(ticket)
    # cascade: open meet requests -> DECLINED
    for mr in db.meet_requests.values():
        if mr["ticket_id"] == tid and mr["status"] in ("REQUESTED", "SCHEDULED"):
            mr["status"] = "DECLINED"
            touch(mr)
    return _ok(serialize(ticket))


@app.route("/locate-tickets/<tid>/notifications", methods=["GET"])
def list_ticket_notifications(tid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    find_ticket(tid)
    return list_response(db.utility_notifications, lambda r: r["ticket_id"] == tid)


@app.route("/locate-tickets/<tid>/mark-outs", methods=["GET"])
def list_ticket_markouts(tid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    find_ticket(tid)
    return list_response(db.mark_outs, lambda r: r["ticket_id"] == tid)


@app.route("/locate-tickets/<tid>/meet-requests", methods=["GET"])
def list_ticket_meets(tid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    find_ticket(tid)
    return list_response(db.meet_requests, lambda r: r["ticket_id"] == tid)


@app.route("/locate-tickets/<tid>/damage-reports", methods=["GET"])
def list_ticket_damages(tid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    find_ticket(tid)
    return list_response(db.damage_reports, lambda r: r["ticket_id"] == tid)


# ===========================================================================
# Utility Notifications
# ===========================================================================
@app.route("/utility-notifications", methods=["GET"])
def list_notifications():
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    tid = request.args.get("ticket_id")
    muid = request.args.get("member_utility_id")

    def pred(r):
        if tid and r["ticket_id"] != tid:
            return False
        if muid and r["member_utility_id"] != muid:
            return False
        return True
    return list_response(db.utility_notifications, pred)


@app.route("/utility-notifications/<nid>", methods=["GET"])
def get_notification(nid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return _ok(serialize(find_notification(nid)))


# ===========================================================================
# Positive Responses
# ===========================================================================
@app.route("/positive-responses", methods=["POST"])
def create_positive_response():
    user_id, role = get_user_context()
    require_roles(role, ["FacilityOwner"])
    body = get_json()
    require_fields(body, ["notification_id", "outcome"])
    note = find_notification(body["notification_id"])
    if body["outcome"] not in ("CLEAR", "CONFLICT", "MARKED_BY_OWNER"):
        raise err("ERR_INVALID_REQUEST", "Invalid outcome")
    ticket = db.locate_tickets.get(note["ticket_id"])
    # state: parent ticket must be SUBMITTED
    if ticket is None or ticket["status"] != "SUBMITTED":
        raise err("ERR_TICKET_NOT_ACCEPTING_RESPONSES", "Ticket not accepting responses")
    # state: notification PENDING
    if note["response_status"] != "PENDING":
        raise err("ERR_NOTIFICATION_ALREADY_ANSWERED", "Notification already answered")
    # ownership
    if note["member_utility_id"] != user_id:
        raise err("ERR_NOT_NOTIFICATION_OWNER", "Not the notification owner")

    now = db.clock.get()
    resp = _base(with_version=False)
    resp.update({
        "notification_id": note["id"],
        "outcome": body["outcome"],
        "comment": body.get("comment"),
        "responded_at": now,
        "was_late": note["due_at"] is not None and now > note["due_at"],
    })
    db.positive_responses[resp["id"]] = resp

    note["response_status"] = body["outcome"]
    touch(note)

    # bubble-up
    ticket["open_response_count"] = svc.compute_open_count(ticket["id"])
    ticket["response_posture"] = svc.compute_posture(ticket)
    if ticket["open_response_count"] == 0 and ticket["response_posture"] != "CONFLICT":
        ticket["status"] = "RESPONSES_COMPLETE"
        ticket["response_posture"] = svc.compute_posture(ticket)
    touch(ticket)

    return _ok(serialize(resp), status=201)


@app.route("/positive-responses", methods=["GET"])
def list_positive_responses():
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    nid = request.args.get("notification_id")
    pred = (lambda r: r["notification_id"] == nid) if nid else None
    return list_response(db.positive_responses, pred)


@app.route("/positive-responses/<pid>", methods=["GET"])
def get_positive_response(pid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    r = db.positive_responses.get(pid)
    if r is None:
        raise err("ERR_INVALID_REQUEST", "PositiveResponse not found")
    return _ok(serialize(r))


# ===========================================================================
# Locate Assignments
# ===========================================================================
@app.route("/locate-assignments", methods=["POST"])
def create_assignment():
    _, role = get_user_context()
    require_roles(role, ["FacilityOwner", "CallCenter"])
    body = get_json()
    require_fields(body, ["ticket_id", "notification_id", "locate_tech_id"])
    ticket = find_ticket(body["ticket_id"])
    note = find_notification(body["notification_id"])
    tech = find_tech(body["locate_tech_id"])
    member = db.member_utilities.get(note["member_utility_id"])
    if member is None:
        raise err("ERR_MEMBER_UTILITY_NOT_FOUND", "MemberUtility not found")
    # 5.5 tech AVAILABLE
    if tech["status"] != "AVAILABLE":
        raise err("ERR_TECH_OFF_DUTY", "Tech is off duty")
    # 6 tech certified
    if member["facility_type"] not in tech["certified_facility_types"]:
        raise err("ERR_TECH_NOT_CERTIFIED", "Tech not certified for facility type")

    now = db.clock.get()
    deadline = svc.compute_assignment_deadline(ticket, member, note, tech, now)
    rec = _base()
    rec.update({
        "ticket_id": ticket["id"],
        "notification_id": note["id"],
        "locate_tech_id": tech["id"],
        "dispatched_at": now,
        "sla_deadline_at": deadline,
        "completed_at": None,
        "sla_breached": False,
        "status": "DISPATCHED",
    })
    db.locate_assignments[rec["id"]] = rec
    tech["active_assignment_count"] += 1
    touch(tech)
    return _ok(serialize(rec), status=201)


@app.route("/locate-assignments", methods=["GET"])
def list_assignments():
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    tid = request.args.get("ticket_id")
    nid = request.args.get("notification_id")
    lid = request.args.get("locate_tech_id")

    def pred(r):
        if tid and r["ticket_id"] != tid:
            return False
        if nid and r["notification_id"] != nid:
            return False
        if lid and r["locate_tech_id"] != lid:
            return False
        return True
    return list_response(db.locate_assignments, pred)


@app.route("/locate-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return _ok(serialize(find_assignment(aid)))


@app.route("/locate-assignments/<aid>/en-route", methods=["POST"])
def assignment_en_route(aid):
    user_id, role = get_user_context()
    require_roles(role, ["LocateTech"])
    a = find_assignment(aid)
    if a["status"] != "DISPATCHED":
        raise err("ERR_ASSIGNMENT_NOT_DISPATCHED", "Assignment not dispatched")
    if a["locate_tech_id"] != user_id:
        raise err("ERR_NOT_ASSIGNMENT_TECH", "Not the assignment tech")
    a["status"] = "EN_ROUTE"
    touch(a)
    return _ok(serialize(a))


@app.route("/locate-assignments/<aid>/complete", methods=["POST"])
def assignment_complete(aid):
    user_id, role = get_user_context()
    require_roles(role, ["LocateTech"])
    a = find_assignment(aid)
    if a["status"] != "EN_ROUTE":
        raise err("ERR_ASSIGNMENT_NOT_EN_ROUTE", "Assignment not en route")
    if a["locate_tech_id"] != user_id:
        raise err("ERR_NOT_ASSIGNMENT_TECH", "Not the assignment tech")
    has_complete = any(m["assignment_id"] == aid and m["status"] == "COMPLETE"
                       for m in db.mark_outs.values())
    if not has_complete:
        raise err("ERR_MARKOUT_NOT_COMPLETE", "No COMPLETE mark-out for assignment")
    now = db.clock.get()
    a["completed_at"] = now
    a["sla_breached"] = a["sla_deadline_at"] is not None and now > a["sla_deadline_at"]
    a["status"] = "COMPLETED"
    touch(a)
    tech = db.locate_techs.get(a["locate_tech_id"])
    if tech:
        tech["active_assignment_count"] = max(0, tech["active_assignment_count"] - 1)
        touch(tech)
    return _ok(serialize(a))


@app.route("/locate-assignments/<aid>/cancel", methods=["POST"])
def assignment_cancel(aid):
    _, role = get_user_context()
    require_roles(role, ["FacilityOwner", "CallCenter"])
    a = find_assignment(aid)
    if a["status"] not in ("DISPATCHED", "EN_ROUTE"):
        raise err("ERR_ASSIGNMENT_NOT_CANCELLABLE", "Assignment not cancellable")
    a["status"] = "CANCELLED"
    touch(a)
    tech = db.locate_techs.get(a["locate_tech_id"])
    if tech:
        tech["active_assignment_count"] = max(0, tech["active_assignment_count"] - 1)
        touch(tech)
    # cascade: IN_PROGRESS mark-out -> EXPIRED
    for m in db.mark_outs.values():
        if m["assignment_id"] == aid and m["status"] == "IN_PROGRESS":
            m["status"] = "EXPIRED"
            touch(m)
    return _ok(serialize(a))


# ===========================================================================
# Mark Outs
# ===========================================================================
@app.route("/mark-outs", methods=["POST"])
def create_markout():
    user_id, role = get_user_context()
    require_roles(role, ["LocateTech"])
    body = get_json()
    require_fields(body, ["assignment_id", "ticket_id", "marks_count"])
    assignment = find_assignment(body["assignment_id"])
    ticket = find_ticket(body["ticket_id"])
    supersedes_id = body.get("supersedes_markout_id")
    is_refresh = supersedes_id is not None

    prior = None
    if is_refresh:
        prior = find_markout(supersedes_id)

    # geometry / constraint
    mc = body["marks_count"]
    if not isinstance(mc, int) or isinstance(mc, bool) or mc < 1:
        raise err("ERR_INVALID_GEOMETRY", "marks_count must be >= 1")

    if is_refresh:
        # priority 9: refresh target must be COMPLETE on this ticket, window not expired
        if prior["status"] != "COMPLETE" or prior["ticket_id"] != ticket["id"]:
            raise err("ERR_MARKOUT_NOT_REFRESHABLE", "Mark-out not refreshable")
        if ticket["dig_window_expires_at"] is not None and db.clock.get() > ticket["dig_window_expires_at"]:
            raise err("ERR_MARKOUT_NOT_REFRESHABLE", "Dig window expired")
        # priority 11: OCC
        expected = body.get("expected_ticket_version")
        if expected != ticket["version"]:
            raise err("ERR_STALE_TICKET_VERSION", "Stale ticket version")

    rec = _base()
    rec.update({
        "assignment_id": assignment["id"],
        "ticket_id": ticket["id"],
        "marks_count": mc,
        "is_refresh": is_refresh,
        "supersedes_markout_id": supersedes_id,
        "valid_until": None,
        "completed_at": None,
        "status": "IN_PROGRESS",
    })
    db.mark_outs[rec["id"]] = rec
    return _ok(serialize(rec), status=201)


@app.route("/mark-outs", methods=["GET"])
def list_markouts():
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    aid = request.args.get("assignment_id")
    tid = request.args.get("ticket_id")
    sid = request.args.get("supersedes_markout_id")

    def pred(r):
        if aid and r["assignment_id"] != aid:
            return False
        if tid and r["ticket_id"] != tid:
            return False
        if sid and r.get("supersedes_markout_id") != sid:
            return False
        return True
    return list_response(db.mark_outs, pred)


@app.route("/mark-outs/<mid>", methods=["GET"])
def get_markout(mid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return _ok(serialize(find_markout(mid)))


@app.route("/mark-outs/<mid>/complete", methods=["POST"])
def complete_markout(mid):
    user_id, role = get_user_context()
    require_roles(role, ["LocateTech"])
    m = find_markout(mid)
    if m["status"] != "IN_PROGRESS":
        raise err("ERR_MARKOUT_NOT_IN_PROGRESS", "Mark-out not in progress")
    ticket = db.locate_tickets.get(m["ticket_id"])
    if ticket is None:
        raise err("ERR_TICKET_NOT_FOUND", "Ticket not found")
    if ticket["response_posture"] != "ALL_CLEAR":
        raise err("ERR_TICKET_NOT_ALL_CLEAR", "Ticket not ALL_CLEAR")
    assignment = db.locate_assignments.get(m["assignment_id"])
    if assignment is None or assignment["locate_tech_id"] != user_id:
        raise err("ERR_NOT_ASSIGNMENT_TECH", "Not the assignment tech")

    now = db.clock.get()
    valid_until = svc.markout_valid_until(now)
    m["completed_at"] = now
    m["valid_until"] = valid_until
    m["status"] = "COMPLETE"
    touch(m)

    # bubble-up to ticket
    ticket["markout_completed_at"] = now
    ticket["dig_window_expires_at"] = valid_until
    if ticket["status"] == "RESPONSES_COMPLETE":
        ticket["status"] = "MARKED"
    touch(ticket)

    # refresh: supersede prior
    if m["is_refresh"] and m["supersedes_markout_id"]:
        prior = db.mark_outs.get(m["supersedes_markout_id"])
        if prior and prior["status"] == "COMPLETE":
            prior["status"] = "SUPERSEDED"
            touch(prior)

    return _ok(serialize(m))


# ===========================================================================
# Meet Requests
# ===========================================================================
@app.route("/meet-requests", methods=["POST"])
def create_meet():
    _, role = get_user_context()
    require_roles(role, ["Excavator", "CallCenter"])
    body = get_json()
    require_fields(body, ["ticket_id", "member_utility_id", "proposed_start_min", "proposed_end_min"])
    find_ticket(body["ticket_id"])
    find_member(body["member_utility_id"])
    start = body["proposed_start_min"]
    end = body["proposed_end_min"]
    if (not isinstance(start, int) or isinstance(start, bool)
            or not isinstance(end, int) or isinstance(end, bool) or end <= start):
        raise err("ERR_INVALID_GEOMETRY", "proposed_end_min must be > proposed_start_min")
    rec = _base()
    rec.update({
        "ticket_id": body["ticket_id"],
        "member_utility_id": body["member_utility_id"],
        "proposed_start_min": start,
        "proposed_end_min": end,
        "status": "REQUESTED",
    })
    db.meet_requests[rec["id"]] = rec
    return _ok(serialize(rec), status=201)


@app.route("/meet-requests", methods=["GET"])
def list_meets():
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    tid = request.args.get("ticket_id")
    muid = request.args.get("member_utility_id")

    def pred(r):
        if tid and r["ticket_id"] != tid:
            return False
        if muid and r["member_utility_id"] != muid:
            return False
        return True
    return list_response(db.meet_requests, pred)


@app.route("/meet-requests/<mid>", methods=["GET"])
def get_meet(mid):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return _ok(serialize(find_meet(mid)))


@app.route("/meet-requests/<mid>/schedule", methods=["POST"])
def schedule_meet(mid):
    user_id, role = get_user_context()
    require_roles(role, ["FacilityOwner"])
    mr = find_meet(mid)
    if mr["status"] != "REQUESTED":
        raise err("ERR_MEET_NOT_REQUESTED", "Meet not in REQUESTED")
    if mr["member_utility_id"] != user_id:
        raise err("ERR_NOT_MEET_OWNER", "Not the meet owner")
    # overlap check: half-open [start, end) vs other SCHEDULED for same member
    for other in db.meet_requests.values():
        if other["id"] == mr["id"]:
            continue
        if other["status"] != "SCHEDULED":
            continue
        if other["member_utility_id"] != mr["member_utility_id"]:
            continue
        if mr["proposed_start_min"] < other["proposed_end_min"] and other["proposed_start_min"] < mr["proposed_end_min"]:
            raise err("ERR_MEET_WINDOW_OVERLAP", "Meet window overlap")
    mr["status"] = "SCHEDULED"
    touch(mr)
    return _ok(serialize(mr))


@app.route("/meet-requests/<mid>/complete", methods=["POST"])
def complete_meet(mid):
    user_id, role = get_user_context()
    require_roles(role, ["FacilityOwner"])
    mr = find_meet(mid)
    if mr["status"] != "SCHEDULED":
        raise err("ERR_MEET_NOT_SCHEDULED", "Meet not in SCHEDULED")
    if mr["member_utility_id"] != user_id:
        raise err("ERR_NOT_MEET_OWNER", "Not the meet owner")
    mr["status"] = "COMPLETED"
    touch(mr)
    return _ok(serialize(mr))


@app.route("/meet-requests/<mid>/decline", methods=["POST"])
def decline_meet(mid):
    user_id, role = get_user_context()
    require_roles(role, ["FacilityOwner"])
    mr = find_meet(mid)
    if mr["status"] not in ("REQUESTED", "SCHEDULED"):
        raise err("ERR_MEET_NOT_DECLINABLE", "Meet not declinable")
    if mr["member_utility_id"] != user_id:
        raise err("ERR_NOT_MEET_OWNER", "Not the meet owner")
    mr["status"] = "DECLINED"
    touch(mr)
    return _ok(serialize(mr))


# ===========================================================================
# Damage Reports
# ===========================================================================
@app.route("/damage-reports", methods=["POST"])
def create_damage():
    _, role = get_user_context()
    require_roles(role, ["FacilityOwner", "Excavator"])
    body = get_json()
    require_fields(body, ["ticket_id", "member_utility_id", "repair_cost_cents", "dug_within_marks"])
    find_ticket(body["ticket_id"])
    find_member(body["member_utility_id"])
    markout_id = body.get("markout_id")
    if markout_id is not None:
        find_markout(markout_id)
    cost = body["repair_cost_cents"]
    if not isinstance(cost, int) or isinstance(cost, bool) or cost < 0:
        raise err("ERR_INVALID_GEOMETRY", "repair_cost_cents must be >= 0")
    dwm = body["dug_within_marks"]
    if not isinstance(dwm, bool):
        raise err("ERR_INVALID_REQUEST", "dug_within_marks must be boolean")
    rec = _base()
    rec.update({
        "ticket_id": body["ticket_id"],
        "member_utility_id": body["member_utility_id"],
        "markout_id": markout_id,
        "repair_cost_cents": cost,
        "dug_within_marks": dwm,
        "excavator_liability_cents": None,
        "member_liability_cents": None,
        "status": "FILED",
    })
    db.damage_reports[rec["id"]] = rec
    return _ok(serialize(rec), status=201)


@app.route("/damage-reports", methods=["GET"])
def list_damages():
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    tid = request.args.get("ticket_id")
    muid = request.args.get("member_utility_id")
    moid = request.args.get("markout_id")

    def pred(r):
        if tid and r["ticket_id"] != tid:
            return False
        if muid and r["member_utility_id"] != muid:
            return False
        if moid and r.get("markout_id") != moid:
            return False
        return True
    return list_response(db.damage_reports, pred)


@app.route("/damage-reports/<did>", methods=["GET"])
def get_damage(did):
    _, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    return _ok(serialize(find_damage(did)))


@app.route("/damage-reports/<did>/review", methods=["POST"])
def review_damage(did):
    user_id, role = get_user_context()
    require_roles(role, ["FacilityOwner"])
    dr = find_damage(did)
    if dr["status"] != "FILED":
        raise err("ERR_DAMAGE_NOT_FILED", "Damage report not FILED")
    if dr["member_utility_id"] != user_id:
        raise err("ERR_NOT_DAMAGE_OWNER", "Not the damage owner")
    exc, mem = svc.compute_liability(dr["repair_cost_cents"], dr["markout_id"], dr["dug_within_marks"])
    dr["excavator_liability_cents"] = exc
    dr["member_liability_cents"] = mem
    dr["status"] = "UNDER_REVIEW"
    touch(dr)
    return _ok(serialize(dr))


@app.route("/damage-reports/<did>/settle", methods=["POST"])
def settle_damage(did):
    user_id, role = get_user_context()
    require_roles(role, ["FacilityOwner"])
    dr = find_damage(did)
    if dr["status"] != "UNDER_REVIEW":
        raise err("ERR_DAMAGE_NOT_UNDER_REVIEW", "Damage report not UNDER_REVIEW")
    if dr["member_utility_id"] != user_id:
        raise err("ERR_NOT_DAMAGE_OWNER", "Not the damage owner")
    dr["status"] = "SETTLED"
    touch(dr)
    return _ok(serialize(dr))


@app.route("/damage-reports/<did>/dispute", methods=["POST"])
def dispute_damage(did):
    user_id, role = get_user_context()
    require_roles(role, ["Excavator"])
    dr = find_damage(did)
    if dr["status"] != "UNDER_REVIEW":
        raise err("ERR_DAMAGE_NOT_UNDER_REVIEW", "Damage report not UNDER_REVIEW")
    ticket = db.locate_tickets.get(dr["ticket_id"])
    if ticket is None or ticket["excavator_id"] != user_id:
        raise err("ERR_NOT_DAMAGE_EXCAVATOR", "Not the damage excavator")
    dr["status"] = "DISPUTED"
    touch(dr)
    return _ok(serialize(dr))


# ===========================================================================
# Logical Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_user_context()
    require_roles(role, ["Admin", "CallCenter"])
    body = get_json()
    require_fields(body, ["to_iso8601"])
    try:
        dt = parse_iso(body["to_iso8601"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Invalid to_iso8601")
    db.clock.set(dt)
    svc.advance_clock_transitions()
    return _ok({"current_utc": iso_ms(dt)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))

"""ServiceRequest endpoints: intake, triage, route, reopen, close,
plus notifications/escalations reverse-reachability reads (PRD §3.2-3.6)."""
from flask import Blueprint, request as flask_request

import db
import errors
import validate
import serialize
from middleware import authenticate, authorize
import response
import clock
from services import calc, notify, workflow

bp = Blueprint("requests", __name__)


# ---------------- Intake ----------------

@bp.route("/service-requests", methods=["POST"])
def create_service_request():
    p = authenticate()
    authorize(p, {"Citizen", "Dispatcher"})
    data = validate.body()
    citizen_id = validate.require_str(data, "citizen_id")
    category_id = validate.require_str(data, "category_id")
    description = validate.require_str(data, "description")
    lat = validate.opt_number(data, "lat", None)
    lng = validate.opt_number(data, "lng", None)
    requested_priority = validate.opt_enum(data, "requested_priority", validate.PRIORITIES, None)

    # Existence (priority 3), left-to-right: citizen then category.
    if citizen_id not in db.citizens:
        raise errors.not_found("Citizen not found.")
    category = db.categories.get(category_id)
    if category is None:
        raise errors.not_found("Category not found.")

    # priority 8: category active.
    if not category["active"]:
        raise errors.category_inactive()
    # priority 9: geolocation required.
    if category["requires_geolocation"] and (lat is None or lng is None):
        raise errors.geolocation_required()

    rec = {
        "citizen_id": citizen_id,
        "category_id": category_id,
        "description": description,
        "lat": lat,
        "lng": lng,
        "priority": None,
        "requested_priority": requested_priority,
        "jurisdiction_id": None,
        "department_id": None,
        "cluster_id": None,
        "status": "SUBMITTED",
        "sla_deadline_at": None,
        "routed_at": None,
        "resolved_at": None,
        "sla_breached": False,
        "reopen_count": 0,
    }
    db.stamp_common(rec)
    db.service_requests[rec["id"]] = rec
    return response.object_response(serialize.view("service_request", rec), 201)


@bp.route("/service-requests/<rid>", methods=["GET"])
def get_service_request(rid):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Agent", "Citizen"})
    rec = db.service_requests.get(rid)
    if rec is None:
        raise errors.not_found("Service request not found.")
    return response.object_response(serialize.view("service_request", rec))


@bp.route("/service-requests", methods=["GET"])
def list_service_requests():
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Agent", "Citizen"})
    limit, offset = validate.pagination()
    args = flask_request.args
    f_citizen = args.get("citizen_id")
    f_category = args.get("category_id")
    f_department = args.get("department_id")
    f_jurisdiction = args.get("jurisdiction_id")
    f_cluster = args.get("cluster_id")
    f_status = args.get("status")

    def pred(r):
        if f_citizen is not None and r["citizen_id"] != f_citizen:
            return False
        if f_category is not None and r["category_id"] != f_category:
            return False
        if f_department is not None and r.get("department_id") != f_department:
            return False
        if f_jurisdiction is not None and r.get("jurisdiction_id") != f_jurisdiction:
            return False
        if f_cluster is not None and r.get("cluster_id") != f_cluster:
            return False
        if f_status is not None and r["status"] != f_status:
            return False
        return True

    rows = db.ordered(db.service_requests, pred)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("service_request", page), limit, offset, total)


# ---------------- Triage ----------------

@bp.route("/service-requests/<rid>/triage", methods=["POST"])
def triage(rid):
    p = authenticate()
    authorize(p, {"Dispatcher"})
    rec = db.service_requests.get(rid)
    if rec is None:
        raise errors.not_found("Service request not found.")
    data = validate.body()
    requested_priority = validate.opt_enum(data, "requested_priority", validate.PRIORITIES, None)

    # priority 6: state.
    if rec["status"] != "SUBMITTED":
        raise errors.invalid_state("Request is not SUBMITTED.")

    category = db.categories.get(rec["category_id"])
    # priority 8: category active.
    if category is None or not category["active"]:
        raise errors.category_inactive()
    # priority 9: geolocation required.
    if category["requires_geolocation"] and (rec.get("lat") is None or rec.get("lng") is None):
        raise errors.geolocation_required()

    # Side effects: set priority (triage override > stored requested > default).
    effective_requested = requested_priority if requested_priority is not None else rec.get("requested_priority")
    if effective_requested is not None:
        rec["requested_priority"] = effective_requested
        rec["priority"] = effective_requested
    else:
        rec["priority"] = category["default_priority"]

    rec["jurisdiction_id"] = calc.jurisdiction_match(rec.get("lat"), rec.get("lng"))

    from_status = rec["status"]
    rec["status"] = "TRIAGED"
    notify.synthesize(rec, from_status, "TRIAGED")
    db.touch(rec)
    return response.object_response(serialize.view("service_request", rec))


# ---------------- Route ----------------

@bp.route("/service-requests/<rid>/route", methods=["POST"])
def route_request(rid):
    p = authenticate()
    authorize(p, {"Dispatcher"})
    rec = db.service_requests.get(rid)
    if rec is None:
        raise errors.not_found("Service request not found.")

    # priority 6: state.
    if rec["status"] != "TRIAGED":
        raise errors.invalid_state("Request is not TRIAGED.")

    # Resolve destination department: jurisdiction override (if non-null) else category default.
    dept_id = None
    jid = rec.get("jurisdiction_id")
    if jid is not None:
        juris = db.jurisdictions.get(jid)
        if juris is not None and juris.get("override_department_id") is not None:
            dept_id = juris["override_department_id"]
    if dept_id is None:
        category = db.categories.get(rec["category_id"])
        dept_id = category["default_department_id"] if category else None

    dept = db.departments.get(dept_id) if dept_id else None
    if dept is None:
        raise errors.not_found("Routed department not found.")

    # priority 12: an SlaPolicy exists for (category_id, priority).
    policy = calc.find_sla_policy(rec["category_id"], rec["priority"])
    if policy is None:
        raise errors.no_sla_policy()

    # priority 21: window blocks routing. routed_at == clock_now.
    now = db.CLOCK.now()
    for w in db.windows.values():
        if w["window_type"] == "MAINTENANCE" and w["department_id"] == dept_id:
            if calc.maintenance_blocks(clock.parse_iso(w["starts_at"]), clock.parse_iso(w["ends_at"]), now):
                raise errors.window_blocks_routing()
        elif w["window_type"] == "BLACKOUT" and jid is not None and w["jurisdiction_id"] == jid:
            if calc.blackout_blocks(clock.parse_iso(w["starts_at"]), clock.parse_iso(w["ends_at"]), now):
                raise errors.window_blocks_routing()

    # A request has at most one WorkOrder (request_id unique).
    if workflow.work_order_for_request(rec["id"]) is not None:
        raise errors.duplicate_work_order()

    # Side effects.
    rec["department_id"] = dept_id
    rec["routed_at"] = db.CLOCK.now_iso()
    rec["sla_deadline_at"] = clock.fmt(now + _hours(policy["resolution_sla_hours"]))

    wo = {
        "request_id": rec["id"],
        "department_id": dept_id,
        "assigned_agent_id": None,
        "status": "OPEN",
        "completion_note": None,
    }
    db.stamp_common(wo)
    db.work_orders[wo["id"]] = wo
    calc.department_backlog(dept)

    from_status = rec["status"]
    rec["status"] = "ROUTED"
    notify.synthesize(rec, from_status, "ROUTED")
    db.touch(rec)
    return response.object_response(serialize.view("service_request", rec))


def _hours(n):
    from datetime import timedelta
    return timedelta(hours=n)


# ---------------- Reopen ----------------

@bp.route("/service-requests/<rid>/reopen", methods=["POST"])
def reopen(rid):
    p = authenticate()
    authorize(p, {"Citizen"})
    rec = db.service_requests.get(rid)
    if rec is None:
        raise errors.not_found("Service request not found.")

    # priority 4: ownership.
    if rec["citizen_id"] != p.user_id:
        raise errors.not_resource_owner()
    # priority 6: state.
    if rec["status"] != "RESOLVED":
        raise errors.invalid_state("Request is not RESOLVED.")
    # priority 13: reopen window. resolved_at + 72h >= clock_now.
    resolved_at = clock.parse_iso(rec["resolved_at"])
    if not (resolved_at + _hours(calc.REOPEN_WINDOW_HOURS) >= db.CLOCK.now()):
        raise errors.reopen_window_closed()

    workflow.request_reopen_cascade(rec)
    return response.object_response(serialize.view("service_request", rec))


# ---------------- Close ----------------

@bp.route("/service-requests/<rid>/close", methods=["POST"])
def close_request(rid):
    p = authenticate()
    authorize(p, {"Dispatcher"})
    rec = db.service_requests.get(rid)
    if rec is None:
        raise errors.not_found("Service request not found.")
    # priority 6: state.
    if rec["status"] != "RESOLVED":
        raise errors.invalid_state("Request is not RESOLVED.")
    # priority 15: no open escalation.
    if workflow.open_escalations_for_request(rec["id"]):
        raise errors.open_escalation_blocks_close()

    workflow.request_close_cascade(rec)
    return response.object_response(serialize.view("service_request", rec))


# ---------------- Reverse-reachability reads ----------------

@bp.route("/service-requests/<rid>/notifications", methods=["GET"])
def list_notifications(rid):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Citizen"})
    if rid not in db.service_requests:
        raise errors.not_found("Service request not found.")
    limit, offset = validate.pagination()
    rows = db.ordered(db.notifications, lambda r: r["request_id"] == rid)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("notification", page), limit, offset, total)


@bp.route("/service-requests/<rid>/escalations", methods=["GET"])
def list_escalations(rid):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Agent"})
    if rid not in db.service_requests:
        raise errors.not_found("Service request not found.")
    limit, offset = validate.pagination()
    rows = db.ordered(db.escalations, lambda r: r["request_id"] == rid)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("escalation", page), limit, offset, total)

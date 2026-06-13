"""Assignment endpoints: list, get, accept, decline, reports (submit/resubmit)."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from services import domain, pagination, serialize, validate

bp = Blueprint("assignments", __name__)

UAD_CONDITION_SET = {"C1", "C2", "C3", "C4", "C5", "C6"}
UAD_QUALITY_SET = {"Q1", "Q2", "Q3", "Q4", "Q5", "Q6"}
TRAVEL_BUFFER_SECONDS = 60 * 60  # 60 minutes


# ---------------------------------------------------------------------------
# GET /amc/assignments
# ---------------------------------------------------------------------------
@bp.route("/amc/assignments", methods=["GET"])
def list_assignments():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "Appraiser"})
    limit, offset = pagination.parse()

    items = list(db.assignments.values())
    appraiser_id = request.args.get("appraiser_id")
    order_id = request.args.get("order_id")
    supersedes = request.args.get("supersedes_assignment_id")
    status = request.args.get("status")
    if appraiser_id:
        items = [a for a in items if a.get("appraiser_id") == appraiser_id]
    if order_id:
        items = [a for a in items if a.get("order_id") == order_id]
    if supersedes:
        items = [a for a in items if a.get("supersedes_assignment_id") == supersedes]
    if status:
        items = [a for a in items if a["status"] == status]

    page, total = pagination.apply(items, limit, offset)
    return response.ok_array([serialize.public(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# GET /amc/assignments/{id}
# ---------------------------------------------------------------------------
@bp.route("/amc/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "Appraiser"})
    assignment = db.assignments.get(aid)
    if assignment is None:
        raise errors.not_found("Assignment not found.")
    return response.ok_object(serialize.public(assignment), 200)


# ---------------------------------------------------------------------------
# POST /amc/assignments/{id}/accept
# ---------------------------------------------------------------------------
@bp.route("/amc/assignments/<aid>/accept", methods=["POST"])
def accept_assignment(aid):
    user_id, role = middleware.authenticate()
    middleware.require_roles(role, {"Appraiser"})
    assignment = db.assignments.get(aid)
    if assignment is None:
        raise errors.not_found("Assignment not found.")

    # Ownership: acting appraiser must be the assignment's appraiser_id.
    if assignment.get("appraiser_id") != user_id:
        raise errors.unauthorized("Assignment does not belong to the acting appraiser.")

    data = validate.body()

    # State legality (priority 7).
    if assignment["status"] != "OFFERED":
        raise errors.invalid_state("Assignment is not OFFERED.")

    # Parse window endpoints.
    raw_start = data.get("inspection_start")
    raw_end = data.get("inspection_end")
    if raw_start is None or raw_end is None:
        raise errors.invalid_request("inspection_start and inspection_end are required.")
    start = clock.parse_iso(raw_start)
    end = clock.parse_iso(raw_end)
    if start is None or end is None:
        raise errors.invalid_request("inspection_start/inspection_end must be ISO 8601.")

    order = db.orders.get(assignment.get("order_id"))

    # Priority 9: appraiser window conflict (half-open + 60-min travel buffer).
    _check_appraiser_window(assignment, start, end)
    # Priority 10: property window conflict (closed interval, no buffer).
    _check_property_window(assignment, order, start, end)
    # Priority 11: window validity (end strictly after start).
    if not (end > start):
        raise errors.err(errors.ERR_INVALID_WINDOW,
                         "inspection_end must be strictly after inspection_start.")

    now = clock.now()
    assignment["status"] = "ACCEPTED"
    assignment["accepted_at"] = clock.format_iso(now)
    assignment["inspection_start"] = clock.format_iso(start)
    assignment["inspection_end"] = clock.format_iso(end)
    db.touch(assignment)

    appraiser = db.appraisers.get(assignment["appraiser_id"])
    if appraiser is not None:
        domain.recompute_appraiser(appraiser)
        db.touch(appraiser)

    # Cascade: Order PLACED/ASSIGNED -> IN_PROGRESS.
    if order is not None and order["status"] in ("PLACED", "ASSIGNED"):
        order["status"] = "IN_PROGRESS"
        db.touch(order)

    return response.ok_object(serialize.public(assignment), 200)


def _window_intervals(appraiser_id=None, property_id=None, exclude_id=None):
    """Yield (start_dt, end_dt) for ACCEPTED/REVISION assignments matching the
    filter, with parsed inspection windows."""
    out = []
    for a in db.assignments.values():
        if a["id"] == exclude_id:
            continue
        if a["status"] not in ("ACCEPTED", "REVISION"):
            continue
        if a.get("inspection_start") is None or a.get("inspection_end") is None:
            continue
        if appraiser_id is not None and a.get("appraiser_id") != appraiser_id:
            continue
        if property_id is not None:
            o = db.orders.get(a.get("order_id"))
            if o is None or o.get("property_id") != property_id:
                continue
        s = clock.parse_iso(a["inspection_start"])
        e = clock.parse_iso(a["inspection_end"])
        if s is None or e is None:
            continue
        out.append((s, e))
    return out


def _check_appraiser_window(assignment, start, end):
    """Half-open [start,end) + 60-min travel buffer. Collide when later starts
    strictly less than 60 min after earlier ends: earlier.end + 60min > later.start."""
    for s, e in _window_intervals(appraiser_id=assignment.get("appraiser_id"),
                                  exclude_id=assignment["id"]):
        # Determine earlier / later by start.
        if s <= start:
            earlier_end, later_start = e, start
        else:
            earlier_end, later_start = end, s
        buffer_end = earlier_end.timestamp() + TRAVEL_BUFFER_SECONDS
        if buffer_end > later_start.timestamp():
            raise errors.err(errors.ERR_APPRAISER_WINDOW_CONFLICT,
                             "Inspection window conflicts with another appraiser window.")


def _check_property_window(assignment, order, start, end):
    """Closed interval [start,end], no buffer. Boundary touch is a conflict:
    overlap when start <= other.end AND end >= other.start."""
    if order is None:
        return
    pid = order.get("property_id")
    for s, e in _window_intervals(property_id=pid, exclude_id=assignment["id"]):
        if start <= e and end >= s:
            raise errors.err(errors.ERR_PROPERTY_WINDOW_CONFLICT,
                             "Inspection window conflicts with another property window.")


# ---------------------------------------------------------------------------
# POST /amc/assignments/{id}/decline
# ---------------------------------------------------------------------------
@bp.route("/amc/assignments/<aid>/decline", methods=["POST"])
def decline_assignment(aid):
    user_id, role = middleware.authenticate()
    middleware.require_roles(role, {"Appraiser"})
    assignment = db.assignments.get(aid)
    if assignment is None:
        raise errors.not_found("Assignment not found.")
    if assignment.get("appraiser_id") != user_id:
        raise errors.unauthorized("Assignment does not belong to the acting appraiser.")

    if assignment["status"] != "OFFERED":
        raise errors.invalid_state("Assignment is not OFFERED.")

    assignment["status"] = "DECLINED"
    db.touch(assignment)
    # Order stays ASSIGNED; no appraiser counters change.
    return response.ok_object(serialize.public(assignment), 200)


# ---------------------------------------------------------------------------
# POST /amc/assignments/{id}/reports  — submit / resubmit
# ---------------------------------------------------------------------------
@bp.route("/amc/assignments/<aid>/reports", methods=["POST"])
def submit_report(aid):
    user_id, role = middleware.authenticate()
    middleware.require_roles(role, {"Appraiser"})
    assignment = db.assignments.get(aid)
    if assignment is None:
        raise errors.not_found("Assignment not found.")

    data = validate.body()

    # Priority 6: report-target revisability — assignment in ACCEPTED/REVISION
    # and owned by the acting appraiser.
    if assignment.get("appraiser_id") != user_id \
            or assignment["status"] not in ("ACCEPTED", "REVISION"):
        raise errors.err(errors.ERR_ASSIGNMENT_NOT_REVISABLE,
                         "Assignment is not in a revisable state for this appraiser.")

    # Field-shape validation (priority 14).
    opinion = data.get("opinion_of_value_cents")
    if opinion is None:
        raise errors.invalid_request("opinion_of_value_cents is required.")
    if isinstance(opinion, bool) or not isinstance(opinion, int):
        raise errors.invalid_request("opinion_of_value_cents must be an integer.")
    if opinion <= 0:
        raise errors.invalid_request("opinion_of_value_cents must be > 0.")
    condition = validate.require_enum(data, "uad_condition_rating", UAD_CONDITION_SET)
    quality = validate.require_enum(data, "uad_quality_rating", UAD_QUALITY_SET)
    comp_count = data.get("comparable_count")
    if comp_count is None:
        raise errors.invalid_request("comparable_count is required.")
    if isinstance(comp_count, bool) or not isinstance(comp_count, int):
        raise errors.invalid_request("comparable_count must be an integer.")
    if comp_count < 0:
        raise errors.invalid_request("comparable_count must be >= 0.")

    order = db.orders.get(assignment.get("order_id"))
    now = clock.now()

    # Existing report for this assignment?
    existing = None
    for rpt in db.reports.values():
        if rpt.get("assignment_id") == aid:
            existing = rpt
            break

    if existing is None:
        # First submission -> creates Report SUBMITTED.
        report = {
            "assignment_id": aid,
            "opinion_of_value_cents": opinion,
            "uad_condition_rating": condition,
            "uad_quality_rating": quality,
            "comparable_count": comp_count,
            "submitted_at": clock.format_iso(now),
            "status": "SUBMITTED",
        }
        db.stamp_create(report)
        db.reports[report["id"]] = report

        # Cascade Order IN_PROGRESS -> IN_QC.
        if order is not None and order["status"] == "IN_PROGRESS":
            order["status"] = "IN_QC"
            db.touch(order)
        return response.ok_object(serialize.public(report), 201)

    # Resubmission: supersede the same Report in place.
    # Only honored when the report is in REVISION_REQUESTED (PRD §3.4).
    if existing["status"] != "REVISION_REQUESTED":
        raise errors.err(errors.ERR_ASSIGNMENT_NOT_REVISABLE,
                         "Report is not awaiting resubmission.")

    existing["opinion_of_value_cents"] = opinion
    existing["uad_condition_rating"] = condition
    existing["uad_quality_rating"] = quality
    existing["comparable_count"] = comp_count
    existing["submitted_at"] = clock.format_iso(now)
    existing["status"] = "RESUBMITTED"
    db.touch(existing)

    # Mark the open RevisionRequest RESOLVED.
    for rr in db.revision_requests.values():
        if rr.get("report_id") == existing["id"] and rr["status"] == "OPEN":
            rr["status"] = "RESOLVED"
            db.touch(rr)

    # Cascade: Assignment REVISION -> ACCEPTED; Order IN_PROGRESS -> IN_QC.
    if assignment["status"] == "REVISION":
        assignment["status"] = "ACCEPTED"
        db.touch(assignment)
    if order is not None and order["status"] == "IN_PROGRESS":
        order["status"] = "IN_QC"
        db.touch(order)

    return response.ok_object(serialize.public(existing), 201)


# ---------------------------------------------------------------------------
# GET /amc/assignments/{id}/reports
# ---------------------------------------------------------------------------
@bp.route("/amc/assignments/<aid>/reports", methods=["GET"])
def list_assignment_reports(aid):
    _, role = middleware.authenticate()
    middleware.require_roles(
        role, {"AMCCoordinator", "PlatformAdmin", "ComplianceReviewer", "Appraiser"})
    assignment = db.assignments.get(aid)
    if assignment is None:
        raise errors.not_found("Assignment not found.")
    limit, offset = pagination.parse()
    items = [r for r in db.reports.values() if r.get("assignment_id") == aid]
    page, total = pagination.apply(items, limit, offset)
    return response.ok_array([serialize.public(r) for r in page], limit, offset, total)

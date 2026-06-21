"""Break housing request routes: request, get, list, approve, deny, cancel."""

from datetime import datetime, timezone

from flask import Blueprint, request

import db
import errors
import response
import common
from middleware import authenticate, require_role
from services import core

bp = Blueprint("break_housing", __name__)

ALL_ROLES = ("HousingOfficer", "Student", "ResidentAdvisor")
NIGHT_SECONDS = 86400


def _parse_date(value, field):
    """Parse an ISO 8601 date/datetime into an aware UTC datetime."""
    if not isinstance(value, str):
        raise errors.invalid_request("%s must be an ISO 8601 date string." % field)
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        if "T" in candidate:
            dt = datetime.fromisoformat(candidate)
        else:
            dt = datetime.fromisoformat(candidate + "T00:00:00")
    except ValueError:
        raise errors.invalid_request("%s is not a valid ISO 8601 date." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


@bp.route("/break-housing-requests", methods=["POST"])
def create_request():
    principal = authenticate()
    require_role(principal, ("Student",))
    body = common.get_body()
    common.require_fields(body, ["assignment_id", "check_in_date", "check_out_date"])
    assignment_id = body["assignment_id"]
    check_in = _parse_date(body["check_in_date"], "check_in_date")
    check_out = _parse_date(body["check_out_date"], "check_out_date")

    with db.LOCK:
        assignment = core.get_or_404(db.assignments, assignment_id)
        # Ownership: requesting resident must own the assignment.
        if principal.user_id != assignment["student_id"]:
            raise errors.forbidden("Caller does not own this assignment.")
        # Date range: check_out strictly after check_in (priority 5).
        if check_out <= check_in:
            raise errors.invalid_date_range()

        night_count = (check_out - check_in).days
        rec = core.init_record({
            "assignment_id": assignment_id,
            "room_id": assignment["room_id"],
            "check_in_date": body["check_in_date"],
            "check_out_date": body["check_out_date"],
            "night_count": night_count,
            "total_charge_cents": None,
            "status": "REQUESTED",
        })
        # Store parsed datetimes privately for overlap math.
        rec["_check_in"] = check_in
        rec["_check_out"] = check_out
        db.break_housing_requests[rec["id"]] = rec
        return response.object_response(core.serialize(rec), status=201)


@bp.route("/break-housing-requests/<request_id>", methods=["GET"])
def get_request(request_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.break_housing_requests, request_id)
        return response.object_response(core.serialize(rec))


@bp.route("/break-housing-requests", methods=["GET"])
def list_requests():
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        limit, offset = common.parse_pagination()
        items = list(db.break_housing_requests.values())
        for key in ("assignment_id", "room_id"):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r.get(key) == val]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(r) for r in page], limit, offset, total
        )


@bp.route("/break-housing-requests/<request_id>/approve", methods=["POST"])
def approve_request(request_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        req = core.get_or_404(db.break_housing_requests, request_id)
        if req["status"] != "REQUESTED":
            raise errors.invalid_state("Request is not REQUESTED.")
        room = db.rooms.get(req["room_id"])
        if room is None:
            raise errors.not_found("Room no longer exists.")
        building = db.buildings.get(room["building_id"])
        if building is None:
            raise errors.not_found("Building no longer exists.")

        # Precondition: building must offer break housing (priority 7).
        if not building["offers_break_housing"]:
            raise errors.precondition_not_met("Building does not offer break housing.")

        # Per-room exclusive overlap (priority 10).
        ci, co = req["_check_in"], req["_check_out"]
        for other in db.break_housing_requests.values():
            if other["id"] == req["id"]:
                continue
            if other["status"] != "APPROVED":
                continue
            if other["room_id"] != req["room_id"]:
                continue
            if _intervals_overlap(ci, co, other["_check_in"], other["_check_out"]):
                raise errors.break_overlap()

        # Per-building aggregate-capacity overlap (priority 11).
        if not _building_capacity_ok(building, req, ci, co):
            raise errors.break_capacity_exceeded()

        # Compute the charge and debit the student.
        total = req["night_count"] * room["nightly_break_rate_cents"]
        req["status"] = "APPROVED"
        req["total_charge_cents"] = total
        core.touch(req)
        student = _student_for_request(req)
        if student is not None:
            student["account_balance_cents"] += total
            core.touch(student)
        return response.object_response(core.serialize(req))


@bp.route("/break-housing-requests/<request_id>/deny", methods=["POST"])
def deny_request(request_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        req = core.get_or_404(db.break_housing_requests, request_id)
        if req["status"] != "REQUESTED":
            raise errors.invalid_state("Request is not REQUESTED.")
        req["status"] = "DENIED"
        core.touch(req)
        return response.object_response(core.serialize(req))


@bp.route("/break-housing-requests/<request_id>/cancel", methods=["POST"])
def cancel_request(request_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        req = core.get_or_404(db.break_housing_requests, request_id)
        assignment = db.assignments.get(req["assignment_id"])
        owner_id = assignment["student_id"] if assignment else None
        if principal.user_id != owner_id:
            raise errors.forbidden("Caller does not own this break request.")
        if req["status"] not in ("REQUESTED", "APPROVED"):
            raise errors.invalid_state("Request is not REQUESTED or APPROVED.")
        was_approved = req["status"] == "APPROVED"
        req["status"] = "CANCELLED"
        core.touch(req)
        if was_approved:
            student = _student_for_request(req)
            if student is not None:
                refund = req["total_charge_cents"] or 0
                student["account_balance_cents"] = max(
                    0, student["account_balance_cents"] - refund
                )
                core.touch(student)
        return response.object_response(core.serialize(req))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _intervals_overlap(a_in, a_out, b_in, b_out):
    """Half-open [in, out) overlap: share an instant. Adjacency allowed."""
    return a_in < b_out and b_in < a_out


def _building_capacity_ok(building, req, ci, co):
    """At every instant within [ci, co), the count of APPROVED break requests in
    the building (across all rooms) overlapping that instant, plus this one,
    must not exceed building.break_housing_capacity.

    Implemented as a sweep over interval boundaries: the max concurrent count of
    {existing APPROVED requests in the building} over the requested window must
    be <= capacity - 1 (room for this new request).
    """
    capacity = building["break_housing_capacity"]
    # This request itself adds 1, so existing concurrent must be <= capacity - 1
    # at every instant of the requested window.
    if capacity < 1:
        return False

    room_ids = {r["id"] for r in db.rooms.values() if r["building_id"] == building["id"]}
    intervals = []
    for other in db.break_housing_requests.values():
        if other["id"] == req["id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        if other["room_id"] not in room_ids:
            continue
        oi, oo = other["_check_in"], other["_check_out"]
        # Clip to the requested window; only the overlapping portion matters.
        start = max(ci, oi)
        end = min(co, oo)
        if start < end:
            intervals.append((start, end))

    if not intervals:
        return True

    # Sweep: at each existing interval start, count concurrent existing intervals.
    # The maximum concurrency over the window is the relevant peak.
    events = []
    for s, e in intervals:
        events.append((s, 1))
        events.append((e, -1))
    # Process starts before ends at the same instant (half-open: an interval
    # ending exactly when another starts does not overlap).
    events.sort(key=lambda x: (x[0], x[1]))
    current = 0
    peak = 0
    for _, delta in events:
        current += delta
        if current > peak:
            peak = current
    # Existing peak plus this new request must not exceed capacity.
    return peak + 1 <= capacity


def _student_for_request(req):
    assignment = db.assignments.get(req["assignment_id"])
    if assignment is None:
        return None
    return db.students.get(assignment["student_id"])

"""InterpreterRequest endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import core

bp = Blueprint("interpreter_requests", __name__)

REQ_READERS = {"SchoolAdmin", "FrontOfficeStaff", "Interpreter", "FamilyGuardian"}
STAFF = {"SchoolAdmin", "FrontOfficeStaff"}


def _check_request_read_scope(role, uid, req):
    if role == "Interpreter":
        if req["interpreter_id"] is not None and req["interpreter_id"] != uid:
            raise errors.forbidden("Interpreter may view only their own requests")
    if role == "FamilyGuardian":
        booking = db.bookings.get(req["booking_id"])
        if booking is None or booking["family_id"] != uid:
            raise errors.forbidden("FamilyGuardian may view only their own family's requests")


def _assignment_checks(req, interp, candidate_interval):
    """Language, channel, overlap, fatigue, capacity — in §2.7 order."""
    if req["language"] not in interp["languages"]:
        raise errors.language_not_covered()
    if req["channel_required"] == "IN_PERSON" and not interp["supports_in_person"]:
        raise errors.channel_not_allowed()
    if req["channel_required"] == "VIRTUAL" and not interp["supports_virtual"]:
        raise errors.channel_not_allowed()
    cand_start, cand_end = candidate_interval
    # Fatigue (p9) precedes overlap (p10) per the validation ordering
    if not core.interpreter_fatigue_ok(interp["id"], cand_start, cand_end,
                                       interp["max_consecutive_minutes"]):
        raise errors.interpreter_fatigue()
    if core.interpreter_overlap_conflict(interp["id"], cand_start, cand_end):
        raise errors.interpreter_overlap()
    committed, _allowance, capacity, _headroom = core.interpreter_capacity(
        interp["id"], req["window_id"])
    if committed + req["assigned_minutes"] > capacity:
        raise errors.interpreter_capacity()


def _candidate_passes(req, interp, candidate_interval):
    try:
        _assignment_checks(req, interp, candidate_interval)
        return True
    except errors.ApiError:
        return False


@bp.route("/conf/interpreter-requests", methods=["POST"])
def create_request():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF)
    body = util.get_body()
    util.require_fields(body, ["booking_id", "language"])
    booking_id = body["booking_id"]
    if not isinstance(booking_id, str):
        raise errors.validation("booking_id must be a string")
    language = util.require_string(body, "language")
    booking = core.get_booking_or_404(booking_id)
    if booking["status"] != "CONFIRMED":
        raise errors.invalid_state("booking must be CONFIRMED")
    for r in db.interpreter_requests.values():
        if r["booking_id"] == booking_id and r["status"] in core.NON_TERMINAL_REQUEST_STATUSES:
            raise errors.already_has_interpreter_request()
    req = core.create_interpreter_request(booking, language)
    return response.success_object(serializers.request_view(req), status=201)


@bp.route("/conf/interpreter-requests", methods=["GET"])
def list_requests():
    role, uid = middleware.get_auth()
    middleware.require_roles(role, REQ_READERS)
    limit, offset = util.parse_pagination(request.args)
    filters = {
        "booking_id": request.args.get("booking_id"),
        "window_id": request.args.get("window_id"),
        "interpreter_id": request.args.get("interpreter_id"),
        "status": request.args.get("status"),
        "language": request.args.get("language"),
    }
    items = list(db.interpreter_requests.values())
    if role == "Interpreter":
        items = [r for r in items
                 if r["interpreter_id"] is None or r["interpreter_id"] == uid]
    if role == "FamilyGuardian":
        items = [r for r in items
                 if db.bookings.get(r["booking_id"]) is not None
                 and db.bookings[r["booking_id"]]["family_id"] == uid]
    for key, value in filters.items():
        if value is not None:
            items = [r for r in items if r.get(key) == value]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.request_view(r) for r in page],
                                 total, limit, offset)


@bp.route("/conf/interpreter-requests/<rid>", methods=["GET"])
def get_request(rid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, REQ_READERS)
    req = core.get_request_or_404(rid)
    _check_request_read_scope(role, uid, req)
    return response.success_object(serializers.request_view(req))


@bp.route("/conf/interpreter-requests/<rid>/assign", methods=["POST"])
def assign_request(rid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF)
    body = util.get_body()
    req = core.get_request_or_404(rid)
    booking = core.get_booking_or_404(req["booking_id"])

    # Entity state (p8)
    if req["status"] != "REQUESTED":
        raise errors.invalid_state("request must be REQUESTED")
    if booking["status"] != "CONFIRMED":
        raise errors.invalid_state("booking must be CONFIRMED")

    slot = core.get_slot_or_404(booking["slot_id"])
    interval = (util.parse_dt(slot["start_at"]), util.parse_dt(slot["end_at"]))

    interpreter_id = body.get("interpreter_id")
    if interpreter_id is not None and not isinstance(interpreter_id, str):
        raise errors.validation("interpreter_id must be a string")

    if interpreter_id:
        interp = core.get_interpreter_or_404(interpreter_id)
        if interp["status"] != "ACTIVE":
            raise errors.invalid_state("interpreter must be ACTIVE")
        _assignment_checks(req, interp, interval)
        chosen = interp
    else:
        # Auto-selector: rank by committed_minutes ASC, created_at ASC, created_seq ASC
        pool = [i for i in db.interpreters.values()
                if i["status"] == "ACTIVE"
                and req["language"] in i["languages"]
                and ((req["channel_required"] == "IN_PERSON" and i["supports_in_person"])
                     or (req["channel_required"] == "VIRTUAL" and i["supports_virtual"]))
                and i["id"] not in req["declined_interpreter_ids"]]
        pool.sort(key=lambda i: (core.interpreter_committed_minutes(i["id"]),
                                 i["created_at"], i["created_seq"]))
        chosen = None
        for candidate in pool:
            if _candidate_passes(req, candidate, interval):
                chosen = candidate
                break
        if chosen is None:
            raise errors.no_eligible_interpreter()

    req["interpreter_id"] = chosen["id"]
    req["status"] = "ASSIGNED"
    req["version"] += 1
    req["updated_at"] = util.now_iso()
    return response.success_object(serializers.request_view(req))


@bp.route("/conf/interpreter-requests/<rid>/accept", methods=["POST"])
def accept_request(rid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, {"Interpreter"})
    util.get_body()
    req = core.get_request_or_404(rid)
    if req["interpreter_id"] != uid:
        raise errors.forbidden("only the assigned interpreter may accept")
    if req["status"] != "ASSIGNED":
        raise errors.invalid_state("request must be ASSIGNED")
    req["status"] = "CONFIRMED"
    req["version"] += 1
    req["updated_at"] = util.now_iso()
    return response.success_object(serializers.request_view(req))


@bp.route("/conf/interpreter-requests/<rid>/decline", methods=["POST"])
def decline_request(rid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, {"Interpreter"})
    util.get_body()  # optional reason
    req = core.get_request_or_404(rid)
    if req["interpreter_id"] != uid:
        raise errors.forbidden("only the assigned interpreter may decline")
    if req["status"] != "ASSIGNED":
        raise errors.invalid_state("request must be ASSIGNED")
    if uid not in req["declined_interpreter_ids"]:
        req["declined_interpreter_ids"].append(uid)
    req["interpreter_id"] = None
    req["status"] = "REQUESTED"
    req["version"] += 1
    req["updated_at"] = util.now_iso()
    return response.success_object(serializers.request_view(req))


@bp.route("/conf/interpreter-requests/<rid>/cancel", methods=["POST"])
def cancel_request(rid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF)
    util.get_body()  # optional reason
    req = core.get_request_or_404(rid)
    if req["status"] not in core.NON_TERMINAL_REQUEST_STATUSES:
        raise errors.invalid_state("request is already terminal")
    req["status"] = "CANCELLED"
    req["version"] += 1
    req["updated_at"] = util.now_iso()
    return response.success_object(serializers.request_view(req))

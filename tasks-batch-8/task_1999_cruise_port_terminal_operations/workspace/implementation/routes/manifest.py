"""Manifest entries: create plus the embark/debark action chains (PRD 3.5)."""

from flask import Blueprint, request

import db
import services
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_MANIFEST_DIRECTION,
    ERR_DUPLICATE_MANIFEST_REF, ERR_SCREENING_CAPACITY, ERR_CUSTOMS_NOT_CLEARED,
    ERR_CUSTOMS_HOLD_ACTIVE, ERR_VESSEL_SCOPE,
)
from middleware import authenticate, ANY, scope_call
from response import success_obj, success_list
from util import body_json, check_shape, pagination_params, paginate, apply_filters

bp = Blueprint("manifest", __name__, url_prefix="/port-ops")


def _get_entry_or_404(entry_id):
    entry = db.get("manifest_entries", entry_id)
    if entry is None:
        raise ApiError(ERR_NOT_FOUND, 404, "manifest entry not found")
    return entry


def _require_direction(entry, direction):
    """Priority 7: direction applicability, before any state check."""
    if entry["direction"] != direction:
        raise ApiError(ERR_MANIFEST_DIRECTION, 422,
                       f"action is not valid for a {entry['direction']} entry")


@bp.route("/port-calls/<call_id>/manifest-entries", methods=["POST"])
def create_entry(call_id):
    user_id, role = authenticate({"VesselAgent"})
    call = db.get("port_calls", call_id)
    if call is None:
        raise ApiError(ERR_NOT_FOUND, 404, "port call not found")
    scope_call(user_id, role, call)
    body = body_json()
    check_shape(body, {
        "passenger_ref": {"type": "string", "required": True},
        "direction": {"type": "enum", "required": True, "values": {"EMBARK", "DEBARK"}},
        "cabin_class": {"type": "enum", "required": True, "values": {"STANDARD", "PREMIUM", "CREW"}},
    })
    # Priority 8: parent-state gate on child creation.
    if call["status"] not in ("SCHEDULED", "DELAYED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "manifest entries may only be added while the call is SCHEDULED or DELAYED")
    # Priority 16: passenger_ref unique per call.
    for other in services.entries_of_call(call["id"]):
        if other["passenger_ref"] == body["passenger_ref"]:
            raise ApiError(ERR_DUPLICATE_MANIFEST_REF, 409,
                           "passenger_ref already exists on this port call")
    entry = db.new_entity("manifest_entries", {
        "port_call_id": call["id"],
        "passenger_ref": body["passenger_ref"],
        "direction": body["direction"],
        "cabin_class": body["cabin_class"],
        "status": "BOOKED" if body["direction"] == "EMBARK" else "ABOARD",
        "is_taxable": body["cabin_class"] != "CREW",
    })
    return success_obj(db.public(entry), code=201)


@bp.route("/manifest-entries", methods=["GET"])
def list_entries():
    user_id, role = authenticate(ANY)
    limit, offset = pagination_params()
    items = db.all_of("manifest_entries")
    if role == "VesselAgent":
        port_call_id = request.args.get("port_call_id")
        if port_call_id is not None:
            call = db.get("port_calls", port_call_id)
            if call is not None and call["vessel_id"] != user_id:
                raise ApiError(ERR_VESSEL_SCOPE, 403,
                               "vessel agent may only read its own vessel's calls")
        items = [
            e for e in items
            if (db.get("port_calls", e["port_call_id"]) or {}).get("vessel_id") == user_id
        ]
    items = apply_filters(items, ["port_call_id", "status", "direction"])
    page, total, has_more = paginate([db.public(e) for e in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/manifest-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    user_id, role = authenticate(ANY)
    entry = _get_entry_or_404(entry_id)
    if role == "VesselAgent":
        call = db.get("port_calls", entry["port_call_id"])
        if call is None or call["vessel_id"] != user_id:
            raise ApiError(ERR_VESSEL_SCOPE, 403,
                           "vessel agent may only read its own vessel's calls")
    return success_obj(db.public(entry))


@bp.route("/manifest-entries/<entry_id>/check-in", methods=["POST"])
def check_in(entry_id):
    authenticate({"TerminalOperator"})
    entry = _get_entry_or_404(entry_id)
    _require_direction(entry, "EMBARK")
    if entry["status"] != "BOOKED":
        raise ApiError(ERR_INVALID_STATE, 409, "check-in requires status BOOKED")
    call = db.get("port_calls", entry["port_call_id"])
    if call["status"] not in ("SCHEDULED", "ARRIVED", "TURNAROUND"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "check-in requires the call to be SCHEDULED, ARRIVED, or TURNAROUND")
    entry["status"] = "CHECKED_IN"
    db.touch(entry)
    return success_obj(db.public(entry))


@bp.route("/manifest-entries/<entry_id>/screen", methods=["POST"])
def screen(entry_id):
    authenticate({"TerminalOperator"})
    entry = _get_entry_or_404(entry_id)
    _require_direction(entry, "EMBARK")
    if entry["status"] != "CHECKED_IN":
        raise ApiError(ERR_INVALID_STATE, 409, "screen requires status CHECKED_IN")
    call = db.get("port_calls", entry["port_call_id"])
    if call["status"] not in ("ARRIVED", "TURNAROUND"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "screen requires the call to be ARRIVED or TURNAROUND")
    # Priority 19: at least one OPEN lane of the terminal with officers >= 1.
    open_staffed = any(
        lane["terminal_id"] == call["terminal_id"]
        and lane["status"] == "OPEN"
        and lane["officers_assigned"] >= 1
        for lane in db.all_of("screening_lanes")
    )
    if not open_staffed:
        raise ApiError(ERR_SCREENING_CAPACITY, 409,
                       "no OPEN screening lane with at least one officer assigned")
    entry["status"] = "SCREENED"
    db.touch(entry)
    return success_obj(db.public(entry))


@bp.route("/manifest-entries/<entry_id>/board", methods=["POST"])
def board(entry_id):
    authenticate({"TerminalOperator"})
    entry = _get_entry_or_404(entry_id)
    _require_direction(entry, "EMBARK")
    if entry["status"] != "SCREENED":
        raise ApiError(ERR_INVALID_STATE, 409, "board requires status SCREENED")
    call = db.get("port_calls", entry["port_call_id"])
    if call["status"] != "TURNAROUND":
        raise ApiError(ERR_INVALID_STATE, 409, "board requires the call to be TURNAROUND")
    case = services.customs_case_of(call["id"])
    if case is None or case["status"] != "CLEARED":
        raise ApiError(ERR_CUSTOMS_NOT_CLEARED, 409,
                       "the call's customs case is not CLEARED")
    entry["status"] = "EMBARKED"
    db.touch(entry)
    return success_obj(db.public(entry))


@bp.route("/manifest-entries/<entry_id>/offload", methods=["POST"])
def offload(entry_id):
    authenticate({"TerminalOperator"})
    entry = _get_entry_or_404(entry_id)
    _require_direction(entry, "EMBARK")
    if entry["status"] != "EMBARKED":
        raise ApiError(ERR_INVALID_STATE, 409, "offload requires status EMBARKED")
    call = db.get("port_calls", entry["port_call_id"])
    if call["status"] != "TURNAROUND":
        raise ApiError(ERR_INVALID_STATE, 409, "offload requires the call to be TURNAROUND")
    entry["status"] = "CHECKED_IN"
    db.touch(entry)
    # Cascade: this entry's LOADED bags -> OFFLOADED.
    for bag in services.bags_of_entry(entry["id"]):
        if bag["status"] == "LOADED":
            bag["status"] = "OFFLOADED"
            db.touch(bag)
    return success_obj(db.public(entry))


@bp.route("/manifest-entries/<entry_id>/disembark", methods=["POST"])
def disembark(entry_id):
    authenticate({"TerminalOperator"})
    entry = _get_entry_or_404(entry_id)
    _require_direction(entry, "DEBARK")
    if entry["status"] != "ABOARD":
        raise ApiError(ERR_INVALID_STATE, 409, "disembark requires status ABOARD")
    call = db.get("port_calls", entry["port_call_id"])
    if call["status"] not in ("ARRIVED", "TURNAROUND"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "disembark requires the call to be ARRIVED or TURNAROUND")
    case = services.customs_case_of(call["id"])
    if case is not None and case["status"] == "HELD":
        raise ApiError(ERR_CUSTOMS_HOLD_ACTIVE, 409,
                       "the call's customs case is HELD")
    if case is None or case["status"] not in ("FILED", "CLEARED"):
        raise ApiError(ERR_CUSTOMS_NOT_CLEARED, 409,
                       "the call's customs case is not FILED or CLEARED")
    entry["status"] = "DISEMBARKED"
    db.touch(entry)
    return success_obj(db.public(entry))


@bp.route("/manifest-entries/<entry_id>/customs-hold", methods=["POST"])
def customs_hold(entry_id):
    authenticate({"CustomsOfficer"})
    entry = _get_entry_or_404(entry_id)
    _require_direction(entry, "DEBARK")
    if entry["status"] != "DISEMBARKED":
        raise ApiError(ERR_INVALID_STATE, 409, "customs-hold requires status DISEMBARKED")
    entry["status"] = "HELD"
    db.touch(entry)
    return success_obj(db.public(entry))


@bp.route("/manifest-entries/<entry_id>/customs-release", methods=["POST"])
def customs_release(entry_id):
    authenticate({"CustomsOfficer"})
    entry = _get_entry_or_404(entry_id)
    _require_direction(entry, "DEBARK")
    if entry["status"] not in ("DISEMBARKED", "HELD"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "customs-release requires status DISEMBARKED or HELD")
    entry["status"] = "CLEARED"
    db.touch(entry)
    return success_obj(db.public(entry))

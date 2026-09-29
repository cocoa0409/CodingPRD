"""Warm transfers to a public-safety answering point."""
from flask import Blueprint

import lookups
from auth import (ALL_ROLES, INTAKE_AGENT, TRIAGE_NURSE, acting_role,
                  acting_user, authorize)
from envelope import list_response, object_response, pagination_params
from errors import ApiError
from serializers import warm_transfer_json
from store import base_record, ordered, store, touch
from util import PSAP_CODE_RE, STATE_RE
from validators import (body, get_bool, get_enum, get_int, get_number,
                        get_string, query_enum)

bp = Blueprint("transfers", __name__)

LOCATION_SOURCES = ("CALLER_STATED", "DEVICE_GPS", "PRACTICE_RECORD")
TRANSFER_STATUSES = ("INITIATED", "LOCATION_CONFIRMED", "ACCEPTED_BY_PSAP",
                     "REJECTED_BY_PSAP", "HANDOFF_COMPLETE")
SLOT_TAKEN_STATUSES = ("INITIATED", "LOCATION_CONFIRMED", "ACCEPTED_BY_PSAP",
                       "HANDOFF_COMPLETE")
LOCATION_CONFIDENCE_MIN = 75


def _require_assigned_nurse(call):
    if acting_role() == TRIAGE_NURSE and call["assigned_nurse_id"] != acting_user():
        raise ApiError("ERR_NOT_ASSIGNED_NURSE")


@bp.route("/triage-calls/<call_id>/warm-transfers", methods=["POST"])
@authorize([TRIAGE_NURSE])
def create_warm_transfer(call_id):
    data = body()
    psap_code = get_string(data, "psap_center_code", pattern=PSAP_CODE_RE)
    source = get_enum(data, "location_source", LOCATION_SOURCES)
    address = get_string(data, "location_address_line", max_len=200, allow_empty=True)
    state_code = get_string(data, "location_state_code", pattern=STATE_RE)
    lat = get_number(data, "location_lat")
    lng = get_number(data, "location_lng")
    callback_number = get_string(data, "callback_number", min_len=1, max_len=32)

    call = lookups.call(call_id)
    _require_assigned_nurse(call)

    if not address.strip() or not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        raise ApiError("ERR_INVALID_LOCATION")
    if state_code != call["caller_state_code"]:
        raise ApiError("ERR_LOCATION_STATE_MISMATCH")
    if not call["requires_warm_transfer"]:
        raise ApiError("ERR_WARM_TRANSFER_NOT_INDICATED")
    for existing in ordered(store.warm_transfers):
        if existing["call_id"] == call_id and existing["status"] in SLOT_TAKEN_STATUSES:
            raise ApiError("ERR_WARM_TRANSFER_ALREADY_OPEN")

    record = base_record()
    record.update({
        "call_id": call_id,
        "psap_center_code": psap_code,
        "location_source": source,
        "location_address_line": address,
        "location_state_code": state_code,
        "location_lat": lat,
        "location_lng": lng,
        "callback_number": callback_number,
        "location_verified_by": None,
        "location_confidence_pct": None,
        "psap_incident_number": None,
        "status": "INITIATED",
    })
    store.warm_transfers[record["id"]] = record
    return object_response(warm_transfer_json(record), 201)


@bp.route("/warm-transfers/<transfer_id>", methods=["GET"])
@authorize(ALL_ROLES)
def read_warm_transfer(transfer_id):
    return object_response(warm_transfer_json(lookups.warm_transfer(transfer_id)))


@bp.route("/triage-calls/<call_id>/warm-transfers", methods=["GET"])
@authorize(ALL_ROLES)
def list_call_warm_transfers(call_id):
    limit, offset = pagination_params()
    status = query_enum("status", TRANSFER_STATUSES)
    lookups.call(call_id)
    rows = [t for t in ordered(store.warm_transfers) if t["call_id"] == call_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    return list_response(rows, warm_transfer_json, limit, offset)


@bp.route("/warm-transfers/<transfer_id>/confirm-location", methods=["POST"])
@authorize([TRIAGE_NURSE])
def confirm_location(transfer_id):
    data = body()
    confidence = get_int(data, "location_confidence_pct", minimum=0, maximum=100)

    transfer = lookups.warm_transfer(transfer_id)
    call = store.calls.get(transfer["call_id"])
    if call is None:
        raise ApiError("ERR_TRIAGE_CALL_NOT_FOUND")
    _require_assigned_nurse(call)
    if transfer["status"] != "INITIATED":
        raise ApiError("ERR_TRANSFER_INVALID_STATE")
    if confidence < LOCATION_CONFIDENCE_MIN:
        raise ApiError("ERR_LOCATION_CONFIDENCE_TOO_LOW")

    transfer["location_verified_by"] = acting_user()
    transfer["location_confidence_pct"] = confidence
    transfer["status"] = "LOCATION_CONFIRMED"
    touch(transfer)
    return object_response(warm_transfer_json(transfer))


@bp.route("/warm-transfers/<transfer_id>/psap-response", methods=["POST"])
@authorize([INTAKE_AGENT])
def psap_response(transfer_id):
    data = body()
    accepted = get_bool(data, "accepted")
    incident_number = get_string(data, "psap_incident_number", required=accepted,
                                 min_len=1, max_len=60)

    transfer = lookups.warm_transfer(transfer_id)
    if transfer["status"] != "LOCATION_CONFIRMED":
        raise ApiError("ERR_TRANSFER_INVALID_STATE")

    if accepted:
        transfer["psap_incident_number"] = incident_number
        transfer["status"] = "ACCEPTED_BY_PSAP"
    else:
        transfer["status"] = "REJECTED_BY_PSAP"
    touch(transfer)
    return object_response(warm_transfer_json(transfer))


@bp.route("/warm-transfers/<transfer_id>/complete-handoff", methods=["POST"])
@authorize([TRIAGE_NURSE])
def complete_handoff(transfer_id):
    transfer = lookups.warm_transfer(transfer_id)
    call = store.calls.get(transfer["call_id"])
    if call is None:
        raise ApiError("ERR_TRIAGE_CALL_NOT_FOUND")
    _require_assigned_nurse(call)
    if transfer["status"] != "ACCEPTED_BY_PSAP":
        raise ApiError("ERR_TRANSFER_INVALID_STATE")

    transfer["status"] = "HANDOFF_COMPLETE"
    touch(transfer)
    call["warm_transfer_completed_at"] = store.clock
    touch(call)
    return object_response(warm_transfer_json(transfer))

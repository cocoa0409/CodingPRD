"""HearingSlot routes."""

from __future__ import annotations

from flask import Blueprint, request

from app.envelope import list_response, success_response
from app.routes._helpers import (
    get_json_body,
    paginate,
    parse_pagination,
    with_auth,
)
from app.serializers import serialize_hearing_slot
from app.services import hearing_slots as service


bp = Blueprint("hearing_slots", __name__)


@bp.route("/hearing-slots", methods=["POST"])
@with_auth("ALJ", "PlatformAdmin")
def create_slot(caller):
    body = get_json_body()
    record = service.create_slot(body)
    return success_response(serialize_hearing_slot(record), status=201)


@bp.route("/hearing-slots", methods=["GET"])
@with_auth("ALJ", "AppealsCouncil", "Claimant", "PlatformAdmin")
def list_slots(caller):
    limit, offset = parse_pagination()
    alj_id = request.args.get("alj_id")
    status = request.args.get("status")
    from_ = request.args.get("from")
    to = request.args.get("to")
    rows = service.list_slots(alj_id, status, from_, to)
    page, total = paginate(rows, limit, offset)
    return list_response(
        [serialize_hearing_slot(r) for r in page],
        limit=limit,
        offset=offset,
        total=total,
    )


@bp.route("/hearing-slots/<slot_id>/book", methods=["POST"])
@with_auth("ALJ")
def book_slot(caller, slot_id: str):
    body = get_json_body()
    record = service.book_slot(slot_id, body)
    return success_response(serialize_hearing_slot(record))


@bp.route("/hearing-slots/<slot_id>/hold", methods=["POST"])
@with_auth("ALJ")
def hold_slot(caller, slot_id: str):
    record = service.hold_slot(slot_id)
    return success_response(serialize_hearing_slot(record))


@bp.route("/hearing-slots/<slot_id>/no-show", methods=["POST"])
@with_auth("ALJ")
def no_show(caller, slot_id: str):
    record = service.no_show_slot(slot_id)
    return success_response(serialize_hearing_slot(record))


@bp.route("/hearing-slots/<slot_id>/reschedule", methods=["POST"])
@with_auth("ALJ")
def reschedule(caller, slot_id: str):
    body = get_json_body()
    record = service.reschedule_slot(slot_id, body)
    return success_response(serialize_hearing_slot(record))

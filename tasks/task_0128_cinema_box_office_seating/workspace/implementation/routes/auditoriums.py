"""Auditorium endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
import errors as E
from middleware import authenticate, authorize, CINEMA_MANAGER, BOX_OFFICE_AGENT
import response
from services import common as C
from routes._helpers import get_or_404

bp = Blueprint("auditoriums", __name__)


@bp.route("/auditoriums", methods=["POST"])
def create_auditorium():
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})
    body = C.get_body()
    C.require_fields(body, ["name", "seat_count"])
    name = C.require_str(body, "name")
    seat_count = C.require_int(body, "seat_count")
    if seat_count < 1:
        raise E.invalid_request("seat_count must be >= 1")

    turnaround = body.get("turnaround_minutes", 20)
    if turnaround is None:
        turnaround = 20
    if not C.is_int(turnaround) or turnaround < 0:
        raise E.invalid_request("turnaround_minutes must be an integer >= 0")

    aud = C.new_common_fields()
    aud.update({
        "name": name,
        "seat_count": seat_count,
        "turnaround_minutes": turnaround,
        "status": "ACTIVE",
    })
    db.auditoriums[aud["id"]] = aud
    return response.ok_object(C.serialize(aud), 201)


@bp.route("/auditoriums/<aud_id>", methods=["GET"])
def get_auditorium(aud_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, BOX_OFFICE_AGENT})
    aud = get_or_404(db.auditoriums, aud_id, "Auditorium")
    return response.ok_object(C.serialize(aud), 200)


@bp.route("/auditoriums", methods=["GET"])
def list_auditoriums():
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, BOX_OFFICE_AGENT})
    limit, offset = C.parse_pagination()
    from flask import request
    status = request.args.get("status")
    items = list(db.auditoriums.values())
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)

"""AdvancePacket endpoints (PRD 3.5): get packet, section submit/approve/reject,
plus flat fetch/search.

Every section transition (submit, approve, reject) increments packet_revision
by one. A rejected section is recorded and immediately returned to PENDING
for re-submission (a single revision bump per reject call). Approval is
guarded by expected_packet_revision (PRD 2.8).
"""
from flask import Blueprint, request

from db import store, touch
from errors import ApiError
from middleware import (
    authenticate, READ_ROLES, ROLE_TOUR_MANAGER, ROLE_VENUE_REP, get_body, v_int,
)
from response import success_object, list_response
from services import (
    SECTION_FIELDS, packet_json, resolve_tour, resolve_show, packet_for_show,
)

bp = Blueprint("packets", __name__)


def _resolve_packet(tourId, showId):
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    p = packet_for_show(s["id"])
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "AdvancePacket not found")
    return t, s, p


def _resolve_section(section):
    field = SECTION_FIELDS.get(section)
    if field is None:
        # The section path identifier must be one of tech_rider, hospitality,
        # immigration (PRD 3.5); anything else does not resolve.
        raise ApiError("ERR_NOT_FOUND", 404, "Advance-packet section not found")
    return field


@bp.get("/tours/<tourId>/shows/<showId>/advance-packet")
def get_packet(tourId, showId):
    authenticate(READ_ROLES)
    _, _, p = _resolve_packet(tourId, showId)
    return success_object(packet_json(p))


@bp.post("/tours/<tourId>/shows/<showId>/advance-packet/sections/<section>/submit")
def submit_section(tourId, showId, section):
    authenticate(frozenset({ROLE_TOUR_MANAGER}))
    _, _, p = _resolve_packet(tourId, showId)
    field = _resolve_section(section)
    if p[field] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "submit requires section.status == PENDING"
        )
    p[field] = "SUBMITTED"
    p["packet_revision"] += 1
    touch(p)
    return success_object(packet_json(p))


@bp.post("/tours/<tourId>/shows/<showId>/advance-packet/sections/<section>/approve")
def approve_section(tourId, showId, section):
    authenticate(frozenset({ROLE_VENUE_REP}))
    _, _, p = _resolve_packet(tourId, showId)
    field = _resolve_section(section)
    b = get_body()
    # OCC gate (PRD 2.8): expected_packet_revision is non-optional.
    expected_packet_revision = v_int(b, "expected_packet_revision")
    if expected_packet_revision != p["packet_revision"]:
        raise ApiError(
            "ERR_STALE_PACKET_REVISION",
            412,
            "expected_packet_revision does not match AdvancePacket.packet_revision",
        )
    if p[field] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "approve requires section.status == SUBMITTED"
        )
    p[field] = "APPROVED"
    p["packet_revision"] += 1
    touch(p)
    return success_object(packet_json(p))


@bp.post("/tours/<tourId>/shows/<showId>/advance-packet/sections/<section>/reject")
def reject_section(tourId, showId, section):
    authenticate(frozenset({ROLE_VENUE_REP}))
    _, _, p = _resolve_packet(tourId, showId)
    field = _resolve_section(section)
    if p[field] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "reject requires section.status == SUBMITTED"
        )
    # Rejection is recorded and the section immediately returns to PENDING
    # for re-submission (PRD 3.5).
    p[field] = "PENDING"
    p["packet_revision"] += 1
    touch(p)
    return success_object(packet_json(p))


# --- Flat fetch / flat search (PRD 2.9) ---

@bp.get("/tours/advance-packets/<packetId>")
def flat_get_packet(packetId):
    authenticate(READ_ROLES)
    p = store["packets"].get(packetId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "AdvancePacket not found")
    return success_object(packet_json(p))


@bp.get("/tours/advance-packets")
def flat_search_packets():
    authenticate(READ_ROLES)
    show_id = request.args.get("show_id")
    items = list(store["packets"].values())
    if show_id is not None:
        items = [p for p in items if p["show_id"] == show_id]
    return list_response(items, packet_json)

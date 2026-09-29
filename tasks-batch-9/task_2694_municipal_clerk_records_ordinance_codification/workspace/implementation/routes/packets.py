"""Agenda packet revisions, their immutable items, posting and withdrawal."""
from flask import Blueprint

import calc
import domain
from core import (ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK, STAFF_ROLES, ApiError,
                  authorize, body_dict, db, fetch, listing, new_record, now_dt,
                  occ, ok, opt_bool, q, req_enum, req_int, req_str, touch)

bp = Blueprint("packets", __name__)

ITEM_TYPES = ("CONSENT", "PUBLIC_HEARING", "ORDINANCE_FIRST_READING",
              "ORDINANCE_ADOPTION", "RESOLUTION", "MINUTES", "REPORT")


@bp.route("/clerk/meetings/<meeting_id>/agenda-packets", methods=["POST"])
def create_packet(meeting_id):
    authorize((ROLE_CITY_CLERK,))
    meeting = fetch(db.meetings, meeting_id, "ERR_MEETING_NOT_FOUND")
    body = body_dict()
    late_addendum = opt_bool(body, "late_addendum", default=False)
    occ(body, "expected_meeting_version", meeting, "ERR_STALE_MEETING_VERSION")
    existing = domain.packets_of(meeting["id"])
    revision = 1 + max([p["revision_number"] for p in existing] or [0])
    if revision > calc.MAX_PACKET_REVISIONS:
        raise ApiError("ERR_PACKET_REVISION_LIMIT", 422)
    for prior in existing:
        if prior["status"] in ("DRAFT", "POSTED"):
            prior["status"] = "SUPERSEDED"
            touch(prior)
    packet = new_record()
    packet.update({
        "meeting_id": meeting["id"],
        "revision_number": revision,
        "status": "DRAFT",
        "late_addendum": late_addendum,
        "item_count": 0,
        "contains_public_hearing": False,
        "required_notice_hours": None,
        "notice_deadline_at": None,
        "posted_at": None,
        "notice_compliant": False,
    })
    domain.recompute_packet_notice(packet, meeting)
    db.packets[packet["id"]] = packet
    if meeting["status"] == "NOTICED":
        meeting["status"] = "SCHEDULED"
    domain.mirror_meeting_notice(meeting)
    touch(meeting)
    return ok(packet, 201)


@bp.route("/clerk/meetings/<meeting_id>/agenda-packets", methods=["GET"])
def list_packets_of_meeting(meeting_id):
    authorize(STAFF_ROLES)
    fetch(db.meetings, meeting_id, "ERR_MEETING_NOT_FOUND")
    return listing(domain.packets_of(meeting_id))


@bp.route("/clerk/agenda-packets/<packet_id>", methods=["GET"])
def get_packet(packet_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.packets, packet_id, "ERR_PACKET_NOT_FOUND"))


@bp.route("/clerk/agenda-packets", methods=["GET"])
def list_packets():
    authorize(STAFF_ROLES)
    return listing(list(db.packets.values()),
                   {"meeting_id": q("meeting_id"), "status": q("status")})


@bp.route("/clerk/agenda-packets/<packet_id>/agenda-items", methods=["POST"])
def create_item(packet_id):
    authorize((ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK))
    packet = fetch(db.packets, packet_id, "ERR_PACKET_NOT_FOUND")
    body = body_dict()
    sequence_number = req_int(body, "sequence_number", minimum=1)
    item_type = req_enum(body, "item_type", ITEM_TYPES)
    title = req_str(body, "title")
    if packet["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PACKET_STATE", 409)
    for sibling in domain.items_of(packet["id"]):
        if sibling["sequence_number"] == sequence_number:
            raise ApiError("ERR_DUPLICATE_SEQUENCE_NUMBER", 422)
    item = new_record(versioned=False)
    item.update({
        "packet_id": packet["id"],
        "sequence_number": sequence_number,
        "item_type": item_type,
        "title": title,
    })
    db.agenda_items[item["id"]] = item
    domain.packet_derived(packet)
    touch(packet)
    return ok(item, 201)


@bp.route("/clerk/agenda-packets/<packet_id>/agenda-items", methods=["GET"])
def list_items_of_packet(packet_id):
    authorize(STAFF_ROLES)
    fetch(db.packets, packet_id, "ERR_PACKET_NOT_FOUND")
    return listing(domain.items_of(packet_id),
                   sort_key=lambda r: (r["sequence_number"], r["_seq"]))


@bp.route("/clerk/agenda-items/<item_id>", methods=["GET"])
def get_item(item_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.agenda_items, item_id, "ERR_AGENDA_ITEM_NOT_FOUND"))


@bp.route("/clerk/agenda-items", methods=["GET"])
def list_items():
    authorize(STAFF_ROLES)
    return listing(list(db.agenda_items.values()),
                   {"packet_id": q("packet_id"), "item_type": q("item_type")},
                   sort_key=lambda r: (r["created_at"], r["_seq"]))


@bp.route("/clerk/agenda-packets/<packet_id>/post", methods=["POST"])
def post_packet(packet_id):
    authorize((ROLE_CITY_CLERK,))
    packet = fetch(db.packets, packet_id, "ERR_PACKET_NOT_FOUND")
    meeting = db.meetings.get(packet["meeting_id"])
    if packet["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PACKET_STATE", 409)
    if meeting is None or meeting["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_MEETING_STATE", 409)
    domain.packet_derived(packet)
    if packet["item_count"] < 1:
        raise ApiError("ERR_EMPTY_AGENDA_PACKET", 422)
    domain.recompute_packet_notice(packet, meeting)
    packet["posted_at"] = now_dt()
    packet["notice_compliant"] = calc.agenda_notice_compliance(
        packet["posted_at"], packet["notice_deadline_at"])
    packet["status"] = "POSTED"
    touch(packet)
    meeting["status"] = "NOTICED"
    domain.mirror_meeting_notice(meeting)
    touch(meeting)
    domain.new_notice("MEETING_AGENDA", meeting=meeting)
    return ok(packet)


@bp.route("/clerk/agenda-packets/<packet_id>/withdraw", methods=["POST"])
def withdraw_packet(packet_id):
    authorize((ROLE_CITY_CLERK,))
    packet = fetch(db.packets, packet_id, "ERR_PACKET_NOT_FOUND")
    if packet["status"] not in ("DRAFT", "POSTED"):
        raise ApiError("ERR_INVALID_PACKET_STATE", 409)
    was_posted = packet["status"] == "POSTED"
    packet["status"] = "WITHDRAWN"
    touch(packet)
    meeting = db.meetings.get(packet["meeting_id"])
    if was_posted and meeting is not None:
        if meeting["status"] == "NOTICED":
            meeting["status"] = "SCHEDULED"
        domain.void_meeting_agenda_notices(meeting["id"])
        domain.mirror_meeting_notice(meeting)
        touch(meeting)
    return ok(packet)

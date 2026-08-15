"""BoardSeat + Committee routes."""
from flask import Blueprint, request

import db
from db import clock, _format_iso
from middleware import get_auth, require_roles
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_TERM_WINDOW_INVALID, ERR_SEAT_TERM_OVERLAP, ERR_SUCCESSOR_ALREADY_BOOKED,
    ERR_COMMITTEE_FULL, ERR_CHAIR_ALREADY_ASSIGNED, ERR_DUPLICATE_MEMBERSHIP,
)
from services.core import (
    get_body, check_unknown_fields, req_str, req_enum, req_int, req_datetime,
    new_entity, touch, get_or_404, pagination_params, paginate,
    serialize_seat, serialize_committee, committee_status,
)

bp = Blueprint("seats_committees", __name__)
ALL_ROLES = ("BoardAdmin", "Physician", "ComplianceOfficer")


# ---------------- BoardSeat ----------------

@bp.post("/governance/board-seats")
def create_seat():
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["seat_label", "seat_class"])
    require_roles(role, ("BoardAdmin",))
    seat_label = req_str(body, "seat_label")
    seat_class = req_enum(body, "seat_class", ("CLINICAL", "AT_LARGE", "EX_OFFICIO"))
    s = new_entity(db.board_seats, {
        "seat_label": seat_label,
        "seat_class": seat_class,
        "status": "VACANT",
        "current_holder_physician_id": None,
        "current_term_start": None,
        "current_term_end": None,
        "next_holder_physician_id": None,
        "next_term_start": None,
        "next_term_end": None,
    })
    return success_object(serialize_seat(s), 201)


@bp.get("/governance/board-seats")
def list_seats():
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.board_seats.values())
    f_status = request.args.get("status")
    f_cur = request.args.get("current_holder_physician_id")
    f_next = request.args.get("next_holder_physician_id")
    if f_status is not None:
        items = [s for s in items if s["status"] == f_status]
    if f_cur is not None:
        items = [s for s in items if s.get("current_holder_physician_id") == f_cur]
    if f_next is not None:
        items = [s for s in items if s.get("next_holder_physician_id") == f_next]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_seat(s) for s in page], limit, offset, total)


@bp.get("/governance/board-seats/<sid>")
def get_seat(sid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    s = get_or_404(db.board_seats, sid, "BoardSeat")
    return success_object(serialize_seat(s))


@bp.post("/governance/board-seats/<sid>/appoint")
def appoint_seat(sid):
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["physician_id", "term_start", "term_end"])
    require_roles(role, ("BoardAdmin",))
    s = get_or_404(db.board_seats, sid, "BoardSeat")

    physician_id = body.get("physician_id")
    if not isinstance(physician_id, str) or not physician_id:
        raise_err(ERR_INVALID_REQUEST, "physician_id is required")
    term_start = req_datetime(body, "term_start")
    term_end = req_datetime(body, "term_end")

    phys = db.physicians.get(physician_id)
    if phys is None:
        raise_err(ERR_NOT_FOUND, "Physician not found")

    # state: holder eligibility
    if phys["partnership_status"] != "SHAREHOLDER" or phys["standing"] == "SUSPENDED":
        raise_err(ERR_INVALID_STATE,
                  "Holder must be SHAREHOLDER and not SUSPENDED")
    # temporal: window well-formed
    if term_end <= term_start:
        raise_err(ERR_TERM_WINDOW_INVALID, "term_end must be after term_start")

    if s["status"] == "VACANT":
        s["current_holder_physician_id"] = physician_id
        s["current_term_start"] = _format_iso(term_start)
        s["current_term_end"] = _format_iso(term_end)
        s["status"] = "FILLED"
    else:
        # FILLED -> book successor
        if s.get("next_holder_physician_id"):
            raise_err(ERR_SUCCESSOR_ALREADY_BOOKED,
                      "Seat already has a booked successor")
        from db import _parse_iso
        cur_end = _parse_iso(s["current_term_end"])
        if term_start < cur_end:
            raise_err(ERR_SEAT_TERM_OVERLAP,
                      "Successor term must not overlap current term")
        s["next_holder_physician_id"] = physician_id
        s["next_term_start"] = _format_iso(term_start)
        s["next_term_end"] = _format_iso(term_end)
    touch(s)
    return success_object(serialize_seat(s))


# ---------------- Committee ----------------

@bp.post("/governance/committees")
def create_committee():
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["name", "committee_type", "quorum_count",
                                "approval_threshold"])
    require_roles(role, ("BoardAdmin",))
    name = req_str(body, "name")
    ctype = req_enum(body, "committee_type", ("QUALITY", "FINANCE", "COMPENSATION"))
    quorum = req_int(body, "quorum_count", min_val=1)
    threshold = req_enum(body, "approval_threshold",
                         ("SIMPLE_MAJORITY", "SUPERMAJORITY"))
    c = new_entity(db.committees, {
        "name": name,
        "committee_type": ctype,
        "quorum_count": quorum,
        "approval_threshold": threshold,
        "charter_version": 1,
        "members": [],
        "status": "CHARTERED",
    })
    return success_object(serialize_committee(c), 201)


@bp.get("/governance/committees")
def list_committees():
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.committees.values())
    f_type = request.args.get("committee_type")
    f_status = request.args.get("status")
    if f_type is not None:
        items = [c for c in items if c["committee_type"] == f_type]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_committee(c) for c in page], limit, offset, total)


@bp.get("/governance/committees/<cid>")
def get_committee(cid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    c = get_or_404(db.committees, cid, "Committee")
    return success_object(serialize_committee(c))


@bp.post("/governance/committees/<cid>/members")
def add_member(cid):
    role, _ = get_auth()
    body = get_body()
    check_unknown_fields(body, ["physician_id", "committee_role"])
    require_roles(role, ("BoardAdmin",))
    c = get_or_404(db.committees, cid, "Committee")
    physician_id = body.get("physician_id")
    if not isinstance(physician_id, str) or not physician_id:
        raise_err(ERR_INVALID_REQUEST, "physician_id is required")
    crole = req_enum(body, "committee_role", ("CHAIR", "MEMBER"))

    if db.physicians.get(physician_id) is None:
        raise_err(ERR_NOT_FOUND, "Physician not found")

    if c["status"] == "DISSOLVED":
        raise_err(ERR_INVALID_STATE, "Committee is DISSOLVED")

    # cardinality
    max_members = db.policy["max_committee_members"] if db.policy else 7
    if len(c["members"]) >= max_members:
        raise_err(ERR_COMMITTEE_FULL, "Committee is full")
    if any(m["physician_id"] == physician_id for m in c["members"]):
        raise_err(ERR_DUPLICATE_MEMBERSHIP, "Physician already a member")
    if crole == "CHAIR" and any(m["committee_role"] == "CHAIR" for m in c["members"]):
        raise_err(ERR_CHAIR_ALREADY_ASSIGNED, "Committee already has a CHAIR")

    c["members"].append({
        "physician_id": physician_id,
        "committee_role": crole,
        "added_at": clock.now_iso(),
    })
    c["status"] = committee_status(len(c["members"]), c["quorum_count"], c["status"])
    touch(c)
    return success_object(serialize_committee(c))


@bp.post("/governance/committees/<cid>/members/<physician_id>/remove")
def remove_member(cid, physician_id):
    role, _ = get_auth()
    require_roles(role, ("BoardAdmin",))
    c = get_or_404(db.committees, cid, "Committee")
    if db.physicians.get(physician_id) is None:
        raise_err(ERR_NOT_FOUND, "Physician not found")
    if c["status"] == "DISSOLVED":
        raise_err(ERR_INVALID_STATE, "Committee is DISSOLVED")
    idx = next((i for i, m in enumerate(c["members"])
                if m["physician_id"] == physician_id), None)
    if idx is None:
        raise_err(ERR_NOT_FOUND, "Membership not found")
    c["members"].pop(idx)
    c["status"] = committee_status(len(c["members"]), c["quorum_count"], c["status"])
    touch(c)
    return success_object(serialize_committee(c))


@bp.post("/governance/committees/<cid>/dissolve")
def dissolve_committee(cid):
    role, _ = get_auth()
    require_roles(role, ("BoardAdmin",))
    c = get_or_404(db.committees, cid, "Committee")
    if c["status"] == "DISSOLVED":
        raise_err(ERR_INVALID_STATE, "Committee already DISSOLVED")
    # blocked while any motion referencing this committee is OPEN or TABLED
    for m in db.motions.values():
        if m.get("committee_id") == cid and m["status"] in ("OPEN", "TABLED"):
            raise_err(ERR_INVALID_STATE,
                      "Committee referenced by an OPEN/TABLED motion")
    c["members"] = []
    c["status"] = "DISSOLVED"
    touch(c)
    return success_object(serialize_committee(c))

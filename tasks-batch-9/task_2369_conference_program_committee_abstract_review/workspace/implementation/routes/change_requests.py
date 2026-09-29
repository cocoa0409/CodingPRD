"""Program change request endpoints (late program changes and fees)."""

from flask import Blueprint

from db import db, new_row, parse_dt, touch
from errors import fail
from middleware import ROLE_ADMIN, ROLE_AUTHOR, ROLE_CHAIR, endpoint
from response import created, ok, ok_list
from routes.helpers import filtered, lookup, resolve_fk
from services import calc, derive, logic
from validators import (body_json, paginate, present, q_str, v_enum, v_string)

bp = Blueprint("change_requests", __name__)

CHANGE_TYPES = ("MOVE", "SWAP", "SUBSTITUTE_PRESENTER", "WITHDRAW")


@bp.post("/program-change-requests")
@endpoint(ROLE_AUTHOR, ROLE_CHAIR)
def create_change_request(actor):
    body = body_json()
    slot = resolve_fk(body, "session_slot_id")
    requested_by = resolve_fk(body, "requested_by_author_id")
    target_session = resolve_fk(body, "target_session_id")
    substitute = resolve_fk(body, "substitute_presenter_author_id")

    if slot is None:
        fail("ERR_VALIDATION", "session_slot_id is required.")
    session = db.sessions.get(slot["session_id"])
    abstract = db.abstracts.get(slot["abstract_id"])
    conference = db.conferences.get(session["conference_id"]) if session else None

    # Band 6 — ownership.
    if actor.is_author:
        if actor.author_id not in (slot["presenter_author_id"],
                                   abstract["submitting_author_id"] if abstract else None):
            fail("ERR_NOT_RESOURCE_OWNER")
    else:
        if conference is None or actor.member["conference_id"] != conference["id"]:
            fail("ERR_NOT_RESOURCE_OWNER")

    change_type = v_enum(body, "change_type", CHANGE_TYPES, required=True)
    if present(body, "reason"):
        v_string(body, "reason", min_len=1)
    if change_type in ("MOVE", "SWAP") and target_session is None:
        fail("ERR_VALIDATION", "target_session_id is required for %s." % change_type)
    if change_type == "SUBSTITUTE_PRESENTER" and substitute is None:
        fail("ERR_VALIDATION",
             "substitute_presenter_author_id is required for SUBSTITUTE_PRESENTER.")

    # Band 9 — conference gate (including the event-window ceiling).
    if conference is None or conference["status"] not in ("DECISIONS_RELEASED",
                                                          "PROGRAM_PUBLISHED"):
        fail("ERR_CONFERENCE_STATE_INVALID",
             "Late changes are accepted once decisions are released.")
    if not (db.now() < parse_dt(conference["event_end_utc"])):
        fail("ERR_CONFERENCE_STATE_INVALID", "The conference window has closed.")
    # Band 10.
    if slot["status"] != "SCHEDULED":
        fail("ERR_SLOT_STATE_INVALID")
    for existing in db.change_requests.values():
        if existing["session_slot_id"] == slot["id"] and existing["status"] == "PENDING":
            fail("ERR_CHANGE_REQUEST_STATE_INVALID",
                 "A pending change request already exists for this slot.")
    # Band 14.
    if change_type == "SUBSTITUTE_PRESENTER":
        if abstract is None or substitute["email"] not in abstract["coauthor_emails"]:
            fail("ERR_PRESENTER_NOT_ON_ABSTRACT")

    if requested_by is not None:
        requested_by_id = requested_by["id"]
    elif actor.is_author:
        requested_by_id = actor.author_id
    else:
        requested_by_id = slot["presenter_author_id"]

    submitted_at = db.now_raw()
    days_to_event = int(
        (parse_dt(conference["event_start_utc"]) - db.now()).total_seconds() // 86400)

    row = new_row({
        "conference_id": conference["id"],
        "session_slot_id": slot["id"],
        "requested_by_author_id": requested_by_id,
        "change_type": change_type,
        "target_session_id": target_session["id"] if target_session else None,
        "substitute_presenter_author_id": substitute["id"] if substitute else None,
        "approver_member_id": None,
        "status": "PENDING",
        "submitted_at": submitted_at,
        "days_to_event": days_to_event,
        "estimated_fee_cents": calc.estimated_fee(change_type, days_to_event),
        "final_fee_cents": None,
        "rush_pct_applied": None,
    })
    db.change_requests[row["id"]] = row
    return created(derive.change_request_out(row))


@bp.get("/program-change-requests")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_AUTHOR)
def list_change_requests(actor):
    rows = filtered(db.change_requests.values(), {
        "conference_id": q_str("conference_id"),
        "session_slot_id": q_str("session_slot_id"),
        "requested_by_author_id": q_str("requested_by_author_id"),
        "target_session_id": q_str("target_session_id"),
        "substitute_presenter_author_id": q_str("substitute_presenter_author_id"),
        "approver_member_id": q_str("approver_member_id"),
        "change_type": q_str("change_type"),
        "status": q_str("status"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.change_request_out(r) for r in page], meta)


@bp.get("/program-change-requests/<request_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_AUTHOR)
def get_change_request(actor, request_id):
    row = lookup("change_requests", request_id, "ERR_CHANGE_REQUEST_NOT_FOUND")
    return ok(derive.change_request_out(row))


@bp.post("/program-change-requests/<request_id>/adjudication")
@endpoint(ROLE_CHAIR)
def adjudicate_change_request(actor, request_id):
    request_row = lookup("change_requests", request_id, "ERR_CHANGE_REQUEST_NOT_FOUND")
    body = body_json()
    outcome = v_enum(body, "outcome", ("APPROVED", "REJECTED"), required=True)
    if present(body, "note"):
        v_string(body, "note", min_len=1)

    # Band 10.
    if request_row["status"] != "PENDING":
        fail("ERR_CHANGE_REQUEST_STATE_INVALID")

    slot = db.slots.get(request_row["session_slot_id"])
    session = db.sessions.get(slot["session_id"]) if slot else None
    abstract = db.abstracts.get(slot["abstract_id"]) if slot else None
    conference = db.conferences.get(request_row["conference_id"])

    if outcome == "REJECTED":
        request_row["status"] = "REJECTED"
        request_row["final_fee_cents"] = 0
        request_row["approver_member_id"] = actor.member_id
        touch(request_row)
        return ok(derive.change_request_out(request_row))

    if slot is None or slot["status"] != "SCHEDULED":
        fail("ERR_SLOT_STATE_INVALID")

    change_type = request_row["change_type"]
    target = db.sessions.get(request_row["target_session_id"]) if request_row["target_session_id"] else None

    if change_type in ("MOVE", "SWAP"):
        if target is None:
            fail("ERR_SESSION_NOT_FOUND")
        # Band 14.
        if target["format"] != abstract["decision"]:
            fail("ERR_SESSION_FORMAT_MISMATCH")
        if target["theme_code"] not in abstract["keywords"]:
            fail("ERR_SESSION_THEME_MISMATCH")
        # Band 19.
        if derive.session_slot_count(target["id"]) >= target["capacity_slots"]:
            fail("ERR_SESSION_SLOT_CAPACITY_REACHED")

    days_to_event = request_row["days_to_event"]
    post_freeze = parse_dt(request_row["submitted_at"]) >= parse_dt(
        conference["program_freeze_utc"])
    request_row["status"] = "APPLIED"
    request_row["final_fee_cents"] = calc.final_fee(change_type, days_to_event, post_freeze)
    request_row["rush_pct_applied"] = calc.rush_pct_final(days_to_event)
    request_row["approver_member_id"] = actor.member_id
    touch(request_row)

    if change_type == "MOVE":
        position = derive.session_slot_count(target["id"]) + 1
        slot["status"] = "MOVED"
        touch(slot)
        replacement = new_row({
            "session_id": target["id"],
            "abstract_id": slot["abstract_id"],
            "presenter_author_id": slot["presenter_author_id"],
            "swapped_with_slot_id": None,
            "position": position,
            "duration_minutes": slot["duration_minutes"],
            "status": "SCHEDULED",
        })
        db.slots[replacement["id"]] = replacement
        logic.bump_session(session)
        logic.unpublish_if_empty(session)
        logic.bump_session(target)

    elif change_type == "SWAP":
        peers = [s for s in derive.session_slots(target["id"]) if s["status"] == "SCHEDULED"]
        if not peers:
            fail("ERR_SESSION_STATE_INVALID",
                 "The target session has no scheduled slot to swap with.")
        peers.sort(key=lambda s: s["position"])
        peer = peers[0]
        slot_session_id, slot_position = slot["session_id"], slot["position"]
        slot["session_id"] = peer["session_id"]
        slot["position"] = peer["position"]
        slot["swapped_with_slot_id"] = peer["id"]
        touch(slot)
        peer["session_id"] = slot_session_id
        peer["position"] = slot_position
        peer["swapped_with_slot_id"] = slot["id"]
        touch(peer)
        logic.bump_session(session)
        logic.bump_session(target)

    elif change_type == "SUBSTITUTE_PRESENTER":
        slot["presenter_author_id"] = request_row["substitute_presenter_author_id"]
        touch(slot)

    else:  # WITHDRAW
        logic.withdraw_abstract(abstract)

    return ok(derive.change_request_out(request_row))

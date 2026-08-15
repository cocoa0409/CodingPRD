"""Communication entries."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, mint, touch, pub, pub_list
from response import ok_object, ok_list
from util import parse_dt

bp = Blueprint("communications", __name__)


@bp.post("/tc/communications")
def create_communication():
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator", "Agent"})
    data = mw.body()
    # priority 3: body FK existence (file_id, then in_reply_to_id).
    file_rec = None
    if data.get("file_id") is not None:
        file_rec = mw.get_or_404("file", data["file_id"])
    reply_to = None
    if data.get("in_reply_to_id") is not None:
        reply_to = mw.get_or_404("communication", data["in_reply_to_id"])
    # priority 4: coordinator owns the file (agents: no party gate specified).
    if file_rec is not None and role == "Coordinator":
        mw.own_file(uid, file_rec)
    # priority 6: reply target must be OPEN.
    if reply_to is not None and reply_to["status"] != "OPEN":
        E.raise_err(E.ERR_COMMUNICATION_INVALID_STATE, "Reply target is not OPEN")
    # priority 8: response_due_at strictly after the current clock time.
    if data.get("requires_response") is True and isinstance(data.get("response_due_at"), str) \
            and mw.is_dt_str(data["response_due_at"]):
        if parse_dt(data["response_due_at"]) <= store.now:
            E.raise_err(E.ERR_RESPONSE_DUE_IN_PAST,
                        "response_due_at must be strictly after the current clock time")
    # priority 12: shape.
    mw.validate_shape(data, [
        ("file_id", "string", True),
        ("party", "enum", True, mw.PARTIES),
        ("direction", "enum", True, mw.DIRECTIONS),
        ("body", "string", True),
        ("requires_response", "bool", False),
        ("response_due_at", "datetime", False),
        ("in_reply_to_id", "string", False),
    ])
    if data.get("requires_response") is True and data.get("response_due_at") is None:
        E.raise_err(E.ERR_INVALID_REQUEST,
                    "response_due_at is required when requires_response is true")
    if reply_to is not None and reply_to["file_id"] != data["file_id"]:
        E.raise_err(E.ERR_INVALID_REQUEST, "in_reply_to_id references an entry on another file")
    rec = mint({
        "file_id": data["file_id"],
        "entry_kind": "LOG",
        "author_role": role,
        "party": data["party"],
        "direction": data["direction"],
        "body": data["body"],
        "requires_response": data.get("requires_response", False),
        "response_due_at": data.get("response_due_at"),
        "in_reply_to_id": data.get("in_reply_to_id"),
        "status": "OPEN",
    }, common=False)
    store.communications[rec["id"]] = rec
    if reply_to is not None and reply_to["status"] == "OPEN":
        reply_to["status"] = "ANSWERED"
    return ok_object(pub("communication", rec), 201)


@bp.get("/tc/communications/<communicationId>")
def get_communication(communicationId):
    mw.auth()
    rec = mw.get_or_404("communication", communicationId)
    return ok_object(pub("communication", rec))


@bp.get("/tc/communications")
def list_communications():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.communications.values())
    recs = mw.filter_eq(recs, "file_id", request.args.get("file_id"))
    recs = mw.filter_eq(recs, "status", request.args.get("status"))
    recs = mw.filter_eq(recs, "in_reply_to_id", request.args.get("in_reply_to_id"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("communication", page), limit, offset, total)


@bp.post("/tc/communications/<communicationId>/resolve")
def resolve_communication(communicationId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("communication", communicationId)
    file_rec = mw.own_file_chain(uid, rec, "communication")
    if rec["status"] not in ("OPEN", "ESCALATED"):
        E.raise_err(E.ERR_COMMUNICATION_INVALID_STATE,
                    "Only an OPEN or ESCALATED entry can be resolved")
    was_escalated = rec["status"] == "ESCALATED"
    rec["status"] = "RESOLVED"
    if was_escalated and file_rec is not None:
        file_rec["open_escalation_count"] = max(0, file_rec["open_escalation_count"] - 1)
        touch(file_rec)
    return ok_object(pub("communication", rec))

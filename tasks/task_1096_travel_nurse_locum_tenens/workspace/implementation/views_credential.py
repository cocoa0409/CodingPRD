"""Credential packets and credential items."""
import uuid

from app import app
from store import store
from common import (
    ApiError, ok, ok_list, authenticate, authorize, body, verr,
    req_str, opt_date, req_enum, new_common, touch, pagination, paginate,
    READ_ROLES, fine_authz, check_ownership,
)
from serializers import ser_packet, ser_item
from domain import (
    ITEM_TYPES, compute_readiness, apply_readiness, withdraw_open_extensions,
    _readiness_snapshot,
)


def _uuid():
    return str(uuid.uuid4())


def _filter(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ===========================================================================
# GET /assignments/{id}/credential-packets
# ===========================================================================
@app.route("/assignments/<aid>/credential-packets", methods=["GET"])
def list_assignment_packets(aid):
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    if aid not in store.assignments:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment not found")
    limit, offset = pagination()
    rows = [p for p in store.packets.values() if p["assignment_id"] == aid]
    window, total = paginate(rows, limit, offset)
    return ok_list([ser_packet(p) for p in window], limit, offset, total)


# ===========================================================================
# GET /credential-packets/{id}
# ===========================================================================
@app.route("/credential-packets/<pid>", methods=["GET"])
def get_packet(pid):
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    p = store.packets.get(pid)
    if not p:
        raise ApiError("ERR_PACKET_NOT_FOUND", 404, "Credential packet not found")
    return ok(ser_packet(p), 200)


# ===========================================================================
# GET /credential-packets/{id}/items
# ===========================================================================
@app.route("/credential-packets/<pid>/items", methods=["GET"])
def list_packet_items(pid):
    _uid, role = authenticate()
    authorize(role, READ_ROLES)
    if pid not in store.packets:
        raise ApiError("ERR_PACKET_NOT_FOUND", 404, "Credential packet not found")
    limit, offset = pagination()
    rows = [it for it in store.items.values() if it["packet_id"] == pid]
    type_f = _filter("item_type")
    status_f = _filter("status")
    if type_f is not None:
        rows = [it for it in rows if it["item_type"] == type_f]
    if status_f is not None:
        rows = [it for it in rows if it["status"] == status_f]
    window, total = paginate(rows, limit, offset)
    return ok_list([ser_item(it) for it in window], limit, offset, total)


# ===========================================================================
# POST /credential-packets/{id}/items
# ===========================================================================
@app.route("/credential-packets/<pid>/items", methods=["POST"])
def attach_item(pid):
    uid, role = authenticate()
    authorize(role, ["Clinician", "CredentialingSpecialist"])
    p = store.packets.get(pid)
    if not p:
        raise ApiError("ERR_PACKET_NOT_FOUND", 404, "Credential packet not found")
    a = store.assignments[p["assignment_id"]]
    check_ownership(role, uid, a)
    b = body()
    item_type = req_enum(b, "item_type", ITEM_TYPES)
    document_ref = req_str(b, "document_ref")
    expires_on = opt_date(b, "expires_on", None)

    it = new_common(True)
    it["id"] = _uuid()
    it.update({
        "packet_id": pid, "item_type": item_type, "document_ref": document_ref,
        "expires_on": expires_on, "status": "PENDING", "verified_by_user_id": None,
    })
    store.items[it["id"]] = it
    apply_readiness(p)
    return ok(ser_item(it), 201)


# ===========================================================================
# POST /credential-packets/{id}/transition
# ===========================================================================
PACKET_STATES = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED",
                 "CLEARED", "REJECTED"}


@app.route("/credential-packets/<pid>/transition", methods=["POST"])
def transition_packet(pid):
    uid, role = authenticate()
    authorize(role, ["Clinician", "CredentialingSpecialist"])
    b = body()
    fine_authz("packet", role, b.get("to"))
    p = store.packets.get(pid)
    if not p:
        raise ApiError("ERR_PACKET_NOT_FOUND", 404, "Credential packet not found")
    a = store.assignments[p["assignment_id"]]
    check_ownership(role, uid, a)
    to = req_str(b, "to")
    if to not in PACKET_STATES:
        verr("to must be one of %s" % sorted(PACKET_STATES))
    status = p["status"]

    if to == "SUBMITTED":
        if status not in ("DRAFT", "CHANGES_REQUESTED"):
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal packet transition")
        p["status"] = "SUBMITTED"
        p["submitted_by_user_id"] = uid
        compute_readiness(p)
        touch(p)
    elif to == "UNDER_REVIEW":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal packet transition")
        p["status"] = "UNDER_REVIEW"
        touch(p)
    elif to == "CHANGES_REQUESTED":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal packet transition")
        if p["revision_round"] >= 3:
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Revision rounds exhausted")
        p["status"] = "CHANGES_REQUESTED"
        p["revision_round"] += 1
        touch(p)
    elif to == "CLEARED":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal packet transition")
        # SoD (priority 9) before packet-cleared guard (priority 11)
        if uid == p["submitted_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Clearer must differ from submitter")
        compute_readiness(p)
        if p["blocking_item_count_start_basis"] != 0:
            raise ApiError("ERR_PACKET_NOT_CLEARED", 422, "Blocking items remain")
        p["status"] = "CLEARED"
        p["cleared_by_user_id"] = uid
        touch(p)
        if a["compliance_status"] in ("PENDING_CREDENTIALS", "SUSPENDED"):
            a["compliance_status"] = "CLEARED"
            touch(a)
    elif to == "REJECTED":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal packet transition")
        p["status"] = "REJECTED"
        touch(p)
    else:
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal packet transition")
    return ok(ser_packet(p), 200)


# ===========================================================================
# POST /credential-items/{id}/transition
# ===========================================================================
ITEM_STATES = {"PENDING", "VERIFIED", "REJECTED", "REVOKED", "EXPIRED"}
ITEM_EDGES = {
    "PENDING": {"VERIFIED", "REJECTED"},
    "REJECTED": {"PENDING"},
    "VERIFIED": {"REVOKED", "EXPIRED"},
    "REVOKED": set(),
    "EXPIRED": set(),
}


@app.route("/credential-items/<iid>/transition", methods=["POST"])
def transition_item(iid):
    uid, role = authenticate()
    authorize(role, ["CredentialingSpecialist"])
    it = store.items.get(iid)
    if not it:
        raise ApiError("ERR_CREDENTIAL_ITEM_NOT_FOUND", 404, "Credential item not found")
    b = body()
    to = req_str(b, "to")
    if to not in ITEM_STATES:
        verr("to must be one of %s" % sorted(ITEM_STATES))
    if to not in ITEM_EDGES[it["status"]]:
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Illegal item transition")

    it["status"] = to
    if to == "VERIFIED":
        it["verified_by_user_id"] = uid
    touch(it)

    # Recompute parent packet readiness; Cascade A when a cleared packet loses a required type.
    p = store.packets[it["packet_id"]]
    was_cleared = p["status"] == "CLEARED"
    before = _readiness_snapshot(p)
    compute_readiness(p)
    changed = _readiness_snapshot(p) != before
    if was_cleared and p["blocking_item_count_start_basis"] > 0:
        p["status"] = "CHANGES_REQUESTED"
        p["revision_round"] += 1
        touch(p)
        a = store.assignments[p["assignment_id"]]
        if a["compliance_status"] == "CLEARED":
            a["compliance_status"] = "SUSPENDED"
            touch(a)
            withdraw_open_extensions(a)
    elif changed:
        touch(p)
    return ok(ser_item(it), 200)

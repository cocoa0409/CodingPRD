"""EmergencyContact endpoints and contact-tree validation (PRD 3.6)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_auth, require_role
from models import new_record, touch, serialize_contact
from response import object_response, array_response
from services.lookup import (get_contact, get_subscriber, contacts_for_subscriber,
                             require_owner_subscriber)
from util import (get_json_body, require_fields, require_enum, require_bool,
                  parse_pagination, paginate)

bp = Blueprint("contacts", __name__)

RELATIONSHIPS = {"CAREGIVER", "FAMILY", "NEIGHBOR", "PHYSICIAN"}


def _check_no_cycle(subscriber_id, contact_id, escalates_to_id):
    """Walk the escalation chain from contact_id; reject if it loops back.

    contact_id is the contact being created/updated; escalates_to_id is its new
    fallback pointer. We follow escalates_to from escalates_to_id forward; if we
    ever reach contact_id again, that is a cycle.
    """
    if escalates_to_id is None:
        return
    seen = {contact_id}
    cur = escalates_to_id
    while cur is not None:
        if cur in seen:
            raise err("ERR_CONTACT_TREE_INVALID", "Escalation cycle detected")
        seen.add(cur)
        nxt = store.emergency_contacts.get(cur)
        if nxt is None:
            return
        cur = nxt.get("escalates_to_contact_id")


def _validate_escalation_target(subscriber_id, escalates_to_id):
    """escalates_to_contact_id must reference an existing contact of the same subscriber."""
    if escalates_to_id is None:
        return
    target = store.emergency_contacts.get(escalates_to_id)
    if target is None:
        raise err("ERR_NOT_FOUND", "escalates_to_contact_id not found")
    if target["subscriber_id"] != subscriber_id:
        raise err("ERR_CONTACT_TREE_INVALID", "Escalation target belongs to a different subscriber")


def _check_unique_rank(subscriber_id, rank, exclude_id=None):
    for c in contacts_for_subscriber(subscriber_id):
        if exclude_id is not None and c["id"] == exclude_id:
            continue
        if c["priority_rank"] == rank:
            raise err("ERR_CONTACT_TREE_INVALID", "priority_rank not unique within subscriber")


@bp.route("/pers/emergency-contacts", methods=["POST"])
def create_contact():
    uid, role = get_auth()
    require_role(role, {"Subscriber"})
    body = get_json_body()
    require_fields(body, ["subscriber_id", "name", "phone", "relationship", "priority_rank"])
    sub = get_subscriber(body["subscriber_id"])
    require_owner_subscriber(role, uid, sub["id"])

    require_enum(body["relationship"], RELATIONSHIPS, "relationship")
    rank = body["priority_rank"]
    if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
        raise err("ERR_INVALID_REQUEST", "priority_rank must be an integer >= 1")
    if not isinstance(body["name"], str) or body["name"] == "":
        raise err("ERR_INVALID_REQUEST", "name must be a non-empty string")
    if not isinstance(body["phone"], str) or body["phone"] == "":
        raise err("ERR_INVALID_REQUEST", "phone must be a non-empty string")

    escalates_to = body.get("escalates_to_contact_id")
    can_auth = body.get("can_authorize_911", False)
    if can_auth is None:
        can_auth = False
    require_bool(can_auth, "can_authorize_911")

    # existence of escalation target (FK) checked left-to-right (priority 3) then tree (priority 15)
    _validate_escalation_target(body["subscriber_id"], escalates_to)

    # contact tree validation (priority 15)
    _check_unique_rank(body["subscriber_id"], rank)

    r = new_record()
    r.update({
        "subscriber_id": body["subscriber_id"],
        "name": body["name"],
        "phone": body["phone"],
        "relationship": body["relationship"],
        "priority_rank": rank,
        "escalates_to_contact_id": escalates_to,
        "can_authorize_911": can_auth,
        "active": True,
    })
    # cycle check (the new contact's id can't yet be referenced, but be safe)
    _check_no_cycle(body["subscriber_id"], r["id"], escalates_to)
    store.emergency_contacts[r["id"]] = r
    return object_response(serialize_contact(r), 201)


@bp.route("/pers/emergency-contacts/<cid>", methods=["GET"])
def get_contact_route(cid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "CallCenterAgent"})
    r = get_contact(cid)
    return object_response(serialize_contact(r), 200)


@bp.route("/pers/emergency-contacts", methods=["GET"])
def list_contacts():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "CallCenterAgent"})
    limit, offset = parse_pagination()
    items = list(store.emergency_contacts.values())
    if "subscriber_id" in request.args:
        items = [c for c in items if c["subscriber_id"] == request.args.get("subscriber_id")]
    if "escalates_to_contact_id" in request.args:
        items = [c for c in items if c.get("escalates_to_contact_id") == request.args.get("escalates_to_contact_id")]
    # PRD 2.3 / 3.6: ordered by priority_rank ASC
    items = sorted(items, key=lambda c: (c["priority_rank"], c.get("_seq", 0)))
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_contact(c) for c in page], limit, offset, total)


@bp.route("/pers/emergency-contacts/<cid>", methods=["PATCH"])
def update_contact(cid):
    uid, role = get_auth()
    require_role(role, {"Subscriber"})
    r = get_contact(cid)
    require_owner_subscriber(role, uid, r["subscriber_id"])
    body = get_json_body()

    new_rank = r["priority_rank"]
    if "priority_rank" in body and body["priority_rank"] is not None:
        rank = body["priority_rank"]
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
            raise err("ERR_INVALID_REQUEST", "priority_rank must be an integer >= 1")
        new_rank = rank

    new_escalates = r.get("escalates_to_contact_id")
    escalates_provided = "escalates_to_contact_id" in body
    if escalates_provided:
        new_escalates = body["escalates_to_contact_id"]

    new_can_auth = r["can_authorize_911"]
    if "can_authorize_911" in body and body["can_authorize_911"] is not None:
        new_can_auth = require_bool(body["can_authorize_911"], "can_authorize_911")

    new_active = r["active"]
    if "active" in body and body["active"] is not None:
        new_active = require_bool(body["active"], "active")

    # validate escalation target existence + same subscriber (priority 3 / 15)
    if escalates_provided:
        _validate_escalation_target(r["subscriber_id"], new_escalates)

    # unique rank within subscriber (priority 15)
    if new_rank != r["priority_rank"]:
        _check_unique_rank(r["subscriber_id"], new_rank, exclude_id=cid)

    # cycle check with the proposed pointer (priority 15)
    if escalates_provided:
        _check_no_cycle(r["subscriber_id"], cid, new_escalates)

    r["priority_rank"] = new_rank
    if escalates_provided:
        r["escalates_to_contact_id"] = new_escalates
    r["can_authorize_911"] = new_can_auth
    r["active"] = new_active
    touch(r)
    return object_response(serialize_contact(r), 200)

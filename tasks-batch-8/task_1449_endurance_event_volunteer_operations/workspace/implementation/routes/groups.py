"""Fundraising groups + credit summary."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles
from response import success_object, success_list
from util import get_body, require_field, as_string
from services.core import (
    make_record, touch, paginate, sort_by_created, serialize_group,
    get_event_or_404, get_group_or_404,
)
from services.credit import credit_summary

bp = Blueprint("groups", __name__)
ANY = ("Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector")


@bp.post("/volunteer-ops/fundraising-groups")
def create_group():
    require_roles("EventDirector")
    body = get_body()
    event_id = as_string(require_field(body, "event_id"), "event_id")
    get_event_or_404(event_id)
    name = as_string(require_field(body, "name"), "name")
    charity_code = as_string(require_field(body, "charity_code"), "charity_code")
    for g in store.fundraising_groups.values():
        if g["event_id"] == event_id and g["charity_code"] == charity_code:
            raise errors.invalid_request("charity_code must be unique within the event.")
    rec = make_record({
        "event_id": event_id,
        "name": name,
        "charity_code": charity_code,
        "status": "ACTIVE",
    })
    store.fundraising_groups[rec["id"]] = rec
    return success_object(serialize_group(rec), status=201)


@bp.get("/volunteer-ops/fundraising-groups")
def list_groups():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    items = [g for g in store.fundraising_groups.values()
             if event_id is None or g["event_id"] == event_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_group(g) for g in page], limit, offset, total)


@bp.get("/volunteer-ops/fundraising-groups/<groupId>")
def get_group(groupId):
    require_roles(*ANY)
    grp = get_group_or_404(groupId)
    return success_object(serialize_group(grp))


@bp.get("/volunteer-ops/fundraising-groups/<groupId>/credit-summary")
def get_credit_summary(groupId):
    user_id, role = require_roles("GroupLeader", "EventDirector")
    grp = get_group_or_404(groupId)
    if role == "GroupLeader" and user_id != grp["id"]:
        raise errors.not_resource_owner()
    return success_object(credit_summary(grp))


@bp.post("/volunteer-ops/fundraising-groups/<groupId>/suspend")
def suspend_group(groupId):
    require_roles("EventDirector")
    grp = get_group_or_404(groupId)
    if grp["status"] != "ACTIVE":
        raise errors.group_invalid_state()
    grp["status"] = "SUSPENDED"
    touch(grp)
    return success_object(serialize_group(grp))


@bp.post("/volunteer-ops/fundraising-groups/<groupId>/reinstate")
def reinstate_group(groupId):
    require_roles("EventDirector")
    grp = get_group_or_404(groupId)
    if grp["status"] != "SUSPENDED":
        raise errors.group_invalid_state()
    grp["status"] = "ACTIVE"
    touch(grp)
    return success_object(serialize_group(grp))

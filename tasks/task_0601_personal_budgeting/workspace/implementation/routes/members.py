"""Member routes: invite, get, list."""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, enforce_household_access,
                     paginate_and_respond)
from lookups import get_household, get_member

bp = Blueprint("members", __name__)


@bp.route("/households/<household_id>/members", methods=["POST"])
@require_roles("HouseholdOwner")
def invite_member(household_id):
    h = get_household(household_id)
    enforce_household_access(household_id)
    body = get_body()
    email = require_str(body, "email")
    display_name = require_str(body, "display_name")

    with lock:
        # Email unique within the household.
        for m in db.members.values():
            if m["household_id"] == household_id and m["email"] == email:
                raise errors.ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                                      "Member email already exists in household")
        mid = new_id()
        ts = now_ts()
        member = {
            "id": mid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "household_id": household_id,
            "email": email,
            "display_name": display_name,
            "role": "MEMBER",
        }
        db.members[mid] = member
    return success(serializers.member(member), status=201)


@bp.route("/households/members/<member_id>", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def get_member_route(member_id):
    m = get_member(member_id)
    enforce_household_access(m["household_id"])
    return success(serializers.member(m), status=200)


@bp.route("/households/members", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def list_members():
    household_id = request.args.get("household_id")
    items = list(db.members.values())
    if household_id is not None:
        items = [m for m in items if m["household_id"] == household_id]
    return paginate_and_respond(items, serializers.member)

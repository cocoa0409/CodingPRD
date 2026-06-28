"""Member endpoints (PRD §3.3)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers

bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def create_member():
    # Public registration (Anonymous) — no auth required.
    body = common.get_body()
    email = common.req_str(body, "email")
    full_name = common.req_str(body, "full_name")
    state_code = common.req_str(body, "state_code")
    common.validate_state_code(state_code)
    has_insurance = common.opt_bool(body, "has_insurance", False)

    # email globally unique
    for existing in db.members.values():
        if existing["email"] == email:
            raise errors.validation("A member with this email already exists.")

    rec = {
        "email": email,
        "full_name": full_name,
        "state_code": state_code,
        "has_insurance": has_insurance,
        "lifetime_savings_cents": 0,
        "active_gold_membership_id": None,
    }
    db.stamp_create(rec, common_fields=True)
    db.members[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    middleware.require_auth(["Member", "PlatformAdmin"])
    rec = common.must_exist(db.members, mid, "Member")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/members", methods=["GET"])
def list_members():
    middleware.require_auth(["PlatformAdmin"])
    limit, offset = common.parse_pagination()
    email = request.args.get("email")
    items = list(db.members.values())
    if email is not None:
        items = [m for m in items if m["email"] == email]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)

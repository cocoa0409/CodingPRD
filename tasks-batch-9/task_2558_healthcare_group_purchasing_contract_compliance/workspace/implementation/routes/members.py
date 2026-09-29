"""Members and their item masters (PRD section 3.3)."""

from flask import Blueprint

from db import db, ordered
from enums import MEMBER_STATUSES, WATCHLIST_STATUSES
from errors import ApiError
from middleware import (
    ALL_ROLES,
    COMPLIANCE_ANALYST,
    CONTRACT_MANAGER,
    MEMBER_MATERIALS_MANAGER,
    authenticate,
    require_member_scope,
)
from response import list_response, object_response
from services.lookup import get_member
from validation import (
    bad,
    body_json,
    field_int,
    field_list,
    field_string,
    paginate,
    pagination,
    query_enum,
    query_string,
)

members_bp = Blueprint("members", __name__)


def parse_item_master(body, key="item_master"):
    raw = field_list(body, key, min_len=1, max_len=50)
    entries = []
    seen = []
    for index, entry in enumerate(raw):
        label = "%s[%d]" % (key, index)
        if not isinstance(entry, dict):
            raise bad("Field '%s' must be an object." % label)
        member_item_number = field_string(
            {label + ".member_item_number": entry.get("member_item_number")},
            label + ".member_item_number",
            1,
            None,
        )
        description = field_string(
            {label + ".description": entry.get("description")},
            label + ".description",
            1,
            None,
        )
        units_per_uom = field_int(
            {label + ".units_per_uom": entry.get("units_per_uom")},
            label + ".units_per_uom",
            minimum=1,
        )
        if member_item_number in seen:
            raise bad("member_item_number must be unique within item_master.")
        seen.append(member_item_number)
        entries.append(
            {
                "member_item_number": member_item_number,
                "description": description,
                "units_per_uom": units_per_uom,
            }
        )
    return entries


@members_bp.route("/gpo/members", methods=["POST"])
def create_member():
    authenticate((CONTRACT_MANAGER,))
    body = body_json()
    member_code = field_string(body, "member_code", 1, 40)
    name = field_string(body, "name", 1, 120)
    aggregation_group_code = field_string(body, "aggregation_group_code", 1, 40)
    item_master = parse_item_master(body)
    for existing in db.members.values():
        if existing["member_code"] == member_code:
            raise bad("member_code must be globally unique.")

    row = db.new_row()
    row.update(
        {
            "member_code": member_code,
            "name": name,
            "aggregation_group_code": aggregation_group_code,
            "item_master": item_master,
            "status": "ACTIVE",
            "watchlist_status": "NONE",
            "fee_credit_balance_cents": 0,
        }
    )
    db.members[row["id"]] = row
    return object_response(row, 201)


@members_bp.route("/gpo/members/<member_id>", methods=["GET"])
def read_member(member_id):
    authenticate(ALL_ROLES)
    return object_response(get_member(member_id))


@members_bp.route("/gpo/members", methods=["GET"])
def list_members():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = query_enum("status", MEMBER_STATUSES)
    watchlist_status = query_enum("watchlist_status", WATCHLIST_STATUSES)
    aggregation_group_code = query_string("aggregation_group_code")
    rows = [
        row
        for row in ordered(db.members.values())
        if (status is None or row["status"] == status)
        and (watchlist_status is None or row["watchlist_status"] == watchlist_status)
        and (
            aggregation_group_code is None
            or row["aggregation_group_code"] == aggregation_group_code
        )
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@members_bp.route("/gpo/members/<member_id>/item-master", methods=["PATCH"])
def replace_item_master(member_id):
    acting_user_id, _ = authenticate((MEMBER_MATERIALS_MANAGER,))
    require_member_scope(acting_user_id, member_id)
    member = get_member(member_id)
    body = body_json()
    member["item_master"] = parse_item_master(body)
    db.touch(member)
    return object_response(member)


@members_bp.route("/gpo/members/<member_id>/suspend", methods=["POST"])
def suspend_member(member_id):
    authenticate((COMPLIANCE_ANALYST,))
    member = get_member(member_id)
    body = body_json()
    field_string(body, "reason", 0, None, required=False, default=None)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", "Only an ACTIVE member can be suspended.")
    member["status"] = "SUSPENDED"
    db.touch(member)
    return object_response(member)

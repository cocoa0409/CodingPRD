"""The capital committee roster (PRD section 3.7)."""

from flask import Blueprint

import lookups
import serializers
from db import db, new_row, touch
from middleware import CAPITAL_PLANNER, guard
from response import created_response, object_response
from validation import (body, bool_field, enum_field, int_field, pagination,
                        q_bool, q_str, raw_ref, str_field)

bp = Blueprint("members", __name__)

SEATS = ("CHAIR", "FINANCE", "CLINICAL", "FACILITIES", "SAFETY_OFFICER")


@bp.route("/capital/committee-members", methods=["POST"])
@guard(CAPITAL_PLANNER)
def create_member():
    data = body()
    for key, resolver in (("facility_id", lookups.facility),
                          ("department_id", lookups.department)):
        ref = raw_ref(data, key)
        if ref is not None:
            resolver(ref)

    full_name = str_field(data, "full_name", 1, 120)
    seat = enum_field(data, "seat", SEATS)
    voting_weight = int_field(data, "voting_weight", 1, 5)
    facility_id = str_field(data, "facility_id", 1, None, required=False)
    department_id = str_field(data, "department_id", 1, None, required=False)

    row = new_row({
        "full_name": full_name,
        "seat": seat,
        "facility_id": facility_id,
        "department_id": department_id,
        "voting_weight": voting_weight,
        "active": True,
    })
    db.members[row["id"]] = row
    return created_response(serializers.member(row))


@bp.route("/capital/committee-members/<member_id>", methods=["PATCH"])
@guard(CAPITAL_PLANNER)
def patch_member(member_id):
    member = lookups.member(member_id)
    data = body()
    for key, resolver in (("facility_id", lookups.facility),
                          ("department_id", lookups.department)):
        ref = raw_ref(data, key)
        if ref is not None:
            resolver(ref)

    full_name = str_field(data, "full_name", 1, 120, required=False)
    seat = enum_field(data, "seat", SEATS, required=False)
    voting_weight = int_field(data, "voting_weight", 1, 5, required=False)
    facility_id = str_field(data, "facility_id", 1, None, required=False)
    department_id = str_field(data, "department_id", 1, None, required=False)
    active = bool_field(data, "active", required=False)

    if full_name is not None:
        member["full_name"] = full_name
    if seat is not None:
        member["seat"] = seat
    if voting_weight is not None:
        member["voting_weight"] = voting_weight
    if facility_id is not None:
        member["facility_id"] = facility_id
    if department_id is not None:
        member["department_id"] = department_id
    if active is not None:
        member["active"] = active
    touch(member)
    return object_response(serializers.member(member))


@bp.route("/capital/committee-members/<member_id>", methods=["GET"])
@guard()
def get_member(member_id):
    return object_response(serializers.member(lookups.member(member_id)))


@bp.route("/capital/committee-members", methods=["GET"])
@guard()
def list_members():
    limit, offset = pagination()
    rows = lookups.filtered(db.members.values(), [
        ("facility_id", q_str("facility_id")),
        ("department_id", q_str("department_id")),
        ("seat", q_str("seat")),
        ("active", q_bool("active")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.member)


@bp.route("/capital/committee-members/<member_id>/votes", methods=["GET"])
@guard()
def list_member_votes(member_id):
    member = lookups.member(member_id)
    limit, offset = pagination()
    rows = lookups.filtered(
        [v for v in db.votes.values() if v["member_id"] == member["id"]],
        [("superseded", q_bool("superseded")), ("vote", q_str("vote"))])
    return lookups.paginate(rows, limit, offset, serializers.vote)

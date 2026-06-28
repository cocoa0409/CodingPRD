"""Orientation scheduling, completion (waiver gate), and cancellation."""
from flask import Blueprint, request

import errors
import serializers
from clock import clock
from db import db, stamp_create, touch
from helpers import (
    get_json_body,
    require_fields,
    parse_datetime,
    parse_pagination,
    paginate,
)
from middleware import authenticate, require_role
from response import success

bp = Blueprint("orientations", __name__)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    # Half-open [start, end) overlap test.
    return a_start < b_end and b_start < a_end


@bp.route("/orientations", methods=["POST"])
def create_orientation():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    body = get_json_body()
    require_fields(body, ["member_id", "attendant_id", "start_utc", "end_utc"])
    # Existence (left-to-right) before well-formedness on timing relationship.
    member = db.members.get(body["member_id"])
    if member is None:
        raise errors.not_found("Member not found.")
    attendant = db.attendants.get(body["attendant_id"])
    if attendant is None:
        raise errors.not_found("Attendant not found.")

    start = parse_datetime(body["start_utc"], "start_utc")
    end = parse_datetime(body["end_utc"], "end_utc")
    if end <= start:
        raise errors.invalid_request("end_utc must be after start_utc.")

    waiver_version = body.get("waiver_version", 1)
    if not isinstance(waiver_version, int) or isinstance(waiver_version, bool):
        raise errors.invalid_request("waiver_version must be an integer.")
    if waiver_version < 1:
        raise errors.invalid_request("waiver_version must be >= 1.")

    # Attendant interval non-overlap against other SCHEDULED orientations.
    for o in db.orientations.values():
        if o["attendant_id"] == body["attendant_id"] and o["status"] == "SCHEDULED":
            if _intervals_overlap(start, end, o["start_utc"], o["end_utc"]):
                raise errors.attendant_time_conflict()

    record = {
        "member_id": body["member_id"],
        "attendant_id": body["attendant_id"],
        "start_utc": start,
        "end_utc": end,
        "status": "SCHEDULED",
        "waiver_version": waiver_version,
    }
    stamp_create(record)
    db.orientations[record["id"]] = record
    return success(serializers.orientation_out(record), status=201)


@bp.route("/orientations/<oid>", methods=["GET"])
def get_orientation(oid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    o = db.orientations.get(oid)
    if o is None:
        raise errors.not_found("Orientation not found.")
    if principal.is_member() and o["member_id"] != principal.user_id:
        raise errors.forbidden()
    return success(serializers.orientation_out(o), status=200)


@bp.route("/orientations", methods=["GET"])
def list_orientations():
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    limit, offset = parse_pagination()
    records = list(db.orientations.values())
    member_id = request.args.get("member_id")
    attendant_id = request.args.get("attendant_id")
    if member_id is not None:
        records = [r for r in records if r["member_id"] == member_id]
    if attendant_id is not None:
        records = [r for r in records if r["attendant_id"] == attendant_id]
    if principal.is_member():
        records = [r for r in records if r["member_id"] == principal.user_id]
    page, meta = paginate(records, limit, offset)
    return success([serializers.orientation_out(r) for r in page], status=200, pagination=meta)


@bp.route("/orientations/<oid>/complete", methods=["POST"])
def complete_orientation(oid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk"})
    o = db.orientations.get(oid)
    if o is None:
        raise errors.not_found("Orientation not found.")
    if o["status"] != "SCHEDULED":
        raise errors.invalid_state("Orientation is not SCHEDULED.")
    now = clock.now()
    if now < o["start_utc"]:
        # PRD §3.2: a premature completion is "an illegal transition".
        raise errors.invalid_state("Orientation cannot complete before start_utc.")
    o["status"] = "COMPLETED"
    touch(o)
    member = db.members.get(o["member_id"])
    if member is not None:
        member["orientation_completed"] = True
        member["waiver_signed_version"] = o["waiver_version"]
        touch(member)
    return success(serializers.orientation_out(o), status=200)


@bp.route("/orientations/<oid>/cancel", methods=["POST"])
def cancel_orientation(oid):
    principal = authenticate()
    require_role(principal, {"Admin", "FrontDesk", "Member"})
    o = db.orientations.get(oid)
    if o is None:
        raise errors.not_found("Orientation not found.")
    if principal.is_member() and o["member_id"] != principal.user_id:
        raise errors.forbidden()
    if o["status"] != "SCHEDULED":
        raise errors.invalid_state("Orientation is not SCHEDULED.")
    o["status"] = "CANCELLED"
    touch(o)
    return success(serializers.orientation_out(o), status=200)

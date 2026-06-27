"""AvailabilityHold endpoints and lifecycle (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, lock
from errors import ApiError
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import (
    mint_common,
    touch,
    public,
    get_json_body,
    require_str,
    require_enum,
    lookup,
    paginate,
)
from timeutil import require_dt, to_date

bp = Blueprint("availability_holds", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}
HOLD_KINDS = {"FIRST_REFUSAL", "CONFIRMED_BOOKING"}


@bp.route("/availability-holds", methods=["POST"])
def create_hold():
    _, role = get_identity()
    require_role(role, {"Agent"})
    body = get_json_body()
    talent_id = require_str(body, "talent_id")
    require_str(body, "start_date")
    require_str(body, "end_date")
    hold_kind = require_enum(body, "hold_kind", HOLD_KINDS)
    start_date = require_dt(body["start_date"])
    end_date = require_dt(body["end_date"])
    with lock:
        lookup("Talent", talent_id)

        # Same-kind overlap (priority 10): half-open [start, end+1day).
        _check_same_kind_overlap(talent_id, hold_kind, start_date, end_date)

        # Date ordering (priority 11): end on or after start.
        if to_date(end_date) < to_date(start_date):
            raise ApiError("ERR_INVALID_DATE_RANGE")

        record = mint_common({
            "talent_id": talent_id,
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "hold_kind": hold_kind,
            "status": "ACTIVE",
        })
        db.availability_holds[record["id"]] = record

        # Side effect: a CONFIRMED_BOOKING hold bumps overlapping ACTIVE
        # FIRST_REFUSAL holds on the same talent to CONFLICTED.
        if hold_kind == "CONFIRMED_BOOKING":
            for h in db.availability_holds.values():
                if h["id"] == record["id"]:
                    continue
                if h["talent_id"] != talent_id:
                    continue
                if h["status"] != "ACTIVE" or h["hold_kind"] != "FIRST_REFUSAL":
                    continue
                if _half_open_overlap(
                    start_date, end_date,
                    require_dt(h["start_date"]), require_dt(h["end_date"]),
                ):
                    h["status"] = "CONFLICTED"
                    touch(h)
        return object_response(public(record), status=201)


def _half_open_overlap(a_start, a_end, b_start, b_end):
    """Overlap on half-open [start, end+1day) by calendar date."""
    a_s = to_date(a_start)
    a_e_excl = to_date(a_end) + timedelta(days=1)
    b_s = to_date(b_start)
    b_e_excl = to_date(b_end) + timedelta(days=1)
    return a_s < b_e_excl and b_s < a_e_excl


def _check_same_kind_overlap(talent_id, hold_kind, start_date, end_date):
    for h in db.availability_holds.values():
        if h["talent_id"] != talent_id:
            continue
        if h["status"] != "ACTIVE" or h["hold_kind"] != hold_kind:
            continue
        if _half_open_overlap(
            start_date, end_date,
            require_dt(h["start_date"]), require_dt(h["end_date"]),
        ):
            raise ApiError("ERR_HOLD_OVERLAP")


@bp.route("/availability-holds", methods=["GET"])
def list_holds():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        items = list(db.availability_holds.values())
        for field in ("talent_id", "status"):
            val = request.args.get(field)
            if val is not None:
                items = [h for h in items if h[field] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/availability-holds/<hold_id>", methods=["GET"])
def get_hold(hold_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        record = lookup("AvailabilityHold", hold_id)
        return object_response(public(record), status=200)


@bp.route("/availability-holds/<hold_id>/release", methods=["POST"])
def release_hold(hold_id):
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        hold = lookup("AvailabilityHold", hold_id)
        if hold["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        hold["status"] = "RELEASED"
        touch(hold)
        return object_response(public(hold), status=200)

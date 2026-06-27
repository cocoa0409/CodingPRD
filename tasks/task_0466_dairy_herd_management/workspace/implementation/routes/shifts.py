"""MilkingShift routes (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request, g

import db
import errors
import serializers
from errors import err
from middleware import require_roles
from records import make_record, touch
from response import object_response, array_response
from domain import paginate, sorted_by_creation
from util import parse_datetime
import validators as V

bp = Blueprint("shifts", __name__)

ALL_ROLES = ("HerdManager", "ParlorTech", "Veterinarian", "CoopSettlementAgent", "Auditor")


@bp.route("/herds/milking-shifts", methods=["POST"])
@require_roles("ParlorTech", "HerdManager")
def create_shift():
    body = V.require_json_object()
    parlor_id = V.require_fk(body, "parlor_id")
    start_at = V.require_datetime(body, "start_at")
    end_at = V.require_datetime(body, "end_at")
    cows_milked = V.require_int(body, "cows_milked", minimum=0)
    # field shape: end_at strictly after start_at (priority 6)
    if end_at <= start_at:
        raise err(errors.ERR_INVALID_REQUEST, "end_at must be strictly after start_at")
    # existence
    parlor = V.get_or_404("parlor", parlor_id)
    with db.lock:
        # temporal overlap (priority 10): half-open interval + turnaround buffer.
        # A new shift's start_at must be >= prior.end_at + turnaround_minutes for
        # every LOGGED shift on this parlor; and symmetrically the existing shift
        # must start at/after the new shift's end + buffer. We reject if the
        # buffered intervals overlap.
        buffer = timedelta(minutes=parlor["turnaround_minutes"])
        for other in db.milking_shifts.values():
            if other["parlor_id"] != parlor_id:
                continue
            if other["status"] != "LOGGED":
                continue
            o_start = parse_datetime(other["start_at"])
            o_end = parse_datetime(other["end_at"])
            # Allowed iff new starts at/after other.end + buffer, OR
            # other starts at/after new.end + buffer.
            ok = (start_at >= o_end + buffer) or (o_start >= end_at + buffer)
            if not ok:
                raise err(errors.ERR_PARLOR_SHIFT_OVERLAP,
                          "Shift overlaps an existing LOGGED shift on this parlor")
        rec = make_record({
            "parlor_id": parlor_id,
            "herd_id": parlor["herd_id"],
            "operator_user_id": g.user_id,
            "start_at": body["start_at"],
            "end_at": body["end_at"],
            "cows_milked": cows_milked,
            "status": "LOGGED",
        })
        db.milking_shifts[rec["id"]] = rec
        return object_response(serializers.milking_shift_out(rec), 201)


@bp.route("/herds/milking-shifts", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_shifts():
    items = list(db.milking_shifts.values())
    parlor_id = request.args.get("parlor_id")
    herd_id = request.args.get("herd_id")
    if parlor_id is not None:
        items = [r for r in items if r["parlor_id"] == parlor_id]
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.milking_shift_out(r) for r in page], limit, offset, total)


@bp.route("/herds/milking-shifts/<shift_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_shift(shift_id):
    rec = V.get_or_404("shift", shift_id)
    return object_response(serializers.milking_shift_out(rec), 200)


@bp.route("/herds/milking-shifts/<shift_id>/void", methods=["POST"])
@require_roles("ParlorTech", "HerdManager")
def void_shift(shift_id):
    rec = V.get_or_404("shift", shift_id)
    with db.lock:
        if rec["status"] != "LOGGED":
            raise err(errors.ERR_SHIFT_NOT_LOGGED, "Shift is not LOGGED")
        rec["status"] = "VOIDED"
        touch(rec)
        return object_response(serializers.milking_shift_out(rec), 200)

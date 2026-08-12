"""Panel memberships, compensation summary, availability windows."""

from flask import Blueprint, request

import db
import services
import util
from errors import (
    ApiError,
    ERR_DUPLICATE_MEMBERSHIP,
    ERR_MEMBERSHIP_NOT_SUSPENDED,
    ERR_MEMBERSHIP_SUSPENDED,
    ERR_NOT_MEMBERSHIP_OWNER,
    ERR_SPECIALIST_INACTIVE,
    ERR_AVAILABILITY_WINDOW_OVERLAP,
    ERR_WINDOW_INVALID_RANGE,
    ERR_WINDOW_NOT_ACTIVE,
)
from middleware import require_roles, ANY_ROLE
from response import ok, ok_list
from util import serialize, serialize_list

bp = Blueprint("panel", __name__)


# --- panel memberships ---------------------------------------------------------

@bp.route("/econsult/panel-memberships", methods=["POST"])
def create_membership():
    require_roles("ProgramCoordinator")
    data = util.json_body()
    specialist_id = util.req_str(data, "specialist_id")
    track_id = util.req_str(data, "specialty_track_id")
    is_accepting = util.opt_bool(data, "is_accepting", default=True)

    specialist = services.get_specialist(specialist_id)
    services.get_track(track_id)

    for existing in db.store["panel_memberships"].values():
        if (existing["specialist_id"] == specialist_id
                and existing["specialty_track_id"] == track_id):
            raise ApiError(
                ERR_DUPLICATE_MEMBERSHIP, 409,
                "A panel membership already exists for this specialist and track",
            )

    if specialist["status"] != "ACTIVE":
        raise ApiError(ERR_SPECIALIST_INACTIVE, 409, "Specialist is not ACTIVE")

    rec = services.base_record()
    rec.update({
        "specialist_id": specialist_id,
        "specialty_track_id": track_id,
        "standing": "GOOD_STANDING",
        "quality_score_bps": 8500,
        "reviews_count": 0,
        "reviews_score_sum": 0,
        "responded_count": 0,
        "on_time_count": 0,
        "rebuke_count": 0,
        "expired_count": 0,
        "open_consult_count": 0,
        "provisional_balance_cents": 0,
        "posted_balance_cents": 0,
        "is_accepting": is_accepting,
        "unique_membership": "%s:%s" % (specialist_id, track_id),
    })
    db.store["panel_memberships"][rec["id"]] = rec
    return ok(serialize("panel_membership", rec), 201)


@bp.route("/econsult/panel-memberships", methods=["GET"])
def list_memberships():
    require_roles(*ANY_ROLE)
    specialist_id = request.args.get("specialist_id")
    track_id = request.args.get("specialty_track_id")
    standing = request.args.get("standing")
    records = list(db.store["panel_memberships"].values())
    if specialist_id is not None:
        records = [m for m in records if m["specialist_id"] == specialist_id]
    if track_id is not None:
        records = [m for m in records if m["specialty_track_id"] == track_id]
    if standing is not None:
        records = [m for m in records if m["standing"] == standing]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("panel_membership", page), total, limit, offset)


@bp.route("/econsult/panel-memberships/<rid>", methods=["GET"])
def get_membership(rid):
    require_roles(*ANY_ROLE)
    return ok(serialize("panel_membership", services.get_membership(rid)), 200)


@bp.route("/econsult/panel-memberships/<rid>/reinstate", methods=["POST"])
def reinstate_membership(rid):
    require_roles("ProgramCoordinator")
    membership = services.get_membership(rid)
    if membership["standing"] != "SUSPENDED":
        raise ApiError(
            ERR_MEMBERSHIP_NOT_SUSPENDED, 409,
            "Reinstate requires standing SUSPENDED",
        )
    membership["standing"] = "PROBATION"
    membership["is_accepting"] = True
    services.touch(membership)
    return ok(serialize("panel_membership", membership), 200)


@bp.route("/econsult/panel-memberships/<rid>/compensation-summary", methods=["GET"])
def compensation_summary(rid):
    require_roles("ProgramCoordinator", "Specialist", "BillingClerk")
    membership = services.get_membership(rid)
    reversed_total = sum(
        entry["amount_cents"]
        for entry in db.store["compensation_entries"].values()
        if entry["membership_id"] == membership["id"] and entry["posture"] == "REVERSED"
    )
    return ok({
        "provisional_balance_cents": membership["provisional_balance_cents"],
        "posted_balance_cents": membership["posted_balance_cents"],
        "reversed_total_cents": reversed_total,
        "open_consult_count": membership["open_consult_count"],
    }, 200)


@bp.route("/econsult/panel-memberships/<rid>/availability-windows", methods=["GET"])
def list_membership_windows(rid):
    require_roles(*ANY_ROLE)
    membership = services.get_membership(rid)
    status = request.args.get("status")
    records = [
        w for w in db.store["availability_windows"].values()
        if w["membership_id"] == membership["id"]
    ]
    if status is not None:
        records = [w for w in records if w["status"] == status]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("availability_window", page), total, limit, offset)


# --- availability windows ------------------------------------------------------

@bp.route("/econsult/specialist-availability-windows", methods=["POST"])
def create_window():
    uid, _role = require_roles("Specialist")
    data = util.json_body()
    membership_id = util.req_str(data, "membership_id")
    window_start = util.req_datetime(data, "window_start")
    window_end = util.req_datetime(data, "window_end")

    membership = services.get_membership(membership_id)
    if membership["specialist_id"] != uid:
        raise ApiError(
            ERR_NOT_MEMBERSHIP_OWNER, 403,
            "Caller is not the specialist of the window's membership",
        )
    if membership["standing"] == "SUSPENDED":
        raise ApiError(
            ERR_MEMBERSHIP_SUSPENDED, 403,
            "A SUSPENDED membership cannot create availability windows",
        )
    if window_end <= window_start:
        raise ApiError(
            ERR_WINDOW_INVALID_RANGE, 422,
            "window_end must be strictly later than window_start",
        )
    for existing in db.store["availability_windows"].values():
        if existing["membership_id"] != membership["id"]:
            continue
        if existing["status"] != "ACTIVE":
            continue
        # Half-open overlap: adjacent windows do not conflict.
        if window_start < existing["window_end"] and existing["window_start"] < window_end:
            raise ApiError(
                ERR_AVAILABILITY_WINDOW_OVERLAP, 409,
                "Window overlaps an ACTIVE window of the same membership",
            )

    rec = services.base_record()
    rec.update({
        "membership_id": membership["id"],
        "window_start": window_start,
        "window_end": window_end,
        "status": "ACTIVE",
    })
    db.store["availability_windows"][rec["id"]] = rec
    return ok(serialize("availability_window", rec), 201)


@bp.route("/econsult/specialist-availability-windows/<rid>/cancel", methods=["POST"])
def cancel_window(rid):
    uid, _role = require_roles("Specialist")
    window = services.get_window(rid)
    membership = services.get_membership(window["membership_id"])
    if membership["specialist_id"] != uid:
        raise ApiError(
            ERR_NOT_MEMBERSHIP_OWNER, 403,
            "Caller is not the specialist of the window's membership",
        )
    if window["status"] != "ACTIVE":
        raise ApiError(ERR_WINDOW_NOT_ACTIVE, 409, "Window is not ACTIVE")
    window["status"] = "CANCELLED"
    services.touch(window)
    return ok(serialize("availability_window", window), 200)

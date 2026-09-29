"""Ensembles, instrumentation sections and the chair rotation."""

from flask import Blueprint, request

import calc
import services as svc
from auth import ALL_ROLES, endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import db
from validate import Body, bad, pagination

bp = Blueprint("ensembles", __name__)

TIERS = ("SYMPHONY", "PHILHARMONIC", "CONCERT_ORCHESTRA")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


# ------------------------------------------------------------------ ensembles
@bp.route("/ensembles", methods=["POST"])
@endpoint("ArtisticDirector")
def create_ensemble():
    body = Body()
    season_id = body.string("season_id", required=True)
    name = body.string("name", required=True, min_len=1, max_len=200)
    tier = body.enum("tier", TIERS, required=True)
    min_total = body.integer("min_total_size", required=True, minimum=1)
    max_total = body.integer("max_total_size", required=True, minimum=1)
    weekday = body.enum("rehearsal_weekday", WEEKDAYS, required=True)
    if max_total < min_total:
        bad("max_total_size must be at least min_total_size.")

    season = svc.season_or_404(season_id)

    row = svc.new_row()
    row.update({
        "season_id": season["id"],
        "name": name,
        "tier": tier,
        "min_total_size": min_total,
        "max_total_size": max_total,
        "rehearsal_weekday": weekday,
        "roster_state": "FORMING",
    })
    db.ensembles[row["id"]] = row
    svc.touch(season)
    return ok(svc.ensemble_json(row), 201)


@bp.route("/ensembles", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_ensembles():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.ensembles.values())), request.args,
                             ["season_id", "roster_state", "tier"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.ensemble_json(r) for r in page], limit, offset, len(rows))


@bp.route("/ensembles/<ensemble_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_ensemble(ensemble_id):
    return ok(svc.ensemble_json(svc.ensemble_or_404(ensemble_id)))


# -------------------------------------------------------------- section quotas
@bp.route("/section-quotas", methods=["POST"])
@endpoint("ArtisticDirector")
def create_quota():
    body = Body()
    ensemble_id = body.string("ensemble_id", required=True)
    instrument = body.enum("instrument", calc.INSTRUMENTS, required=True)
    min_count = body.integer("min_count", required=True, minimum=0)
    target_count = body.integer("target_count", required=True, minimum=1)
    max_count = body.integer("max_count", required=True, minimum=1)
    principal_required = body.boolean("principal_required", default=True)
    rotation_policy = body.enum("rotation_policy", ("ROTATING", "FIXED"),
                                required=False, default="ROTATING")
    if target_count < min_count:
        bad("target_count must be at least min_count.")
    if max_count < target_count:
        bad("max_count must be at least target_count.")

    ensemble = svc.ensemble_or_404(ensemble_id)
    if svc.quota_for(ensemble["id"], instrument) is not None:
        raise ApiError("ERR_DUPLICATE_SECTION_QUOTA",
                       "This ensemble already seats %s." % instrument)

    row = svc.new_row()
    row.update({
        "ensemble_id": ensemble["id"],
        "instrument": instrument,
        "min_count": min_count,
        "target_count": target_count,
        "max_count": max_count,
        "principal_required": principal_required,
        "rotation_policy": rotation_policy,
        "balance_state": "UNDERFILLED" if min_count > 0 else "BALANCED",
        "rotation_cycle_index": 0,
    })
    db.section_quotas[row["id"]] = row
    svc.touch(ensemble)
    return ok(svc.quota_json(row), 201)


@bp.route("/section-quotas", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_quotas():
    limit, offset = pagination()
    rows = svc.apply_filters(svc.ordered(list(db.section_quotas.values())),
                             request.args,
                             ["ensemble_id", "instrument", "balance_state"])
    page = svc.paginate(rows, limit, offset)
    return ok_list([svc.quota_json(r) for r in page], limit, offset, len(rows))


@bp.route("/section-quotas/<quota_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_quota(quota_id):
    return ok(svc.quota_json(svc.quota_or_404(quota_id)))


@bp.route("/section-quotas/<quota_id>/rotate-chairs", methods=["POST"])
@endpoint("ArtisticDirector")
def rotate_chairs(quota_id):
    quota = svc.quota_or_404(quota_id)
    body = Body()
    expected = body.integer("expected_ensemble_version", required=True)
    ensemble = svc.ensemble_of_quota(quota)
    if expected != ensemble["version"]:
        raise ApiError("ERR_STALE_ENSEMBLE_VERSION",
                       "The ensemble has moved on since your last read.")
    if ensemble["roster_state"] != "SEATED":
        raise ApiError("ERR_ENSEMBLE_NOT_SEATED",
                       "Only a SEATED ensemble may rotate chairs.")

    seats = svc.active_seats_of_quota(quota["id"])
    if quota["rotation_policy"] != "ROTATING" or len(seats) < 2:
        raise ApiError("ERR_ROTATION_NOT_PERMITTED",
                       "This section may not rotate chairs.")

    size = len(seats)
    for seat in seats:
        successor = svc.new_row()
        chair_number = size if seat["chair_number"] == 1 else seat["chair_number"] - 1
        successor.update({
            "placement_id": seat["placement_id"],
            "section_quota_id": seat["section_quota_id"],
            "member_id": seat["member_id"],
            "predecessor_assignment_id": seat["id"],
            "chair_number": chair_number,
            "is_principal": bool(chair_number == 1 and quota["principal_required"]),
            "ranking_score": seat["ranking_score"],
            "rotation_cycle_index": seat["rotation_cycle_index"] + 1,
            "status": "ACTIVE",
        })
        db.seat_assignments[successor["id"]] = successor
        seat["status"] = "ROTATED_OUT"
        svc.touch(seat)

    quota["rotation_cycle_index"] += 1
    svc.touch(quota)
    svc.touch(ensemble)
    return ok(svc.quota_json(quota))

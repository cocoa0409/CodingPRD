from flask import Blueprint, request

import db
from db import new_entity, touch
from errors import (
    ApiError,
    ERR_CORRECTION_KIND_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_RACE_VERSION,
)
from middleware import endpoint
from response import ok
from serializers import ser_correction
from services import recompute as engine
from util import parse_dt
from validators import get_body, get_or_404, list_page, v_enum, v_int, v_str

bp = Blueprint("corrections", __name__)

_READERS = ("RaceDirector", "RaceOfficial")
_KINDS = ("EXCLUDE_READ", "REINSTATE_READ", "ADJUST_READ_TIME")
_ADJUDICATE_STATES = ("PROVISIONAL_PUBLISHED", "FINALIZED", "AMENDMENT_OPEN")


def _check_kind_actionable(kind, read):
    if kind == "EXCLUDE_READ" and read["status"] != "SCORED":
        raise ApiError(
            ERR_CORRECTION_KIND_MISMATCH,
            409,
            "EXCLUDE_READ requires the read to be SCORED",
        )
    if kind == "REINSTATE_READ" and read["status"] != "EXCLUDED":
        raise ApiError(
            ERR_CORRECTION_KIND_MISMATCH,
            409,
            "REINSTATE_READ requires the read to be EXCLUDED",
        )
    if kind == "ADJUST_READ_TIME" and read["status"] != "SCORED":
        raise ApiError(
            ERR_CORRECTION_KIND_MISMATCH,
            409,
            "ADJUST_READ_TIME requires the read to be SCORED",
        )


def _conditional_timestamp(body, kind):
    ct_raw = body.get("corrected_timestamp")
    if kind == "ADJUST_READ_TIME":
        corrected = parse_dt(ct_raw)
        if corrected is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "corrected_timestamp is required for ADJUST_READ_TIME",
            )
        return corrected
    if ct_raw is not None:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "corrected_timestamp is only allowed for ADJUST_READ_TIME",
        )
    return None


@bp.post("/race-timing/corrections")
@endpoint("RaceOfficial")
def create_correction():
    body = get_body(("race_id", "timing_read_id", "kind", "reason"))
    race = get_or_404(db.races, body.get("race_id"))
    read = get_or_404(db.timing_reads, body.get("timing_read_id"))
    kind = v_enum(body, "kind", _KINDS)
    reason = v_str(body, "reason")
    # coherence: the read must belong to the race
    point = db.timing_points.get(read["timing_point_id"])
    if point is None or point["race_id"] != race["id"]:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "timing_read_id does not belong to the race"
        )
    corrected = _conditional_timestamp(body, kind)
    _check_kind_actionable(kind, read)

    corr = new_entity()
    corr.update(
        {
            "race_id": race["id"],
            "timing_read_id": read["id"],
            "kind": kind,
            "corrected_timestamp": corrected,
            "reason": reason,
            "protest_id": None,
            "status": "FILED",
            "adjudicated_by_user_id": None,
        }
    )
    db.corrections[corr["id"]] = corr
    return ok(ser_correction(corr), 201)


@bp.get("/race-timing/corrections/<correction_id>")
@endpoint(*_READERS)
def get_correction(correction_id):
    return ok(ser_correction(get_or_404(db.corrections, correction_id)))


@bp.get("/race-timing/corrections")
@endpoint(*_READERS)
def list_corrections():
    items = list(db.corrections.values())
    for param in ("race_id", "timing_read_id", "status", "protest_id"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    return list_page(items, ser_correction)


@bp.post("/race-timing/corrections/<correction_id>/adjudicate")
@endpoint("RaceOfficial")
def adjudicate_correction(correction_id):
    corr = get_or_404(db.corrections, correction_id)
    body = get_body(("decision", "expected_race_version"))
    decision = v_enum(body, "decision", ("APPROVED", "REJECTED"))
    expected = v_int(body, "expected_race_version")
    race = db.races.get(corr["race_id"])
    # state first
    if (
        corr["status"] != "FILED"
        or race is None
        or race["status"] not in _ADJUDICATE_STATES
    ):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Correction must be FILED and the race in PROVISIONAL_PUBLISHED, FINALIZED or AMENDMENT_OPEN",
        )
    # then concurrency
    if expected != race["version"]:
        raise ApiError(
            ERR_STALE_RACE_VERSION,
            412,
            "expected_race_version does not match the current race version",
        )
    # then kind-actionability
    read = db.timing_reads.get(corr["timing_read_id"])
    if read is None:
        raise ApiError(
            ERR_CORRECTION_KIND_MISMATCH, 409, "The target read no longer exists"
        )
    _check_kind_actionable(corr["kind"], read)

    corr["adjudicated_by_user_id"] = request.user_id
    if decision == "REJECTED":
        corr["status"] = "REJECTED"
        touch(corr)
        touch(race)  # rejection still advances the race version by one
        return ok(ser_correction(corr))

    corr["status"] = "APPROVED"
    touch(corr)
    engine.apply_correction_cascade(corr, race)
    return ok(ser_correction(corr))

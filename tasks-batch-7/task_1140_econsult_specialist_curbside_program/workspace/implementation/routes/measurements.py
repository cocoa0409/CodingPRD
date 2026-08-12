"""Avoided-visit measurements: create (computes both variants), finalize, list, get."""

from flask import Blueprint, request

import db
import services
import util
from errors import (
    ApiError,
    ERR_MEASUREMENT_ALREADY_EXISTS,
    ERR_MEASUREMENT_ALREADY_FINALIZED,
)
from middleware import require_roles, ANY_ROLE
from response import ok, ok_list
from util import serialize, serialize_list

bp = Blueprint("measurements", __name__)


@bp.route("/econsult/avoided-visit-measurements", methods=["POST"])
def create_measurement():
    require_roles("ProgramCoordinator")
    data = util.json_body()
    track_id = util.req_str(data, "specialty_track_id")
    period_key = util.req_period_key(data, "period_key")

    services.get_track(track_id)
    for existing in db.store["avoided_visit_measurements"].values():
        if (existing["specialty_track_id"] == track_id
                and existing["period_key"] == period_key):
            raise ApiError(
                ERR_MEASUREMENT_ALREADY_EXISTS, 409,
                "A measurement already exists for this track and period",
            )

    counts = services.measurement_counts(track_id, period_key)
    rec = services.base_record()
    rec.update({
        "specialty_track_id": track_id,
        "period_key": period_key,
        "responded_count": counts["responded_count"],
        "conversions_count": counts["conversions_count"],
        "avoided_attributed_count": counts["avoided_attributed_count"],
        "avoided_conservative_count": counts["avoided_conservative_count"],
        "status": "OPEN",
    })
    db.store["avoided_visit_measurements"][rec["id"]] = rec
    return ok(serialize("avoided_visit_measurement", rec), 201)


@bp.route("/econsult/avoided-visit-measurements/<rid>/finalize", methods=["POST"])
def finalize_measurement(rid):
    require_roles("ProgramCoordinator")
    measurement = services.get_measurement(rid)
    if measurement["status"] != "OPEN":
        raise ApiError(
            ERR_MEASUREMENT_ALREADY_FINALIZED, 409,
            "Measurement is already FINALIZED",
        )
    counts = services.measurement_counts(
        measurement["specialty_track_id"], measurement["period_key"]
    )
    measurement["responded_count"] = counts["responded_count"]
    measurement["conversions_count"] = counts["conversions_count"]
    measurement["avoided_attributed_count"] = counts["avoided_attributed_count"]
    measurement["avoided_conservative_count"] = counts["avoided_conservative_count"]
    measurement["status"] = "FINALIZED"
    services.touch(measurement)
    return ok(serialize("avoided_visit_measurement", measurement), 200)


@bp.route("/econsult/avoided-visit-measurements", methods=["GET"])
def list_measurements():
    require_roles(*ANY_ROLE)
    track_id = request.args.get("specialty_track_id")
    period_key = request.args.get("period_key")
    records = list(db.store["avoided_visit_measurements"].values())
    if track_id is not None:
        records = [m for m in records if m["specialty_track_id"] == track_id]
    if period_key is not None:
        records = [m for m in records if m["period_key"] == period_key]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("avoided_visit_measurement", page), total, limit, offset)


@bp.route("/econsult/avoided-visit-measurements/<rid>", methods=["GET"])
def get_measurement(rid):
    require_roles(*ANY_ROLE)
    return ok(serialize("avoided_visit_measurement", services.get_measurement(rid)), 200)

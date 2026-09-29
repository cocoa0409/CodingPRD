"""PRD 3.1 -- jurisdictions and the loading criteria that govern them."""

from flask import Blueprint, request

import constants as C
import serializers as S
import validation as V
from errors import ApiError
from middleware import ANY, roles_required
from response import object_response, paginated
from services import domain
from store import db, new_row, ordered, touch

bp = Blueprint("jurisdictions", __name__)

CODE_PATTERN = r"[A-Z0-9\-]+"


def _criteria_fields(data):
    return {
        "exposure_category": V.get_enum(data, "exposure_category", C.EXPOSURE_CATEGORIES),
        "design_wind_speed_mph": V.get_number(data, "design_wind_speed_mph", exclusive_minimum=0),
        "ground_snow_load_psf": V.get_number(data, "ground_snow_load_psf", minimum=0),
        "seismic_design_category": V.get_enum(
            data, "seismic_design_category", C.SEISMIC_CATEGORIES
        ),
    }


@bp.route("/jurisdictions", methods=["POST"])
@roles_required("PlatformAdmin")
def create_jurisdiction():
    data = V.body()
    code = V.get_string(data, "code", min_len=3, max_len=32, pattern=CODE_PATTERN)
    name = V.get_string(data, "name", min_len=1)
    state_code = V.get_string(data, "state_code", min_len=2, max_len=2, pattern=r"[A-Z]{2}")
    territory_code = V.get_string(data, "territory_code", min_len=3, max_len=16)
    freight_zone = V.get_int(data, "freight_zone", minimum=1, maximum=5)
    max_builders = V.get_int(
        data,
        "max_authorized_builders",
        required=False,
        default=C.DEFAULT_MAX_AUTHORIZED_BUILDERS,
        minimum=1,
    )
    criteria = _criteria_fields(data)

    # Band 14: uniqueness.
    for existing in db.jurisdictions.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE")

    fields = {
        "code": code,
        "name": name,
        "state_code": state_code,
        "territory_code": territory_code,
        "freight_zone": freight_zone,
        "max_authorized_builders": max_builders,
        "criteria_revision": 1,
    }
    fields.update(criteria)
    row = new_row(fields)
    db.jurisdictions[row["id"]] = row
    return object_response(S.jurisdiction_out(row), 201)


@bp.route("/jurisdictions/<jurisdiction_id>", methods=["GET"])
@roles_required(ANY)
def read_jurisdiction(jurisdiction_id):
    row = domain.get_jurisdiction(jurisdiction_id)
    return object_response(S.jurisdiction_out(row))


@bp.route("/jurisdictions", methods=["GET"])
@roles_required(ANY)
def list_jurisdictions():
    territory_code = request.args.get("territory_code")
    state_code = request.args.get("state_code")

    def predicate(row):
        if territory_code is not None and row["territory_code"] != territory_code:
            return False
        if state_code is not None and row["state_code"] != state_code:
            return False
        return True

    return paginated(ordered(db.jurisdictions, predicate), S.jurisdiction_out)


@bp.route("/jurisdictions/<jurisdiction_id>/loading-criteria", methods=["POST"])
@roles_required("PlatformAdmin")
def publish_loading_criteria(jurisdiction_id):
    data = V.body()
    criteria = _criteria_fields(data)
    row = domain.get_jurisdiction(jurisdiction_id)

    row.update(criteria)
    row["criteria_revision"] = row["criteria_revision"] + 1
    touch(row)

    # PRD 2.10 chain one -- five hops inside this request.
    domain.cascade_criteria_revision(row)
    return object_response(S.jurisdiction_out(row))

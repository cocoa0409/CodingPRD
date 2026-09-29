"""Grantee registration, reads, the baseline lock and the governance summary."""

from flask import Blueprint, request

import db
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authorize
from response import object_response
from routes.common import listing, require
from services import health_center as hc_svc
from validation import Field, pagination, parse_body

bp = Blueprint("health_centers", __name__)

CREATE_FIELDS = [
    Field("legal_name", "string", required=True),
    Field("grant_number", "string", required=True),
    Field("pps_base_rate_cents", "integer", required=True, exclusive_min=0),
    Field("medicare_upper_limit_cents", "integer", required=True, exclusive_min=0),
    Field("nominal_fee_cap_cents", "integer", exclusive_min=0),
]


@bp.post("/health-centers")
def create_health_center():
    authorize("PlatformAdmin")
    body = parse_body(CREATE_FIELDS)

    for row in db.db.health_centers.values():
        if row["grant_number"] == body["grant_number"]:
            raise ApiError("ERR_DUPLICATE_KEY")

    row = db.base_row()
    row.update(
        {
            "legal_name": body["legal_name"],
            "grant_number": body["grant_number"],
            "pps_base_rate_cents": body["pps_base_rate_cents"],
            "medicare_upper_limit_cents": body["medicare_upper_limit_cents"],
            "nominal_fee_cap_cents": body.get("nominal_fee_cap_cents", 2500),
            "scope_baseline_locked": False,
        }
    )
    db.db.health_centers[row["id"]] = row
    return object_response(serializers.health_center(row), 201)


@bp.get("/health-centers/<hc_id>")
def read_health_center(hc_id):
    authorize(*ALL_ROLES)
    return object_response(serializers.health_center(require("health_centers", hc_id)))


@bp.get("/health-centers")
def list_health_centers():
    authorize(*ALL_ROLES)
    limit, offset = pagination()

    wanted_operational = request.args.get("operational_status")
    wanted_governance = request.args.get("governance_posture")

    def predicate(row):
        derived = hc_svc.derived(row)
        if wanted_operational is not None and derived["operational_status"] != wanted_operational:
            return False
        if wanted_governance is not None and derived["governance_posture"] != wanted_governance:
            return False
        return True

    return listing(
        db.all_rows("health_centers"),
        serializers.health_center,
        limit,
        offset,
        specs=[("grant_number", "grant_number", "string")],
        predicate=predicate,
    )


@bp.post("/health-centers/<hc_id>/lock-scope-baseline")
def lock_scope_baseline(hc_id):
    authorize("PlatformAdmin")
    parse_body([])
    hc = require("health_centers", hc_id)
    if hc["scope_baseline_locked"]:
        raise ApiError("ERR_SCOPE_BASELINE_LOCKED")
    hc["scope_baseline_locked"] = True
    db.touch(hc)
    return object_response(serializers.health_center(hc))


@bp.get("/health-centers/<hc_id>/governance-summary")
def governance_summary(hc_id):
    authorize("PlatformAdmin", "ComplianceOfficer", "BoardChair", "ProjectOfficer")
    hc = require("health_centers", hc_id)
    gov = hc_svc.governance(hc_id)
    return object_response(
        {
            "health_center_id": hc_id,
            "seated_board_count": gov["seated_board_count"],
            "qualified_patient_seat_count": gov["qualified_patient_seat_count"],
            "non_patient_seat_count": gov["non_patient_seat_count"],
            "healthcare_industry_seat_count": gov["healthcare_industry_seat_count"],
            "patient_seat_pct": gov["patient_seat_pct"],
            "governance_posture": gov["governance_posture"],
            "version": hc["version"],
        }
    )

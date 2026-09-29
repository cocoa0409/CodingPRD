"""Carrier enrollments: OCC-guarded creation, supersession and carrier decisions."""
from flask import Blueprint

import clock
import response
import validate
from errors import ApiError
from middleware import require, own_winery
from routes import common
from services import derive, serialize
from store import db, base_row, touch, ordered

bp = Blueprint("carriers", __name__)

ENROLLMENT_STATUSES = ("PENDING", "APPROVED", "SUSPENDED")
DECISIONS = ("APPROVED", "SUSPENDED")
LIVE = ("PENDING", "APPROVED")


@bp.route("/dtc/carrier-enrollments", methods=["POST"])
def create_enrollment():
    uid, role = require("WineryOperator", "ComplianceOfficer")
    own_winery(uid, role, validate.raw_body().get("winery_id"))
    b = validate.body()
    winery_id = validate.field_str(b, "winery_id")
    program_id = validate.field_str(b, "carrier_program_id")
    account = validate.field_str(b, "account_number")
    expected = validate.field_int(b, "expected_winery_version")

    winery = common.winery(winery_id)
    common.carrier_program(program_id)

    if expected != winery["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_winery_version %s does not match the winery's current version %s."
                       % (expected, winery["version"]))

    superseded = False
    for prior in ordered(list(db.carrier_enrollments.values())):
        if prior["winery_id"] != winery_id:
            continue
        if prior["carrier_program_id"] != program_id:
            continue
        if prior["status"] not in LIVE:
            continue
        prior["status"] = "SUSPENDED"
        touch(prior)
        superseded = True

    row = base_row()
    row.update({
        "winery_id": winery_id,
        "carrier_program_id": program_id,
        "account_number": account,
        "status": "PENDING",
        "approved_at": None,
        "decided_by_user_id": None,
    })
    db.carrier_enrollments[row["id"]] = row
    if superseded:
        derive.bump_winery(winery)
    return response.obj(serialize.carrier_enrollment(row), 201)


@bp.route("/dtc/carrier-enrollments/<eid>", methods=["GET"])
def read_enrollment(eid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "CarrierAgent")
    enrollment = common.carrier_enrollment(eid)
    own_winery(uid, role, enrollment["winery_id"])
    return response.obj(serialize.carrier_enrollment(enrollment))


@bp.route("/dtc/carrier-enrollments", methods=["GET"])
def list_enrollments():
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "CarrierAgent")
    winery_id = common.scope_winery(common.arg("winery_id"), uid, role)
    program_id = common.arg("carrier_program_id")
    status = validate.query_enum("status", ENROLLMENT_STATUSES)
    rows = [e for e in db.carrier_enrollments.values()
            if (winery_id is None or e["winery_id"] == winery_id)
            and (program_id is None or e["carrier_program_id"] == program_id)
            and (status is None or e["status"] == status)]
    return common.listing(rows, serialize.carrier_enrollment)


@bp.route("/dtc/carrier-enrollments/<eid>/decision", methods=["POST"])
def decide_enrollment(eid):
    uid, _role = require("CarrierAgent")
    enrollment = common.carrier_enrollment(eid)
    b = validate.body()
    decision = validate.field_enum(b, "decision", DECISIONS)
    validate.field_str(b, "note", required=False, allow_empty=True)

    current = enrollment["status"]
    if decision == current:
        raise ApiError("ERR_ENROLLMENT_ALREADY_DECIDED",
                       "The enrollment is already %s." % current)
    if decision == "APPROVED":
        if current not in ("PENDING", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Approval is only reachable from PENDING or SUSPENDED.")
        enrollment["approved_at"] = clock.now_iso()
    else:
        if current != "APPROVED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Suspension is only reachable from APPROVED.")
    enrollment["status"] = decision
    enrollment["decided_by_user_id"] = uid
    touch(enrollment)
    return response.obj(serialize.carrier_enrollment(enrollment))

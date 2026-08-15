"""TestBay endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp

bp = Blueprint("test_bays", __name__)

VALID_BAY_STATUSES = {"ACTIVE", "OUT_OF_SERVICE"}


@bp.route("/genset-packaging/test-bays", methods=["POST"])
def create_test_bay():
    mw.require_roles("PlatformAdmin")
    body = mw.get_json_body()

    record = {
        "bay_code": mw.require_string(body, "bay_code"),
        "max_kw": mw.require_int(body, "max_kw", minimum=1),
        "status": mw.optional_enum(body, "status", VALID_BAY_STATUSES, "ACTIVE"),
    }
    db.stamp_new(record)
    db.test_bays[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/test-bays/<testBayId>", methods=["GET"])
def get_test_bay(testBayId):
    mw.authenticate()
    record = db.test_bays.get(testBayId)
    if record is None:
        raise errors.not_found("Test bay not found")
    return resp.success_object(record)

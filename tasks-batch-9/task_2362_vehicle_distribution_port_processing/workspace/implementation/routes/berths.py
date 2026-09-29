"""Berths — immutable facility records (PRD §2.4, §3.1)."""
from flask import Blueprint

import db
import validation as v
from errors import fail
from middleware import OPS_ROLES, ROLE_PLANNER, authenticate
from response import list_response, object_response
from services import serializers as ser

bp = Blueprint("berths", __name__)


@bp.route("/vpc/berths", methods=["POST"])
def create_berth():
    authenticate([ROLE_PLANNER])
    body = v.body()

    # Band 4: body foreign key.
    center = None
    if v.present(body, "processing_center_id"):
        center = db.centers.get(body["processing_center_id"])
        if center is None:
            fail("ERR_REFERENCE_NOT_FOUND", "processing_center_id does not resolve")

    v.req_str(body, "processing_center_id")
    berth_code = v.req_str(body, "berth_code")
    buffer_minutes = v.opt_int(body, "turnaround_buffer_minutes", default=120, minimum=0)

    if any(
        b["processing_center_id"] == center["id"] and b["berth_code"] == berth_code
        for b in db.berths.values()
    ):
        fail("ERR_DUPLICATE_KEY", "berth_code %s already exists at this center" % berth_code)

    record = db.base_record(versioned=False)
    record.update(
        {
            "processing_center_id": center["id"],
            "berth_code": berth_code,
            "turnaround_buffer_minutes": buffer_minutes,
        }
    )
    db.berths[record["id"]] = record
    return object_response(ser.berth(record), 201)


@bp.route("/vpc/berths/<berth_id>", methods=["GET"])
def read_berth(berth_id):
    authenticate(OPS_ROLES)
    berth = db.must_get("berths", berth_id)
    return object_response(ser.berth(berth))


@bp.route("/vpc/berths", methods=["GET"])
def list_berths():
    authenticate(OPS_ROLES)
    center_id = v.query_filter("processing_center_id")
    berth_code = v.query_filter("berth_code")
    records = db.ordered(db.berths)
    if center_id is not None:
        records = [b for b in records if b["processing_center_id"] == center_id]
    if berth_code is not None:
        records = [b for b in records if b["berth_code"] == berth_code]
    items, limit, offset, total = v.paginate(records, ser.berth)
    return list_response(items, limit, offset, total)

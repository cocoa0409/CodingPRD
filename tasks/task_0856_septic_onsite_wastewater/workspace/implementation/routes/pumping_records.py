"""Pumping records -- immutable field evidence that refreshes the schedule."""
from flask import Blueprint

import derive
import lookup
import response
import serialize
import store
import validate as v
from auth import authenticate
from errors import ApiError
from store import ordered, touch
from util import now

bp = Blueprint("pumping_records", __name__)

PUMPER_CLASSES = ("PUMPER", "DUAL")
PUMPING_READ_ROLES = ["Applicant", "Pumper", "EnvironmentalHealthSpecialist",
                      "HealthOfficer", "RecordsClerk"]


@bp.post("/pumping-records")
def file_pumping_record():
    actor = authenticate(["Pumper"])
    body = v.body()
    permit = lookup.operating_permit(v.req_fk(body, "operating_permit_id"))
    pumped_on = v.req_dt(body, "pumped_on")
    gallons_removed = v.req_int(body, "gallons_removed", minimum=1)
    sludge_depth_in = v.req_num(body, "sludge_depth_in", minimum=0)
    scum_depth_in = v.req_num(body, "scum_depth_in", minimum=0)
    if pumped_on > now():
        raise v.bad("pumped_on may not lie in the future of the logical clock.")

    contractor = store.contractors.get(actor.user_id)
    if contractor is None or contractor["license_class"] not in PUMPER_CLASSES:
        raise ApiError("ERR_LICENSE_CLASS_MISMATCH")

    record = store.new_record(with_version=False)
    record.update({
        "operating_permit_id": permit["id"],
        "contractor_id": actor.user_id,
        "pumped_on": pumped_on,
        "gallons_removed": gallons_removed,
        "sludge_depth_in": sludge_depth_in,
        "scum_depth_in": scum_depth_in,
        "accepted": True,
    })
    store.pumping_records[record["id"]] = record

    permit["last_pumped_on"] = pumped_on
    derive.recompute_schedule_fields(permit)
    touch(permit)

    parcel = store.parcels.get(permit["parcel_id"])
    if parcel is not None:
        derive.recompute_parcel(parcel)

    return response.ok(serialize.pumping_record(record), 201)


@bp.get("/pumping-records/<record_id>")
def read_pumping_record(record_id):
    authenticate(PUMPING_READ_ROLES)
    record = lookup.pumping_record(record_id)
    return response.ok(serialize.pumping_record(record))


@bp.get("/pumping-records")
def list_pumping_records():
    authenticate(PUMPING_READ_ROLES)
    limit, offset = v.pagination()
    rows = ordered(store.pumping_records.values())
    for field in ("operating_permit_id", "contractor_id"):
        value = v.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("pumping_record", page),
                            limit, offset, total)

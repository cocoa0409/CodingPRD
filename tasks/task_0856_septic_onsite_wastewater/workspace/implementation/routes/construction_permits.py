"""Construction permits: issue, read, list and the compensating void."""
from flask import Blueprint

import calc
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

bp = Blueprint("construction_permits", __name__)

PERMIT_READ_ROLES = ["Applicant", "DesignProfessional", "Installer",
                     "EnvironmentalHealthSpecialist", "HealthOfficer",
                     "RecordsClerk"]
INSTALLER_CLASSES = ("INSTALLER", "DUAL")
BARRED_SETBACKS = ("VARIANCE_REQUIRED", "VARIANCE_DENIED")


@bp.post("/construction-permits")
def issue_construction_permit():
    authenticate(["HealthOfficer"])
    body = v.body()
    design = lookup.system_design(v.req_fk(body, "system_design_id"))
    contractor = lookup.contractor(v.req_fk(body, "contractor_id"))
    valid_from = v.req_dt(body, "valid_from")
    valid_until = v.req_dt(body, "valid_until")
    if valid_until <= valid_from:
        raise v.bad("valid_until must be strictly after valid_from.")

    if contractor["license_class"] not in INSTALLER_CLASSES:
        raise ApiError("ERR_LICENSE_CLASS_MISMATCH")

    if design["status"] != "APPROVED":
        raise ApiError("ERR_DESIGN_NOT_APPROVED")
    if design["setback_status"] in BARRED_SETBACKS:
        raise ApiError("ERR_SETBACK_VIOLATION")

    evaluation = store.site_evaluations[design["site_evaluation_id"]]
    if now() > evaluation["valid_until"]:
        raise ApiError("ERR_SITE_EVALUATION_EXPIRED")

    parcel = store.parcels[evaluation["parcel_id"]]
    for existing in derive.construction_permits_of_parcel(parcel["id"]):
        if existing["status"] not in calc.PARCEL_OCCUPYING_PERMIT_STATES:
            continue
        if calc.parcel_window_conflict(valid_from, valid_until,
                                       existing["valid_from"],
                                       existing["valid_until"]):
            raise ApiError("ERR_PERMIT_WINDOW_CONFLICT")

    flow = design["design_flow_gpd"] or 0
    if parcel["permitted_design_flow_gpd"] + flow > parcel["max_design_flow_gpd"]:
        raise ApiError("ERR_DESIGN_FLOW_EXCEEDS_PARCEL_CAP")

    sequence = store.county_permit_sequence.get(parcel["county_code"], 0) + 1
    store.county_permit_sequence[parcel["county_code"]] = sequence
    fee_cents = calc.construction_permit_fee(flow, design["system_type"],
                                             design["setback_status"])

    permit = store.new_record()
    permit.update({
        "system_design_id": design["id"],
        "parcel_id": parcel["id"],
        "contractor_id": contractor["id"],
        "permit_number": "%s-CP-%06d" % (parcel["county_code"], sequence),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "design_flow_gpd": flow,
        "fee_cents": fee_cents,
        "status": "ISSUED",
        "cover_inspection_passed_at": None,
    })
    store.construction_permits[permit["id"]] = permit

    design["status"] = "PERMITTED"
    touch(design)

    parcel["fees_assessed_cents"] += fee_cents
    derive.recompute_parcel(parcel)

    return response.ok(serialize.construction_permit(permit), 201)


@bp.get("/construction-permits/<permit_id>")
def read_construction_permit(permit_id):
    authenticate(PERMIT_READ_ROLES)
    permit = lookup.construction_permit(permit_id)
    return response.ok(serialize.construction_permit(permit))


@bp.get("/construction-permits")
def list_construction_permits():
    authenticate(PERMIT_READ_ROLES)
    limit, offset = v.pagination()
    rows = ordered(store.construction_permits.values())
    for field in ("parcel_id", "system_design_id", "contractor_id", "status"):
        value = v.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("construction_permit", page),
                            limit, offset, total)


@bp.post("/construction-permits/<permit_id>/void")
def void_construction_permit(permit_id):
    authenticate(["HealthOfficer"])
    permit = lookup.construction_permit(permit_id)
    body = v.body()
    v.req_str(body, "reason", non_empty=False)

    if permit["status"] not in ("ISSUED", "UNDER_CONSTRUCTION"):
        raise ApiError("ERR_INVALID_STATE")
    for inspection in derive.inspections_of_permit(permit["id"]):
        if inspection["status"] == "PASSED":
            raise ApiError("ERR_INVALID_STATE")

    permit["status"] = "VOIDED"
    touch(permit)

    design = store.system_designs.get(permit["system_design_id"])
    if design is not None and design["status"] == "PERMITTED":
        design["status"] = "APPROVED"
        touch(design)

    derive.release_permit(permit, cancel_failed=True)

    parcel = store.parcels.get(permit["parcel_id"])
    if parcel is not None:
        parcel["fees_credited_cents"] += permit["fee_cents"]
        derive.recompute_parcel(parcel)

    return response.ok(serialize.construction_permit(permit))

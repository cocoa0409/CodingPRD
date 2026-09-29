"""Financial assurance instrument endpoints (PRD 3.8)."""

from decimal import Decimal as D

from flask import Blueprint

import db
import enums
import middleware as mw
import response
from errors import ApiError
from services import calc, derive, lookup, serialize

bp = Blueprint("instruments", __name__)

ADMIN = "ProgramAdmin"
DEV = "ProjectDeveloper"
REVIEWER = "RegulatoryReviewer"

DEALLOCATABLE_PROJECT_STATUSES = ("DRAFT", "SITE_CHARACTERIZATION", "PERMITTING")


@bp.post("/ccs/financial-instruments")
@mw.require(DEV)
def post_instrument():
    payload = mw.body()
    project_id = mw.req_str(payload, "project_id")
    instrument_type = mw.req_enum(payload, "instrument_type", enums.INSTRUMENT_TYPE)
    face_amount = mw.req_num(payload, "face_amount_usd", gt=0)

    project = lookup.project(project_id)
    derive.require_not_frozen(project)

    row = db.base_fields()
    row.update(
        {
            "project_id": project["id"],
            "instrument_type": instrument_type,
            "face_amount_usd": calc.q2(face_amount),
            "allocated_ca_usd": D("0.00"),
            "allocated_plugging_usd": D("0.00"),
            "allocated_pisc_usd": D("0.00"),
            "allocated_emergency_usd": D("0.00"),
            "unallocated_usd": calc.q2(face_amount),
            "drawn_usd": D("0.00"),
            "status": "POSTED",
            "released_at": None,
        }
    )
    db.financial_instruments[row["id"]] = row
    return response.object_response(serialize.instrument(row), 201)


@bp.get("/ccs/financial-instruments/<instrument_id>")
@mw.require(ADMIN, DEV, REVIEWER)
def get_instrument(instrument_id):
    return response.object_response(serialize.instrument(lookup.instrument(instrument_id)))


@bp.post("/ccs/financial-instruments/<instrument_id>/allocate")
@mw.require(DEV)
def allocate(instrument_id):
    payload = mw.body()
    expected_instrument_version = mw.req_int(payload, "expected_instrument_version")

    instrument = lookup.instrument(instrument_id)
    project = db.projects.get(instrument["project_id"])
    derive.require_not_frozen(project)

    if instrument["status"] not in ("POSTED", "ALLOCATED"):
        raise ApiError(
            "ERR_INVALID_INSTRUMENT_STATE",
            "allocation is only admissible from POSTED or ALLOCATED",
        )

    if expected_instrument_version != instrument["version"]:
        raise ApiError(
            "ERR_STALE_INSTRUMENT_VERSION", "expected_instrument_version does not match"
        )

    if D(project["required_financial_assurance_usd"]) <= 0:
        raise ApiError(
            "ERR_ALLOCATION_EXCEEDS_FACE_AMOUNT",
            "the project's required financial assurance is not greater than zero",
        )

    buckets = derive.assurance_buckets(project)
    allocated, unallocated = calc.waterfall(instrument["face_amount_usd"], buckets)
    instrument["allocated_ca_usd"] = allocated["CORRECTIVE_ACTION"]
    instrument["allocated_plugging_usd"] = allocated["PLUGGING"]
    instrument["allocated_pisc_usd"] = allocated["PISC"]
    instrument["allocated_emergency_usd"] = allocated["EMERGENCY"]
    instrument["unallocated_usd"] = unallocated
    instrument["status"] = "ALLOCATED"
    db.touch(instrument)

    derive.recompute_allocated_assurance(project)
    db.touch(project)

    return response.object_response(serialize.instrument(instrument))


@bp.post("/ccs/financial-instruments/<instrument_id>/deallocate")
@mw.require(DEV)
def deallocate(instrument_id):
    payload = mw.body()
    mw.req_str(payload, "deallocation_reason")

    instrument = lookup.instrument(instrument_id)
    project = db.projects.get(instrument["project_id"])
    derive.require_not_frozen(project)

    if instrument["status"] != "ALLOCATED":
        raise ApiError(
            "ERR_INVALID_INSTRUMENT_STATE", "deallocation is only admissible from ALLOCATED"
        )
    if project["status"] not in DEALLOCATABLE_PROJECT_STATUSES:
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            "assurance cannot be pulled back once injection has been authorized",
        )

    instrument["allocated_ca_usd"] = D("0.00")
    instrument["allocated_plugging_usd"] = D("0.00")
    instrument["allocated_pisc_usd"] = D("0.00")
    instrument["allocated_emergency_usd"] = D("0.00")
    # PRD 3.8: deallocation restores the full face amount; only an ALLOCATED
    # instrument may deallocate and an ALLOCATED instrument's drawn_usd is 0.
    instrument["unallocated_usd"] = calc.q2(instrument["face_amount_usd"])
    instrument["status"] = "POSTED"
    db.touch(instrument)

    derive.recompute_allocated_assurance(project)
    db.touch(project)

    return response.object_response(serialize.instrument(instrument))

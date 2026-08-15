"""Inspection endpoints (PRD 3.5): scheduling and result submission drive the
production-entry accept/rework loop.

Cascade bookkeeping (BidItem.accepted_quantity, WorkPackage.rework_open_count,
DRAFT invoice hold_reason) is derived from the ledger on read, so a PASS/FAIL
verdict takes effect everywhere by simply flipping the entry's status.
"""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_INSPECTION_ALREADY_OPEN,
    ERR_CROSS_CONTRACT_REFERENCE,
)
from middleware import authorized
from response import success_object
from routes.helpers import serialize, list_response, get_one
from routes.work_packages import require_contract_active
from services.core import (
    new_record, touch, work_package_of_assignment, contract_of_work_package,
)
from validate import (
    get_body, req_str, req_enum, require_path_resource, require_body_ref,
)

bp = Blueprint("inspections", __name__)


@bp.post("/work-packages/<work_package_id>/inspections")
def create_inspection(work_package_id):
    authorized(["UTILITY_INSPECTOR"])
    body = get_body()
    production_entry_id = req_str(body, "production_entry_id")
    standard_code = req_str(body, "standard_code")
    wp = require_path_resource("work_packages", work_package_id)
    entry = require_body_ref("production_entries", production_entry_id,
                             "production_entry_id")
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    # The entry under inspection must stand in SUBMITTED.
    if entry["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    "inspections are scheduled against SUBMITTED production entries")
    # At most one SCHEDULED inspection per production entry.
    for i in db["inspections"].values():
        if (i["production_entry_id"] == entry["id"]
                and i["status"] == "SCHEDULED"):
            raise_error(ERR_INSPECTION_ALREADY_OPEN,
                        "a SCHEDULED inspection already exists for this production entry")
    # Cross-contract integrity: the entry must belong to this work package.
    assignment = db["assignments"].get(entry["assignment_id"])
    if assignment is None or assignment["work_package_id"] != wp["id"]:
        raise_error(ERR_CROSS_CONTRACT_REFERENCE,
                    "production entry does not belong to this work package")
    rec = new_record("inspections", {
        "work_package_id": wp["id"],
        "production_entry_id": entry["id"],
        "standard_code": standard_code,
        "result": None,
        "status": "SCHEDULED",
    })
    return success_object(serialize("inspections", rec), status=201)


@bp.post("/inspections/<inspection_id>/submit")
def submit_inspection(inspection_id):
    authorized(["UTILITY_INSPECTOR"])
    body = get_body()
    result = req_enum(body, "result", {"PASS", "FAIL"})
    inspection = require_path_resource("inspections", inspection_id)
    wp = require_path_resource("work_packages", inspection["work_package_id"])
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if inspection["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    "only a SCHEDULED inspection can be submitted")
    entry = require_path_resource("production_entries",
                                  inspection["production_entry_id"])
    if entry["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    "the production entry under inspection is no longer SUBMITTED")

    inspection["result"] = result
    if result == "PASS":
        inspection["status"] = "PASSED"
        # ProductionEntry SUBMITTED -> ACCEPTED: accepted_quantity rises and
        # DRAFT invoices recompute (both derived on read).
        entry["status"] = "ACCEPTED"
    else:
        inspection["status"] = "FAILED"
        # SUBMITTED -> REWORK_REQUIRED: rework_open_count rises; DRAFT invoice
        # hold_reason becomes OPEN_REWORK while the count is above zero.
        entry["status"] = "REWORK_REQUIRED"
    touch(entry)
    touch(inspection)
    return success_object(serialize("inspections", inspection))


@bp.get("/inspections")
def list_inspections():
    filters = {
        "work_package_id": request.args.get("work_package_id"),
        "production_entry_id": request.args.get("production_entry_id"),
        "result": request.args.get("result"),
    }
    return list_response("inspections", filters)


@bp.get("/inspections/<inspection_id>")
def get_inspection(inspection_id):
    return get_one("inspections", inspection_id)

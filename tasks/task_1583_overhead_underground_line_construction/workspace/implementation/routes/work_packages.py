"""Work package endpoints: create (under contract), get/list, transition
(PRD 3.2; WorkPackage state machine)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_CONTRACT_SUSPENDED,
    ERR_CONTRACT_NOT_ACTIVE, ERR_OPEN_REWORK, ERR_OPEN_MATERIAL_ISSUES,
)
from middleware import authorized
from response import success_object
from routes.helpers import serialize, list_response, get_one
from services.core import (
    new_record, touch, rework_open_count, open_material_issue_count,
)
from validate import (
    get_body, req_str, opt_bool, req_enum, require_path_resource,
)

bp = Blueprint("work_packages", __name__)

WP_TERMINAL = ("COMPLETED", "CANCELLED")


def require_contract_active(contract):
    """Priority 6 contract-activity gate (PRD 2.10)."""
    if contract["status"] == "SUSPENDED":
        raise_error(ERR_CONTRACT_SUSPENDED,
                    "contract is SUSPENDED; operational writes are blocked")
    if contract["status"] != "ACTIVE":
        raise_error(ERR_CONTRACT_NOT_ACTIVE,
                    "contract is not ACTIVE; operation requires an ACTIVE contract")


def create_work_package_impl(contract_id):
    authorized(["CONTRACTOR_PM"])
    body = get_body()
    name = req_str(body, "name")
    location = req_str(body, "location")
    requires_outage = opt_bool(body, "requires_outage", False)
    contract = require_path_resource("contracts", contract_id)
    require_contract_active(contract)
    rec = new_record("work_packages", {
        "contract_id": contract["id"],
        "name": name,
        "location": location,
        "requires_outage": requires_outage,
        "status": "PLANNED",
    })
    return success_object(serialize("work_packages", rec), status=201)


@bp.get("/work-packages")
def list_work_packages():
    filters = {
        "contract_id": request.args.get("contract_id"),
        "status": request.args.get("status"),
    }
    return list_response("work_packages", filters)


@bp.get("/work-packages/<work_package_id>")
def get_work_package(work_package_id):
    return get_one("work_packages", work_package_id)


@bp.post("/work-packages/<work_package_id>/transition")
def transition_work_package(work_package_id):
    authorized(["CONTRACTOR_PM"])
    body = get_body()
    to = req_enum(body, "to",
                  {"MOBILIZED", "IN_PROGRESS", "PUNCH", "COMPLETED", "CANCELLED"})
    wp = require_path_resource("work_packages", work_package_id)
    contract = require_path_resource("contracts", wp["contract_id"])
    require_contract_active(contract)
    cur = wp["status"]

    if cur == "PLANNED" and to == "MOBILIZED":
        pass
    elif cur == "MOBILIZED" and to == "IN_PROGRESS":
        has_assignment = any(
            a["work_package_id"] == wp["id"] and a["status"] in ("PLANNED", "ACTIVE")
            for a in db["assignments"].values())
        if not has_assignment:
            raise_error(ERR_INVALID_STATE,
                        "IN_PROGRESS requires at least one PLANNED or ACTIVE assignment")
    elif cur == "IN_PROGRESS" and to == "PUNCH":
        pass
    elif cur == "PUNCH" and to == "COMPLETED":
        if rework_open_count(wp["id"]) != 0:
            raise_error(ERR_OPEN_REWORK,
                        "work package has production entries in REWORK_REQUIRED")
        if open_material_issue_count(wp["id"]) != 0:
            raise_error(ERR_OPEN_MATERIAL_ISSUES,
                        "work package has OPEN material issues")
    elif to == "CANCELLED" and cur in ("PLANNED", "MOBILIZED", "IN_PROGRESS"):
        _cancel_cascade(wp)
    else:
        raise_error(ERR_INVALID_STATE,
                    f"cannot transition work package from {cur} to {to}")

    wp["status"] = to
    touch(wp)
    return success_object(serialize("work_packages", wp))


def _cancel_cascade(wp):
    """Cancellation: assignments PLANNED/ACTIVE -> CANCELLED; DRAFT/REJECTED
    invoices -> VOID (frozen unit pool released)."""
    for a in db["assignments"].values():
        if a["work_package_id"] == wp["id"] and a["status"] in ("PLANNED", "ACTIVE"):
            a["status"] = "CANCELLED"
            touch(a)
    for inv in db["invoices"].values():
        if inv["work_package_id"] == wp["id"] and inv["status"] in ("DRAFT", "REJECTED"):
            inv["status"] = "VOID"
            touch(inv)

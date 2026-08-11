"""Contractor endpoints (§3.4)."""
from flask import Blueprint

from db import store
from errors import invalid_request
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from util import bump, new_entity, serialize
from validate import get_or_404, json_body, req_str

bp = Blueprint("contractors", __name__)

TERMINAL = ("SUSPENDED",)


@bp.route("/rollout/contractors", methods=["POST"], strict_slashes=False)
@authed(["ProcurementLead"])
def create_contractor():
    body = json_body()
    legal_name = req_str(body, "legal_name")
    license_no = req_str(body, "license_no")
    license_state = req_str(body, "license_state")
    if any(c["license_no"] == license_no for c in store.contractors.values()):
        invalid_request("license_no '%s' already exists" % license_no)
    contractor = new_entity(store)
    contractor.update({
        "legal_name": legal_name,
        "license_no": license_no,
        "license_state": license_state,
        "status": "PREQUALIFIED",
    })
    store.contractors[contractor["id"]] = contractor
    return ok(serialize(contractor), status=201)


@bp.route("/rollout/contractors", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_contractors():
    return list_response(store.contractors, [("status", "status", "str")])


@bp.route("/rollout/contractors/<contractorId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_contractor(contractorId):
    return ok(serialize(get_or_404(store.contractors, contractorId, "contractor")))


@bp.route("/rollout/contractors/<contractorId>/suspend", methods=["POST"], strict_slashes=False)
@authed(["ProcurementLead"])
def suspend_contractor(contractorId):
    contractor = get_or_404(store.contractors, contractorId, "contractor")
    require_state(contractor, ("PREQUALIFIED",), TERMINAL)
    contractor["status"] = "SUSPENDED"
    bump(contractor)
    return ok(serialize(contractor))

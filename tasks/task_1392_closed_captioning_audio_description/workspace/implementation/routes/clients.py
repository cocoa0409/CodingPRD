"""Client endpoints (PRD §3.1)."""
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, stamp_new, touch
from errors import invalid_transition, not_found, validation
from respond import list_response, ok_object
from services.pricing import TURNAROUND_TIERS
from util import opt_enum, req_enum, req_str

bp = Blueprint("clients", __name__)

COMPLIANCE_STANDARDS = {"FCC_BROADCAST", "SECTION_508", "INTERNAL"}


def get_client(client_id):
    c = DB.clients.get(client_id)
    if c is None:
        raise not_found("Client not found")
    return c


@bp.post("/caption-ad/clients")
@guarded({"OperationsManager"})
def create_client(_user_id, _role):
    data = body()
    name = req_str(data, "name")
    compliance_standard = req_enum(data, "compliance_standard", COMPLIANCE_STANDARDS)
    default_tier = opt_enum(data, "default_turnaround_tier", TURNAROUND_TIERS, default="STANDARD")
    rec = {
        "name": name,
        "compliance_standard": compliance_standard,
        "default_turnaround_tier": default_tier,
        "client_status": "ACTIVE",
        "ytd_completed_minutes": 0,
    }
    stamp_new(rec)
    DB.clients[rec["id"]] = rec
    return ok_object(serialize.client(rec), status=201)


@bp.get("/caption-ad/clients")
@guarded(set(ALL_ROLES))
def list_clients(_user_id, _role):
    records = list(DB.clients.values())
    status = request.args.get("client_status")
    if status is not None:
        records = [r for r in records if r["client_status"] == status]
    return list_response(records, serialize.client)


@bp.get("/caption-ad/clients/<clientId>")
@guarded(set(ALL_ROLES))
def get_one_client(clientId, _user_id, _role):
    return ok_object(serialize.client(get_client(clientId)))


@bp.post("/caption-ad/clients/<clientId>/suspend")
@guarded({"OperationsManager"})
def suspend_client(clientId, _user_id, _role):
    c = get_client(clientId)
    if c["client_status"] != "ACTIVE":
        raise invalid_transition("Only an ACTIVE client can be suspended")
    c["client_status"] = "SUSPENDED"
    touch(c)
    return ok_object(serialize.client(c))


@bp.post("/caption-ad/clients/<clientId>/reactivate")
@guarded({"OperationsManager"})
def reactivate_client(clientId, _user_id, _role):
    c = get_client(clientId)
    if c["client_status"] != "SUSPENDED":
        raise invalid_transition("Only a SUSPENDED client can be reactivated")
    c["client_status"] = "ACTIVE"
    touch(c)
    return ok_object(serialize.client(c))


# Re-exported for other blueprints that need the validation constant.
CLIENT_STATUSES = {"ACTIVE", "SUSPENDED", "TERMINATED"}
_ = validation  # silence unused import in some tooling

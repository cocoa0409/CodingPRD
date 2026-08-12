"""Client engagement endpoints (PRD §3.1)."""
from flask import Blueprint, request

from calc import mint_entity, recompute_client_aggregates, touch
from db import STORE
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    raise_err,
)
from middleware import (
    authenticate,
    get_body,
    req_enum,
    req_int,
    req_str,
    require_client_scope,
    require_role,
)
from response import paginate, success_object
from serializers import serialize, sorted_by_creation

bp = Blueprint("clients", __name__)

ALL_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}
LIST_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager"}
ENGAGEMENT_STATUSES = {"ACTIVE", "SUSPENDED", "TERMINATED"}

_ALLOWED_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "TERMINATED"),
    ("SUSPENDED", "TERMINATED"),
}


def get_client_or_404(client_id):
    client = STORE["clients"].get(client_id)
    if client is None:
        raise_err(ERR_NOT_FOUND, f"Client {client_id} not found")
    return client


@bp.route("/customs/clients", methods=["POST"])
def create_client():
    _, role = authenticate()
    require_role(role, {"FirmAdmin"})
    body = get_body()
    name = req_str(body, "name")
    iorn = req_str(body, "importer_of_record_number")
    fee_bps = req_int(body, "contingency_fee_bps")
    if fee_bps <= 0 or fee_bps > 10000:
        raise_err(
            ERR_INVALID_REQUEST,
            "contingency_fee_bps must be greater than 0 and at most 10000",
        )
    for existing in STORE["clients"].values():
        if existing["importer_of_record_number"] == iorn:
            raise_err(
                ERR_INVALID_REQUEST,
                "importer_of_record_number must be globally unique",
            )
    client = mint_entity()
    client.update({
        "name": name,
        "importer_of_record_number": iorn,
        "contingency_fee_bps": fee_bps,
        "engagement_status": "ACTIVE",
        "lifetime_recovered_cents": 0,
        "projected_fee_accrual_cents": 0,
        "open_audit_count": 0,
    })
    STORE["clients"][client["id"]] = client
    return success_object(serialize(client), 201)


@bp.route("/customs/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    client = get_client_or_404(client_id)
    require_client_scope(user_id, role, client["id"])
    recompute_client_aggregates(client, bump_on_change=False)
    return success_object(serialize(client))


@bp.route("/customs/clients", methods=["GET"])
def list_clients():
    _, role = authenticate()
    require_role(role, LIST_ROLES)
    items = sorted_by_creation(STORE["clients"].values())
    status_filter = request.args.get("engagement_status")
    if status_filter is not None:
        items = [c for c in items if c["engagement_status"] == status_filter]
    for c in items:
        recompute_client_aggregates(c, bump_on_change=False)
    return paginate([serialize(c) for c in items])


@bp.route("/customs/clients/<client_id>", methods=["PATCH"])
def patch_client(client_id):
    _, role = authenticate()
    require_role(role, {"FirmAdmin"})
    client = get_client_or_404(client_id)
    body = get_body()
    target = req_enum(body, "engagement_status", ENGAGEMENT_STATUSES)
    current = client["engagement_status"]
    if current == "TERMINATED":
        raise_err(ERR_ALREADY_TERMINAL, "Client is TERMINATED; no further transitions")
    if (current, target) not in _ALLOWED_TRANSITIONS:
        raise_err(ERR_INVALID_STATE, f"Cannot transition client {current} -> {target}")
    client["engagement_status"] = target
    touch(client)
    return success_object(serialize(client))

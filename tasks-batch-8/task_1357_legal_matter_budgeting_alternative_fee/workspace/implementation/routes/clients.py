"""Client endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import util
from errors import ApiError, ERR_INVALID_STATE_TRANSITION, ERR_CLIENT_HAS_OPEN_MATTERS
from middleware import get_context, require_roles
from response import success_object, success_list

bp = Blueprint("clients", __name__)


@bp.post("/firms/<firmId>/clients")
def create_client(firmId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin", "BillingPartner")
    firm = util.get_firm(firmId)
    data = util.body()
    util.require_fields(data, ["display_name", "client_number"])
    display_name = util.check_string(data, "display_name")
    client_number = util.check_string(data, "client_number")
    accrual_required = util.check_bool(data, "accrual_reporting_required", default=False)
    cadence = data.get("accrual_reporting_cadence_periods")
    if cadence is None:
        cadence = 1
    else:
        cadence = util.check_int(data, "accrual_reporting_cadence_periods", minimum=1)

    client = util.new_resource()
    client.update({
        "firm_id": firm["id"],
        "display_name": display_name,
        "client_number": client_number,
        "accrual_reporting_required": accrual_required,
        "accrual_reporting_cadence_periods": cadence,
        "status": "ACTIVE",
    })
    db.clients[client["id"]] = client
    return success_object(client, 201)


@bp.get("/firms/clients/<clientId>")
def get_client(clientId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin", "PricingAnalyst", "BillingPartner",
                  "ManagingPartner", "ClientContact")
    client = util.get_client_flat(clientId)
    return success_object(client, 200)


@bp.get("/firms/clients")
def list_clients():
    ctx = get_context()
    require_roles(ctx, "FirmAdmin", "PricingAnalyst", "BillingPartner",
                  "ManagingPartner", "ClientContact")
    filters = util.query_filters(["firm_id", "status"])
    items = util.apply_filters(list(db.clients.values()), filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.post("/firms/<firmId>/clients/<clientId>/suspend")
def suspend_client(firmId, clientId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin")
    client = util.get_client_scoped(firmId, clientId)
    if client["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only an ACTIVE client can be suspended", 409)
    client["status"] = "SUSPENDED"
    util.touch(client)
    return success_object(client, 200)


@bp.post("/firms/<firmId>/clients/<clientId>/activate")
def activate_client(firmId, clientId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin")
    client = util.get_client_scoped(firmId, clientId)
    if client["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a SUSPENDED client can be reactivated", 409)
    client["status"] = "ACTIVE"
    util.touch(client)
    return success_object(client, 200)


@bp.post("/firms/<firmId>/clients/<clientId>/close")
def close_client(firmId, clientId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin")
    client = util.get_client_scoped(firmId, clientId)
    if client["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only an ACTIVE or SUSPENDED client can be closed", 409)
    open_matters = [
        m for m in db.matters.values()
        if m.get("client_id") == clientId and m.get("status") != "CLOSED"
    ]
    if open_matters:
        raise ApiError(ERR_CLIENT_HAS_OPEN_MATTERS,
                       "Cannot close client with non-CLOSED matters", 409)
    client["status"] = "CLOSED"
    util.touch(client)
    return success_object(client, 200)

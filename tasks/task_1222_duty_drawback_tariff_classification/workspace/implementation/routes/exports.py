"""Export shipment endpoints (PRD §3.3)."""
from flask import Blueprint, request

from calc import mint_entity
from db import STORE
from errors import ERR_NOT_FOUND, raise_err
from middleware import (
    authenticate,
    get_body,
    req_dt,
    req_int,
    req_str,
    require_client_scope,
    require_role,
)
from response import paginate, success_object
from serializers import serialize, sorted_by_creation

bp = Blueprint("exports", __name__)

ALL_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}


def get_export_or_404(export_id):
    export = STORE["export_shipments"].get(export_id)
    if export is None:
        raise_err(ERR_NOT_FOUND, f"Export shipment {export_id} not found")
    return export


@bp.route("/customs/export-shipments", methods=["POST"])
def create_export():
    _, role = authenticate()
    require_role(role, {"Analyst"})
    body = get_body()
    client_id = req_str(body, "client_id")
    export_date = req_dt(body, "export_date")
    hts_code = req_str(body, "hts_code")
    quantity = req_int(body, "quantity", minimum=1)
    fob_value_cents = req_int(body, "fob_value_cents", minimum=0)
    dest_country = req_str(body, "dest_country")
    substituted_duty_rate_bps = req_int(body, "substituted_duty_rate_bps", minimum=0)

    if client_id not in STORE["clients"]:
        raise_err(ERR_NOT_FOUND, f"Client {client_id} not found")

    export = mint_entity()
    export.update({
        "client_id": client_id,
        "export_date": export_date,
        "hts_code": hts_code,
        "quantity": quantity,
        "fob_value_cents": fob_value_cents,
        "dest_country": dest_country,
        "substituted_duty_rate_bps": substituted_duty_rate_bps,
        "matched_quantity": 0,
        "value_pool_remaining_cents": fob_value_cents,
        "status": "UNMATCHED",
    })
    STORE["export_shipments"][export["id"]] = export
    return success_object(serialize(export), 201)


@bp.route("/customs/export-shipments/<export_id>", methods=["GET"])
def get_export(export_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    export = get_export_or_404(export_id)
    require_client_scope(user_id, role, export["client_id"])
    return success_object(serialize(export))


@bp.route("/customs/export-shipments", methods=["GET"])
def list_exports():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sorted_by_creation(STORE["export_shipments"].values())
    if role == "ClientContact":
        items = [e for e in items if e["client_id"] == user_id]
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [e for e in items if e["client_id"] == client_id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate([serialize(e) for e in items])

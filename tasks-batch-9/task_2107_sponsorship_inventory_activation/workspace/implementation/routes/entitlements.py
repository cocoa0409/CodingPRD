"""Entitlement reads (PRD 3.4)."""

from flask import Blueprint, request

from db import store, ordered
from errors import ApiError
from middleware import endpoint
from response import ok, paginate
from services.serialize import entitlement_out
from util import v_pagination, v_query_enum

bp = Blueprint("entitlements", __name__)

ENTITLEMENT_STATUSES = {"PENDING", "PARTIAL", "FULFILLED", "SHORTFALL", "WAIVED"}
READ_ROLES = ["PropertyAdmin", "SponsorshipSeller", "ContractApprover",
              "ActivationManager", "PerformanceAuditor"]


def get_entitlement_or_404(entitlement_id):
    ent = store.entitlements.get(entitlement_id)
    if ent is None:
        raise ApiError("ERR_ENTITLEMENT_NOT_FOUND", 404)
    return ent


@bp.get("/entitlements/<entitlement_id>")
@endpoint(READ_ROLES)
def read_entitlement(entitlement_id):
    return ok(entitlement_out(get_entitlement_or_404(entitlement_id)))


@bp.get("/entitlements")
@endpoint(READ_ROLES)
def list_entitlements():
    status = v_query_enum(request, "status", ENTITLEMENT_STATUSES)
    limit, offset = v_pagination(request)
    contract_id = request.args.get("contract_id")
    inventory_asset_id = request.args.get("inventory_asset_id")

    rows = list(store.entitlements.values())
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    if inventory_asset_id is not None:
        rows = [r for r in rows if r["inventory_asset_id"] == inventory_asset_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(ordered(rows), limit, offset, entitlement_out)

"""CarveOutProvision and StopLossProvision endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db as _db
from errors import (
    err_not_found,
    err_invalid_request,
    err_contract_not_draft,
    err_invalid_rate_parameters,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_carve_out, serialize_stop_loss
from services.validation import body, reject_unknown, as_str, as_int, as_enum, as_list
from routes.contracts import SERVICE_CATEGORIES

bp = Blueprint("provisions", __name__)

CARVE_TYPES = {"IMPLANT", "HIGH_COST_DRUG", "TRANSPLANT", "NICU"}
CARVE_RATE_MODELS = {"PERCENT_OF_CHARGE", "INVOICE_COST_PLUS"}
PROVISION_TYPES = {"STOP_LOSS", "OUTLIER"}


# --- CarveOutProvision ---

@bp.post("/api/carve-out-provisions")
def create_carve_out():
    require_roles(["ContractAnalyst"])
    data = body()
    reject_unknown(data, {
        "contract_id", "carve_type", "revenue_codes", "rate_model",
        "percent_bp", "invoice_markup_bp", "max_cap_cents",
    })
    contract_id = as_str(data, "contract_id")
    carve_type = as_enum(data, "carve_type", CARVE_TYPES)
    revenue_codes = as_list(data, "revenue_codes", required=True, non_empty=True)
    for rc in revenue_codes:
        if not isinstance(rc, str) or not rc:
            raise err_invalid_request("revenue_codes must be non-empty strings")
    rate_model = as_enum(data, "rate_model", CARVE_RATE_MODELS)
    percent_bp = as_int(data, "percent_bp", required=False, min_value=0, max_value=10000)
    invoice_markup_bp = as_int(data, "invoice_markup_bp", required=False, min_value=0, max_value=10000)
    max_cap_cents = as_int(data, "max_cap_cents", required=False, min_value=0)

    contract = _db.store.contracts.get(contract_id)
    if contract is None:
        raise err_not_found("Contract not found")
    if contract["status"] != "DRAFT":
        raise err_contract_not_draft()

    if rate_model == "PERCENT_OF_CHARGE":
        if percent_bp is None or invoice_markup_bp is not None:
            raise err_invalid_rate_parameters(
                "PERCENT_OF_CHARGE carve-out requires percent_bp and forbids invoice_markup_bp"
            )
    else:
        if invoice_markup_bp is None or percent_bp is not None:
            raise err_invalid_rate_parameters(
                "INVOICE_COST_PLUS carve-out requires invoice_markup_bp and forbids percent_bp"
            )

    now = _db.now_iso()
    prov = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "contract_id": contract_id,
        "carve_type": carve_type,
        "revenue_codes": revenue_codes,
        "rate_model": rate_model,
        "percent_bp": percent_bp,
        "invoice_markup_bp": invoice_markup_bp,
        "max_cap_cents": max_cap_cents,
    }
    _db.store.carve_outs[prov["id"]] = prov
    return success_object(serialize_carve_out(prov), status=201)


@bp.get("/api/carve-out-provisions/<pid>")
def get_carve_out(pid):
    require_roles(ALL_ROLES)
    prov = _db.store.carve_outs.get(pid)
    if prov is None:
        raise err_not_found("CarveOutProvision not found")
    return success_object(serialize_carve_out(prov))


@bp.get("/api/carve-out-provisions")
def list_carve_outs():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    contract_id = request.args.get("contract_id")
    carve_type = request.args.get("carve_type")
    if carve_type is not None and carve_type not in CARVE_TYPES:
        raise err_invalid_request("carve_type filter invalid")
    items = list(_db.store.carve_outs.values())
    if contract_id is not None:
        items = [p for p in items if p["contract_id"] == contract_id]
    if carve_type is not None:
        items = [p for p in items if p["carve_type"] == carve_type]
    items.sort(key=lambda p: p["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_carve_out(p) for p in page], limit, offset, total)


# --- StopLossProvision ---

@bp.post("/api/stop-loss-provisions")
def create_stop_loss():
    require_roles(["ContractAnalyst"])
    data = body()
    reject_unknown(data, {"contract_id", "provision_type", "service_category", "threshold_cents", "rate_bp"})
    contract_id = as_str(data, "contract_id")
    provision_type = as_enum(data, "provision_type", PROVISION_TYPES)
    service_category = as_enum(data, "service_category", SERVICE_CATEGORIES, required=False)
    threshold_cents = as_int(data, "threshold_cents", required=True)
    rate_bp = as_int(data, "rate_bp", required=True)

    contract = _db.store.contracts.get(contract_id)
    if contract is None:
        raise err_not_found("Contract not found")
    if contract["status"] != "DRAFT":
        raise err_contract_not_draft()

    if threshold_cents <= 0:
        raise err_invalid_rate_parameters("threshold_cents must be > 0")
    if rate_bp <= 0 or rate_bp > 10000:
        raise err_invalid_rate_parameters("rate_bp must be in (0, 10000]")

    now = _db.now_iso()
    prov = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "contract_id": contract_id,
        "provision_type": provision_type,
        "service_category": service_category,
        "threshold_cents": threshold_cents,
        "rate_bp": rate_bp,
    }
    _db.store.stop_losses[prov["id"]] = prov
    return success_object(serialize_stop_loss(prov), status=201)


@bp.get("/api/stop-loss-provisions/<pid>")
def get_stop_loss(pid):
    require_roles(ALL_ROLES)
    prov = _db.store.stop_losses.get(pid)
    if prov is None:
        raise err_not_found("StopLossProvision not found")
    return success_object(serialize_stop_loss(prov))


@bp.get("/api/stop-loss-provisions")
def list_stop_losses():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    contract_id = request.args.get("contract_id")
    provision_type = request.args.get("provision_type")
    if provision_type is not None and provision_type not in PROVISION_TYPES:
        raise err_invalid_request("provision_type filter invalid")
    items = list(_db.store.stop_losses.values())
    if contract_id is not None:
        items = [p for p in items if p["contract_id"] == contract_id]
    if provision_type is not None:
        items = [p for p in items if p["provision_type"] == provision_type]
    items.sort(key=lambda p: p["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_stop_loss(p) for p in page], limit, offset, total)

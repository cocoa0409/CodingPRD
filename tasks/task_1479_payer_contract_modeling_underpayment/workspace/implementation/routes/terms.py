"""ContractTerm endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db as _db
from errors import (
    err_not_found,
    err_invalid_request,
    err_contract_not_draft,
    err_duplicate_service_category,
    err_invalid_rate_parameters,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_term
from services.validation import body, reject_unknown, as_str, as_int, as_enum
from routes.contracts import SERVICE_CATEGORIES

bp = Blueprint("terms", __name__)

RATE_MODELS = {"PER_DIEM", "CASE_RATE", "PERCENT_OF_CHARGE", "DRG_BASE"}


@bp.post("/api/contract-terms")
def create_term():
    require_roles(["ContractAnalyst"])
    data = body()
    reject_unknown(data, {"contract_id", "service_category", "rate_model", "base_rate_cents", "percent_of_charge_bp"})
    contract_id = as_str(data, "contract_id")
    service_category = as_enum(data, "service_category", SERVICE_CATEGORIES)
    rate_model = as_enum(data, "rate_model", RATE_MODELS)
    base_rate_cents = as_int(data, "base_rate_cents", required=False, min_value=0)
    pct = as_int(data, "percent_of_charge_bp", required=False, min_value=0, max_value=10000)

    contract = _db.store.contracts.get(contract_id)
    if contract is None:
        raise err_not_found("Contract not found")

    # State (rung 6): requires DRAFT
    if contract["status"] != "DRAFT":
        raise err_contract_not_draft()

    # Uniqueness/consistency (rung 10)
    for t in _db.store.terms.values():
        if t["contract_id"] == contract_id and t["service_category"] == service_category:
            raise err_duplicate_service_category()
    if rate_model == "PERCENT_OF_CHARGE":
        if pct is None or base_rate_cents is not None:
            raise err_invalid_rate_parameters(
                "PERCENT_OF_CHARGE requires percent_of_charge_bp and forbids base_rate_cents"
            )
    else:
        if base_rate_cents is None or pct is not None:
            raise err_invalid_rate_parameters(
                f"{rate_model} requires base_rate_cents and forbids percent_of_charge_bp"
            )

    now = _db.now_iso()
    term = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "contract_id": contract_id,
        "service_category": service_category,
        "rate_model": rate_model,
        "base_rate_cents": base_rate_cents,
        "percent_of_charge_bp": pct,
    }
    _db.store.terms[term["id"]] = term
    return success_object(serialize_term(term), status=201)


@bp.get("/api/contract-terms/<tid>")
def get_term(tid):
    require_roles(ALL_ROLES)
    term = _db.store.terms.get(tid)
    if term is None:
        raise err_not_found("ContractTerm not found")
    return success_object(serialize_term(term))


@bp.get("/api/contract-terms")
def list_terms():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    contract_id = request.args.get("contract_id")
    service_category = request.args.get("service_category")
    if service_category is not None and service_category not in SERVICE_CATEGORIES:
        raise err_invalid_request("service_category filter invalid")
    items = list(_db.store.terms.values())
    if contract_id is not None:
        items = [t for t in items if t["contract_id"] == contract_id]
    if service_category is not None:
        items = [t for t in items if t["service_category"] == service_category]
    items.sort(key=lambda t: t["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_term(t) for t in page], limit, offset, total)

"""RateEscalator endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db as _db
from db import parse_date
from errors import (
    err_not_found,
    err_invalid_state,
    err_invalid_request,
    err_escalator_out_of_term,
    err_escalator_date_collision,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_escalator
from services.validation import body, reject_unknown, as_str, as_int, as_enum, as_date, as_bool
from services.pricing import run_pricing, reevaluate_claim_after_change, touch
from routes.contracts import SERVICE_CATEGORIES

bp = Blueprint("escalators", __name__)


@bp.post("/api/rate-escalators")
def create_escalator():
    require_roles(["ContractAnalyst"])
    data = body()
    reject_unknown(data, {"contract_id", "effective_date", "escalator_bp", "applies_to_category", "compounding"})
    contract_id = as_str(data, "contract_id")
    effective_date = as_date(data, "effective_date")
    escalator_bp = as_int(data, "escalator_bp", required=True)
    if escalator_bp <= 0:
        raise err_invalid_request("escalator_bp must be > 0")
    applies_to_category = as_enum(data, "applies_to_category", SERVICE_CATEGORIES, required=False)
    compounding = as_bool(data, "compounding", default=True)

    contract = _db.store.contracts.get(contract_id)
    if contract is None:
        raise err_not_found("Contract not found")

    # State (rung 6): DRAFT or ACTIVE only; terminal and SUSPENDED reject
    if contract["status"] not in {"DRAFT", "ACTIVE"}:
        raise err_invalid_state("Escalator creation requires contract DRAFT or ACTIVE")

    # Temporal (rung 9): within term
    if not (parse_date(contract["effective_date"]) <= parse_date(effective_date) <= parse_date(contract["expiration_date"])):
        raise err_escalator_out_of_term()

    # Uniqueness (rung 10): effective_date unique per contract
    for e in _db.store.escalators.values():
        if e["contract_id"] == contract_id and e["effective_date"] == effective_date:
            raise err_escalator_date_collision()

    now = _db.now_iso()
    esc = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "contract_id": contract_id,
        "effective_date": effective_date,
        "escalator_bp": escalator_bp,
        "applies_to_category": applies_to_category,
        "compounding": compounding,
        "status": "SCHEDULED",
        "applied_date": None,
    }
    _db.store.escalators[esc["id"]] = esc
    return success_object(serialize_escalator(esc), status=201)


@bp.get("/api/rate-escalators/<eid>")
def get_escalator(eid):
    require_roles(ALL_ROLES)
    esc = _db.store.escalators.get(eid)
    if esc is None:
        raise err_not_found("RateEscalator not found")
    return success_object(serialize_escalator(esc))


@bp.get("/api/rate-escalators")
def list_escalators():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    if status is not None and status not in {"SCHEDULED", "APPLIED", "VOIDED"}:
        raise err_invalid_request("status filter invalid")
    items = list(_db.store.escalators.values())
    if contract_id is not None:
        items = [e for e in items if e["contract_id"] == contract_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_escalator(e) for e in page], limit, offset, total)


@bp.post("/api/rate-escalators/<eid>/void")
def void_escalator(eid):
    require_roles(["ContractManager"])
    esc = _db.store.escalators.get(eid)
    if esc is None:
        raise err_not_found("RateEscalator not found")
    if esc["status"] not in {"SCHEDULED", "APPLIED"}:
        raise err_invalid_state("Only a SCHEDULED or APPLIED escalator may be voided")
    was_applied = esc["status"] == "APPLIED"
    esc["status"] = "VOIDED"
    touch(esc)
    if was_applied:
        # Reprice cascade: claims priced under this contract, PRICED/REPRICED,
        # discharge_date >= escalator.effective_date
        eff = parse_date(esc["effective_date"])
        targets = [
            c for c in _db.store.claims.values()
            if c.get("priced_contract_id") == esc["contract_id"]
            and c["pricing_status"] in {"PRICED", "REPRICED"}
            and parse_date(c["discharge_date"]) >= eff
        ]
        targets.sort(key=lambda c: c["seq"])
        for claim in targets:
            run_pricing(claim, "RETROSPECTIVE")
            reevaluate_claim_after_change(claim, restate_original=True)
    return success_object(serialize_escalator(esc))

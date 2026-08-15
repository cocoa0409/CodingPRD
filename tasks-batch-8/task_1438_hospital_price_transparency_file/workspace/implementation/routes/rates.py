"""PayerNegotiatedRate: create-with-supersede, read, list, DRAFT-only amend."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CONTRACT_NOT_EDITABLE,
    ERR_CONTRACT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ITEM_RETIRED,
    ERR_RATE_LOCKED,
    ERR_RATE_NOT_FOUND,
    ERR_SERVICE_ITEM_NOT_FOUND,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import PERCENT_RATE_TYPES, RATE_TYPES, RATE_TYPE_FEE_SCHEDULE_FLAT, materialize_rate
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    require_number,
    require_string,
    sort_created,
)

bp = Blueprint("rates", __name__)


def get_rate_or_404(rid: str) -> dict:
    r = db.payer_negotiated_rates.get(rid)
    if r is None:
        raise_err(ERR_RATE_NOT_FOUND, "Negotiated rate not found")
    return r


def _validate_rate_payload_types(body: dict, rate_type: str) -> tuple:
    """Conditional required inputs: rate_percent iff percent-typed,
    flat_amount_cents iff FEE_SCHEDULE_FLAT (PRD 3.2). Returns (pct, flat)."""
    pct = None
    flat = None
    if rate_type in PERCENT_RATE_TYPES:
        pct = require_number(body, "rate_percent", minimum=0, maximum=200)
    elif rate_type == RATE_TYPE_FEE_SCHEDULE_FLAT:
        flat_raw = require_field(body, "flat_amount_cents")
        if isinstance(flat_raw, bool) or not isinstance(flat_raw, int) or flat_raw < 0:
            raise_err(ERR_INVALID_REQUEST, "flat_amount_cents must be an integer >= 0")
        flat = flat_raw
    return pct, flat


@bp.post("/transparency/payer-negotiated-rates")
@require_roles("ContractManager")
def create_rate(_user_id: str, _role: str):
    body = get_json_body()
    contract_id = require_string(body, "contract_id")
    service_item_id = require_string(body, "service_item_id")
    rate_type = require_enum(body, "rate_type", RATE_TYPES)
    pct, flat = _validate_rate_payload_types(body, rate_type)

    # Existence (P3), body field order: contract_id, then service_item_id.
    contract = db.payer_contracts.get(contract_id)
    if contract is None:
        raise_err(ERR_CONTRACT_NOT_FOUND, "Payer contract not found")
    item = db.service_items.get(service_item_id)
    if item is None:
        raise_err(ERR_SERVICE_ITEM_NOT_FOUND, "Service item not found")

    # State (P4), field order: contract editability, then retired-item guard.
    if contract["status"] not in ("DRAFT", "RENEGOTIATING"):
        raise_err(ERR_CONTRACT_NOT_EDITABLE, "Rates may only be created while the contract is DRAFT or RENEGOTIATING")
    if item["status"] != "ACTIVE":
        raise_err(ERR_ITEM_RETIRED, "Cannot create a rate against a RETIRED service item")

    # Create-with-supersede: a pre-existing DRAFT rate for the same
    # (contract, item) pair moves DRAFT -> SUPERSEDED.
    for r in db.payer_negotiated_rates.values():
        if (
            r["contract_id"] == contract_id
            and r["service_item_id"] == service_item_id
            and r["status"] == "DRAFT"
        ):
            r["status"] = "SUPERSEDED"
            db.bump(r)

    rate = db.stamp_new({
        "contract_id": contract_id,
        "service_item_id": service_item_id,
        "rate_type": rate_type,
        "rate_percent": pct,
        "flat_amount_cents": flat,
        "negotiated_amount_cents": 0,
        "status": "DRAFT",
    })
    rate["negotiated_amount_cents"] = materialize_rate(rate)
    db.payer_negotiated_rates[rate["id"]] = rate
    return success_object(db.public(rate), 201)


@bp.get("/transparency/payer-negotiated-rates/<rid>")
@require_roles(*ALL_ROLES)
def get_rate(rid: str, _user_id: str, _role: str):
    return success_object(db.public(get_rate_or_404(rid)), 200)


@bp.get("/transparency/payer-negotiated-rates")
@require_roles(*ALL_ROLES)
def list_rates(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.payer_negotiated_rates.values())
    items = apply_filters(items, ["contract_id", "service_item_id", "status"])
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([db.public(r) for r in page], limit, offset, total)


@bp.patch("/transparency/payer-negotiated-rates/<rid>")
@require_roles("ContractManager")
def amend_rate(rid: str, _user_id: str, _role: str):
    rate = get_rate_or_404(rid)

    # State (P4): amendment is defined only while the rate is DRAFT.
    if rate["status"] != "DRAFT":
        raise_err(ERR_RATE_LOCKED, "Only DRAFT rates may be amended")

    body = get_json_body()
    has_pct = "rate_percent" in body and body["rate_percent"] is not None
    has_flat = "flat_amount_cents" in body and body["flat_amount_cents"] is not None
    if not has_pct and not has_flat:
        raise_err(ERR_INVALID_REQUEST, "No-op payload: provide rate_percent or flat_amount_cents")

    if has_pct:
        pct = require_number(body, "rate_percent", minimum=0, maximum=200)
        rate["rate_percent"] = pct
    if has_flat:
        flat_raw = body["flat_amount_cents"]
        if isinstance(flat_raw, bool) or not isinstance(flat_raw, int) or flat_raw < 0:
            raise_err(ERR_INVALID_REQUEST, "flat_amount_cents must be an integer >= 0")
        rate["flat_amount_cents"] = flat_raw

    # Recompute the materialized amount. No record cascade: DRAFT rates are
    # excluded from every record's input set anyway (PRD 3.2).
    rate["negotiated_amount_cents"] = materialize_rate(rate)
    db.bump(rate)
    return success_object(db.public(rate), 200)

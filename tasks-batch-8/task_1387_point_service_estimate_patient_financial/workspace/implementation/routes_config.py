"""Configuration endpoints: charge items, payer contracts, contract rates."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_RATE_WINDOW_OVERLAP,
    ERR_UNKNOWN_CPT_CODE,
    not_found,
)
from middleware import ALL_ROLES, authenticate
from response import ok_list, ok_object
from util import (
    base_record,
    get_body,
    opt_date,
    opt_int,
    paginate,
    req_bool,
    req_date,
    req_enum,
    req_int,
    req_str,
    serialize,
)

bp = Blueprint("config", __name__)


# --- charge items -----------------------------------------------------------

@bp.post("/clearance/charge-items")
def create_charge_item():
    authenticate(["SystemAdmin"])
    b = get_body()
    cpt_code = req_str(b, "cpt_code")
    description = req_str(b, "description")
    list_price_cents = req_int(b, "list_price_cents")
    if list_price_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "list_price_cents must be > 0", 400)
    requires_auth_prior = req_bool(b, "requires_auth_prior")
    if cpt_code in db.cpt_index:
        raise ApiError(ERR_INVALID_REQUEST, "cpt_code already exists", 400)
    rec = base_record()
    rec.update({
        "cpt_code": cpt_code,
        "description": description,
        "list_price_cents": list_price_cents,
        "requires_auth_prior": requires_auth_prior,
    })
    db.charge_items[rec["id"]] = rec
    db.cpt_index[cpt_code] = rec["id"]
    return ok_object(serialize(rec), 201)


# --- payer contracts --------------------------------------------------------

@bp.post("/clearance/payer-contracts")
def create_payer_contract():
    authenticate(["SystemAdmin"])
    b = get_body()
    payer_code = req_str(b, "payer_code")
    payer_name = req_str(b, "payer_name")
    bundling_rule = req_enum(b, "bundling_rule", ("NONE", "MULTIPLE_PROCEDURE_REDUCTION"))
    if bundling_rule == "MULTIPLE_PROCEDURE_REDUCTION":
        reduction_pct = req_int(b, "reduction_pct")
        if reduction_pct < 1 or reduction_pct > 99:
            raise ApiError(ERR_INVALID_REQUEST,
                           "reduction_pct must be in 1..99 for MULTIPLE_PROCEDURE_REDUCTION", 400)
    else:
        reduction_pct = opt_int(b, "reduction_pct", 0)
    if payer_code in db.payer_code_index:
        raise ApiError(ERR_INVALID_REQUEST, "payer_code already exists", 400)
    rec = base_record()
    rec.update({
        "payer_code": payer_code,
        "payer_name": payer_name,
        "bundling_rule": bundling_rule,
        "reduction_pct": reduction_pct,
    })
    db.payer_contracts[rec["id"]] = rec
    db.payer_code_index[payer_code] = rec["id"]
    return ok_object(serialize(rec), 201)


@bp.get("/clearance/payer-contracts/<cid>")
def get_payer_contract(cid):
    authenticate(ALL_ROLES)
    rec = db.payer_contracts.get(cid)
    if rec is None:
        raise not_found("payer contract not found")
    return ok_object(serialize(rec))


@bp.get("/clearance/payer-contracts")
def list_payer_contracts():
    authenticate(ALL_ROLES)
    items = list(db.payer_contracts.values())
    payer_code = request.args.get("payer_code")
    if payer_code is not None:
        items = [c for c in items if c["payer_code"] == payer_code]
    page, meta = paginate(items)
    return ok_list([serialize(c) for c in page], meta)


# --- contract rates ---------------------------------------------------------

@bp.post("/clearance/payer-contracts/<cid>/rates")
def create_rate(cid):
    authenticate(["SystemAdmin"])
    contract = db.payer_contracts.get(cid)
    if contract is None:
        raise not_found("payer contract not found")
    b = get_body()
    cpt_code = req_str(b, "cpt_code")
    rate_cents = req_int(b, "rate_cents")
    if rate_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "rate_cents must be > 0", 400)
    effective_from = req_date(b, "effective_from")
    effective_to = opt_date(b, "effective_to")
    if effective_to is not None and effective_to <= effective_from:
        raise ApiError(ERR_INVALID_REQUEST, "effective_to must be > effective_from", 400)
    # cpt must exist in the charge master
    if cpt_code not in db.cpt_index:
        raise ApiError(ERR_UNKNOWN_CPT_CODE, "unknown cpt_code: %s" % cpt_code, 422)
    # half-open [from, to) overlap check per (contract, cpt); touching is allowed
    for r in db.rates.values():
        if r["contract_id"] != cid or r["cpt_code"] != cpt_code:
            continue
        existing_to = r["effective_to"] or "9999-12-31"  # None = open-ended
        new_to = effective_to or "9999-12-31"
        if effective_from < existing_to and r["effective_from"] < new_to:
            raise ApiError(ERR_RATE_WINDOW_OVERLAP,
                           "rate window overlaps an existing window for this contract and CPT", 409)
    rec = base_record()
    rec.update({
        "contract_id": cid,
        "cpt_code": cpt_code,
        "rate_cents": rate_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
    })
    db.rates[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/clearance/payer-contracts/<cid>/rates")
def list_rates(cid):
    authenticate(ALL_ROLES)
    if cid not in db.payer_contracts:
        raise not_found("payer contract not found")
    items = [r for r in db.rates.values() if r["contract_id"] == cid]
    page, meta = paginate(items)
    return ok_list([serialize(r) for r in page], meta)

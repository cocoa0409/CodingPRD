"""PayerContract lifecycle: create (DRAFT), activate, renegotiate, terminate,
plus the facility-scoped contract listing. Expiry is clock-driven (clock.py)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CONTRACT_ALREADY_TERMINAL,
    ERR_CONTRACT_NOT_FOUND,
    ERR_CONTRACT_WINDOW_OVERLAP,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_PAYER_NOT_FOUND,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import (
    cascade_contract_activate,
    cascade_contract_deactivate,
    cascade_contract_renegotiate,
)
from util import (
    apply_filters,
    get_json_body,
    optional_enum,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
    require_ts,
    sort_created,
)

bp = Blueprint("contracts", __name__)

CONF_CLAUSES = {"DISCLOSE_ALLOWED", "DERIVED_ONLY", "AGGREGATE_ONLY"}


def get_contract_or_404(cid: str) -> dict:
    c = db.payer_contracts.get(cid)
    if c is None:
        raise_err(ERR_CONTRACT_NOT_FOUND, "Payer contract not found")
    return c


@bp.post("/transparency/payer-contracts")
@require_roles("ContractManager")
def create_contract(_user_id: str, _role: str):
    body = get_json_body()
    facility_id = require_string(body, "facility_id")
    payer_id = require_string(body, "payer_id")
    clause_raw = require_string(body, "confidentiality_clause")
    annual_volume = require_int(body, "annual_volume", minimum=0)
    effective_start = require_ts(body, "effective_start")
    effective_end = require_ts(body, "effective_end")

    # Existence (P3), body field order: facility_id then payer_id.
    if facility_id not in db.facilities:
        raise_err(ERR_FACILITY_NOT_FOUND, "Facility not found")
    if payer_id not in db.payers:
        raise_err(ERR_PAYER_NOT_FOUND, "Payer not found")

    # Enum membership after FK existence.
    if clause_raw not in CONF_CLAUSES:
        raise_err(ERR_INVALID_REQUEST, "confidentiality_clause must be DISCLOSE_ALLOWED, DERIVED_ONLY, or AGGREGATE_ONLY")

    # Temporal (P8): closed interval, start must not fall after end.
    if parse_iso8601(effective_start, "effective_start") > parse_iso8601(effective_end, "effective_end"):
        raise_err(ERR_INVALID_WINDOW, "effective_start must not fall after effective_end")

    contract = db.stamp_new({
        "facility_id": facility_id,
        "payer_id": payer_id,
        "confidentiality_clause": clause_raw,
        "annual_volume": annual_volume,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "status": "DRAFT",
    })
    db.payer_contracts[contract["id"]] = contract
    return success_object(db.public(contract), 201)


@bp.get("/transparency/facilities/<fid>/payer-contracts")
@require_roles(*ALL_ROLES)
def list_facility_contracts(fid: str, _user_id: str, _role: str):
    if fid not in db.facilities:
        raise_err(ERR_FACILITY_NOT_FOUND, "Facility not found")
    limit, offset = parse_pagination()
    items = [c for c in db.payer_contracts.values() if c["facility_id"] == fid]
    items = apply_filters(items, ["status"])
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([db.public(c) for c in page], limit, offset, total)


def _check_activation_window_and_overlap(contract: dict) -> None:
    start = parse_iso8601(contract["effective_start"], "effective_start")
    end = parse_iso8601(contract["effective_end"], "effective_end")
    # Window re-check first (PRD 3.8 prose order), then single-active-coverage.
    if start > end:
        raise_err(ERR_INVALID_WINDOW, "effective_start must not fall after effective_end")
    for other in db.payer_contracts.values():
        if other["id"] == contract["id"]:
            continue
        if other["facility_id"] != contract["facility_id"] or other["payer_id"] != contract["payer_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        o_start = parse_iso8601(other["effective_start"], "effective_start")
        o_end = parse_iso8601(other["effective_end"], "effective_end")
        # CLOSED intervals: touching endpoints count as intersection.
        if start <= o_end and end >= o_start:
            raise_err(ERR_CONTRACT_WINDOW_OVERLAP, "An ACTIVE contract already covers an intersecting window for this facility+payer")


@bp.post("/transparency/payer-contracts/<cid>/activate")
@require_roles("ContractManager")
def activate_contract(cid: str, _user_id: str, _role: str):
    contract = get_contract_or_404(cid)
    if contract["status"] not in ("DRAFT", "RENEGOTIATING"):
        raise_err(ERR_CONTRACT_ALREADY_TERMINAL, "Contract cannot be activated from its current status")
    _check_activation_window_and_overlap(contract)
    contract["status"] = "ACTIVE"
    db.bump(contract)
    cascade_contract_activate(contract)
    return success_object(db.public(contract), 200)


@bp.post("/transparency/payer-contracts/<cid>/renegotiate")
@require_roles("ContractManager")
def renegotiate_contract(cid: str, _user_id: str, _role: str):
    contract = get_contract_or_404(cid)
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_ALREADY_TERMINAL, "Only an ACTIVE contract can move to RENEGOTIATING")
    body = get_json_body()
    new_end = None
    if "effective_end" in body and body["effective_end"] is not None:
        new_end = require_ts(body, "effective_end")
    new_clause = optional_enum(body, "confidentiality_clause", CONF_CLAUSES, default=None)
    if new_end is not None:
        contract["effective_end"] = new_end
    if new_clause is not None:
        contract["confidentiality_clause"] = new_clause
    contract["status"] = "RENEGOTIATING"
    db.bump(contract)
    cascade_contract_renegotiate(contract)
    return success_object(db.public(contract), 200)


@bp.post("/transparency/payer-contracts/<cid>/terminate")
@require_roles("ContractManager")
def terminate_contract(cid: str, _user_id: str, _role: str):
    contract = get_contract_or_404(cid)
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_ALREADY_TERMINAL, "Only an ACTIVE contract can be terminated")
    contract["status"] = "TERMINATED"
    db.bump(contract)
    cascade_contract_deactivate(contract)
    return success_object(db.public(contract), 200)

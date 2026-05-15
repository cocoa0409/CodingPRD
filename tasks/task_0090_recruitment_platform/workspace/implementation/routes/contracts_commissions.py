"""HeadhunterContract creation + CommissionRecord read/list."""
from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request

from auth import get_caller, require_roles
from errors import (
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from request_body import get_json_body, paginate, parse_pagination, require_field
from response import success_array, success_object
from services.commission import project_view
from store import init_common_fields, lock, store


bp = Blueprint("contracts_commissions", __name__)


_FEE_MODELS = {"SUCCESS_FEE", "RETAINER", "HYBRID"}
_TRIGGER_EVENTS = {"OFFER_ACCEPTED", "ONBOARDED", "PROBATION_PASSED"}


@bp.post("/recruitment/headhunter-contracts")
def create_contract():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    body = get_json_body()
    headhunter_user_id = require_field(body, "headhunter_user_id")
    company_id = require_field(body, "company_id")
    fee_model = require_field(body, "fee_model")
    trigger_event = require_field(body, "trigger_event")
    success_fee_pct_bps = body.get("success_fee_pct_bps", 0)
    retainer_amount_cents = body.get("retainer_amount_cents", 0)
    clawback_window_days = body.get("clawback_window_days", 90)
    tax_withholding_pct_bps = body.get("tax_withholding_pct_bps", 1000)

    if fee_model not in _FEE_MODELS:
        raise_err(ERR_VALIDATION, "fee_model invalid.")
    if trigger_event not in _TRIGGER_EVENTS:
        raise_err(ERR_VALIDATION, "trigger_event invalid.")

    company = store.companies.get(company_id)
    if company is None:
        raise_err(ERR_REFERENCE_NOT_FOUND, "company_id not found.")

    for v, name in (
        (success_fee_pct_bps, "success_fee_pct_bps"),
        (retainer_amount_cents, "retainer_amount_cents"),
        (clawback_window_days, "clawback_window_days"),
        (tax_withholding_pct_bps, "tax_withholding_pct_bps"),
    ):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise_err(ERR_VALIDATION, f"{name} must be a non-negative integer.")

    if not isinstance(headhunter_user_id, str) or not headhunter_user_id:
        raise_err(ERR_VALIDATION, "headhunter_user_id required.")

    # Use the supplied headhunter_user_id as the contract's id so that the
    # HeadhunterUser caller can authenticate against it via X-User-ID.
    row = init_common_fields(
        {
            "id": headhunter_user_id,
            "headhunter_user_id": headhunter_user_id,
            "company_id": company_id,
            "fee_model": fee_model,
            "success_fee_pct_bps": success_fee_pct_bps,
            "retainer_amount_cents": retainer_amount_cents,
            "trigger_event": trigger_event,
            "clawback_window_days": clawback_window_days,
            "tax_withholding_pct_bps": tax_withholding_pct_bps,
            "contract_status": "ACTIVE",
        }
    )
    store.headhunter_contracts[row["id"]] = row
    body_out, status = success_object(dict(row), 201)
    return jsonify(body_out), status


@bp.get("/recruitment/commission-records/<cid>")
def get_commission_record(cid: str):
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "HeadhunterUser"])
    rec = store.commission_records.get(cid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "CommissionRecord not found.")
    if caller.role == "HeadhunterUser":
        if rec.get("headhunter_contract_id") != caller.user_id:
            raise_err(ERR_FORBIDDEN, "Cannot view another contract's commission record.")
    body_out, status = success_object(project_view(rec))
    return jsonify(body_out), status


@bp.get("/recruitment/commission-records")
def list_commission_records():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin", "HeadhunterUser"])
    limit, offset = parse_pagination()
    hc_id = request.args.get("headhunter_contract_id")
    sstatus = request.args.get("settlement_status")
    rows = list(store.commission_records.values())
    if caller.role == "HeadhunterUser":
        rows = [r for r in rows if r.get("headhunter_contract_id") == caller.user_id]
    if hc_id is not None:
        rows = [r for r in rows if r.get("headhunter_contract_id") == hc_id]
    if sstatus is not None:
        rows = [r for r in rows if r.get("settlement_status") == sstatus]
    rows.sort(key=lambda r: r.get("created_at", ""))
    page, total = paginate(rows, limit, offset)
    out = [project_view(r) for r in page]
    body_out, status = success_array(out, limit=limit, offset=offset, total_count=total)
    return jsonify(body_out), status

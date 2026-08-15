"""Claim and ClaimLine endpoints (PRD §3.5)."""

from flask import Blueprint, request

import db as _db
from db import parse_date
from errors import (
    err_not_found,
    err_invalid_state,
    err_invalid_request,
    err_payer_inactive,
    err_duplicate_claim_number,
    err_line_outside_stay,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_claim, serialize_claim_line
from services.validation import (
    body, reject_unknown, as_str, as_int, as_enum, as_date, as_number,
)
from services.pricing import (
    run_pricing,
    reevaluate_claim_after_change,
    touch,
    compute_paid_amount,
)
from routes.contracts import SERVICE_CATEGORIES

bp = Blueprint("claims", __name__)


@bp.post("/api/claims")
def create_claim():
    require_roles(["RevenueIntegrityAnalyst"])
    data = body()
    reject_unknown(data, {
        "payer_id", "claim_number", "patient_account_number", "service_category",
        "admission_date", "discharge_date", "total_billed_charges_cents", "drg_weight",
    })
    payer_id = as_str(data, "payer_id")
    claim_number = as_str(data, "claim_number")
    patient_account_number = as_str(data, "patient_account_number")
    service_category = as_enum(data, "service_category", SERVICE_CATEGORIES)
    admission_date = as_date(data, "admission_date")
    discharge_date = as_date(data, "discharge_date")
    if parse_date(admission_date) > parse_date(discharge_date):
        raise err_invalid_request("admission_date must be <= discharge_date")
    if parse_date(discharge_date) > _db.today():
        raise err_invalid_request("discharge_date may not be after today")
    total_billed = as_int(data, "total_billed_charges_cents", required=True, min_value=0)
    drg_weight = as_number(data, "drg_weight", required=False)
    if drg_weight is not None and drg_weight < 0:
        raise err_invalid_request("drg_weight must be >= 0")

    payer = _db.store.payers.get(payer_id)
    if payer is None:
        raise err_not_found("Payer not found")
    if payer["status"] != "ACTIVE":
        raise err_payer_inactive()
    for c in _db.store.claims.values():
        if c["payer_id"] == payer_id and c["claim_number"] == claim_number:
            raise err_duplicate_claim_number()

    now = _db.now_iso()
    claim = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "payer_id": payer_id,
        "claim_number": claim_number,
        "patient_account_number": patient_account_number,
        "service_category": service_category,
        "admission_date": admission_date,
        "discharge_date": discharge_date,
        "total_billed_charges_cents": total_billed,
        "drg_weight": drg_weight,
        "pricing_status": "UNPRICED",
        "remittance_status": "AWAITING_REMITTANCE",
        "priced_contract_id": None,
        "network_agreement_id": None,
        "network_flag": "NONE",
        "pricing_variant": None,
        "expected_reimbursement_cents": None,
        "original_expected_cents": None,
        "pricing_trace": None,
    }
    _db.store.claims[claim["id"]] = claim
    return success_object(serialize_claim(claim), status=201)


@bp.get("/api/claims/<cid>")
def get_claim(cid):
    require_roles(ALL_ROLES)
    claim = _db.store.claims.get(cid)
    if claim is None:
        raise err_not_found("Claim not found")
    return success_object(serialize_claim(claim))


@bp.get("/api/claims")
def list_claims():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    payer_id = request.args.get("payer_id")
    priced_contract_id = request.args.get("priced_contract_id")
    network_agreement_id = request.args.get("network_agreement_id")
    pricing_status = request.args.get("pricing_status")
    remittance_status = request.args.get("remittance_status")
    network_flag = request.args.get("network_flag")
    if pricing_status is not None and pricing_status not in {"UNPRICED", "PRICED", "REPRICED"}:
        raise err_invalid_request("pricing_status filter invalid")
    if remittance_status is not None and remittance_status not in {
        "AWAITING_REMITTANCE", "REMITTANCE_POSTED", "VARIANCE_FLAGGED", "RECONCILED",
    }:
        raise err_invalid_request("remittance_status filter invalid")
    if network_flag is not None and network_flag not in {
        "NONE", "WRAP_CONFIRMED", "SILENT_PPO_SUSPECT", "OUT_OF_NETWORK",
    }:
        raise err_invalid_request("network_flag filter invalid")
    items = list(_db.store.claims.values())
    if payer_id is not None:
        items = [c for c in items if c["payer_id"] == payer_id]
    if priced_contract_id is not None:
        items = [c for c in items if c.get("priced_contract_id") == priced_contract_id]
    if network_agreement_id is not None:
        items = [c for c in items if c.get("network_agreement_id") == network_agreement_id]
    if pricing_status is not None:
        items = [c for c in items if c["pricing_status"] == pricing_status]
    if remittance_status is not None:
        items = [c for c in items if c["remittance_status"] == remittance_status]
    if network_flag is not None:
        items = [c for c in items if c["network_flag"] == network_flag]
    items.sort(key=lambda c: c["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_claim(c) for c in page], limit, offset, total)


def _get_claim_or_404(cid):
    claim = _db.store.claims.get(cid)
    if claim is None:
        raise err_not_found("Claim not found")
    return claim


@bp.post("/api/claims/<cid>/lines")
def add_claim_line(cid):
    require_roles(["RevenueIntegrityAnalyst"])
    # Path params validated left to right: claim first
    claim = _db.store.claims.get(cid)
    if claim is None:
        raise err_not_found("Claim not found")
    data = body()
    reject_unknown(data, {"revenue_code", "service_date", "charge_cents", "units", "invoice_cost_cents"})
    revenue_code = as_str(data, "revenue_code")
    service_date = as_date(data, "service_date")
    charge_cents = as_int(data, "charge_cents", required=True, min_value=0)
    units = as_int(data, "units", required=False, min_value=1)
    if units is None:
        units = 1
    invoice_cost_cents = as_int(data, "invoice_cost_cents", required=False, min_value=0)

    # State (rung 6): only while UNPRICED
    if claim["pricing_status"] != "UNPRICED":
        raise err_invalid_state("Claim lines may be added only while the claim is UNPRICED")

    # Temporal (rung 9): inside stay
    if not (parse_date(claim["admission_date"]) <= parse_date(service_date) <= parse_date(claim["discharge_date"])):
        raise err_line_outside_stay()

    now = _db.now_iso()
    line = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "claim_id": cid,
        "revenue_code": revenue_code,
        "service_date": service_date,
        "charge_cents": charge_cents,
        "units": units,
        "invoice_cost_cents": invoice_cost_cents,
        "is_carve_out": False,
        "priced_amount_cents": None,
    }
    _db.store.claim_lines[line["id"]] = line
    return success_object(serialize_claim_line(line), status=201)


@bp.get("/api/claims/<cid>/lines")
def list_claim_lines(cid):
    require_roles(ALL_ROLES)
    claim = _db.store.claims.get(cid)
    if claim is None:
        raise err_not_found("Claim not found")
    limit, offset = parse_pagination(request.args)
    items = [l for l in _db.store.claim_lines.values() if l["claim_id"] == cid]
    items.sort(key=lambda l: l["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_claim_line(l) for l in page], limit, offset, total)


@bp.post("/api/claims/<cid>/price")
def price_claim(cid):
    require_roles(["RevenueIntegrityAnalyst"])
    claim = _get_claim_or_404(cid)
    if claim["pricing_status"] != "UNPRICED":
        raise err_invalid_state("Only an UNPRICED claim may be priced")
    # Pricing-chain preconditions (ERR_NO_MATCHING_TERM before ERR_CLAIM_HAS_NO_LINES /
    # ERR_MISSING_DRG_WEIGHT) are enforced inside run_pricing.
    run_pricing(claim, "PROSPECTIVE")
    reevaluate_claim_after_change(claim)
    return success_object(serialize_claim(claim))


@bp.post("/api/claims/<cid>/reprice")
def reprice_claim(cid):
    require_roles(["RevenueIntegrityAnalyst"])
    claim = _get_claim_or_404(cid)
    if claim["pricing_status"] not in {"PRICED", "REPRICED"}:
        raise err_invalid_state("Only a PRICED or REPRICED claim may be repriced")
    run_pricing(claim, "RETROSPECTIVE")
    reevaluate_claim_after_change(claim, restate_original=True)
    return success_object(serialize_claim(claim))

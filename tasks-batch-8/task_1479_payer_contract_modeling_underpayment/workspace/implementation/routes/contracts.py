"""PayerContract endpoints (PRD §3.1)."""

from flask import Blueprint, request

import db as _db
from db import parse_date
from errors import (
    err_not_found,
    err_invalid_state,
    err_invalid_request,
    err_payer_inactive,
    err_prior_contract_mismatch,
    err_contract_window_invalid,
    err_contract_window_overlap,
    err_duplicate_contract_code,
    err_invalid_rate_parameters,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_contract
from services.validation import body, reject_unknown, as_str, as_int, as_date, as_list
from services.pricing import touch

bp = Blueprint("contracts", __name__)

SERVICE_CATEGORIES = {
    "INPATIENT_MEDICAL", "INPATIENT_SURGICAL", "OUTPATIENT_SURGERY",
    "EMERGENCY", "OBSERVATION", "IMAGING", "LAB",
}


def _validate_volume_tiers(tiers):
    """Each entry: {service_category, min_annual_units, rate_adjustment_bp};
    mins strictly increasing per category; rate_adjustment_bp in [-2000, 2000]."""
    if tiers is None:
        return []
    if not isinstance(tiers, list):
        raise err_invalid_request("volume_tiers must be a list")
    by_cat = {}
    for entry in tiers:
        if not isinstance(entry, dict):
            raise err_invalid_request("volume_tiers entries must be objects")
        extra = set(entry.keys()) - {"service_category", "min_annual_units", "rate_adjustment_bp"}
        if extra:
            raise err_invalid_request(f"Unknown volume_tiers fields: {sorted(extra)}")
        cat = entry.get("service_category")
        if cat not in SERVICE_CATEGORIES:
            raise err_invalid_rate_parameters("volume_tiers.service_category invalid")
        mau = entry.get("min_annual_units")
        if isinstance(mau, bool) or not isinstance(mau, int) or mau < 0:
            raise err_invalid_rate_parameters("volume_tiers.min_annual_units invalid")
        bp = entry.get("rate_adjustment_bp")
        if isinstance(bp, bool) or not isinstance(bp, int) or bp < -2000 or bp > 2000:
            raise err_invalid_rate_parameters("volume_tiers.rate_adjustment_bp must be in [-2000, 2000]")
        prev = by_cat.setdefault(cat, [])
        if prev and mau <= prev[-1]:
            raise err_invalid_rate_parameters("volume_tiers min_annual_units must be strictly increasing per service_category")
        prev.append(mau)
        by_cat[cat] = prev
    return tiers


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval intersection: at least one shared calendar date."""
    return a_start <= b_end and b_start <= a_end


def _check_window_overlap(payer_id, effective, expiration, prior_contract_id, exclude_id=None):
    """Same-payer windows may not share a date unless renewal-linked via prior_contract_id;
    renewal-linked pairs may share at most one boundary date."""
    eff = parse_date(effective)
    exp = parse_date(expiration)
    for other in _db.store.contracts.values():
        if other["payer_id"] != payer_id or other["id"] == exclude_id:
            continue
        o_eff = parse_date(other["effective_date"])
        o_exp = parse_date(other["expiration_date"])
        if not _windows_overlap(eff, exp, o_eff, o_exp):
            continue
        # Renewal-linked? either direction
        linked = (
            prior_contract_id == other["id"]
            or other.get("prior_contract_id") == exclude_id
        )
        if not linked:
            raise err_contract_window_overlap()
        # Renewal-linked: may share at most one boundary date
        shared_start = max(eff, o_eff)
        shared_end = min(exp, o_exp)
        shared_days = (shared_end - shared_start).days + 1
        if shared_days > 1:
            raise err_contract_window_overlap(
                "Renewal-linked contract windows may share at most one boundary date"
            )


@bp.post("/api/payer-contracts")
def create_contract():
    require_roles(["ContractAnalyst"])
    data = body()
    reject_unknown(data, {
        "payer_id", "contract_code", "effective_date", "expiration_date",
        "prior_contract_id", "payment_terms_days", "underpayment_threshold_cents",
        "underpayment_threshold_bp", "volume_tiers",
    })
    payer_id = as_str(data, "payer_id")
    contract_code = as_str(data, "contract_code")
    effective = as_date(data, "effective_date")
    expiration = as_date(data, "expiration_date")
    if parse_date(effective) > parse_date(expiration):
        raise err_invalid_request("effective_date must be <= expiration_date")
    prior_contract_id = data.get("prior_contract_id")
    if prior_contract_id is not None and not isinstance(prior_contract_id, str):
        raise err_invalid_request("prior_contract_id must be a string")
    payment_terms_days = as_int(data, "payment_terms_days", required=False, min_value=0)
    if payment_terms_days is None:
        payment_terms_days = 30
    threshold_cents = as_int(data, "underpayment_threshold_cents", required=False, min_value=0)
    if threshold_cents is None:
        threshold_cents = 5000
    threshold_bp = as_int(data, "underpayment_threshold_bp", required=False, min_value=0, max_value=10000)
    if threshold_bp is None:
        threshold_bp = 100
    volume_tiers = _validate_volume_tiers(as_list(data, "volume_tiers", required=False))

    # Existence (rung 4)
    payer = _db.store.payers.get(payer_id)
    if payer is None:
        raise err_not_found("Payer not found")
    prior = None
    if prior_contract_id is not None:
        prior = _db.store.contracts.get(prior_contract_id)
        if prior is None:
            raise err_not_found("prior_contract_id not found")

    # Cross-entity (rung 8)
    if payer["status"] != "ACTIVE":
        raise err_payer_inactive()
    if prior is not None and prior["payer_id"] != payer_id:
        raise err_prior_contract_mismatch()

    # Temporal (rung 9)
    _check_window_overlap(payer_id, effective, expiration, prior_contract_id)

    # Uniqueness (rung 10)
    for c in _db.store.contracts.values():
        if c["payer_id"] == payer_id and c["contract_code"] == contract_code:
            raise err_duplicate_contract_code()

    now = _db.now_iso()
    contract = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "payer_id": payer_id,
        "contract_code": contract_code,
        "effective_date": effective,
        "expiration_date": expiration,
        "prior_contract_id": prior_contract_id,
        "payment_terms_days": payment_terms_days,
        "underpayment_threshold_cents": threshold_cents,
        "underpayment_threshold_bp": threshold_bp,
        "volume_tiers": volume_tiers,
        "status": "DRAFT",
    }
    _db.store.contracts[contract["id"]] = contract
    return success_object(serialize_contract(contract), status=201)


@bp.get("/api/payer-contracts/<cid>")
def get_contract(cid):
    require_roles(ALL_ROLES)
    contract = _db.store.contracts.get(cid)
    if contract is None:
        raise err_not_found("Contract not found")
    return success_object(serialize_contract(contract))


@bp.get("/api/payer-contracts")
def list_contracts():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    payer_id = request.args.get("payer_id")
    prior_contract_id = request.args.get("prior_contract_id")
    status = request.args.get("status")
    if status is not None and status not in {"DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED", "SUPERSEDED"}:
        raise err_invalid_request("status filter invalid")
    items = list(_db.store.contracts.values())
    if payer_id is not None:
        items = [c for c in items if c["payer_id"] == payer_id]
    if prior_contract_id is not None:
        items = [c for c in items if c.get("prior_contract_id") == prior_contract_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_contract(c) for c in page], limit, offset, total)


def _get_contract_or_404(cid):
    contract = _db.store.contracts.get(cid)
    if contract is None:
        raise err_not_found("Contract not found")
    return contract


@bp.post("/api/payer-contracts/<cid>/activate")
def activate_contract(cid):
    require_roles(["ContractManager"])
    contract = _get_contract_or_404(cid)
    # State (rung 6): only DRAFT -> ACTIVE; terminal states reject every action
    if contract["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT contract may be activated")
    payer = _db.store.payers.get(contract["payer_id"])
    # Cross-entity (rung 8): payer must be ACTIVE
    if payer is None or payer["status"] != "ACTIVE":
        raise err_payer_inactive()
    # Activation requires expiration_date > today
    if parse_date(contract["expiration_date"]) <= _db.today():
        raise err_contract_window_invalid()

    contract["status"] = "ACTIVE"
    touch(contract)
    # Renewal cascade
    prior_id = contract.get("prior_contract_id")
    if prior_id:
        prior = _db.store.contracts.get(prior_id)
        if prior is not None and prior["status"] in {"ACTIVE", "SUSPENDED"}:
            prior["status"] = "SUPERSEDED"
            touch(prior)
    return success_object(serialize_contract(contract))


@bp.post("/api/payer-contracts/<cid>/suspend")
def suspend_contract(cid):
    require_roles(["ContractManager"])
    contract = _get_contract_or_404(cid)
    if contract["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE contract may be suspended")
    contract["status"] = "SUSPENDED"
    touch(contract)
    return success_object(serialize_contract(contract))


@bp.post("/api/payer-contracts/<cid>/resume")
def resume_contract(cid):
    require_roles(["ContractManager"])
    contract = _get_contract_or_404(cid)
    if contract["status"] != "SUSPENDED":
        raise err_invalid_state("Only a SUSPENDED contract may be resumed")
    if parse_date(contract["expiration_date"]) <= _db.today():
        raise err_contract_window_invalid()
    contract["status"] = "ACTIVE"
    touch(contract)
    return success_object(serialize_contract(contract))


@bp.post("/api/payer-contracts/<cid>/terminate")
def terminate_contract(cid):
    require_roles(["ContractManager"])
    contract = _get_contract_or_404(cid)
    if contract["status"] not in {"ACTIVE", "SUSPENDED"}:
        raise err_invalid_state("Only an ACTIVE or SUSPENDED contract may be terminated")
    contract["status"] = "TERMINATED"
    touch(contract)
    return success_object(serialize_contract(contract))

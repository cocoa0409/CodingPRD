"""NetworkAgreement endpoints (PRD §3.4)."""

from flask import Blueprint, request

import db as _db
from db import parse_date
from errors import (
    err_not_found,
    err_invalid_state,
    err_invalid_request,
    err_network_agreement_overlap,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_network_agreement
from services.validation import body, reject_unknown, as_str, as_int, as_date
from services.pricing import touch

bp = Blueprint("network_agreements", __name__)

NA_STATUSES = {"REGISTERED", "VERIFIED", "FLAGGED_SUSPECT", "RETIRED"}


@bp.post("/api/network-agreements")
def create_agreement():
    require_roles(["ContractAnalyst"])
    data = body()
    reject_unknown(data, {"payer_id", "network_name", "wrap_rate_bp", "precedence_rank", "effective_date", "expiration_date"})
    payer_id = as_str(data, "payer_id")
    network_name = as_str(data, "network_name")
    wrap_rate_bp = as_int(data, "wrap_rate_bp", required=True)
    if wrap_rate_bp <= 0 or wrap_rate_bp > 10000:
        raise err_invalid_request("wrap_rate_bp must be in (0, 10000]")
    precedence_rank = as_int(data, "precedence_rank", required=True)
    effective = as_date(data, "effective_date")
    expiration = as_date(data, "expiration_date")
    if parse_date(effective) > parse_date(expiration):
        raise err_invalid_request("effective_date must be <= expiration_date")

    payer = _db.store.payers.get(payer_id)
    if payer is None:
        raise err_not_found("Payer not found")

    # Overlap: same payer + network_name, non-RETIRED, closed-interval
    eff = parse_date(effective)
    exp = parse_date(expiration)
    for n in _db.store.network_agreements.values():
        if n["payer_id"] != payer_id or n["network_name"] != network_name:
            continue
        if n["status"] == "RETIRED":
            continue
        n_eff = parse_date(n["effective_date"])
        n_exp = parse_date(n["expiration_date"])
        if eff <= n_exp and n_eff <= exp:
            raise err_network_agreement_overlap()

    now = _db.now_iso()
    na = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "payer_id": payer_id,
        "network_name": network_name,
        "wrap_rate_bp": wrap_rate_bp,
        "precedence_rank": precedence_rank,
        "effective_date": effective,
        "expiration_date": expiration,
        "status": "REGISTERED",
    }
    _db.store.network_agreements[na["id"]] = na
    return success_object(serialize_network_agreement(na), status=201)


@bp.get("/api/network-agreements/<nid>")
def get_agreement(nid):
    require_roles(ALL_ROLES)
    na = _db.store.network_agreements.get(nid)
    if na is None:
        raise err_not_found("NetworkAgreement not found")
    return success_object(serialize_network_agreement(na))


@bp.get("/api/network-agreements")
def list_agreements():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    payer_id = request.args.get("payer_id")
    status = request.args.get("status")
    if status is not None and status not in NA_STATUSES:
        raise err_invalid_request("status filter invalid")
    items = list(_db.store.network_agreements.values())
    if payer_id is not None:
        items = [n for n in items if n["payer_id"] == payer_id]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    items.sort(key=lambda n: n["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_network_agreement(n) for n in page], limit, offset, total)


def _get_na_or_404(nid):
    na = _db.store.network_agreements.get(nid)
    if na is None:
        raise err_not_found("NetworkAgreement not found")
    return na


@bp.post("/api/network-agreements/<nid>/verify")
def verify_agreement(nid):
    require_roles(["ContractManager"])
    na = _get_na_or_404(nid)
    if na["status"] not in {"REGISTERED", "FLAGGED_SUSPECT"}:
        raise err_invalid_state("Only REGISTERED or FLAGGED_SUSPECT agreements may be verified")
    na["status"] = "VERIFIED"
    touch(na)
    return success_object(serialize_network_agreement(na))


@bp.post("/api/network-agreements/<nid>/flag_suspect")
def flag_agreement(nid):
    require_roles(["RevenueIntegrityAnalyst"])
    na = _get_na_or_404(nid)
    if na["status"] != "VERIFIED":
        raise err_invalid_state("Only a VERIFIED agreement may be flagged suspect")
    na["status"] = "FLAGGED_SUSPECT"
    touch(na)
    return success_object(serialize_network_agreement(na))


@bp.post("/api/network-agreements/<nid>/retire")
def retire_agreement(nid):
    require_roles(["ContractManager"])
    na = _get_na_or_404(nid)
    if na["status"] not in {"REGISTERED", "VERIFIED", "FLAGGED_SUSPECT"}:
        raise err_invalid_state("Agreement is already RETIRED")
    na["status"] = "RETIRED"
    touch(na)
    return success_object(serialize_network_agreement(na))

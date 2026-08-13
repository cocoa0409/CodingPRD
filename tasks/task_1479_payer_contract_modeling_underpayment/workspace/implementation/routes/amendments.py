"""RateAmendment endpoints (PRD §3.3)."""

from flask import Blueprint, request

import db as _db
from db import parse_date
from errors import (
    err_not_found,
    err_invalid_state,
    err_invalid_request,
    err_stale_contract_version,
    err_contract_not_active,
    err_sod_amendment,
    err_amendment_supersede_mismatch,
    err_amendment_out_of_term,
    err_invalid_rate_parameters,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_amendment
from services.validation import body, reject_unknown, as_str, as_int, as_date, as_list
from services.pricing import touch
from routes.contracts import SERVICE_CATEGORIES

bp = Blueprint("amendments", __name__)


def _validate_term_overrides(contract_id, overrides):
    """Non-empty list of {service_category, base_rate_cents?, percent_of_charge_bp?};
    categories must exist as ContractTerms on the contract; at least one rate field per entry."""
    if not isinstance(overrides, list) or not overrides:
        raise err_invalid_request("term_overrides must be a non-empty list")
    for ov in overrides:
        if not isinstance(ov, dict):
            raise err_invalid_request("term_overrides entries must be objects")
        extra = set(ov.keys()) - {"service_category", "base_rate_cents", "percent_of_charge_bp"}
        if extra:
            raise err_invalid_request(f"Unknown term_overrides fields: {sorted(extra)}")
        cat = ov.get("service_category")
        if cat not in SERVICE_CATEGORIES:
            raise err_invalid_request("term_overrides.service_category invalid")
        brc = ov.get("base_rate_cents")
        pct = ov.get("percent_of_charge_bp")
        if brc is not None and (isinstance(brc, bool) or not isinstance(brc, int) or brc < 0):
            raise err_invalid_request("base_rate_cents must be a non-negative integer")
        if pct is not None and (isinstance(pct, bool) or not isinstance(pct, int) or pct < 0 or pct > 10000):
            raise err_invalid_request("percent_of_charge_bp must be in [0, 10000]")
        if brc is None and pct is None:
            raise err_invalid_request("Each term_overrides entry must carry base_rate_cents or percent_of_charge_bp")
        # Category must exist as a term on the contract
        exists = any(
            t["contract_id"] == contract_id and t["service_category"] == cat
            for t in _db.store.terms.values()
        )
        if not exists:
            raise err_invalid_rate_parameters(
                f"No ContractTerm exists for service_category {cat} on this contract"
            )
    return overrides


@bp.post("/api/rate-amendments")
def create_amendment():
    user_id, _ = require_roles(["ContractAnalyst", "ContractManager"])
    data = body()
    reject_unknown(data, {
        "contract_id", "effective_date", "term_overrides",
        "retroactive_to_date", "supersedes_amendment_id", "expected_contract_version",
    })
    contract_id = as_str(data, "contract_id")
    effective_date = as_date(data, "effective_date")
    retroactive_to_date = as_date(data, "retroactive_to_date", required=False)
    supersedes_amendment_id = data.get("supersedes_amendment_id")
    if supersedes_amendment_id is not None and not isinstance(supersedes_amendment_id, str):
        raise err_invalid_request("supersedes_amendment_id must be a string")
    expected_contract_version = as_int(data, "expected_contract_version", required=True)

    # Existence (rung 4)
    contract = _db.store.contracts.get(contract_id)
    if contract is None:
        raise err_not_found("Contract not found")
    prior = None
    if supersedes_amendment_id is not None:
        prior = _db.store.amendments.get(supersedes_amendment_id)
        if prior is None:
            raise err_not_found("supersedes_amendment_id not found")

    # OCC (rung 5)
    if expected_contract_version != contract["version"]:
        raise err_stale_contract_version()

    # State (rung 6): contract ACTIVE or SUSPENDED
    if contract["status"] not in {"ACTIVE", "SUSPENDED"}:
        raise err_invalid_state("Amendment creation requires contract ACTIVE or SUSPENDED")

    # Cross-entity (rung 8)
    if prior is not None and prior["contract_id"] != contract_id:
        raise err_amendment_supersede_mismatch()

    # Temporal (rung 9): effective_date within term; retroactive within [contract.effective, effective]
    eff = parse_date(effective_date)
    if not (parse_date(contract["effective_date"]) <= eff <= parse_date(contract["expiration_date"])):
        raise err_amendment_out_of_term("effective_date outside the contract term")
    if retroactive_to_date is not None:
        retro = parse_date(retroactive_to_date)
        if retro > eff or retro < parse_date(contract["effective_date"]):
            raise err_amendment_out_of_term(
                "retroactive_to_date must lie within [contract.effective_date, amendment.effective_date]"
            )

    # Uniqueness/consistency (rung 10)
    overrides = _validate_term_overrides(contract_id, data.get("term_overrides"))

    now = _db.now_iso()
    amendment = {
        "id": _db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": _db.store.next_seq(),
        "contract_id": contract_id,
        "supersedes_amendment_id": supersedes_amendment_id,
        "effective_date": effective_date,
        "retroactive_to_date": retroactive_to_date,
        "term_overrides": overrides,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
    }
    _db.store.amendments[amendment["id"]] = amendment

    # Void the contract's prior pending amendment(s)
    for other in _db.store.amendments.values():
        if (
            other["id"] != amendment["id"]
            and other["contract_id"] == contract_id
            and other["status"] in {"DRAFT", "APPROVED"}
        ):
            other["status"] = "VOIDED"
            touch(other)

    # Bump contract version
    touch(contract)

    return success_object(serialize_amendment(amendment), status=201)


@bp.get("/api/rate-amendments/<aid>")
def get_amendment(aid):
    require_roles(ALL_ROLES)
    a = _db.store.amendments.get(aid)
    if a is None:
        raise err_not_found("RateAmendment not found")
    return success_object(serialize_amendment(a))


@bp.get("/api/rate-amendments")
def list_amendments():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    contract_id = request.args.get("contract_id")
    supersedes_amendment_id = request.args.get("supersedes_amendment_id")
    status = request.args.get("status")
    if status is not None and status not in {"DRAFT", "APPROVED", "EFFECTIVE", "SUPERSEDED", "VOIDED"}:
        raise err_invalid_request("status filter invalid")
    items = list(_db.store.amendments.values())
    if contract_id is not None:
        items = [a for a in items if a["contract_id"] == contract_id]
    if supersedes_amendment_id is not None:
        items = [a for a in items if a.get("supersedes_amendment_id") == supersedes_amendment_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_amendment(a) for a in page], limit, offset, total)


@bp.post("/api/rate-amendments/<aid>/approve")
def approve_amendment(aid):
    user_id, _ = require_roles(["ContractManager"])
    a = _db.store.amendments.get(aid)
    if a is None:
        raise err_not_found("RateAmendment not found")
    # State (rung 6): amendment DRAFT; contract ACTIVE
    if a["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT amendment may be approved")
    contract = _db.store.contracts.get(a["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise err_contract_not_active()
    # SoD (rung 7)
    if a["created_by_user_id"] == user_id:
        raise err_sod_amendment()
    a["status"] = "APPROVED"
    a["approved_by_user_id"] = user_id
    touch(a)
    return success_object(serialize_amendment(a))


@bp.post("/api/rate-amendments/<aid>/void")
def void_amendment(aid):
    require_roles(["ContractManager"])
    a = _db.store.amendments.get(aid)
    if a is None:
        raise err_not_found("RateAmendment not found")
    if a["status"] not in {"DRAFT", "APPROVED"}:
        raise err_invalid_state("Only a DRAFT or APPROVED amendment may be voided")
    a["status"] = "VOIDED"
    touch(a)
    return success_object(serialize_amendment(a))

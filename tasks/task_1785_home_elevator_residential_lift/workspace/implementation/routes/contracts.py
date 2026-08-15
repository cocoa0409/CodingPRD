"""ServiceContract endpoints (PRD 3.7): tier-derived terms, OCC-guarded
re-tiering, activate/suspend/resume/terminate."""

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_CONTRACT_ALREADY_EXISTS, ERR_CONTRACT_NOT_FOUND,
    ERR_CONTRACT_STATE_FORBIDS, ERR_STALE_CONTRACT_VERSION,
    ERR_UNIT_NOT_FOUND, ERR_UNIT_NOT_IN_SERVICE, state_forbids,
)
from middleware import PROJECT_COORDINATOR, ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint
from services import calc
from util import get_json_body, serialize, validate_body

bp = Blueprint("contracts", __name__)

TIERS = ["BASIC", "STANDARD", "PREMIUM"]

CREATE_SPEC = {
    "unit_id": ("string", True, None),
    "tier": ("enum", True, TIERS),
    "contract_year_start": ("datetime", True, None),
}

PATCH_SPEC = {
    "tier": ("enum", True, TIERS),
    "expected_contract_version": ("int", True, None),
}


def _apply_tier(rec, tier):
    terms = calc.CONTRACT_TIERS[tier]
    rec["tier"] = tier
    rec["annual_fee"] = terms["annual_fee"]
    rec["included_visits"] = terms["included_visits"]
    rec["entrapment_sla_minutes"] = terms["entrapment_sla_minutes"]


@bp.post("/api/service-contracts")
@require_roles(PROJECT_COORDINATOR)
def create_contract():
    vals = validate_body(get_json_body(), CREATE_SPEC)
    unit = get_or_404(db.units, vals["unit_id"], ERR_UNIT_NOT_FOUND, "Unit")
    rec = db.new_record({
        "unit_id": unit["id"],
        "tier": vals["tier"],
        "annual_fee": None,
        "included_visits": None,
        "visits_consumed": 0,
        "entrapment_sla_minutes": None,
        "contract_year_start": vals["contract_year_start"],
        "status": "DRAFT",
    })
    _apply_tier(rec, vals["tier"])
    db.contracts[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/service-contracts")
@require_roles(*ALL_ROLES)
def list_contracts():
    return list_endpoint(db.contracts, {"unit_id": "unit_id", "tier": "tier", "status": "status"})


@bp.get("/api/service-contracts/<contractId>")
@require_roles(*ALL_ROLES)
def get_contract(contractId):
    rec = get_or_404(db.contracts, contractId, ERR_CONTRACT_NOT_FOUND, "ServiceContract")
    return ok(serialize(rec))


@bp.patch("/api/service-contracts/<contractId>")
@require_roles(PROJECT_COORDINATOR)
def patch_contract(contractId):
    rec = get_or_404(db.contracts, contractId, ERR_CONTRACT_NOT_FOUND, "ServiceContract")
    vals = validate_body(get_json_body(), PATCH_SPEC)
    # state admission (priority 5): re-tiering only while DRAFT
    if rec["status"] != "DRAFT":
        raise state_forbids(ERR_CONTRACT_STATE_FORBIDS, "ServiceContract")
    # optimistic concurrency (PRD 2.6)
    if vals["expected_contract_version"] != rec["version"]:
        raise ApiError(ERR_STALE_CONTRACT_VERSION, 412, "Contract version has advanced since the client's last read")
    _apply_tier(rec, vals["tier"])
    db.touch(rec)
    return ok(serialize(rec))


@bp.post("/api/service-contracts/<contractId>/activate")
@require_roles(PROJECT_COORDINATOR)
def activate_contract(contractId):
    rec = get_or_404(db.contracts, contractId, ERR_CONTRACT_NOT_FOUND, "ServiceContract")
    if rec["status"] != "DRAFT":
        raise state_forbids(ERR_CONTRACT_STATE_FORBIDS, "ServiceContract")
    # unit must be IN_SERVICE (priority 8)
    unit = db.units.get(rec["unit_id"])
    if unit is None or unit["equipment_status"] != "IN_SERVICE":
        raise ApiError(ERR_UNIT_NOT_IN_SERVICE, 409, "Activation requires the unit to be IN_SERVICE")
    # one live (ACTIVE/SUSPENDED) contract per unit (priority 9)
    if any(
        c["unit_id"] == rec["unit_id"] and c["id"] != rec["id"] and c["status"] in ("ACTIVE", "SUSPENDED")
        for c in db.contracts.values()
    ):
        raise ApiError(ERR_CONTRACT_ALREADY_EXISTS, 409, "Unit already has an ACTIVE or SUSPENDED service contract")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return ok(serialize(rec))


@bp.post("/api/service-contracts/<contractId>/suspend")
@require_roles(PROJECT_COORDINATOR)
def suspend_contract(contractId):
    rec = get_or_404(db.contracts, contractId, ERR_CONTRACT_NOT_FOUND, "ServiceContract")
    if rec["status"] != "ACTIVE":
        raise state_forbids(ERR_CONTRACT_STATE_FORBIDS, "ServiceContract")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return ok(serialize(rec))


@bp.post("/api/service-contracts/<contractId>/resume")
@require_roles(PROJECT_COORDINATOR)
def resume_contract(contractId):
    rec = get_or_404(db.contracts, contractId, ERR_CONTRACT_NOT_FOUND, "ServiceContract")
    if rec["status"] != "SUSPENDED":
        raise state_forbids(ERR_CONTRACT_STATE_FORBIDS, "ServiceContract")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return ok(serialize(rec))


@bp.post("/api/service-contracts/<contractId>/terminate")
@require_roles(PROJECT_COORDINATOR)
def terminate_contract(contractId):
    rec = get_or_404(db.contracts, contractId, ERR_CONTRACT_NOT_FOUND, "ServiceContract")
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise state_forbids(ERR_CONTRACT_STATE_FORBIDS, "ServiceContract")
    rec["status"] = "TERMINATED"
    db.touch(rec)
    # attached OPEN/DISPATCHED service calls detach to ad-hoc
    for call in db.service_calls.values():
        if call.get("contract_id") == rec["id"] and call["status"] in ("OPEN", "DISPATCHED"):
            call["contract_id"] = None
            db.touch(call)
    return ok(serialize(rec))

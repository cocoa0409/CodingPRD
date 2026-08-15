"""Contracts (PRD §3.1)."""

from flask import Blueprint, request

from db import store
from errors import (
    conflict,
    ERR_INVALID_STATE_TRANSITION,
    ERR_GROWER_NOT_ACTIVE,
    ERR_SITE_NOT_ACTIVE,
    ERR_CONTRACT_NOT_YET_EFFECTIVE,
    ERR_CONTRACT_EXPIRED,
    ERR_CONTRACT_NOT_EXPIRED,
    ERR_CONTRACT_SITE_OVERLAP,
    ERR_CONTRACT_HAS_ACTIVE_GROUPS,
    ERR_SETTLEMENTS_PENDING,
)
from middleware import require_roles, ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER
from response import success_object, paginate
from services.core import (
    new_record, touch, ser_contract, GROUP_ACTIVE_STATUSES,
    SETTLEMENT_PENDING_STATUSES,
)
from util import get_body, req, opt, as_str, as_int, as_num, as_date, load_or_404

bp = Blueprint("contracts", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER]


@bp.route("/contracts", methods=["POST"])
def create_contract():
    require_roles([ROLE_INTEGRATOR_ADMIN])
    body = get_body()
    # body FK existence, left-to-right: grower_id then site_id (priority 4)
    grower_id = as_str(req(body, "grower_id"), "grower_id")
    load_or_404(store.growers, grower_id, "Grower")
    site_id = as_str(req(body, "site_id"), "site_id")
    load_or_404(store.sites, site_id, "Site")
    base_pay = as_int(req(body, "base_pay_cents_per_head"), "base_pay_cents_per_head", 0)
    bonus_cap = as_int(req(body, "bonus_cap_cents_per_head"), "bonus_cap_cents_per_head", 0)
    fcr_target = as_num(req(body, "fcr_target"), "fcr_target", 0, exclusive_minimum=True)
    adg_target = as_num(req(body, "adg_target_lbs"), "adg_target_lbs", 0, exclusive_minimum=True)
    mort_thresh = as_num(req(body, "mortality_threshold_pct"), "mortality_threshold_pct", 0)
    feed_budget = as_int(req(body, "feed_budget_lbs_per_head"), "feed_budget_lbs_per_head", 0)
    structural = as_int(opt(body, "structural_owner_pct"), "structural_owner_pct", 0, 100) \
        if opt(body, "structural_owner_pct") is not None else 100
    equipment = as_int(opt(body, "equipment_owner_pct"), "equipment_owner_pct", 0, 100) \
        if opt(body, "equipment_owner_pct") is not None else 50
    routine = as_int(opt(body, "routine_owner_pct"), "routine_owner_pct", 0, 100) \
        if opt(body, "routine_owner_pct") is not None else 0
    effective = as_date(req(body, "effective_date"), "effective_date")
    expiry = as_date(req(body, "expiry_date"), "expiry_date")
    rec = new_record()
    rec.update({
        "grower_id": grower_id, "site_id": site_id,
        "base_pay_cents_per_head": base_pay,
        "bonus_cap_cents_per_head": bonus_cap,
        "fcr_target": fcr_target, "adg_target_lbs": adg_target,
        "mortality_threshold_pct": mort_thresh,
        "feed_budget_lbs_per_head": feed_budget,
        "structural_owner_pct": structural,
        "equipment_owner_pct": equipment,
        "routine_owner_pct": routine,
        "effective_date": effective, "expiry_date": expiry,
        "contract_status": "DRAFT",
    })
    store.contracts[rec["id"]] = rec
    return success_object(ser_contract(rec), 201)


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    require_roles(ROLES_READ)
    grower_id = request.args.get("grower_id")
    site_id = request.args.get("site_id")
    status = request.args.get("contract_status")
    items = list(store.contracts.values())
    if grower_id is not None:
        items = [c for c in items if c["grower_id"] == grower_id]
    if site_id is not None:
        items = [c for c in items if c["site_id"] == site_id]
    if status is not None:
        items = [c for c in items if c["contract_status"] == status]
    return paginate(items, request.args, ser_contract)


@bp.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require_roles(ROLES_READ)
    return success_object(ser_contract(load_or_404(store.contracts, cid, "Contract")))


@bp.route("/contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    contract = load_or_404(store.contracts, cid, "Contract")
    if contract["contract_status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot activate a contract in {contract['contract_status']}")
    grower = store.growers.get(contract["grower_id"])
    if grower is None or grower["grower_status"] != "ACTIVE":
        raise conflict(ERR_GROWER_NOT_ACTIVE, "Grower is not ACTIVE")
    site = store.sites.get(contract["site_id"])
    if site is None or site["site_status"] != "ACTIVE":
        raise conflict(ERR_SITE_NOT_ACTIVE, "Site is not ACTIVE")
    clock_date = store.now().date()
    if clock_date < contract["effective_date"]:
        raise conflict(ERR_CONTRACT_NOT_YET_EFFECTIVE,
                       "Clock date is before the contract effective_date")
    if clock_date > contract["expiry_date"]:
        raise conflict(ERR_CONTRACT_EXPIRED, "Clock date is past the contract expiry_date")
    for c in store.contracts.values():
        if (c["id"] != cid and c["site_id"] == contract["site_id"]
                and c["contract_status"] == "ACTIVE"):
            raise conflict(ERR_CONTRACT_SITE_OVERLAP,
                           "Another contract covering this site is already ACTIVE")
    contract["contract_status"] = "ACTIVE"
    touch(contract)
    return success_object(ser_contract(contract))


def _contract_exit_blockers(contract):
    """Shared terminate/expire blockers: live groups first, then pending settlements."""
    for g in store.pig_groups.values():
        if g["contract_id"] == contract["id"] and g["group_status"] in GROUP_ACTIVE_STATUSES:
            raise conflict(ERR_CONTRACT_HAS_ACTIVE_GROUPS,
                           "Contract has pig groups still SCHEDULED, PLACED, or MARKETING")
    for s in store.settlements.values():
        if s["contract_id"] == contract["id"] and s["settlement_status"] in SETTLEMENT_PENDING_STATUSES:
            raise conflict(ERR_SETTLEMENTS_PENDING,
                           "Contract has settlements still FINALIZED, DISPUTED, or APPROVED")


@bp.route("/contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    contract = load_or_404(store.contracts, cid, "Contract")
    if contract["contract_status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot terminate a contract in {contract['contract_status']}")
    _contract_exit_blockers(contract)
    contract["contract_status"] = "TERMINATED"
    touch(contract)
    return success_object(ser_contract(contract))


@bp.route("/contracts/<cid>/expire", methods=["POST"])
def expire_contract(cid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    contract = load_or_404(store.contracts, cid, "Contract")
    if contract["contract_status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot expire a contract in {contract['contract_status']}")
    # temporal gate precedes the blockers (priority 9 < 11)
    if store.now().date() <= contract["expiry_date"]:
        raise conflict(ERR_CONTRACT_NOT_EXPIRED,
                       "Clock date has not passed the contract expiry_date")
    _contract_exit_blockers(contract)
    contract["contract_status"] = "EXPIRED"
    touch(contract)
    return success_object(ser_contract(contract))

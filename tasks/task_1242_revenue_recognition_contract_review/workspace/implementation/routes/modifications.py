from flask import Blueprint

from db import STORE, make_rec, mark, sort_created
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE_TRANSITION, ERR_CONTRACT_NOT_ACTIVE,
                    ERR_STALE_VERSION, ERR_SOD_VIOLATION, ERR_INVALID_AMOUNT,
                    ERR_NO_PENDING_POB, ERR_OVER_RECOGNITION)
from response import ok_object, ok_list
import serializers as ser
import services as svc
from clock import CLOCK
from validate import require_roles, body, req_enum, req_int, req_date, opt_str

bp = Blueprint("modifications", __name__)

MOD_TYPES = {"CUMULATIVE_CATCH_UP", "PROSPECTIVE", "SEPARATE_CONTRACT"}
ALL_READ = ("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")


def get_contract_or_404(contract_id):
    c = STORE.contracts.get(contract_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "contract id does not identify an existing contract")
    return c


def get_mod_or_404(modification_id):
    m = STORE.modifications.get(modification_id)
    if m is None:
        raise ApiError(ERR_NOT_FOUND, 404, "modification_id does not identify an existing modification")
    return m


@bp.post("/revrec/contracts/<contract_id>/modifications")
def create_modification(contract_id):
    uid = require_roles("RevenueAccountant")
    c = get_contract_or_404(contract_id)
    data = body()
    mod_type = req_enum(data, "mod_type", MOD_TYPES)
    delta = req_int(data, "delta_fixed_consideration_cents")
    eff = req_date(data, "effective_date")
    if "expected_contract_version" not in data or data.get("expected_contract_version") is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_contract_version is required")
    expected = data.get("expected_contract_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_contract_version must be an integer")
    reason = opt_str(data, "reason")
    # Tier 4: optimistic concurrency, before state checks.
    if expected != c["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_contract_version does not equal the contract's current version")
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "modifications may be proposed only against ACTIVE contracts")
    if delta == 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "delta_fixed_consideration_cents must be non-zero")
    rec = make_rec(STORE.modifications, {
        "contract_id": contract_id,
        "mod_type": mod_type,
        "delta_fixed_consideration_cents": delta,
        "effective_date": eff.isoformat(),
        "reason": reason,
        "proposed_by_user_id": uid,
        "approved_by_user_id": None,
        "spawned_contract_id": None,
        "status": "PROPOSED",
    })
    mark(c)  # proposing a modification is itself a contract mutation
    return ok_object(ser.modification(rec), 201)


@bp.get("/revrec/contracts/<contract_id>/modifications")
def list_modifications(contract_id):
    require_roles(*ALL_READ)
    get_contract_or_404(contract_id)
    items = sort_created([m for m in STORE.modifications.values() if m["contract_id"] == contract_id])
    return ok_list([ser.modification(m) for m in items], len(items) or 1, 0, len(items))


@bp.post("/revrec/modifications/<modification_id>/approve")
def approve_modification(modification_id):
    uid = require_roles("RevenueManager")
    m = get_mod_or_404(modification_id)
    if m["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "approve requires the modification to be PROPOSED")
    c = get_contract_or_404(m["contract_id"])
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "modification approval requires the contract to be ACTIVE")
    if uid == m["proposed_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 409, "the approver must differ from the proposer")

    mod_type = m["mod_type"]
    delta = m["delta_fixed_consideration_cents"]
    spawned = None
    alloc = catch_ups = None
    pending_shares = None

    if mod_type == "CUMULATIVE_CATCH_UP":
        svc.require_open_period(CLOCK.today())
        alloc, catch_ups = svc.plan_catch_ups(c, c["fixed_consideration_cents"] + delta, c["vc_estimate_cents"])
        if svc.check_over_recognition(c, alloc):
            raise ApiError(ERR_OVER_RECOGNITION, 422,
                           "reallocation would leave an obligation below its recognized amount")
    elif mod_type == "PROSPECTIVE":
        pendings = [p for p in svc.pobs_of(c["id"]) if p["status"] == "PENDING"]
        if not pendings:
            raise ApiError(ERR_NO_PENDING_POB, 422,
                           "a PROSPECTIVE modification requires at least one PENDING obligation")
        pending_shares = svc.compute_allocation(pendings, delta)
        new_amounts = {p["id"]: p["allocated_amount_cents"] + pending_shares[p["id"]] for p in pendings}
        for p in svc.live_pobs(c["id"]):
            if new_amounts.get(p["id"], p["allocated_amount_cents"]) < svc.pob_recognized(p["id"]):
                raise ApiError(ERR_OVER_RECOGNITION, 422,
                               "reallocation would leave an obligation below its recognized amount")

    # Commit.
    m["status"] = "APPROVED"
    m["approved_by_user_id"] = uid
    mark(m)
    if mod_type in ("CUMULATIVE_CATCH_UP", "PROSPECTIVE"):
        c["fixed_consideration_cents"] += delta
    if mod_type == "CUMULATIVE_CATCH_UP":
        for p in svc.live_pobs(c["id"]):
            if p["allocated_amount_cents"] != alloc[p["id"]]:
                p["allocated_amount_cents"] = alloc[p["id"]]
                mark(p)
        for p, amount in catch_ups:
            svc.post_entry(c, p, "CATCH_UP_ADJUSTMENT", "MODIFICATION", amount, CLOCK.today())
    elif mod_type == "PROSPECTIVE":
        for p in [p for p in svc.pobs_of(c["id"]) if p["status"] == "PENDING"]:
            p["allocated_amount_cents"] += pending_shares[p["id"]]
            mark(p)
    else:  # SEPARATE_CONTRACT: original contract's consideration unchanged
        spawned = make_rec(STORE.contracts, {
            "customer_id": c["customer_id"],
            "contract_ref": f"SPAWNED-{modification_id}",
            "signed_date": m["effective_date"],
            "risk_tier": c["risk_tier"],
            "package_negotiated_flag": False,
            "combined_into_contract_id": None,
            "fixed_consideration_cents": delta,
            "vc_estimate_cents": 0,
            "active_vc_estimate_id": None,
            "status": "DRAFT",
            "completed_at": None,
        })
        m["spawned_contract_id"] = spawned["id"]
    mark(c)  # approving a modification bumps the owning contract's version
    return ok_object(ser.modification(m))


@bp.post("/revrec/modifications/<modification_id>/reject")
def reject_modification(modification_id):
    require_roles("RevenueManager")
    m = get_mod_or_404(modification_id)
    if m["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "reject requires the modification to be PROPOSED")
    m["status"] = "REJECTED"
    mark(m)
    return ok_object(ser.modification(m))

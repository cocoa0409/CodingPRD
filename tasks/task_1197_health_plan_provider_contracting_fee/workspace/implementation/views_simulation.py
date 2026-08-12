"""Simulation batches and claims: claim accumulation, pricing, scoring, and
the reopen compensation."""

from flask import Blueprint

import store
from bodycheck import DATE, INT, STR, validate_body
from envelope import ok, ok_list
from errors import ApiError
from helpers import get_batch, get_version, sorted_by_created
from pricing import (
    PASS_THRESHOLD_BPS, price_claim_line, recompute_batch_counters,
)
from security import ALL_ROLES, ROLE_CONFIG_ANALYST, auth, require_roles

bp = Blueprint("simulation", __name__)


def _batch_invalid_state(action):
    return ApiError(
        "ERR_BATCH_INVALID_STATE", 409,
        f"SimulationBatch state does not permit {action}.",
    )


def _parent_contract_id(batch):
    version = store.versions.get(batch["contract_version_id"])
    return version["contract_id"] if version else None


@bp.get("/simulation-batches/<bid>")
def get_one_batch(bid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    return ok(dict(get_batch(bid)))


@bp.post("/simulation-batches/<bid>/claims")
def create_claim(bid):
    data = validate_body({
        "hcpcs_code": (STR, True),
        "service_category": (STR, True),
        "service_date": (DATE, True),
        "billed_cents": (INT, True),
        "expected_allowed_cents": (INT, True),
        "los_days": (INT, False),
    })
    _, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    batch = get_batch(bid)
    if batch["batch_status"] != "OPEN":
        raise _batch_invalid_state("claim creation (requires OPEN)")
    claim = store.stamp_new({
        "simulation_batch_id": bid,
        "hcpcs_code": data["hcpcs_code"],
        "service_category": data["service_category"],
        "service_date": data["service_date"],
        "billed_cents": data["billed_cents"],
        "los_days": data["los_days"] if data["los_days"] is not None else 1,
        "expected_allowed_cents": data["expected_allowed_cents"],
        "priced_allowed_cents": None,
        "claim_outcome": "PENDING",
    })
    store.claims[claim["id"]] = claim
    recompute_batch_counters(batch)
    store.touch(batch)
    return ok(dict(claim), 201)


@bp.get("/simulation-batches/<bid>/claims")
def list_claims(bid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_batch(bid)
    items = [c for c in store.claims.values() if c["simulation_batch_id"] == bid]
    return ok_list([dict(c) for c in sorted_by_created(items)])


@bp.post("/simulation-batches/<bid>/price")
def price_batch(bid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    batch = get_batch(bid)
    if batch["batch_status"] != "OPEN":
        raise _batch_invalid_state("price (requires OPEN)")
    version = get_version(batch["contract_version_id"])
    contract = store.contracts.get(version["contract_id"])
    pending = sorted_by_created(
        c for c in store.claims.values()
        if c["simulation_batch_id"] == bid and c["claim_outcome"] == "PENDING"
    )
    for claim in pending:
        priced, outcome = price_claim_line(claim, version, contract)
        claim["priced_allowed_cents"] = priced
        claim["claim_outcome"] = outcome
        store.touch(claim)
    recompute_batch_counters(batch)
    batch["batch_status"] = "PRICED"
    store.touch(batch)
    return ok(dict(batch))


@bp.post("/simulation-batches/<bid>/score")
def score_batch(bid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    batch = get_batch(bid)
    if batch["batch_status"] != "PRICED":
        raise _batch_invalid_state("score (requires PRICED)")
    if batch["total_claims"] < 1:
        raise ApiError(
            "ERR_BATCH_EMPTY", 422,
            "Cannot score a batch with zero claims.",
        )
    matched = batch["matched_claims"]
    priced_count = batch["matched_claims"] + batch["mismatched_claims"]
    contract_id = _parent_contract_id(batch)
    if matched * 10000 >= priced_count * PASS_THRESHOLD_BPS:
        batch["batch_status"] = "PASSED"
        store.touch(batch)
        store.add_audit(contract_id, "SIMULATION_PASSED", role, user_id,
                        "Simulation batch scored PASSED.")
    else:
        batch["batch_status"] = "FAILED"
        store.touch(batch)
        store.add_audit(contract_id, "SIMULATION_FAILED", role, user_id,
                        "Simulation batch scored FAILED.")
    return ok(dict(batch))


@bp.post("/simulation-batches/<bid>/reopen")
def reopen_batch(bid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    batch = get_batch(bid)
    if batch["batch_status"] != "FAILED":
        raise _batch_invalid_state("reopen (requires FAILED)")
    # Compensation: every resolved claim reverts to PENDING with price reset.
    for claim in store.claims.values():
        if claim["simulation_batch_id"] != bid:
            continue
        if claim["claim_outcome"] in ("MATCH", "MISMATCH", "EXCLUDED"):
            claim["claim_outcome"] = "PENDING"
            claim["priced_allowed_cents"] = None
            store.touch(claim)
    batch["batch_status"] = "OPEN"
    recompute_batch_counters(batch)
    store.touch(batch)
    return ok(dict(batch))

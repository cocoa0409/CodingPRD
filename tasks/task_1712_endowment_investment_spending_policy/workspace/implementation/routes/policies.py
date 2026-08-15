from flask import Blueprint

from constants import ALL_ROLES
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services.domain import get_or_404, list_response, pool_gate
from util import new_id, parse_body, req_str, req_int, is_int

bp = Blueprint("policies", __name__)


@bp.route("/endowment/policies", methods=["POST"])
def create_policy():
    user_id, _ = authenticate(["InvestmentOfficer"])
    body = parse_body(required=True)
    pool_id = req_str(body, "pool_id")
    rate = req_int(body, "spending_rate_bps")
    window = req_int(body, "smoothing_window_quarters")
    band_floor = req_int(body, "band_floor_bps")
    band_cap = req_int(body, "band_cap_bps")
    effective = req_int(body, "effective_from_fiscal_year")

    pool = get_or_404(store.pools, pool_id, "EndowmentPool")
    pool_gate(pool, "policy_create")

    if not (100 <= rate <= 2000):
        raise_err(
            "ERR_POLICY_PARAM_OUT_OF_RANGE",
            "spending_rate_bps must be between 100 and 2000",
        )
    if not (4 <= window <= 20):
        raise_err(
            "ERR_POLICY_PARAM_OUT_OF_RANGE",
            "smoothing_window_quarters must be between 4 and 20",
        )
    if not (0 <= band_floor <= 10000):
        raise_err(
            "ERR_POLICY_PARAM_OUT_OF_RANGE",
            "band_floor_bps must be between 0 and 10000",
        )
    if not (0 <= band_cap <= 10000):
        raise_err(
            "ERR_POLICY_PARAM_OUT_OF_RANGE",
            "band_cap_bps must be between 0 and 10000",
        )

    rec = {
        "id": new_id(),
        "pool_id": pool_id,
        "spending_rate_bps": rate,
        "smoothing_window_quarters": window,
        "band_floor_bps": band_floor,
        "band_cap_bps": band_cap,
        "effective_from_fiscal_year": effective,
        "policy_status": "DRAFT",
        "proposed_by_user_id": user_id,
        "adopted_by_user_id": None,
        "version": 1,
    }
    stamp_new(rec)
    store.policies[rec["id"]] = rec
    return success(pub(rec), status=201)


@bp.route("/endowment/policies", methods=["GET"])
def list_policies():
    authenticate(ALL_ROLES)
    return list_response(
        store.policies,
        [("pool_id", "pool_id", "str"), ("policy_status", "policy_status", "str")],
    )


@bp.route("/endowment/policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.policies, policy_id, "SpendingPolicyVersion")))


@bp.route("/endowment/policies/<policy_id>/adopt", methods=["POST"])
def adopt_policy(policy_id):
    user_id, _ = authenticate(["BoardMember"])
    policy = store.policies.get(policy_id)
    # Priority 3 (segregation of duties) outranks body shape (4) and
    # existence (5); it is evaluable only when the record exists.
    if policy is not None and user_id == policy["proposed_by_user_id"]:
        raise_err(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "The adopter must differ from the policy's proposer",
        )
    body = parse_body(required=True)
    expected = req_int(body, "expected_pool_version")
    if policy is None:
        raise_err("ERR_NOT_FOUND", f"SpendingPolicyVersion not found: {policy_id}")
    if policy["policy_status"] != "DRAFT":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot adopt a policy in state {policy['policy_status']}",
        )
    pool = store.pools.get(policy["pool_id"])
    pool_gate(pool, "policy_adopt")
    if expected != pool["version"]:
        raise_err(
            "ERR_STALE_POOL_VERSION",
            "expected_pool_version does not match the pool's current version",
        )
    adopted_siblings = [
        p
        for p in store.policies.values()
        if p["pool_id"] == pool["id"] and p["policy_status"] == "ADOPTED"
    ]
    for sib in adopted_siblings:
        if policy["effective_from_fiscal_year"] <= sib["effective_from_fiscal_year"]:
            raise_err(
                "ERR_WINDOW_CONFLICT",
                "Adopted policies must form a strictly increasing sequence of "
                "effective_from_fiscal_year values",
            )
    # Supersede the previously latest ADOPTED policy, if any.
    if adopted_siblings:
        adopted_siblings.sort(
            key=lambda p: (p["effective_from_fiscal_year"], p["created_at"], p["_seq"])
        )
        latest = adopted_siblings[-1]
        latest["policy_status"] = "SUPERSEDED"
        bump(latest)
    policy["policy_status"] = "ADOPTED"
    policy["adopted_by_user_id"] = user_id
    bump(policy)
    bump(pool)
    return success(pub(policy))


@bp.route("/endowment/policies/<policy_id>/withdraw", methods=["POST"])
def withdraw_policy(policy_id):
    authenticate(["InvestmentOfficer"])
    policy = get_or_404(store.policies, policy_id, "SpendingPolicyVersion")
    if policy["policy_status"] != "DRAFT":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot withdraw a policy in state {policy['policy_status']}",
        )
    pool = store.pools.get(policy["pool_id"])
    if pool is not None and pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )
    policy["policy_status"] = "WITHDRAWN"
    bump(policy)
    return success(pub(policy))

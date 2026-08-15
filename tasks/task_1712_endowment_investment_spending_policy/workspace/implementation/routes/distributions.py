from flask import Blueprint

from constants import ALL_ROLES, QUARTERS_PER_FISCAL_YEAR
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services import calc
from services.domain import get_or_404, list_response, pool_gate, is_exempt
from services.pipeline import emit_ledger, refresh_fund_mv, _exception_exit_posture
from services.spending import (
    compute_distribution,
    approved_exception_for,
    applicable_policy,
)
from util import new_id, parse_body, req_str, req_int

bp = Blueprint("distributions", __name__)


def _current_fiscal_year(pool):
    return pool["inception_fiscal_year"] + (
        pool["current_quarter_index"] // QUARTERS_PER_FISCAL_YEAR
    )


def _terminated_gate(pool):
    if pool is not None and pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )


@bp.route("/endowment/distributions", methods=["POST"])
def create_distribution():
    authenticate(["DevelopmentOfficer"])
    body = parse_body(required=True)
    fund_id = req_str(body, "fund_id")
    fiscal_year = req_int(body, "fiscal_year")

    fund = get_or_404(store.funds, fund_id, "Fund")
    if fund["fund_status"] != "ACTIVE":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            "Distribution creation requires an ACTIVE fund",
        )
    pool = store.pools.get(fund["pool_id"])
    pool_gate(pool, "distribution_create")

    duplicate = any(
        d["fund_id"] == fund_id
        and d["fiscal_year"] == fiscal_year
        and d["distribution_status"] != "CANCELLED"
        for d in store.distributions.values()
    )
    if duplicate:
        raise_err(
            "ERR_DUPLICATE_RECORD",
            f"A non-CANCELLED distribution already exists for this fund and "
            f"fiscal year {fiscal_year}",
        )

    current_fy = _current_fiscal_year(pool)
    if not (pool["inception_fiscal_year"] <= fiscal_year <= current_fy + 1):
        raise_err(
            "ERR_WINDOW_CONFLICT",
            f"fiscal_year must lie between {pool['inception_fiscal_year']} and "
            f"{current_fy + 1}",
        )

    # Applicable-policy lookup (raises ERR_NO_APPLICABLE_POLICY when absent).
    applicable_policy(pool, fiscal_year)

    rec = {
        "id": new_id(),
        "fund_id": fund_id,
        "fiscal_year": fiscal_year,
        "distribution_status": "PROJECTED",
        "policy_id": None,
        "smoothed_base_cents": 0,
        "raw_amount_cents": 0,
        "prior_year_distribution_cents": None,
        "band_adjusted_amount_cents": 0,
        "was_underwater_at_proposal": False,
        "applied_exception_id": None,
        "final_amount_cents": 0,
        "distributed_amount_cents": 0,
        "units_redeemed_micro": None,
        "proposed_by_user_id": None,
        "approved_by_user_id": None,
        "_distributed_epoch": None,
        "version": 1,
    }
    stamp_new(rec)
    store.distributions[rec["id"]] = rec
    compute_distribution(rec, fund, pool)
    return success(pub(rec), status=201)


@bp.route("/endowment/distributions", methods=["GET"])
def list_distributions():
    authenticate(ALL_ROLES)
    return list_response(
        store.distributions,
        [
            ("fund_id", "fund_id", "str"),
            ("policy_id", "policy_id", "str"),
            ("applied_exception_id", "applied_exception_id", "str"),
            ("fiscal_year", "fiscal_year", "int"),
            ("distribution_status", "distribution_status", "str"),
        ],
    )


@bp.route("/endowment/distributions/<distribution_id>", methods=["GET"])
def get_distribution(distribution_id):
    authenticate(ALL_ROLES)
    return success(
        pub(get_or_404(store.distributions, distribution_id, "SpendingDistribution"))
    )


@bp.route("/endowment/distributions/<distribution_id>/propose", methods=["POST"])
def propose_distribution(distribution_id):
    user_id, _ = authenticate(["DevelopmentOfficer"])
    dist = get_or_404(store.distributions, distribution_id, "SpendingDistribution")
    if dist["distribution_status"] != "PROJECTED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot propose a distribution in state {dist['distribution_status']}",
        )
    fund = store.funds.get(dist["fund_id"])
    if fund is None or fund["fund_status"] != "ACTIVE":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            "Distribution propose requires an ACTIVE fund",
        )
    pool = store.pools.get(fund["pool_id"])
    pool_gate(pool, "distribution_propose")
    compute_distribution(dist, fund, pool)
    dist["applied_exception_id"] = None
    dist["distribution_status"] = "PROPOSED"
    dist["proposed_by_user_id"] = user_id
    bump(dist)
    return success(pub(dist))


@bp.route(
    "/endowment/distributions/<distribution_id>/request_revision", methods=["POST"]
)
def request_revision(distribution_id):
    authenticate(["BoardMember"])
    dist = get_or_404(store.distributions, distribution_id, "SpendingDistribution")
    if dist["distribution_status"] != "PROPOSED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot request revision on a distribution in state "
            f"{dist['distribution_status']}",
        )
    fund = store.funds.get(dist["fund_id"])
    _terminated_gate(store.pools.get(fund["pool_id"]) if fund else None)
    dist["distribution_status"] = "REVISION_REQUESTED"
    bump(dist)
    return success(pub(dist))


@bp.route("/endowment/distributions/<distribution_id>/repropose", methods=["POST"])
def repropose_distribution(distribution_id):
    user_id, _ = authenticate(["DevelopmentOfficer"])
    dist = get_or_404(store.distributions, distribution_id, "SpendingDistribution")
    if dist["distribution_status"] != "REVISION_REQUESTED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot repropose a distribution in state "
            f"{dist['distribution_status']}",
        )
    fund = store.funds.get(dist["fund_id"])
    pool = store.pools.get(fund["pool_id"]) if fund else None
    pool_gate(pool, "distribution_repropose")
    compute_distribution(dist, fund, pool)
    dist["applied_exception_id"] = None
    dist["distribution_status"] = "PROPOSED"
    dist["proposed_by_user_id"] = user_id
    bump(dist)
    return success(pub(dist))


@bp.route("/endowment/distributions/<distribution_id>/approve", methods=["POST"])
def approve_distribution(distribution_id):
    user_id, _ = authenticate(["BoardMember"])
    dist = store.distributions.get(distribution_id)
    # Priority 3 (segregation of duties) before existence (5) where evaluable.
    if dist is not None and user_id == dist.get("proposed_by_user_id"):
        raise_err(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "The approver must differ from the distribution's proposer",
        )
    if dist is None:
        raise_err(
            "ERR_NOT_FOUND", f"SpendingDistribution not found: {distribution_id}"
        )
    if dist["distribution_status"] != "PROPOSED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot approve a distribution in state {dist['distribution_status']}",
        )
    fund = store.funds.get(dist["fund_id"])
    pool = store.pools.get(fund["pool_id"])
    pool_gate(pool, "distribution_approve")

    if fund["is_underwater"] and not is_exempt(fund, pool):
        exc = approved_exception_for(fund, dist["fiscal_year"])
        if exc is None:
            raise_err(
                "ERR_UNDERWATER_SPENDING_BLOCKED",
                "Approving a distribution for an underwater, non-exempt fund "
                "requires an APPROVED policy exception",
            )

    exc = compute_distribution(dist, fund, pool)
    dist["applied_exception_id"] = exc["id"] if exc is not None else None
    dist["distribution_status"] = "APPROVED"
    dist["approved_by_user_id"] = user_id
    bump(dist)
    return success(pub(dist))


@bp.route("/endowment/distributions/<distribution_id>/distribute", methods=["POST"])
def distribute_distribution(distribution_id):
    authenticate(["InvestmentOfficer"])
    dist = get_or_404(store.distributions, distribution_id, "SpendingDistribution")
    if dist["distribution_status"] != "APPROVED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot distribute a distribution in state "
            f"{dist['distribution_status']}",
        )
    fund = store.funds.get(dist["fund_id"])
    pool = store.pools.get(fund["pool_id"])
    pool_gate(pool, "distribution_distribute")

    if dist["final_amount_cents"] <= 0:
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            "Distribution requires a final_amount_cents strictly greater than 0",
        )
    units = calc.units_for_amount(
        dist["final_amount_cents"], pool["current_unit_price_millicents"]
    )
    if units > fund["units_held_micro"]:
        raise_err(
            "ERR_INSUFFICIENT_UNITS",
            "Redemption requires more units than the fund holds",
        )

    dist["units_redeemed_micro"] = units
    dist["distributed_amount_cents"] = dist["final_amount_cents"]
    dist["distribution_status"] = "DISTRIBUTED"
    dist["_distributed_epoch"] = pool["current_quarter_index"]
    fund["units_held_micro"] -= units
    pool["total_units_outstanding_micro"] -= units
    open_quarter = pool["current_quarter_index"] + 1
    emit_ledger(
        fund["id"],
        open_quarter,
        "DISTRIBUTION_REDEEM",
        -units,
        -dist["final_amount_cents"],
        dist["id"],
    )
    bump(dist)
    bump(fund)
    bump(pool)
    refresh_fund_mv(fund, pool["current_unit_price_millicents"])

    if dist.get("applied_exception_id"):
        exc = store.exceptions.get(dist["applied_exception_id"])
        if exc is not None and exc["exception_status"] == "APPROVED":
            exc["exception_status"] = "EXERCISED"
            bump(exc)
            _exception_exit_posture(exc)
    return success(pub(dist))


@bp.route("/endowment/distributions/<distribution_id>/cancel", methods=["POST"])
def cancel_distribution(distribution_id):
    user_id, role = authenticate(["DevelopmentOfficer", "BoardMember"])
    dist = get_or_404(store.distributions, distribution_id, "SpendingDistribution")
    status = dist["distribution_status"]
    was_approved = False
    if status in ("PROJECTED", "PROPOSED", "REVISION_REQUESTED"):
        pass
    elif status == "APPROVED":
        if role != "BoardMember":
            raise_err(
                "ERR_INVALID_STATE_TRANSITION",
                "Only a BoardMember may cancel an APPROVED distribution",
            )
        has_payouts = any(
            p["distribution_id"] == dist["id"] for p in store.payouts.values()
        )
        if has_payouts:
            raise_err(
                "ERR_INVALID_STATE_TRANSITION",
                "An APPROVED distribution with payouts may not be cancelled",
            )
        was_approved = True
    else:
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot cancel a distribution in state {status}",
        )
    fund = store.funds.get(dist["fund_id"])
    _terminated_gate(store.pools.get(fund["pool_id"]) if fund else None)

    dist["distribution_status"] = "CANCELLED"
    bump(dist)
    if was_approved and dist.get("applied_exception_id"):
        exc = store.exceptions.get(dist["applied_exception_id"])
        if exc is not None and exc["exception_status"] == "APPROVED":
            exc["exception_status"] = "RESCINDED"
            bump(exc)
            _exception_exit_posture(exc)
    return success(pub(dist))

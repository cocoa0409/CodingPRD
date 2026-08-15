from flask import Blueprint

from constants import ALL_ROLES, PROGRAM_PURPOSES
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services.domain import get_or_404, list_response, pool_gate
from util import new_id, parse_body, req_str, req_int, req_enum

bp = Blueprint("payouts", __name__)


@bp.route("/endowment/payouts", methods=["POST"])
def create_payout():
    authenticate(["DevelopmentOfficer"])
    body = parse_body(required=True)
    distribution_id = req_str(body, "distribution_id")
    program_code = req_str(body, "program_code")
    program_purpose = req_enum(body, "program_purpose", PROGRAM_PURPOSES)
    allocated = req_int(body, "allocated_amount_cents", minv=1)

    dist = get_or_404(store.distributions, distribution_id, "SpendingDistribution")
    if dist["distribution_status"] != "DISTRIBUTED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            "Payout creation requires a DISTRIBUTED distribution",
        )
    fund = store.funds.get(dist["fund_id"])
    pool = store.pools.get(fund["pool_id"]) if fund else None
    pool_gate(pool, "payout_create")

    # Donor-restriction compliance.
    if (
        fund["purpose_restriction"] != "UNRESTRICTED"
        and program_purpose != fund["purpose_restriction"]
    ):
        raise_err(
            "ERR_PURPOSE_MISMATCH",
            "program_purpose must equal the fund's purpose_restriction unless "
            "the fund is UNRESTRICTED",
        )

    # Aggregate cap across the distribution's payouts.
    committed = sum(
        p["allocated_amount_cents"]
        for p in store.payouts.values()
        if p["distribution_id"] == dist["id"]
    )
    if committed + allocated > dist["distributed_amount_cents"]:
        raise_err(
            "ERR_ALLOCATION_EXCEEDS_DISTRIBUTION",
            "Payout allocations would exceed the distribution's "
            "distributed_amount_cents",
        )

    rec = {
        "id": new_id(),
        "distribution_id": distribution_id,
        "program_code": program_code,
        "program_purpose": program_purpose,
        "allocated_amount_cents": allocated,
        "payout_status": "SCHEDULED",
        "disbursed_quarter_index": None,
        "spent_amount_cents": 0,
        "unspent_amount_cents": allocated,
        "swept_gift_id": None,
        "version": 1,
    }
    stamp_new(rec)
    store.payouts[rec["id"]] = rec
    return success(pub(rec), status=201)


@bp.route("/endowment/payouts", methods=["GET"])
def list_payouts():
    authenticate(ALL_ROLES)
    return list_response(
        store.payouts,
        [
            ("distribution_id", "distribution_id", "str"),
            ("swept_gift_id", "swept_gift_id", "str"),
            ("payout_status", "payout_status", "str"),
        ],
    )


@bp.route("/endowment/payouts/<payout_id>", methods=["GET"])
def get_payout(payout_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.payouts, payout_id, "ProgramPayout")))


@bp.route("/endowment/payouts/<payout_id>/disburse", methods=["POST"])
def disburse_payout(payout_id):
    authenticate(["DevelopmentOfficer"])
    payout = get_or_404(store.payouts, payout_id, "ProgramPayout")
    if payout["payout_status"] != "SCHEDULED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot disburse a payout in state {payout['payout_status']}",
        )
    dist = store.distributions.get(payout["distribution_id"])
    if dist is None or dist["distribution_status"] != "DISTRIBUTED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            "Payout disbursement requires a DISTRIBUTED distribution",
        )
    fund = store.funds.get(dist["fund_id"]) if dist else None
    pool = store.pools.get(fund["pool_id"]) if fund else None
    pool_gate(pool, "payout_disburse")

    payout["payout_status"] = "DISBURSED"
    payout["disbursed_quarter_index"] = pool["current_quarter_index"] + 1
    payout["unspent_amount_cents"] = (
        payout["allocated_amount_cents"] - payout["spent_amount_cents"]
    )
    bump(payout)
    return success(pub(payout))


@bp.route("/endowment/payouts/<payout_id>/report_spending", methods=["POST"])
def report_spending(payout_id):
    authenticate(["ProgramManager"])
    body = parse_body(required=True)
    spent = req_int(body, "spent_amount_cents", minv=0)
    payout = get_or_404(store.payouts, payout_id, "ProgramPayout")
    if payout["payout_status"] != "DISBURSED":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot report spending on a payout in state "
            f"{payout['payout_status']}",
        )
    dist = store.distributions.get(payout["distribution_id"])
    fund = store.funds.get(dist["fund_id"]) if dist else None
    pool = store.pools.get(fund["pool_id"]) if fund else None
    if pool is not None and pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )
    if spent < payout["spent_amount_cents"]:
        raise_err(
            "ERR_INVALID_SPENT_AMOUNT",
            "spent_amount_cents may not decrease",
        )
    if spent > payout["allocated_amount_cents"]:
        raise_err(
            "ERR_INVALID_SPENT_AMOUNT",
            "spent_amount_cents may not exceed allocated_amount_cents",
        )
    payout["spent_amount_cents"] = spent
    if spent == payout["allocated_amount_cents"]:
        payout["payout_status"] = "CLOSED_FULLY_SPENT"
        payout["unspent_amount_cents"] = 0
    else:
        payout["unspent_amount_cents"] = (
            payout["allocated_amount_cents"] - spent
        )
    bump(payout)
    return success(pub(payout))

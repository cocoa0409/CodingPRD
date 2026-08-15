from flask import Blueprint

from constants import ALL_ROLES, ENDOWMENT_CLASSES, PURPOSE_RESTRICTIONS, MIN_ENDOWMENT_CORPUS_CENTS
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services import calc
from services.domain import (
    get_or_404,
    list_response,
    pool_gate,
    is_term_matured,
)
from services.pipeline import emit_ledger, refresh_fund_mv
from util import new_id, parse_body, req_str, req_int, req_enum, opt_int_nullable

bp = Blueprint("funds", __name__)


@bp.route("/endowment/funds", methods=["POST"])
def create_fund():
    user_id, _ = authenticate(["DevelopmentOfficer"])
    body = parse_body(required=True)
    pool_id = req_str(body, "pool_id")
    fund_code = req_str(body, "fund_code")
    fund_name = req_str(body, "fund_name")
    endowment_class = req_enum(body, "endowment_class", ENDOWMENT_CLASSES)
    term_end = opt_int_nullable(body, "term_end_quarter_index", minv=1)
    purpose = req_enum(body, "purpose_restriction", PURPOSE_RESTRICTIONS)
    if endowment_class == "TERM_ENDOWMENT":
        if term_end is None:
            raise_err(
                "ERR_INVALID_REQUEST",
                "term_end_quarter_index is required for TERM_ENDOWMENT funds",
            )
    elif term_end is not None:
        raise_err(
            "ERR_INVALID_REQUEST",
            "term_end_quarter_index must be null for non-TERM_ENDOWMENT funds",
        )

    pool = get_or_404(store.pools, pool_id, "EndowmentPool")
    if pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )
    duplicate = any(
        f["pool_id"] == pool_id and f["fund_code"] == fund_code
        for f in store.funds.values()
    )
    if duplicate:
        raise_err(
            "ERR_DUPLICATE_RECORD",
            f"A fund with fund_code {fund_code} already exists in this pool",
        )

    rec = {
        "id": new_id(),
        "pool_id": pool_id,
        "fund_code": fund_code,
        "fund_name": fund_name,
        "endowment_class": endowment_class,
        "term_end_quarter_index": term_end,
        "purpose_restriction": purpose,
        "fund_status": "DRAFT",
        "spending_posture": "NORMAL",
        "historic_gift_value_cents": 0,
        "pledged_corpus_cents": 0,
        "units_held_micro": 0,
        "market_value_cents": 0,
        "is_underwater": False,
        "activated_quarter_index": None,
        "created_by_user_id": user_id,
        "version": 1,
    }
    stamp_new(rec)
    store.funds[rec["id"]] = rec
    return success(pub(rec), status=201)


@bp.route("/endowment/funds", methods=["GET"])
def list_funds():
    authenticate(ALL_ROLES)
    return list_response(
        store.funds,
        [
            ("pool_id", "pool_id", "str"),
            ("fund_status", "fund_status", "str"),
            ("spending_posture", "spending_posture", "str"),
        ],
    )


@bp.route("/endowment/funds/<fund_id>", methods=["GET"])
def get_fund(fund_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.funds, fund_id, "Fund")))


@bp.route("/endowment/funds/<fund_id>/activate", methods=["POST"])
def activate_fund(fund_id):
    authenticate(["DevelopmentOfficer"])
    fund = get_or_404(store.funds, fund_id, "Fund")
    if fund["fund_status"] != "DRAFT":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot activate a fund in state {fund['fund_status']}",
        )
    pool = store.pools.get(fund["pool_id"])
    pool_gate(pool, "fund_activate")
    if fund["pledged_corpus_cents"] < MIN_ENDOWMENT_CORPUS_CENTS:
        raise_err(
            "ERR_MINIMUM_FUNDING_NOT_MET",
            "pledged_corpus_cents is below the 5000000 activation minimum",
        )
    fund["fund_status"] = "ACTIVE"
    fund["activated_quarter_index"] = pool["current_quarter_index"] + 1
    bump(fund)
    return success(pub(fund))


@bp.route("/endowment/funds/<fund_id>/terminate", methods=["POST"])
def terminate_fund(fund_id):
    authenticate(["BoardMember"])
    fund = get_or_404(store.funds, fund_id, "Fund")
    if fund["fund_status"] != "ACTIVE":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot terminate a fund in state {fund['fund_status']}",
        )
    pool = store.pools.get(fund["pool_id"])
    if pool is not None and pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )
    if fund["units_held_micro"] != 0:
        raise_err(
            "ERR_NOT_TERMINABLE",
            "Fund termination requires zero units held",
        )
    open_gifts = any(
        g["fund_id"] == fund["id"] and g["gift_status"] in ("PLEDGED", "RECEIVED")
        for g in store.gifts.values()
    )
    if open_gifts:
        raise_err(
            "ERR_NOT_TERMINABLE",
            "Fund termination requires no PLEDGED or RECEIVED gifts",
        )
    fund_dist_ids = {
        d["id"] for d in store.distributions.values() if d["fund_id"] == fund["id"]
    }
    open_dists = any(
        d["fund_id"] == fund["id"]
        and d["distribution_status"]
        in ("PROJECTED", "PROPOSED", "REVISION_REQUESTED", "APPROVED")
        for d in store.distributions.values()
    )
    if open_dists:
        raise_err(
            "ERR_NOT_TERMINABLE",
            "Fund termination requires no non-terminal distributions",
        )
    open_payouts = any(
        p["distribution_id"] in fund_dist_ids
        and p["payout_status"] in ("SCHEDULED", "DISBURSED")
        for p in store.payouts.values()
    )
    if open_payouts:
        raise_err(
            "ERR_NOT_TERMINABLE",
            "Fund termination requires no SCHEDULED or DISBURSED payouts",
        )
    fund["fund_status"] = "TERMINATED"
    fund["spending_posture"] = "NORMAL"
    bump(fund)
    return success(pub(fund))


@bp.route("/endowment/funds/<fund_id>/redeem_corpus", methods=["POST"])
def redeem_corpus(fund_id):
    authenticate(["BoardMember"])
    body = parse_body(required=True)
    amount = req_int(body, "amount_cents", minv=1)
    fund = get_or_404(store.funds, fund_id, "Fund")
    if fund["fund_status"] != "ACTIVE":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot redeem corpus from a fund in state {fund['fund_status']}",
        )
    pool = store.pools.get(fund["pool_id"])
    pool_gate(pool, "fund_redeem_corpus")

    # Corpus inviolability: TRUE_ENDOWMENT and unmatured TERM_ENDOWMENT.
    if fund["endowment_class"] == "TRUE_ENDOWMENT" or (
        fund["endowment_class"] == "TERM_ENDOWMENT"
        and not is_term_matured(fund, pool)
    ):
        raise_err(
            "ERR_CORPUS_INVIOLABLE",
            "Corpus redemption is allowed only for QUASI_ENDOWMENT or "
            "matured TERM_ENDOWMENT funds",
        )

    units_needed = calc.units_for_amount(
        amount, pool["current_unit_price_millicents"]
    )
    if units_needed > fund["units_held_micro"]:
        raise_err(
            "ERR_INSUFFICIENT_UNITS",
            "Redemption requires more units than the fund holds",
        )

    fund["units_held_micro"] -= units_needed
    pool["total_units_outstanding_micro"] -= units_needed
    fund["historic_gift_value_cents"] = max(
        0, fund["historic_gift_value_cents"] - amount
    )
    open_quarter = pool["current_quarter_index"] + 1
    emit_ledger(
        fund["id"], open_quarter, "CORPUS_REDEEM", -units_needed, -amount, fund["id"]
    )
    bump(fund)
    bump(pool)
    refresh_fund_mv(fund, pool["current_unit_price_millicents"])
    return success(pub(fund))

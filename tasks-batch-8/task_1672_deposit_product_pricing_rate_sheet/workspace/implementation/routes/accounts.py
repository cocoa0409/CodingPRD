"""DepositAccount endpoints (PRD 3.5)."""

from datetime import date

from flask import Blueprint

from db import STORE, today
from errors import (
    ApiError,
    ERR_ACCOUNT_INVALID_STATE,
    ERR_PRODUCT_NOT_FOUND,
    ERR_PROMO_MIN_BALANCE_UNMET,
    ERR_PROMO_NOT_ENROLLABLE,
    ERR_PROMO_NOT_FOUND,
    ERR_SHEET_NOT_FOUND,
    ERR_STALE_VERSION,
    bad_request,
    not_found,
)
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from services.rates import (
    CHANNELS,
    recompute_account_rates,
    refresh_customer_enrollments,
    tiered_rate,
)
from utils import (
    bump,
    req_enum,
    req_int,
    req_str,
    round_half_up_int,
    stamp_new,
    today_iso,
)

bp = Blueprint("accounts", __name__)

LIFECYCLES = ("OPEN", "FROZEN", "CLOSED")
RATE_SOURCES = ("SHEET", "PROMO", "EXCEPTION", "GRANDFATHERED")
ACTIONS = ("FREEZE", "UNFREEZE", "CLOSE", "ENROLL_PROMO")


def _get_or_404(account_id):
    row = STORE["accounts"].get(account_id)
    if row is None:
        raise not_found("Deposit account not found")
    return row


def _effective_sheet_for(product_id, market_code):
    for s in STORE["sheets"].values():
        if (s["product_id"] == product_id and s["market_code"] == market_code
                and s["status"] == "EFFECTIVE"):
            return s
    return None


@bp.post("/deposit-accounts")
@require_roles("BranchBanker")
def open_account():
    data = get_body()
    customer_ref = req_str(data, "customer_ref")
    product_id = req_str(data, "product_id")
    market_code = req_str(data, "market_code")
    opening_balance = req_int(data, "opening_balance_cents", minimum=0)
    channel = req_enum(data, "channel", CHANNELS)
    product = STORE["products"].get(product_id)
    if product is None:
        raise ApiError(ERR_PRODUCT_NOT_FOUND, 422, "Referenced product_id does not exist")
    sheet = _effective_sheet_for(product_id, market_code)
    if sheet is None:
        raise ApiError(ERR_SHEET_NOT_FOUND, 422,
                       "No EFFECTIVE sheet exists for this product+market")
    tiso = today_iso()
    row = {
        "customer_ref": customer_ref,
        "product_id": product_id,
        "market_code": market_code,
        "sheet_id": sheet["id"],
        "balance_cents": opening_balance,
        "channel": channel,
        "lifecycle": "OPEN",
        "rate_source": "SHEET",
        "promo_offer_id": None,
        "promo_end_date": None,
        "exception_request_id": None,
        "exception_end_date": None,
        "base_rate_bp": 0,
        "bundle_bonus_bp": 0,
        "exception_rate_bp": None,
        "current_rate_bp": 0,
        "unposted_accrual_milli": 0,
        "posted_interest_cents": 0,
        "last_accrual_date": tiso,
        "opened_at": tiso,
    }
    stamp_new(row)
    STORE["accounts"][row["id"]] = row
    # The new OPEN account feeds the customer's combined relationship balance;
    # refresh enrollments first so its own bundle bonus sees the update.
    refresh_customer_enrollments(customer_ref, skip_bump_ids=(row["id"],))
    recompute_account_rates(row)
    return ok_object(serialize("accounts", row), 201)


@bp.get("/deposit-accounts")
@require_roles("BranchBanker", "PricingAnalyst", "PricingCommittee")
def list_accounts():
    from flask import request
    customer_ref = request.args.get("customer_ref")
    product_id = request.args.get("product_id")
    market_code = request.args.get("market_code")
    sheet_id = request.args.get("sheet_id")
    rate_source = query_enum("rate_source", RATE_SOURCES)
    lifecycle = query_enum("lifecycle", LIFECYCLES)
    promo_offer_id = request.args.get("promo_offer_id")
    exception_request_id = request.args.get("exception_request_id")
    rows = list(STORE["accounts"].values())
    if customer_ref is not None:
        rows = [r for r in rows if r["customer_ref"] == customer_ref]
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if market_code is not None:
        rows = [r for r in rows if r["market_code"] == market_code]
    if sheet_id is not None:
        rows = [r for r in rows if r["sheet_id"] == sheet_id]
    if rate_source is not None:
        rows = [r for r in rows if r["rate_source"] == rate_source]
    if lifecycle is not None:
        rows = [r for r in rows if r["lifecycle"] == lifecycle]
    if promo_offer_id is not None:
        rows = [r for r in rows if r["promo_offer_id"] == promo_offer_id]
    if exception_request_id is not None:
        rows = [r for r in rows if r["exception_request_id"] == exception_request_id]
    return paginate(serialize_many("accounts", rows))


@bp.get("/deposit-accounts/<account_id>")
@require_roles("BranchBanker", "PricingAnalyst", "PricingCommittee")
def get_account(account_id):
    return ok_object(serialize("accounts", _get_or_404(account_id)))


@bp.patch("/deposit-accounts/<account_id>")
@require_roles("BranchBanker")
def adjust_balance(account_id):
    data = get_body()
    expected = req_int(data, "expected_account_version")
    balance = req_int(data, "balance_cents", minimum=0)
    account = _get_or_404(account_id)
    if account["lifecycle"] == "CLOSED":
        raise ApiError(ERR_ACCOUNT_INVALID_STATE, 409,
                       "Cannot adjust the balance of a CLOSED account")
    if expected != account["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_account_version does not match the current version")
    account["balance_cents"] = balance
    recompute_account_rates(account)
    bump(account)
    # The balance change feeds combined_relationship_balance for this customer.
    refresh_customer_enrollments(
        account["customer_ref"], skip_bump_ids=(account["id"],)
    )
    return ok_object(serialize("accounts", account))


@bp.post("/deposit-accounts/<account_id>/actions")
@require_roles("BranchBanker")
def account_action(account_id):
    data = get_body()
    action = req_enum(data, "action", ACTIONS)
    promo_offer_id = None
    if action == "ENROLL_PROMO":
        promo_offer_id = req_str(data, "promo_offer_id")
    account = _get_or_404(account_id)
    offer = None
    if action == "ENROLL_PROMO":
        offer = STORE["promos"].get(promo_offer_id)
        if offer is None:
            raise ApiError(ERR_PROMO_NOT_FOUND, 422,
                           "Referenced promo_offer_id does not exist")
    if action == "FREEZE":
        if account["lifecycle"] != "OPEN":
            raise ApiError(ERR_ACCOUNT_INVALID_STATE, 409,
                           "Only an OPEN account may be frozen")
        account["lifecycle"] = "FROZEN"
    elif action == "UNFREEZE":
        if account["lifecycle"] != "FROZEN":
            raise ApiError(ERR_ACCOUNT_INVALID_STATE, 409,
                           "Only a FROZEN account may be unfrozen")
        account["lifecycle"] = "OPEN"
    elif action == "CLOSE":
        if account["lifecycle"] == "CLOSED":
            raise ApiError(ERR_ACCOUNT_INVALID_STATE, 409,
                           "Account is already CLOSED")
        account["lifecycle"] = "CLOSED"
    else:  # ENROLL_PROMO
        if account["lifecycle"] != "OPEN" or account["rate_source"] != "SHEET":
            raise ApiError(ERR_ACCOUNT_INVALID_STATE, 409,
                           "Promo enrollment requires an OPEN account on SHEET pricing")
        product = STORE["products"][account["product_id"]]
        if not product["allows_promos"]:
            raise bad_request("Product does not allow promotions")
        t = today()
        if (offer["status"] != "ACTIVE"
                or not (date.fromisoformat(offer["enrollment_start"]) <= t
                        <= date.fromisoformat(offer["enrollment_end"]))
                or offer["product_id"] != account["product_id"]
                or offer["market_code"] != account["market_code"]):
            raise ApiError(ERR_PROMO_NOT_ENROLLABLE, 422,
                           "Offer is not enrollable for this account")
        if account["balance_cents"] < offer["min_opening_balance_cents"]:
            raise ApiError(ERR_PROMO_MIN_BALANCE_UNMET, 422,
                           "Balance below the offer's minimum opening balance")
        account["rate_source"] = "PROMO"
        account["promo_offer_id"] = offer["id"]
        end = t.fromordinal(t.toordinal() + offer["promo_term_days"])
        account["promo_end_date"] = end.isoformat()
        recompute_account_rates(account)
    bump(account)
    if action == "CLOSE":
        # A CLOSED account drops out of combined_relationship_balance.
        refresh_customer_enrollments(
            account["customer_ref"], skip_bump_ids=(account["id"],)
        )
    return ok_object(serialize("accounts", account))


@bp.post("/deposit-accounts/<account_id>/interest-postings")
@require_roles("BranchBanker")
def post_interest(account_id):
    get_body()
    account = _get_or_404(account_id)
    if account["lifecycle"] == "CLOSED":
        raise ApiError(ERR_ACCOUNT_INVALID_STATE, 409,
                       "Cannot post interest on a CLOSED account")
    # Sum-then-round: milli-cents convert to cents exactly once, round half up.
    delta = round_half_up_int(account["unposted_accrual_milli"], 1000)
    account["posted_interest_cents"] += delta
    account["unposted_accrual_milli"] = 0
    account["last_accrual_date"] = today_iso()
    bump(account)
    return ok_object(serialize("accounts", account), 201)


@bp.get("/deposit-accounts/<account_id>/rate-quote")
@require_roles("BranchBanker", "PricingAnalyst")
def rate_quote(account_id):
    account = _get_or_404(account_id)
    if account["rate_source"] == "PROMO":
        offer = STORE["promos"].get(account["promo_offer_id"])
        stack_base = offer["promo_rate_bp"] if offer else account["base_rate_bp"]
        uncapped = stack_base
    elif account["rate_source"] == "EXCEPTION":
        uncapped = account["exception_rate_bp"] or 0
    else:
        uncapped = account["base_rate_bp"] + account["bundle_bonus_bp"]
    quote = {
        "account_id": account["id"],
        "rate_source": account["rate_source"],
        "base_rate_bp": account["base_rate_bp"],
        "bundle_bonus_bp": account["bundle_bonus_bp"],
        "exception_rate_bp": account["exception_rate_bp"],
        "cap_applied": uncapped > account["current_rate_bp"],
        "current_rate_bp": account["current_rate_bp"],
    }
    return ok_object(quote)

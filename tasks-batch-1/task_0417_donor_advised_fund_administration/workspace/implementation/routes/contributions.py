"""Contribution endpoints: record, settle (valuation + receipt), reject (PRD 3.3)."""
from flask import Blueprint, request

from db import (
    db, common_create_fields, audit_create_fields, touch, LOCK, next_receipt_number,
)
from errors import err
from middleware import get_identity, require_role, get_json_body, get_pagination, paginate
from response import object_response, array_response
from services import calc, serialize
from services.accounts import recompute_account, post_ledger
from services.lookup import (
    get_or_404, require_string, require_enum, optional_int, optional_bool,
    filtered_sorted,
)

bp = Blueprint("contributions", __name__)

RECORD_ROLES = {"DonorAdvisor", "ContributionAdmin"}
READ_ROLES = {"SponsorAdmin", "DonorAdvisor", "ContributionAdmin"}
ASSET_TYPES = {"CASH", "SECURITIES", "CRYPTO"}


@bp.post("/daf/contributions")
def record_contribution():
    _, role = get_identity()
    require_role(role, RECORD_ROLES)
    body = get_json_body()
    donor_account_id = require_string(body, "donor_account_id")
    asset_type = require_enum(body, "asset_type", ASSET_TYPES)

    # Body-shape: numeric pricing inputs, if present, must be well-formed.
    cash_amount_cents = optional_int(body, "cash_amount_cents", None)
    quantity_milli = optional_int(body, "quantity_milli", None)
    high_price_cents = optional_int(body, "high_price_cents", None)
    low_price_cents = optional_int(body, "low_price_cents", None)
    closing_price_cents = optional_int(body, "closing_price_cents", None)
    spot_price_cents = optional_int(body, "spot_price_cents", None)
    thinly_traded = optional_bool(body, "thinly_traded", False)
    ticker = body.get("ticker")
    if ticker is not None and not isinstance(ticker, str):
        raise err("ERR_INVALID_REQUEST")
    # A cash gift's amount, when supplied at record time, must be positive (PRD 3.3).
    if cash_amount_cents is not None and cash_amount_cents <= 0:
        raise err("ERR_INVALID_REQUEST")

    with LOCK:
        get_or_404(db.accounts, donor_account_id)  # body FK existence
        contribution = common_create_fields()
        contribution.update({
            "donor_account_id": donor_account_id,
            "asset_type": asset_type,
            "cash_amount_cents": cash_amount_cents,
            "ticker": ticker,
            "quantity_milli": quantity_milli,
            "high_price_cents": high_price_cents,
            "low_price_cents": low_price_cents,
            "closing_price_cents": closing_price_cents,
            "spot_price_cents": spot_price_cents,
            "thinly_traded": thinly_traded,
            "fair_market_value_cents": None,
            "status": "PENDING",
        })
        db.contributions[contribution["id"]] = contribution
    return object_response(serialize.contribution(contribution), status=201)


@bp.get("/daf/contributions/<contribution_id>")
def get_contribution(contribution_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    contribution = get_or_404(db.contributions, contribution_id)
    return object_response(serialize.contribution(contribution))


@bp.get("/daf/contributions")
def list_contributions():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.contributions, {
        "donor_account_id": request.args.get("donor_account_id"),
        "status": request.args.get("status"),
        "asset_type": request.args.get("asset_type"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.contribution(c) for c in page], meta)


@bp.post("/daf/contributions/<contribution_id>/settle")
def settle_contribution(contribution_id):
    _, role = get_identity()
    require_role(role, {"ContributionAdmin"})
    with LOCK:
        contribution = get_or_404(db.contributions, contribution_id)
        # State precedes business rules (PRD 3.10): only PENDING can settle.
        if contribution["status"] != "PENDING":
            raise err("ERR_INVALID_STATE")
        account = db.accounts[contribution["donor_account_id"]]
        # Account must be ACTIVE (PRD 3.3).
        if account["status"] != "ACTIVE":
            raise err("ERR_ACCOUNT_NOT_ACTIVE")
        # Required valuation inputs present (PRD 3.3), then whole-share quantity.
        _check_valuation_inputs(contribution)
        if contribution["asset_type"] == "SECURITIES":
            if contribution["quantity_milli"] % 1000 != 0:
                raise err("ERR_VALUATION_QUANTITY_INVALID")

        # Compute and stamp the irrevocable FMV.
        fmv = calc.contribution_fmv(contribution)
        contribution["fair_market_value_cents"] = fmv
        contribution["status"] = "SETTLED"
        touch(contribution)

        # Cascade: credit cash, append CONTRIBUTION_SETTLED ledger, recompute grantable.
        account["cash_balance_cents"] += fmv
        post_ledger(account, "CONTRIBUTION_SETTLED", fmv, "Contribution", contribution_id)
        recompute_account(account)
        touch(account)

        # Mint the SubstantiationReceipt (append-only: id + created_at only).
        sponsor = db.sponsors[account["sponsor_id"]]
        receipt = audit_create_fields()
        receipt.update({
            "contribution_id": contribution_id,
            "donor_account_id": account["id"],
            "receipt_number": next_receipt_number(),
            "deductible_value_cents": fmv,
            "asset_description": _asset_description(contribution),
            "issued_quarter_index": sponsor["current_quarter_index"],
        })
        db.receipts[receipt["id"]] = receipt
    return object_response(serialize.contribution(contribution))


@bp.post("/daf/contributions/<contribution_id>/reject")
def reject_contribution(contribution_id):
    _, role = get_identity()
    require_role(role, {"ContributionAdmin"})
    with LOCK:
        contribution = get_or_404(db.contributions, contribution_id)
        if contribution["status"] != "PENDING":
            raise err("ERR_INVALID_STATE")
        # status -> REJECTED; no valuation, no ledger, no receipt (PRD 3.3).
        contribution["status"] = "REJECTED"
        touch(contribution)
    return object_response(serialize.contribution(contribution))


def _check_valuation_inputs(contribution):
    asset_type = contribution["asset_type"]
    if asset_type == "CASH":
        if contribution["cash_amount_cents"] is None:
            raise err("ERR_VALUATION_INPUT_MISSING")
    elif asset_type == "SECURITIES":
        if contribution["quantity_milli"] is None:
            raise err("ERR_VALUATION_INPUT_MISSING")
        if contribution["thinly_traded"]:
            if contribution["closing_price_cents"] is None:
                raise err("ERR_VALUATION_INPUT_MISSING")
        else:
            if contribution["high_price_cents"] is None or contribution["low_price_cents"] is None:
                raise err("ERR_VALUATION_INPUT_MISSING")
    elif asset_type == "CRYPTO":
        if contribution["quantity_milli"] is None or contribution["spot_price_cents"] is None:
            raise err("ERR_VALUATION_INPUT_MISSING")


def _asset_description(contribution):
    asset_type = contribution["asset_type"]
    if asset_type == "CASH":
        return f"Cash contribution of {contribution['cash_amount_cents']} cents"
    qty = contribution.get("quantity_milli")
    ticker = contribution.get("ticker") or "UNKNOWN"
    if asset_type == "SECURITIES":
        return f"Securities: {qty} milli-shares of {ticker}"
    return f"Crypto: {qty} milli-units of {ticker}"

from flask import Blueprint

import errors
from db import DB, CLOCK, new_id, stamp_new, touch
from middleware import (
    get_context, require_role, get_json_body, require_fields, reject_unexpected,
    require_string, require_enum, require_int,
)
from response import success_object, no_content
from services import bids as bid_svc

bp = Blueprint("leveling", __name__)

TREATMENTS = {"GC_ALLOWANCE", "SUB_QUOTE", "EXCLUDED_SCOPE"}
UNLOCKED_PACKAGE_STATES = {"BIDDING_CLOSED", "TABULATED"}


def serialize_adjustment(adj):
    return {
        "id": adj["id"],
        "bid_id": adj["bid_id"],
        "description": adj["description"],
        "treatment": adj["treatment"],
        "amount_cents": adj["amount_cents"],
        "pct_of_base": adj["pct_of_base"],
        "resolved_amount_cents": adj["resolved_amount_cents"],
        "created_at": adj["created_at"],
        "updated_at": adj["updated_at"],
        "version": adj["version"],
    }


def get_adjustment_or_404(adj_id):
    adj = DB.leveling_adjustments.get(adj_id)
    if adj is None:
        raise errors.err_resource_not_found()
    return adj


def _check_leveling_unlocked(bid):
    """Bid must be SUBMITTED; package must be in BIDDING_CLOSED or TABULATED."""
    if bid["status"] != "SUBMITTED":
        raise errors.err_bid_invalid_state()
    pkg = DB.bid_packages.get(bid["bid_package_id"])
    if pkg is None or pkg["status"] not in UNLOCKED_PACKAGE_STATES:
        raise errors.err_leveling_locked()
    return pkg


def _validate_exactly_one(amount_cents, pct_of_base):
    if (amount_cents is None) == (pct_of_base is None):
        raise errors.err_invalid_request(
            "Exactly one of amount_cents / pct_of_base is required")
    if amount_cents is not None:
        if not isinstance(amount_cents, int) or isinstance(amount_cents, bool):
            raise errors.err_invalid_request("amount_cents must be an integer")
    if pct_of_base is not None:
        if not isinstance(pct_of_base, (int, float)) or isinstance(pct_of_base, bool):
            raise errors.err_invalid_request("pct_of_base must be a number")


@bp.post("/leveling-adjustments")
def create_adjustment():
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    body = get_json_body()
    reject_unexpected(body, {"bid_id", "description", "treatment", "amount_cents", "pct_of_base"})
    require_fields(body, ["bid_id", "description", "treatment"])
    bid_id = body["bid_id"]
    if not isinstance(bid_id, str):
        raise errors.err_invalid_request("bid_id must be a string")
    bid = DB.bids.get(bid_id)
    if bid is None:
        raise errors.err_bid_not_found()
    _check_leveling_unlocked(bid)
    description = require_string(body, "description")
    treatment = require_enum(body, "treatment", TREATMENTS)
    amount_cents = body.get("amount_cents")
    pct_of_base = body.get("pct_of_base")
    _validate_exactly_one(amount_cents, pct_of_base)

    adj = {
        "id": new_id(),
        "bid_id": bid_id,
        "description": description,
        "treatment": treatment,
        "amount_cents": amount_cents,
        "pct_of_base": pct_of_base,
        "resolved_amount_cents": 0,
    }
    stamp_new(adj)
    adj["_created_at_dt"] = CLOCK.now()
    adj["resolved_amount_cents"] = bid_svc.resolve_adjustment(adj, bid)
    DB.leveling_adjustments[adj["id"]] = adj
    return success_object(serialize_adjustment(adj), 201)


@bp.patch("/leveling-adjustments/<adj_id>")
def edit_adjustment(adj_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    adj = get_adjustment_or_404(adj_id)
    bid = DB.bids.get(adj["bid_id"])
    if bid is None:
        raise errors.err_bid_not_found()
    _check_leveling_unlocked(bid)
    body = get_json_body()
    reject_unexpected(body, {"description", "treatment", "amount_cents", "pct_of_base"})

    if "description" in body:
        adj["description"] = require_string(body, "description")
    if "treatment" in body:
        adj["treatment"] = require_enum(body, "treatment", TREATMENTS)
    if "amount_cents" in body or "pct_of_base" in body:
        new_amount = body.get("amount_cents") if "amount_cents" in body else adj["amount_cents"]
        new_pct = body.get("pct_of_base") if "pct_of_base" in body else adj["pct_of_base"]
        # Explicit null clears the field, so the other becomes the sole price input.
        if "amount_cents" in body and body["amount_cents"] is None:
            new_amount = None
        if "pct_of_base" in body and body["pct_of_base"] is None:
            new_pct = None
        _validate_exactly_one(new_amount, new_pct)
        adj["amount_cents"] = new_amount
        adj["pct_of_base"] = new_pct
    adj["resolved_amount_cents"] = bid_svc.resolve_adjustment(adj, bid)
    touch(adj)
    return success_object(serialize_adjustment(adj))


@bp.delete("/leveling-adjustments/<adj_id>")
def delete_adjustment(adj_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    adj = get_adjustment_or_404(adj_id)
    bid = DB.bids.get(adj["bid_id"])
    if bid is None:
        raise errors.err_bid_not_found()
    _check_leveling_unlocked(bid)
    del DB.leveling_adjustments[adj_id]
    return no_content()

"""Group purchasing contracts and vendor quote negotiation (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import lookups
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import CAPITAL_PLANNER, guard
from response import created_response, object_response
from services import cascades, pricing
from validation import (body, bool_field, dec_field, dt_field, int_field,
                        pagination, q_str, raw_ref, str_field)

bp = Blueprint("gpo", __name__)

WARRANTY_VALUES = (0, 12, 24)
QUOTE_STATES_OPEN = ("SUBMITTED", "COUNTERED", "ACCEPTED")
MAX_NEGOTIATION_ROUNDS = 3
SAFETY_REVIEW_THRESHOLD = Decimal("90.00")
QUOTABLE_REQUEST_STATES = ("SCORED", "IN_COMMITTEE", "APPROVED", "FUNDED")


def _warranty(data, key, required=True, default=None):
    value = int_field(data, key, 0, 24, required=required, default=default)
    if value is not None and value not in WARRANTY_VALUES:
        raise ApiError("ERR_VALIDATION")
    return value


# ------------------------------------------------------------- GpoContract

@bp.route("/capital/gpo-contracts", methods=["POST"])
@guard(CAPITAL_PLANNER)
def create_contract():
    data = body()
    contract_code = str_field(data, "contract_code", 2, 24)
    vendor_name = str_field(data, "vendor_name", 1, 120)
    small_pct = dec_field(data, "small_tier_pct", "0.00", "0.50", max_dp=4)
    mid_pct = dec_field(data, "mid_tier_pct", "0.00", "0.50", max_dp=4)
    large_pct = dec_field(data, "large_tier_pct", "0.00", "0.50", max_dp=4)
    mid_floor = int_field(data, "tier_mid_floor_cents", 1)
    large_floor = int_field(data, "tier_large_floor_cents", 1)
    addendum_pct = dec_field(data, "multi_unit_addendum_pct", "0.00", "0.20",
                             max_dp=4)
    trade_in_cap_pct = dec_field(data, "trade_in_cap_pct", "0.00", "0.50",
                                 max_dp=4)
    expires_raw, expires_on = dt_field(data, "expires_on")

    if large_floor <= mid_floor:
        raise ApiError("ERR_VALIDATION")

    for row in db.contracts.values():
        if row["contract_code"] == contract_code:
            raise ApiError("ERR_DUPLICATE_KEY")

    row = new_row({
        "contract_code": contract_code,
        "vendor_name": vendor_name,
        "small_tier_pct": small_pct,
        "mid_tier_pct": mid_pct,
        "large_tier_pct": large_pct,
        "tier_mid_floor_cents": mid_floor,
        "tier_large_floor_cents": large_floor,
        "multi_unit_addendum_pct": addendum_pct,
        "trade_in_cap_pct": trade_in_cap_pct,
        "expires_on": expires_raw,
        "_expires_on": expires_on,
    })
    db.contracts[row["id"]] = row
    return created_response(serializers.contract(row))


@bp.route("/capital/gpo-contracts/<contract_id>", methods=["PATCH"])
@guard(CAPITAL_PLANNER)
def patch_contract(contract_id):
    contract = lookups.contract(contract_id)
    data = body()
    vendor_name = str_field(data, "vendor_name", 1, 120, required=False)
    small_pct = dec_field(data, "small_tier_pct", "0.00", "0.50", max_dp=4,
                          required=False)
    mid_pct = dec_field(data, "mid_tier_pct", "0.00", "0.50", max_dp=4,
                        required=False)
    large_pct = dec_field(data, "large_tier_pct", "0.00", "0.50", max_dp=4,
                          required=False)
    mid_floor = int_field(data, "tier_mid_floor_cents", 1, required=False)
    large_floor = int_field(data, "tier_large_floor_cents", 1, required=False)
    addendum_pct = dec_field(data, "multi_unit_addendum_pct", "0.00", "0.20",
                             max_dp=4, required=False)
    trade_in_cap_pct = dec_field(data, "trade_in_cap_pct", "0.00", "0.50",
                                 max_dp=4, required=False)
    expires_raw, expires_on = dt_field(data, "expires_on", required=False)

    effective_mid = mid_floor if mid_floor is not None \
        else contract["tier_mid_floor_cents"]
    effective_large = large_floor if large_floor is not None \
        else contract["tier_large_floor_cents"]
    if effective_large <= effective_mid:
        raise ApiError("ERR_VALIDATION")

    if vendor_name is not None:
        contract["vendor_name"] = vendor_name
    if small_pct is not None:
        contract["small_tier_pct"] = small_pct
    if mid_pct is not None:
        contract["mid_tier_pct"] = mid_pct
    if large_pct is not None:
        contract["large_tier_pct"] = large_pct
    if mid_floor is not None:
        contract["tier_mid_floor_cents"] = mid_floor
    if large_floor is not None:
        contract["tier_large_floor_cents"] = large_floor
    if addendum_pct is not None:
        contract["multi_unit_addendum_pct"] = addendum_pct
    if trade_in_cap_pct is not None:
        contract["trade_in_cap_pct"] = trade_in_cap_pct
    if expires_raw is not None:
        contract["expires_on"] = expires_raw
        contract["_expires_on"] = expires_on
    touch(contract)
    return object_response(serializers.contract(contract))


@bp.route("/capital/gpo-contracts/<contract_id>", methods=["GET"])
@guard()
def get_contract(contract_id):
    return object_response(serializers.contract(lookups.contract(contract_id)))


@bp.route("/capital/gpo-contracts", methods=["GET"])
@guard()
def list_contracts():
    limit, offset = pagination()
    rows = lookups.filtered(db.contracts.values(), [
        ("vendor_name", q_str("vendor_name")),
        ("contract_code", q_str("contract_code")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.contract)


# -------------------------------------------------------------- VendorQuote

@bp.route("/capital/requests/<request_id>/quotes", methods=["POST"])
@guard(CAPITAL_PLANNER)
def create_quote(request_id):
    request_row = lookups.request_row(request_id)
    data = body()
    ref = raw_ref(data, "gpo_contract_id")
    if ref is not None:
        lookups.contract(ref)
    ref = raw_ref(data, "trade_in_asset_id")
    if ref is not None:
        lookups.asset(ref)

    contract_id = str_field(data, "gpo_contract_id", 1, None)
    vendor_name = str_field(data, "vendor_name", 1, 120)
    list_price = int_field(data, "list_price_cents", 1)
    escalation_pct = dec_field(data, "service_escalation_pct", "0.00", "0.25",
                               max_dp=4)
    valid_raw, valid_until = dt_field(data, "valid_until")
    trade_in_asset_id = str_field(data, "trade_in_asset_id", 1, None,
                                  required=False)
    trade_in_offer = int_field(data, "trade_in_offer_cents", 0, required=False,
                               default=0)
    multi_unit_count = int_field(data, "multi_unit_count", 1, 10, required=False,
                                 default=1)
    warranty_months = _warranty(data, "warranty_months", required=False,
                                default=0)

    contract = lookups.contract(contract_id)
    if trade_in_asset_id is not None:
        lookups.asset(trade_in_asset_id)

    if request_row["status"] not in QUOTABLE_REQUEST_STATES:
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    if contract["_expires_on"] <= db.now():
        raise ApiError("ERR_GPO_CONTRACT_EXPIRED")

    if (trade_in_asset_id is not None
            and trade_in_asset_id != request_row["asset_id"]):
        raise ApiError("ERR_TRADE_IN_ASSET_MISMATCH")

    row = new_row({
        "request_id": request_row["id"],
        "gpo_contract_id": contract["id"],
        "trade_in_asset_id": trade_in_asset_id,
        "vendor_name": vendor_name,
        "list_price_cents": list_price,
        "trade_in_offer_cents": trade_in_offer,
        "multi_unit_count": multi_unit_count,
        "warranty_months": warranty_months,
        "service_escalation_pct": escalation_pct,
        "valid_until": valid_raw,
        "_valid_until": valid_until,
        "status": "SUBMITTED",
        "negotiation_round": 1,
        "gpo_tier": None,
        "gpo_discount_cents": 0,
        "multi_unit_addendum_cents": 0,
        "subtotal_cents": 0,
        "trade_in_credit_cents": 0,
        "net_capital_cents": 0,
    })
    pricing.price_quote(row, contract)
    db.quotes[row["id"]] = row
    return created_response(serializers.quote(row))


@bp.route("/capital/vendor-quotes/<quote_id>", methods=["GET"])
@guard()
def get_quote(quote_id):
    return object_response(serializers.quote(lookups.quote(quote_id)))


@bp.route("/capital/vendor-quotes", methods=["GET"])
@guard()
def list_quotes():
    limit, offset = pagination()
    rows = lookups.filtered(db.quotes.values(), [
        ("request_id", q_str("request_id")),
        ("gpo_contract_id", q_str("gpo_contract_id")),
        ("trade_in_asset_id", q_str("trade_in_asset_id")),
        ("status", q_str("status")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.quote)


@bp.route("/capital/vendor-quotes/<quote_id>/counter", methods=["POST"])
@guard(CAPITAL_PLANNER)
def counter_quote(quote_id):
    quote = lookups.quote(quote_id)
    data = body()
    counter_price = int_field(data, "counter_list_price_cents", 1)
    counter_offer = int_field(data, "counter_trade_in_offer_cents", 0,
                              required=False)
    str_field(data, "counter_note", 0, 500, required=False)

    if quote["status"] != "SUBMITTED":
        raise ApiError("ERR_QUOTE_INVALID_STATE")

    quote["list_price_cents"] = counter_price
    if counter_offer is not None:
        quote["trade_in_offer_cents"] = counter_offer
    quote["negotiation_round"] += 1
    quote["status"] = "COUNTERED"
    pricing.price_quote(quote, lookups.contract(quote["gpo_contract_id"]))
    touch(quote)
    return object_response(serializers.quote(quote))


@bp.route("/capital/vendor-quotes/<quote_id>/revise", methods=["POST"])
@guard(CAPITAL_PLANNER)
def revise_quote(quote_id):
    quote = lookups.quote(quote_id)
    data = body()
    revised_price = int_field(data, "revised_list_price_cents", 1)
    revised_offer = int_field(data, "revised_trade_in_offer_cents", 0,
                              required=False)
    revised_warranty = _warranty(data, "revised_warranty_months", required=False)

    if quote["status"] != "COUNTERED":
        raise ApiError("ERR_QUOTE_INVALID_STATE")

    if quote["negotiation_round"] > MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT")

    quote["list_price_cents"] = revised_price
    if revised_offer is not None:
        quote["trade_in_offer_cents"] = revised_offer
    if revised_warranty is not None:
        quote["warranty_months"] = revised_warranty
    quote["status"] = "SUBMITTED"
    pricing.price_quote(quote, lookups.contract(quote["gpo_contract_id"]))
    touch(quote)
    return object_response(serializers.quote(quote))


@bp.route("/capital/vendor-quotes/<quote_id>/accept", methods=["POST"])
@guard(CAPITAL_PLANNER)
def accept_quote(quote_id):
    quote = lookups.quote(quote_id)
    data = body()
    ack = bool_field(data, "safety_review_ack", required=False)

    if quote["status"] != "SUBMITTED":
        raise ApiError("ERR_QUOTE_INVALID_STATE")

    request_row = lookups.request_row(quote["request_id"])
    if request_row["status"] not in ("APPROVED", "FUNDED"):
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    if db.now() > quote["_valid_until"]:
        raise ApiError("ERR_QUOTE_EXPIRED")

    trade_in_asset = None
    if quote["trade_in_asset_id"]:
        trade_in_asset = db.assets.get(quote["trade_in_asset_id"])
        if (trade_in_asset is None
                or trade_in_asset["id"] != request_row["asset_id"]
                or trade_in_asset["status"] == "DECOMMISSIONED"
                or trade_in_asset["disposition_status"]
                not in ("NONE", "HELD_FOR_TRADE_IN")):
            raise ApiError("ERR_TRADE_IN_ASSET_UNAVAILABLE")
        for other in db.quotes.values():
            if (other["id"] != quote["id"] and other["status"] == "ACCEPTED"
                    and other["trade_in_asset_id"] == trade_in_asset["id"]
                    and other["request_id"] != quote["request_id"]):
                raise ApiError("ERR_TRADE_IN_ASSET_UNAVAILABLE")

    if request_row["safety_driver"] >= SAFETY_REVIEW_THRESHOLD and ack is not True:
        raise ApiError("ERR_SAFETY_REVIEW_REQUIRED")

    new_funded = (quote["net_capital_cents"]
                  + request_row["facility_modification_cents"])
    delta = new_funded - request_row["funded_amount_cents"]

    cycle = None
    allocation = None
    if request_row["status"] == "FUNDED":
        cycle = lookups.cycle(request_row["cycle_id"])
        facility_id = lookups.request_facility_id(request_row)
        allocation = lookups.find_allocation(cycle["id"], facility_id)
        if allocation is None:
            raise ApiError("ERR_NO_FACILITY_ALLOCATION")
        if allocation["available_cents"] - delta < 0:
            raise ApiError("ERR_ALLOCATION_INSUFFICIENT")

    quote["status"] = "ACCEPTED"
    touch(quote)

    for sibling in ordered(db.quotes.values()):
        if sibling["id"] == quote["id"]:
            continue
        if sibling["request_id"] != quote["request_id"]:
            continue
        if sibling["status"] not in QUOTE_STATES_OPEN:
            continue
        was_accepted = sibling["status"] == "ACCEPTED"
        sibling["status"] = "SUPERSEDED"
        touch(sibling)
        if was_accepted:
            cascades.release_trade_in_claim(sibling)

    if trade_in_asset is not None:
        cascades.claim_trade_in(quote)

    pricing.write_negotiated(request_row, quote)
    request_row["funded_amount_cents"] = new_funded
    touch(request_row)

    if allocation is not None:
        cascades.apply_committed_delta(allocation, cycle, delta)

    return object_response(serializers.quote(quote))


@bp.route("/capital/vendor-quotes/<quote_id>/withdraw", methods=["POST"])
@guard(CAPITAL_PLANNER)
def withdraw_quote(quote_id):
    quote = lookups.quote(quote_id)
    data = body()
    str_field(data, "withdrawal_reason", 0, 500, required=False)

    if quote["status"] not in QUOTE_STATES_OPEN:
        raise ApiError("ERR_QUOTE_INVALID_STATE")

    request_row = lookups.request_row(quote["request_id"])
    if request_row["status"] in ("IMPLEMENTED", "AUDITED"):
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    was_accepted = quote["status"] == "ACCEPTED"

    cycle = None
    allocation = None
    delta = 0
    new_funded = request_row["funded_amount_cents"]
    if was_accepted:
        new_funded = (request_row["estimated_capital_cents"]
                      + request_row["facility_modification_cents"])
        delta = new_funded - request_row["funded_amount_cents"]
        if request_row["status"] == "FUNDED":
            cycle = lookups.cycle(request_row["cycle_id"])
            facility_id = lookups.request_facility_id(request_row)
            allocation = lookups.find_allocation(cycle["id"], facility_id)
            if allocation is None:
                raise ApiError("ERR_NO_FACILITY_ALLOCATION")
            if allocation["available_cents"] - delta < 0:
                raise ApiError("ERR_ALLOCATION_INSUFFICIENT")

    quote["status"] = "WITHDRAWN"
    touch(quote)

    if was_accepted:
        cascades.release_trade_in_claim(quote)
        pricing.clear_negotiated(request_row)
        request_row["funded_amount_cents"] = new_funded
        touch(request_row)
        if allocation is not None:
            cascades.apply_committed_delta(allocation, cycle, delta)

    return object_response(serializers.quote(quote))

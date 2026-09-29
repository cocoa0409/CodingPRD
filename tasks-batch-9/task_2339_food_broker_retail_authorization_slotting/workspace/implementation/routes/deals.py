"""Slotting fee negotiation and the quote ladder (PRD section 3.5)."""

from flask import Blueprint

import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize, check_principal_scope, check_retailer_scope
from services import calc, domain

bp = Blueprint("deals", __name__)

_QUOTE_KEYS = (
    "gross_fee_cents",
    "volume_credit_cents",
    "net_before_admin_cents",
    "admin_fee_cents",
    "quoted_fee_cents",
)


def serialize(rec):
    return {
        "id": rec["id"],
        "presentation_id": rec["presentation_id"],
        "requested_fee_per_store_cents": rec["requested_fee_per_store_cents"],
        "current_fee_per_store_cents": rec["current_fee_per_store_cents"],
        "last_offer_side": rec["last_offer_side"],
        "store_count_in_scope": rec["store_count_in_scope"],
        "item_count_in_scope": rec["item_count_in_scope"],
        "forecast_annual_units": rec["forecast_annual_units"],
        "amortization_periods": rec["amortization_periods"],
        "amortization_method": rec["amortization_method"],
        "round_index": rec["round_index"],
        "gross_fee_cents": rec["gross_fee_cents"],
        "volume_credit_cents": rec["volume_credit_cents"],
        "net_before_admin_cents": rec["net_before_admin_cents"],
        "admin_fee_cents": rec["admin_fee_cents"],
        "quoted_fee_cents": rec["quoted_fee_cents"],
        "accepted_fee_cents": rec["accepted_fee_cents"],
        "cost_per_forecast_unit_cents": rec["cost_per_forecast_unit_cents"],
        "recovered_cents": rec["recovered_cents"],
        "written_off_cents": rec["written_off_cents"],
        "unamortized_balance_cents": rec["unamortized_balance_cents"],
        "periods_posted": rec["periods_posted"],
        "state": rec["state"],
        "reject_reason": rec["reject_reason"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _requote(deal):
    quote = calc.slotting_quote(
        deal["current_fee_per_store_cents"],
        deal["store_count_in_scope"],
        deal["item_count_in_scope"],
        deal["forecast_annual_units"],
    )
    for key in _QUOTE_KEYS:
        deal[key] = quote[key]


@bp.post("/slotting-deals")
def create_deal():
    authorize("BrokerAccountManager")
    data = v.body()

    presentation_id = v.req_id(data, "presentation_id")
    requested_fee = v.req_int(data, "requested_fee_per_store_cents", 0)
    store_count = v.req_int(data, "store_count_in_scope", 1)
    item_count = v.req_int(data, "item_count_in_scope", 1)
    forecast_units = v.req_int(data, "forecast_annual_units", 0)
    periods = v.req_int(data, "amortization_periods", 1, 12)
    method = v.opt_enum(data, "amortization_method", v.AMORTIZATION_METHODS)
    if method is None:
        method = "FORECAST_STRAIGHT"

    presentation = db.get("presentations", presentation_id)

    listed = len(presentation.get("item_ids") or [])
    if item_count > listed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'item_count_in_scope' may not exceed the presentation's item count.",
        )

    review = domain.review_of_presentation(presentation)
    retailer = db.find("retailers", review["retailer_id"]) if review else None
    if retailer is not None and store_count > retailer["total_store_count"]:
        raise ApiError("ERR_STORE_COUNT_EXCEEDS_CHAIN")

    rec = db.base_record()
    rec.update({
        "presentation_id": presentation["id"],
        "requested_fee_per_store_cents": requested_fee,
        "current_fee_per_store_cents": requested_fee,
        "last_offer_side": None,
        "store_count_in_scope": store_count,
        "item_count_in_scope": item_count,
        "forecast_annual_units": forecast_units,
        "amortization_periods": periods,
        "amortization_method": method,
        "round_index": 0,
        "accepted_fee_cents": 0,
        "cost_per_forecast_unit_cents": None,
        "recovered_cents": 0,
        "written_off_cents": 0,
        "unamortized_balance_cents": 0,
        "periods_posted": 0,
        "state": "DRAFT",
        "reject_reason": None,
    })
    _requote(rec)
    db.insert("deals", rec)
    return response.created(serialize(rec))


@bp.get("/slotting-deals/<deal_id>")
def read_deal(deal_id):
    user_id, role = authorize(*ALL_ROLES)
    rec = db.get("deals", deal_id)
    presentation = domain.presentation_of_deal(rec)
    if presentation is not None:
        check_principal_scope(role, user_id, presentation["principal_id"])
    return response.ok(serialize(rec))


@bp.get("/slotting-deals")
def list_deals():
    authorize(*ALL_ROLES)
    limit, offset = v.pagination()
    presentation_id = v.filter_value("presentation_id")
    state = v.filter_value("state")
    rows = []
    for rec in db.ordered("deals"):
        if presentation_id is not None and rec["presentation_id"] != presentation_id:
            continue
        if state is not None and rec["state"] != state:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.post("/slotting-deals/<deal_id>/propose")
def propose_deal(deal_id):
    authorize("BrokerAccountManager")
    data = v.body()
    fee = v.req_int(data, "proposed_fee_per_store_cents", 0)

    rec = db.get("deals", deal_id)

    if rec["state"] not in ("DRAFT", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE")

    presentation = domain.presentation_of_deal(rec)
    if presentation is not None and presentation["status"] == "DECLINED":
        raise ApiError("ERR_PRESENTATION_DECLINED")

    if rec["state"] == "COUNTERED" and fee >= rec["current_fee_per_store_cents"]:
        raise ApiError("ERR_PROPOSAL_NOT_LOWER")

    rec["current_fee_per_store_cents"] = fee
    rec["last_offer_side"] = "BROKER"
    rec["state"] = "PROPOSED"
    _requote(rec)
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/slotting-deals/<deal_id>/counter")
def counter_deal(deal_id):
    user_id, role = authorize("RetailerBuyer")
    data = v.body()
    fee = v.req_int(data, "counter_fee_per_store_cents", 0)
    forecast = v.opt_int(data, "counter_forecast_annual_units", None, 0)

    rec = db.get("deals", deal_id)

    review = domain.review_of_presentation(domain.presentation_of_deal(rec))
    if review is not None:
        check_retailer_scope(role, user_id, review["retailer_id"])

    if rec["state"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE")

    if rec["round_index"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")
    if fee <= rec["current_fee_per_store_cents"]:
        raise ApiError("ERR_COUNTER_NOT_HIGHER")

    rec["round_index"] = rec["round_index"] + 1
    rec["current_fee_per_store_cents"] = fee
    if forecast is not None:
        rec["forecast_annual_units"] = forecast
    rec["last_offer_side"] = "RETAILER"
    rec["state"] = "COUNTERED"
    _requote(rec)
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/slotting-deals/<deal_id>/accept")
def accept_deal(deal_id):
    user_id, role = authorize("RetailerBuyer", "BrokerAccountManager")
    data = v.body()
    expected_version = v.req_int(data, "expected_principal_version", 0)

    rec = db.get("deals", deal_id)

    presentation = domain.presentation_of_deal(rec)
    review = domain.review_of_presentation(presentation)
    principal = db.find("principals", presentation["principal_id"]) if presentation else None

    if review is not None:
        check_retailer_scope(role, user_id, review["retailer_id"])

    if principal is None:
        raise ApiError("ERR_PRINCIPAL_NOT_FOUND")

    if expected_version != principal["version"]:
        raise ApiError("ERR_STALE_PRINCIPAL_VERSION")

    if rec["state"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE")

    # a party may never accept its own standing offer
    if role == "RetailerBuyer" and rec["last_offer_side"] != "BROKER":
        raise ApiError("ERR_ACCEPT_BY_OFFEROR")
    if role == "BrokerAccountManager" and rec["last_offer_side"] != "RETAILER":
        raise ApiError("ERR_ACCEPT_BY_OFFEROR")

    if review is None or review["status"] != "DECIDED":
        raise ApiError("ERR_REVIEW_NOT_DECIDED")
    if presentation["status"] != "ACCEPTED":
        raise ApiError("ERR_PRESENTATION_NOT_ACCEPTED")
    if principal["status"] != "ACTIVE":
        raise ApiError("ERR_PRINCIPAL_NOT_ACTIVE")

    if domain.active_agreement(principal["id"], review["retailer_id"], review["category_code"]) is None:
        raise ApiError("ERR_NO_ACTIVE_COMMISSION_AGREEMENT")

    if principal["credit_posture"] == "RESTRICTED":
        raise ApiError("ERR_PRINCIPAL_CREDIT_RESTRICTED")

    quoted = rec["quoted_fee_cents"]
    if principal["slotting_committed_cents"] + quoted > principal["slotting_budget_cents"]:
        raise ApiError("ERR_SLOTTING_BUDGET_EXCEEDED")

    # ---------------------------------------------------------------- success
    rec["accepted_fee_cents"] = quoted
    rec["unamortized_balance_cents"] = quoted
    rec["cost_per_forecast_unit_cents"] = calc.round_half_up_2(quoted, rec["forecast_annual_units"])
    rec["state"] = "ACCEPTED"
    db.touch(rec)

    # the deal never rests in ACCEPTED
    rec["state"] = "AMORTIZING"
    db.touch(rec)

    domain.acceptance_cascade(rec)
    db.touch(principal)
    domain.recompute_principal(principal)

    return response.ok(serialize(rec))


@bp.post("/slotting-deals/<deal_id>/reject")
def reject_deal_route(deal_id):
    user_id, role = authorize("RetailerBuyer")
    data = v.body()
    reason = v.req_string(data, "reject_reason")

    rec = db.get("deals", deal_id)

    review = domain.review_of_presentation(domain.presentation_of_deal(rec))
    if review is not None:
        check_retailer_scope(role, user_id, review["retailer_id"])

    if rec["state"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE")

    domain.reject_deal(rec, reason)
    domain.recompute_principal(domain.principal_of_deal(rec))
    return response.ok(serialize(rec))

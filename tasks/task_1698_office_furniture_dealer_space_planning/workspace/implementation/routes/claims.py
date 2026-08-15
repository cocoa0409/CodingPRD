"""ManufacturerClaim routes: the negotiation cycle (submit / acknowledge /
offer / counter / accept / deny / withdraw) and the settlement cascades."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_PUNCH_NOT_VERIFIED,
)
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import (
    get_or_404, new_entity, touch,
    recompute_order_totals, recompute_promised_date, recompute_install_posture,
    recompute_customer_balance,
)
from services.pricing import price_line, set_provisional_lead
from util import CLOCK
from validate import body_dict, req_str, req_enum, req_int

bp = Blueprint("manufacturer_claims", __name__)

CLAIM_TYPES = {"DEFECT", "FREIGHT_DAMAGE", "SHORTAGE"}
REMEDIES = {"REPAIR", "REPLACE", "CREDIT"}


@bp.route("/api/manufacturer-claims", methods=["POST"])
def create_claim():
    authorize(["ClaimsCoordinator"])
    body = body_dict()
    punch_item_id = req_str(body, "punch_item_id")
    # priority 3
    punch = get_or_404("punch_items", punch_item_id)
    # priority 7e: manual claim creation requires a VERIFIED punch item
    if punch["status"] != "VERIFIED":
        raise_error(ERR_PUNCH_NOT_VERIFIED, f"punch item is {punch['status']}, not VERIFIED")
    # priority 8a
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    remedy_requested = req_enum(body, "remedy_requested", REMEDIES)
    claimed_amount_cents = req_int(body, "claimed_amount_cents", minv=1)
    line = db["order_lines"].get(punch.get("order_line_id") or "")
    claim = new_entity("manufacturer_claims", {
        "punch_item_id": punch_item_id,
        "series_id": line["series_id"] if line is not None else None,
        "claim_type": claim_type,
        "remedy_requested": remedy_requested,
        "claimed_amount_cents": claimed_amount_cents,
        "settlement_amount_cents": None,
        "settled_amount_cents": None,
        "replacement_order_line_id": None,
        "origin": "MANUAL",
        "status": "DRAFT",
    })
    return success_object(public(claim), status=201)


@bp.route("/api/manufacturer-claims", methods=["GET"])
def list_claims():
    authorize(ALL_ROLES)
    return list_response("manufacturer_claims",
                         ["punch_item_id", "series_id", "replacement_order_line_id", "status"])


@bp.route("/api/manufacturer-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    authorize(ALL_ROLES)
    return get_response("manufacturer_claims", claim_id)


def _transition(claim_id, roles, from_states, to_state):
    authorize(roles)
    claim = get_or_404("manufacturer_claims", claim_id)
    if claim["status"] not in from_states:
        raise_error(ERR_INVALID_STATE,
                    f"cannot move a claim from {claim['status']} to {to_state}")
    claim["status"] = to_state
    touch(claim)
    return claim


@bp.route("/api/manufacturer-claims/<claim_id>/submit", methods=["POST"])
def submit_claim(claim_id):
    claim = _transition(claim_id, ["ClaimsCoordinator"], ("DRAFT",), "SUBMITTED")
    return success_object(public(claim))


@bp.route("/api/manufacturer-claims/<claim_id>/acknowledge", methods=["POST"])
def acknowledge_claim(claim_id):
    claim = _transition(claim_id, ["ManufacturerRep"], ("SUBMITTED",), "ACKNOWLEDGED")
    return success_object(public(claim))


@bp.route("/api/manufacturer-claims/<claim_id>/offer_settlement", methods=["POST"])
def offer_settlement(claim_id):
    authorize(["ManufacturerRep"])
    claim = get_or_404("manufacturer_claims", claim_id)
    if claim["status"] != "ACKNOWLEDGED":
        raise_error(ERR_INVALID_STATE, f"cannot offer settlement on a claim in status {claim['status']}")
    body = body_dict()
    settlement = req_int(body, "settlement_amount_cents", minv=1)
    claim["settlement_amount_cents"] = settlement
    claim["status"] = "SETTLEMENT_OFFERED"
    touch(claim)
    return success_object(public(claim))


@bp.route("/api/manufacturer-claims/<claim_id>/counter", methods=["POST"])
def counter_claim(claim_id):
    authorize(["ClaimsCoordinator"])
    claim = get_or_404("manufacturer_claims", claim_id)
    if claim["status"] != "SETTLEMENT_OFFERED":
        raise_error(ERR_INVALID_STATE, f"cannot counter a claim in status {claim['status']}")
    claim["settlement_amount_cents"] = None
    claim["status"] = "SUBMITTED"
    touch(claim)
    return success_object(public(claim))


@bp.route("/api/manufacturer-claims/<claim_id>/accept_settlement", methods=["POST"])
def accept_settlement(claim_id):
    authorize(["ClaimsCoordinator"])
    claim = get_or_404("manufacturer_claims", claim_id)
    if claim["status"] != "SETTLEMENT_OFFERED":
        raise_error(ERR_INVALID_STATE, f"cannot accept a settlement on a claim in status {claim['status']}")
    claim["settled_amount_cents"] = claim["settlement_amount_cents"]
    claim["status"] = "SETTLED"
    touch(claim)
    punch = db["punch_items"].get(claim["punch_item_id"])
    order = db["project_orders"].get(punch["order_id"]) if punch is not None else None
    if claim["remedy_requested"] == "REPLACE" and punch is not None and order is not None:
        # replacement-line cascade: warranty-zero pricing, OPEN status
        source_line = db["order_lines"].get(punch.get("order_line_id") or "")
        series_id = claim.get("series_id") or (source_line["series_id"] if source_line else None)
        contract = db["pricing_contracts"].get(order["contract_id"])
        line = new_entity("order_lines", {
            "order_id": order["id"],
            "series_id": series_id,
            "typical_id": None,
            "quantity": punch.get("affected_units", 1),
            "selected_options": [],
            "is_replacement": True,
            "unit_list_price_cents": 0,
            "unit_net_price_cents": 0,
            "line_total_cents": 0,
            "provisional_lead_time_days": None,
            "provisional_promise_date": None,
            "confirmed_lead_time_days": None,
            "confirmed_promise_date": None,
            "received_units": 0,
            "status": "OPEN",
        })
        series = db["product_series"].get(series_id) if series_id else None
        if series is not None and contract is not None:
            price_line(line, series, contract)  # replacement: prices stay zero
            set_provisional_lead(line, series, CLOCK.today())
            touch(line)
        claim["replacement_order_line_id"] = line["id"]
        recompute_order_totals(order)
        old_promised, new_promised = recompute_promised_date(order)
        # promise-date cascade: demote CONFIRMED events scheduled before the
        # advanced promised date back to TENTATIVE
        if new_promised and (old_promised is None or new_promised > old_promised):
            for event in db["install_events"].values():
                if (event["order_id"] == order["id"] and event["status"] == "CONFIRMED"
                        and event["scheduled_date"] < new_promised):
                    event["status"] = "TENTATIVE"
                    touch(event)
            recompute_install_posture(order)
    elif claim["remedy_requested"] == "CREDIT" and order is not None:
        # settled CREDIT claims feed the customer's credit ledger
        customer = db["customers"].get(order["customer_id"])
        if customer is not None:
            recompute_customer_balance(customer)
    return success_object(public(claim))


@bp.route("/api/manufacturer-claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    claim = _transition(claim_id, ["ManufacturerRep"], ("ACKNOWLEDGED",), "DENIED")
    return success_object(public(claim))


@bp.route("/api/manufacturer-claims/<claim_id>/withdraw", methods=["POST"])
def withdraw_claim(claim_id):
    claim = _transition(claim_id, ["ClaimsCoordinator"], ("DRAFT", "SUBMITTED", "ACKNOWLEDGED"), "WITHDRAWN")
    return success_object(public(claim))

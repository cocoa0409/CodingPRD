"""Claim endpoints."""

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity, touch, parse_datetime, format_instant
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.calculations import claim_provisional_total, payer_responsibility

bp = Blueprint("claims", __name__)

LINE_TYPES = {"DEVICE", "WARRANTY", "TRAINING", "SHIPPING"}


@bp.post("/api/claims")
def create_claim():
    require_roles(["BillingSpecialist"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {
        "funding_authorization_id", "device_order_id", "service_date", "lines",
    })
    funding_authorization_id = v.req_string(body, "funding_authorization_id")
    device_order_id = v.req_string(body, "device_order_id")
    service_date = v.req_datetime(body, "service_date")

    raw_lines = body.get("lines")
    if not isinstance(raw_lines, list) or not (1 <= len(raw_lines) <= 10):
        raise errors.validation("lines must be an array of 1..10 elements")
    lines = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise errors.validation("each line must be an object")
        v.reject_unknown_fields(raw, {"line_type", "unit_price_cents", "quantity"})
        line_type = v.req_enum(raw, "line_type", LINE_TYPES)
        unit_price_cents = v.req_int(raw, "unit_price_cents", min_v=0)
        quantity = v.req_int(raw, "quantity", min_v=1, max_v=10)
        lines.append({
            "line_type": line_type,
            "unit_price_cents": unit_price_cents,
            "quantity": quantity,
        })

    auth = store.funding_authorizations.get(funding_authorization_id)
    if auth is None:
        raise errors.not_found("FundingAuthorization not found")
    order = store.device_orders.get(device_order_id)
    if order is None:
        raise errors.not_found("DeviceOrder not found")
    if order["client_id"] != auth["client_id"]:
        raise errors.validation("device_order_id does not belong to the authorization's client")

    provisional_total_cents = claim_provisional_total(lines, auth["payer_type"])

    claim = new_entity()
    claim.update({
        "funding_authorization_id": funding_authorization_id,
        "device_order_id": device_order_id,
        "service_date": format_instant(service_date),
        "lines": lines,
        "provisional_total_cents": provisional_total_cents,
        "final_amount_cents": None,
        "payer_pays_cents": None,
        "client_pays_cents": None,
        "submitted_by_user_id": None,
        "status": "DRAFT",
    })
    store.claims[claim["id"]] = claim
    return success_object(claim, status=201)


@bp.get("/api/claims/<cid>")
def get_claim(cid):
    require_roles(ALL_ROLES)
    claim = store.claims.get(cid)
    if claim is None:
        raise errors.not_found("Claim not found")
    return success_object(claim)


@bp.get("/api/claims")
def list_claims():
    require_roles(ALL_ROLES)
    limit, offset = v.parse_pagination(request.args)
    items = v.apply_filters(list(store.claims.values()), [
        (request.args.get("funding_authorization_id"), "funding_authorization_id"),
        (request.args.get("device_order_id"), "device_order_id"),
        (request.args.get("status"), "status"),
    ])
    items = v.sort_by_created(items)
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.post("/api/claims/<cid>/submit")
def submit_claim(cid):
    actor = require_roles(["BillingSpecialist"])
    claim = store.claims.get(cid)
    if claim is None:
        raise errors.not_found("Claim not found")
    if claim["status"] != "DRAFT":
        raise errors.invalid_state("Claim is not DRAFT")

    auth = store.funding_authorizations.get(claim["funding_authorization_id"])
    if auth is None:
        raise errors.not_found("FundingAuthorization not found")
    # cross-entity state
    if auth["status"] != "APPROVED":
        raise errors.funding_not_approved()
    # temporal window (inclusive)
    service_date = parse_datetime(claim["service_date"])
    valid_from = parse_datetime(auth["valid_from"])
    valid_until = parse_datetime(auth["valid_until"])
    if not (valid_from <= service_date <= valid_until):
        raise errors.funding_window_invalid()
    # fiscal sufficiency (exact equality allowed)
    if claim["provisional_total_cents"] > auth["remaining_amount_cents"]:
        raise errors.insufficient_funding()

    claim["status"] = "SUBMITTED"
    claim["submitted_by_user_id"] = actor.user_id
    touch(claim)

    auth["remaining_amount_cents"] -= claim["provisional_total_cents"]
    touch(auth)
    return success_object(claim)


@bp.post("/api/claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    actor = require_roles(["PayerAdjudicator"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"decision", "allowed_amount_cents"})
    decision = v.req_enum(body, "decision", {"PAY", "DENY"})
    allowed_amount_cents = v.opt_int(body, "allowed_amount_cents", default=None, min_v=0)

    claim = store.claims.get(cid)
    if claim is None:
        raise errors.not_found("Claim not found")
    if claim["status"] != "SUBMITTED":
        raise errors.invalid_state("Claim is not SUBMITTED")
    if claim["submitted_by_user_id"] == actor.user_id:
        raise errors.segregation()
    if decision == "PAY" and allowed_amount_cents is None:
        raise errors.validation("allowed_amount_cents is required for PAY")

    auth = store.funding_authorizations.get(claim["funding_authorization_id"])
    if auth is None:
        raise errors.not_found("FundingAuthorization not found")

    if decision == "PAY":
        client = store.clients.get(auth["client_id"])
        copay_tier = client["copay_tier"] if client else "STANDARD"
        payer_pays_cents, client_pays_cents = payer_responsibility(
            allowed_amount_cents, auth["payer_type"],
            auth["remaining_amount_cents"], claim["provisional_total_cents"],
            copay_tier,
        )
        claim["final_amount_cents"] = allowed_amount_cents
        claim["payer_pays_cents"] = payer_pays_cents
        claim["client_pays_cents"] = client_pays_cents
        claim["status"] = "PAID"
        touch(claim)

        auth["remaining_amount_cents"] += claim["provisional_total_cents"] - payer_pays_cents
        if auth["status"] == "APPROVED" and auth["remaining_amount_cents"] == 0:
            auth["status"] = "EXHAUSTED"
        touch(auth)
    else:  # DENY
        claim["status"] = "DENIED"
        touch(claim)
        auth["remaining_amount_cents"] += claim["provisional_total_cents"]
        touch(auth)

    return success_object(claim)


@bp.post("/api/claims/<cid>/void")
def void_claim(cid):
    require_roles(["BillingSpecialist"])
    claim = store.claims.get(cid)
    if claim is None:
        raise errors.not_found("Claim not found")
    if claim["status"] not in ("SUBMITTED", "PAID"):
        raise errors.invalid_state("Only SUBMITTED or PAID claims can be voided")

    auth = store.funding_authorizations.get(claim["funding_authorization_id"])
    if auth is None:
        raise errors.not_found("FundingAuthorization not found")

    if claim["status"] == "SUBMITTED":
        auth["remaining_amount_cents"] += claim["provisional_total_cents"]
    else:  # PAID
        auth["remaining_amount_cents"] += claim["payer_pays_cents"]

    claim["status"] = "VOIDED"
    touch(claim)

    if auth["status"] == "EXHAUSTED" and auth["remaining_amount_cents"] > 0:
        auth["status"] = "APPROVED"
    touch(auth)
    return success_object(claim)

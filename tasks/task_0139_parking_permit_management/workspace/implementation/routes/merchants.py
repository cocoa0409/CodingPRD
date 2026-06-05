"""Merchant + Validation endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_MERCHANT_BUDGET_EXHAUSTED
from middleware import get_json_body, require_auth
from response import ok_object
from services.common import (
    list_response,
    lookup,
    require_datetime,
    require_enum,
    require_int,
    require_owner_merchant,
    require_string,
)
from services.serialize import public

bp = Blueprint("merchants", __name__)

DISCOUNT_KINDS = {"FLAT_CENTS", "PERCENT", "FREE_HOURS"}


@bp.post("/parking/merchants")
def create_merchant():
    require_auth(["FacilityAdmin"])()
    body = get_json_body()
    garage_id = require_string(body, "garage_id")
    name = require_string(body, "name")
    validation_budget_cents = require_int(body, "validation_budget_cents", required=True, minimum=0)

    lookup(db.garages, garage_id)

    m = db.stamp_common(
        {
            "garage_id": garage_id,
            "name": name,
            "validation_budget_cents": validation_budget_cents,
        }
    )
    db.merchants[m["id"]] = m
    return ok_object(public(m), 201)


@bp.get("/parking/merchants/<mid>")
def read_merchant(mid):
    require_auth(["FacilityAdmin", "Merchant"])()
    m = lookup(db.merchants, mid)
    return ok_object(public(m), 200)


@bp.get("/parking/merchants/<mid>/validations")
def list_merchant_validations(mid):
    require_auth(["FacilityAdmin", "Merchant"])()
    lookup(db.merchants, mid)
    items = [v for v in db.validations.values() if v["merchant_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return list_response(items, request.args)


@bp.post("/parking/validations")
def create_validation():
    require_auth(["Merchant"])()
    body = get_json_body()
    garage_id = require_string(body, "garage_id")
    merchant_id = require_string(body, "merchant_id")
    discount_kind = require_enum(body, "discount_kind", DISCOUNT_KINDS, required=True)
    discount_value = require_int(body, "discount_value", required=True, minimum=0)
    expires_at_utc = require_datetime(body, "expires_at_utc", required=True)

    lookup(db.garages, garage_id)
    merchant = lookup(db.merchants, merchant_id)

    require_owner_merchant(merchant_id)

    # Merchant budget must be > 0 to issue (PRD §3.7, priority 13).
    if merchant["validation_budget_cents"] <= 0:
        raise APIError(ERR_MERCHANT_BUDGET_EXHAUSTED, 409, "Merchant has no remaining validation budget")

    v = db.stamp_common(
        {
            "garage_id": garage_id,
            "merchant_id": merchant_id,
            "discount_kind": discount_kind,
            "discount_value": discount_value,
            "status": "ISSUED",
            "expires_at_utc": expires_at_utc,
        }
    )
    db.validations[v["id"]] = v
    return ok_object(public(v), 201)


@bp.get("/parking/validations/<vid>")
def read_validation(vid):
    require_auth(["FacilityAdmin", "Merchant", "Motorist"])()
    v = lookup(db.validations, vid)
    return ok_object(public(v), 200)


@bp.get("/parking/validations/<vid>/sessions")
def list_validation_sessions(vid):
    require_auth(["FacilityAdmin", "Merchant"])()
    lookup(db.validations, vid)
    items = [s for s in db.sessions.values() if s.get("validation_id") == vid]
    return list_response(items, request.args)

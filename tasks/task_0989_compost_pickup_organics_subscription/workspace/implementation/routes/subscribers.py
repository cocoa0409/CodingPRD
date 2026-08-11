"""Subscriber endpoints: signup, read, impact, credit adjustments."""

from flask import Blueprint

import db
import response
from db import new_entity, store
from errors import (ERR_INSUFFICIENT_CREDIT, bad_request, not_found,
                    unprocessable)
from middleware import auth, own_or_403, require_roles
from services import (SUBSCRIBER_TYPES, impact_report, post_entry,
                      ser_subscriber, ser_entry)
from utils import get_body, require_enum, require_str, season_label

bp = Blueprint("subscribers", __name__)


@bp.post("/subscribers")
def signup():
    _, role = auth()
    require_roles(role, "Anonymous")
    body = get_body()
    sub = new_entity(common=True)
    sub.update({
        "email": require_str(body, "email"),
        "full_name": require_str(body, "full_name"),
        "subscriber_type": require_enum(body, "subscriber_type", SUBSCRIBER_TYPES),
        "address": require_str(body, "address"),
        "credit_balance_cents": 0,
    })
    store["subscribers"][sub["id"]] = sub
    return response.ok(ser_subscriber(sub), code=201)


@bp.get("/subscribers/<sid>")
def get_subscriber(sid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    if role == "Subscriber":
        own_or_403(sid, uid)
    sub = store["subscribers"].get(sid)
    if sub is None:
        not_found("Subscriber not found")
    return response.ok(ser_subscriber(sub))


@bp.get("/subscribers/<sid>/impact")
def get_impact(sid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    if role == "Subscriber":
        own_or_403(sid, uid)
    if sid not in store["subscribers"]:
        not_found("Subscriber not found")
    return response.ok(impact_report(sid))


@bp.post("/subscribers/<sid>/credit-adjustments")
def credit_adjustment(sid):
    uid, role = auth()
    require_roles(role, "OperationsManager")
    body = get_body()
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool):
        bad_request("amount_cents must be an integer")
    if amount == 0:
        bad_request("amount_cents must be nonzero")
    reason = body.get("reason")
    if not isinstance(reason, str):
        bad_request("reason is required")
    sub = store["subscribers"].get(sid)
    if sub is None:
        not_found("Subscriber not found")
    if sub["credit_balance_cents"] + amount < 0:
        unprocessable(ERR_INSUFFICIENT_CREDIT,
                      "Adjustment would push credit_balance_cents below zero")
    entry = post_entry(sid, "MANUAL_ADJUSTMENT", amount,
                       season_label(db.logical_now().date()), reason=reason)
    return response.ok(ser_entry(entry), code=201)

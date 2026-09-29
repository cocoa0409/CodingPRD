"""Retailer authorization reads and status transitions (PRD 3.6)."""

from flask import Blueprint

import constants as K
import db
import middleware as mw
import response
import serializers
import validate as V
from db import S, touch
from errors import ApiError
from middleware import (ROLE_AUDITOR, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_LICENSEE,
                        ROLE_MANAGER, guard, paginate, pagination)
from services import domain
from services import retailers as R

bp = Blueprint("retailer_authorizations", __name__)

READ_ROLES = [ROLE_MANAGER, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_AUDITOR, ROLE_LICENSEE]


@bp.get("/licensing/retailer-authorizations")
def list_authorizations():
    ctx = guard(READ_ROLES)
    limit, offset = pagination()
    licensee_id = mw.filter_str("licensee_id")
    channel_class = mw.filter_enum("channel_class", K.AUTH_CHANNEL_CLASSES)
    status = mw.filter_enum("status", K.AUTH_STATUSES)
    retailer_name = mw.filter_str("retailer_name")
    closeout = mw.filter_bool("closeout_allowed")

    rows = list(S.authorizations.values())
    if ctx.role == ROLE_LICENSEE:
        rows = [r for r in rows if r["licensee_id"] == ctx.uid]
    if licensee_id is not None:
        rows = [r for r in rows if r["licensee_id"] == licensee_id]
    if channel_class is not None:
        rows = [r for r in rows if r["channel_class"] == channel_class]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if retailer_name is not None:
        rows = [r for r in rows if r["retailer_name"] == retailer_name]
    if closeout is not None:
        rows = [r for r in rows if r["closeout_allowed"] == closeout]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("RetailerAuthorization", page),
                            limit, offset, total)


@bp.get("/licensing/retailer-authorizations/<authorization_id>")
def get_authorization(authorization_id):
    ctx = guard(READ_ROLES)
    auth = R.find_auth(authorization_id)
    mw.scope_licensee(ctx, auth["licensee_id"])
    return response.ok(serializers.dump("RetailerAuthorization", auth))


@bp.post("/licensing/retailer-authorizations/<authorization_id>/status")
def authorization_status(authorization_id):
    ctx = guard([ROLE_MANAGER, ROLE_COMPLIANCE])
    auth = R.find_auth(authorization_id)
    body = ctx.body
    action = V.req_enum(body, "action", ("APPROVE", "SUSPEND", "REINSTATE", "REVOKE"))
    reason = V.opt_string(body, "reason")

    licensee = S.licensees[auth["licensee_id"]]
    status = auth["status"]

    if action == "APPROVE":
        if status != "PENDING":
            raise ApiError("ERR_INVALID_STATE")
    elif action == "SUSPEND":
        if status != "AUTHORIZED":
            raise ApiError("ERR_INVALID_STATE")
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
    else:
        if status not in ("PENDING", "AUTHORIZED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")

    if R.portfolio_frozen(auth["licensee_id"]):
        raise ApiError("ERR_POSTURE_FROZEN")

    if action in ("APPROVE", "REINSTATE") and licensee["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSEE_NOT_ACTIVE")

    if action == "APPROVE":
        start = db.parse_date(auth["authorized_from"])
        end = db.parse_date(auth["authorized_to"])
        R.check_off_price_capacity(auth["licensee_id"], auth["channel_class"], start, end,
                                  exclude_id=auth["id"])
        R.check_window_rule(auth["licensee_id"], auth["retailer_name"],
                            auth["channel_class"], start, end, exclude_id=auth["id"])
        auth["status"] = "AUTHORIZED"
        auth["approved_by_user_id"] = ctx.uid
        touch(auth)
        domain.refresh_portfolio_aggregates(auth["licensee_id"])

    elif action == "SUSPEND":
        auth["status"] = "SUSPENDED"
        auth["suspension_reason"] = reason
        auth["suspended_at"] = db.now_iso()
        touch(auth)
        domain.refresh_portfolio_aggregates(auth["licensee_id"])

    elif action == "REINSTATE":
        live = domain.approved_sku_classes(auth["licensee_id"])
        if not any(sku in live for sku in auth["sku_classes"]):
            raise ApiError("ERR_INVALID_STATE",
                           "No approved submission covers this authorization's SKU classes.")
        auth["status"] = "AUTHORIZED"
        auth["suspension_reason"] = None
        auth["suspended_at"] = None
        touch(auth)
        domain.refresh_portfolio_aggregates(auth["licensee_id"])

    else:
        auth["status"] = "REVOKED"
        touch(auth)
        if status == "AUTHORIZED":
            domain.refresh_portfolio_aggregates(auth["licensee_id"])

    return response.ok(serializers.dump("RetailerAuthorization", auth))

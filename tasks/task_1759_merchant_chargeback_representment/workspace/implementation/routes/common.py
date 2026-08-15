"""Shared route helpers: existence checks, MerchantUser data hiding, list plumbing."""

from flask import g, request

from db import db
from errors import ApiError
from middleware import auth_ctx, is_merchant_user, require_roles
from response import ok_list
from util import pagination_params


def authenticate(allowed_roles):
    """Priority 1 (auth) then priority 2 (role)."""
    auth_ctx()
    require_roles(*allowed_roles)


ALL_ROLES = ("AcquirerOps", "MerchantUser", "RiskOfficer", "FinanceOps")


def get_or_404(store, rid, what="Resource"):
    rec = store.get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise ApiError(404, "ERR_NOT_FOUND", "%s not found" % what)
    return rec


def hide_if_cross_merchant(merchant_id):
    """MerchantUser touching another merchant's resource: existence hidden (404, never 403)."""
    if is_merchant_user() and merchant_id != g.uid:
        raise ApiError(404, "ERR_NOT_FOUND", "Resource not found")


def json_body():
    return request.get_json(silent=True)


def list_response(records, serialize):
    """created_at ascending; dict insertion order breaks ties (creation order)."""
    limit, offset = pagination_params(request.args)
    ordered = sorted(records, key=lambda r: r["created_at"])
    page = ordered[offset:offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, len(ordered))

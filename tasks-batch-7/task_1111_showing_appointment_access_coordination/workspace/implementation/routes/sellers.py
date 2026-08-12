"""Seller endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response
from services import core

bp = Blueprint("sellers", __name__)


@bp.post("/showing-desk/sellers")
def create_seller():
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "full_name": ("string", True),
        "contact_email": ("string", True),
        "approval_timeout_minutes": ("integer", False),
        "auto_approve": ("boolean", False),
    })
    mw.require_roles(caller, ["PlatformAdmin"])

    timeout = fields.get("approval_timeout_minutes", 240)
    if timeout < 1 or timeout > 10080:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "approval_timeout_minutes must be between 1 and 10080.", 400)
    seller = core.stamp_new({
        "full_name": fields["full_name"],
        "contact_email": fields["contact_email"],
        "approval_timeout_minutes": timeout,
        "auto_approve": fields.get("auto_approve", False),
    })
    db.sellers[seller["id"]] = seller
    return response.success_object(core.seller_view(seller), status=201)


def _get_seller_or_404(seller_id):
    seller = db.sellers.get(seller_id)
    if seller is None:
        raise errors.err(errors.ERR_SELLER_NOT_FOUND, "Seller not found.", 404)
    return seller


@bp.get("/showing-desk/sellers/<seller_id>")
def get_seller(seller_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["PlatformAdmin", "Seller"])
    seller = _get_seller_or_404(seller_id)
    if caller.role == "Seller" and caller.user_id != seller["id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Seller does not own this resource.", 403)
    return response.success_object(core.seller_view(seller))


@bp.patch("/showing-desk/sellers/<seller_id>/approval-settings")
def update_approval_settings(seller_id):
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "approval_timeout_minutes": ("integer", False),
        "auto_approve": ("boolean", False),
        "expected_seller_version": ("integer", True),
    })
    mw.require_roles(caller, ["Seller"])
    seller = _get_seller_or_404(seller_id)
    if caller.user_id != seller["id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Seller does not own this resource.", 403)
    # OCC (stage 6)
    if fields["expected_seller_version"] != seller["version"]:
        raise errors.err(errors.ERR_STALE_SELLER_VERSION,
                         "expected_seller_version does not match the seller's current version.",
                         412)
    if "approval_timeout_minutes" in fields:
        t = fields["approval_timeout_minutes"]
        if t < 1 or t > 10080:
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "approval_timeout_minutes must be between 1 and 10080.", 400)
        seller["approval_timeout_minutes"] = t
    if "auto_approve" in fields:
        seller["auto_approve"] = fields["auto_approve"]
    core.touch(seller)
    return response.success_object(core.seller_view(seller))

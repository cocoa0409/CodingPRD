"""Contact endpoints (§3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_VALIDATION
from middleware import authorized, READ_ROLES
from response import success_object
from services.core import (
    new_record, touch, public, cancel_pending_reminders_for_contact,
)
from routes.helpers import resolve_portfolio, resolve_contact, sorted_items, paged, parse_bool_query
from validate import get_body, req_str, req_enum, opt_bool

bp = Blueprint("contacts", __name__)

CONTACT_KINDS = ["ASSET_MANAGER", "BROKER", "LANDLORD_COUNSEL"]


@bp.post("/portfolios/<pid>/contacts")
def create_contact(pid):
    authorized(["PlatformAdmin", "AssetManager"])
    resolve_portfolio(pid)
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    kind = req_enum(body, "contact_kind", CONTACT_KINDS)
    is_active = opt_bool(body, "is_active", True)
    for c in db["contacts"].values():
        if c["portfolio_id"] == pid and c["email"] == email:
            raise_error(ERR_VALIDATION, "email must be unique within the portfolio")
    c = new_record("contacts", {
        "portfolio_id": pid,
        "full_name": full_name,
        "email": email,
        "contact_kind": kind,
        "is_active": is_active,
    })
    return success_object(public(c), 201)


@bp.get("/portfolios/<pid>/contacts")
def list_contacts(pid):
    authorized(READ_ROLES)
    resolve_portfolio(pid)
    is_active = parse_bool_query("is_active")
    items = sorted_items("contacts", {
        "portfolio_id": pid,
        "contact_kind": request.args.get("contact_kind"),
        "is_active": is_active,
    })
    return paged(items, public)


@bp.get("/portfolios/<pid>/contacts/<cid>")
def get_contact(pid, cid):
    authorized(READ_ROLES)
    _p, c = resolve_contact(pid, cid)
    return success_object(public(c))


@bp.patch("/portfolios/<pid>/contacts/<cid>")
def update_contact(pid, cid):
    authorized(["PlatformAdmin", "AssetManager"])
    _p, c = resolve_contact(pid, cid)
    body = get_body()
    if "full_name" in body:
        c["full_name"] = req_str(body, "full_name")
    if "email" in body:
        email = req_str(body, "email")
        for other in db["contacts"].values():
            if (other["portfolio_id"] == pid and other["id"] != cid
                    and other["email"] == email):
                raise_error(ERR_VALIDATION, "email must be unique within the portfolio")
        c["email"] = email
    if "is_active" in body:
        new_active = opt_bool(body, "is_active", c["is_active"])
        was_active = c["is_active"]
        c["is_active"] = new_active
        if was_active and not new_active:
            # deactivation cascade: this contact's PENDING reminders -> CANCELED
            cancel_pending_reminders_for_contact(cid)
    touch(c)
    return success_object(public(c))

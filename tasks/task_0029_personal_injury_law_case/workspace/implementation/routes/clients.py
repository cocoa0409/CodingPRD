"""Client routes (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from db import clients, stamp_common, bump, now_iso
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import require_str, get_or_404_path


bp = Blueprint("clients", __name__)


def _client_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "phone": c["phone"],
        "retainer_signed": c["retainer_signed"],
        "retainer_signed_at": c.get("retainer_signed_at"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/clients/register")
def register_client():
    # Public — Anonymous or Paralegal. Anonymous = no X-User-Role header.
    require_auth({"Anonymous", "Paralegal"}, allow_anonymous=True)()
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    phone = require_str(body, "phone")

    # Uniqueness on email (scaffold entity table: unique).
    for existing in clients.values():
        if existing["email"] == email:
            raise APIError(ERR_INVALID_REQUEST, 400, "email already in use")

    c = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "retainer_signed": False,
        "retainer_signed_at": None,
    }
    stamp_common(c)
    clients[c["id"]] = c
    return ok_object(_client_view(c), 201)


@bp.post("/clients/<cid>/sign-retainer")
def sign_retainer(cid):
    require_auth({"Paralegal"})()
    c = get_or_404_path(clients, cid, "Client")
    # Flipping from False -> True stamps retainer_signed_at; idempotent re-call
    # when already True still bumps updated_at/version per common-field rules
    # (mutation).
    if not c["retainer_signed"]:
        c["retainer_signed"] = True
        c["retainer_signed_at"] = db.get_current_utc()
    bump(c)
    return ok_object(_client_view(c), 200)


@bp.get("/clients/<cid>")
def get_client(cid):
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    c = get_or_404_path(clients, cid, "Client")
    return ok_object(_client_view(c), 200)


@bp.get("/clients")
def list_clients():
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    limit, offset = paginate_params(request.args)
    email_filter = request.args.get("email")
    items = [c for c in clients.values() if email_filter is None or c["email"] == email_filter]
    items.sort(key=lambda c: c["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array([_client_view(c) for c in page], limit, offset, total, 200)

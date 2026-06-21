"""Guardian routes (PRD §3.3) and guardian-scoped list reads."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import (
    require_roles,
    ROLE_GUARDIAN,
    ROLE_DIRECTOR,
    ROLE_BILLING,
)
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import (
    make_record,
    serialize,
    serialize_list,
    sort_by_created,
    get_body,
    require_str,
)
from services.lookups import get_guardian

bp = Blueprint("guardians", __name__)


def _validate_zip(value: str) -> None:
    if not (len(value) == 5 and value.isdigit()):
        raise APIError(ERR_INVALID_REQUEST, 400, "home_zip must be exactly 5 digits")


@bp.post("/guardians")
def create_guardian():
    # Anonymous is the only role permitted to register a guardian.
    require_roles("Anonymous")
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    phone = require_str(body, "phone")
    home_zip = require_str(body, "home_zip")
    _validate_zip(home_zip)

    # email unique among guardians, case-insensitive.
    lowered = email.strip().lower()
    for g in db.guardians.values():
        if g["email"].strip().lower() == lowered:
            raise APIError(ERR_INVALID_REQUEST, 400, "email already registered")

    rec = make_record(
        {
            "email": email,
            "full_name": full_name,
            "phone": phone,
            "home_zip": home_zip,
        }
    )
    db.guardians[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/guardians/<gid>")
def fetch_guardian(gid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING)
    rec = get_guardian(gid)
    return ok_object(serialize(rec), 200)


@bp.get("/guardians/<gid>/children")
def list_guardian_children(gid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR)
    get_guardian(gid)
    limit, offset = paginate_params(request.args)
    items = [c for c in db.children.values() if c["guardian_id"] == gid]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.get("/guardians/<gid>/invoices")
def list_guardian_invoices(gid):
    require_roles(ROLE_GUARDIAN, ROLE_BILLING)
    get_guardian(gid)
    limit, offset = paginate_params(request.args)
    status = request.args.get("status")
    items = [i for i in db.invoices.values() if i["guardian_id"] == gid]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)

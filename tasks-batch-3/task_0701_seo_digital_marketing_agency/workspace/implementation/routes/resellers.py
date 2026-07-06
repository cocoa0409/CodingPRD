"""Reseller routes."""
from flask import Blueprint, request

from auth import require_auth, require_role, VALID_ROLES, Principal
from db import store, base_record
from errors import err
from helpers import (
    get_body, require_str, require_number, opt_number, find,
    assert_owns_reseller, paginate,
)
from response import ok_object, ok_list

bp = Blueprint("resellers", __name__)


@bp.route("/resellers", methods=["POST"])
def create_reseller():
    # Bootstrap endpoint: auth headers not required (priority-1 skip), but if a
    # role header is present it must be permitted (priority-2 applies to all).
    role = request.headers.get("X-User-Role")
    if role is not None:
        if role not in VALID_ROLES:
            raise err("ERR_MISSING_AUTH", "Malformed X-User-Role header")
        require_role(Principal(request.headers.get("X-User-ID"), role), ["AgencyAdmin"])

    body = get_body()
    brand_name = require_str(body, "brand_name")
    markup_pct = require_number(body, "markup_pct", minimum=0.0, maximum=1.0)
    ppc_management_pct = opt_number(body, "ppc_management_pct", default=0.15, minimum=0.0, maximum=0.5)

    rec = base_record(versioned=True)
    rec.update({
        "brand_name": brand_name,
        "markup_pct": markup_pct,
        "ppc_management_pct": ppc_management_pct,
        "status": "ACTIVE",
    })
    store.resellers[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.route("/resellers/<rid>", methods=["GET"])
def get_reseller(rid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "Reseller"])
    reseller = find("reseller", rid)
    assert_owns_reseller(principal, reseller)
    return ok_object(reseller, 200)


@bp.route("/resellers", methods=["GET"])
def list_resellers():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin"])
    records = list(store.resellers.values())
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)

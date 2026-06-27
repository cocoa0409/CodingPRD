"""Family routes (PRD 3.1, 2.9, 3.9)."""
from flask import Blueprint

from db import common_fields, db, new_id, touch
from errors import err
from helpers import (lookup, paginate, require_fields, require_int, require_str,
                     sort_by_created)
from middleware import authenticate, get_json, require_owner
from response import success
from views import public, public_list

bp = Blueprint("families", __name__)


def _email_taken(email):
    norm = email.strip().lower()
    return any(f["email"].strip().lower() == norm for f in db.families.values())


@bp.route("/families", methods=["POST"])
def create_family():
    authenticate({"Anonymous", "StudioAdmin"})
    body = get_json()
    require_fields(body, ["email", "family_name"])
    email = require_str(body, "email")
    family_name = require_str(body, "family_name")
    if _email_taken(email):
        raise err("ERR_INVALID_REQUEST", "Email already registered.")
    fam = {
        "id": new_id(),
        "email": email,
        "family_name": family_name,
        "autopay_enabled": False,
        "payment_method_on_file": False,
        "account_credit_cents": 0,
        "sibling_count": 0,
        "status": "ACTIVE",
        **common_fields(),
    }
    db.families[fam["id"]] = fam
    return success(public(fam), status=201)


@bp.route("/families/<fid>", methods=["GET"])
def get_family(fid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    fam = lookup(db.families, fid)
    require_owner(role, user_id, fam["id"])
    return success(public(fam), status=200)


@bp.route("/families", methods=["GET"])
def list_families():
    authenticate({"StudioAdmin"})
    items = sort_by_created(list(db.families.values()))
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/families/<fid>", methods=["PATCH"])
def patch_family(fid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    fam = lookup(db.families, fid)
    require_owner(role, user_id, fam["id"])
    body = get_json()

    # Optional OCC echo (PRD 3.1). Not one of the §2.8 guarded writes, but
    # accepted as an optional input here.
    if "expected_family_version" in body and body["expected_family_version"] is not None:
        if body["expected_family_version"] != fam["version"]:
            raise err("ERR_STALE_VERSION", "Family version mismatch.")

    changed = False
    if "family_name" in body and body["family_name"] is not None:
        fam["family_name"] = require_str(body, "family_name")
        changed = True
    if "autopay_enabled" in body and body["autopay_enabled"] is not None:
        val = body["autopay_enabled"]
        if not isinstance(val, bool):
            raise err("ERR_INVALID_REQUEST", "autopay_enabled must be boolean.")
        if val and not fam["payment_method_on_file"]:
            raise err("ERR_NO_PAYMENT_METHOD",
                      "Enabling auto-pay requires a payment method on file.")
        fam["autopay_enabled"] = val
        changed = True
    if changed:
        touch(fam)
    return success(public(fam), status=200)


@bp.route("/families/<fid>/payment-method", methods=["POST"])
def add_payment_method(fid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    fam = lookup(db.families, fid)
    require_owner(role, user_id, fam["id"])
    body = get_json()
    require_fields(body, ["card_token"])
    require_str(body, "card_token")
    fam["payment_method_on_file"] = True
    touch(fam)
    return success(public(fam), status=200)


@bp.route("/families/<fid>/credit", methods=["POST"])
def grant_credit(fid):
    authenticate({"StudioAdmin"})
    fam = lookup(db.families, fid)
    body = get_json()
    require_fields(body, ["amount_cents"])
    amount = require_int(body, "amount_cents", lo=0)
    fam["account_credit_cents"] += amount
    touch(fam)
    return success(public(fam), status=200)

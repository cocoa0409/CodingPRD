"""Account routes (PRD §3.1)."""
from flask import Blueprint

from db import db, create_versioned, touch
from errors import err, ERR_INVALID_REQUEST
from helpers import get_json_body, require_fields, require_enum
from middleware import require_roles
from response import success
from serializers import serialize_account
from services.common import get_or_404, require_account_owner
from services.cascades import withdraw_estimated_matches_for_account

accounts_bp = Blueprint("accounts", __name__)


@accounts_bp.route("/dna/accounts", methods=["POST"])
def create_account():
    require_roles({"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["email", "full_name"])

    email = body["email"]
    if not isinstance(email, str) or email.strip() == "":
        raise err(ERR_INVALID_REQUEST, "email must be non-empty")
    # email unique across accounts
    for acc in db.accounts.values():
        if acc["email"] == email:
            raise err(ERR_INVALID_REQUEST, "email must be unique")

    data_residency = body.get("data_residency", "US")
    require_enum(data_residency, {"US", "EU"}, "data_residency")

    opt_in = body.get("relative_finder_opt_in", False)
    if not isinstance(opt_in, bool):
        raise err(ERR_INVALID_REQUEST, "relative_finder_opt_in must be boolean")

    rec = create_versioned(db.accounts, {
        "email": email,
        "full_name": body["full_name"],
        "data_residency": data_residency,
        "relative_finder_opt_in": opt_in,
    })
    return success(serialize_account(rec), status=201)


@accounts_bp.route("/dna/accounts/<rid>", methods=["GET"])
def get_account(rid):
    user_id, role = require_roles({"PlatformAdmin", "Account"})
    rec = get_or_404(db.accounts, rid)
    require_account_owner(rec["id"], user_id, role)
    return success(serialize_account(rec), status=200)


@accounts_bp.route("/dna/accounts/<rid>", methods=["PATCH"])
def update_account(rid):
    user_id, role = require_roles({"Account"})
    rec = get_or_404(db.accounts, rid)
    require_account_owner(rec["id"], user_id, role)

    body = get_json_body()
    require_fields(body, ["relative_finder_opt_in"])
    opt_in = body["relative_finder_opt_in"]
    if not isinstance(opt_in, bool):
        raise err(ERR_INVALID_REQUEST, "relative_finder_opt_in must be boolean")

    rec["relative_finder_opt_in"] = opt_in
    touch(rec)

    # cascade: setting account-level opt-in false auto-withdraws ESTIMATED
    # matches of this account's pets (PRD §3.1).
    if opt_in is False:
        withdraw_estimated_matches_for_account(rec["id"])

    return success(serialize_account(rec), status=200)

"""Pet routes (PRD §3.1)."""
from flask import Blueprint, request

from db import db, create_versioned, touch
from errors import err, ERR_INVALID_REQUEST
from helpers import (
    get_json_body, require_fields, require_enum, parse_pagination, paginate,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_pet
from services.common import get_or_404, require_account_owner
from services.cascades import withdraw_estimated_matches_for_pet

pets_bp = Blueprint("pets", __name__)


@pets_bp.route("/dna/pets", methods=["POST"])
def create_pet():
    user_id, role = require_roles({"Account"})
    body = get_json_body()
    require_fields(body, ["account_id", "name", "species", "birth_year"])

    account = get_or_404(db.accounts, body["account_id"])
    require_account_owner(account["id"], user_id, role)

    require_enum(body["species"], {"DOG", "CAT"}, "species")

    opt_in = body.get("relative_finder_opt_in", False)
    if not isinstance(opt_in, bool):
        raise err(ERR_INVALID_REQUEST, "relative_finder_opt_in must be boolean")

    rec = create_versioned(db.pets, {
        "account_id": account["id"],
        "name": body["name"],
        "species": body["species"],
        "birth_year": body["birth_year"],
        "relative_finder_opt_in": opt_in,
        "status": "REGISTERED",
        "finalized_report_id": None,
    })
    # registering a pet increments the owning account's pet_count (computed/
    # derived from pets; no stored counter to bump).
    return success(serialize_pet(rec), status=201)


@pets_bp.route("/dna/pets/<rid>", methods=["GET"])
def get_pet(rid):
    user_id, role = require_roles({"PlatformAdmin", "Account"})
    rec = get_or_404(db.pets, rid)
    require_account_owner(rec["account_id"], user_id, role)
    return success(serialize_pet(rec), status=200)


@pets_bp.route("/dna/pets", methods=["GET"])
def list_pets():
    user_id, role = require_roles({"PlatformAdmin", "Account"})
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")

    items = list(db.pets.values())
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if role == "Account":
        items = [p for p in items if p["account_id"] == user_id]

    window, total = paginate(items, limit, offset)
    return list_success([serialize_pet(p) for p in window], limit, offset, total)


@pets_bp.route("/dna/pets/<rid>", methods=["PATCH"])
def update_pet(rid):
    user_id, role = require_roles({"Account"})
    rec = get_or_404(db.pets, rid)
    require_account_owner(rec["account_id"], user_id, role)

    body = get_json_body()
    require_fields(body, ["relative_finder_opt_in"])
    opt_in = body["relative_finder_opt_in"]
    if not isinstance(opt_in, bool):
        raise err(ERR_INVALID_REQUEST, "relative_finder_opt_in must be boolean")

    rec["relative_finder_opt_in"] = opt_in
    touch(rec)

    # cascade: setting false withdraws ESTIMATED RelativeMatch referencing this
    # pet (PRD §3.1).
    if opt_in is False:
        withdraw_estimated_matches_for_pet(rec["id"])

    return success(serialize_pet(rec), status=200)

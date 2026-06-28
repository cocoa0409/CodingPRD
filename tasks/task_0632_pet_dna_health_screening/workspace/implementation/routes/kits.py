"""Kit routes (PRD §3.2)."""
import uuid

from flask import Blueprint, request

from db import db, create_versioned, touch
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
)
from helpers import (
    get_json_body, require_fields, require_enum, parse_pagination, paginate,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_kit
from services.common import get_or_404, require_account_owner, assert_not_purge_pending

kits_bp = Blueprint("kits", __name__)


def _mint_barcode():
    return "KIT-" + uuid.uuid4().hex.upper()


@kits_bp.route("/dna/kits", methods=["POST"])
def create_kit():
    user_id, role = require_roles({"Account"})
    body = get_json_body()
    require_fields(body, ["account_id", "product_tier"])

    account = get_or_404(db.accounts, body["account_id"])
    require_account_owner(account["id"], user_id, role)
    require_enum(body["product_tier"], {"BREED", "BREED_HEALTH"}, "product_tier")

    rec = create_versioned(db.kits, {
        "account_id": account["id"],
        "barcode": _mint_barcode(),
        "product_tier": body["product_tier"],
        "status": "ORDERED",
        "activated_pet_id": None,
    })
    return success(serialize_kit(rec), status=201)


@kits_bp.route("/dna/kits/<rid>", methods=["GET"])
def get_kit(rid):
    user_id, role = require_roles({"PlatformAdmin", "Account", "LabTechnician"})
    rec = get_or_404(db.kits, rid)
    require_account_owner(rec["account_id"], user_id, role)
    return success(serialize_kit(rec), status=200)


@kits_bp.route("/dna/kits", methods=["GET"])
def list_kits():
    user_id, role = require_roles({"PlatformAdmin", "Account"})
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    activated_pet_id = request.args.get("activated_pet_id")

    items = list(db.kits.values())
    if account_id is not None:
        items = [k for k in items if k["account_id"] == account_id]
    if activated_pet_id is not None:
        items = [k for k in items if k["activated_pet_id"] == activated_pet_id]
    if role == "Account":
        items = [k for k in items if k["account_id"] == user_id]

    window, total = paginate(items, limit, offset)
    return list_success([serialize_kit(k) for k in window], limit, offset, total)


@kits_bp.route("/dna/kits/<rid>/activate", methods=["POST"])
def activate_kit(rid):
    user_id, role = require_roles({"Account"})
    rec = get_or_404(db.kits, rid)
    require_account_owner(rec["account_id"], user_id, role)

    body = get_json_body()
    require_fields(body, ["pet_id"])
    pet = get_or_404(db.pets, body["pet_id"])

    # State: kit must be ORDERED (ERR_INVALID_STATE, priority 5).
    if rec["status"] != "ORDERED":
        raise err(ERR_INVALID_STATE, "Kit is not in ORDERED state")

    # purge-in-progress freeze (priority 8) comes after state in PRD §2.8.
    assert_not_purge_pending(rec["account_id"])

    # Business referential: pet belongs to same account; pet REGISTERED.
    if pet["account_id"] != rec["account_id"]:
        raise err(ERR_INVALID_REQUEST, "Pet does not belong to the kit's account")
    if pet["status"] != "REGISTERED":
        raise err(ERR_INVALID_REQUEST, "Pet is not in REGISTERED state")

    rec["activated_pet_id"] = pet["id"]
    rec["status"] = "ACTIVATED"
    touch(rec)
    return success(serialize_kit(rec), status=200)


@kits_bp.route("/dna/kits/<rid>/void", methods=["POST"])
def void_kit(rid):
    user_id, role = require_roles({"Account"})
    rec = get_or_404(db.kits, rid)
    require_account_owner(rec["account_id"], user_id, role)

    # Only a kit still in ORDERED may be voided (ERR_INVALID_STATE).
    if rec["status"] != "ORDERED":
        raise err(ERR_INVALID_STATE, "Only an ORDERED kit may be voided")

    rec["status"] = "VOIDED"
    touch(rec)
    return success(serialize_kit(rec), status=200)

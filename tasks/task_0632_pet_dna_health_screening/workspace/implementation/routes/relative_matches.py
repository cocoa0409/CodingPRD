"""Relative-finder match routes (PRD §3.6)."""
from flask import Blueprint, request

from db import db, create_versioned, touch
from errors import (
    err, ERR_INVALID_STATE, ERR_REPORTS_NOT_FINALIZED,
    ERR_RELATIVE_FINDER_NOT_OPTED_IN, ERR_INVALID_RANGE, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_REQUEST,
)
from helpers import (
    get_json_body, require_fields, parse_pagination, paginate,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_relative_match
from services.common import get_or_404, assert_not_purge_pending
from services.calculations import compute_relationship_pct

relative_matches_bp = Blueprint("relative_matches", __name__)


def _pet_opted_in(pet):
    """Two-level relative-finder check: both account-level and pet-level
    relative_finder_opt_in must be true (PRD §3.1)."""
    account = db.accounts.get(pet["account_id"])
    if account is None:
        return False
    return bool(account["relative_finder_opt_in"]) and bool(pet["relative_finder_opt_in"])


@relative_matches_bp.route("/dna/relative-matches", methods=["POST"])
def create_match():
    require_roles({"LabTechnician"})
    body = get_json_body()
    require_fields(body, ["pet_id", "relative_pet_id", "shared_cm"])

    # Existence left-to-right.
    pet = get_or_404(db.pets, body["pet_id"])
    relative_pet = get_or_404(db.pets, body["relative_pet_id"])

    # purge-in-progress freeze (priority 8): creating a match is blocked while
    # either pet's account is purge_pending.
    assert_not_purge_pending(pet["account_id"])
    assert_not_purge_pending(relative_pet["account_id"])

    # Relative-finder opt-in (priority 7).
    if not _pet_opted_in(pet) or not _pet_opted_in(relative_pet):
        raise err(ERR_RELATIVE_FINDER_NOT_OPTED_IN,
                  "Both pets must satisfy account- and pet-level opt-in")

    # Numeric range (priority 13): shared_cm in [0, 2500].
    shared_cm = body["shared_cm"]
    if not isinstance(shared_cm, (int, float)) or isinstance(shared_cm, bool):
        raise err(ERR_INVALID_REQUEST, "shared_cm must be numeric")
    if shared_cm < 0 or shared_cm > 2500:
        raise err(ERR_INVALID_RANGE, "shared_cm out of range [0,2500]")

    relationship_pct = compute_relationship_pct(shared_cm, confirmed=False)

    rec = create_versioned(db.relative_matches, {
        "pet_id": pet["id"],
        "relative_pet_id": relative_pet["id"],
        "shared_cm": shared_cm,
        "relationship_pct": relationship_pct,
        "status": "ESTIMATED",
    })
    return success(serialize_relative_match(rec), status=201)


@relative_matches_bp.route("/dna/relative-matches/<rid>", methods=["GET"])
def get_match(rid):
    user_id, role = require_roles({"PlatformAdmin", "Account", "LabTechnician"})
    rec = get_or_404(db.relative_matches, rid)
    if role == "Account":
        _require_either_pet_owner(rec, user_id)
    return success(serialize_relative_match(rec), status=200)


@relative_matches_bp.route("/dna/relative-matches", methods=["GET"])
def list_matches():
    user_id, role = require_roles({"PlatformAdmin", "Account", "LabTechnician"})
    limit, offset = parse_pagination()
    pet_id = request.args.get("pet_id")
    relative_pet_id = request.args.get("relative_pet_id")

    items = list(db.relative_matches.values())
    if pet_id is not None:
        items = [m for m in items if m["pet_id"] == pet_id]
    if relative_pet_id is not None:
        items = [m for m in items if m["relative_pet_id"] == relative_pet_id]
    if role == "Account":
        owned_pet_ids = {p["id"] for p in db.pets.values() if p["account_id"] == user_id}
        items = [m for m in items
                 if m["pet_id"] in owned_pet_ids or m["relative_pet_id"] in owned_pet_ids]

    window, total = paginate(items, limit, offset)
    return list_success(
        [serialize_relative_match(m) for m in window], limit, offset, total
    )


def _require_either_pet_owner(match, user_id):
    """For a RelativeMatch, either pet's owner is an authorised actor."""
    pet = db.pets.get(match["pet_id"])
    relative_pet = db.pets.get(match["relative_pet_id"])
    owners = set()
    if pet:
        owners.add(pet["account_id"])
    if relative_pet:
        owners.add(relative_pet["account_id"])
    if user_id not in owners:
        raise err(ERR_NOT_RESOURCE_OWNER, "Acting account owns neither pet")


@relative_matches_bp.route("/dna/relative-matches/<rid>/confirm", methods=["POST"])
def confirm_match(rid):
    require_roles({"LabTechnician"})
    rec = get_or_404(db.relative_matches, rid)

    # State precondition (priority 5): must be ESTIMATED.
    if rec["status"] != "ESTIMATED":
        raise err(ERR_INVALID_STATE, "Match is not in ESTIMATED state")

    # Cross-entity precondition (priority 6): both pets have a FINALIZED report.
    pet = db.pets.get(rec["pet_id"])
    relative_pet = db.pets.get(rec["relative_pet_id"])
    if (not pet or pet.get("finalized_report_id") is None
            or not relative_pet or relative_pet.get("finalized_report_id") is None):
        raise err(ERR_REPORTS_NOT_FINALIZED,
                  "Both pets must have a FINALIZED report to confirm")

    rec["status"] = "CONFIRMED"
    rec["relationship_pct"] = compute_relationship_pct(rec["shared_cm"], confirmed=True)
    touch(rec)
    return success(serialize_relative_match(rec), status=200)


@relative_matches_bp.route("/dna/relative-matches/<rid>/withdraw", methods=["POST"])
def withdraw_match(rid):
    user_id, role = require_roles({"Account"})
    rec = get_or_404(db.relative_matches, rid)

    # Ownership: actor must own either pet_id or relative_pet_id.
    _require_either_pet_owner(rec, user_id)

    # Withdrawable from ESTIMATED or CONFIRMED.
    if rec["status"] not in ("ESTIMATED", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "Match cannot be withdrawn from its current state")

    rec["status"] = "WITHDRAWN"
    touch(rec)
    return success(serialize_relative_match(rec), status=200)

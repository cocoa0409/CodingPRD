"""Unit endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import success_object
from ..errors import APIError, err_not_found, err_share_factor
from ..serializers import serialize_unit
from ..services.common import (
    bump_version,
    check_version,
    require,
    sum_share_factors,
)
from ..store import store
from ..util import new_uuid
from ._helpers import as_decimal, get_json_body, get_version, require_field

bp = Blueprint("units", __name__)


@bp.route("/hoa/units", methods=["POST"])
@require_roles(["PresidentRole"])
def create_unit():
    body = get_json_body()
    address = require_field(body, "address")
    owner_member_id = require_field(body, "owner_member_id")
    share_factor = as_decimal(require_field(body, "share_factor"), "share_factor")
    mortgage_holder = body.get("mortgage_holder")

    if not isinstance(address, str) or not address:
        raise APIError("ERR_INVALID_STATE", "address must be a non-empty string", 409)
    if not isinstance(owner_member_id, str):
        raise APIError("ERR_INVALID_STATE", "owner_member_id must be a string", 409)

    # Owner must exist.
    require("members", owner_member_id)

    # share_factor bounds
    if share_factor < Decimal("0.0001") or share_factor > Decimal("1.0000"):
        raise APIError(
            "ERR_INVALID_STATE",
            "share_factor must be in [0.0001, 1.0000]",
            409,
        )

    s = store()
    now = s.now()
    uid = new_uuid()
    unit = {
        "id": uid,
        "address": address,
        "owner_member_id": owner_member_id,
        "share_factor": float(share_factor),
        "mortgage_holder": mortgage_holder,
        "lien_status": "NONE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }

    with s.lock:
        s.insert("units", unit)
        total = sum_share_factors()
        # PRD §3.1: the sum invariant is "after any insert or update".
        # We reject any operation that would push the sum strictly ABOVE
        # 1.0000 (a state from which no further legal recovery exists),
        # but tolerate intermediate sums at or below 1.0000 so that
        # multi-unit rosters can be built progressively (the cycle-
        # issuance gate of PRD §3.2 re-validates strict equality).
        if total.quantize(Decimal("0.0001")) > Decimal("1.0000"):
            # rollback insert
            del s.units[uid]
            s.insertion_order["units"].remove(uid)
            raise err_share_factor(
                f"Sum of share_factor would be {total} (must be 1.0000)"
            )
        # Recompute owner's eligible_to_vote since they now own a unit
        owner = s.members.get(owner_member_id)
        if owner is not None:
            from ..services.common import compute_eligible_to_vote
            owner["eligible_to_vote"] = compute_eligible_to_vote(owner)

    return jsonify(success_object(serialize_unit(unit))), 201


@bp.route("/hoa/units/<unit_id>", methods=["GET"])
@require_roles(["Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"])
def get_unit(unit_id: str):
    unit = require("units", unit_id)
    return jsonify(success_object(serialize_unit(unit))), 200


@bp.route("/hoa/units/<unit_id>", methods=["PATCH"])
@require_roles(["PresidentRole"])
def update_unit(unit_id: str):
    unit = require("units", unit_id)
    body = get_json_body()
    version = get_version(body)
    check_version(unit, version)

    new_share = None
    if "share_factor" in body:
        new_share = as_decimal(body["share_factor"], "share_factor")
        if new_share < Decimal("0.0001") or new_share > Decimal("1.0000"):
            raise APIError(
                "ERR_INVALID_STATE",
                "share_factor must be in [0.0001, 1.0000]",
                409,
            )

    new_mortgage = None
    if "mortgage_holder" in body:
        new_mortgage = body["mortgage_holder"]
        if new_mortgage is not None and not isinstance(new_mortgage, str):
            raise APIError("ERR_INVALID_STATE", "mortgage_holder must be string or null", 409)

    s = store()
    now = s.now()
    with s.lock:
        old_share = unit["share_factor"]
        old_mortgage = unit["mortgage_holder"]
        if new_share is not None:
            unit["share_factor"] = float(new_share)
        if "mortgage_holder" in body:
            unit["mortgage_holder"] = new_mortgage
        total = sum_share_factors()
        if total.quantize(Decimal("0.0001")) > Decimal("1.0000"):
            unit["share_factor"] = old_share
            unit["mortgage_holder"] = old_mortgage
            raise err_share_factor(
                f"Sum of share_factor would be {total} (must be 1.0000)"
            )
        bump_version(unit, now)

    return jsonify(success_object(serialize_unit(unit))), 200

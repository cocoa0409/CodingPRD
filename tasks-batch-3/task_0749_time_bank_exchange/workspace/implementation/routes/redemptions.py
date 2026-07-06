"""Redemption routes — OCC-guarded creation."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_MEMBER, ROLE_ADMIN
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND,
                    ERR_OWNERSHIP_VIOLATION, ERR_MEMBER_SUSPENDED,
                    ERR_INSUFFICIENT_BALANCE, ERR_STALE_MEMBER_VERSION,
                    ERR_INVALID_STATE)
from response import envelope_object, envelope_array
from services import validators, pagination, balance, ledger
from services.reward_catalog import resolve_cost
from services.serializers import redemption_dto

bp = Blueprint("redemptions", __name__)


@bp.route("/redemptions", methods=["POST"])
def create_redemption():
    user_id, _ = require_role({ROLE_MEMBER})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, ["member_id", "reward_code", "expected_member_version"])
    member_id = validators.require_str(payload, "member_id")
    reward_code = validators.require_str(payload, "reward_code")
    ex_ver = validators.require_int(payload, "expected_member_version")

    m = db.members.get(member_id)
    if m is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Member not found")

    # Priority 5: OCC gate
    if m["version"] != ex_ver:
        raise_err(ERR_STALE_MEMBER_VERSION,
                  f"expected_member_version {ex_ver} does not match current {m['version']}")

    # Priority 6: ownership
    if member_id != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal redemption.member_id")

    # Priority 7: suspension
    balance.recompute_member_snapshot(member_id, bump_version=False)
    if m["is_suspended"]:
        raise_err(ERR_MEMBER_SUSPENDED, "member is suspended")

    # Priority 14: reward code -> minutes_cost
    minutes_cost = resolve_cost(reward_code)
    if minutes_cost is None or minutes_cost <= 0:
        raise_err(ERR_INVALID_REQUEST, f"unknown reward_code {reward_code}")

    # Priority 8: forward-looking balance
    if m["forward_looking_balance_minutes"] < minutes_cost:
        raise_err(ERR_INSUFFICIENT_BALANCE, "insufficient forward-looking balance")

    r = {
        "member_id": member_id,
        "reward_code": reward_code,
        "minutes_cost": minutes_cost,
        "expected_member_version": ex_ver,
        "status": "REQUESTED",
        "fulfilled_at_utc": None,
    }
    db.stamp_new(r)
    db.redemptions[r["id"]] = r

    # Bump member version (redemption creation is a member-scoped mutation)
    db.touch(m)
    return envelope_object(redemption_dto(r), status=201)


@bp.route("/redemptions", methods=["GET"])
def list_redemptions():
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    items = list(db.redemptions.values())
    for k in ("member_id", "status"):
        v = request.args.get(k)
        if v is not None:
            items = [x for x in items if x[k] == v]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([redemption_dto(x) for x in window], limit, offset, total)


@bp.route("/redemptions/<rid>", methods=["GET"])
def get_redemption(rid):
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    r = db.redemptions.get(rid)
    if r is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Redemption not found")
    return envelope_object(redemption_dto(r), status=200)


@bp.route("/redemptions/<rid>/fulfill", methods=["POST"])
def fulfill(rid):
    require_role({ROLE_ADMIN})
    r = db.redemptions.get(rid)
    if r is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Redemption not found")
    if r["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "Redemption.status must be REQUESTED")
    m = db.members.get(r["member_id"])
    if m is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Member not found")
    balance.recompute_member_snapshot(m["id"], bump_version=False)
    if m["forward_looking_balance_minutes"] < r["minutes_cost"]:
        raise_err(ERR_INSUFFICIENT_BALANCE, "member balance insufficient at fulfillment")

    r["status"] = "FULFILLED"
    r["fulfilled_at_utc"] = db.get_clock_iso()
    db.touch(r)
    ledger.post_entry(member_id=m["id"], entry_kind="REDEMPTION",
                      delta_minutes=-r["minutes_cost"], redemption_id=rid)
    balance.recompute_member_snapshot(m["id"], bump_version=True)
    return envelope_object(redemption_dto(r), status=200)


@bp.route("/redemptions/<rid>/void", methods=["POST"])
def void(rid):
    require_role({ROLE_ADMIN})
    r = db.redemptions.get(rid)
    if r is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Redemption not found")
    if r["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "Redemption.status must be REQUESTED")
    r["status"] = "VOIDED"
    db.touch(r)
    return envelope_object(redemption_dto(r), status=200)

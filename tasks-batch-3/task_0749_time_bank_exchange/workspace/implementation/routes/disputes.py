"""Dispute routes."""
from flask import Blueprint, request
import db
from auth import require_role, ROLE_MEMBER, ROLE_ADMIN
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND,
                    ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE)
from response import envelope_object, envelope_array
from services import validators, pagination, balance, ledger
from services.serializers import dispute_dto

bp = Blueprint("disputes", __name__)

REASON_CODES = {"NO_SHOW", "INCOMPLETE_SERVICE", "WRONG_DURATION", "OTHER"}


@bp.route("/disputes", methods=["POST"])
def create_dispute():
    user_id, _ = require_role({ROLE_MEMBER})
    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, [
        "exchange_id", "raised_by_member_id", "reason_code", "claimed_delta_minutes"
    ])
    exchange_id = validators.require_str(payload, "exchange_id")
    raised_by = validators.require_str(payload, "raised_by_member_id")
    reason = validators.require_enum(payload, "reason_code", REASON_CODES)
    claimed = validators.require_minute_multiple(payload, "claimed_delta_minutes", 15, 480)
    if claimed <= 0:
        raise_err(ERR_INVALID_REQUEST, "claimed_delta_minutes must be a positive multiple of 15")

    x = db.exchanges.get(exchange_id)
    if x is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Exchange not found")
    if x["status"] != "DELIVERED":
        raise_err(ERR_INVALID_STATE, "Exchange.status must be DELIVERED")
    if raised_by not in (x["provider_member_id"], x["requester_member_id"]):
        raise_err(ERR_OWNERSHIP_VIOLATION, "raised_by must be a party to the exchange")
    if raised_by != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal raised_by_member_id")

    d = {
        "exchange_id": exchange_id,
        "raised_by_member_id": raised_by,
        "reason_code": reason,
        "claimed_delta_minutes": claimed,
        "status": "OPEN",
        "admin_notes": None,
    }
    db.stamp_new(d)
    db.disputes[d["id"]] = d

    # Cascade: Exchange DELIVERED -> DISPUTED
    x["status"] = "DISPUTED"
    db.touch(x)

    return envelope_object(dispute_dto(d), status=201)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    limit, offset = pagination.parse_pagination()
    items = list(db.disputes.values())
    for k in ("exchange_id", "raised_by_member_id", "status"):
        v = request.args.get(k)
        if v is not None:
            items = [x for x in items if x[k] == v]
    window, total = pagination.sort_and_page(items, limit, offset)
    return envelope_array([dispute_dto(x) for x in window], limit, offset, total)


@bp.route("/disputes/<did>", methods=["GET"])
def get_dispute(did):
    require_role({ROLE_MEMBER, ROLE_ADMIN})
    d = db.disputes.get(did)
    if d is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Dispute not found")
    return envelope_object(dispute_dto(d), status=200)


@bp.route("/disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    require_role({ROLE_ADMIN})
    d = db.disputes.get(did)
    if d is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Dispute not found")
    if d["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Dispute.status must be OPEN")

    payload = request.get_json(silent=True) or {}
    validators.require_fields(payload, ["outcome"])
    outcome = validators.require_enum(payload, "outcome", {"UPHELD", "REJECTED"})
    notes = validators.optional_str(payload, "admin_notes")
    if outcome == "UPHELD":
        if not notes:
            raise_err(ERR_INVALID_REQUEST, "admin_notes is required on UPHELD")

    d["admin_notes"] = notes
    x = db.exchanges.get(d["exchange_id"])
    if x is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Exchange not found")

    if outcome == "REJECTED":
        d["status"] = "RESOLVED_REJECTED"
        db.touch(d)
        x["status"] = "DELIVERED"
        db.touch(x)
        return envelope_object(dispute_dto(d), status=200)

    # UPHELD: settle with reduced credit
    d["status"] = "RESOLVED_UPHELD"
    db.touch(d)
    committed = x["committed_minutes"]
    claimed = d["claimed_delta_minutes"]
    reduced = committed - claimed
    x["status"] = "SETTLED"
    x["settled_at_utc"] = db.get_clock_iso()
    db.touch(x)
    # Ledger entries
    ledger.post_entry(member_id=x["requester_member_id"], entry_kind="SPENT",
                      delta_minutes=-reduced, exchange_id=x["id"])
    ledger.post_entry(member_id=x["provider_member_id"], entry_kind="EARNED",
                      delta_minutes=+reduced, exchange_id=x["id"])
    deficient = (x["provider_member_id"]
                 if d["raised_by_member_id"] == x["requester_member_id"]
                 else x["requester_member_id"])
    ledger.post_entry(member_id=deficient, entry_kind="DISPUTE_REVERSAL",
                      delta_minutes=-claimed, exchange_id=x["id"], memo=d["id"])
    balance.recompute_member_snapshot(x["requester_member_id"], bump_version=True)
    balance.recompute_member_snapshot(x["provider_member_id"], bump_version=True)
    # Request MATCHED -> CLOSED
    req = db.skill_requests.get(x["request_id"])
    if req is not None and req["status"] == "MATCHED":
        req["status"] = "CLOSED"
        db.touch(req)
    return envelope_object(dispute_dto(d), status=200)


@bp.route("/disputes/<did>/withdraw", methods=["POST"])
def withdraw_dispute(did):
    user_id, _ = require_role({ROLE_MEMBER})
    d = db.disputes.get(did)
    if d is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Dispute not found")
    if d["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Dispute.status must be OPEN")
    if d["raised_by_member_id"] != user_id:
        raise_err(ERR_OWNERSHIP_VIOLATION, "acting member must equal dispute.raised_by_member_id")
    d["status"] = "WITHDRAWN"
    db.touch(d)
    # Exchange DISPUTED -> DELIVERED
    x = db.exchanges.get(d["exchange_id"])
    if x is not None and x["status"] == "DISPUTED":
        x["status"] = "DELIVERED"
        db.touch(x)
    return envelope_object(dispute_dto(d), status=200)

"""BureauFurnishing and BureauDispute (e-OSCAR) endpoints."""
from flask import Blueprint, request

from clock import clock, format_iso8601, add_days
from db import db, stamp_create, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_VALIDATION_HOLD, ERR_FURNISH_BLOCKED,
)
from middleware import require_roles
from response import object_response, array_response
from serializers import serialize_bureau_furnishing, serialize_bureau_dispute
from pagination import paginate
from validation import get_body, require_str, require_enum

bp = Blueprint("bureau", __name__)

BUREAUS = {"EQUIFAX", "EXPERIAN", "TRANSUNION"}
BUREAU_OUTCOMES = {"VERIFIED", "CORRECTED", "DELETED"}


def _account_has_unresolved_dispute(account_id):
    for d in db.disputes.values():
        if d["account_id"] != account_id:
            continue
        if d["dispute_type"] in ("ACCURACY", "VALIDATION") and d["status"] in (
            "OPEN", "INVESTIGATING", "REOPENED"
        ):
            return True
    return False


# ---- BureauFurnishing ----
@bp.route("/bureau-furnishings", methods=["POST"])
@require_roles("ComplianceOfficer", "BureauOperator")
def furnish():
    body = get_body()
    account_id = require_str(body, "account_id")
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError(*ERR_NOT_FOUND, message="Account not found")
    bureau = require_enum(body, "bureau", BUREAUS)
    # Validation hold surfaces as ERR_VALIDATION_HOLD (priority 7) before the
    # general furnish guardrail (priority 13).
    if account["contact_status"] == "VALIDATION_HELD":
        raise ApiError(*ERR_VALIDATION_HOLD, message="Account under validation hold")
    if account["work_status"] in ("RECALLED", "CLOSED_UNCOLLECTIBLE"):
        raise ApiError(*ERR_FURNISH_BLOCKED, message="Account state blocks furnishing")
    if _account_has_unresolved_dispute(account_id):
        raise ApiError(*ERR_FURNISH_BLOCKED, message="Unresolved dispute blocks furnishing")

    f = stamp_create({
        "account_id": account_id,
        "bureau": bureau,
        "furnished_balance_cents": account["balance_cents"],
        "status": "REPORTED",
    })
    db.bureau_furnishings[f["id"]] = f
    return object_response(serialize_bureau_furnishing(f), status=201)


@bp.route("/bureau-furnishings/<fid>", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "BureauOperator", "System")
def get_furnishing(fid):
    f = db.bureau_furnishings.get(fid)
    if f is None:
        raise ApiError(*ERR_NOT_FOUND, message="BureauFurnishing not found")
    return object_response(serialize_bureau_furnishing(f), status=200)


@bp.route("/bureau-furnishings", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "BureauOperator", "System")
def list_furnishings():
    items = list(db.bureau_furnishings.values())
    account_id = request.args.get("account_id")
    if account_id:
        items = [f for f in items if f["account_id"] == account_id]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_bureau_furnishing(f) for f in page], limit, offset, total)


# ---- BureauDispute ----
@bp.route("/bureau-disputes", methods=["POST"])
@require_roles("BureauOperator")
def open_bureau_dispute():
    body = get_body()
    furnishing_id = require_str(body, "furnishing_id")
    furnishing = db.bureau_furnishings.get(furnishing_id)
    if furnishing is None:
        raise ApiError(*ERR_NOT_FOUND, message="BureauFurnishing not found")
    now = clock.now
    bd = stamp_create({
        "furnishing_id": furnishing_id,
        "opened_at": format_iso8601(now),
        "investigation_deadline": format_iso8601(add_days(now, 30)),
        "outcome": None,
        "status": "OPEN",
    })
    db.bureau_disputes[bd["id"]] = bd
    return object_response(serialize_bureau_dispute(bd), status=201)


@bp.route("/bureau-disputes/<bid>", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "BureauOperator", "System")
def get_bureau_dispute(bid):
    bd = db.bureau_disputes.get(bid)
    if bd is None:
        raise ApiError(*ERR_NOT_FOUND, message="BureauDispute not found")
    return object_response(serialize_bureau_dispute(bd), status=200)


@bp.route("/bureau-disputes", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "BureauOperator", "System")
def list_bureau_disputes():
    items = list(db.bureau_disputes.values())
    furnishing_id = request.args.get("furnishing_id")
    if furnishing_id:
        items = [b for b in items if b["furnishing_id"] == furnishing_id]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_bureau_dispute(b) for b in page], limit, offset, total)


@bp.route("/bureau-disputes/<bid>/resolve", methods=["POST"])
@require_roles("BureauOperator")
def resolve_bureau_dispute(bid):
    bd = db.bureau_disputes.get(bid)
    if bd is None:
        raise ApiError(*ERR_NOT_FOUND, message="BureauDispute not found")
    if bd["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(*ERR_INVALID_STATE, message="BureauDispute cannot be resolved from its current state")
    body = get_body()
    outcome = require_enum(body, "outcome", BUREAU_OUTCOMES)
    bd["status"] = "RESOLVED"
    bd["outcome"] = outcome
    touch(bd)
    furnishing = db.bureau_furnishings.get(bd["furnishing_id"])
    if furnishing is not None:
        if outcome == "CORRECTED":
            furnishing["status"] = "UPDATED"
            account = db.accounts.get(furnishing["account_id"])
            if account is not None:
                furnishing["furnished_balance_cents"] = account["balance_cents"]
            touch(furnishing)
        elif outcome == "DELETED":
            furnishing["status"] = "DELETED"
            touch(furnishing)
        # VERIFIED: furnishing unchanged.
    return object_response(serialize_bureau_dispute(bd), status=200)


@bp.route("/bureau-disputes/<bid>/reopen", methods=["POST"])
@require_roles("BureauOperator")
def reopen_bureau_dispute(bid):
    bd = db.bureau_disputes.get(bid)
    if bd is None:
        raise ApiError(*ERR_NOT_FOUND, message="BureauDispute not found")
    if bd["status"] != "RESOLVED":
        raise ApiError(*ERR_INVALID_STATE, message="Only a RESOLVED bureau dispute can be reopened")
    bd["status"] = "REOPENED"
    bd["outcome"] = None
    touch(bd)
    return object_response(serialize_bureau_dispute(bd), status=200)

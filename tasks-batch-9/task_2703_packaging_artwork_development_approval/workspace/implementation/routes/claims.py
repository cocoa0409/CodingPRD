"""PRD 3.2 - the marketing claim library and time-bounded legal clearance."""
from flask import Blueprint, request

import calc
from core import fmt_dt, new_row, parse_dt, rows, touch
from errors import fail, invalid
from http_util import (
    ALL_ROLES,
    auth,
    body_fields,
    created,
    load,
    need_enum,
    need_string,
    ok,
    paginate,
)
from serialize import claim_json

bp = Blueprint("claims", __name__)


@bp.route("/marketing-claims", methods=["POST"])
def create_claim():
    auth(["PackagingCoordinator"])
    body = body_fields(
        ["claim_code", "claim_text", "claim_type", "market_code", "substantiation_ref"]
    )
    claim_code = need_string(body, "claim_code", 3, 40, calc.CLAIM_CODE_PATTERN)
    claim_text = need_string(body, "claim_text", 3, 300)
    claim_type = need_enum(body, "claim_type", calc.CLAIM_TYPES)
    market_code = need_string(body, "market_code", 2, 2, calc.MARKET_CODE_PATTERN)
    substantiation_ref = need_string(body, "substantiation_ref", 3, 80)

    row = new_row(
        "claims",
        {
            "claim_code": claim_code,
            "claim_text": claim_text,
            "claim_type": claim_type,
            "market_code": market_code,
            "substantiation_ref": substantiation_ref,
            "legal_status": "DRAFT",
            "cleared_from_utc": None,
            "cleared_until_utc": None,
            "cleared_by_user_id": None,
            "rejection_reason": None,
        },
    )
    return created(claim_json(row))


@bp.route("/marketing-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    auth(ALL_ROLES)
    return ok(claim_json(load("claims", claim_id)))


@bp.route("/marketing-claims", methods=["GET"])
def list_claims():
    auth(ALL_ROLES)
    items = rows("claims")
    claim_code = request.args.get("claim_code")
    market_code = request.args.get("market_code")
    legal_status = request.args.get("legal_status")
    if claim_code:
        items = [c for c in items if c["claim_code"] == claim_code]
    if market_code:
        items = [c for c in items if c["market_code"] == market_code]
    if legal_status:
        items = [c for c in items if c["legal_status"] == legal_status]
    items = sorted(items, key=lambda c: (c["created_at"], c["_seq"]))
    return paginate(items, claim_json)


@bp.route("/marketing-claims/<claim_id>/clearance", methods=["POST"])
def clear_claim(claim_id):
    user_id, _role = auth(["LegalReviewer"])
    claim = load("claims", claim_id)
    body = body_fields(
        ["decision"], ["cleared_from_utc", "cleared_until_utc", "rejection_reason"]
    )
    decision = need_enum(body, "decision", ("CLEARED", "REJECTED"))

    cleared_from = None
    cleared_until = None
    rejection_reason = None
    if decision == "CLEARED":
        if body.get("cleared_from_utc") is None or body.get("cleared_until_utc") is None:
            invalid("a clearance requires both cleared_from_utc and cleared_until_utc")
        cleared_from = parse_dt(body["cleared_from_utc"])
        cleared_until = parse_dt(body["cleared_until_utc"])
        if cleared_from is None or cleared_until is None:
            invalid("clearance bounds must be ISO 8601 UTC datetimes")
        if not cleared_from < cleared_until:
            invalid("cleared_from_utc must be strictly earlier than cleared_until_utc")
    else:
        rejection_reason = body.get("rejection_reason")
        if not isinstance(rejection_reason, str) or not rejection_reason.strip():
            invalid("a rejection requires a non-empty rejection_reason")

    if claim["legal_status"] == "REJECTED":
        fail("ERR_CLAIM_STATE_INVALID", "a REJECTED claim is terminal")
    if decision == "CLEARED" and claim["legal_status"] != "DRAFT":
        fail("ERR_CLAIM_STATE_INVALID", "only a DRAFT claim may be cleared")

    if decision == "CLEARED":
        for other in rows("claims"):
            if other["id"] == claim["id"]:
                continue
            if other["legal_status"] != "CLEARED":
                continue
            if other["claim_code"] != claim["claim_code"]:
                continue
            if other["market_code"] != claim["market_code"]:
                continue
            other_from = parse_dt(other["cleared_from_utc"])
            other_until = parse_dt(other["cleared_until_utc"])
            if other_from is None or other_until is None:
                continue
            # Half-open intervals with no buffer whatsoever (PRD 3.2).
            if cleared_from < other_until and other_from < cleared_until:
                fail(
                    "ERR_CLAIM_CLEARANCE_OVERLAP",
                    "the requested clearance window intersects an existing CLEARED window",
                )
        claim["legal_status"] = "CLEARED"
        claim["cleared_from_utc"] = fmt_dt(cleared_from)
        claim["cleared_until_utc"] = fmt_dt(cleared_until)
        claim["cleared_by_user_id"] = user_id
    else:
        # A withdrawal deliberately retains the stored clearance bounds for audit.
        claim["legal_status"] = "REJECTED"
        claim["rejection_reason"] = rejection_reason
        claim["cleared_by_user_id"] = user_id
    touch(claim)
    return ok(claim_json(claim))

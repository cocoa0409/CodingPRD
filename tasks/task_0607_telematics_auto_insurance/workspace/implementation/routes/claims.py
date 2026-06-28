"""Claim (FNOL) endpoints (PRD §3.8)."""
from flask import Blueprint, request

import calculations as calc
import db
from common import (
    find_or_404,
    get_body,
    new_record,
    optional_str,
    pagination,
    paginate,
    require_int,
    require_str,
    serialize,
    touch,
)
from errors import ApiError
from middleware import auth_context, require_owner, require_role
from response import array_response, object_response

bp = Blueprint("claims", __name__)

ALL_ROLES = ["DriverUser", "UnderwritingOps", "ClaimsAdjuster"]


@bp.post("/claims")
def create_claim():
    user_id, role = auth_context()
    require_role(role, ["DriverUser", "ClaimsAdjuster"])
    body = get_body()
    policy_id = require_str(body, "policy_id")
    reported_severity = require_int(body, "reported_severity")
    reason = optional_str(body, "reason")

    pol = find_or_404(db.policies, policy_id)
    require_owner(role, user_id, pol["driver_id"])

    if reported_severity < 1 or reported_severity > 5:
        raise ApiError("ERR_VALIDATION", "reported_severity must be between 1 and 5.")

    rec = new_record(
        {
            "policy_id": pol["id"],
            "trip_id": None,
            "origin": "MANUAL",
            "reported_severity": reported_severity,
            "reserve_cents": 0,
            "reopen_count": 0,
            "status": "FNOL",
        }
    )
    db.claims[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.get("/claims")
def list_claims():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    limit, offset = pagination()
    items = list(db.claims.values())
    for key in ("policy_id", "trip_id", "status", "origin"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    data, total = paginate(items, limit, offset)
    return array_response(data, limit, offset, total)


@bp.get("/claims/<rid>")
def get_claim(rid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    rec = find_or_404(db.claims, rid)
    return object_response(serialize(rec), 200)


@bp.post("/claims/<rid>/triage")
def triage_claim(rid):
    _, role = auth_context()
    require_role(role, ["ClaimsAdjuster"])
    claim = find_or_404(db.claims, rid)
    if claim["status"] != "FNOL":
        raise ApiError("ERR_CLAIM_NOT_FNOL")
    pol = db.policies[claim["policy_id"]]
    if pol["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE")

    claim["reserve_cents"] = calc.claim_reserve_cents(claim["reported_severity"])
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return object_response(serialize(claim), 200)


@bp.post("/claims/<rid>/close")
def close_claim(rid):
    _, role = auth_context()
    require_role(role, ["ClaimsAdjuster"])
    claim = find_or_404(db.claims, rid)
    # Close is valid from UNDER_REVIEW (UNDER_REVIEW -> CLOSED) or from REOPENED
    # (REOPENED -> CLOSED). For any other state the generic close error is
    # ERR_CLAIM_NOT_UNDER_REVIEW (PRD §3.8); the REOPENED path uses
    # ERR_CLAIM_NOT_REOPENABLE only when a reopened-close is specifically attempted.
    if claim["status"] not in ("UNDER_REVIEW", "REOPENED"):
        raise ApiError("ERR_CLAIM_NOT_UNDER_REVIEW")
    claim["status"] = "CLOSED"
    touch(claim)
    return object_response(serialize(claim), 200)


@bp.post("/claims/<rid>/reopen")
def reopen_claim(rid):
    _, role = auth_context()
    require_role(role, ["ClaimsAdjuster"])
    claim = find_or_404(db.claims, rid)
    body = get_body()
    expected_version = require_int(body, "expected_claim_version")

    # OCC before business logic (PRD §2.9, §3.12).
    if expected_version != claim["version"]:
        raise ApiError("ERR_STALE_VERSION")

    if claim["status"] != "CLOSED":
        raise ApiError("ERR_CLAIM_NOT_CLOSED")
    if claim["reopen_count"] >= calc.MAX_CLAIM_REOPENS:
        raise ApiError("ERR_REOPEN_LIMIT_REACHED")

    claim["reopen_count"] += 1
    claim["reserve_cents"] = calc.claim_reserve_cents(claim["reported_severity"])
    claim["status"] = "REOPENED"
    touch(claim)
    return object_response(serialize(claim), 200)

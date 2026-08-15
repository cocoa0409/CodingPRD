"""Coverage verifications."""
from flask import Blueprint, request

import db
from errors import api_error, bad_request
from middleware import require_roles
from response import ok
from services import (bump, check_body_fk, get_claim, is_int, new_entity,
                      need_bool, need_enum, opt_str, require_claim_open, view)

bp = Blueprint("verifications", __name__)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/coverage-verifications")
def create_verification():
    require_roles(["ClaimsAdjuster"])
    b = body()
    # rung 4: body FK existence
    check_body_fk(b, "claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    # shape
    claim_id = b.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id:
        raise bad_request("claim_id is required")
    if not is_int(b.get("expected_claim_version")):
        raise bad_request("expected_claim_version is required")
    claim = get_claim(claim_id)
    # rung 6
    require_claim_open(claim)
    # rung 9: OCC on the claim
    if b["expected_claim_version"] != claim["version"]:
        raise api_error("ERR_STALE_VERSION", 412,
                        "expected_claim_version does not match the claim's current version")
    # supersede any still-PENDING verification on this claim
    for v in db.verifications.values():
        if v["claim_id"] == claim_id and v["status"] == "PENDING":
            v["status"] = "SUPERSEDED"
            bump(v)
    e = new_entity()
    e.update({
        "claim_id": claim_id,
        "status": "PENDING",
        "rental_eligible": None,
        "loss_of_use_eligible": None,
        "denial_reason": None,
    })
    db.verifications[e["id"]] = e
    bump(claim)
    return ok(view(e), status=201)


@bp.post("/coverage-verifications/<vid>/decide")
def decide_verification(vid):
    require_roles(["ClaimsAdjuster"])
    # rung 3: path existence
    v = db.verifications.get(vid)
    if v is None:
        raise api_error("ERR_COVERAGE_VERIFICATION_NOT_FOUND", 404,
                        "coverage verification not found: %s" % vid)
    b = body()
    # shape
    decision = need_enum(b, "decision", ("VERIFIED", "DENIED"))
    rental_eligible = need_bool(b, "rental_eligible")
    lou_eligible = need_bool(b, "loss_of_use_eligible")
    denial_reason = opt_str(b, "denial_reason")
    if decision == "VERIFIED" and not (rental_eligible or lou_eligible):
        raise bad_request("a VERIFIED decision requires at least one benefit eligible")
    if decision == "DENIED" and not denial_reason:
        raise bad_request("a DENIED decision requires denial_reason")
    claim = get_claim(v["claim_id"])
    # rung 6
    require_claim_open(claim)
    # rung 8
    if v["status"] != "PENDING":
        raise api_error("ERR_VERIFICATION_ALREADY_DECIDED", 409,
                        "verification is not PENDING")
    v["status"] = decision
    v["rental_eligible"] = rental_eligible
    v["loss_of_use_eligible"] = lou_eligible
    v["denial_reason"] = denial_reason
    # The track transitions are defined from OPEN only; a later decision on an
    # already-advanced track must not drag it backwards.
    if claim["rental_track_status"] == "OPEN":
        if decision == "VERIFIED" and rental_eligible:
            claim["rental_track_status"] = "COVERAGE_VERIFIED"
        else:
            claim["rental_track_status"] = "COVERAGE_DENIED"
    bump(v)
    bump(claim)
    return ok(view(v))

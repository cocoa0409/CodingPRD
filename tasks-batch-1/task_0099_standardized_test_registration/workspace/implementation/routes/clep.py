"""CLEPClaim routes: file, get, adjudicate."""
from flask import Blueprint

from db import store, stamp_create, touch
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_roles
from response import object_response
from services import lookups, serializers
from services.common import get_json_body, require_fields
from services import calculations as calc

bp = Blueprint("clep", __name__)


@bp.route("/clep-claims", methods=["POST"])
@require_roles("Candidate")
def create_clep_claim():
    body = get_json_body()
    require_fields(body, ["candidate_id", "clep_subject", "clep_scaled_score"])

    candidate = lookups.candidate(body["candidate_id"])

    clep_subject = body["clep_subject"]
    if not isinstance(clep_subject, str):
        raise err(ERR_INVALID_REQUEST, "clep_subject must be a string")

    score = body["clep_scaled_score"]
    if not isinstance(score, int) or isinstance(score, bool):
        raise err(ERR_INVALID_REQUEST, "clep_scaled_score must be an integer")
    # CLEP scale is 20-80.
    if score < 20 or score > 80:
        raise err(ERR_INVALID_REQUEST, "clep_scaled_score out of range (20-80)")

    claim = {
        "candidate_id": candidate["id"],
        "clep_subject": clep_subject,
        "clep_scaled_score": score,
        "recommended_credit_hours": 0,
        "status": "PENDING",
    }
    stamp_create(claim)
    store.clep_claims[claim["id"]] = claim
    return object_response(serializers.clep_claim(claim), 201)


@bp.route("/clep-claims/<cid>", methods=["GET"])
@require_roles("Candidate", "ScoreOps")
def get_clep_claim(cid):
    claim = lookups.clep_claim(cid)
    return object_response(serializers.clep_claim(claim), 200)


@bp.route("/clep-claims/<cid>/adjudicate", methods=["POST"])
@require_roles("ScoreOps")
def adjudicate_clep_claim(cid):
    claim = lookups.clep_claim(cid)
    if claim["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "CLEP claim is not PENDING")

    score = claim["clep_scaled_score"]
    if score >= calc.CLEP_PASS_THRESHOLD:
        claim["status"] = "RECOGNIZED"
        claim["recommended_credit_hours"] = calc.clep_credit(score)
    else:
        claim["status"] = "REJECTED"
        claim["recommended_credit_hours"] = 0
    touch(claim)
    return object_response(serializers.clep_claim(claim), 200)

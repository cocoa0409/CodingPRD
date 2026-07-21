"""Adverse party endpoints (§3.1)."""
from flask import Blueprint, request

import serialize
from auth import authorize
from envelope import success
from helpers import lookup_or_404
from store import db, stamp
import validate as v

bp = Blueprint("adverse_parties", __name__)


@bp.route("/subro/adverse-parties", methods=["POST"])
def create_adverse_party():
    authorize(request, {"RecoverySpecialist", "RecoveryManager"})
    body = v.get_body(request)
    name = v.req_str(body, "name")
    adverse_carrier_name = v.req_str(body, "adverse_carrier_name")
    eligible = v.req_bool(body, "is_arbitration_eligible")
    policy_limit = v.req_int(body, "policy_limit_cents", min=0)
    party = stamp({
        "name": name,
        "adverse_carrier_name": adverse_carrier_name,
        "is_arbitration_eligible": eligible,
        "policy_limit_cents": policy_limit,
    })
    db.adverse_parties[party["id"]] = party
    return success(serialize.adverse_party(party), "object", 201)


@bp.route("/subro/adverse-parties/<adverse_party_id>", methods=["GET"])
def get_adverse_party(adverse_party_id):
    authorize(request, None)
    party = lookup_or_404(db.adverse_parties, adverse_party_id)
    return success(serialize.adverse_party(party), "object", 200)

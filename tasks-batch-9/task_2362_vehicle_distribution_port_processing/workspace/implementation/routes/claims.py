"""Carrier claims: response, the dispute cycle and settlement (PRD §3.3)."""
from flask import Blueprint

import db
import validation as v
from errors import fail, invalid, invalid_state
from middleware import OPS_ROLES, ROLE_MANAGER, ROLE_SURVEYOR, authenticate
from response import list_response, object_response
from services import calculations as calc
from services import serializers as ser
from services import state

bp = Blueprint("claims", __name__)


@bp.route("/vpc/carrier-claims/<claim_id>", methods=["GET"])
def read_claim(claim_id):
    authenticate(OPS_ROLES)
    claim = db.must_get("claims", claim_id)
    return object_response(ser.claim(claim))


@bp.route("/vpc/carrier-claims", methods=["GET"])
def list_claims():
    authenticate(OPS_ROLES)
    survey_id = v.query_filter("damage_survey_id")
    status = v.query_filter("status")
    carrier_scac = v.query_filter("carrier_scac")
    basis = v.query_filter("recoverable_basis")
    records = db.ordered(db.claims)
    if survey_id is not None:
        records = [r for r in records if r["damage_survey_id"] == survey_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if carrier_scac is not None:
        records = [r for r in records if r["carrier_scac"] == carrier_scac]
    if basis is not None:
        records = [r for r in records if r["recoverable_basis"] == basis]
    items, limit, offset, total = v.paginate(records, ser.claim)
    return list_response(items, limit, offset, total)


@bp.route("/vpc/carrier-claims/<claim_id>/carrier-response", methods=["POST"])
def carrier_response(claim_id):
    authenticate([ROLE_MANAGER])
    claim = db.must_get("claims", claim_id)
    body = v.body()
    outcome = v.req_enum(body, "outcome", ("ACCEPT", "DISPUTE", "DENY"))

    conceded = None
    if outcome == "DISPUTE":
        conceded = v.req_int(body, "disputed_amount_cents", minimum=0)
        if conceded >= claim["claimed_amount_cents"]:
            invalid(
                "disputed_amount_cents must be strictly below the claim's claimed_amount_cents"
            )

    if claim["status"] != "FILED":
        invalid_state("a carrier response can only be recorded against a FILED claim")

    if outcome == "ACCEPT":
        claim["status"] = "ACCEPTED_PENDING_SETTLEMENT"
    elif outcome == "DISPUTE":
        claim["status"] = "DISPUTED"
        claim["disputed_amount_cents"] = conceded
    else:
        claim["status"] = "DENIED"
    db.touch(claim)
    return object_response(ser.claim(claim))


@bp.route("/vpc/carrier-claims/<claim_id>/resubmit", methods=["POST"])
def resubmit_claim(claim_id):
    authenticate([ROLE_SURVEYOR])
    claim = db.must_get("claims", claim_id)
    body = v.body()
    revised = v.req_int(body, "revised_claim_amount_cents", minimum=0)
    if revised > claim["claimed_amount_cents"]:
        invalid("revised_claim_amount_cents may not exceed the claim's current claimed amount")

    if claim["status"] != "DISPUTED":
        invalid_state("only a DISPUTED claim can be resubmitted")
    if claim["revision_round"] >= calc.MAX_CLAIM_REVISIONS:
        fail("ERR_CLAIM_REVISION_LIMIT", "this claim has already used all three revisions")

    claim["revision_round"] = claim["revision_round"] + 1
    claim["claimed_amount_cents"] = revised
    claim["disputed_amount_cents"] = None
    claim["status"] = "FILED"
    claim["recoverable_amount_cents"] = state.claim_recoverable(claim)
    db.touch(claim)
    return object_response(ser.claim(claim))


@bp.route("/vpc/carrier-claims/<claim_id>/settle", methods=["POST"])
def settle_claim(claim_id):
    user_id, _role = authenticate([ROLE_MANAGER])
    claim = db.must_get("claims", claim_id)
    body = v.body()
    settled = v.req_int(body, "settled_amount_cents", minimum=0)

    if claim["status"] != "ACCEPTED_PENDING_SETTLEMENT":
        invalid_state("only an accepted claim can be settled")
    if claim["filed_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "the settler of a claim may not be its filer")
    if settled > claim["recoverable_amount_cents"]:
        fail(
            "ERR_SETTLEMENT_EXCEEDS_RECOVERABLE",
            "settled_amount_cents exceeds the claim's recoverable amount",
        )

    claim["settled_amount_cents"] = settled
    claim["settled_by_user_id"] = user_id
    claim["status"] = "SETTLED"
    db.touch(claim)
    return object_response(ser.claim(claim))

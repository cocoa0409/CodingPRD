"""Liability claims and their cyclic adjudication machine."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import FINANCE, RISK, VETTING, endpoint
from response import list_response, object_response
from routes import API_PREFIX
from serializers import claim_json
from services.cascades import recompute_operator_score
from util import apply_bps
from validation import (claim_or_404, f, paginate, pagination, query_values, raw_body,
                        validate_body)

bp = Blueprint("claims", __name__)

CLAIM_STATUSES = ("SUBMITTED", "UNDER_OPERATOR_REVIEW", "DISPUTED", "ADJUDICATED_UPHELD",
                  "ADJUDICATED_DENIED", "SETTLED")
CLAIM_ACTIONS = ("SEND_TO_OPERATOR", "RECORD_DISPUTE", "ADJUDICATE_UPHELD", "ADJUDICATE_DENIED")
MAX_DISPUTE_ROUNDS = 2

READ_ROLES = (RISK, FINANCE, VETTING)

CLAIM_ACTION = [
    f("action", "enum", required=True, enum=CLAIM_ACTIONS),
    f("note", "string"),
    f("liability_share_bps", "int", lo=1, hi=10000),
    f("settlement_amount_cents", "int", lo=0),
]


@bp.get(API_PREFIX + "/claims/<claim_id>")
@endpoint(*READ_ROLES)
def read_claim(caller, claim_id):
    return object_response(claim_json(claim_or_404(claim_id)))


@bp.get(API_PREFIX + "/claims")
@endpoint(*READ_ROLES)
def list_claims(caller):
    limit, offset = pagination()
    filters = query_values([
        f("incident_id", "string"),
        f("operator_id", "string"),
        f("port_call_id", "string"),
        f("status", "enum", enum=CLAIM_STATUSES),
    ])
    rows = db.ordered("claims")
    for key in ("incident_id", "operator_id", "port_call_id", "status"):
        if key in filters:
            rows = [r for r in rows if r.get(key) == filters[key]]
    page, total = paginate(rows, limit, offset)
    return list_response([claim_json(r) for r in page], limit, offset, total)


@bp.post(API_PREFIX + "/claims/<claim_id>/actions")
@endpoint(RISK)
def claim_action(caller, claim_id):
    # priority 4 outranks request shape, so read the action leniently first
    raw = raw_body()
    candidate = db.claims.get(claim_id)
    if (candidate is not None and raw.get("action") in ("ADJUDICATE_UPHELD", "ADJUDICATE_DENIED")
            and caller.user_id == candidate.get("submitted_by_user_id")):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the officer who opened the claim may not adjudicate it")

    body = validate_body(CLAIM_ACTION, raw)
    claim = claim_or_404(claim_id)
    action = body["action"]
    status = claim["status"]
    operator = db.operators.get(claim["operator_id"]) if claim.get("operator_id") else None

    share = body.get("liability_share_bps")
    settlement = body.get("settlement_amount_cents")
    if action == "ADJUDICATE_UPHELD":
        if share is None:
            fail("ERR_VALIDATION", "liability_share_bps is required to uphold a claim")
        if settlement is None:
            fail("ERR_VALIDATION", "settlement_amount_cents is required to uphold a claim")
        if settlement > claim["claimed_amount_cents"]:
            fail("ERR_VALIDATION", "settlement_amount_cents may not exceed claimed_amount_cents")

    allowed = {
        "SEND_TO_OPERATOR": ("SUBMITTED", "DISPUTED"),
        "RECORD_DISPUTE": ("UNDER_OPERATOR_REVIEW",),
        "ADJUDICATE_UPHELD": ("UNDER_OPERATOR_REVIEW", "DISPUTED"),
        "ADJUDICATE_DENIED": ("UNDER_OPERATOR_REVIEW", "DISPUTED"),
    }[action]
    if status not in allowed:
        fail("ERR_INVALID_CLAIM_ACTION",
             "%s is not declared for a claim in %s" % (action, status))
    if action == "SEND_TO_OPERATOR" and status == "SUBMITTED":
        if operator is None or operator["vetting_status"] == "TERMINATED":
            fail("ERR_INVALID_CLAIM_ACTION", "a terminated operator receives no claims")

    if action == "SEND_TO_OPERATOR":
        if status == "DISPUTED" and claim["dispute_round_count"] > MAX_DISPUTE_ROUNDS:
            fail("ERR_DISPUTE_ROUNDS_EXHAUSTED", "the dispute loop is exhausted")
        claim["status"] = "UNDER_OPERATOR_REVIEW"
        db.touch(claim)

    elif action == "RECORD_DISPUTE":
        if claim["dispute_round_count"] >= MAX_DISPUTE_ROUNDS:
            fail("ERR_DISPUTE_ROUNDS_EXHAUSTED", "the dispute loop is exhausted")
        claim["status"] = "DISPUTED"
        claim["dispute_round_count"] = claim["dispute_round_count"] + 1
        db.touch(claim)

    elif action == "ADJUDICATE_UPHELD":
        charge = apply_bps(settlement, share)
        limit = operator["insurance_liability_limit_cents"] if operator else 0
        if charge > limit:
            fail("ERR_CLAIM_EXCEEDS_INSURANCE_LIMIT",
                 "the operator charge exceeds the operator's liability limit")

        claim["liability_share_bps"] = share
        claim["settlement_amount_cents"] = settlement
        claim["operator_charge_cents"] = charge
        claim["adjudicated_by_user_id"] = caller.user_id
        claim["status"] = "ADJUDICATED_UPHELD"
        db.touch(claim)

        if operator is not None:
            operator["liability_reserve_cents"] = operator["liability_reserve_cents"] + charge
            recompute_operator_score(operator, allow_auto_suspend=True)
            db.touch(operator)

        incident = db.incidents.get(claim["incident_id"])
        if incident is not None and incident["status"] == "CLAIM_OPENED":
            incident["status"] = "CLOSED_UPHELD"
            db.touch(incident)

    else:  # ADJUDICATE_DENIED
        claim["adjudicated_by_user_id"] = caller.user_id
        claim["status"] = "ADJUDICATED_DENIED"
        db.touch(claim)
        incident = db.incidents.get(claim["incident_id"])
        if incident is not None and incident["status"] == "CLAIM_OPENED":
            incident["status"] = "CLOSED_DENIED"
            db.touch(incident)

    return object_response(claim_json(claim))

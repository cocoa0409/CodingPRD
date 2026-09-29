"""Marketing commitments: the conserved-quantity ledger (PRD 3.8)."""
from flask import Blueprint

import constants as K
from auth import enforce_scope, guard
from cascades import refresh_commitment_status
from common import (
    BUSINESS_READ_ROLES,
    created,
    list_endpoint,
    ok,
    read_endpoint,
    scope_from_body_agreement,
)
from errors import ApiError
from lookup import must, put
from store import db, new_entity, now, touch
from validation import check_body, field

bp = Blueprint("marketing", __name__)
BASE = "/carriage/marketing-commitments"


@bp.route(BASE, methods=["POST"])
def create_commitment():
    caller = guard(["AffiliateSalesExec"])
    scope_from_body_agreement(caller)
    body = check_body(
        {
            "agreement_id": field("id", required=True),
            "commitment_type": field("enum", required=True, enum=K.COMMITMENT_TYPES),
            "committed_cents": field("int", required=True, minimum=1),
            "performance_deadline": field("datetime", required=True),
        }
    )
    agreement = must("agreement", body["agreement_id"])

    record = new_entity()
    record.update(
        {
            "agreement_id": agreement["id"],
            "commitment_type": body["commitment_type"],
            "committed_cents": body["committed_cents"],
            "performance_deadline": body["performance_deadline"],
            "earned_cents": 0,
            "earned_unbilled_cents": 0,
            "billed_cents": 0,
            "forfeited_cents": 0,
            "remaining_cents": body["committed_cents"],
            "status": "OPEN",
        }
    )
    put("commitment", record)
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_commitments():
    return list_endpoint(
        "commitment",
        BUSINESS_READ_ROLES,
        ["agreement_id", "commitment_type", "status"],
    )


@bp.route(BASE + "/<commitment_id>", methods=["GET"])
def read_commitment(commitment_id):
    return read_endpoint("commitment", BUSINESS_READ_ROLES, commitment_id)


@bp.route(BASE + "/<commitment_id>/earn", methods=["POST"])
def earn_commitment(commitment_id):
    caller = guard(["AffiliateSalesExec"])
    body = check_body(
        {
            "earned_cents": field("int", required=True, minimum=0),
            "proof_reference": field("string", required=True, min_len=1, max_len=200),
        }
    )
    commitment = must("commitment", commitment_id)
    agreement = db.agreements.get(commitment["agreement_id"])
    enforce_scope(caller, agreement["distributor_id"] if agreement else None)

    # ORDER 1 - only a live agreement can accept proof of performance
    if agreement is None or agreement["lifecycle_status"] != "EXECUTED":
        raise ApiError(
            "ERR_AGREEMENT_NOT_EXECUTED",
            "performance is earned only under an EXECUTED agreement",
        )

    # ORDER 2 - the deadline is a hard stop, whatever the ledger says
    if now() > commitment["performance_deadline"]:
        raise ApiError(
            "ERR_COMMITMENT_DEADLINE_PASSED",
            "the performance deadline for this commitment has passed",
        )

    # ORDER 3 - the ledger may never be over-drawn
    amount = body["earned_cents"]
    if commitment["earned_cents"] + amount > commitment["committed_cents"]:
        raise ApiError(
            "ERR_MARKETING_OVEREARN",
            "the claim would earn more than the commitment funds",
        )

    commitment["earned_cents"] += amount
    refresh_commitment_status(commitment)
    touch(commitment)
    return ok(commitment)

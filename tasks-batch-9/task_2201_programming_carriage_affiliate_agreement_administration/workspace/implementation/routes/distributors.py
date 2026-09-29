"""Distributor registration, adjustment and credit posture (PRD section 3.1)."""
from flask import Blueprint

import constants as K
from auth import guard
from cascades import apply_credit_hold
from common import ALL_READ_ROLES, created, list_endpoint, ok, read_endpoint
from errors import ApiError
from lookup import must, put
from store import db, new_entity, touch
from validation import bad, check_body, field

bp = Blueprint("distributors", __name__)
BASE = "/carriage/distributors"

CREDIT_ACTIONS = ["PLACE_HOLD", "RELEASE_HOLD", "SUSPEND", "TERMINATE", "REACTIVATE"]


@bp.route(BASE, methods=["POST"])
def create_distributor():
    guard(["NetworkAdmin", "AffiliateSalesExec"])
    body = check_body(
        {
            "legal_name": field("string", required=True, min_len=1, max_len=200),
            "distributor_type": field("enum", required=True, enum=K.DISTRIBUTOR_TYPES),
            "rate_card_class": field("enum", required=True, enum=K.RATE_CARD_CLASSES),
            "total_subscribers": field("int", required=True, minimum=1),
            "credit_limit_cents": field("int", default=100000000, minimum=0),
        }
    )
    for existing in db.distributors.values():
        if existing["legal_name"] == body["legal_name"]:
            bad("legal_name must be unique across all operators")

    record = new_entity()
    record.update(
        {
            "legal_name": body["legal_name"],
            "distributor_type": body["distributor_type"],
            "rate_card_class": body["rate_card_class"],
            "total_subscribers": body["total_subscribers"],
            "credit_limit_cents": body["credit_limit_cents"],
            "receivable_balance_cents": 0,
            "audit_recovery_balance_cents": 0,
            "executed_agreement_count": 0,
            "status": "ACTIVE",
            "credit_hold_reason": "NONE",
        }
    )
    put("distributor", record)
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_distributors():
    return list_endpoint(
        "distributor", ALL_READ_ROLES, ["status", "distributor_type", "rate_card_class"]
    )


@bp.route(BASE + "/<distributor_id>", methods=["GET"])
def read_distributor(distributor_id):
    return read_endpoint("distributor", ALL_READ_ROLES, distributor_id)


@bp.route(BASE + "/<distributor_id>", methods=["PATCH"])
def patch_distributor(distributor_id):
    guard(["NetworkAdmin"])
    body = check_body(
        {
            "total_subscribers": field("int", minimum=1),
            "credit_limit_cents": field("int", minimum=0),
        }
    )
    distributor = must("distributor", distributor_id)
    # Not retroactive: already-accepted reports keep their stamped figures.
    if body["total_subscribers"] is not None:
        distributor["total_subscribers"] = body["total_subscribers"]
    if body["credit_limit_cents"] is not None:
        distributor["credit_limit_cents"] = body["credit_limit_cents"]
    touch(distributor)
    return ok(distributor)


def _open_invoices(distributor_id):
    return [
        i
        for i in db.invoices.values()
        if i["distributor_id"] == distributor_id
        and i["status"] in ("ISSUED", "PARTIALLY_PAID")
    ]


@bp.route(BASE + "/<distributor_id>/credit-review", methods=["POST"])
def credit_review(distributor_id):
    guard(["NetworkAdmin", "RevenueAccountant"])
    body = check_body(
        {
            "action": field("enum", required=True, enum=CREDIT_ACTIONS),
            "reason": field("string", max_len=500),
        }
    )
    distributor = must("distributor", distributor_id)
    action = body["action"]

    if action == "PLACE_HOLD":
        apply_credit_hold(distributor, "MANUAL_REVIEW")
        return ok(distributor)

    if action == "RELEASE_HOLD":
        if distributor["receivable_balance_cents"] > distributor["credit_limit_cents"]:
            bad("receivable balance still exceeds the credit limit")
        if distributor["audit_recovery_balance_cents"] != 0:
            bad("an audit recovery balance is still outstanding")
        distributor["status"] = "ACTIVE"
        distributor["credit_hold_reason"] = "NONE"
        # Suspended agreements are NOT auto-reinstated.
        touch(distributor)
        return ok(distributor)

    if action == "SUSPEND":
        distributor["status"] = "SUSPENDED"
        touch(distributor)
        return ok(distributor)

    if action == "TERMINATE":
        if _open_invoices(distributor["id"]):
            raise ApiError(
                "ERR_OPEN_RECEIVABLE_BLOCKS_TERMINATION",
                "an invoice of this operator is still ISSUED or PARTIALLY_PAID",
            )
        distributor["status"] = "TERMINATED"
        touch(distributor)
        return ok(distributor)

    # REACTIVATE
    distributor["status"] = "ACTIVE"
    distributor["credit_hold_reason"] = "NONE"
    touch(distributor)
    return ok(distributor)

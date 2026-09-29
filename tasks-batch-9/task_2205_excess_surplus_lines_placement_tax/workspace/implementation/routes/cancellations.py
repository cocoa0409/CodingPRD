"""Cancellations, return premium and the refund ledger (PRD 3.8)."""

from flask import Blueprint

import auth
import ledger
import serialize
import store
import validation
from calc import return_premium
from envelope import created, ok
from errors import ApiError
from routes.common import arg, filtered, list_response
from store import db, touch

bp = Blueprint("cancellations", __name__)

CANCELLATION_TYPES = ("FLAT", "PRO_RATA", "SHORT_RATE")


@bp.post("/policies/<rec_id>/cancellations")
def create_cancellation(rec_id):
    auth.require("PlacementBroker")
    policy = auth.path_entity("policies", "policy", rec_id)
    data = validation.body()
    cancellation_type = validation.req_enum(data, "cancellation_type",
                                           CANCELLATION_TYPES)
    cancel_at, cancel_raw = validation.req_datetime(data, "cancellation_date")
    auth.check_owner(policy.get("broker_id"))

    rec = db.insert("cancellations", {
        "policy_id": policy["id"],
        "cancellation_type": cancellation_type,
        "cancellation_date": cancel_raw,
        "status": "REQUESTED",
        "earned_premium_cents": 0,
        "return_premium_cents": 0,
        "tax_refund_cents": 0,
        "stamping_fee_refund_cents": 0,
        "_cancellation_at": cancel_at,
    })
    return created(serialize.public(rec))


@bp.get("/policies/<rec_id>/cancellations")
def list_cancellations(rec_id):
    auth.require(auth.ANY)
    policy = auth.path_entity("policies", "policy", rec_id)
    rows = filtered(store.where("cancellations", policy_id=policy["id"]),
                    status=arg("status"))
    return list_response(rows)


@bp.post("/cancellations/<rec_id>/process")
def process_cancellation(rec_id):
    auth.require("PlacementBroker")
    rec = auth.path_entity("cancellations", "cancellation", rec_id)
    policy = db.get("policies", rec.get("policy_id"))
    if policy is None:
        raise ApiError("ERR_POLICY_NOT_FOUND")
    auth.check_owner(policy.get("broker_id"))

    if rec.get("status") != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REQUESTED cancellation may be processed.")
    if policy.get("status") != "ISSUED":
        raise ApiError("ERR_POLICY_NOT_ISSUED",
                       "The policy's status is %s." % policy.get("status"))
    if policy.get("tax_status") == "UNCALCULATED":
        raise ApiError("ERR_TAX_NOT_CALCULATED",
                       "The policy's premium tax has not been calculated.")

    # Rung 17: out-of-term first, then the flat-cancellation availability rule.
    result = return_premium.compute(policy, rec)

    rec["earned_premium_cents"] = result["earned_premium_cents"]
    rec["return_premium_cents"] = result["return_premium_cents"]
    rec["tax_refund_cents"] = result["tax_refund_cents"]
    rec["stamping_fee_refund_cents"] = result["stamping_fee_refund_cents"]
    rec["status"] = "PROCESSED"
    touch(rec)

    # The ledger mirror image: negative amounts, one line per allocated state.
    for entry in result["per_state"]:
        ledger.emit_line(policy, entry["state_program_id"], "CANCELLATION_RETURN",
                         -entry["return_premium_cents"],
                         -entry["tax_refund_cents"],
                         -entry["stamping_fee_refund_cents"],
                         source_cancellation_id=rec["id"])

    policy["status"] = "CANCELLED"
    has_delta = (result["tax_refund_cents"] != 0
                 or result["stamping_fee_refund_cents"] != 0)
    ledger.advance_to_adjusted(policy, has_delta)
    touch(policy)

    return ok(serialize.public(rec))

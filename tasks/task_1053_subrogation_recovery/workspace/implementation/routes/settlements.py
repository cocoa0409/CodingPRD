"""Settlement endpoints (§3.5)."""
from flask import Blueprint, request

import errors
import serialize
import validate as v
from auth import authorize
from cascade import withdraw_live_arbitrations
from envelope import success
from helpers import lookup_or_404, respond_list
from store import db, stamp, touch, MANAGER_AUTHORITY_CENTS

bp = Blueprint("settlements", __name__)


@bp.route("/subro/claims/<claim_id>/settlements", methods=["POST"])
def propose_settlement(claim_id):
    uid, role = authorize(request, {"RecoverySpecialist"})
    claim = lookup_or_404(db.claims, claim_id)
    body = v.get_body(request)
    amount = v.req_int(body, "settled_amount_cents", gt=0)
    expected = v.req_int(body, "expected_claim_version", min=0)

    # (13) OCC — the last check.
    if expected != claim["version"]:
        raise errors.stale_claim_version()

    # supersede any prior PROPOSED settlement on this claim
    for s in db.settlements.values():
        if s["claim_id"] == claim_id and s["status"] == "PROPOSED":
            s["status"] = "SUPERSEDED"
            touch(s)

    settlement = stamp({
        "claim_id": claim_id,
        "settled_amount_cents": amount,
        "proposed_by_user_id": uid,
        "approved_by_user_id": None,
        "status": "PROPOSED",
    })
    db.settlements[settlement["id"]] = settlement
    touch(claim)  # increments Claim.version by 1
    return success(serialize.settlement(settlement), "object", 201)


@bp.route("/subro/settlements/<settlement_id>", methods=["GET"])
def get_settlement(settlement_id):
    authorize(request, None)
    settlement = lookup_or_404(db.settlements, settlement_id)
    return success(serialize.settlement(settlement), "object", 200)


@bp.route("/subro/settlements", methods=["GET"])
def list_settlements():
    authorize(request, None)
    claim_id = request.args.get("claim_id")
    status = request.args.get("status")
    items = []
    for s in db.settlements.values():
        if claim_id is not None and s["claim_id"] != claim_id:
            continue
        if status is not None and s["status"] != status:
            continue
        items.append(s)
    return respond_list(request, items, serialize.settlement)


@bp.route("/subro/settlements/<settlement_id>/approve", methods=["POST"])
def approve_settlement(settlement_id):
    uid, role = authorize(request, {"RecoveryManager"})
    settlement = lookup_or_404(db.settlements, settlement_id)
    # (6) segregation of duties
    if uid == settlement["proposed_by_user_id"]:
        raise errors.sod()
    # (7) state
    if settlement["status"] != "PROPOSED":
        raise errors.invalid_state()
    # (10) authority ceiling
    if settlement["settled_amount_cents"] > MANAGER_AUTHORITY_CENTS:
        raise errors.exceeds_authority()
    settlement["status"] = "APPROVED"
    settlement["approved_by_user_id"] = uid
    touch(settlement)
    return success(serialize.settlement(settlement), "object", 200)


@bp.route("/subro/settlements/<settlement_id>/reject", methods=["POST"])
def reject_settlement(settlement_id):
    authorize(request, {"RecoveryManager"})
    settlement = lookup_or_404(db.settlements, settlement_id)
    if settlement["status"] != "PROPOSED":
        raise errors.invalid_state()
    settlement["status"] = "REJECTED"
    touch(settlement)
    return success(serialize.settlement(settlement), "object", 200)


@bp.route("/subro/settlements/<settlement_id>/accept", methods=["POST"])
def accept_settlement(settlement_id):
    uid, role = authorize(request, {"CarrierUser"})
    settlement = lookup_or_404(db.settlements, settlement_id)
    claim = db.claims[settlement["claim_id"]]
    # (4) ownership
    if claim["carrier_id"] != uid:
        raise errors.not_claim_owner()
    # (7) state
    if settlement["status"] != "APPROVED" or claim["status"] not in {"DEMAND_ISSUED", "ARBITRATION"}:
        raise errors.invalid_state()

    was_arbitration = claim["status"] == "ARBITRATION"
    settlement["status"] = "ACCEPTED"
    touch(settlement)
    claim["settled_amount_cents"] = settlement["settled_amount_cents"]
    claim["status"] = "SETTLED"
    touch(claim)
    if was_arbitration:
        withdraw_live_arbitrations(claim["id"])
    return success(serialize.settlement(settlement), "object", 200)

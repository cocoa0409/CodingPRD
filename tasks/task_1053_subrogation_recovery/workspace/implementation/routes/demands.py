"""Demand endpoints (§3.3)."""
from flask import Blueprint, request

import errors
import serialize
import validate as v
from auth import authorize
from envelope import success
from helpers import lookup_or_404, respond_list
from store import db, stamp, touch, clock_now, DEMAND_RESPONSE_DAYS, ARBITRATION_FILING_DAYS
from timeutil import parse_iso, days

bp = Blueprint("demands", __name__)


@bp.route("/subro/claims/<claim_id>/demands", methods=["POST"])
def issue_demand(claim_id):
    authorize(request, {"RecoverySpecialist"})
    claim = lookup_or_404(db.claims, claim_id)
    body = v.get_body(request)
    amount = v.req_int(body, "amount_demanded_cents", gt=0)

    # (7) state
    if claim["status"] not in {"LIABILITY_ASSESSED", "DEMAND_ISSUED"}:
        raise errors.invalid_state()
    # (9) no open ISSUED demand window, then statute
    now = clock_now()
    for d in db.demands.values():
        if d["claim_id"] == claim_id and d["status"] == "ISSUED" and now < d["response_due_at"]:
            raise errors.demand_window_open()
    if now >= parse_iso(claim["statute_deadline"]):
        raise errors.statute_expired()

    issued_at = now
    demand = stamp({
        "claim_id": claim_id,
        "amount_demanded_cents": amount,
        "issued_at": issued_at,
        "response_due_at": issued_at + days(DEMAND_RESPONSE_DAYS),
        "disputed_at": None,
        "arbitration_window_due_at": None,
        "outcome": None,
        "status": "ISSUED",
    })
    db.demands[demand["id"]] = demand
    if claim["status"] != "DEMAND_ISSUED":
        claim["status"] = "DEMAND_ISSUED"
        touch(claim)
    return success(serialize.demand(demand), "object", 201)


@bp.route("/subro/demands/<demand_id>", methods=["GET"])
def get_demand(demand_id):
    authorize(request, None)
    demand = lookup_or_404(db.demands, demand_id)
    return success(serialize.demand(demand), "object", 200)


@bp.route("/subro/demands", methods=["GET"])
def list_demands():
    authorize(request, None)
    claim_id = request.args.get("claim_id")
    status = request.args.get("status")
    items = []
    for d in db.demands.values():
        if claim_id is not None and d["claim_id"] != claim_id:
            continue
        if status is not None and d["status"] != status:
            continue
        items.append(d)
    return respond_list(request, items, serialize.demand)


@bp.route("/subro/demands/<demand_id>/record-response", methods=["POST"])
def record_response(demand_id):
    authorize(request, {"RecoverySpecialist"})
    demand = lookup_or_404(db.demands, demand_id)
    body = v.get_body(request)
    outcome = v.req_enum(body, "outcome", {"HONORED", "DISPUTED"})

    # (7) state
    if demand["status"] != "ISSUED":
        raise errors.invalid_state()
    now = clock_now()
    # response window must still be open
    if now >= demand["response_due_at"]:
        raise errors.invalid_state("Demand response window has closed")

    if outcome == "HONORED":
        demand["outcome"] = "HONORED"
        demand["status"] = "HONORED"
    else:
        demand["outcome"] = "DISPUTED"
        demand["status"] = "DISPUTED"
        demand["disputed_at"] = now
        demand["arbitration_window_due_at"] = now + days(ARBITRATION_FILING_DAYS)
    touch(demand)
    return success(serialize.demand(demand), "object", 200)

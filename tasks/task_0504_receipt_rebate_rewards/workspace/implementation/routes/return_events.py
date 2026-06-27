"""ReturnEvent endpoints (PRD §3.9). Append-only; triggers clawback cascade."""
from flask import Blueprint, request

from clock import format_iso
from db import base_common_fields
from errors import err
from middleware import get_identity, require_roles
from response import object_response
from routes.common import list_response, member_owns
from services.calculations import compute_clawback
from services.claims import clawback_claim
from services.serialize import return_event_out
from state import store
from validation import get_json_body, require_int

bp = Blueprint("return_events", __name__)


@bp.route("/return-events", methods=["POST"])
def create_return_event():
    _, role = get_identity()
    require_roles(role, ["FinanceAdmin"])
    body = get_json_body()

    reward_claim_id = body.get("reward_claim_id")
    if reward_claim_id is None:
        raise err("ERR_VALIDATION", "Missing required field: reward_claim_id")
    if not isinstance(reward_claim_id, str) or reward_claim_id not in store.reward_claims:
        raise err("ERR_REFERENCE_NOT_FOUND", "reward_claim_id does not resolve.")

    returned_amount_cents = require_int(body, "returned_amount_cents", minimum=1)

    claim = store.reward_claims[reward_claim_id]

    # State (priority 6): a return may not be filed against a terminal claim.
    if claim["status"] in ("PAID", "CLAWED_BACK", "EXPIRED"):
        raise err("ERR_CLAIM_ALREADY_TERMINAL", "Claim is already terminal.")

    # Business (returned amount may not exceed purchase amount).
    if returned_amount_cents > claim["purchase_amount_cents"]:
        raise err("ERR_RETURN_EXCEEDS_PURCHASE",
                  "Returned amount exceeds the claim's purchase amount.")

    clawback_cents = compute_clawback(
        claim["amount_cents"], returned_amount_cents, claim["purchase_amount_cents"]
    )

    ev = base_common_fields(store, full=False)
    ev.update({
        "reward_claim_id": reward_claim_id,
        "returned_amount_cents": returned_amount_cents,
        "clawback_cents": clawback_cents,
        "reported_at": format_iso(store.clock.get()),
    })
    store.return_events[ev["id"]] = ev

    # Move the claim to CLAWED_BACK and run the state-dependent cascade.
    clawback_claim(store, claim, clawback_cents)

    return object_response(store.clock, return_event_out(store, ev), status=201)


@bp.route("/return-events/<eid>", methods=["GET"])
def get_return_event(eid):
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    ev = store.return_events.get(eid)
    if ev is None:
        raise err("ERR_NOT_FOUND", "Return event not found.")
    if role == "Member":
        claim = store.reward_claims.get(ev["reward_claim_id"])
        if claim is None or not member_owns(user_id, claim["member_id"]):
            raise err("ERR_FORBIDDEN", "A member may only read their own return events.")
    return object_response(store.clock, return_event_out(store, ev))


@bp.route("/return-events", methods=["GET"])
def list_return_events():
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    items = list(store.return_events.values())
    if role == "Member":
        def owned(ev):
            claim = store.reward_claims.get(ev["reward_claim_id"])
            return claim is not None and claim["member_id"] == user_id
        items = [ev for ev in items if owned(ev)]
    reward_claim_id = request.args.get("reward_claim_id")
    if reward_claim_id is not None:
        items = [ev for ev in items if ev["reward_claim_id"] == reward_claim_id]
    return list_response(items, return_event_out)

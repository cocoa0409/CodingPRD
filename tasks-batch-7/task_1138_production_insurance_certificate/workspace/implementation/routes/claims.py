"""Claim endpoints and the append-only claim event log."""

from flask import request

from db import db, new_id
from errors import err
from middleware import require_roles
from response import success_list, success_object
from routes import bp
from services.claims import deductible_applied, would_exceed_cap
from services.posture import recompute_posture
from util import (
    body,
    get_child,
    get_production,
    make_entity,
    now,
    paginate,
    req_dt,
    req_enum,
    req_int,
    serialize,
    sort_key,
    touch,
)

CLAIM_TYPES = ("DAMAGE", "INJURY", "WEATHER_DELAY", "THEFT", "THIRD_PARTY")
CLAIMABLE_POLICY_STATUSES = ("BOUND", "ENDORSED_PENDING", "ACTIVE", "EXPIRED")
CLAIM_ROLES = {"BrokerAgent", "ProductionManager", "ClaimsAdjuster", "PlatformOperator"}


def get_claim(prod_id, claim_id):
    return get_child(db.claims, claim_id, "production_id", prod_id, "Claim")


def _append_event(claim, event_type, payload, actor_role):
    ts = now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "claim_id": claim["id"],
        "event_type": event_type,
        "payload": payload,
        "recorded_at": ts,
        "actor_role": actor_role,
        "_seq": db.next_seq(),
    }
    db.claim_events[rec["id"]] = rec
    return rec


@bp.route("/productions/<id>/claims", methods=["POST"])
def create_claim(id):
    user_id, _role = require_roles({"ProductionManager"})
    with db.lock:
        prod = get_production(id)
        data = body()
        policy_id = data.get("policy_id")
        if not isinstance(policy_id, str) or not policy_id:
            raise err("ERR_INVALID_REQUEST", "Field 'policy_id' is required")
        pol = get_child(db.policies, policy_id, "production_id", id, "Policy")

        if pol["status"] not in CLAIMABLE_POLICY_STATUSES:
            raise err("ERR_REFERENCED_STATE_INVALID",
                      "Policy in %s is not claimable" % pol["status"])

        claim_type = req_enum(data, "claim_type", CLAIM_TYPES)
        occurrence_date = req_dt(data, "occurrence_date")
        loss_amount_cents = req_int(data, "loss_amount_cents")

        if not (pol["effective_date"] <= occurrence_date <= pol["expiry_date"]):
            raise err("ERR_TEMPORAL_RANGE_INVALID",
                      "occurrence_date must lie within the policy effective window")
        if loss_amount_cents <= 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "loss_amount_cents must be greater than zero")
        if would_exceed_cap(pol, loss_amount_cents):
            raise err("ERR_DEDUCTIBLE_CAP_EXCEEDED",
                      "Aggregate deductible cap would be exceeded by this claim")

        applied = deductible_applied(pol, loss_amount_cents)
        carrier_payable = loss_amount_cents - applied

        rec = make_entity({
            "production_id": id,
            "policy_id": pol["id"],
            "claim_type": claim_type,
            "occurrence_date": occurrence_date,
            "reported_date": now(),
            "loss_amount_cents": loss_amount_cents,
            "deductible_applied_cents": applied,
            "carrier_payable_cents": carrier_payable,
            "reserve_cents": carrier_payable,
            "status": "SUBMITTED",
            "_submitted_by": user_id,
        })
        db.claims[rec["id"]] = rec
        recompute_posture(prod)
        return success_object(serialize(rec), status=201)


@bp.route("/productions/<id>/claims", methods=["GET"])
def list_claims(id):
    require_roles(CLAIM_ROLES)
    get_production(id)
    pol_id = request.args.get("policy_id")
    ctype = request.args.get("claim_type")
    status = request.args.get("status")
    records = [c for c in db.claims.values() if c["production_id"] == id]
    if pol_id is not None:
        records = [r for r in records if r["policy_id"] == pol_id]
    if ctype is not None:
        records = [r for r in records if r["claim_type"] == ctype]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>/claims/<childId>", methods=["GET"])
def get_claim_by_id(id, childId):
    require_roles(CLAIM_ROLES)
    get_production(id)
    rec = get_claim(id, childId)
    return success_object(serialize(rec))


@bp.route("/productions/<id>/claims/<childId>/acknowledge", methods=["POST"])
def acknowledge_claim(id, childId):
    _uid, role = require_roles({"ClaimsAdjuster"})
    with db.lock:
        prod = get_production(id)
        cl = get_claim(id, childId)
        if cl["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE",
                      "Claim must be SUBMITTED to acknowledge (current: %s)" % cl["status"])
        pol = db.policies[cl["policy_id"]]
        if pol["status"] not in CLAIMABLE_POLICY_STATUSES:
            raise err("ERR_POLICY_NOT_CLAIMABLE",
                      "Policy in %s is not claimable" % pol["status"])
        cl["status"] = "UNDER_REVIEW"
        cl["reserve_cents"] = cl["carrier_payable_cents"]
        touch(cl)
        _append_event(cl, "SUBMIT", {}, role)
        recompute_posture(prod)
        return success_object(serialize(cl))


@bp.route("/productions/<id>/claims/<childId>/adjust", methods=["POST"])
def adjust_claim(id, childId):
    _uid, role = require_roles({"ClaimsAdjuster"})
    with db.lock:
        prod = get_production(id)
        cl = get_claim(id, childId)
        if cl["status"] not in ("UNDER_REVIEW", "ADJUSTED"):
            raise err("ERR_INVALID_STATE",
                      "Claim must be UNDER_REVIEW or ADJUSTED to adjust (current: %s)"
                      % cl["status"])
        data = body()
        new_reserve = req_int(data, "new_reserve_cents")
        if new_reserve < 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "new_reserve_cents must be zero or more")
        cl["reserve_cents"] = new_reserve
        cl["status"] = "ADJUSTED" if cl["status"] == "UNDER_REVIEW" else "UNDER_REVIEW"
        touch(cl)
        _append_event(cl, "ADJUST_RESERVE", {"new_reserve_cents": new_reserve}, role)
        recompute_posture(prod)
        return success_object(serialize(cl))


@bp.route("/productions/<id>/claims/<childId>/deny", methods=["POST"])
def deny_claim(id, childId):
    _uid, role = require_roles({"ClaimsAdjuster"})
    with db.lock:
        prod = get_production(id)
        cl = get_claim(id, childId)
        if cl["status"] not in ("UNDER_REVIEW", "ADJUSTED"):
            raise err("ERR_INVALID_STATE",
                      "Claim must be UNDER_REVIEW or ADJUSTED to deny (current: %s)"
                      % cl["status"])
        data = body()
        reason = data.get("reason")
        if cl["status"] == "UNDER_REVIEW":
            if not isinstance(reason, str) or reason == "":
                raise err("ERR_INVALID_REQUEST",
                          "Field 'reason' must be a non-empty string")
        elif reason is not None and not isinstance(reason, str):
            raise err("ERR_INVALID_REQUEST", "Field 'reason' must be a string")
        cl["status"] = "DENIED"
        cl["reserve_cents"] = 0
        touch(cl)
        _append_event(cl, "DENY", {"reason": reason}, role)
        recompute_posture(prod)
        return success_object(serialize(cl))


@bp.route("/productions/<id>/claims/<childId>/settle", methods=["POST"])
def settle_claim(id, childId):
    user_id, role = require_roles({"ClaimsAdjuster"})
    with db.lock:
        prod = get_production(id)
        cl = get_claim(id, childId)
        if cl["status"] not in ("UNDER_REVIEW", "ADJUSTED"):
            raise err("ERR_INVALID_STATE",
                      "Claim must be UNDER_REVIEW or ADJUSTED to settle (current: %s)"
                      % cl["status"])
        # Segregation of duties: the submitter may not settle.
        if user_id == cl.get("_submitted_by"):
            raise err("ERR_SELF_SETTLEMENT_FORBIDDEN",
                      "The operator who submitted the claim cannot settle it")
        data = body()
        amount = req_int(data, "settlement_amount_cents")
        if amount < 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "settlement_amount_cents must be zero or more")
        if amount > cl["reserve_cents"]:
            raise err("ERR_SETTLEMENT_EXCEEDS_RESERVE",
                      "settlement_amount_cents exceeds reserve_cents")
        cl["status"] = "SETTLED"
        cl["reserve_cents"] = 0
        touch(cl)
        _append_event(cl, "SETTLE", {"settlement_amount_cents": amount}, role)
        recompute_posture(prod)
        return success_object(serialize(cl))


@bp.route("/productions/<id>/claims/<childId>/close", methods=["POST"])
def close_claim(id, childId):
    _uid, role = require_roles({"ClaimsAdjuster"})
    with db.lock:
        prod = get_production(id)
        cl = get_claim(id, childId)
        if cl["status"] not in ("SETTLED", "DENIED"):
            raise err("ERR_INVALID_STATE",
                      "Claim must be SETTLED or DENIED to close (current: %s)" % cl["status"])
        cl["status"] = "CLOSED"
        touch(cl)
        _append_event(cl, "CLOSE", {}, role)
        recompute_posture(prod)
        return success_object(serialize(cl))


@bp.route("/productions/<id>/claims/<claimId>/events", methods=["GET"])
def list_claim_events(id, claimId):
    require_roles(CLAIM_ROLES)
    get_production(id)
    get_claim(id, claimId)
    records = [e for e in db.claim_events.values() if e["claim_id"] == claimId]
    items, page = paginate(records)
    return success_list(items, page)

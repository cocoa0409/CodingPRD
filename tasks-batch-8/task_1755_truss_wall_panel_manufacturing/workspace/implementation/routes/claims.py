"""DamageClaim endpoints: file, triage, decide (cap + rebuild cascade), settle
(settlement waterfall), void (including post-settlement reversal)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_CLAIM_INVALID_TRANSITION,
    ERR_CLAIM_DECIDER_MUST_DIFFER,
    ERR_CLAIM_BUNDLE_NOT_IN_LOAD,
)
from middleware import authenticate, require_role, require_ownership, get_or_404, ALL_ROLES
from response import success, success_list
from services import cascade, serializers
from services.cascade import COMPONENT_VALUE_CENTS_PER_BF, claim_hold_release_check
from util import as_enum, as_int, as_num, as_str, as_fk, body, paginate, dec, round_cents

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"FIELD_DAMAGE", "MATERIAL_DEFECT", "SHORT_SHIPMENT"}
DECISIONS = {"APPROVE_REBUILD", "APPROVE_CREDIT", "DENY"}


def _claim_customer_id(claim):
    load = db.delivery_loads[claim["delivery_load_id"]]
    return db.jobs[load["job_id"]]["customer_id"]


@bp.route("/plant/loads/<load_id>/claims", methods=["POST"])
def file_claim(load_id):
    uid, role = authenticate()
    require_role(role, ["CustomerContact"])
    load = get_or_404(db.delivery_loads, load_id, "delivery load")
    # Ownership (priority 3): the filer must own the load's job.
    require_ownership(role, uid, db.jobs[load["job_id"]]["customer_id"])
    data = body()
    bundle = as_fk(data.get("bundle_id"), "bundle_id", db.bundles, "bundle")
    if bundle is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: bundle_id")
    claim_type = as_enum(data.get("claim_type"), "claim_type", CLAIM_TYPES, required=True)
    description = as_str(data.get("description"), "description", required=True)
    claimed_amount_cents = as_int(data.get("claimed_amount_cents"), "claimed_amount_cents", required=True)
    # Referential: the bundle must belong to this load (priority 35).
    if bundle["delivery_load_id"] != load["id"]:
        raise ApiError(ERR_CLAIM_BUNDLE_NOT_IN_LOAD, 422,
                       "claim bundle does not belong to this load")
    rec = db.new_record({
        "delivery_load_id": load["id"],
        "bundle_id": bundle["id"],
        "filed_by_customer_id": uid,
        "claim_type": claim_type,
        "description": description,
        "claimed_amount_cents": claimed_amount_cents,
        "damage_pct": None,
        "approved_cap_cents": None,
        "rebuild_material_cents": None,
        "rebuild_labor_cents": None,
        "redelivery_cents": None,
        "residual_credit_cents": None,
        "triaged_by": None,
        "decided_by": None,
        "status": "FILED",
    })
    db.damage_claims[rec["id"]] = rec
    if load["status"] == "DELIVERED":
        load["status"] = "CLAIM_HOLD"
        db.touch(load)
    return success(serializers.damage_claim(rec), status=201)


@bp.route("/plant/claims/<cid>", methods=["GET"])
def get_claim(cid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.damage_claims, cid, "damage claim")
    require_ownership(role, uid, _claim_customer_id(rec))
    return success(serializers.damage_claim(rec))


@bp.route("/plant/claims", methods=["GET"])
def list_claims():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    records = list(db.damage_claims.values())
    if role == "CustomerContact":
        records = [c for c in records if _claim_customer_id(c) == uid]
    for field in ("delivery_load_id", "bundle_id", "filed_by_customer_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            records = [c for c in records if c[field] == raw]
    page, meta = paginate(records)
    return success_list([serializers.damage_claim(c) for c in page], meta)


@bp.route("/plant/claims/<cid>/triage", methods=["POST"])
def triage_claim(cid):
    uid, role = authenticate()
    require_role(role, ["ClaimsAdjuster"])
    rec = get_or_404(db.damage_claims, cid, "damage claim")
    if rec["status"] != "FILED":
        raise ApiError(ERR_CLAIM_INVALID_TRANSITION, 409, "triage requires status FILED")
    rec["triaged_by"] = uid
    rec["status"] = "TRIAGED"
    db.touch(rec)
    return success(serializers.damage_claim(rec))


@bp.route("/plant/claims/<cid>/decide", methods=["POST"])
def decide_claim(cid):
    uid, role = authenticate()
    require_role(role, ["ClaimsAdjuster"])
    rec = get_or_404(db.damage_claims, cid, "damage claim")
    data = body()
    decision = as_enum(data.get("decision"), "decision", DECISIONS, required=True)
    damage_pct = None
    if decision != "DENY":
        damage_pct = as_num(data.get("damage_pct"), "damage_pct", required=True)
        if not (dec("0") < damage_pct <= dec("1")):
            raise ApiError(ERR_INVALID_REQUEST, 400, "damage_pct must be greater than 0 and at most 1")
    # Action guard (priority 13) precedes decider segregation (priority 19).
    if rec["status"] != "TRIAGED":
        raise ApiError(ERR_CLAIM_INVALID_TRANSITION, 409, "decide requires status TRIAGED")
    if uid == rec["triaged_by"]:
        raise ApiError(ERR_CLAIM_DECIDER_MUST_DIFFER, 422,
                       "claim decider must differ from the triaging adjuster")
    rec["decided_by"] = uid
    load = db.delivery_loads[rec["delivery_load_id"]]

    if decision == "DENY":
        rec["status"] = "DENIED"
        db.touch(rec)
        claim_hold_release_check(load)
        return success(serializers.damage_claim(rec))

    # Assessment cap (calculation claim_assessment_cap): same for every type.
    bundle = db.bundles[rec["bundle_id"]]
    batch = db.production_batches[bundle["production_batch_id"]]
    cut_list = db.cut_lists[batch["cut_list_id"]]
    component_value = round_cents(cut_list["total_board_feet"] * COMPONENT_VALUE_CENTS_PER_BF)
    rec["approved_cap_cents"] = min(rec["claimed_amount_cents"],
                                    round_cents(damage_pct * component_value))
    rec["damage_pct"] = damage_pct

    if decision == "APPROVE_CREDIT":
        rec["status"] = "APPROVED_CREDIT"
        db.touch(rec)
        return success(serializers.damage_claim(rec))

    # APPROVE_REBUILD: bundle DAMAGED, rebuild cascade, then auto-advance.
    rec["status"] = "APPROVED_REBUILD"
    db.touch(rec)
    bundle["status"] = "DAMAGED"
    db.touch(bundle)
    cascade.claim_rebuild_cascade(rec)
    rec["status"] = "REBUILD_IN_PROGRESS"
    db.touch(rec)
    return success(serializers.damage_claim(rec))


@bp.route("/plant/claims/<cid>/settle", methods=["POST"])
def settle_claim(cid):
    _uid, role = authenticate()
    require_role(role, ["ClaimsAdjuster"])
    rec = get_or_404(db.damage_claims, cid, "damage claim")
    data = body()
    material_actual = as_int(data.get("rebuild_material_cents"), "rebuild_material_cents", required=True)
    labor_actual = as_int(data.get("rebuild_labor_cents"), "rebuild_labor_cents", required=True)
    redelivery_actual = as_int(data.get("redelivery_cents"), "redelivery_cents", required=True)
    if rec["status"] == "REBUILD_IN_PROGRESS":
        rebuild_batches = [b for b in db.production_batches.values()
                           if b["source_claim_id"] == rec["id"]]
        if not any(b["status"] in ("STAGED", "LOADED") for b in rebuild_batches):
            raise ApiError(ERR_CLAIM_INVALID_TRANSITION, 409,
                           "rebuild batch has not reached STAGED or LOADED")
    elif rec["status"] != "APPROVED_CREDIT":
        raise ApiError(ERR_CLAIM_INVALID_TRANSITION, 409,
                       "settle requires status APPROVED_CREDIT or REBUILD_IN_PROGRESS")
    # Settlement waterfall (calculation claim_settlement_waterfall): buckets in
    # fixed order, residual is credit; conservation is exact in integer cents.
    remaining = rec["approved_cap_cents"]
    rec["rebuild_material_cents"] = min(material_actual, remaining)
    remaining -= rec["rebuild_material_cents"]
    rec["rebuild_labor_cents"] = min(labor_actual, remaining)
    remaining -= rec["rebuild_labor_cents"]
    rec["redelivery_cents"] = min(redelivery_actual, remaining)
    remaining -= rec["redelivery_cents"]
    rec["residual_credit_cents"] = remaining
    rec["status"] = "SETTLED"
    db.touch(rec)
    # Job.credit_issued_cents derives from SETTLED claims; posture recomputes.
    claim_hold_release_check(db.delivery_loads[rec["delivery_load_id"]])
    return success(serializers.damage_claim(rec))


@bp.route("/plant/claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    _uid, role = authenticate()
    require_role(role, ["ClaimsAdjuster"])
    rec = get_or_404(db.damage_claims, cid, "damage claim")
    if rec["status"] not in ("FILED", "TRIAGED", "SETTLED"):
        raise ApiError(ERR_CLAIM_INVALID_TRANSITION, 409,
                       "void requires status FILED, TRIAGED, or SETTLED")
    was_settled = rec["status"] == "SETTLED"
    rec["status"] = "VOID"
    db.touch(rec)
    # SETTLED -> VOID reversal: credit_issued_cents derives from SETTLED claims,
    # so leaving SETTLED subtracts exactly the residual (compensating pair).
    if not was_settled:
        claim_hold_release_check(db.delivery_loads[rec["delivery_load_id"]])
    return success(serializers.damage_claim(rec))

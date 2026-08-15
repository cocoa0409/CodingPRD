"""Damage claims: holds, segregated review/assessment, settlement cascade (PRD §3.8)."""

from flask import Blueprint, request

from db import public, sort_by_creation, stamp_new, store, touch
from errors import raise_err
from middleware import get_ctx, require_roles
from response import success
from routes.helpers import check_grower_on_claim, get_claim, get_lot, get_run, scope_by_lot_for_grower
from services.calculations import claim_liability_assessment, prepaid_waterfall
from validation import get_body, paginate, req_enum, req_int

bp = Blueprint("claims", __name__)

READ_ROLES = {"ElevatorManager", "Grower", "ClaimsAdjuster"}
DAMAGE_TYPES = {"HEAT_DAMAGE", "STRESS_CRACKING", "MOLD_CONTAMINATION", "EXCESS_SHRINK"}
CLAIM_TERMINAL = {"PAID", "WITHDRAWN"}


def _release_hold(lot):
    if lot is not None and lot["status"] == "DAMAGE_HOLD":
        lot["status"] = "DRIED"
        touch(lot)


@bp.post("/damage-claims")
def create_claim():
    ctx = get_ctx()
    require_roles(ctx, {"Grower"})
    body = get_body()
    # priority 4: body FK existence (lot_id then dryer_run_id, input order)
    lot = None
    run = None
    if body.get("lot_id") is not None:
        lot = get_lot(body["lot_id"])
    if body.get("dryer_run_id") is not None:
        run = get_run(body["dryer_run_id"])
    # priority 3: the owning grower files (filer equals the lot's current owner)
    if lot is not None and lot["current_owner_id"] != ctx["user_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Grower acting on a resource owned by another customer")
    # priority 5: shape
    if not isinstance(body.get("lot_id"), str) or not body["lot_id"]:
        raise_err("ERR_INVALID_REQUEST", "Field lot_id is required")
    if not isinstance(body.get("dryer_run_id"), str) or not body["dryer_run_id"]:
        raise_err("ERR_INVALID_REQUEST", "Field dryer_run_id is required")
    damage_type = req_enum(body, "damage_type", DAMAGE_TYPES)
    claimed = req_int(body, "claimed_amount_cents")
    if claimed <= 0:
        raise_err("ERR_INVALID_REQUEST", "claimed_amount_cents must be positive")
    # lot-state split mapping: delivered lots -> 422; everything else non-DRIED -> 409
    if lot["status"] in ("LOADED_OUT", "BLENDED_OUT"):
        raise_err("ERR_CLAIM_AFTER_DELIVERY", "Claim filed for a lot already LOADED_OUT or BLENDED_OUT")
    if lot["status"] != "DRIED":
        raise_err("ERR_INVALID_STATE", "Lot state does not permit filing a damage claim")
    # priority 10: the named run must reference the claimed lot
    if run["lot_id"] != lot["id"]:
        raise_err("ERR_CLAIM_RUN_MISMATCH", "Claim's dryer_run does not reference the claim's lot")
    rec = stamp_new(
        {
            "lot_id": lot["id"],
            "dryer_run_id": run["id"],
            "damage_type": damage_type,
            "claimed_amount_cents": claimed,
            "status": "FILED",
            "filed_by_user_id": ctx["user_id"],
            "reviewed_by_user_id": None,
            "assessed_by_user_id": None,
            "lot_value_cents": None,
            "fault_multiplier": None,
            "assessed_liability_cents": None,
        }
    )
    store.claims[rec["id"]] = rec
    lot["status"] = "DAMAGE_HOLD"
    touch(lot)
    return success(public(rec), code=201)


@bp.get("/damage-claims")
def list_claims():
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    records = scope_by_lot_for_grower(ctx, list(store.claims.values()), "lot_id")
    for field in ("lot_id", "dryer_run_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/damage-claims/<cid>")
def get_one_claim(cid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_claim(cid)
    check_grower_on_claim(ctx, rec)
    return success(public(rec))


@bp.post("/damage-claims/<cid>/review")
def review_claim(cid):
    ctx = get_ctx()
    require_roles(ctx, {"ClaimsAdjuster"})
    rec = get_claim(cid)
    if rec["status"] in CLAIM_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Damage claim is in a terminal state")
    if rec["status"] not in ("FILED", "APPEALED"):
        raise_err("ERR_INVALID_STATE", "Only a FILED or APPEALED claim may be reviewed")
    # priority 8: reviewer must differ from the filer
    if rec["filed_by_user_id"] == ctx["user_id"]:
        raise_err("ERR_CLAIM_SO_DUTY_VIOLATION", "Claim reviewer equals filer")
    rec["status"] = "UNDER_REVIEW"
    rec["reviewed_by_user_id"] = ctx["user_id"]
    touch(rec)
    return success(public(rec))


@bp.post("/damage-claims/<cid>/assess")
def assess_claim(cid):
    ctx = get_ctx()
    require_roles(ctx, {"ClaimsAdjuster"})
    rec = get_claim(cid)
    if rec["status"] in CLAIM_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Damage claim is in a terminal state")
    if rec["status"] != "UNDER_REVIEW":
        raise_err("ERR_INVALID_STATE", "Only an UNDER_REVIEW claim may be assessed")
    run = store.runs.get(rec["dryer_run_id"])
    if run is None or run["status"] != "COMPLETED":
        raise_err("ERR_INVALID_STATE", "Referenced run must be COMPLETED for assessment")
    # priority 8: assessor differs from filer and from the run's operator
    if ctx["user_id"] == rec["filed_by_user_id"] or ctx["user_id"] == run["operator_user_id"]:
        raise_err("ERR_CLAIM_SO_DUTY_VIOLATION", "Claim assessor equals filer or the run's operator")
    lot = store.lots.get(rec["lot_id"])
    lot_value, multiplier, liability = claim_liability_assessment(rec, lot, run)
    rec["lot_value_cents"] = lot_value
    rec["fault_multiplier"] = multiplier
    rec["assessed_liability_cents"] = liability
    rec["assessed_by_user_id"] = ctx["user_id"]
    rec["status"] = "ASSESSED"
    touch(rec)
    return success(public(rec))


@bp.post("/damage-claims/<cid>/deny")
def deny_claim(cid):
    ctx = get_ctx()
    require_roles(ctx, {"ClaimsAdjuster"})
    rec = get_claim(cid)
    if rec["status"] in CLAIM_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Damage claim is in a terminal state")
    if rec["status"] != "UNDER_REVIEW":
        raise_err("ERR_INVALID_STATE", "Only an UNDER_REVIEW claim may be denied")
    if rec["filed_by_user_id"] == ctx["user_id"]:
        raise_err("ERR_CLAIM_SO_DUTY_VIOLATION", "Claim denier equals filer")
    rec["status"] = "DENIED"
    touch(rec)
    _release_hold(store.lots.get(rec["lot_id"]))
    return success(public(rec))


@bp.post("/damage-claims/<cid>/appeal")
def appeal_claim(cid):
    ctx = get_ctx()
    require_roles(ctx, {"Grower"})
    rec = get_claim(cid)
    check_grower_on_claim(ctx, rec)
    # appeal is open only to the operator in filed_by_user_id
    if rec["filed_by_user_id"] != ctx["user_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Only the filer may appeal a claim")
    if rec["status"] in CLAIM_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Damage claim is in a terminal state")
    if rec["status"] != "DENIED":
        raise_err("ERR_INVALID_STATE", "Only a DENIED claim may be appealed")
    rec["status"] = "APPEALED"
    touch(rec)
    return success(public(rec))


@bp.post("/damage-claims/<cid>/withdraw")
def withdraw_claim(cid):
    ctx = get_ctx()
    require_roles(ctx, {"Grower"})
    rec = get_claim(cid)
    check_grower_on_claim(ctx, rec)
    if rec["filed_by_user_id"] != ctx["user_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Only the filer may withdraw a claim")
    if rec["status"] in CLAIM_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Damage claim is in a terminal state")
    if rec["status"] not in ("FILED", "UNDER_REVIEW"):
        raise_err("ERR_INVALID_STATE", "Only a FILED or UNDER_REVIEW claim may be withdrawn")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    _release_hold(store.lots.get(rec["lot_id"]))
    return success(public(rec))


@bp.post("/damage-claims/<cid>/pay")
def pay_claim(cid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_claim(cid)
    if rec["status"] in CLAIM_TERMINAL:
        raise_err("ERR_ALREADY_TERMINAL", "Damage claim is in a terminal state")
    if rec["status"] != "ASSESSED":
        raise_err("ERR_INVALID_STATE", "Only an ASSESSED claim may be paid")
    lot = store.lots.get(rec["lot_id"])
    customer = store.customers.get(lot["customer_id"]) if lot is not None else None
    # link 1: credit the prepaid ledger
    if customer is not None and rec["assessed_liability_cents"]:
        customer["prepaid_balance_cents"] += rec["assessed_liability_cents"]
        touch(customer)
        # link 2 + 3: auto-apply waterfall; fully covered invoices ISSUED -> PAID
        prepaid_waterfall(customer)
    rec["status"] = "PAID"
    touch(rec)
    _release_hold(lot)
    return success(public(rec))

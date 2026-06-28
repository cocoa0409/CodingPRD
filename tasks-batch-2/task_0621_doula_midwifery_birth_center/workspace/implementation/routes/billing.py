"""Charge, InsuranceClaim, and PaymentPlan routes (financial axis)."""
from flask import Blueprint, request

from db import db
from common import (stamp_new, touch, public, paginate, get_body,
                    require_string, require_int, require_enum)
from errors import (err, ERR_INVALID_STATE, ERR_CLAIM_AMOUNTS_INVALID,
                    ERR_CLAIM_HAS_PLAN, ERR_NO_BALANCE, ERR_OVERPAYMENT,
                    ERR_STALE_VERSION)
from middleware import require_auth, require_role, ALL_ROLES
from response import object_response, array_response
import lookup
from services import calc, cascade

bp = Blueprint("billing", __name__)


# ===========================================================================
# Charge (§3.6)
# ===========================================================================
@bp.route("/birth-center/charges", methods=["POST"])
def create_charge():
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    body = get_body()
    episode_id = require_string(body, "episode_id")
    # Out-of-bundle charges are EXTRA_VISIT or SUPPLY; GLOBAL_FEE/TRANSFER_FEE
    # are created only by the system, never directly.
    charge_kind = require_enum(body, "charge_kind", {"EXTRA_VISIT", "SUPPLY"})
    amount_cents = require_int(body, "amount_cents", minimum=0)
    episode = lookup.get_episode(episode_id)

    rec = {
        "episode_id": episode_id,
        "claim_id": "",
        "charge_kind": charge_kind,
        "amount_cents": amount_cents,
        # extras always carry full client responsibility
        "client_responsibility_cents": amount_cents,
        "status": "DRAFT",
    }
    stamp_new(rec)
    db.charges[rec["id"]] = rec
    # re-derive Episode.balance_due_cents and increment Episode.version by 1.
    calc.rederive_balance(episode)
    touch(episode)
    return object_response(public(rec), 201)


@bp.route("/birth-center/charges/<cid>", methods=["GET"])
def get_charge(cid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_charge(cid)
    return object_response(public(rec), 200)


@bp.route("/birth-center/charges", methods=["GET"])
def list_charges():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    episode_id = request.args.get("episode_id")
    claim_id = request.args.get("claim_id")
    charge_kind = request.args.get("charge_kind")
    status = request.args.get("status")
    records = [r for r in db.charges.values()
               if (episode_id is None or r["episode_id"] == episode_id)
               and (claim_id is None or r.get("claim_id") == claim_id)
               and (charge_kind is None or r["charge_kind"] == charge_kind)
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/charges/<cid>/bill", methods=["POST"])
def bill_charge(cid):
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    rec = lookup.get_charge(cid)
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Charge is not DRAFT")
    rec["status"] = "BILLED"
    touch(rec)
    return object_response(public(rec), 200)


# ===========================================================================
# InsuranceClaim (§3.6)
# ===========================================================================
def _global_charge(episode_id):
    for ch in db.charges.values():
        if ch["episode_id"] == episode_id and ch["charge_kind"] == "GLOBAL_FEE":
            return ch
    return None


@bp.route("/birth-center/insurance-claims", methods=["POST"])
def submit_claim():
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    body = get_body()
    episode_id = require_string(body, "episode_id")
    episode = lookup.get_episode(episode_id)
    rec = {
        "episode_id": episode_id,
        "billed_amount_cents": episode["global_fee_cents"],
        "allowed_amount_cents": 0,
        "paid_amount_cents": 0,
        "status": "SUBMITTED",
    }
    stamp_new(rec)
    db.insurance_claims[rec["id"]] = rec
    # Link the episode's GLOBAL_FEE charge to this claim.
    gch = _global_charge(episode_id)
    if gch is not None:
        gch["claim_id"] = rec["id"]
        touch(gch)
    return object_response(public(rec), 201)


@bp.route("/birth-center/insurance-claims/<cid>", methods=["GET"])
def get_claim(cid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_claim(cid)
    return object_response(public(rec), 200)


@bp.route("/birth-center/insurance-claims", methods=["GET"])
def list_claims():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    episode_id = request.args.get("episode_id")
    status = request.args.get("status")
    records = [r for r in db.insurance_claims.values()
               if (episode_id is None or r["episode_id"] == episode_id)
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/insurance-claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    rec = lookup.get_claim(cid)
    body = get_body()
    allowed = require_int(body, "allowed_amount_cents", minimum=0)
    paid = require_int(body, "paid_amount_cents", minimum=0)
    # state check (priority 6)
    if rec["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Claim is not SUBMITTED")
    # amounts ordering (priority 14): paid <= allowed <= billed
    if not (paid <= allowed <= rec["billed_amount_cents"]):
        raise err(ERR_CLAIM_AMOUNTS_INVALID, "paid <= allowed <= billed ordering violated")
    rec["allowed_amount_cents"] = allowed
    rec["paid_amount_cents"] = paid
    rec["status"] = "ADJUDICATED"
    touch(rec)
    episode = db.episodes.get(rec["episode_id"])
    if episode is not None:
        cascade.recompute_after_claim_change(episode)
    return object_response(public(rec), 200)


@bp.route("/birth-center/insurance-claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    rec = lookup.get_claim(cid)
    if rec["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Claim is not SUBMITTED")
    rec["status"] = "DENIED"
    touch(rec)
    episode = db.episodes.get(rec["episode_id"])
    if episode is not None:
        cascade.recompute_after_claim_change(episode)
    return object_response(public(rec), 200)


@bp.route("/birth-center/insurance-claims/<cid>/void", methods=["POST"])
def void_claim(cid):
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    rec = lookup.get_claim(cid)
    if rec["status"] not in ("SUBMITTED", "DENIED"):
        raise err(ERR_INVALID_STATE, "Claim cannot be voided from this state")
    # blocked while a PaymentPlan exists on the episode (priority 20)
    for p in db.payment_plans.values():
        if p["episode_id"] == rec["episode_id"]:
            raise err(ERR_CLAIM_HAS_PLAN, "Cannot void a claim while a payment plan exists")
    rec["status"] = "VOID"
    touch(rec)
    episode = db.episodes.get(rec["episode_id"])
    if episode is not None:
        cascade.recompute_after_claim_change(episode)
    return object_response(public(rec), 200)


# ===========================================================================
# PaymentPlan (§3.10) — OCC on Episode.version, waterfall allocation
# ===========================================================================
def _build_schedule(total_cents, installment_count):
    base = total_cents // installment_count
    remainder = total_cents - base * installment_count
    schedule = []
    for i in range(installment_count):
        due = base + 1 if i < remainder else base
        schedule.append({"due": due, "paid": 0})
    return schedule


@bp.route("/birth-center/payment-plans", methods=["POST"])
def create_plan():
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    body = get_body()
    episode_id = require_string(body, "episode_id")
    installment_count = require_int(body, "installment_count", minimum=1)
    expected_episode_version = require_int(body, "expected_episode_version")
    episode = lookup.get_episode(episode_id)

    # state check (priority 6): financial axis must be UNBILLED.
    if episode["financial_status"] != "UNBILLED":
        raise err(ERR_INVALID_STATE, "Episode financial status is not UNBILLED")
    # balance must be > 0 (priority 17).
    if episode["balance_due_cents"] <= 0:
        raise err(ERR_NO_BALANCE, "Episode has no balance to plan")
    # OCC (priority 21).
    if expected_episode_version != episode["version"]:
        raise err(ERR_STALE_VERSION, "expected_episode_version does not match current episode version")

    total = episode["balance_due_cents"]
    rec = {
        "episode_id": episode_id,
        "total_cents": total,
        "installment_count": installment_count,
        "paid_cents": 0,
        "remaining_cents": total,
        "status": "OPEN",
        "_schedule": _build_schedule(total, installment_count),
    }
    stamp_new(rec)
    db.payment_plans[rec["id"]] = rec
    # financial axis UNBILLED -> PLAN_ACTIVE; bump episode version.
    episode["financial_status"] = "PLAN_ACTIVE"
    calc.rederive_balance(episode)
    touch(episode)
    return object_response(public(rec), 201)


@bp.route("/birth-center/payment-plans/<pid>", methods=["GET"])
def get_plan(pid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_payment_plan(pid)
    return object_response(public(rec), 200)


@bp.route("/birth-center/payment-plans/<pid>/payments", methods=["POST"])
def apply_payment(pid):
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    rec = lookup.get_payment_plan(pid)
    body = get_body()
    amount = require_int(body, "amount_cents", minimum=0)
    if rec["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Plan is not OPEN")
    # overpayment forbidden (priority 16): amount must not exceed remaining.
    if amount > rec["remaining_cents"]:
        raise err(ERR_OVERPAYMENT, "Payment exceeds remaining balance")

    # Waterfall allocation: walk installments in order, fill each before moving on.
    remaining_payment = amount
    for inst in rec["_schedule"]:
        if remaining_payment <= 0:
            break
        outstanding = inst["due"] - inst["paid"]
        if outstanding <= 0:
            continue
        applied = min(remaining_payment, outstanding)
        inst["paid"] += applied
        remaining_payment -= applied

    rec["paid_cents"] += amount
    rec["remaining_cents"] = rec["total_cents"] - rec["paid_cents"]
    touch(rec)

    episode = db.episodes.get(rec["episode_id"])
    if rec["remaining_cents"] == 0:
        rec["status"] = "PAID_OFF"
        # cascade: financial PLAN_ACTIVE -> SETTLED, BILLED charges -> PAID.
        if episode is not None and episode["financial_status"] == "PLAN_ACTIVE":
            cascade.settle_cascade(episode)
            calc.rederive_balance(episode)
            touch(episode)
    return object_response(public(rec), 200)


@bp.route("/birth-center/payment-plans/<pid>/default", methods=["POST"])
def default_plan(pid):
    _, role = require_auth()
    require_role(role, ["BillingClerk"])
    rec = lookup.get_payment_plan(pid)
    if rec["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Plan is not OPEN")
    if rec["remaining_cents"] <= 0:
        raise err(ERR_INVALID_STATE, "Plan has no remaining balance to default")
    rec["status"] = "DEFAULTED"
    touch(rec)
    return object_response(public(rec), 200)

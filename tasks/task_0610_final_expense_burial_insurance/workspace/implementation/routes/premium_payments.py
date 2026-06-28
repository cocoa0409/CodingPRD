"""PremiumPayment endpoints (PRD §3.6)."""
from flask import Blueprint, request

import db
from clock import get_now, parse_iso, format_iso_millis
from errors import err
from helpers import get_body, require_fields, serialize, paginate, sort_by_created
from middleware import get_identity, require_roles, require_owner_if_policyholder
from response import success
from services import policy_calc, ledger

bp = Blueprint("premium_payments", __name__)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test. Adjacency (a_end == b_start) is not overlap."""
    return a_start < b_end and b_start < a_end


@bp.route("/premium-payments", methods=["POST"])
def post_premium():
    user_id, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Policyholder"})
    body = get_body()
    require_fields(body, ["policy_id", "amount_cents", "coverage_start", "coverage_end"])
    policy = db.policies.get(body["policy_id"])
    if policy is None:
        raise err("ERR_NOT_FOUND", "Policy not found")
    require_owner_if_policyholder(role, user_id, policy)

    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise err("ERR_VALIDATION", "amount_cents must be a positive integer")
    cs = parse_iso(body["coverage_start"])
    ce = parse_iso(body["coverage_end"])
    if cs is None or ce is None:
        raise err("ERR_VALIDATION", "coverage_start/coverage_end must be valid ISO 8601")
    if not (cs < ce):
        raise err("ERR_VALIDATION", "coverage_start must be strictly before coverage_end")

    # Overlap against existing POSTED payments on the same policy.
    for p in db.premium_payments.values():
        if p["policy_id"] != policy["id"] or p["status"] != "POSTED":
            continue
        ps = parse_iso(p["coverage_start"])
        pe = parse_iso(p["coverage_end"])
        if _intervals_overlap(cs, ce, ps, pe):
            raise err("ERR_COVERAGE_PERIOD_OVERLAP", "Coverage interval overlaps an existing payment")

    payment = {
        "policy_id": policy["id"],
        "amount_cents": amount,
        "coverage_start": body["coverage_start"],
        "coverage_end": body["coverage_end"],
        "posted_date": format_iso_millis(get_now()),
        "status": "POSTED",
    }
    with db.LOCK:
        db.stamp_full(payment)
        db.premium_payments[payment["id"]] = payment
        # Recompute paid_through/due/total; restore CURRENT if applicable.
        policy_calc.recompute_policy(policy)
        _maybe_restore_current(policy)
        ledger.append(policy["id"], "PREMIUM_POSTED", amount, policy["net_cash_value_cents"])
        db.touch(policy)
    return success(serialize(payment), status=201, response_type="object")


def _maybe_restore_current(policy):
    """If payment_status was GRACE/DELINQUENT and paid_through now past the clock,
    payment_status returns to CURRENT (PRD §3.6)."""
    if policy["coverage_status"] != "ACTIVE":
        return
    due = parse_iso(policy["due_date"])
    if policy["payment_status"] in ("GRACE", "DELINQUENT") and due > get_now():
        policy["payment_status"] = "CURRENT"


@bp.route("/premium-payments/<payment_id>", methods=["GET"])
def get_premium(payment_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Policyholder", "ClaimsExaminer"})
    payment = db.premium_payments.get(payment_id)
    if payment is None:
        raise err("ERR_NOT_FOUND", "PremiumPayment not found")
    return success(serialize(payment), status=200, response_type="object")


@bp.route("/premium-payments", methods=["GET"])
def list_premiums():
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Policyholder", "ClaimsExaminer"})
    items = list(db.premium_payments.values())
    policy_id = request.args.get("policy_id")
    status = request.args.get("status")
    if policy_id:
        items = [p for p in items if p["policy_id"] == policy_id]
    if status:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(p) for p in page], status=200, response_type="array", pagination=meta)


@bp.route("/premium-payments/<payment_id>/reverse", methods=["POST"])
def reverse_premium(payment_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin"})
    payment = db.premium_payments.get(payment_id)
    if payment is None:
        raise err("ERR_NOT_FOUND", "PremiumPayment not found")
    if payment["status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "PremiumPayment is not POSTED")
    with db.LOCK:
        payment["status"] = "REVERSED"
        db.touch(payment)
        policy = db.policies.get(payment["policy_id"])
        if policy is not None:
            policy_calc.recompute_policy(policy)
            ledger.append(policy["id"], "PREMIUM_REVERSED", -payment["amount_cents"],
                          policy["net_cash_value_cents"])
            db.touch(policy)
    return success(serialize(payment), status=200, response_type="object")

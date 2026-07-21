"""Recovery payment endpoints and the allocation waterfall (§3.6)."""
from flask import Blueprint, request

import calc
import errors
import serialize
import validate as v
from auth import authorize
from envelope import success
from helpers import lookup_or_404, respond_list
from store import db, stamp, touch, clock_now

bp = Blueprint("payments", __name__)


def _deductible_committed(claim_id):
    """Sum of alloc_deductible_cents across currently-CLEARED payments on the claim."""
    total = 0
    for p in db.recovery_payments.values():
        if p["claim_id"] == claim_id and p["status"] == "CLEARED":
            total += p["alloc_deductible_cents"] or 0
    return total


def _cleared_sum(claim_id):
    total = 0
    for p in db.recovery_payments.values():
        if p["claim_id"] == claim_id and p["status"] == "CLEARED":
            total += p["amount_cents"]
    return total


@bp.route("/subro/claims/<claim_id>/recovery-payments", methods=["POST"])
def record_payment(claim_id):
    authorize(request, {"FinanceOfficer"})
    claim = lookup_or_404(db.claims, claim_id)
    body = v.get_body(request)
    amount = v.req_int(body, "amount_cents", gt=0)

    # (7) state: claim must be settled to book money against it
    if claim["status"] not in {"SETTLED", "RECOVERED"}:
        raise errors.invalid_state()
    # (11) fiscal ceiling: cleared-so-far + this must not exceed settled amount
    if _cleared_sum(claim_id) + amount > claim["settled_amount_cents"]:
        raise errors.payment_exceeds_settlement()

    payment = stamp({
        "claim_id": claim_id,
        "amount_cents": amount,
        "received_at": clock_now(),
        "alloc_deductible_cents": None,
        "alloc_carrier_cents": None,
        "alloc_commission_cents": None,
        "status": "RECEIVED",
    })
    db.recovery_payments[payment["id"]] = payment
    return success(serialize.recovery_payment(payment), "object", 201)


@bp.route("/subro/recovery-payments/<recovery_payment_id>", methods=["GET"])
def get_payment(recovery_payment_id):
    authorize(request, None)
    payment = lookup_or_404(db.recovery_payments, recovery_payment_id)
    return success(serialize.recovery_payment(payment), "object", 200)


@bp.route("/subro/recovery-payments", methods=["GET"])
def list_payments():
    authorize(request, None)
    claim_id = request.args.get("claim_id")
    status = request.args.get("status")
    items = []
    for p in db.recovery_payments.values():
        if claim_id is not None and p["claim_id"] != claim_id:
            continue
        if status is not None and p["status"] != status:
            continue
        items.append(p)
    return respond_list(request, items, serialize.recovery_payment)


@bp.route("/subro/recovery-payments/<recovery_payment_id>/clear", methods=["POST"])
def clear_payment(recovery_payment_id):
    authorize(request, {"FinanceOfficer"})
    payment = lookup_or_404(db.recovery_payments, recovery_payment_id)
    claim = db.claims[payment["claim_id"]]
    # (7) state
    if payment["status"] != "RECEIVED" or claim["status"] not in {"SETTLED", "RECOVERED"}:
        raise errors.invalid_state()

    carrier = db.carriers[claim["carrier_id"]]
    outstanding = claim["deductible_cents"] - _deductible_committed(claim["id"])
    if outstanding < 0:
        outstanding = 0
    alloc_deductible = min(payment["amount_cents"], outstanding)
    rem1 = payment["amount_cents"] - alloc_deductible
    alloc_commission = calc.commission_on(rem1, carrier["commission_rate_bps"])
    alloc_carrier = rem1 - alloc_commission

    payment["alloc_deductible_cents"] = alloc_deductible
    payment["alloc_commission_cents"] = alloc_commission
    payment["alloc_carrier_cents"] = alloc_carrier
    payment["status"] = "CLEARED"
    touch(payment)

    # cascade onto the claim ledger
    claim["final_recovered_cents"] += payment["amount_cents"]
    claim["carrier_recovered_cents"] += alloc_carrier
    claim["accrued_commission_cents"] += alloc_commission
    if claim["status"] == "SETTLED" and claim["final_recovered_cents"] >= claim["settled_amount_cents"]:
        claim["status"] = "RECOVERED"
    touch(claim)

    # downstream deductible reimbursement
    if alloc_deductible > 0:
        reimb = stamp({
            "claim_id": claim["id"],
            "recovery_payment_id": payment["id"],
            "amount_cents": alloc_deductible,
            "disbursed_at": None,
            "status": "PENDING",
        })
        db.deductible_reimbursements[reimb["id"]] = reimb

    return success(serialize.recovery_payment(payment), "object", 200)


@bp.route("/subro/recovery-payments/<recovery_payment_id>/reverse", methods=["POST"])
def reverse_payment(recovery_payment_id):
    authorize(request, {"FinanceOfficer"})
    payment = lookup_or_404(db.recovery_payments, recovery_payment_id)

    if payment["status"] == "RECEIVED":
        payment["status"] = "BOUNCED"
        touch(payment)
        return success(serialize.recovery_payment(payment), "object", 200)

    if payment["status"] != "CLEARED":
        raise errors.invalid_state()

    claim = db.claims[payment["claim_id"]]
    # compensation — exactly back out the bookings
    claim["final_recovered_cents"] -= payment["amount_cents"]
    claim["carrier_recovered_cents"] -= payment["alloc_carrier_cents"]
    claim["accrued_commission_cents"] -= payment["alloc_commission_cents"]
    if claim["status"] == "RECOVERED" and claim["final_recovered_cents"] < claim["settled_amount_cents"]:
        claim["status"] = "SETTLED"
    # claw back the funded reimbursement
    for r in db.deductible_reimbursements.values():
        if r["recovery_payment_id"] == payment["id"] and r["status"] in {"PENDING", "DISBURSED"}:
            if r["status"] == "DISBURSED":
                claim["deductible_reimbursed_cents"] -= r["amount_cents"]
            r["status"] = "CLAWED_BACK"
            touch(r)
    touch(claim)

    payment["status"] = "REVERSED"
    touch(payment)
    return success(serialize.recovery_payment(payment), "object", 200)

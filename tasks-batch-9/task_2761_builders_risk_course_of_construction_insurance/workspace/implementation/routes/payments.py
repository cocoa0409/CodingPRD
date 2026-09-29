"""LossPayment endpoints (PRD 3.8): the four-hop erosion cascade and its exact reversal."""
from flask import Blueprint

import lookup
import recompute
from db import by_policy, new_row, ordered, store, touch
from enums import LOSS_PAYMENT_STATUSES, PART_TYPES
from errors import ApiError
from middleware import authenticate, body, filter_enum, filter_str, get_enum, get_int, \
    pagination, paginate
from response import created, ok, ok_list

bp = Blueprint("payments", __name__)


def _apply_axes(claim, policy):
    """Hops two to four: recompute money, then derive both state axes from paid_cents."""
    recompute.recompute_erosion(policy, claim)
    paid = claim["paid_cents"]
    indemnity = claim["indemnity_cents"]
    if paid <= 0:
        claim["payment_status"] = "UNPAID"
    elif paid >= indemnity:
        claim["payment_status"] = "PAID"
    else:
        claim["payment_status"] = "PARTIALLY_PAID"
    if claim["payment_status"] == "PAID" and claim["adjustment_status"] == "SETTLED":
        claim["adjustment_status"] = "CLOSED"
    elif claim["payment_status"] != "PAID" and claim["adjustment_status"] == "CLOSED":
        claim["adjustment_status"] = "SETTLED"
    touch(claim)
    touch(policy)


@bp.post("/loss-payments")
def issue_payment():
    user_id, _role = authenticate("ClaimAdjuster")
    payload = body()
    claim = lookup.fk_claim(payload)
    interest = lookup.fk_interest(payload)
    part_type = get_enum(payload, "part_type", PART_TYPES)
    amount_cents = get_int(payload, "amount_cents", minimum=1)
    expected = get_int(payload, "expected_claim_version", minimum=0)
    if expected != claim["version"]:
        raise ApiError(
            "ERR_STALE_CLAIM_VERSION", "expected_claim_version does not match the stored version."
        )
    policy = store.policies[claim["policy_id"]]
    if claim["adjustment_status"] not in ("ADJUSTED", "SETTLED"):
        raise ApiError(
            "ERR_INVALID_CLAIM_STATE", "Payment requires an ADJUSTED or SETTLED claim."
        )
    if policy["status"] not in ("IN_FORCE", "EXPIRED", "CANCELLED"):
        raise ApiError(
            "ERR_INVALID_CLAIM_STATE",
            "Payment requires a policy that is IN_FORCE, EXPIRED or CANCELLED.",
        )
    if interest["policy_id"] != policy["id"] or interest["loss_payee_priority"] is None:
        raise ApiError(
            "ERR_PAYEE_NOT_ON_POLICY",
            "The payee must be a loss payee named on the claim's own policy.",
        )
    line = next(
        (row for row in claim["allocation_lines"] if row["part_type"] == part_type), None
    )
    if line is None or line["allocated_cents"] <= 0:
        raise ApiError(
            "ERR_PAYMENT_PART_NOT_ALLOCATED",
            "The claim has no positive allocation line for this part_type.",
        )
    already = recompute.issued_paid_for_part(claim["id"], part_type)
    if already + amount_cents > line["allocated_cents"]:
        raise ApiError(
            "ERR_PAYMENT_EXCEEDS_ALLOCATION",
            "Cumulative payments for this part_type would exceed its allocated amount.",
        )
    if amount_cents > claim["outstanding_reserve_cents"]:
        raise ApiError(
            "ERR_PAYMENT_EXCEEDS_RESERVE",
            "The payment would exceed the claim's outstanding reserve.",
        )
    part = next(
        (row for row in by_policy(store.coverage_parts, policy["id"])
         if row["part_type"] == part_type), None
    )
    if part is not None and amount_cents > part["available_cents"]:
        raise ApiError(
            "ERR_PAYMENT_EXCEEDS_RESERVE",
            "The payment would exceed the coverage part's remaining availability.",
        )
    row = new_row()
    row.update({
        "claim_id": claim["id"],
        "payee_interest_id": interest["id"],
        "part_type": part_type,
        "amount_cents": amount_cents,
        "status": "ISSUED",
        "created_by_user_id": user_id,
        "voided_by_user_id": None,
    })
    store.payments[row["id"]] = row
    _apply_axes(claim, policy)
    return created(row)


@bp.post("/loss-payments/<payment_id>/void")
def void_payment(payment_id):
    user_id, _role = authenticate("UnderwritingManager")
    payment = lookup.payment(payment_id)
    if payment["created_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The issuing user may not void the same payment."
        )
    if payment["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_PAYMENT_STATE", "Only an ISSUED payment may be voided.")
    payment["status"] = "VOIDED"
    payment["voided_by_user_id"] = user_id
    touch(payment)
    claim = store.claims[payment["claim_id"]]
    policy = store.policies[claim["policy_id"]]
    _apply_axes(claim, policy)
    return ok(payment)


@bp.get("/loss-payments")
def list_payments():
    user_id, role = authenticate(
        "Underwriter", "UnderwritingManager", "ClaimAdjuster", "LossPayee"
    )
    limit, offset = pagination()
    claim_id = filter_str("claim_id")
    payee_interest_id = filter_str("payee_interest_id")
    status = filter_enum("status", LOSS_PAYMENT_STATUSES)
    if role == "LossPayee":
        if payee_interest_id is not None and payee_interest_id != user_id:
            raise ApiError(
                "ERR_NOT_RESOURCE_OWNER",
                "A LossPayee may only list payments made to its own interest.",
            )
        payee_interest_id = user_id
    rows = ordered(list(store.payments.values()))
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if payee_interest_id is not None:
        rows = [r for r in rows if r["payee_interest_id"] == payee_interest_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/loss-payments/<payment_id>")
def read_payment(payment_id):
    user_id, role = authenticate(
        "Underwriter", "UnderwritingManager", "ClaimAdjuster", "LossPayee"
    )
    payment = lookup.payment(payment_id)
    if role == "LossPayee" and payment["payee_interest_id"] != user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "A LossPayee may only read its own loss payments."
        )
    return ok(payment)

"""Design proofs: post (first/subsequent), approve, request-changes, list."""
from flask import Blueprint, request, g

import serializers as S
import validators as V
from db import store
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_auth
from response import success, list_response, parse_pagination
from services import calculations as calc
from services.orders import get_order_or_404, assert_owner, order_lines

bp = Blueprint("proofs", __name__)


def _order_proofs(oid):
    items = [p for p in store.proofs.values() if p["order_id"] == oid]
    return sorted(items, key=lambda p: (p["created_at"], p["id"]))


def _get_proof(oid, pid):
    proof = store.proofs.get(pid)
    if proof is None or proof["order_id"] != oid:
        raise err(ERR_NOT_FOUND, "proof not found")
    return proof


@bp.route("/orders/<oid>/proofs", methods=["POST"])
@require_auth(["BakeryStaff"])
def post_proof(oid):
    order = get_order_or_404(oid)
    data = V.body()
    image_ref = V.require_str(data, "image_ref")

    status = order["production_status"]
    if status == "QUOTED":
        # first proof: gated on deposit captured
        if order["payment_status"] != "DEPOSIT_PAID":
            raise err(ERR_INVALID_STATE, "first proof requires DEPOSIT_PAID")
    elif status == "CHANGES_REQUESTED":
        # subsequent proof: no proof currently AWAITING_REVIEW
        if any(p["proof_status"] == "AWAITING_REVIEW" for p in store.proofs.values()
               if p["order_id"] == oid):
            raise err(ERR_INVALID_STATE, "an awaiting-review proof already exists")
    else:
        raise err(ERR_INVALID_STATE, "cannot post a proof in this state")

    prior_max = max(
        [p["revision_number"] for p in store.proofs.values() if p["order_id"] == oid],
        default=0,
    )
    proof = {
        "order_id": oid,
        "revision_number": prior_max + 1,
        "image_ref": image_ref,
        "proof_status": "AWAITING_REVIEW",
        "change_note": None,
    }
    store.stamp_create(proof)
    store.proofs[proof["id"]] = proof

    order["production_status"] = "PROOF_PENDING"
    store.touch(order)
    return success(S.proof(proof), status=201)


@bp.route("/orders/<oid>/proofs", methods=["GET"])
@require_auth(["Customer", "BakeryStaff", "BakeryManager"])
def list_proofs(oid):
    order = get_order_or_404(oid)
    assert_owner(order)
    limit, offset = parse_pagination(request.args)
    items = _order_proofs(oid)
    return list_response([S.proof(p) for p in items], limit, offset)


@bp.route("/orders/<oid>/proofs/<pid>/approve", methods=["POST"])
@require_auth(["Customer"])
def approve_proof(oid, pid):
    order = get_order_or_404(oid)
    assert_owner(order)
    proof = _get_proof(oid, pid)

    if order["production_status"] != "PROOF_PENDING" or proof["proof_status"] != "AWAITING_REVIEW":
        raise err(ERR_INVALID_STATE, "proof not approvable in this state")

    # approve this proof; supersede other AWAITING_REVIEW / REJECTED proofs
    proof["proof_status"] = "APPROVED"
    store.touch(proof)
    for other in store.proofs.values():
        if other["order_id"] != oid or other["id"] == pid:
            continue
        if other["proof_status"] in ("AWAITING_REVIEW", "REJECTED"):
            other["proof_status"] = "SUPERSEDED"
            store.touch(other)

    # final pricing locks now
    order["production_status"] = "PROOF_APPROVED"
    product = store.products[order["product_id"]]
    pday = store.production_days[order["production_day_id"]]
    lines = order_lines(oid)
    final_total, peak = calc.compute_pricing(lines, product, pday)
    order["final_total_cents"] = final_total
    order["peak_surcharge_cents"] = peak

    captured_deposit = sum(
        p["amount_cents"] for p in store.payments.values()
        if p["order_id"] == oid and p["kind"] == "DEPOSIT"
    )
    order["balance_due_cents"] = final_total - captured_deposit
    store.touch(order)
    return success(S.proof(proof), status=200)


@bp.route("/orders/<oid>/proofs/<pid>/request-changes", methods=["POST"])
@require_auth(["Customer"])
def request_changes(oid, pid):
    order = get_order_or_404(oid)
    assert_owner(order)
    proof = _get_proof(oid, pid)

    data = V.body()
    change_note = V.optional_str(data, "change_note", default=None)

    if order["production_status"] != "PROOF_PENDING" or proof["proof_status"] != "AWAITING_REVIEW":
        raise err(ERR_INVALID_STATE, "proof not rejectable in this state")

    proof["proof_status"] = "REJECTED"
    if change_note is not None:
        proof["change_note"] = change_note
    store.touch(proof)

    order["production_status"] = "CHANGES_REQUESTED"
    store.touch(order)
    return success(S.proof(proof), status=200)

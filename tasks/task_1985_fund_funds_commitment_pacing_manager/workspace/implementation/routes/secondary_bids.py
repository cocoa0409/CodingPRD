"""SecondaryBid endpoints: propose, counter, accept, settle, reject, withdraw."""

from flask import Blueprint, request

import db
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REF_NOT_FOUND, ERR_INVALID_STATE,
    ERR_POSTURE_GATED, ERR_PREMIUM_CAP_EXCEEDED, ERR_DISCOUNT_CAP_EXCEEDED,
    ERR_BUFFER_BREACH, ERR_STALE_VERSION, ERR_INVALID_REQUEST,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from services import domain
from util import dec, frac4
from validate import body, req_str, req_enum, req_positive_num, req_nonneg_num

bp = Blueprint("secondary_bids", __name__)

SIDES = ["PURCHASE", "SALE"]


def get_program_or_404(pid):
    prog = STORE.programs.get(pid)
    if prog is None:
        raise_err(ERR_NOT_FOUND, "program id does not exist")
    return prog


def get_bid_or_404(pid, bid_id):
    b = STORE.secondary_bids.get(bid_id)
    if b is None or b["program_id"] != pid:
        raise_err(ERR_NOT_FOUND, "secondary bid id does not exist")
    return b


@bp.route("/fof/programs/<pid>/secondary-bids", methods=["POST"])
def propose_bid(pid):
    _, role = auth_context()
    require_role(role, ["Analyst"])
    prog = get_program_or_404(pid)
    data = body()
    vehicle_id = req_str(data, "vehicle_id")
    if STORE.vehicles.get(vehicle_id) is None:
        raise_err(ERR_REF_NOT_FOUND, "vehicle_id does not exist")
    side = req_enum(data, "side", SIDES)
    nav_basis = req_positive_num(data, "nav_basis")
    price = req_positive_num(data, "price")
    unfunded_assumed = data.get("unfunded_assumed")
    linked_commitment_id = data.get("linked_commitment_id")
    if side == "PURCHASE":
        if unfunded_assumed is None:
            raise_err(ERR_INVALID_REQUEST,
                      "unfunded_assumed is required for PURCHASE")
        if linked_commitment_id is not None:
            raise_err(ERR_INVALID_REQUEST,
                      "linked_commitment_id must be null for PURCHASE")
    else:  # SALE
        if linked_commitment_id is None:
            raise_err(ERR_INVALID_REQUEST,
                      "linked_commitment_id is required for SALE")
        if unfunded_assumed is not None and dec(unfunded_assumed) != 0:
            raise_err(ERR_INVALID_REQUEST,
                      "unfunded_assumed must be 0 for SALE")
    if unfunded_assumed is None:
        unfunded_assumed = 0
    if dec(unfunded_assumed) < 0:
        raise_err(ERR_INVALID_REQUEST, "unfunded_assumed must be >= 0")
    if linked_commitment_id is not None:
        if STORE.commitments.get(linked_commitment_id) is None:
            raise_err(ERR_REF_NOT_FOUND, "linked_commitment_id does not exist")
    deviation = (dec(price) - dec(nav_basis)) / dec(nav_basis)
    bid = new_entity(STORE.secondary_bids, {
        "program_id": pid,
        "vehicle_id": vehicle_id,
        "side": side,
        "nav_basis": nav_basis,
        "price": price,
        "unfunded_assumed": unfunded_assumed,
        "pricing_deviation_pct": frac4(deviation),
        "linked_commitment_id": linked_commitment_id,
        "status": "PROPOSED",
    })
    return ok(public(bid), status=201)


@bp.route("/fof/programs/<pid>/secondary-bids", methods=["GET"])
def list_bids(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    rows = [b for b in STORE.secondary_bids.values() if b["program_id"] == pid]
    return list_response(rows, filters={
        "status": request.args.get("status"),
        "side": request.args.get("side"),
    })


@bp.route("/fof/programs/<pid>/secondary-bids/<bid_id>", methods=["GET"])
def get_bid(pid, bid_id):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    return ok(public(get_bid_or_404(pid, bid_id)))


@bp.route("/fof/programs/<pid>/secondary-bids/<bid_id>/counter", methods=["POST"])
def counter_bid(pid, bid_id):
    _, role = auth_context()
    require_role(role, ["InvestmentCommittee"])
    prog = get_program_or_404(pid)
    bid = get_bid_or_404(pid, bid_id)
    if bid["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "bid is not PROPOSED")
    if prog["posture"] == "FROZEN":
        raise_err(ERR_POSTURE_GATED, "program posture is FROZEN")
    bid["status"] = "COUNTERED"
    touch(bid)
    return ok(public(bid))


@bp.route("/fof/programs/<pid>/secondary-bids/<bid_id>/accept", methods=["POST"])
def accept_bid(pid, bid_id):
    _, role = auth_context()
    require_role(role, ["CIO"])
    prog = get_program_or_404(pid)
    bid = get_bid_or_404(pid, bid_id)
    if bid["status"] not in ("PROPOSED", "COUNTERED"):
        raise_err(ERR_INVALID_STATE, "bid is not PROPOSED or COUNTERED")
    if prog["status"] != "OPEN" or prog["posture"] != "NORMAL":
        raise_err(ERR_POSTURE_GATED, "program must be OPEN with posture NORMAL")
    deviation = dec(bid["pricing_deviation_pct"])
    if bid["side"] == "PURCHASE":
        if deviation > dec(prog["secondary_premium_cap_pct"]):
            raise_err(ERR_PREMIUM_CAP_EXCEEDED,
                      "purchase premium exceeds secondary_premium_cap_pct")
    else:
        if -deviation > dec(prog["secondary_discount_cap_pct"]):
            raise_err(ERR_DISCOUNT_CAP_EXCEEDED,
                      "sale discount exceeds secondary_discount_cap_pct")
        linked = STORE.commitments.get(bid["linked_commitment_id"])
        if (linked is None or linked["status"] != "EXECUTED"
                or linked["program_id"] != pid
                or linked["vehicle_id"] != bid["vehicle_id"]):
            raise_err(ERR_INVALID_STATE,
                      "linked commitment must be EXECUTED for this program and vehicle")
    bid["status"] = "ACCEPTED"
    touch(bid)
    return ok(public(bid))


@bp.route("/fof/programs/<pid>/secondary-bids/<bid_id>/settle", methods=["POST"])
def settle_bid(pid, bid_id):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    data = body()
    prog = get_program_or_404(pid)
    bid = get_bid_or_404(pid, bid_id)
    expected = data.get("expected_program_version")
    if expected is None:
        raise_err(ERR_INVALID_REQUEST, "expected_program_version is required")
    if expected != prog["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_program_version does not match the current version")
    if bid["status"] != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, "bid is not ACCEPTED")
    if prog["posture"] == "FROZEN":
        raise_err(ERR_POSTURE_GATED, "program posture is FROZEN")
    if bid["side"] == "PURCHASE":
        if (dec(prog["unrestricted_cash"]) - dec(bid["price"])
                < dec(prog["liquidity_buffer_min"])):
            raise_err(ERR_BUFFER_BREACH,
                      "settlement would leave unrestricted_cash below the buffer")
        # All checks pass: move cash, spawn the EXECUTED commitment.
        domain.append_ledger(prog, "SECONDARY_SETTLEMENT_OUT", -dec(bid["price"]),
                             ref_entity="SecondaryBid", ref_id=bid["id"])
        new_entity(STORE.commitments, {
            "program_id": pid,
            "vehicle_id": bid["vehicle_id"],
            "proposal_id": None,
            "sized_amount": float(domain.money2_dec(
                dec(bid["price"]) + dec(bid["unfunded_assumed"]))),
            "unfunded_amount": bid["unfunded_assumed"],
            "status": "EXECUTED",
            "executed_at": db.now_iso(),
        })
        domain.recompute_program_aggregates(prog)
        domain.recompute_posture(prog)
    else:  # SALE
        linked = STORE.commitments.get(bid["linked_commitment_id"])
        if linked is None:
            raise_err(ERR_REF_NOT_FOUND, "linked commitment does not exist")
        paid = domain.paid_calls_total(linked["id"])
        if dec(linked["unfunded_amount"]) != dec(linked["sized_amount"]) - paid:
            raise_err(ERR_INVALID_STATE,
                      "linked commitment unfunded consistency check failed")
        domain.append_ledger(prog, "SECONDARY_SETTLEMENT_IN", dec(bid["price"]),
                             ref_entity="SecondaryBid", ref_id=bid["id"])
        linked["sized_amount"] = float(domain.money2_dec(paid))
        linked["unfunded_amount"] = 0
        linked["status"] = "REDUCED"
        touch(linked)
        domain.recompute_program_aggregates(prog)
        domain.recompute_posture(prog)
    bid["status"] = "SETTLED"
    touch(bid)
    # append_ledger already bumped the program version; settlement itself is
    # also a guarded write, so recompute + bump once more for the bid settle.
    domain.recompute_program_aggregates(prog)
    domain.recompute_posture(prog)
    touch(prog)
    return ok(public(bid))


@bp.route("/fof/programs/<pid>/secondary-bids/<bid_id>/reject", methods=["POST"])
def reject_bid(pid, bid_id):
    _, role = auth_context()
    require_role(role, ["CIO"])
    get_program_or_404(pid)
    bid = get_bid_or_404(pid, bid_id)
    if bid["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "bid is not PROPOSED")
    bid["status"] = "REJECTED"
    touch(bid)
    return ok(public(bid))


@bp.route("/fof/programs/<pid>/secondary-bids/<bid_id>/withdraw", methods=["POST"])
def withdraw_bid(pid, bid_id):
    _, role = auth_context()
    require_role(role, ["Analyst"])
    get_program_or_404(pid)
    bid = get_bid_or_404(pid, bid_id)
    if bid["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "bid is not PROPOSED")
    bid["status"] = "WITHDRAWN"
    touch(bid)
    return ok(public(bid))

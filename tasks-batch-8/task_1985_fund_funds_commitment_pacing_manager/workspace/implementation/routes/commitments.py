"""Commitment endpoints: execute (OCC), reduce, cancel, scoped lists."""

from flask import Blueprint, request

import db
from db import STORE, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_POSTURE_GATED,
    ERR_STALE_VERSION, ERR_SIZE_OUT_OF_BAND, ERR_VINTAGE_BAND_BREACH,
    ERR_BUFFER_BREACH, ERR_REDUCE_BELOW_PAID, ERR_INVALID_REQUEST,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from services import domain
from util import dec
from validate import body, req_positive_num

bp = Blueprint("commitments", __name__)


def get_program_or_404(pid):
    prog = STORE.programs.get(pid)
    if prog is None:
        raise_err(ERR_NOT_FOUND, "program id does not exist")
    return prog


def get_commitment_or_404(pid, cid):
    c = STORE.commitments.get(cid)
    if c is None or c["program_id"] != pid:
        raise_err(ERR_NOT_FOUND, "commitment id does not exist")
    return c


@bp.route("/fof/programs/<pid>/commitments", methods=["GET"])
def list_commitments(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    rows = [c for c in STORE.commitments.values() if c["program_id"] == pid]
    return list_response(rows, filters={
        "status": request.args.get("status"),
        "vehicle_id": request.args.get("vehicle_id"),
    })


@bp.route("/fof/programs/<pid>/commitments/<cid>", methods=["GET"])
def get_commitment(pid, cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    return ok(public(get_commitment_or_404(pid, cid)))


@bp.route("/fof/programs/<pid>/commitments/<cid>/execute", methods=["POST"])
def execute_commitment(pid, cid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    data = body()
    prog = get_program_or_404(pid)
    c = get_commitment_or_404(pid, cid)
    sized_amount = req_positive_num(data, "sized_amount")
    expected = data.get("expected_program_version")
    if expected is None:
        raise_err(ERR_INVALID_REQUEST, "expected_program_version is required")
    if expected != prog["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_program_version does not match the current version")
    if c["status"] != "PENDING_DOCS":
        raise_err(ERR_INVALID_STATE, "commitment is not PENDING_DOCS")
    if prog["status"] != "OPEN" or prog["posture"] != "NORMAL":
        raise_err(ERR_POSTURE_GATED, "program must be OPEN with posture NORMAL")
    # Sizing band against the originating proposal (secondary-purchase
    # commitments arrive EXECUTED and never pass through here).
    proposal = STORE.proposals.get(c["proposal_id"]) if c["proposal_id"] else None
    if proposal is not None:
        proposed = dec(proposal["proposed_amount"])
        sized = dec(sized_amount)
        if sized > proposed * dec("1.10") or sized < proposed * dec("0.90"):
            raise_err(ERR_SIZE_OUT_OF_BAND,
                      "sized_amount outside +/-10% of proposed_amount")
    # Vintage band against existing EXECUTED commitments.
    vehicle = STORE.vehicles.get(c["vehicle_id"])
    vy = vehicle["vintage_year"] if vehicle else None
    executed_years = []
    for other in STORE.commitments.values():
        if other["program_id"] == pid and other["status"] == "EXECUTED":
            ov = STORE.vehicles.get(other["vehicle_id"])
            if ov is not None:
                executed_years.append(ov["vintage_year"])
    if vy is not None and executed_years:
        span = max(max(executed_years), vy) - min(min(executed_years), vy)
        if span > prog["max_vintage_band_years"]:
            raise_err(ERR_VINTAGE_BAND_BREACH,
                      "vintage year outside the allowed band span")
    # Buffer: program-level unfunded after execution must leave projected
    # liquidity coverage at or above the buffer (cash unchanged by execution
    # itself, so the check is cash >= buffer).
    if dec(prog["unrestricted_cash"]) < dec(prog["liquidity_buffer_min"]):
        raise_err(ERR_BUFFER_BREACH,
                  "unrestricted_cash below liquidity_buffer_min")
    c["sized_amount"] = sized_amount
    domain.recompute_commitment_unfunded(c)
    c["status"] = "EXECUTED"
    c["executed_at"] = db.now_iso()
    touch(c)
    domain.program_mutated(prog)
    return ok(public(c))


@bp.route("/fof/programs/<pid>/commitments/<cid>/reduce", methods=["POST"])
def reduce_commitment(pid, cid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    data = body()
    prog = get_program_or_404(pid)
    c = get_commitment_or_404(pid, cid)
    reduce_to = req_positive_num(data, "reduce_to")
    if c["status"] != "EXECUTED":
        raise_err(ERR_INVALID_STATE, "commitment is not EXECUTED")
    paid = domain.paid_calls_total(cid)
    if dec(reduce_to) < paid:
        raise_err(ERR_REDUCE_BELOW_PAID,
                  "reduce_to is below already-paid capital calls")
    c["sized_amount"] = reduce_to
    domain.recompute_commitment_unfunded(c)
    c["status"] = "REDUCED"
    touch(c)
    domain.program_mutated(prog)
    return ok(public(c))


@bp.route("/fof/programs/<pid>/commitments/<cid>/cancel", methods=["POST"])
def cancel_commitment(pid, cid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    prog = get_program_or_404(pid)
    c = get_commitment_or_404(pid, cid)
    if c["status"] != "PENDING_DOCS":
        raise_err(ERR_INVALID_STATE, "commitment is not PENDING_DOCS")
    c["status"] = "CANCELLED"
    touch(c)
    domain.program_mutated(prog)
    return ok(public(c))


# ---------------------------------------------------------------------------
# Flat forms.
# ---------------------------------------------------------------------------

@bp.route("/fof/commitments/<cid>", methods=["GET"])
def get_commitment_flat(cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    c = STORE.commitments.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, "commitment id does not exist")
    return ok(public(c))


@bp.route("/fof/commitments/<cid>/calls", methods=["GET"])
def list_commitment_calls_flat(cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if STORE.commitments.get(cid) is None:
        raise_err(ERR_NOT_FOUND, "commitment id does not exist")
    rows = [c for c in STORE.calls.values() if c["commitment_id"] == cid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/commitments/<cid>/distributions", methods=["GET"])
def list_commitment_distributions_flat(cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if STORE.commitments.get(cid) is None:
        raise_err(ERR_NOT_FOUND, "commitment id does not exist")
    rows = [d for d in STORE.distributions.values() if d["commitment_id"] == cid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/commitments/<cid>/secondary-bids", methods=["GET"])
def list_commitment_bids(cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if STORE.commitments.get(cid) is None:
        raise_err(ERR_NOT_FOUND, "commitment id does not exist")
    rows = [b for b in STORE.secondary_bids.values()
            if b["linked_commitment_id"] == cid]
    return list_response(rows, filters={"status": request.args.get("status")})

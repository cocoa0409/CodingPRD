"""Distribution endpoints: record, receive, cancel."""

from flask import Blueprint, request

from db import STORE, new_entity, touch, public, iso
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_COMMITMENT_NOT_EXECUTED,
    ERR_POSTURE_GATED,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from services import domain
from validate import body, req_positive_num, req_enum, req_datetime

bp = Blueprint("distributions", __name__)

DISTRIBUTION_TYPES = ["RETURN_OF_CAPITAL", "GAIN", "INCOME"]


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


def get_distribution_or_404(did):
    d = STORE.distributions.get(did)
    if d is None:
        raise_err(ERR_NOT_FOUND, "distribution id does not exist")
    return d


@bp.route("/fof/programs/<pid>/commitments/<cid>/distributions", methods=["POST"])
def record_distribution(pid, cid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    prog = get_program_or_404(pid)
    get_commitment_or_404(pid, cid)
    if prog["posture"] == "FROZEN":
        raise_err(ERR_POSTURE_GATED, "program posture is FROZEN")
    data = body()
    amount = req_positive_num(data, "amount")
    dist_type = req_enum(data, "distribution_type", DISTRIBUTION_TYPES)
    received_at = req_datetime(data, "received_at")
    d = new_entity(STORE.distributions, {
        "commitment_id": cid,
        "program_id": pid,
        "amount": amount,
        "distribution_type": dist_type,
        "received_at": iso(received_at),
        "status": "PENDING",
    })
    return ok(public(d), status=201)


@bp.route("/fof/programs/<pid>/commitments/<cid>/distributions", methods=["GET"])
def list_distributions(pid, cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    get_commitment_or_404(pid, cid)
    rows = [d for d in STORE.distributions.values() if d["commitment_id"] == cid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/distributions/<did>", methods=["GET"])
def get_distribution(did):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return ok(public(get_distribution_or_404(did)))


@bp.route("/fof/distributions/<did>/receive", methods=["POST"])
def receive_distribution(did):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    d = get_distribution_or_404(did)
    if d["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "distribution is not PENDING")
    commitment = STORE.commitments.get(d["commitment_id"])
    prog = STORE.programs.get(d["program_id"])
    if commitment is None or commitment["status"] not in ("EXECUTED", "REDUCED"):
        raise_err(ERR_COMMITMENT_NOT_EXECUTED,
                  "commitment must be EXECUTED or REDUCED")
    d["status"] = "RECEIVED"
    touch(d)
    domain.append_ledger(prog, "DISTRIBUTION_RECEIPT", d["amount"],
                         ref_entity="Distribution", ref_id=d["id"])
    return ok(public(d))


@bp.route("/fof/distributions/<did>/cancel", methods=["POST"])
def cancel_distribution(did):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    d = get_distribution_or_404(did)
    if d["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "distribution is not PENDING")
    d["status"] = "CANCELLED"
    touch(d)
    return ok(public(d))

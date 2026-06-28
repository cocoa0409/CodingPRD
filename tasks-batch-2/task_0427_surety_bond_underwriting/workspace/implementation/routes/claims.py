"""Claim endpoints (PRD §3.6, §3.7): file, investigate, settle (PAY/DENY) with
the bond-loss recompute and program loss-alert cascade. ClaimsExaminer only for
writes; all roles may read."""

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_claim
from services.domain import (
    touch, recompute_bond_incurred_loss, program_cumulative_loss,
)
from helpers import (
    get_body, require_str, require_int, opt_int, require_enum,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("claims", __name__)

READ_ROLES = ("Underwriter", "SeniorUnderwriter", "ClaimsExaminer")
OUTCOMES = {"PAY", "DENY"}


@bp.route("/surety/claims", methods=["POST"])
@require_roles("ClaimsExaminer")
def file_claim():
    body = get_body()
    bond_id = require_str(body, "bond_id")
    bond = db.bonds.get(bond_id)
    if bond is None:
        raise errors.not_found("Bond not found")
    claimant_name = require_str(body, "claimant_name")
    demand_cents = require_int(body, "demand_cents")
    reserve_cents = require_int(body, "reserve_cents")

    ts = now_ts()
    cid = new_id()
    record = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "bond_id": bond_id,
        "claimant_name": claimant_name,
        "demand_cents": demand_cents,
        "reserve_cents": reserve_cents,
        "paid_loss_cents": None,
        "salvage_cents": 0,
        "status": "FILED",
    }
    db.claims[cid] = record
    # Filing folds the new reserve into the bond's incurred loss.
    recompute_bond_incurred_loss(bond)
    touch(bond)
    return success(serialize_claim(record), status=201)


@bp.route("/surety/claims/<cid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_claim(cid):
    record = db.claims.get(cid)
    if record is None:
        raise errors.not_found("Claim not found")
    return success(serialize_claim(record), status=200)


@bp.route("/surety/claims", methods=["GET"])
@require_roles(*READ_ROLES)
def list_claims():
    limit, offset = parse_pagination()
    items = list(db.claims.values())
    bond_id = request.args.get("bond_id")
    if bond_id is not None:
        items = [c for c in items if c["bond_id"] == bond_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_claim(c) for c in page], limit, offset, total)


@bp.route("/surety/claims/<cid>/investigate", methods=["POST"])
@require_roles("ClaimsExaminer")
def investigate_claim(cid):
    body = get_body()
    record = db.claims.get(cid)
    if record is None:
        raise errors.not_found("Claim not found")
    reserve_cents = require_int(body, "reserve_cents")
    # State: claim FILED and its bond ACTIVE (each else ERR_INVALID_STATE).
    if record["status"] != "FILED":
        raise errors.invalid_state("Claim is not FILED")
    bond = db.bonds.get(record["bond_id"])
    if bond is None or bond["status"] != "ACTIVE":
        raise errors.invalid_state("Bond is not ACTIVE")

    record["reserve_cents"] = reserve_cents
    record["status"] = "INVESTIGATING"
    touch(record)
    recompute_bond_incurred_loss(bond)
    touch(bond)
    return success(serialize_claim(record), status=200)


@bp.route("/surety/claims/<cid>/settle", methods=["POST"])
@require_roles("ClaimsExaminer")
def settle_claim(cid):
    body = get_body()
    record = db.claims.get(cid)
    if record is None:
        raise errors.not_found("Claim not found")
    outcome = require_enum(body, "outcome", OUTCOMES)
    if record["status"] != "INVESTIGATING":
        raise errors.invalid_state("Claim is not INVESTIGATING")
    bond = db.bonds.get(record["bond_id"])

    if outcome == "PAY":
        paid_loss_cents = require_int(body, "paid_loss_cents")
        salvage_cents = opt_int(body, "salvage_cents", 0)
        if paid_loss_cents > bond["penal_sum_cents"]:
            raise errors.ApiError(errors.ERR_LOSS_EXCEEDS_PENAL_SUM, 409,
                                  "Paid loss exceeds the bond penal sum")
        record["paid_loss_cents"] = paid_loss_cents
        record["salvage_cents"] = salvage_cents
        record["status"] = "PAID"
        touch(record)
        recompute_bond_incurred_loss(bond)
        touch(bond)
        # Loss cascade -> program loss-alert brake.
        program = db.programs.get(bond["program_id"])
        if program is not None and program["status"] == "OPEN":
            cumulative = program_cumulative_loss(program["id"])
            if cumulative >= program["loss_alert_threshold_cents"]:
                program["status"] = "SUSPENDED"
                touch(program)
    else:  # DENY
        record["status"] = "DENIED"
        touch(record)
        recompute_bond_incurred_loss(bond)
        touch(bond)

    return success(serialize_claim(record), status=200)

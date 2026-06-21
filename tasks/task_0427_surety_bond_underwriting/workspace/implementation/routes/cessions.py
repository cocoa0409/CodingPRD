"""Cession endpoints (PRD §3.5, §2.8): create (cede a bond's penal sum to a
treaty) and recapture (compensating action), with treaty-capacity/closed gates
and the bond/program exposure cascade."""

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_cession
from services.calculations import cession_amount
from services.domain import touch, bond_net_retained, recompute_bond_ceded
from helpers import (
    get_body, require_str,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("cessions", __name__)

ROLES = ("Underwriter", "SeniorUnderwriter")


@bp.route("/surety/cessions", methods=["POST"])
@require_roles(*ROLES)
def create_cession():
    body = get_body()
    bond_id = require_str(body, "bond_id")
    treaty_id = require_str(body, "treaty_id")
    # Existence validated left-to-right (PRD §2.11).
    bond = db.bonds.get(bond_id)
    if bond is None:
        raise errors.not_found("Bond not found")
    treaty = db.treaties.get(treaty_id)
    if treaty is None:
        raise errors.not_found("Treaty not found")

    # Treaty closed check.
    if treaty["status"] == "CLOSED":
        raise errors.ApiError(errors.ERR_TREATY_CLOSED, 409, "Treaty is CLOSED")

    ceded = cession_amount(bond["penal_sum_cents"], treaty["cession_pct_bps"])
    # Treaty capacity check.
    available = treaty["treaty_capacity_cents"] - treaty["ceded_committed_cents"]
    if ceded > available:
        raise errors.ApiError(errors.ERR_TREATY_CAPACITY_EXCEEDED, 409,
                              "Ceded amount exceeds treaty available capacity")

    ts = now_ts()
    cid = new_id()
    record = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "bond_id": bond_id,
        "treaty_id": treaty_id,
        "ceded_penal_sum_cents": ceded,
        "status": "ACTIVE",
    }
    db.cessions[cid] = record

    # Treaty committed rises; bond ceded rises & net_retained falls; program
    # exposure falls by the reduction in the bond's net_retained.
    treaty["ceded_committed_cents"] += ceded
    touch(treaty)
    program = db.programs.get(bond["program_id"])
    net_before = bond_net_retained(bond)
    recompute_bond_ceded(bond)
    net_after = bond_net_retained(bond)
    touch(bond)
    if program is not None:
        program["aggregate_committed_cents"] += (net_after - net_before)
        touch(program)

    return success(serialize_cession(record), status=201)


@bp.route("/surety/cessions/<cid>", methods=["GET"])
@require_roles(*ROLES)
def get_cession(cid):
    record = db.cessions.get(cid)
    if record is None:
        raise errors.not_found("Cession not found")
    return success(serialize_cession(record), status=200)


@bp.route("/surety/cessions", methods=["GET"])
@require_roles(*ROLES)
def list_cessions():
    limit, offset = parse_pagination()
    items = list(db.cessions.values())
    bond_id = request.args.get("bond_id")
    treaty_id = request.args.get("treaty_id")
    if bond_id is not None:
        items = [c for c in items if c["bond_id"] == bond_id]
    if treaty_id is not None:
        items = [c for c in items if c["treaty_id"] == treaty_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_cession(c) for c in page], limit, offset, total)


@bp.route("/surety/cessions/<cid>/recapture", methods=["POST"])
@require_roles(*ROLES)
def recapture_cession(cid):
    record = db.cessions.get(cid)
    if record is None:
        raise errors.not_found("Cession not found")
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Cession is not ACTIVE")
    bond = db.bonds.get(record["bond_id"])
    if bond is None or bond["status"] != "ACTIVE":
        raise errors.invalid_state("Bond is not ACTIVE")

    treaty = db.treaties.get(record["treaty_id"])
    if treaty is not None:
        treaty["ceded_committed_cents"] -= record["ceded_penal_sum_cents"]
        touch(treaty)

    record["status"] = "RECAPTURED"
    touch(record)

    # Bond ceded recomputed (rises in net_retained); program exposure increased.
    program = db.programs.get(bond["program_id"])
    net_before = bond_net_retained(bond)
    recompute_bond_ceded(bond)
    net_after = bond_net_retained(bond)
    touch(bond)
    if program is not None:
        program["aggregate_committed_cents"] += (net_after - net_before)
        touch(program)

    return success(serialize_cession(record), status=200)

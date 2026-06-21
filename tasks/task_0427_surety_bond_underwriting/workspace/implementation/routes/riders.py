"""Rider endpoints (PRD §3.5): create (DRAFT), apply (with single/aggregate-limit
and open-claim gates, premium computation, exposure adjustment), reject."""

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_rider
from services.calculations import elapsed_months, rider_additional_premium
from services.domain import touch, bond_net_retained
from helpers import (
    get_body, require_str, opt_int, require_enum,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("riders", __name__)

ROLES = ("Underwriter", "SeniorUnderwriter")
RIDER_TYPES = {"INCREASE", "DECREASE", "NAME_CHANGE"}


def _has_open_claim(bond_id):
    for c in db.claims.values():
        if c["bond_id"] == bond_id and c["status"] in ("FILED", "INVESTIGATING"):
            return True
    return False


@bp.route("/surety/riders", methods=["POST"])
@require_roles(*ROLES)
def create_rider():
    body = get_body()
    bond_id = require_str(body, "bond_id")
    if db.bonds.get(bond_id) is None:
        raise errors.not_found("Bond not found")
    rider_type = require_enum(body, "rider_type", RIDER_TYPES)
    penal_sum_delta_cents = opt_int(body, "penal_sum_delta_cents", 0)

    ts = now_ts()
    rid = new_id()
    record = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "bond_id": bond_id,
        "rider_type": rider_type,
        "penal_sum_delta_cents": penal_sum_delta_cents,
        "additional_premium_cents": 0,
        "status": "DRAFT",
    }
    db.riders[rid] = record
    return success(serialize_rider(record), status=201)


@bp.route("/surety/riders/<rid>", methods=["GET"])
@require_roles(*ROLES)
def get_rider(rid):
    record = db.riders.get(rid)
    if record is None:
        raise errors.not_found("Rider not found")
    return success(serialize_rider(record), status=200)


@bp.route("/surety/riders", methods=["GET"])
@require_roles(*ROLES)
def list_riders():
    limit, offset = parse_pagination()
    items = list(db.riders.values())
    bond_id = request.args.get("bond_id")
    if bond_id is not None:
        items = [r for r in items if r["bond_id"] == bond_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_rider(r) for r in page], limit, offset, total)


@bp.route("/surety/riders/<rid>/apply", methods=["POST"])
@require_roles(*ROLES)
def apply_rider(rid):
    record = db.riders.get(rid)
    if record is None:
        raise errors.not_found("Rider not found")
    if record["status"] != "DRAFT":
        raise errors.invalid_state("Rider is not DRAFT")
    bond = db.bonds.get(record["bond_id"])
    if bond is None or bond["status"] != "ACTIVE":
        raise errors.invalid_state("Bond is not ACTIVE")
    if _has_open_claim(bond["id"]):
        raise errors.ApiError(errors.ERR_OPEN_CLAIM_EXISTS, 409,
                              "Bond has an open claim blocking the rider")

    program = db.programs.get(bond["program_id"])
    delta = record["penal_sum_delta_cents"]

    if record["rider_type"] == "INCREASE":
        # Single-limit: resulting penal sum must not exceed single_limit.
        if bond["penal_sum_cents"] + delta > program["single_limit_cents"]:
            raise errors.ApiError(errors.ERR_SINGLE_LIMIT_EXCEEDED, 409,
                                  "Resulting penal sum exceeds single limit")
        # Aggregate: the increase amount must not exceed aggregate_available.
        available = program["aggregate_limit_cents"] - program["aggregate_committed_cents"]
        if delta > available:
            raise errors.ApiError(errors.ERR_AGGREGATE_LIMIT_EXCEEDED, 409,
                                  "Increase amount exceeds aggregate available")
        elapsed = elapsed_months(bond["created_at"], bond["term_months"])
        remaining = bond["term_months"] - elapsed
        additional = rider_additional_premium(delta, bond["premium_rate_bps"], remaining)
        record["additional_premium_cents"] = additional
    else:
        # DECREASE / NAME_CHANGE -> no additional premium.
        record["additional_premium_cents"] = 0

    # Adjust bond penal sum & recompute net_retained; adjust program exposure by
    # the change in net_retained.
    net_before = bond_net_retained(bond)
    bond["penal_sum_cents"] += delta
    net_after = bond_net_retained(bond)
    touch(bond)
    if program is not None:
        program["aggregate_committed_cents"] += (net_after - net_before)
        touch(program)

    record["status"] = "APPLIED"
    touch(record)
    return success(serialize_rider(record), status=200)


@bp.route("/surety/riders/<rid>/reject", methods=["POST"])
@require_roles(*ROLES)
def reject_rider(rid):
    record = db.riders.get(rid)
    if record is None:
        raise errors.not_found("Rider not found")
    if record["status"] != "DRAFT":
        raise errors.invalid_state("Rider is not DRAFT")
    record["status"] = "REJECTED"
    touch(record)
    return success(serialize_rider(record), status=200)

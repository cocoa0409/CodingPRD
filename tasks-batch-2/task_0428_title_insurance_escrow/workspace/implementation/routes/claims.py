"""Claim endpoints (PRD §3.9). File (FNOL) under an issued policy / get / list /
transition (INVESTIGATING computes reserve; CURATIVE<->INVESTIGATING loop;
DENIED releases reserve; PAID requires a RESOLVED CurativeAction + settled_loss_cents
and computes the capped payout).
"""

from flask import Blueprint, request, g

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_claim
from services.domain import touch, require_agency_owns_order
from services.calculations import claim_reserve, claim_payout
from helpers import (
    get_body, require_enum, require_int_min,
    parse_pagination, paginate, sort_by_created,
)
from routes.policies import _get_policy_or_404

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"UNDISCLOSED_LIEN", "BOUNDARY_DISPUTE", "FORGERY", "ACCESS_DEFECT"}
CLAIM_STATUSES = {"FNOL", "INVESTIGATING", "CURATIVE", "PAID", "DENIED"}


def _get_claim_or_404(cid):
    c = db.claims.get(cid)
    if c is None:
        raise errors.not_found("Claim not found")
    return c


def _agency_guard_for_policy(policy):
    if g.user_role == "Agency":
        order = db.orders.get(policy["order_id"])
        if order is not None:
            require_agency_owns_order(order)


@bp.route("/title/policies/<pid>/claims", methods=["POST"])
@require_roles("Underwriter")
def create_claim(pid):
    policy = _get_policy_or_404(pid)
    body = get_body()
    claim_type = require_enum(body, "claim_type", CLAIM_TYPES)
    estimated_loss_cents = require_int_min(body, "estimated_loss_cents", 0)

    ts = now_ts()
    cid = new_id()
    record = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "policy_id": policy["id"],
        "claim_type": claim_type,
        "estimated_loss_cents": estimated_loss_cents,
        "reserve_cents": 0,
        "settled_loss_cents": 0,
        "paid_cents": 0,
        "status": "FNOL",
    }
    db.claims[cid] = record
    return success(serialize_claim(record), status=201)


@bp.route("/title/policies/<pid>/claims", methods=["GET"])
@require_roles("Underwriter", "Agency")
def list_claims(pid):
    policy = _get_policy_or_404(pid)
    _agency_guard_for_policy(policy)
    limit, offset = parse_pagination()
    items = [c for c in db.claims.values() if c["policy_id"] == policy["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_claim(c) for c in page], limit, offset, total)


@bp.route("/title/claims/<cid>", methods=["GET"])
@require_roles("Underwriter", "Agency")
def get_claim(cid):
    c = _get_claim_or_404(cid)
    if g.user_role == "Agency":
        policy = db.policies.get(c["policy_id"])
        if policy is not None:
            _agency_guard_for_policy(policy)
    return success(serialize_claim(c), status=200)


def _has_resolved_curative(subject_type, subject_id):
    for c in db.curative_actions.values():
        if (c["subject_type"] == subject_type and c["subject_id"] == subject_id
                and c["status"] == "RESOLVED"):
            return True
    return False


@bp.route("/title/claims/<cid>/transitions", methods=["POST"])
@require_roles("Underwriter")
def transition_claim(cid):
    body = get_body()
    c = _get_claim_or_404(cid)
    to_status = require_enum(body, "to_status", CLAIM_STATUSES)
    cur = c["status"]

    if to_status == "INVESTIGATING":
        # FNOL -> INVESTIGATING, or CURATIVE -> INVESTIGATING (loop back).
        if cur not in ("FNOL", "CURATIVE"):
            raise errors.invalid_state("Claim is not FNOL or CURATIVE")
        if cur == "FNOL":
            # Cross-entity (priority 7): parent policy must be ISSUED.
            policy = db.policies.get(c["policy_id"])
            if policy is None or policy["status"] != "ISSUED":
                raise errors.ApiError(errors.ERR_POLICY_NOT_ISSUED, 409,
                                      "Parent policy is not ISSUED")
            # Provisional reserve from the adjuster estimate, capped at coverage.
            c["reserve_cents"] = claim_reserve(
                c["estimated_loss_cents"], policy["coverage_amount_cents"])
        c["status"] = "INVESTIGATING"
        touch(c)
    elif to_status == "CURATIVE":
        if cur != "INVESTIGATING":
            raise errors.invalid_state("Claim is not INVESTIGATING")
        c["status"] = "CURATIVE"
        touch(c)
    elif to_status == "DENIED":
        if cur != "INVESTIGATING":
            raise errors.invalid_state("Claim is not INVESTIGATING")
        c["reserve_cents"] = 0
        c["status"] = "DENIED"
        touch(c)
    elif to_status == "PAID":
        if cur != "CURATIVE":
            raise errors.invalid_state("Claim is not CURATIVE")
        # Body well-formedness (priority 4): settled_loss_cents required.
        settled_loss_cents = require_int_min(body, "settled_loss_cents", 0)
        # Safety (priority 9): a RESOLVED CurativeAction on this claim is required.
        if not _has_resolved_curative("CLAIM", c["id"]):
            raise errors.ApiError(errors.ERR_NO_RESOLVED_CURATIVE, 409,
                                  "No RESOLVED CurativeAction on this claim")
        policy = db.policies.get(c["policy_id"])
        coverage = policy["coverage_amount_cents"] if policy else 0
        c["settled_loss_cents"] = settled_loss_cents
        c["paid_cents"] = claim_payout(settled_loss_cents, coverage)
        c["reserve_cents"] = 0
        c["status"] = "PAID"
        touch(c)
    else:
        raise errors.invalid_state("Unsupported claim transition")

    return success(serialize_claim(c), status=200)

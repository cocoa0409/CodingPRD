"""Policy endpoints (PRD §3.6). Create (PENDING) / list / get / transition.

ISSUE (PENDING->ISSUED) checks three commitment preconditions, computes and freezes
gross_premium_cents (owner_premium / lender_premium), and atomically creates a
PENDING PremiumRemittance carrying the pinned-order split snapshot. VOID fires
Cascade A link 3 (reverse remittance, remove endorsements).
"""

from flask import Blueprint, request, g

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_policy
from services.domain import touch, require_agency_owns_order, cascade_a_void_policy
from services.calculations import owner_premium, lender_premium, premium_split
from helpers import (
    get_body, require_str, require_enum, require_int_min, opt_bool,
    parse_pagination, paginate, sort_by_created,
)
from routes.orders import get_order_or_404

bp = Blueprint("policies", __name__)

POLICY_TYPES = {"OWNER", "LENDER"}
POLICY_STATUSES = {"PENDING", "ISSUED", "VOID"}
READ_ROLES = ("Underwriter", "TitleOfficer", "Agency")


def _get_policy_or_404(pid):
    p = db.policies.get(pid)
    if p is None:
        raise errors.not_found("Policy not found")
    return p


@bp.route("/title/orders/<oid>/policies", methods=["POST"])
@require_roles("Underwriter")
def create_policy(oid):
    order = get_order_or_404(oid)
    body = get_body()
    commitment_id = require_str(body, "commitment_id")
    policy_type = require_enum(body, "policy_type", POLICY_TYPES)
    coverage_amount_cents = require_int_min(body, "coverage_amount_cents", 1)
    is_reissue = opt_bool(body, "is_reissue", False)
    co_issued_with_owner = opt_bool(body, "co_issued_with_owner", False)

    # Existence (priority 3): the commitment must exist and belong to this order.
    commitment = db.commitments.get(commitment_id)
    if commitment is None or commitment["order_id"] != order["id"]:
        raise errors.not_found("Commitment not found on this order")

    ts = now_ts()
    pid = new_id()
    record = {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "order_id": order["id"],
        "commitment_id": commitment_id,
        "policy_type": policy_type,
        "coverage_amount_cents": coverage_amount_cents,
        "is_reissue": is_reissue,
        "co_issued_with_owner": co_issued_with_owner,
        "gross_premium_cents": 0,
        "status": "PENDING",
    }
    db.policies[pid] = record
    return success(serialize_policy(record), status=201)


@bp.route("/title/policies", methods=["GET"])
@require_roles(*READ_ROLES)
def list_policies():
    limit, offset = parse_pagination()
    items = list(db.policies.values())
    if g.user_role == "Agency":
        owned = {o["id"] for o in db.orders.values() if o["agency_id"] == g.user_id}
        items = [p for p in items if p["order_id"] in owned]
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [p for p in items if p["order_id"] == order_id]
    commitment_id = request.args.get("commitment_id")
    if commitment_id is not None:
        items = [p for p in items if p["commitment_id"] == commitment_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_policy(p) for p in page], limit, offset, total)


@bp.route("/title/policies/<pid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_policy(pid):
    p = _get_policy_or_404(pid)
    if g.user_role == "Agency":
        order = db.orders.get(p["order_id"])
        if order is not None:
            require_agency_owns_order(order)
    return success(serialize_policy(p), status=200)


def _compute_premium(policy):
    if policy["policy_type"] == "OWNER":
        return owner_premium(policy["coverage_amount_cents"], policy["is_reissue"])
    return lender_premium(policy["coverage_amount_cents"], policy["co_issued_with_owner"])


def _has_open_claim(policy_id):
    for c in db.claims.values():
        if c["policy_id"] == policy_id and c["status"] in ("INVESTIGATING", "CURATIVE"):
            return True
    return False


@bp.route("/title/policies/<pid>/transitions", methods=["POST"])
@require_roles("Underwriter")
def transition_policy(pid):
    body = get_body()
    p = _get_policy_or_404(pid)
    to_status = require_enum(body, "to_status", POLICY_STATUSES)
    cur = p["status"]

    if to_status == "ISSUED":
        if cur != "PENDING":
            raise errors.invalid_state("Policy is not PENDING")
        commitment = db.commitments.get(p["commitment_id"])
        # Cross-entity referential (priority 7): commitment must be ISSUED.
        if commitment is None or commitment["status"] != "ISSUED":
            raise errors.ApiError(errors.ERR_COMMITMENT_NOT_ISSUED, 409,
                                  "Policy's commitment is not ISSUED")
        # Safety (priority 9): the commitment must have no open exceptions.
        from services.domain import commitment_open_exception_count
        if commitment_open_exception_count(commitment["id"]) != 0:
            raise errors.ApiError(errors.ERR_EXCEPTIONS_OPEN, 409,
                                  "Commitment has open exceptions")
        # Fiscal (priority 10): coverage must not exceed commitment insured amount.
        if p["coverage_amount_cents"] > commitment["insured_amount_cents"]:
            raise errors.ApiError(errors.ERR_COVERAGE_EXCEEDS_COMMITMENT, 409,
                                  "Coverage exceeds commitment insured amount")
        # Compute and freeze premium.
        p["gross_premium_cents"] = _compute_premium(p)
        p["status"] = "ISSUED"
        touch(p)
        # Atomically create the PENDING PremiumRemittance with the split snapshot.
        _create_remittance(p)
    elif to_status == "VOID":
        if cur != "ISSUED":
            raise errors.invalid_state("Policy is not ISSUED")
        # A direct void is blocked while a claim is INVESTIGATING or CURATIVE.
        if _has_open_claim(p["id"]):
            raise errors.ApiError(errors.ERR_POLICY_HAS_OPEN_CLAIM, 409,
                                  "Policy has an open claim (INVESTIGATING/CURATIVE)")
        p["status"] = "VOID"
        touch(p)
        # Cascade A link 3.
        cascade_a_void_policy(p)
    else:
        raise errors.invalid_state("Unsupported policy transition")

    return success(serialize_policy(p), status=200)


def _create_remittance(policy):
    """Create the PENDING PremiumRemittance snapshot (PRD §3.8). Split uses the
    owning Agency's remit_split_pct, rounded agency-share-first."""
    order = db.orders.get(policy["order_id"])
    agency = db.agencies.get(order["agency_id"]) if order else None
    remit_split_pct = agency["remit_split_pct"] if agency else 0
    gross = policy["gross_premium_cents"]
    agency_retained, underwriter_remit = premium_split(gross, remit_split_pct)
    ts = now_ts()
    rid = new_id()
    record = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "policy_id": policy["id"],
        "gross_premium_cents": gross,
        "agency_retained_cents": agency_retained,
        "underwriter_remit_cents": underwriter_remit,
        "status": "PENDING",
    }
    db.remittances[rid] = record
    return record

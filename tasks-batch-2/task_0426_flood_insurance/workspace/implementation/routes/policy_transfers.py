"""PolicyTransfer endpoints: assume an ACTIVE policy onto a new owner (PRD §3.7).

A transfer is an assumption: no cash refund; the unearned premium rides with the
policy as a credit balance. The source policy moves ACTIVE -> TRANSFERRED.
"""

from flask import Blueprint, g, request

import errors
from db import db, new_id, now_ts
from clock import clock, format_iso8601_ms, parse_iso8601, floor_days_between
from middleware import require_roles
from response import success, list_success
from serializers import serialize_policy_transfer
from helpers import (
    get_body, require_str, require_int, parse_pagination, paginate, sort_by_created,
)
from services.calculations import prorate_earned, TERM_DAYS

bp = Blueprint("policy_transfers", __name__)


@bp.route("/policy-transfers", methods=["POST"])
@require_roles("Underwriter")
def create_transfer():
    body = get_body()
    from_policy_id = require_str(body, "from_policy_id")
    new_owner_id = require_str(body, "new_owner_id")
    expected = require_int(body, "expected_policy_version")

    # Existence (priority 3): from_policy_id FK must resolve.
    policy = db.policies.get(from_policy_id)
    if policy is None:
        raise errors.not_found("Policy not found")

    # State (priority 5): source policy must be ACTIVE.
    if policy["status"] != "ACTIVE":
        raise errors.invalid_state("Policy must be ACTIVE to transfer")

    # OCC (priority 16): expected_policy_version must match live version.
    if expected != policy["version"]:
        raise errors.ApiError(errors.ERR_STALE_POLICY_VERSION, 412,
                              "expected_policy_version does not match live version")

    now = clock.now()
    effective = parse_iso8601(policy["effective_date"])
    days_elapsed = floor_days_between(effective, now)
    if days_elapsed < 0:
        days_elapsed = 0
    if days_elapsed > TERM_DAYS:
        days_elapsed = TERM_DAYS
    earned, unearned = prorate_earned(policy["quoted_premium"], days_elapsed)

    ts = now_ts()
    tid = new_id()
    transfer = {
        "id": tid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "from_policy_id": from_policy_id,
        "new_owner_id": new_owner_id,
        "superseded_policy_id": from_policy_id,
        "credited_amount": unearned,
        "effective_at": format_iso8601_ms(now),
    }
    db.policy_transfers[tid] = transfer

    # Source policy side effects.
    policy["earned_premium"] = earned
    policy["premium_credit_balance"] += unearned
    policy["holder_id"] = new_owner_id
    policy["status"] = "TRANSFERRED"
    policy["version"] += 1
    policy["updated_at"] = now_ts()

    prop = db.properties.get(policy["property_id"])
    if prop is not None:
        prop["owner_id"] = new_owner_id
        prop["version"] += 1
        prop["updated_at"] = now_ts()

    return success(serialize_policy_transfer(transfer), status=201)


@bp.route("/policy-transfers/<tid>", methods=["GET"])
@require_roles("Underwriter", "FemaAdmin", "PolicyHolder")
def get_transfer(tid):
    record = db.policy_transfers.get(tid)
    if record is None:
        raise errors.not_found("Policy transfer not found")
    if g.user_role == "PolicyHolder":
        policy = db.policies.get(record["from_policy_id"])
        # Holder-scoped: only the new owner or the (now reassigned) holder may read.
        if record["new_owner_id"] != g.user_id and not (
            policy is not None and policy["holder_id"] == g.user_id
        ):
            raise errors.not_resource_owner("Not a party to this transfer")
    return success(serialize_policy_transfer(record), status=200)


@bp.route("/policy-transfers", methods=["GET"])
@require_roles("Underwriter", "FemaAdmin")
def list_transfers():
    limit, offset = parse_pagination()
    from_policy_id = request.args.get("from_policy_id")
    superseded_policy_id = request.args.get("superseded_policy_id")

    items = list(db.policy_transfers.values())
    if from_policy_id is not None:
        items = [t for t in items if t["from_policy_id"] == from_policy_id]
    if superseded_policy_id is not None:
        items = [t for t in items if t["superseded_policy_id"] == superseded_policy_id]

    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_policy_transfer(t) for t in page], limit, offset, total)

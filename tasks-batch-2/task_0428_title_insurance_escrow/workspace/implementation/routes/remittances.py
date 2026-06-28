"""PremiumRemittance endpoints (PRD §3.8). List under a policy / get / transition
(REMIT requires the parent policy ISSUED). Remittances are created as a side effect
of policy issuance, not directly.
"""

from flask import Blueprint, request, g

import errors
from db import db
from middleware import require_roles
from response import success, list_success
from serializers import serialize_remittance
from services.domain import touch, require_agency_owns_order
from helpers import get_body, require_enum, parse_pagination, paginate, sort_by_created
from routes.policies import _get_policy_or_404

bp = Blueprint("remittances", __name__)

REMITTANCE_STATUSES = {"PENDING", "REMITTED", "REVERSED"}


def _get_remittance_or_404(rid):
    r = db.remittances.get(rid)
    if r is None:
        raise errors.not_found("Remittance not found")
    return r


def _agency_guard_for_policy(policy):
    if g.user_role == "Agency":
        order = db.orders.get(policy["order_id"])
        if order is not None:
            require_agency_owns_order(order)


@bp.route("/title/policies/<pid>/remittances", methods=["GET"])
@require_roles("Underwriter", "Agency")
def list_remittances(pid):
    policy = _get_policy_or_404(pid)
    _agency_guard_for_policy(policy)
    limit, offset = parse_pagination()
    items = [r for r in db.remittances.values() if r["policy_id"] == policy["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_remittance(r) for r in page], limit, offset, total)


@bp.route("/title/remittances/<rid>", methods=["GET"])
@require_roles("Underwriter", "Agency")
def get_remittance(rid):
    r = _get_remittance_or_404(rid)
    if g.user_role == "Agency":
        policy = db.policies.get(r["policy_id"])
        if policy is not None:
            _agency_guard_for_policy(policy)
    return success(serialize_remittance(r), status=200)


@bp.route("/title/remittances/<rid>/transitions", methods=["POST"])
@require_roles("Underwriter")
def transition_remittance(rid):
    body = get_body()
    r = _get_remittance_or_404(rid)
    to_status = require_enum(body, "to_status", REMITTANCE_STATUSES)
    cur = r["status"]

    if to_status == "REMITTED":
        if cur != "PENDING":
            raise errors.invalid_state("Remittance is not PENDING")
        # Cross-entity (priority 7): parent policy must be ISSUED.
        policy = db.policies.get(r["policy_id"])
        if policy is None or policy["status"] != "ISSUED":
            raise errors.ApiError(errors.ERR_POLICY_NOT_ISSUED, 409,
                                  "Parent policy is not ISSUED")
        r["status"] = "REMITTED"
        touch(r)
    else:
        # REVERSED is only reachable via Cascade A (system); not client-driven.
        raise errors.invalid_state("Unsupported remittance transition")

    return success(serialize_remittance(r), status=200)

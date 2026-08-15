"""Renewal endpoints (PRD 3.9): RENEW mints a successor application;
NON_RENEW moves the expired policy to NON_RENEWED."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_INVALID_DATE_RANGE, ERR_STALE_VERSION,
    ERR_POLICY_NOT_RENEWABLE,
)
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_policy
from routes.policies import build_policy_record
from serializers import renewal_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_enum, require_int,
    require_datetime, parse_pagination, paginate, sort_created, dt,
)

bp = Blueprint("renewals", __name__)

LIST_ROLES = ("PlatformAdmin", "Underwriter", "ClaimsApprover")

CREATE_FIELDS = {
    "decision", "effective_date", "expiration_date", "expected_prior_policy_version",
}


@bp.route("/carriers/<carrierId>/policies/<policyId>/renewals", methods=["POST"])
@require_roles("Underwriter")
def create_renewal(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    prior = resolve_policy(carrier["id"], policyId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    decision = require_enum(body, "decision", {"RENEW", "NON_RENEW"})
    effective_date = require_datetime(body, "effective_date")
    expiration_date = require_datetime(body, "expiration_date")
    expected_version = require_int(body, "expected_prior_policy_version", minimum=0)

    # OCC (pipeline priority 3.5): ahead of every business rule.
    if expected_version != prior["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_prior_policy_version does not match the prior policy's version")

    if prior["lifecycle_state"] != "EXPIRED":
        raise_err(ERR_POLICY_NOT_RENEWABLE,
                  "Renewal requires the prior policy to be EXPIRED")

    if dt(expiration_date) <= dt(effective_date):
        raise_err(ERR_INVALID_DATE_RANGE,
                  "expiration_date must fall after effective_date")

    now = carrier["current_utc"]
    gap_days = core.continuity_gap_days(prior, dt(effective_date))
    carryover = core.carryover_credit_for(prior, dt(effective_date))

    new_policy = None
    if decision == "RENEW":
        new_policy = build_policy_record(
            carrier,
            grower_id=prior["grower_id"],
            policy_kind=prior["policy_kind"],
            effective_date=effective_date,
            expiration_date=expiration_date,
            prior_policy_id=prior["id"],
        )
        db.policies[new_policy["id"]] = new_policy

        # Continuous-coverage marker (PRD 3.1/3.9): earliest un-broken start.
        grower = db.growers.get(prior["grower_id"])
        if grower is not None:
            if gap_days <= core.MAX_CONTINUITY_GAP_DAYS:
                if grower["continuous_coverage_since"] is None:
                    grower["continuous_coverage_since"] = prior["effective_date"]
            else:
                grower["continuous_coverage_since"] = effective_date
            db.touch(grower, now)
    else:
        prior["lifecycle_state"] = "NON_RENEWED"

    # Either decision advances the prior policy's version (the OCC target).
    db.touch(prior, now)

    renewal = db.stamp_new({
        "policy_id": new_policy["id"] if new_policy is not None else None,
        "prior_policy_id": prior["id"],
        "continuity_gap_days": gap_days,
        "carryover_credit_cents": carryover,
        "decision": decision,
        "decided_at": now,
    }, now)
    db.renewals[renewal["id"]] = renewal
    return success_object(renewal_view(renewal), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/renewals", methods=["GET"])
@require_roles(*LIST_ROLES)
def list_renewals(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    # Renewals naming this policy either as the new policy or as the prior.
    items = [
        r for r in db.renewals.values()
        if r["policy_id"] == policy["id"] or r["prior_policy_id"] == policy["id"]
    ]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([renewal_view(r) for r in page], limit, offset, total)

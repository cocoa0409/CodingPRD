"""Policy endpoints (PRD 3.4, 3.9): application, bind, cancel, reads."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_DATE_RANGE, ERR_NOT_FOUND,
    ERR_POLICY_NOT_IN_APPLICATION, ERR_NO_COVERAGE_UNITS,
    ERR_NO_ACTIVE_RATE_TABLE, ERR_GROWER_NOT_ACTIVE,
    ERR_POLICY_NOT_CANCELLABLE, ERR_OPEN_CLAIMS_BLOCK_CANCEL,
)
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_policy
from serializers import policy_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_string, require_enum,
    require_datetime, parse_pagination, paginate, sort_created, query_arg,
    dt, fmt_dt,
)

bp = Blueprint("policies", __name__)

ALL_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover")
LIST_ROLES = ("PlatformAdmin", "Underwriter", "ClaimsApprover")

CREATE_FIELDS = {
    "grower_id", "policy_kind", "effective_date", "expiration_date", "prior_policy_id",
}


def build_policy_record(carrier: dict, *, grower_id: str, policy_kind: str,
                        effective_date: str, expiration_date: str,
                        prior_policy_id) -> dict:
    """Shared application construction for create and renewal (PRD 3.4)."""
    grower = db.growers[grower_id]
    eff_dt = dt(effective_date)
    exp_dt = dt(expiration_date)
    if policy_kind == "CROP_HAIL":
        acreage_deadline = fmt_dt(eff_dt + timedelta(days=21))
        harvest_deadline = fmt_dt(exp_dt - timedelta(days=14))
        head_deadline = None
    else:
        acreage_deadline = None
        harvest_deadline = None
        head_deadline = fmt_dt(eff_dt + timedelta(days=10))

    carryover = 0
    if prior_policy_id is not None:
        prior = db.policies.get(prior_policy_id)
        if prior is not None:
            carryover = core.carryover_credit_for(prior, eff_dt)

    carrier["_policy_seq"] = carrier.get("_policy_seq", 0) + 1
    policy_number = f"POL-{carrier['carrier_code']}-{carrier['_policy_seq']}"

    return db.stamp_new({
        "carrier_id": carrier["id"],
        "grower_id": grower_id,
        "policy_kind": policy_kind,
        "policy_number": policy_number,
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "acreage_report_deadline": acreage_deadline,
        "harvest_report_deadline": harvest_deadline,
        "head_report_deadline": head_deadline,
        "premium_cents": 0,
        "premium_paid_cents": 0,
        "premium_reserve_cents": 0,
        "continuous_coverage_carryover_credit_cents": carryover,
        "high_risk_surcharge_pct": core.surcharge_pct_for(grower),
        "lifecycle_state": "APPLICATION",
        "billing_state": "UNBILLED",
        "prior_policy_id": prior_policy_id,
        "dual_coverage_link_id": None,
        "version_note": core.VERSION_NOTE,
        "_bound_at": None,
    }, carrier["current_utc"])


@bp.route("/carriers/<carrierId>/policies", methods=["POST"])
@require_roles("Underwriter")
def create_policy(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    grower_id = require_string(body, "grower_id")
    policy_kind = require_enum(body, "policy_kind", {"CROP_HAIL", "LIVESTOCK_MORTALITY"})
    effective_date = require_datetime(body, "effective_date")
    expiration_date = require_datetime(body, "expiration_date")
    if dt(expiration_date) <= dt(effective_date):
        raise_err(ERR_INVALID_DATE_RANGE,
                  "expiration_date must fall after effective_date")
    prior_policy_id = body.get("prior_policy_id")

    # Body references: grower must exist under this carrier.
    grower = db.growers.get(grower_id)
    if not isinstance(grower_id, str) or grower is None or grower["carrier_id"] != carrier["id"]:
        raise_err(ERR_NOT_FOUND, f"Grower not found: {grower_id}")

    if prior_policy_id is not None:
        if not isinstance(prior_policy_id, str) or prior_policy_id not in db.policies:
            raise_err(ERR_NOT_FOUND, f"Policy not found: {prior_policy_id}")
        prior = db.policies[prior_policy_id]
        if prior["grower_id"] != grower_id:
            raise_err(ERR_INVALID_REQUEST,
                      "prior_policy_id must reference a policy of the same grower")

    policy = build_policy_record(
        carrier,
        grower_id=grower_id,
        policy_kind=policy_kind,
        effective_date=effective_date,
        expiration_date=expiration_date,
        prior_policy_id=prior_policy_id,
    )
    db.policies[policy["id"]] = policy
    return success_object(policy_view(policy), 201)


@bp.route("/carriers/<carrierId>/policies", methods=["GET"])
@require_roles(*LIST_ROLES)
def list_policies(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    items = [p for p in db.policies.values() if p["carrier_id"] == carrier["id"]]
    grower_id = query_arg("grower_id")
    lifecycle_state = query_arg("lifecycle_state")
    billing_state = query_arg("billing_state")
    if grower_id is not None:
        items = [p for p in items if p["grower_id"] == grower_id]
    if lifecycle_state is not None:
        items = [p for p in items if p["lifecycle_state"] == lifecycle_state]
    if billing_state is not None:
        items = [p for p in items if p["billing_state"] == billing_state]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([policy_view(p) for p in page], limit, offset, total)


@bp.route("/carriers/<carrierId>/policies/<policyId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_policy(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    return success_object(policy_view(policy))


@bp.route("/carriers/<carrierId>/policies/<policyId>/bind", methods=["POST"])
@require_roles("Underwriter")
def bind_policy(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    body = get_json_body()
    reject_unknown_fields(body, set())

    # Bind checks run in the PRD's fixed order (PRD 3.4).
    if policy["lifecycle_state"] != "APPLICATION":
        raise_err(ERR_POLICY_NOT_IN_APPLICATION,
                  "bind requires lifecycle_state APPLICATION")

    units = core.units_of_policy(policy["id"])
    if not units:
        raise_err(ERR_NO_COVERAGE_UNITS,
                  "bind requires at least one CoverageUnit")

    bind_clock = dt(carrier["current_utc"])
    for unit in units:
        row, premium = core.rate_unit(unit, carrier["id"], bind_clock)
        if row is None:
            raise_err(
                ERR_NO_ACTIVE_RATE_TABLE,
                "No PUBLISHED RateTable matches the CoverageUnit at bind clock time",
            )

    grower = db.growers.get(policy["grower_id"])
    if grower is None or grower["status"] != "ACTIVE":
        raise_err(ERR_GROWER_NOT_ACTIVE, "Grower.status != ACTIVE at bind time")

    if policy["prior_policy_id"] is not None:
        prior = db.policies.get(policy["prior_policy_id"])
        if prior is None or prior["grower_id"] != policy["grower_id"]:
            raise_err(ERR_INVALID_REQUEST,
                      "prior policy must exist and belong to the same grower")

    # Freeze per-unit premiums against the binding clock time.
    now = carrier["current_utc"]
    for unit in units:
        row, premium = core.rate_unit(unit, carrier["id"], bind_clock)
        if unit["premium_cents"] != premium or unit.get("_rate_table_id") != row["id"]:
            unit["premium_cents"] = premium
            unit["_rate_table_id"] = row["id"]
            db.touch(unit, now)

    # Surcharge tier reads the grower's current claim count at bind.
    policy["high_risk_surcharge_pct"] = core.surcharge_pct_for(grower)
    policy["premium_cents"] = core.aggregate_policy_premium(policy)
    policy["lifecycle_state"] = "BOUND"
    policy["billing_state"] = "BILLED"
    policy["premium_reserve_cents"] = policy["premium_cents"] * 3 // 5
    policy["_bound_at"] = now
    db.touch(policy, now)
    return success_object(policy_view(policy))


@bp.route("/carriers/<carrierId>/policies/<policyId>/cancel", methods=["POST"])
@require_roles("Underwriter")
def cancel_policy(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    body = get_json_body()
    reject_unknown_fields(body, set())

    if policy["lifecycle_state"] not in ("BOUND", "ACTIVE"):
        raise_err(ERR_POLICY_NOT_CANCELLABLE,
                  "cancel requires lifecycle_state BOUND or ACTIVE")

    for claim in core.claims_of_policy(policy["id"]):
        if claim["claim_state"] in core.BLOCKING_CLAIM_STATES:
            raise_err(ERR_OPEN_CLAIMS_BLOCK_CANCEL,
                      "Open claims block policy cancellation")

    now = carrier["current_utc"]
    policy["lifecycle_state"] = "CANCELLED"
    policy["premium_reserve_cents"] = 0
    db.touch(policy, now)

    for claim in core.claims_of_policy(policy["id"]):
        if claim["claim_state"] == "REPORTED":
            claim["claim_state"] = "WITHDRAWN"
            db.touch(claim, now)
            core.release_unit(claim, now)

    return success_object(policy_view(policy))

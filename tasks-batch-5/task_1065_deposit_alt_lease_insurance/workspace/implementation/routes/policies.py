from flask import Blueprint, request
from db import db, touch, fmt_ts, now
from errors import err
from middleware import get_caller, require_role
from response import object_response, array_response, parse_pagination, paginate
from validate import body, require_int
import lookups
from services.underwriting import compute_fee
from services.recompute import recompute_policy_gross, recompute_policy_net

policies_bp = Blueprint("policies", __name__)


def _check_policy_ownership(caller, policy):
    if caller.role == "Renter" and lookups.renter_id_for_policy(policy) != caller.user_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own this policy.")
    if caller.role == "Landlord" and lookups.landlord_id_for_policy(policy) != caller.user_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own this policy.")


@policies_bp.get("/policies/<policy_id>")
def get_policy(policy_id):
    caller = get_caller()
    require_role(caller, {"Renter", "UnderwritingAgent", "Landlord", "ClaimsAdjuster", "ComplianceOfficer", "PlatformAdmin"})
    policy = lookups.get_policy(policy_id)
    _check_policy_ownership(caller, policy)
    return object_response(policy)


@policies_bp.post("/policies/<policy_id>/cancel")
def cancel_policy(policy_id):
    caller = get_caller()
    require_role(caller, {"Renter"})
    policy = lookups.get_policy(policy_id)
    if lookups.renter_id_for_policy(policy) != caller.user_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own this policy.")

    if policy["status"] not in ("ACTIVE", "LAPSED"):
        raise err("ERR_INVALID_STATE", "Policy cannot be cancelled from its current state.")

    policy["status"] = "CANCELLED"
    policy["cancelled_at"] = fmt_ts(now())
    touch(policy)
    return object_response(policy)


@policies_bp.post("/policies/<policy_id>/coverage-limit-adjustments")
def adjust_coverage_limit(policy_id):
    caller = get_caller()
    require_role(caller, {"UnderwritingAgent"})
    b = body()
    requested_coverage_limit_cents = require_int(b, "requested_coverage_limit_cents", positive=True)
    expected_policy_version = require_int(b, "expected_policy_version")

    policy = lookups.get_policy(policy_id)

    if expected_policy_version != policy["version"]:
        raise err("ERR_STALE_POLICY_VERSION", "expected_policy_version does not match the policy's current version.")

    prop = lookups.property_for_policy(policy)
    enrollment = lookups.enrollment_for_policy(policy)
    rule = db.state_compliance_rules.get(prop["state_code"])
    fee_calc = compute_fee(requested_coverage_limit_cents, enrollment["risk_tier"], prop, rule)
    if fee_calc["exceeds_cap"]:
        raise err("ERR_FEE_EXCEEDS_STATE_CAP", "Monthly fee would exceed the state's fee cap.")

    policy["coverage_limit_cents"] = requested_coverage_limit_cents
    policy["monthly_fee_cents"] = fee_calc["monthly_fee_cents"]
    recompute_policy_gross(policy)
    recompute_policy_net(policy)
    touch(policy)
    return object_response(policy)


@policies_bp.get("/policies/<policy_id>/invoices")
def list_policy_invoices(policy_id):
    caller = get_caller()
    require_role(caller, {"Renter", "UnderwritingAgent", "ClaimsAdjuster", "PlatformAdmin"})
    policy = lookups.get_policy(policy_id)
    _check_policy_ownership(caller, policy)

    limit, offset = parse_pagination(request.args)
    items = lookups.invoices_for_policy(policy["id"])
    window, total = paginate(items, limit, offset)
    return array_response(window, 200, limit, offset, total)


@policies_bp.get("/policies/<policy_id>/claims")
def list_policy_claims(policy_id):
    caller = get_caller()
    require_role(caller, {"Landlord", "ClaimsAdjuster", "PlatformAdmin", "Renter"})
    policy = lookups.get_policy(policy_id)
    _check_policy_ownership(caller, policy)

    limit, offset = parse_pagination(request.args)
    items = lookups.claims_for_policy(policy["id"])
    window, total = paginate(items, limit, offset)
    return array_response(window, 200, limit, offset, total)

from flask import Blueprint, request
from db import db, new_common_fields, touch, parse_ts
from errors import err
from middleware import get_caller, require_role, require_ownership
from response import object_response, array_response, parse_pagination, paginate
from validate import body, require_str, require_int, require_enum, require_bool, require_datetime
import lookups
from services.underwriting import score_enrollment, compute_fee, create_policy_and_first_invoice, leases_overlap

renter_enrollments_bp = Blueprint("renter_enrollments", __name__)

PAYMENT_PLANS = {"MONTHLY", "ANNUAL_UPFRONT"}
AUTO_APPROVE_THRESHOLD = 35


@renter_enrollments_bp.post("/renter-enrollments")
def create_enrollment():
    caller = get_caller()
    require_role(caller, {"Renter"})
    b = body()

    property_id = require_str(b, "property_id")
    renter_id = require_str(b, "renter_id")
    payment_plan = require_enum(b, "payment_plan", PAYMENT_PLANS)
    requested_coverage_limit_cents = require_int(b, "requested_coverage_limit_cents", positive=True)
    self_reported_annual_income_cents = require_int(b, "self_reported_annual_income_cents", non_negative=True)
    verified_annual_income_cents = require_int(b, "verified_annual_income_cents", required=False, default=None, non_negative=True)
    employment_verified = require_bool(b, "employment_verified", required=False, default=False)
    credit_proxy_score = require_int(b, "credit_proxy_score", min_v=300, max_v=850)
    prior_eviction_count = require_int(b, "prior_eviction_count", required=False, default=0, non_negative=True)
    lease_start_date = require_datetime(b, "lease_start_date")
    lease_end_date = require_datetime(b, "lease_end_date")
    if lease_end_date <= lease_start_date:
        raise err("ERR_VALIDATION", "lease_end_date must be strictly after lease_start_date.")

    # existence: property_id then renter_id (body top-to-bottom order)
    prop = lookups.get_property(property_id)
    renter = lookups.get_renter(renter_id)
    require_ownership(caller, renter["id"], "Renter")

    rule = db.state_compliance_rules.get(prop["state_code"])
    if rule is None:
        raise err("ERR_STATE_NOT_CONFIGURED", "No StateComplianceRule for this property's state.")
    if not rule["enrollment_allowed"]:
        raise err("ERR_STATE_ENROLLMENT_PROHIBITED", "Enrollment is prohibited in this state.")
    if prop["program_status"] != "ACTIVE":
        raise err("ERR_PROPERTY_NOT_ACTIVE", "Property is not ACTIVE.")

    existing_policies = lookups.policies_for_property(prop["id"])
    if leases_overlap(existing_policies, lease_start_date, lease_end_date):
        raise err("ERR_LEASE_TERM_OVERLAP", "Lease window overlaps an existing policy for this property.")

    from db import fmt_ts
    enrollment = {
        **new_common_fields(),
        "property_id": property_id,
        "renter_id": renter_id,
        "payment_plan": payment_plan,
        "requested_coverage_limit_cents": requested_coverage_limit_cents,
        "self_reported_annual_income_cents": self_reported_annual_income_cents,
        "verified_annual_income_cents": verified_annual_income_cents,
        "employment_verified": employment_verified,
        "credit_proxy_score": credit_proxy_score,
        "prior_eviction_count": prior_eviction_count,
        "lease_start_date": fmt_ts(lease_start_date),
        "lease_end_date": fmt_ts(lease_end_date),
        "risk_score_self_reported": None,
        "risk_score_verified": None,
        "risk_tier": None,
        "status": "PENDING_UNDERWRITING",
    }
    db.renter_enrollments[enrollment["id"]] = enrollment
    return object_response(enrollment, 201)


def _enrollment_visible_scope(caller):
    """Returns a predicate(enrollment) enforcing ownership scoping for Renter/Landlord."""
    if caller.role == "Renter":
        return lambda e: e["renter_id"] == caller.user_id
    if caller.role == "Landlord":
        landlord_property_ids = {p["id"] for p in lookups.properties_for_landlord(caller.user_id)}
        return lambda e: e["property_id"] in landlord_property_ids
    return lambda e: True


@renter_enrollments_bp.get("/renter-enrollments")
def list_enrollments():
    caller = get_caller()
    require_role(caller, {"Renter", "UnderwritingAgent", "Landlord", "PlatformAdmin"})

    property_id = request.args.get("property_id")
    renter_id = request.args.get("renter_id")
    limit, offset = parse_pagination(request.args)

    scope = _enrollment_visible_scope(caller)
    items = [e for e in db.renter_enrollments.values() if scope(e)]
    if property_id:
        items = [e for e in items if e["property_id"] == property_id]
    if renter_id:
        items = [e for e in items if e["renter_id"] == renter_id]

    window, total = paginate(items, limit, offset)
    return array_response(window, 200, limit, offset, total)


def _check_enrollment_ownership(caller, enrollment):
    if caller.role == "Renter" and enrollment["renter_id"] != caller.user_id:
        raise err("ERR_UNAUTHORIZED", "Caller does not own this enrollment.")
    if caller.role == "Landlord":
        prop = db.properties[enrollment["property_id"]]
        if prop["landlord_id"] != caller.user_id:
            raise err("ERR_UNAUTHORIZED", "Caller does not own this enrollment's property.")


@renter_enrollments_bp.get("/renter-enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    caller = get_caller()
    require_role(caller, {"Renter", "UnderwritingAgent", "Landlord", "PlatformAdmin"})
    enrollment = lookups.get_enrollment(enrollment_id)
    _check_enrollment_ownership(caller, enrollment)
    return object_response(enrollment)


@renter_enrollments_bp.post("/renter-enrollments/<enrollment_id>/submit-underwriting")
def submit_underwriting(enrollment_id):
    caller = get_caller()
    require_role(caller, {"Renter"})
    enrollment = lookups.get_enrollment(enrollment_id)
    require_ownership(caller, enrollment["renter_id"], "Renter")

    if enrollment["status"] != "PENDING_UNDERWRITING":
        raise err("ERR_INVALID_STATE", "Enrollment is not PENDING_UNDERWRITING.")

    prop = db.properties[enrollment["property_id"]]
    scored = score_enrollment(enrollment, prop)
    enrollment["risk_score_self_reported"] = scored["risk_score_self_reported"]
    enrollment["risk_score_verified"] = scored["risk_score_verified"]
    enrollment["risk_tier"] = scored["risk_tier"]

    if scored["official_score"] <= AUTO_APPROVE_THRESHOLD:
        rule = db.state_compliance_rules.get(prop["state_code"])
        fee_calc = compute_fee(enrollment["requested_coverage_limit_cents"], scored["risk_tier"], prop, rule)
        if fee_calc["exceeds_cap"]:
            raise err("ERR_FEE_EXCEEDS_STATE_CAP", "Monthly fee would exceed the state's fee cap.")
        policy, invoice = create_policy_and_first_invoice(enrollment, fee_calc["monthly_fee_cents"])
        db.policies[policy["id"]] = policy
        db.invoices[invoice["id"]] = invoice
        enrollment["status"] = "APPROVED"
    else:
        enrollment["status"] = "MANUAL_REVIEW"

    touch(enrollment)
    return object_response(enrollment)


@renter_enrollments_bp.post("/renter-enrollments/<enrollment_id>/decide")
def decide_enrollment(enrollment_id):
    caller = get_caller()
    require_role(caller, {"UnderwritingAgent"})
    b = body()
    action = require_enum(b, "action", {"APPROVE", "DECLINE"})
    decision_notes = require_str(b, "decision_notes", required=False, default=None)

    enrollment = lookups.get_enrollment(enrollment_id)
    if enrollment["status"] != "MANUAL_REVIEW":
        raise err("ERR_INVALID_STATE", "Enrollment is not in MANUAL_REVIEW.")

    if action == "APPROVE":
        prop = db.properties[enrollment["property_id"]]
        rule = db.state_compliance_rules.get(prop["state_code"])
        fee_calc = compute_fee(enrollment["requested_coverage_limit_cents"], enrollment["risk_tier"], prop, rule)
        if fee_calc["exceeds_cap"]:
            raise err("ERR_FEE_EXCEEDS_STATE_CAP", "Monthly fee would exceed the state's fee cap.")
        policy, invoice = create_policy_and_first_invoice(enrollment, fee_calc["monthly_fee_cents"])
        db.policies[policy["id"]] = policy
        db.invoices[invoice["id"]] = invoice
        enrollment["status"] = "APPROVED"
    else:
        enrollment["status"] = "DECLINED"

    # NOTE: decision_notes is accepted as input but RenterEnrollment has no
    # decision_notes field in the entity model (unlike Claim) -- not persisted.
    touch(enrollment)
    return object_response(enrollment)


@renter_enrollments_bp.get("/renter-enrollments/<enrollment_id>/policy")
def get_enrollment_policy(enrollment_id):
    caller = get_caller()
    require_role(caller, {"Renter", "UnderwritingAgent", "Landlord", "PlatformAdmin"})
    enrollment = lookups.get_enrollment(enrollment_id)
    _check_enrollment_ownership(caller, enrollment)

    policy = lookups.policy_for_enrollment(enrollment["id"])
    items = [policy] if policy else []
    return array_response(items, 200, 10, 0, len(items))

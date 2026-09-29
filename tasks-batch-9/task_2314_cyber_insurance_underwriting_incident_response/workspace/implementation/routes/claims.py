"""Incident notification, triage, coverage confirmation and panel deployment."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import calc
import errors
import validate
from calc import dec
from cascades import deny_claim, run_waterfall, eligible_sections
from db import new_row, now_iso, round2, sorted_by_created, store, touch
from errors import ApiError, bad_request
from middleware import (CLAIMS_ADJUSTER, INSURED, PANEL_ADMIN, PORTFOLIO_ACTUARY,
                        UNDERWRITER, endpoint, find_claim, find_engagement, find_policy,
                        find_scenario, find_vendor, is_insured, owner_of_claim,
                        owner_of_engagement, scope_guard, scoped_filter)
from response import created, listing, ok
from routes.common import apply_eq, filter_value

bp = Blueprint("claims", __name__, url_prefix="/cyber")


# --------------------------------------------------------------------------
# notification
# --------------------------------------------------------------------------

def _dependent_bi_guard(policy, dependency_key):
    if calc.section_by_key(policy["id"], "DEPENDENT_BI") is None:
        raise ApiError(errors.ERR_DEPENDENT_BI_NOT_COVERED, 422,
                       "the policy tower has no DEPENDENT_BI section")
    if policy["dependent_bi_definition"] == "NAMED_ONLY":
        if dependency_key not in (policy["named_dependency_keys"] or []):
            raise ApiError(errors.ERR_DEPENDENT_BI_NOT_COVERED, 422,
                           "%s is not scheduled among the policy's named dependencies"
                           % dependency_key)


@bp.route("/incident-claims", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER, INSURED])
def notify_incident():
    payload = validate.body()
    policy = find_policy(validate.req_str(payload, "policy_id"))
    scope_guard(policy["insured_account_id"])
    scenario_id = payload.get("systemic_event_scenario_id")
    if scenario_id is not None:
        find_scenario(validate.req_str(payload, "systemic_event_scenario_id"))

    incident_type = validate.req_enum(payload, "incident_type", calc.INCIDENT_TYPES)
    discovered_raw, discovered = validate.req_dt(payload, "incident_discovered_at")
    if incident_type in calc.OUTAGE_REQUIRED_TYPES:
        outage_start_raw, outage_start = validate.req_dt(payload, "outage_start_at")
        outage_end_raw, outage_end = validate.req_dt(payload, "outage_end_at")
    else:
        outage_start_raw, outage_start = validate.opt_dt(payload, "outage_start_at")
        outage_end_raw, outage_end = validate.opt_dt(payload, "outage_end_at")
    if outage_start is not None and outage_end is not None:
        if not outage_start < outage_end:
            raise bad_request("outage_end_at must be strictly after outage_start_at")
    if incident_type == "DEPENDENT_OUTAGE":
        dependency_key = validate.req_enum(payload, "dependency_key", calc.DEPENDENCY_KEYS)
    else:
        dependency_key = validate.opt_enum(payload, "dependency_key", calc.DEPENDENCY_KEYS,
                                           default="NONE")
    record_count = validate.opt_int(payload, "affected_record_count", 0, None, default=0)

    if policy["lifecycle_status"] != "INFORCE" or policy["limit_status"] == "EXHAUSTED":
        raise ApiError(errors.ERR_INVALID_POLICY_STATE, 409,
                       "the responding policy is not INFORCE with capacity remaining")

    if not (policy["_period_start"] <= discovered < policy["_period_end"]):
        raise ApiError(errors.ERR_INCIDENT_OUTSIDE_POLICY_PERIOD, 422,
                       "incident_discovered_at falls outside the policy period")
    notified = store.clock
    if notified - discovered > timedelta(days=calc.NOTIFICATION_DEADLINE_DAYS):
        raise ApiError(errors.ERR_LATE_NOTIFICATION, 422,
                       "notification is more than %d days after discovery"
                       % calc.NOTIFICATION_DEADLINE_DAYS)

    if incident_type == "DEPENDENT_OUTAGE":
        _dependent_bi_guard(policy, dependency_key)

    row = new_row({
        "policy_id": policy["id"],
        "systemic_event_scenario_id": scenario_id,
        "incident_type": incident_type,
        "incident_discovered_at": discovered_raw,
        "notified_at": now_iso(),
        "outage_start_at": outage_start_raw,
        "outage_end_at": outage_end_raw,
        "dependency_key": dependency_key,
        "affected_record_count": record_count,
        "status": "NOTIFIED",
        "covered_section_keys": [],
        "reservation_of_rights": False,
        "reserved_amount_usd": round2(0),
        "retention_absorbed_usd": round2(0),
        "paid_total_usd": round2(0),
        "unallocated_loss_usd": round2(0),
        "proof_review_round": 0,
        "denial_reason": None,
        "_incident_discovered_at": discovered,
        "_outage_start_at": outage_start,
        "_outage_end_at": outage_end,
    })
    store.incident_claims[row["id"]] = row
    return created(row)


@bp.route("/incident-claims/<claim_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def read_claim(claim_id):
    claim = find_claim(claim_id)
    scope_guard(owner_of_claim(claim))
    return ok(claim)


@bp.route("/incident-claims", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def list_claims():
    rows = list(store.incident_claims.values())
    rows = apply_eq(rows, "policy_id", filter_value("policy_id"))
    rows = apply_eq(rows, "systemic_event_scenario_id",
                    filter_value("systemic_event_scenario_id"))
    rows = apply_eq(rows, "status", filter_value("status", calc.CLAIM_STATES))
    rows = apply_eq(rows, "incident_type", filter_value("incident_type", calc.INCIDENT_TYPES))
    rows = scoped_filter(rows, owner_of_claim)
    return listing(sorted_by_created(rows))


# --------------------------------------------------------------------------
# triage / coverage / denial
# --------------------------------------------------------------------------

@bp.route("/incident-claims/<claim_id>/triage", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER])
def triage_claim(claim_id):
    claim = find_claim(claim_id)
    if claim["status"] != "NOTIFIED":
        raise ApiError(errors.ERR_INVALID_CLAIM_STATE, 409,
                       "only a NOTIFIED claim may be moved into triage")
    policy = store.policies[claim["policy_id"]]
    if policy["lifecycle_status"] != "INFORCE":
        raise ApiError(errors.ERR_INVALID_POLICY_STATE, 409,
                       "the responding policy is no longer INFORCE")
    claim["status"] = "TRIAGE"
    touch(claim)
    return ok(claim)


@bp.route("/incident-claims/<claim_id>/confirm-coverage", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER])
def confirm_coverage(claim_id):
    claim = find_claim(claim_id)
    payload = validate.body()
    policy = store.policies[claim["policy_id"]]
    tower_keys = set(row["section_key"] for row in calc.sections_of(policy["id"]))

    raw = payload.get("covered_section_keys")
    if raw is None:
        raise bad_request("covered_section_keys is required")
    if not isinstance(raw, list):
        raise bad_request("covered_section_keys must be an array")
    for entry in raw:
        if not isinstance(entry, str) or entry not in tower_keys:
            raise ApiError(errors.ERR_COVERAGE_SECTION_NOT_FOUND, 404,
                           "the policy tower contains no section named %r" % (entry,))
    covered = validate.req_array(payload, "covered_section_keys", calc.SECTION_KEYS,
                                 non_empty=True)
    reserve = validate.req_num(payload, "initial_reserve_usd", minimum=0, money=True)
    reservation = validate.req_bool(payload, "reservation_of_rights", default=False)

    if claim["status"] != "TRIAGE":
        raise ApiError(errors.ERR_INVALID_CLAIM_STATE, 409,
                       "coverage may only be confirmed on a claim in TRIAGE")
    if policy["lifecycle_status"] != "INFORCE" or policy["limit_status"] == "EXHAUSTED":
        raise ApiError(errors.ERR_INVALID_POLICY_STATE, 409,
                       "the responding policy is not INFORCE with capacity remaining")
    if policy["warranty_status"] != "COMPLIANT":
        raise ApiError(errors.ERR_MANDATORY_CONTROL_LAPSE, 422,
                       "the policy's warranty controls are lapsed")
    if claim["incident_type"] == "DEPENDENT_OUTAGE":
        _dependent_bi_guard(policy, claim["dependency_key"])
    if dec(policy["aggregate_limit_remaining_usd"]) <= 0:
        raise ApiError(errors.ERR_AGGREGATE_LIMIT_EXHAUSTED, 422,
                       "the policy aggregate limit is exhausted")

    claim["covered_section_keys"] = covered
    claim["reservation_of_rights"] = reservation
    claim["reserved_amount_usd"] = round2(reserve)
    claim["status"] = "COVERAGE_CONFIRMED"
    touch(claim)
    return ok(claim)


@bp.route("/incident-claims/<claim_id>/deny", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER])
def deny_incident_claim(claim_id):
    claim = find_claim(claim_id)
    payload = validate.body()
    reason = validate.req_str(payload, "denial_reason", 1, None)
    if claim["status"] not in ("TRIAGE", "RESPONSE_ACTIVE", "PROOF_REVIEW", "INFO_REQUESTED"):
        raise ApiError(errors.ERR_INVALID_CLAIM_STATE, 409,
                       "a claim in %s may not be denied" % claim["status"])
    deny_claim(claim, reason)
    return ok(claim)


# --------------------------------------------------------------------------
# vendor engagements
# --------------------------------------------------------------------------

@bp.route("/incident-claims/<claim_id>/vendor-engagements", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER])
def authorize_engagement(claim_id):
    claim = find_claim(claim_id)
    payload = validate.body()
    directed = None
    if validate.present(payload, "panel_vendor_id"):
        directed = find_vendor(validate.req_str(payload, "panel_vendor_id"))

    vendor_type = validate.req_enum(payload, "vendor_type", calc.VENDOR_TYPES)
    start_raw, start = validate.req_dt(payload, "deployment_start_at")
    end_raw, end = validate.req_dt(payload, "deployment_end_at")
    if not start < end:
        raise bad_request("deployment_end_at must be strictly after deployment_start_at")
    hours_cap = validate.req_num(payload, "authorized_hours_cap", minimum=0,
                                exclusive_min=True, maximum=5000)
    directed_rate = validate.opt_num(payload, "directed_rate_usd", minimum=0, money=True)

    if claim["status"] not in ("COVERAGE_CONFIRMED", "RESPONSE_ACTIVE"):
        raise ApiError(errors.ERR_INVALID_CLAIM_STATE, 409,
                       "a panel deployment requires a claim in COVERAGE_CONFIRMED "
                       "or RESPONSE_ACTIVE")
    policy = store.policies[claim["policy_id"]]
    account = store.insured_accounts[policy["insured_account_id"]]

    if directed is not None:
        if directed["status"] != "ACTIVE":
            raise ApiError(errors.ERR_VENDOR_NOT_ACTIVE, 409,
                           "the directed panel firm is not ACTIVE")
        if calc.colliding_count(directed["id"], start, end) \
                >= directed["capacity_concurrent_engagements"]:
            raise ApiError(errors.ERR_VENDOR_WINDOW_CONFLICT, 422,
                           "the directed panel firm has no capacity in that window")
        vendor = directed
        selection_mode = "DIRECTED"
    else:
        vendor = calc.panel_vendor_selection(vendor_type, account["industry_code"], start, end)
        if vendor is None:
            raise ApiError(errors.ERR_NO_ELIGIBLE_PANEL_VENDOR, 422,
                           "no eligible panel firm is available for that window")
        selection_mode = "PANEL_SELECTED"

    if directed is not None and directed_rate is not None:
        if dec(directed_rate) > dec(vendor["pre_approved_hourly_rate_usd"]):
            raise ApiError(errors.ERR_RATE_EXCEEDS_PRE_APPROVED, 422,
                           "directed_rate_usd exceeds the firm's pre-approved hourly rate")
    if policy["limit_status"] == "EXHAUSTED" \
            or dec(policy["aggregate_limit_remaining_usd"]) <= 0:
        raise ApiError(errors.ERR_AGGREGATE_LIMIT_EXHAUSTED, 422,
                       "the policy aggregate limit is exhausted")

    engagement = new_row({
        "incident_claim_id": claim["id"],
        "panel_vendor_id": vendor["id"],
        "vendor_type": vendor_type,
        "selection_mode": selection_mode,
        "deployment_start_at": start_raw,
        "deployment_end_at": end_raw,
        "authorized_hours_cap": hours_cap,
        "approved_rate_usd": round2(dec(vendor["pre_approved_hourly_rate_usd"])),
        "approved_per_record_rate_usd": round2(dec(vendor["per_record_notification_rate_usd"])),
        "authorized_by_user_id": g.user_id,
        "incurred_hours": Decimal("0"),
        "records_notified": 0,
        "incurred_amount_usd": round2(0),
        "status": "AUTHORIZED",
        "_deployment_start_at": start,
        "_deployment_end_at": end,
    })
    store.vendor_engagements[engagement["id"]] = engagement

    vendor["active_engagement_count"] = vendor["active_engagement_count"] + 1
    touch(vendor)
    if claim["status"] == "COVERAGE_CONFIRMED":
        claim["status"] = "RESPONSE_ACTIVE"
    touch(claim)
    return created(engagement)


@bp.route("/vendor-engagements/<engagement_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, PANEL_ADMIN, INSURED])
def read_engagement(engagement_id):
    engagement = find_engagement(engagement_id)
    scope_guard(owner_of_engagement(engagement))
    return ok(engagement)


@bp.route("/vendor-engagements", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, PANEL_ADMIN, INSURED])
def list_engagements():
    rows = list(store.vendor_engagements.values())
    rows = apply_eq(rows, "incident_claim_id", filter_value("incident_claim_id"))
    rows = apply_eq(rows, "panel_vendor_id", filter_value("panel_vendor_id"))
    rows = apply_eq(rows, "vendor_type", filter_value("vendor_type", calc.VENDOR_TYPES))
    rows = apply_eq(rows, "status", filter_value("status", calc.ENGAGEMENT_STATES))
    rows = scoped_filter(rows, owner_of_engagement)
    return listing(sorted_by_created(rows))


@bp.route("/vendor-engagements/<engagement_id>/log-hours", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER])
def log_engagement_hours(engagement_id):
    engagement = find_engagement(engagement_id)
    payload = validate.body()
    hours = validate.req_num(payload, "hours", minimum=0)
    records = validate.opt_int(payload, "records_notified", 0, None, default=0)

    if engagement["status"] not in calc.LIVE_ENGAGEMENT_STATES:
        raise ApiError(errors.ERR_INVALID_ENGAGEMENT_STATE, 409,
                       "work may not be logged against a %s engagement" % engagement["status"])
    cumulative_hours = dec(engagement["incurred_hours"]) + dec(hours)
    if cumulative_hours > dec(engagement["authorized_hours_cap"]):
        raise ApiError(errors.ERR_AUTHORIZED_HOURS_EXCEEDED, 422,
                       "cumulative hours would exceed authorized_hours_cap")

    engagement["incurred_hours"] = cumulative_hours
    engagement["records_notified"] = engagement["records_notified"] + records
    engagement["incurred_amount_usd"] = calc.engagement_incurred_amount(
        engagement, cumulative_hours, engagement["records_notified"])
    engagement["status"] = "ACTIVE"
    touch(engagement)
    return ok(engagement)


@bp.route("/vendor-engagements/<engagement_id>/complete", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER])
def complete_engagement(engagement_id):
    engagement = find_engagement(engagement_id)
    if engagement["status"] not in calc.LIVE_ENGAGEMENT_STATES:
        raise ApiError(errors.ERR_INVALID_ENGAGEMENT_STATE, 409,
                       "a %s engagement may not be completed" % engagement["status"])
    claim = store.incident_claims[engagement["incident_claim_id"]]
    if claim["status"] not in ("COVERAGE_CONFIRMED", "RESPONSE_ACTIVE", "PROOF_REVIEW",
                               "INFO_REQUESTED", "APPROVED_FOR_PAYMENT"):
        raise ApiError(errors.ERR_INVALID_CLAIM_STATE, 409,
                       "the claim is not in a state that admits engagement completion")
    policy = store.policies[claim["policy_id"]]
    eligible_keys = calc.SECTIONS_FOR_VENDOR_TYPE[engagement["vendor_type"]]
    # priority 13 -- verified before anything is mutated
    eligible_sections(claim, policy, eligible_keys)
    incurred = dec(engagement["incurred_amount_usd"])
    if incurred > 0 and policy["limit_status"] == "EXHAUSTED":
        raise ApiError(errors.ERR_AGGREGATE_LIMIT_EXHAUSTED, 422,
                       "the policy aggregate limit is exhausted")

    engagement["status"] = "COMPLETED"
    touch(engagement)
    vendor = store.panel_vendors.get(engagement["panel_vendor_id"])
    if vendor is not None:
        vendor["active_engagement_count"] = max(0, vendor["active_engagement_count"] - 1)
        touch(vendor)
    run_waterfall(claim, policy, incurred, eligible_keys, "VENDOR_ENGAGEMENT")
    return ok(engagement)

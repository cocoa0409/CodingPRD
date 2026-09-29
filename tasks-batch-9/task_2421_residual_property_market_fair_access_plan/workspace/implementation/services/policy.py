"""Policy construction and the termination cascade shared by cancellation,
take-out acceptance and the expiry sweep."""

from db import db, new_record, touch
from util import add_days, fmt_date, parse_date
from services import commission as commission_svc
from services import premium as premium_svc
from services import refund as refund_svc
from services import zone as zone_svc
from services.constants import EXCLUDED_PERILS, POLICY_TERM_DAYS


def terms_overlap(new_effective, new_expiration, existing):
    """Half-open [effective, expiration) intersection; touching endpoints do
    NOT collide (PRD 2.6 / 3.6)."""
    other_effective = parse_date(existing["effective_date"])
    other_expiration = parse_date(existing["expiration_date"])
    return new_effective < other_expiration and other_effective < new_expiration


def conflicting_policy(property_id, new_effective, new_expiration, exclude_id=None):
    for policy in db.policies.values():
        if policy["property_id"] != property_id:
            continue
        if exclude_id is not None and policy["id"] == exclude_id:
            continue
        if policy["coverage_status"] not in ("BOUND", "IN_FORCE"):
            continue
        if terms_overlap(new_effective, new_expiration, policy):
            return policy
    return None


def build_policy(application, prop, applicant_id, producer, filing, zone,
                 dwelling_limit_cents, effective_date, score,
                 cleared_major_count, condition_score_at_bind,
                 predecessor_policy_id=None):
    """Create the Policy row, credit commission and push the zone posture.

    The territory's concentration_ratio is read BEFORE this policy's own
    exposure is added (PRD 3.6 step 3).
    """
    peril_package = application["requested_peril_package"]
    base_cents, cat_cents, annual_cents = premium_svc.compute(
        filing["filed_rate_per_1000_cents"],
        dwelling_limit_cents,
        prop["construction_type"],
        prop["occupancy"],
        peril_package,
        zone["concentration_ratio"],
        score,
        cleared_major_count,
    )
    expiration_date = add_days(effective_date, POLICY_TERM_DAYS)
    coverage_status = "IN_FORCE" if effective_date <= db.today() else "BOUND"

    policy = new_record({
        "application_id": application["id"],
        "property_id": prop["id"],
        "applicant_id": applicant_id,
        "producer_id": producer["id"] if producer else application["producer_id"],
        "rate_filing_id": filing["id"],
        "predecessor_policy_id": predecessor_policy_id,
        "dwelling_limit_cents": dwelling_limit_cents,
        "peril_package": peril_package,
        "excluded_perils": list(EXCLUDED_PERILS[peril_package]),
        "condition_score_at_bind": condition_score_at_bind,
        "base_premium_cents": base_cents,
        "cat_surcharge_cents": cat_cents,
        "annual_premium_cents": annual_cents,
        "exposure_value_cents": dwelling_limit_cents,
        "commission_credited_cents": 0,
        "commission_returned_cents": 0,
        "coverage_status": coverage_status,
        "depopulation_status": "NOT_OFFERED",
        "effective_date": fmt_date(effective_date),
        "expiration_date": fmt_date(expiration_date),
        "cancel_reason": None,
        "cancellation_date": None,
        "unearned_premium_cents": 0,
        "cancellation_fee_cents": 0,
        "refund_cents": 0,
    })
    policy["commission_credited_cents"] = commission_svc.credit_for(policy, producer)
    db.policies[policy["id"]] = policy

    # Producer: ytd_commission_cents rises and the producer's version increments.
    commission_svc.recompute_ytd(producer)
    # Territory: aggregate, ratio and status re-derived; version increments.
    zone_svc.recompute(zone)
    return policy


def terminate(policy, coverage_status, cancel_reason, cancellation_date,
              with_refund=True):
    """Shared termination cascade.

    Writes the refund legs and the commission clawback, then releases the
    territory's exposure and re-derives its posture.
    """
    policy["coverage_status"] = coverage_status
    if cancel_reason is not None:
        policy["cancel_reason"] = cancel_reason
    if cancellation_date is not None:
        policy["cancellation_date"] = fmt_date(cancellation_date)

    if with_refund:
        fraction, unearned, fee, refund = refund_svc.compute(
            policy, cancel_reason, cancellation_date)
        policy["unearned_premium_cents"] = unearned
        policy["cancellation_fee_cents"] = fee
        policy["refund_cents"] = refund
        producer = db.producers.get(policy["producer_id"])
        policy["commission_returned_cents"] = commission_svc.return_for(
            policy, fraction)
        commission_svc.recompute_ytd(producer)

    touch(policy)
    zone = zone_svc.zone_of_policy(policy)
    if zone is not None:
        zone_svc.recompute(zone)
    return policy

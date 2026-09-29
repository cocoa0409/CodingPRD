"""Pricing policy endpoints (PRD §3.1)."""

from flask import Blueprint

import lookup
from auth import ALL_ROLES, ROLE_BRAND_CHANNEL_MANAGER, ROLE_BRAND_LEGAL_COUNSEL, authenticate
from envelope import created, ok, ok_list
from errors import fail
from store import new_row, now_dt, parse_iso, serialize, store, touch
from validate import (
    body, opt_bool, opt_fraction, opt_int, opt_str, req_dt, req_enum, req_str,
)

bp = Blueprint("policies", __name__)

REVIEW_DECISIONS = ["APPROVE_FOR_PUBLICATION", "RETURN_FOR_REVISION"]


@bp.post("/pricing-policies")
def draft_policy():
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    policy_code = req_str(b, "policy_code", 1, 40)
    shipping = opt_bool(b, "shipping_counts_as_advertised", False)
    auto_coupon = opt_bool(b, "auto_coupon_counts_as_advertised", True)
    promo_code = opt_bool(b, "promo_code_counts_as_advertised", False)
    max_attr = opt_fraction(b, "max_discount_attribution_pct", 0.00, 1.00, 0.40)
    ack_required = opt_bool(b, "non_negotiation_ack_required", True)
    cure_window_days = opt_int(b, "cure_window_days", 1, 60, 10)
    suspension_threshold = opt_int(b, "suspension_points_threshold", 1, None, 6)
    termination_threshold = opt_int(b, "termination_points_threshold", None, None, 12)
    cooling_off = opt_int(b, "suspension_cooling_off_days", 0, 180, 14)
    if termination_threshold <= suspension_threshold:
        fail("ERR_VALIDATION",
             "termination_points_threshold must be strictly greater than suspension_points_threshold.")
    for existing in store.policies.values():
        if existing["policy_code"] == policy_code:
            fail("ERR_VALIDATION", "policy_code must be unique across every policy.")

    row = new_row({
        "policy_code": policy_code,
        "revision_number": 1,
        "status": "DRAFT",
        "effective_from": None,
        "shipping_counts_as_advertised": shipping,
        "auto_coupon_counts_as_advertised": auto_coupon,
        "promo_code_counts_as_advertised": promo_code,
        "max_discount_attribution_pct": max_attr,
        "non_negotiation_ack_required": ack_required,
        "cure_window_days": cure_window_days,
        "suspension_points_threshold": suspension_threshold,
        "termination_points_threshold": termination_threshold,
        "suspension_cooling_off_days": cooling_off,
        "legal_review_notes": None,
        "reviewed_by_user_id": None,
        "published_by_user_id": None,
        "superseded_by_policy_id": None,
        "withdrawn_reason": None,
    })
    store.policies[row["id"]] = row
    return created(serialize(row))


@bp.post("/pricing-policies/<policy_id>/submit-review")
def submit_review(policy_id):
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    body()
    policy = lookup.policy(policy_id)
    if policy["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT policy may be submitted for review.")
    if policy["termination_points_threshold"] <= policy["suspension_points_threshold"]:
        fail("ERR_VALIDATION",
             "termination_points_threshold must be strictly greater than suspension_points_threshold.")
    policy["status"] = "IN_LEGAL_REVIEW"
    touch(policy)
    return ok(serialize(policy))


@bp.post("/pricing-policies/<policy_id>/review-decision")
def review_decision(policy_id):
    ctx = authenticate([ROLE_BRAND_LEGAL_COUNSEL])
    b = body()
    decision = req_enum(b, "decision", REVIEW_DECISIONS)
    notes = opt_str(b, "legal_review_notes", 0, None)
    policy = lookup.policy(policy_id)
    if policy["status"] != "IN_LEGAL_REVIEW":
        fail("ERR_INVALID_STATE", "Only a policy IN_LEGAL_REVIEW may receive a review decision.")
    policy["legal_review_notes"] = notes
    policy["reviewed_by_user_id"] = ctx.user_id
    if decision == "RETURN_FOR_REVISION":
        policy["status"] = "DRAFT"
        policy["revision_number"] = policy["revision_number"] + 1
    else:
        policy["status"] = "APPROVED"
    touch(policy)
    return ok(serialize(policy))


@bp.post("/pricing-policies/<policy_id>/publish")
def publish(policy_id):
    ctx = authenticate([ROLE_BRAND_LEGAL_COUNSEL])
    b = body()
    effective_from = req_dt(b, "effective_from")
    policy = lookup.policy(policy_id)
    if policy["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED policy may be published.")
    if parse_iso(effective_from) < now_dt():
        fail("ERR_VALIDATION", "effective_from must be at or after the current logical clock.")

    for other in store.policies.values():
        if other["id"] == policy["id"] or other["status"] != "PUBLISHED":
            continue
        other["status"] = "SUPERSEDED"
        other["superseded_by_policy_id"] = policy["id"]
        touch(other)

    policy["status"] = "PUBLISHED"
    policy["effective_from"] = effective_from
    policy["published_by_user_id"] = ctx.user_id
    touch(policy)
    return ok(serialize(policy))


@bp.post("/pricing-policies/<policy_id>/withdraw")
def withdraw(policy_id):
    authenticate([ROLE_BRAND_LEGAL_COUNSEL])
    b = body()
    reason = req_str(b, "withdrawn_reason", 1, None)
    policy = lookup.policy(policy_id)
    if policy["status"] != "PUBLISHED":
        fail("ERR_INVALID_STATE", "Only a PUBLISHED policy may be withdrawn.")
    policy["status"] = "WITHDRAWN"
    policy["withdrawn_reason"] = reason
    touch(policy)
    return ok(serialize(policy))


@bp.get("/pricing-policies/<policy_id>")
def read_policy(policy_id):
    authenticate(ALL_ROLES)
    return ok(serialize(lookup.policy(policy_id)))


@bp.get("/pricing-policies")
def list_policies():
    authenticate(ALL_ROLES)
    rows = lookup.filtered("policies", {
        "status": "status",
        "policy_code": "policy_code",
        "superseded_by_policy_id": "superseded_by_policy_id",
    })
    return ok_list(rows)

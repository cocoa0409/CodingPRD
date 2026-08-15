"""ConsentReview, ConsentCondition, and CreditReview endpoints."""
from flask import Blueprint

import db
from db import store, new_id, touch, new_common, iso_logical, parse_iso
from errors import ApiError
from response import ok, created, paginate
from middleware import get_context, require_roles, ADMIN_READ
from validation import parse_body, require_path_entity
from domain import (
    get_consent_review, get_credit_review, get_conditions_for_review,
    get_certified_area, grant_consent, decrement_lease_open_count,
    compute_rent_differential,
)

bp = Blueprint("consent", __name__)

DENIAL_REASONS = ["INSUFFICIENT_CREDIT", "USE_CONFLICT", "INSUFFICIENT_MARKETING",
                  "EXISTING_TENANT_SOLICITATION"]
DECISIONS = ["GRANTED", "GRANTED_WITH_CONDITIONS", "DENIED"]


# ---------------------------------------------------------------------------
# ConsentReview — read
# ---------------------------------------------------------------------------

@bp.get("/sublease-admin/consent-reviews/<review_id>")
def get_consent_review_by_id(review_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    return ok(require_path_entity(store.consent_reviews, review_id))


@bp.get("/sublease-admin/consent-reviews")
def list_consent_reviews():
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    rows = list(store.consent_reviews.values())
    for f in ("transfer_request_id", "reviewer_landlord_id", "decision"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# ConsentReview — decide
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/consent-reviews/<review_id>/decide")
def decide_consent_review(review_id):
    uid, role, _ = get_context()
    require_roles(["Landlord"])
    body = parse_body({
        "decision": ("enum", True, DECISIONS),
        "denial_reason_code": ("enum", False, DENIAL_REASONS),
        "release_of_assignor": ("boolean", False, None),
        "conditions": ("conditions", False, None),
        "expected_consent_review_version": ("integer", True, None),
    }, allow_empty=False)

    # Existence (priority 3)
    review = require_path_entity(store.consent_reviews, review_id)
    transfer = store.transfer_requests.get(review["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent transfer not found")
    lease = store.leases[transfer["lease_id"]]

    # State (priority 5): review must be PENDING
    if review["decision"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Consent review is no longer PENDING")

    # Transfer must be in SUBMITTED or CONSENT_PENDING
    if transfer["status"] not in ("SUBMITTED", "CONSENT_PENDING"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Transfer is not in a decidable state")

    # Duty segregation (priority 6): caller must be the lease's landlord
    if uid != lease["landlord_party_id"]:
        raise ApiError("ERR_DUTY_SEGREGATION", 403,
                       "Only the lease's landlord of record may decide consent")

    # Consent window (priority 11): decision at or before deadline
    now = db.LOGICAL_CLOCK
    deadline_dt = parse_iso(transfer["consent_deadline"])
    if now > deadline_dt:
        raise ApiError("ERR_CONSENT_WINDOW_LAPSED", 409,
                       "Decision submitted after the consent deadline")

    # OCC (priority 14)
    if body["expected_consent_review_version"] != review["version"]:
        raise ApiError("ERR_STALE_REVIEW_VERSION", 412,
                       "Consent review version has advanced since last read")

    # Denial reason validation (after guards)
    decision = body["decision"]
    if decision == "DENIED":
        reason = body.get("denial_reason_code")
        if reason is None:
            raise ApiError("ERR_DENIAL_REASON_INVALID", 422,
                           "DENIED decision requires a denial_reason_code")
        if reason == "INSUFFICIENT_CREDIT":
            credit = get_credit_review(transfer["id"])
            if credit is None or credit["outcome"] != "FAIL":
                raise ApiError("ERR_DENIAL_REASON_INVALID", 422,
                               "INSUFFICIENT_CREDIT requires CreditReview outcome FAIL")

    # GRANTED_WITH_CONDITIONS requires at least one condition
    if decision == "GRANTED_WITH_CONDITIONS":
        conditions = body.get("conditions", [])
        if not conditions:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "conditions required for GRANTED_WITH_CONDITIONS")

    release_of_assignor = body.get("release_of_assignor", False)

    # --- Apply decision ---
    review["decision"] = decision
    review["decided_at"] = iso_logical(now)
    review["reviewer_landlord_id"] = uid
    review["release_of_assignor"] = release_of_assignor
    touch(review)

    if decision == "GRANTED":
        # Express grant: drive transfer to CONSENT_GRANTED
        transfer["status"] = "CONSENT_GRANTED"
        grant_consent(transfer, lease, release_of_assignor)

    elif decision == "GRANTED_WITH_CONDITIONS":
        # Create conditions
        conditions = body.get("conditions", [])
        review["conditions_imposed_count"] = len(conditions)
        for cond_spec in conditions:
            cond = {
                "id": new_id(),
                "consent_review_id": review["id"],
                "condition_kind": cond_spec["condition_kind"],
                "detail": cond_spec["detail"],
                "status": "PENDING",
                "responded_at": None,
            }
            new_common(cond)
            store.consent_conditions[cond["id"]] = cond
        # Transfer moves to/stays in CONSENT_PENDING
        if transfer["status"] == "SUBMITTED":
            transfer["status"] = "CONSENT_PENDING"
            touch(transfer)

    elif decision == "DENIED":
        review["denial_reason_code"] = body["denial_reason_code"]
        transfer["status"] = "CONSENT_DENIED"
        touch(transfer)
        decrement_lease_open_count(lease)

    return ok(review)


# ---------------------------------------------------------------------------
# ConsentReview — rescind
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/consent-reviews/<review_id>/rescind")
def rescind_consent_review(review_id):
    uid, role, _ = get_context()
    require_roles(["Landlord"])
    review = require_path_entity(store.consent_reviews, review_id)
    transfer = store.transfer_requests.get(review["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent transfer not found")
    lease = store.leases[transfer["lease_id"]]

    # State: review must be GRANTED_WITH_CONDITIONS
    if review["decision"] != "GRANTED_WITH_CONDITIONS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Rescind requires the review to be GRANTED_WITH_CONDITIONS")

    # Transfer must still be CONSENT_PENDING (consent not yet joined)
    if transfer["status"] != "CONSENT_PENDING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Transfer is no longer in CONSENT_PENDING")

    # Duty segregation: caller must be the lease's landlord
    if uid != lease["landlord_party_id"]:
        raise ApiError("ERR_DUTY_SEGREGATION", 403,
                       "Only the lease's landlord of record may rescind")

    # At least one condition must be REJECTED
    conditions = get_conditions_for_review(review["id"])
    if not any(c["status"] == "REJECTED" for c in conditions):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Rescission requires at least one REJECTED condition")

    # Apply rescission
    now = db.LOGICAL_CLOCK
    review["decision"] = "RESCINDED"
    review["rescinded_at"] = iso_logical(now)
    touch(review)

    transfer["status"] = "RESCINDED"
    touch(transfer)
    decrement_lease_open_count(lease)

    # Void any open recognition agreements
    from domain import void_recognition_agreements
    void_recognition_agreements(transfer)

    return ok(review)


# ---------------------------------------------------------------------------
# ConsentReview — conditions list
# ---------------------------------------------------------------------------

@bp.get("/sublease-admin/consent-reviews/<review_id>/conditions")
def get_review_conditions(review_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    require_path_entity(store.consent_reviews, review_id)
    rows = get_conditions_for_review(review_id)
    return ok(paginate(rows), rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# ConsentCondition — respond
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/consent-conditions/<condition_id>/respond")
def respond_to_condition(condition_id):
    uid, role, _ = get_context()
    require_roles(["Tenant"])
    body = parse_body({
        "response": ("enum", True, ["ACCEPTED", "REJECTED"]),
    }, allow_empty=False)

    condition = require_path_entity(store.consent_conditions, condition_id)
    review = store.consent_reviews.get(condition["consent_review_id"])
    if review is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent consent review not found")
    transfer = store.transfer_requests.get(review["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent transfer not found")
    lease = store.leases[transfer["lease_id"]]

    # State: condition must be PENDING
    if condition["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Condition is no longer PENDING")

    # Parent review must be GRANTED_WITH_CONDITIONS
    if review["decision"] != "GRANTED_WITH_CONDITIONS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Parent review is no longer GRANTED_WITH_CONDITIONS")

    # Duty segregation: caller must be the lease's tenant
    if uid != lease["tenant_party_id"]:
        raise ApiError("ERR_DUTY_SEGREGATION", 403,
                       "Only the lease's tenant of record may respond to conditions")

    # Apply response
    now = db.LOGICAL_CLOCK
    condition["status"] = body["response"]
    condition["responded_at"] = iso_logical(now)
    touch(condition)

    # Conditional-acceptance join: when ALL conditions are ACCEPTED
    if body["response"] == "ACCEPTED":
        all_conditions = get_conditions_for_review(review["id"])
        if all(c["status"] == "ACCEPTED" for c in all_conditions):
            # Fire the join: transfer CONSENT_PENDING -> CONSENT_GRANTED
            if transfer["status"] == "CONSENT_PENDING":
                transfer["status"] = "CONSENT_GRANTED"
                grant_consent(transfer, lease, review.get("release_of_assignor", False))

    return ok(condition)


# ---------------------------------------------------------------------------
# ConsentCondition — read
# ---------------------------------------------------------------------------

@bp.get("/sublease-admin/consent-conditions/<condition_id>")
def get_condition(condition_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    return ok(require_path_entity(store.consent_conditions, condition_id))


# ---------------------------------------------------------------------------
# CreditReview — read
# ---------------------------------------------------------------------------

@bp.get("/sublease-admin/credit-reviews/<review_id>")
def get_credit_review_by_id(review_id):
    uid, role, _ = get_context()
    require_roles(ADMIN_READ)
    return ok(require_path_entity(store.credit_reviews, review_id))


# ---------------------------------------------------------------------------
# CreditReview — attest
# ---------------------------------------------------------------------------

@bp.post("/sublease-admin/credit-reviews/<review_id>/attest")
def attest_credit_review(review_id):
    uid, role, _ = get_context()
    require_roles(["TenantRepBroker"])
    body = parse_body({
        "reviewed_credit_rating_bps": ("integer", True, None),
    }, allow_empty=False)

    credit = require_path_entity(store.credit_reviews, review_id)
    transfer = store.transfer_requests.get(credit["transfer_request_id"])
    if transfer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Parent transfer not found")

    # State: credit review must be PENDING
    if credit["outcome"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Credit review is no longer PENDING")

    # Duty segregation: attesting broker must differ from originating broker
    if uid == transfer["broker_user_id"]:
        raise ApiError("ERR_DUTY_SEGREGATION", 403,
                       "The originating broker may not attest the credit review")

    rating = body["reviewed_credit_rating_bps"]
    if rating < 0 or rating > 10000:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "reviewed_credit_rating_bps must be between 0 and 10000")

    # Apply attestation
    now = db.LOGICAL_CLOCK
    credit["reviewed_credit_rating_bps"] = rating
    credit["attesting_broker_user_id"] = uid
    credit["attested_at"] = iso_logical(now)
    credit["outcome"] = "PASS" if rating >= credit["minimum_pass_bps"] else "FAIL"
    touch(credit)

    # Drive transfer SUBMITTED -> CONSENT_PENDING
    if transfer["status"] == "SUBMITTED":
        transfer["status"] = "CONSENT_PENDING"
        touch(transfer)

    return ok(credit)

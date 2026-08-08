"""Claim submission gating: validation-priority conflicts, allowance boundary,
cross-entity subscription dependency, the compensating claims_used ledger, and
documentation / archive / segregation-of-duties corners.
"""
from test_helpers import (
    validate_success, validate_error,
    make_household_owner_headers, make_concierge_headers,
    setup_household_with_active_subscription, setup_refund_claim_under_review,
    new_product, new_claim, add_document, submit_claim,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _basic_with_allowance_used(used=2, serial=1, model="P1"):
    """BASIC household with an ACTIVE subscription and `used` submitted claims on one
    product (claims_used == used). Returns dict(mfr, hh, owner, sub, prod)."""
    ctx = setup_household_with_active_subscription(tier="BASIC")
    prod = new_product(ctx["hh"]["id"], ctx["owner"]["id"], ctx["mfr"]["id"],
                       model_number=model, serial_number=serial,
                       purchase_price_cents=10000, warranty_months=24)
    for i in range(used):
        c = new_claim(prod["id"], ctx["owner"]["id"])
        add_document(c["id"], ctx["owner"]["id"], file_uri=f"s3://r/{model}-{i}")
        submit_claim(c["id"], ctx["owner"]["id"])
    ctx["prod"] = prod
    return ctx


# ─── Difficulty: priority-pair conflict {state, business_fiscal} ──────────────
def test_submit_archived_beats_allowance_returns_product_archived(api):
    """PRD 3.6: "First, the product must still be `REGISTERED`; submitting against an
    archived product is rejected with `ERR_PRODUCT_ARCHIVED`."
    PRD 3.6: "submission enforces four business preconditions, and where more than one
    fails the earlier one in this list is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/submit_archived_state_beats_allowance_fiscal
    """
    ctx = _basic_with_allowance_used(used=2)
    owner = ctx["owner"]
    p3 = new_product(ctx["hh"]["id"], owner["id"], ctx["mfr"]["id"], model_number="P3",
                     serial_number=3, purchase_price_cents=10000, warranty_months=24)
    validate_success(api.archive_product(p3["id"], make_household_owner_headers(owner["id"])), 200)
    c3 = new_claim(p3["id"], owner["id"])
    add_document(c3["id"], owner["id"], file_uri="s3://r/9c")
    res = api.submit_claim(c3["id"], make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_PRODUCT_ARCHIVED")


def test_submit_archived_beats_allowance_leaves_claim_draft(api):
    """PRD 3.6: "First, the product must still be `REGISTERED`; submitting against an
    archived product is rejected with `ERR_PRODUCT_ARCHIVED`."

    Design: Difficulty/priority_pair_validation_conflict/submit_archived_state_beats_allowance_fiscal
    """
    ctx = _basic_with_allowance_used(used=2)
    owner = ctx["owner"]
    p3 = new_product(ctx["hh"]["id"], owner["id"], ctx["mfr"]["id"], model_number="P3",
                     serial_number=3, purchase_price_cents=10000, warranty_months=24)
    validate_success(api.archive_product(p3["id"], make_household_owner_headers(owner["id"])), 200)
    c3 = new_claim(p3["id"], owner["id"])
    add_document(c3["id"], owner["id"], file_uri="s3://r/9c")
    api.submit_claim(c3["id"], make_household_owner_headers(owner["id"]))
    after = validate_success(api.get_claim(c3["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


def test_submit_inactive_beats_allowance_returns_subscription_not_active(api):
    """PRD 3.6: "Then the household's subscription must be `ACTIVE`; a `PAST_DUE` or
    `CANCELLED` subscription blocks the submission with `ERR_SUBSCRIPTION_NOT_ACTIVE`."
    PRD 3.6: "submission enforces four business preconditions, and where more than one
    fails the earlier one in this list is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/submit_inactive_constraint_beats_allowance_fiscal
    """
    ctx = _basic_with_allowance_used(used=2)
    owner = ctx["owner"]
    validate_success(api.mark_past_due(ctx["sub"]["id"], ADMIN), 200)
    c3 = new_claim(ctx["prod"]["id"], owner["id"])
    add_document(c3["id"], owner["id"], file_uri="s3://r/10c")
    res = api.submit_claim(c3["id"], make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_SUBSCRIPTION_NOT_ACTIVE")


def test_submit_inactive_beats_allowance_leaves_claim_draft(api):
    """PRD 3.6: "Then the household's subscription must be `ACTIVE`; a `PAST_DUE` or
    `CANCELLED` subscription blocks the submission with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/submit_inactive_constraint_beats_allowance_fiscal
    """
    ctx = _basic_with_allowance_used(used=2)
    owner = ctx["owner"]
    validate_success(api.mark_past_due(ctx["sub"]["id"], ADMIN), 200)
    c3 = new_claim(ctx["prod"]["id"], owner["id"])
    add_document(c3["id"], owner["id"], file_uri="s3://r/10c")
    api.submit_claim(c3["id"], make_household_owner_headers(owner["id"]))
    after = validate_success(api.get_claim(c3["id"], ADMIN), 200)
    assert after["status"] == "DRAFT"


# ─── Difficulty: allowance >= boundary ────────────────────────────────────────
def test_claim_allowance_boundary_third_submit_rejected(api):
    """PRD 3.6: "if `claims_used` has already reached the tier's included-claims
    ceiling (2 for `BASIC`, 5 for `PLUS`, 20 for `PREMIUM`), the submission is rejected
    with `ERR_CLAIM_ALLOWANCE_EXCEEDED`; allowance remains only while `claims_used` is
    strictly below that ceiling."

    Design: Difficulty/boundary_precision_check/claim_allowance_ge_boundary_on_submit
    """
    ctx = _basic_with_allowance_used(used=2)
    owner = ctx["owner"]
    c3 = new_claim(ctx["prod"]["id"], owner["id"])
    add_document(c3["id"], owner["id"], file_uri="s3://r/11c")
    res = api.submit_claim(c3["id"], make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_CLAIM_ALLOWANCE_EXCEEDED")


def test_claim_allowance_boundary_claims_used_stays_two(api):
    """PRD 3.6: "allowance remains only while `claims_used` is strictly below that
    ceiling."

    Design: Difficulty/boundary_precision_check/claim_allowance_ge_boundary_on_submit
    """
    ctx = _basic_with_allowance_used(used=2)
    owner = ctx["owner"]
    c3 = new_claim(ctx["prod"]["id"], owner["id"])
    add_document(c3["id"], owner["id"], file_uri="s3://r/11c")
    api.submit_claim(c3["id"], make_household_owner_headers(owner["id"]))
    sub = validate_success(api.get_subscription(ctx["sub"]["id"], ADMIN), 200)
    assert sub["claims_used"] == 2


# ─── Difficulty: cross-entity claim submit depends on subscription ACTIVE ─────
def test_claim_submit_blocked_while_past_due(api):
    """PRD 3.2: "because a claim can be submitted only while the household's
    subscription is `ACTIVE`, a lapse blocks new submissions (see Section 3.6)."
    PRD 3.6: "Then the household's subscription must be `ACTIVE`; a `PAST_DUE` or
    `CANCELLED` subscription blocks the submission with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_depends_on_subscription_active
    """
    ctx = setup_household_with_active_subscription(tier="BASIC")
    owner = ctx["owner"]
    prod = new_product(ctx["hh"]["id"], owner["id"], ctx["mfr"]["id"], model_number="CX-1",
                       serial_number=1, purchase_price_cents=10000, warranty_months=24)
    claim = new_claim(prod["id"], owner["id"])
    add_document(claim["id"], owner["id"])
    validate_success(api.mark_past_due(ctx["sub"]["id"], ADMIN), 200)
    res = api.submit_claim(claim["id"], make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_SUBSCRIPTION_NOT_ACTIVE")


def test_claim_submit_succeeds_after_reinstate(api):
    """PRD 3.2: "from `PAST_DUE` the `HouseholdOwner` may reinstate it back to
    `ACTIVE`."
    PRD 3.6: "A successful first submission sets the claim to `SUBMITTED`, increments
    the subscription's `claims_used` by one, and recomputes `active_claim_count`."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_depends_on_subscription_active
    """
    ctx = setup_household_with_active_subscription(tier="BASIC")
    owner = ctx["owner"]
    prod = new_product(ctx["hh"]["id"], owner["id"], ctx["mfr"]["id"], model_number="CX-1",
                       serial_number=1, purchase_price_cents=10000, warranty_months=24)
    claim = new_claim(prod["id"], owner["id"])
    add_document(claim["id"], owner["id"])
    validate_success(api.mark_past_due(ctx["sub"]["id"], ADMIN), 200)
    api.submit_claim(claim["id"], make_household_owner_headers(owner["id"]))
    validate_success(api.reinstate_subscription(ctx["sub"]["id"],
                                                make_household_owner_headers(owner["id"])), 200)
    resubmitted = validate_success(
        api.submit_claim(claim["id"], make_household_owner_headers(owner["id"])), 200)
    assert resubmitted["status"] == "SUBMITTED"
    sub = validate_success(api.get_subscription(ctx["sub"]["id"], ADMIN), 200)
    assert sub["claims_used"] == 1


# ─── Difficulty: compensating invariant claims_used (submit then withdraw) ────
def test_withdraw_moves_claim_to_withdrawn(api):
    """PRD 3.6: "Withdrawal is defined from `SUBMITTED`, `UNDER_REVIEW`, or
    `NEEDS_DOCS`, and moves the claim to the terminal `WITHDRAWN` state; each of these
    pre-approval withdrawals decrements the subscription's `claims_used` by one (the
    compensating half of the allowance ledger) and recomputes `active_claim_count`."

    Design: Difficulty/compensating_invariant/claims_used_conserved_by_submit_then_withdraw
    """
    ctx = setup_household_with_active_subscription(tier="BASIC")
    owner = ctx["owner"]
    prod = new_product(ctx["hh"]["id"], owner["id"], ctx["mfr"]["id"], model_number="CN-1",
                       serial_number=1, purchase_price_cents=10000, warranty_months=24)
    claim = new_claim(prod["id"], owner["id"])
    add_document(claim["id"], owner["id"])
    submit_claim(claim["id"], owner["id"])
    withdrawn = validate_success(
        api.withdraw_claim(claim["id"], make_household_owner_headers(owner["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"


def test_withdraw_restores_claims_used_to_zero(api):
    """PRD 3.2: "It is incremented by one when a claim is first submitted and
    decremented by one when a claim is withdrawn before approval (that is, withdrawn
    out of `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_DOCS`); it never drops below zero."

    Design: Difficulty/compensating_invariant/claims_used_conserved_by_submit_then_withdraw
    """
    ctx = setup_household_with_active_subscription(tier="BASIC")
    owner = ctx["owner"]
    prod = new_product(ctx["hh"]["id"], owner["id"], ctx["mfr"]["id"], model_number="CN-1",
                       serial_number=1, purchase_price_cents=10000, warranty_months=24)
    claim = new_claim(prod["id"], owner["id"])
    add_document(claim["id"], owner["id"])
    submit_claim(claim["id"], owner["id"])
    api.withdraw_claim(claim["id"], make_household_owner_headers(owner["id"]))
    sub = validate_success(api.get_subscription(ctx["sub"]["id"], ADMIN), 200)
    assert sub["claims_used"] == 0


# ─── Corner: documentation, archive-with-active-claim, segregation of duties ──
def test_submit_without_documentation_returns_error(api):
    """PRD 3.6: "Next, at least one qualifying `ClaimDocument` must exist for the
    claim, else `ERR_MISSING_DOCUMENTATION`."

    Design: Corner/validations/submit_without_documentation_returns_error
    """
    ctx = setup_household_with_active_subscription(tier="BASIC")
    owner = ctx["owner"]
    prod = new_product(ctx["hh"]["id"], owner["id"], ctx["mfr"]["id"], model_number="V-1",
                       serial_number=1, purchase_price_cents=100, warranty_months=24)
    claim = new_claim(prod["id"], owner["id"])
    res = api.submit_claim(claim["id"], make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_MISSING_DOCUMENTATION")


def test_archive_product_with_active_claim_rejected(api):
    """PRD 3.3: "and refused with `ERR_PRODUCT_HAS_ACTIVE_CLAIM` if any claim on the
    product is still in a non-terminal state — that is, in `DRAFT`, `SUBMITTED`,
    `UNDER_REVIEW`, `NEEDS_DOCS`, or `APPROVED`."

    Design: Corner/validations/archive_product_with_active_claim_rejected
    """
    ctx = setup_household_with_active_subscription(tier="BASIC")
    owner = ctx["owner"]
    prod = new_product(ctx["hh"]["id"], owner["id"], ctx["mfr"]["id"], model_number="V-2",
                       serial_number=1, purchase_price_cents=100, warranty_months=24)
    new_claim(prod["id"], owner["id"])  # DRAFT claim on the product
    res = api.archive_product(prod["id"], make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_PRODUCT_HAS_ACTIVE_CLAIM")


def test_same_concierge_review_and_approve_rejected(api):
    """PRD 3.7: "When a `ConciergeAgent` approves or rejects a claim, the system
    compares the acting `X-User-ID` against the claim's `reviewed_by_user_id`; if they
    are equal the decision is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/sod_same_concierge_review_and_approve_rejected
    """
    ctx = setup_refund_claim_under_review(tier="BASIC", purchase_price_cents=10000,
                                          warranty_months=24, reviewer_id="cx-1")
    res = api.approve_claim(ctx["claim"]["id"], make_concierge_headers("cx-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

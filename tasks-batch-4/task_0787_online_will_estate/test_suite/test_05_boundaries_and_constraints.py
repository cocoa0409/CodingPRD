"""Boundary precision (allocation cap, empty-beneficiary set) and single-rule
business-constraint violations that map to specific error codes.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    make_active_subscription, add_beneficiary, generate_document, make_completed_questionnaire,
    setup_plan, set_clock, register_member, create_pending_subscription, activate,
    make_member_headers, partial_answers, create_questionnaire_payload, NOTARY,
)


# ─── Difficulty: boundary_precision_check / allocation_sum_at_100_boundary ─
def test_allocation_sum_exactly_100_accepted(api):
    """PRD §3.9: "When adding a beneficiary, the sum of `allocation_pct` across all
    non-contingent beneficiaries including the new one must not exceed 100.00 — exactly
    100.00 is allowed, and anything above it is rejected with `ERR_ALLOCATION_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/allocation_sum_at_100_boundary
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    add_beneficiary(sub["id"], hdr, full_name="B60", allocation_pct=60)
    res = api.create_beneficiary(
        {"subscription_id": sub["id"], "full_name": "B40",
         "relationship": "CHILD", "allocation_pct": 40}, hdr)
    validate_success(res, 201)  # total exactly 100.00 is allowed


def test_allocation_sum_over_100_rejected(api):
    """PRD §3.9: "exactly 100.00 is allowed, and anything above it is rejected with
    `ERR_ALLOCATION_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/allocation_sum_at_100_boundary
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    add_beneficiary(sub["id"], hdr, full_name="B60", allocation_pct=60)
    add_beneficiary(sub["id"], hdr, full_name="B40", allocation_pct=40)
    res = api.create_beneficiary(
        {"subscription_id": sub["id"], "full_name": "BOver",
         "relationship": "OTHER", "allocation_pct": 0.01}, hdr)
    validate_error(res, "ERR_ALLOCATION_EXCEEDED")  # total 100.01 > 100.00


# ─── Difficulty: boundary_precision_check / execute_will_zero_beneficiaries_empty_set ─
def test_execute_will_with_zero_beneficiaries_rejected(api):
    """PRD §3.8: "Additionally, executing a `WILL` requires that the subscription have
    at least one non-contingent `Beneficiary`; executing a will with zero non-contingent
    beneficiaries is rejected with `ERR_NO_BENEFICIARIES`."

    Design: Difficulty/boundary_precision_check/execute_will_zero_beneficiaries_empty_set
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    _q, doc = generate_document(sub["id"], hdr, "WILL", "CA")
    res = api.execute_document(doc["id"], {"witnesses_count": 2}, NOTARY)
    validate_error(res, "ERR_NO_BENEFICIARIES")


def test_execute_will_zero_beneficiaries_status_unchanged(api):
    """PRD §3.8: "executing a will with zero non-contingent beneficiaries is rejected
    with `ERR_NO_BENEFICIARIES`." (No transition occurs, so the document stays
    `GENERATED`.)

    Design: Difficulty/boundary_precision_check/execute_will_zero_beneficiaries_empty_set
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    _q, doc = generate_document(sub["id"], hdr, "WILL", "CA")
    api.execute_document(doc["id"], {"witnesses_count": 2}, NOTARY)
    after = validate_success(api.get_document(doc["id"], hdr), 200)
    assert after["status"] == "GENERATED"


# ─── Corner: validations / renew_before_window_returns_window_not_open ───
def test_renew_before_window_returns_window_not_open(api):
    """PRD §3.3: "Initiating too early (before the 30-day window opens) is rejected with
    `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 422)".

    Design: Corner/validations/renew_before_window_returns_window_not_open
    """
    member, sub, hdr = make_active_subscription(
        plan_tier="PLUS", base_price_cents=20000, clock="2026-06-01T00:00:00Z")
    set_clock("2026-07-01T00:00:00Z")
    res = api.renew_subscription(sub["id"], hdr)
    validate_error(res, "ERR_RENEWAL_WINDOW_NOT_OPEN")
    after = validate_success(api.get_subscription(sub["id"], hdr), 200)
    assert after["renewal_pending"] is False


# ─── Corner: validations / generate_trust_not_in_plan_returns_error ──────
def test_generate_trust_without_allows_trust_returns_error(api):
    """PRD §3.6: "The requested `document_type` must be among the plan's
    `included_document_types`, and a `TRUST` additionally requires the plan's
    `allows_trust` to be true; otherwise the request is rejected with
    `ERR_DOCUMENT_TYPE_NOT_IN_PLAN`."

    Design: Corner/validations/generate_trust_not_in_plan_returns_error
    """
    setup_plan(plan_tier="BASIC", base_price_cents=10000,
               included_document_types=["WILL", "TRUST"], max_documents=10, allows_trust=False)
    set_clock("2026-06-01T00:00:00Z")
    member = register_member(email="trust@example.com")
    hdr = make_member_headers(member["id"])
    sub = create_pending_subscription(member["id"], plan_tier="BASIC")
    sub = activate(sub["id"])
    q = make_completed_questionnaire(sub["id"], hdr, "TRUST", "CA")
    res = api.create_document({"questionnaire_id": q["id"]}, hdr)
    validate_error(res, "ERR_DOCUMENT_TYPE_NOT_IN_PLAN")


# ─── Corner: validations / execute_insufficient_witnesses_returns_error ──
def test_execute_with_insufficient_witnesses_returns_error(api):
    """PRD §3.8: "The notary supplies a `witnesses_count`, which must be at least the
    document's `witness_count_required`; a shortfall is rejected with
    `ERR_WITNESS_REQUIREMENT_NOT_MET`."

    Design: Corner/validations/execute_insufficient_witnesses_returns_error
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    add_beneficiary(sub["id"], hdr, allocation_pct=100)
    _q, doc = generate_document(sub["id"], hdr, "WILL", "CA")  # CA WILL requires 2
    res = api.execute_document(doc["id"], {"witnesses_count": 1}, NOTARY)
    validate_error(res, "ERR_WITNESS_REQUIREMENT_NOT_MET")
    after = validate_success(api.get_document(doc["id"], hdr), 200)
    assert after["status"] == "GENERATED"


# ─── Corner: validations / submit_review_without_addon_returns_error ─────
def test_submit_review_without_attorney_support_returns_error(api):
    """PRD §3.7: "A `Member` whose subscription carries the `attorney_support` add-on
    may submit a `GENERATED` document for attorney review. Submitting requires that
    add-on: without it, the submission is rejected with
    `ERR_ATTORNEY_SUPPORT_NOT_ENABLED`."

    Design: Corner/validations/submit_review_without_addon_returns_error
    """
    member, sub, hdr = make_active_subscription(
        plan_tier="PLUS", base_price_cents=20000, attorney_support=False)
    _q, doc = generate_document(sub["id"], hdr, "WILL", "CA")
    res = api.submit_review(doc["id"], hdr)
    validate_error(res, "ERR_ATTORNEY_SUPPORT_NOT_ENABLED")
    after = validate_success(api.get_document(doc["id"], hdr), 200)
    assert after["status"] == "GENERATED"


# ─── Corner: validations / generate_incomplete_questionnaire_returns_error ─
def test_generate_from_incomplete_questionnaire_returns_error(api):
    """PRD §3.6: "The source intake must be `COMPLETED` (its `completeness_pct` at 100),
    or the request is rejected with `ERR_QUESTIONNAIRE_INCOMPLETE`."

    Design: Corner/validations/generate_incomplete_questionnaire_returns_error
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    q = get_success_data(api.create_questionnaire(
        create_questionnaire_payload(sub["id"], document_type="WILL", state_code="CA"), hdr))
    get_success_data(api.submit_answers(q["id"], {"answers": partial_answers(3)}, hdr))
    res = api.create_document({"questionnaire_id": q["id"]}, hdr)
    validate_error(res, "ERR_QUESTIONNAIRE_INCOMPLETE")


# ─── Corner: validations / subscribe_unknown_plan_returns_plan_not_found ─
def test_subscribe_to_unknown_plan_returns_plan_not_found(api):
    """PRD §3.2: "A `Member` opens a subscription by naming the `member_id` of the
    account holder and a `plan_tier` that must match an existing catalog row — a tier
    with no catalog entry is rejected with `ERR_PLAN_NOT_FOUND`."

    Design: Corner/validations/subscribe_unknown_plan_returns_plan_not_found
    """
    setup_plan(plan_tier="PLUS", base_price_cents=20000, included_document_types=["WILL"])
    member = register_member(email="noplan@example.com")
    hdr = make_member_headers(member["id"])
    res = api.create_subscription(
        {"member_id": member["id"], "plan_tier": "PREMIER", "bundle_type": "INDIVIDUAL"}, hdr)
    validate_error(res, "ERR_PLAN_NOT_FOUND")

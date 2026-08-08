"""Installment plans, hardship waivers, overpayment guard, and plan-terms error precedence.

Covers corner calculations (installment, hardship tiers), corner validation (overpayment),
and difficulty rule priority_pair_validation_conflict (plan_terms_vs_downpayment).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    setup_owner_vehicle_case, setup_case_with_violations, file_violation,
    get_case, case_version, make_owner_headers,
    create_payment_plan_payload,
)

EO = TEST_USERS["enforcement_officer_headers"]
COLLECTIONS = TEST_USERS["collections_admin_headers"]


# ─── corner: installment amount ────────────────────────────────────────────

def test_installment_amount_and_paid_to_date_computed(api):
    """PRD §3.5: "On creation the plan enters ACTIVE, its installment_amount_cents is set
    to the total minus the down payment, divided by the installment count, rounded half up,
    and its paid_to_date_cents is initialized to the down payment."

    Design: Corner/calculations/installment_amount_computed_correctly
    """
    owner, _, case, _ = setup_case_with_violations(2, 30000)
    ver = case_version(case["id"])
    payload = create_payment_plan_payload(
        ver, total_amount_cents=100000, installment_count=9, down_payment_cents=10000)
    plan = validate_success(api.create_payment_plan(
        case["id"], payload, make_owner_headers(owner["id"])), 201)
    assert plan["installment_amount_cents"] == 10000  # round_half_up(90000/9)
    assert plan["paid_to_date_cents"] == 10000
    assert plan["status"] == "ACTIVE"


# ─── corner: hardship TIER_2 full forgiveness ──────────────────────────────

def test_tier2_waiver_forgives_full_due_and_marks_waived(api):
    """PRD §3.8: "Under TIER_2 (full forgiveness, corresponding to HARDSHIP_TIER_2_PCT of
    100%), approved_amount_cents equals the sum of the current due of every outstanding
    citation, and each such citation is moved to WAIVED (OUTSTANDING → WAIVED)."

    Design: Corner/calculations/hardship_tier2_full_waiver_marks_waived
    """
    owner, _, case, _ = setup_case_with_violations(0, 0)
    violation = file_violation(case["id"], fine_amount_cents=20000, violation_type="NO_PERMIT")
    waiver = validate_success(api.create_hardship_waiver(
        case["id"], {"hardship_tier": "TIER_2", "requested_amount_cents": 20000},
        make_owner_headers(owner["id"])), 201)
    decided = validate_success(api.decide_hardship_waiver(
        waiver["id"], {"approve": True}, COLLECTIONS), 200)
    assert decided["status"] == "APPROVED"
    assert decided["approved_amount_cents"] == 20000
    assert validate_success(api.get_violation(violation["id"], EO), 200)["status"] == "WAIVED"
    assert get_case(case["id"])["collectible_balance_cents"] == 0


# ─── corner: hardship TIER_1 partial credit ────────────────────────────────

def test_tier1_waiver_credits_half_and_keeps_outstanding(api):
    """PRD §3.8: "Under TIER_1 (partial forgiveness, corresponding to HARDSHIP_TIER_1_PCT
    of 50%), each outstanding citation receives a credit equal to half of its own current
    due, rounded half up per citation, added to that citation's credit_cents;
    approved_amount_cents is the sum of those per-citation rounded credits, and the
    citations remain OUTSTANDING (their reduced current due simply falls)."

    Design: Corner/calculations/hardship_tier1_partial_credit
    """
    owner, _, case, _ = setup_case_with_violations(0, 0)
    violation = file_violation(case["id"], fine_amount_cents=20000, violation_type="NO_PERMIT")
    waiver = validate_success(api.create_hardship_waiver(
        case["id"], {"hardship_tier": "TIER_1", "requested_amount_cents": 10000},
        make_owner_headers(owner["id"])), 201)
    decided = validate_success(api.decide_hardship_waiver(
        waiver["id"], {"approve": True}, COLLECTIONS), 200)
    assert decided["approved_amount_cents"] == 10000  # round_half_up(20000*0.50)
    v = validate_success(api.get_violation(violation["id"], EO), 200)
    assert v["status"] == "OUTSTANDING"
    assert v["credit_cents"] == 10000
    assert get_case(case["id"])["collectible_balance_cents"] == 10000


# ─── corner: overpayment ───────────────────────────────────────────────────

def test_overpayment_exceeding_collectible_rejected(api):
    """PRD §3.4: "The total payment may not exceed the case's collectible balance: a
    payment that would leave money unallocated after every candidate is exhausted is
    rejected in whole with ERR_OVERPAYMENT (HTTP 422) — there is no partial commit."

    Design: Corner/validations/overpayment_rejected
    """
    owner, _, case = setup_owner_vehicle_case()
    file_violation(case["id"], fine_amount_cents=10000)
    res = api.create_payment(
        case["id"], {"amount_cents": 20000, "method": "CARD"},
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_OVERPAYMENT", expected_status=422)


# ─── difficulty: plan_terms_vs_downpayment precedence ──────────────────────

def _plan_conflict(api, owner, case):
    """installment_count 20 (> 12) AND down_payment 0 (< 10%) both fail."""
    ver = case_version(case["id"])
    payload = create_payment_plan_payload(
        ver, total_amount_cents=100000, installment_count=20, down_payment_cents=0)
    return api.create_payment_plan(case["id"], payload, make_owner_headers(owner["id"]))


def test_plan_terms_error_wins_over_downpayment(api):
    """PRD §2.9: "then the domain-specific business rules — temporal windows, capacity,
    uniqueness, plan terms, separation of duties, fiscal thresholds, release conditions"
    PRD §3.5: "The installment_count must be between 1 and PAYMENT_PLAN_MAX_INSTALLMENTS,
    which is 12; a count outside that range is rejected with ERR_INVALID_PLAN_TERMS
    (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/plan_terms_vs_downpayment
    """
    owner, _, case, _ = setup_case_with_violations(2, 30000)
    res = _plan_conflict(api, owner, case)
    validate_error(res, "ERR_INVALID_PLAN_TERMS", expected_status=422)


def test_plan_conflict_creates_no_plan(api):
    """PRD §3.5: "The down payment must be at least PAYMENT_PLAN_MIN_DOWN_PCT (0.10, i.e.
    10%) of the total amount; too small a down payment is rejected with
    ERR_INSUFFICIENT_DOWN_PAYMENT (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/plan_terms_vs_downpayment
    """
    owner, _, case, _ = setup_case_with_violations(2, 30000)
    _plan_conflict(api, owner, case)
    data, meta = validate_paginated(api.list_payment_plans(
        COLLECTIONS, params={"scofflaw_case_id": case["id"]}))
    assert meta["total_count"] == 0
    assert data == []

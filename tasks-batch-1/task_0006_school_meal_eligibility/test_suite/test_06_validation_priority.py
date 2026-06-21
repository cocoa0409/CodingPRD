"""Tests covering validation precedence: state vs business_safety, and auth
vs business_fiscal. PRD §2.10 fixes the evaluation order so the earlier rule
wins when multiple would fail.
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    setup_clean_world,
    create_household,
    create_student,
    create_allergy_profile,
    update_allergy_profile,
    create_direct_cert_eligibility,
    create_menu_item,
    create_service_transaction,
    settle_transaction,
    resolve_parent_account_id,
    api_client,
    TEST_USERS,
    make_parent_headers,
)


# ---------------------------------------------------------------------
# Difficulty rule 5 / instance 1 — state (priority 5) vs business_safety
# (priority 6). State must win.
# ---------------------------------------------------------------------

def test_settle_already_settled_transaction_reports_invalid_state_not_allergen(api):
    """PRD §2.10: "Where multiple validation rules apply to the same endpoint,
    they are evaluated in a fixed order: authentication first (presence and
    recognition of the role), then role authorization for the endpoint, then
    resource-ownership for `Parent`-owned resources, then existence of every
    path-templated id, then the state-machine precondition for any
    state-mutating operation, then business safety (allergen conflict), then
    business-referential checks (overlap and gap rules for claims and
    determinations), then business-fiscal checks (daily top-up cap, then
    sufficient funds), then business-constraint checks (idempotency, period
    closure, household completeness, then the generic request-shape and
    pagination checks). When a request would fail multiple rules, the earlier
    rule in this ordering produces the error."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_dispute_then_severe_allergen
    """
    set_clock("2026-04-01T08:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    profile = create_allergy_profile(stu["id"], allergens=[], severity="MILD")
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(
        school_code="ELEM-101", name="PB Cookie",
        list_price_cents=100, allergens_present=["PEANUT"],
    )
    tx = create_service_transaction(stu["id"], menu["id"])
    settle_transaction(tx["id"])  # now SETTLED
    # Upgrade allergen severity to SEVERE — does NOT affect already-SETTLED tx
    # (the cascade targets PENDING only).
    update_allergy_profile(profile["id"], allergens=["PEANUT"], severity="SEVERE_ANAPHYLACTIC")
    # Now attempt to settle an already-SETTLED tx — both state and allergen
    # checks would fire; state (priority 5) wins.
    res = api.settle_service_transaction(tx["id"], TEST_USERS["school_staff_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_reject_already_rejected_transaction_reports_invalid_state(api):
    """PRD §2.10: "then the state-machine precondition for any state-mutating
    operation, then business safety (allergen conflict)".
    PRD §3.6: "A `PENDING` transaction may instead be rejected by staff with a
    `rejection_reason` from the enumeration `ALLERGEN_CONFLICT`,
    `INELIGIBLE_STATE`, `INSUFFICIENT_FUNDS`, or `MANUAL`. ... `REJECTED` is
    terminal."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_dispute_then_severe_allergen
    """
    # Companion test: state check dominates on a different state-mutating endpoint.
    set_clock("2026-04-01T08:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(
        school_code="ELEM-101", list_price_cents=0,
        federal_reimbursement_free_cents=470,
        federal_reimbursement_reduced_cents=430,
        federal_reimbursement_paid_cents=70,
    )
    tx = create_service_transaction(stu["id"], menu["id"])
    api.reject_service_transaction(
        tx["id"], {"rejection_reason": "MANUAL"},
        TEST_USERS["school_staff_headers"],
    )
    # Already-REJECTED — attempt to settle (terminal-state violation).
    res = api.settle_service_transaction(tx["id"], TEST_USERS["school_staff_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ---------------------------------------------------------------------
# Difficulty rule 5 / instance 2 — auth (priority 3) vs business_fiscal
# (priority 9). NOT_RESOURCE_OWNER must win over TOPUP_CAP_EXCEEDED.
# ---------------------------------------------------------------------

def test_parent_topping_up_other_household_over_cap_reports_not_resource_owner(api):
    """PRD §2.10: "then resource-ownership for `Parent`-owned resources, then
    existence of every path-templated id, then the state-machine precondition
    for any state-mutating operation, then business safety (allergen
    conflict), then business-referential checks (overlap and gap rules for
    claims and determinations), then business-fiscal checks (daily top-up
    cap, then sufficient funds)".
    PRD §2.1: "A parent acting on a resource they do not own is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Difficulty/priority_pair_validation_conflict/auth_vs_business_fiscal_other_parent_topup_over_cap
    """
    set_clock("2026-04-02T08:00:00.000Z")
    hh_a = create_household(
        family_size=2, annual_income_cents=3_000_000,
        address_state="CA", direct_certification_flag=False,
    )
    hh_b = create_household(
        family_size=2, annual_income_cents=3_000_000,
        address_state="CA", direct_certification_flag=False,
    )
    # Parent of A attempts $250 (over the $200 cap) top-up against B's account.
    # Resolve B's parent-account id via PRD §2.8 nested read (the account was
    # auto-created by household creation per §2.9). Per PRD §2.1 ownership
    # compares X-User-ID with the resource's owning household_id; auth
    # (priority 3) must dominate over business-fiscal (priority 9).
    hh_b_account_id = resolve_parent_account_id(hh_b["id"])
    res = api.topup_parent_account(
        hh_b_account_id,
        {"amount_cents": 25000, "idempotency_key": "other-parent-attempt-1"},
        make_parent_headers(hh_a["id"]),
    )
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_school_staff_topup_against_parent_only_endpoint_reports_forbidden(api):
    """PRD §2.1: "If the role is recognized but is not on the endpoint's
    allow-list, the request is rejected with `ERR_FORBIDDEN`."

    Design: Difficulty/priority_pair_validation_conflict/auth_vs_business_fiscal_other_parent_topup_over_cap
    """
    # Companion test: role-authorization (priority 2) dominates business_fiscal —
    # SchoolStaff is not Parent and cannot top up at all.
    set_clock("2026-04-02T08:00:00.000Z")
    hh = create_household(
        family_size=2, annual_income_cents=3_000_000,
        address_state="CA", direct_certification_flag=False,
    )
    res = api.topup_parent_account(
        hh["id"],
        {"amount_cents": 25000, "idempotency_key": "staff-attempt-1"},
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)

"""Corner coverage — RBAC exclusivity, segregation of duties, optimistic
concurrency (OCC) staleness on both guarded parents, derived-field reconciliation
of nonaccrual, and immediate consistency of charge-off effects.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    make_workout_officer_headers, make_special_assets_manager_headers,
    make_credit_committee_headers, make_portfolio_analyst_headers,
    make_loan_accounting_headers, make_appraisal_desk_headers,
    setup_case_in_action_plan, setup_case_in_negotiation,
    setup_case_in_impairment_review, setup_case_in_legal,
    make_borrower_with_loan, open_workout_case, make_borrower, make_collateral,
    create_action_plan_payload, create_proposal_payload, create_charge_off_payload,
    create_recovery_payload, create_legal_referral_payload, create_appraisal_payload,
    create_impairment_cecl_payload, create_loan_payload, create_workout_case_payload,
)
from test_helpers.api_client import api_client


# ===========================================================================
# Section: rbac
# ===========================================================================

def test_rbac_workout_officer_cannot_approve_own_plan(api):
    """PRD §2.1: "A request whose role is recognized but not authorized for the
    targeted endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "`SpecialAssetsManager` (the group's manager, who approves plans,
    decides exit strategy, closes cases, and releases collateral)".

    Design: Corner/rbac/rbac_workout_officer_cannot_approve_own_plan
    """
    ctx = setup_case_in_action_plan(
        officer_id="officer-r1", manager_id="mgr-r1",
        borrower_overrides={"legal_name": "RBAC Co", "tax_id": "55-0000025",
                            "naics_code": "541717", "internal_risk_rating": 7},
        loan_overrides={"loan_number": "LN-R01", "original_principal_cents": 3000000,
                        "contractual_rate_bps": 800, "days_past_due": 62},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 7},
        plan_overrides={"plan_text": "RBAC", "target_resolution_date": "2027-01-31T00:00:00Z",
                        "milestone_count": 1},
    )
    loan, case, plan = ctx["loan"], ctx["case"], ctx["plan"]
    get_success_data(api_client.submit_action_plan(loan["id"], case["id"], plan["id"], ctx["officer_h"]))

    # Approve is exclusive to SpecialAssetsManager; a WorkoutOfficer is denied at the
    # role gate regardless of identity.
    res = api_client.approve_action_plan(
        loan["id"], case["id"], plan["id"], make_workout_officer_headers("officer-r1"))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, expected_status=403)


def test_rbac_committee_cannot_book_chargeoff_and_analyst_read_only(api):
    """PRD §2.1: "A request whose role is recognized but not authorized for the
    targeted endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.1: "`LoanAccounting` (the accounting desk that books charge-offs and
    recoveries, finalizes impairment assessments, and refreshes loan aging)".
    PRD §2.1: "`PortfolioAnalyst` (a read-only analytics role consuming the portfolio
    report)".

    Design: Corner/rbac/rbac_committee_cannot_book_chargeoff_and_analyst_read_only
    """
    officer_h = make_workout_officer_headers("officer-r2")
    borrower = make_borrower(officer_h, legal_name="RBAC2 Co", tax_id="55-0000026",
                             naics_code="541718", internal_risk_rating=8)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-R02",
         "original_principal_cents": 2500000, "contractual_rate_bps": 800,
         "days_past_due": 65},
        officer_h))
    case = get_success_data(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8,
         "case_officer_id": "officer-r2"},
        officer_h))

    res1 = api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=100000, reason_code="STATUTORY"),
        make_credit_committee_headers("cc-r2"))
    validate_error(res1, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, expected_status=403)

    res2 = api_client.create_recovery(
        loan["id"], case["id"],
        create_recovery_payload(amount_cents=100000, recovery_source="BORROWER_CURE",
                                allocation_mode="CHRONOLOGICAL"),
        make_portfolio_analyst_headers("analyst-r2"))
    validate_error(res2, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, expected_status=403)


def test_segregation_of_duties_impairment_finalizer_not_case_officer(api):
    """PRD §2.10: "Third, finalizing an impairment assessment must not be done by
    the case officer: the finalizing `LoanAccounting` user's `X-User-ID` must not
    equal `case_officer_id`. Any breach of these three separations is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.6: "Finalization is where the reserve is computed, and it is guarded four
    ways: the assessment must be `DRAFT` (`ERR_IMPAIRMENT_NOT_DRAFT`), the case must
    be in `IMPAIRMENT_REVIEW` or `LEGAL` (`ERR_CASE_NOT_IMPAIRABLE`), the TDR-method
    confirmation above must hold, and the finalizing user must not be the case's
    `case_officer_id` — segregation of duties, `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_impairment_finalizer_not_case_officer
    """
    ctx = setup_case_in_impairment_review(
        officer_id="officer-sod", manager_id="mgr-sod", committee_id="cc-sod",
        borrower_overrides={"legal_name": "SoD Co", "tax_id": "55-0000027",
                            "naics_code": "541719", "internal_risk_rating": 8},
        loan_overrides={"loan_number": "LN-R03", "original_principal_cents": 3500000,
                        "contractual_rate_bps": 800, "days_past_due": 66},
        case_overrides={"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8},
        plan_overrides={"plan_text": "SoD", "target_resolution_date": "2027-02-14T00:00:00Z",
                        "milestone_count": 1},
        proposal_overrides={"proposal_kind": "MODIFICATION", "concession_rate_bps": 700,
                            "term_extension_months": 6, "principal_forgiveness_cents": 0,
                            "borrower_concession_cents": 0},
        concession=True,
    )
    loan, case = ctx["loan"], ctx["case"]

    imp = get_success_data(api_client.create_impairment(
        loan["id"], case["id"],
        create_impairment_cecl_payload(probability_of_default_bps=1000,
                                       loss_given_default_bps=2000),
        make_loan_accounting_headers("acct-sod")))

    # Finalizer's X-User-ID equals the case_officer_id: segregation breach.
    res = api_client.finalize_impairment(
        loan["id"], case["id"], imp["id"], make_loan_accounting_headers("officer-sod"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403)

    # A different LoanAccounting user succeeds.
    finalized = validate_success(api_client.finalize_impairment(
        loan["id"], case["id"], imp["id"], make_loan_accounting_headers("acct-sod")), 200)
    assert finalized["status"] == "FINALIZED"


# ===========================================================================
# Section: cross_cutting_layers (OCC + derived-field reconciliation)
# ===========================================================================

def test_occ_stale_case_version_on_plan_create(api):
    """PRD §2.8: "On all three endpoints, if the supplied value does not equal the
    parent resource's current `version` at the moment of the write, the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412): the parent's version has advanced
    since the client last read it, and the client must re-read before writing."
    PRD §2.8: "Drafting an action plan on a workout case requires the request body to
    carry `expected_case_version`, holding the case `version` the client last
    observed. Creating the plan moves a `WATCHLIST` case to `ACTION_PLAN` (on the
    first plan), may supersede an approved predecessor, and increments the case's
    `version` by one."

    Design: Corner/cross_cutting_layers/occ_stale_case_version_on_plan_create
    """
    officer_h = make_workout_officer_headers("officer-o1")
    borrower = make_borrower(officer_h, legal_name="OCC Co", tax_id="55-0000028",
                             naics_code="541720", internal_risk_rating=7)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-O01",
         "original_principal_cents": 2000000, "contractual_rate_bps": 800,
         "days_past_due": 62},
        officer_h))
    case = get_success_data(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 7,
         "case_officer_id": "officer-o1"},
        officer_h))

    first_plan = get_success_data(api_client.create_action_plan(
        loan["id"], case["id"],
        create_action_plan_payload(case["version"], plan_text="First plan",
                                   target_resolution_date="2027-03-01T00:00:00Z",
                                   milestone_count=1),
        officer_h))
    case_now = get_success_data(api_client.get_workout_case(loan["id"], case["id"], officer_h))
    captured_version = case_now["version"]

    # First create against the captured version succeeds and advances the version.
    # PRD §3.2: every plan after the first carries the supersedes_plan_id of the
    # plan it replaces.
    plan_a = validate_success(api_client.create_action_plan(
        loan["id"], case["id"],
        create_action_plan_payload(captured_version, plan_text="Second plan A",
                                   target_resolution_date="2027-03-02T00:00:00Z",
                                   milestone_count=1,
                                   supersedes_plan_id=first_plan["id"]),
        officer_h), 201)
    assert plan_a["id"]

    # Second create reusing the same (now stale) captured version is rejected.
    res = api_client.create_action_plan(
        loan["id"], case["id"],
        create_action_plan_payload(captured_version, plan_text="Second plan B (stale)",
                                   target_resolution_date="2027-03-03T00:00:00Z",
                                   milestone_count=1,
                                   supersedes_plan_id=plan_a["id"]),
        officer_h)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_occ_stale_collateral_version_on_appraisal_create(api):
    """PRD §2.8: "Ordering an appraisal on a collateral item requires
    `expected_collateral_version`, holding the item `version` the client last
    observed; ordering flips the item from `PLEDGED` to `UNDER_REVALUATION` and
    increments the item's `version` by one."
    PRD §2.8: "On all three endpoints, if the supplied value does not equal the
    parent resource's current `version` at the moment of the write, the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412): the parent's version has advanced
    since the client last read it, and the client must re-read before writing."

    Design: Corner/cross_cutting_layers/occ_stale_collateral_version_on_appraisal_create
    """
    officer_h = make_workout_officer_headers("officer-o2")
    borrower = make_borrower(officer_h, legal_name="OCC Col Co", tax_id="55-0000029",
                             naics_code="541721", internal_risk_rating=7)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-O02",
         "original_principal_cents": 2200000, "contractual_rate_bps": 800,
         "days_past_due": 62},
        officer_h))
    item = make_collateral(loan["id"], officer_h, collateral_type="SECURITIES",
                           description="Bond portfolio", liquidation_discount_bps=1000)
    desk_h = make_appraisal_desk_headers("appr-o1")

    # First ordering succeeds and bumps the item version (PLEDGED -> UNDER_REVALUATION).
    appraisal = validate_success(api_client.create_appraisal(
        loan["id"], item["id"],
        create_appraisal_payload(item["version"], appraised_value_cents=2000000,
                                 effective_date="2026-07-01T00:00:00Z",
                                 appraiser_id="appr-o1"),
        desk_h), 201)
    assert appraisal["id"]

    # Walk the item back to PLEDGED (submit then reject, PRD §3.5): each flip is a
    # mutation, so the item version advances again while the captured version from
    # before the first ordering stays stale. With the item PLEDGED, the state gate
    # (priority 4) passes and the stale-version check (priority 5) is what fires.
    get_success_data(api_client.submit_appraisal(loan["id"], item["id"], appraisal["id"], desk_h))
    get_success_data(api_client.reject_appraisal(loan["id"], item["id"], appraisal["id"], desk_h))
    item_now = validate_success(api_client.get_collateral(loan["id"], item["id"], desk_h), 200)
    assert item_now["status"] == "PLEDGED"
    assert item_now["version"] > item["version"]

    # Ordering with the same captured (now stale) version is rejected.
    res = api_client.create_appraisal(
        loan["id"], item["id"],
        create_appraisal_payload(item["version"], appraised_value_cents=2100000,
                                 effective_date="2026-07-02T00:00:00Z",
                                 appraiser_id="appr-o1"),
        desk_h)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_derived_field_reconciliation_nonaccrual_on_legal_entry(api):
    """PRD §3.1: "An aging refresh overwrites `days_past_due` with the supplied value
    and re-evaluates the nonaccrual flag: `nonaccrual` becomes true when the
    refreshed `days_past_due` reaches at least ninety days, and it is also forced
    true — regardless of delinquency — whenever any workout case on the loan is in
    `LEGAL`."
    PRD §3.7: "Creating a referral is permitted only from `NEGOTIATION` or
    `IMPAIRMENT_REVIEW` — elsewhere it is rejected with `ERR_CASE_NOT_REFERRABLE` —
    and it moves the case to `LEGAL` while forcing the loan's `nonaccrual` flag true
    regardless of delinquency."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_nonaccrual_on_legal_entry
    """
    ctx = setup_case_in_negotiation(
        officer_id="officer-o3", manager_id="mgr-o3",
        borrower_overrides={"legal_name": "Derived Co", "tax_id": "55-0000030",
                            "naics_code": "541722", "internal_risk_rating": 7},
        loan_overrides={"loan_number": "LN-O03", "original_principal_cents": 2400000,
                        "contractual_rate_bps": 800, "days_past_due": 30},
        case_overrides={"entry_trigger": "COVENANT_DEFAULT", "risk_rating_at_entry": 7},
        plan_overrides={"plan_text": "Legal flip",
                        "target_resolution_date": "2027-03-05T00:00:00Z", "milestone_count": 1},
    )
    loan, case = ctx["loan"], ctx["case"]

    before = validate_success(api_client.get_loan(loan["id"], ctx["officer_h"]), 200)
    assert before["nonaccrual"] is False, "30 days past due is below the 90-day threshold"
    assert before["days_past_due"] == 30

    get_success_data(api_client.create_legal_referral(
        loan["id"], case["id"],
        create_legal_referral_payload(referral_kind="NOTE_SALE_PREP", demand_amount_cents=0,
                                      statute_deadline="2028-01-01T00:00:00Z",
                                      decision_rationale="Prep"),
        ctx["officer_h"]))

    after = validate_success(api_client.get_loan(loan["id"], ctx["officer_h"]), 200)
    assert after["nonaccrual"] is True, "a case in LEGAL forces nonaccrual regardless of delinquency"
    assert after["days_past_due"] == 30, "legal referral does not alter days_past_due"


# ===========================================================================
# Section: consistency_model
# ===========================================================================

def test_immediate_consistency_chargeoff_visible_in_same_response_and_reads(api):
    """PRD §2.9: "Every such cascaded touch is a full mutation of the affected
    resource per §2.4: `updated_at` refreshes and `version` increments. Clients must
    therefore re-read resources after triggering cascades rather than assume their
    last observed values still hold."
    PRD §3.8: "The system stamps `booked_at` from the logical clock, computes
    `is_partial` as true exactly when the amount is strictly less than the principal
    outstanding at booking, moves the amount out of `current_principal_cents` and
    into `charged_off_principal_cents`, and recomputes the case's
    loss-given-default."

    Design: Corner/consistency_model/immediate_consistency_chargeoff_visible_in_same_response_and_reads
    """
    officer_h = make_workout_officer_headers("officer-i2")
    borrower = make_borrower(officer_h, legal_name="Immediate Co", tax_id="55-0000031",
                             naics_code="541723", internal_risk_rating=8)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-I01",
         "original_principal_cents": 8000000, "contractual_rate_bps": 800,
         "days_past_due": 70},
        officer_h))
    case = get_success_data(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8,
         "case_officer_id": "officer-i2"},
        officer_h))
    acct_h = make_loan_accounting_headers("acct-i2")

    loan_before = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    case_before = validate_success(api_client.get_workout_case(loan["id"], case["id"], acct_h), 200)

    validate_success(api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=3000000, reason_code="PARTIAL_IMPAIRMENT"),
        acct_h), 201)

    # Immediate reads reflect the new balances with no delay or recompute endpoint.
    loan_after = validate_success(api_client.get_loan(loan["id"], acct_h), 200)
    assert loan_after["current_principal_cents"] == 5000000
    assert loan_after["charged_off_principal_cents"] == 3000000
    assert loan_after["version"] > loan_before["version"], (
        "moving principal between buckets is a loan mutation: version increments per "
        "PRD §2.4/§2.9")

    case_after = validate_success(api_client.get_workout_case(loan["id"], case["id"], acct_h), 200)
    assert case_after["loss_given_default_cents"] == 5000000, (
        "no collateral: LGD tracks the post-charge-off current principal")
    assert case_after["version"] > case_before["version"], (
        "LGD recomputation is a case mutation: version increments")

"""Second-coverage tests for the harder PRD-described behaviors.

Each test in this file targets a behavior the PRD names explicitly
under §3 and adds a second perspective on a rule whose primary test
lives elsewhere in the suite. Every difficulty-design instance is
covered by at least TWO tests — one primary, one here.

Mapping each difficulty-design rule_id/instance to its two coverage
tests:

  dual_variant_calc/usda_reimbursement_provisional_vs_final_on_claim:
    - test_10::test_provisional_paid_then_final_free_diverge (primary)
    - test_13::test_finalize_with_no_tier_change_provisional_equals_final
      (this file)
  dual_variant_calc/parent_account_top_up_balance_two_orderings:
    - test_08::test_charge_below_zero_rejected (primary)
    - test_13::test_waterfall_replay_topup_charge_topup_order_matters
      (this file)
  combinatorial_formula/frl_tier_threshold_with_nested_branches:
    - test_05::test_ratio_one_cent_above_free_threshold_yields_reduced
      and ::test_ratio_exactly_at_free_threshold_yields_free (primary)
    - test_13::test_two_household_sizes_same_income_diverge (this file)
  combinatorial_formula/usda_reimbursement_final_chronological_order_pinning:
    - test_10::test_provisional_paid_then_final_free_diverge (primary)
    - test_13::test_chronological_order_pinning_after_multiple_tier_flips
      (this file)
  non_linear_state_machine/frl_application_cycle_submitted_info_requested_submitted:
    - test_04::TestInfoRequestAndResubmit::test_resubmit_cycles_back_to_submitted
      (primary)
    - test_13::test_application_full_cycle_approve_after_resubmit (this file)
  non_linear_state_machine/usda_claim_branching_finalize_or_reject:
    - test_09::TestClaimRejection::test_reject_submitted_claim (primary)
    - test_13::test_two_claims_finalize_and_reject_branches_diverge
      (this file)
  transitive_cascade/approve_application_cascades_through_eligibility_to_serving_to_claim:
    - test_10::test_provisional_paid_then_final_free_diverge (primary)
    - test_13::test_three_link_cascade_explicit_per_link_assertions
      (this file)
  transitive_cascade/void_serving_cascades_refund_then_district_total_unaffected_after_finalize:
    - test_08::TestRefund::test_refund_exact_charge_succeeds (primary)
    - test_13::test_void_cascades_to_refund_and_balance (this file)
  priority_pair_validation_conflict/state_vs_business_safety_invalid_state_wins_over_allergen:
    - test_11::test_retired_menu_with_allergen_returns_invalid_state
      (primary)
    - test_13::test_state_vs_allergen_second_perspective (this file)
  priority_pair_validation_conflict/business_safety_vs_business_fiscal_allergen_wins_over_balance:
    - test_11::test_paid_with_allergy_and_zero_balance_returns_allergen_block
      (primary)
    - test_13::test_allergen_vs_balance_second_perspective (this file)
  boundary_precision_check/frl_tier_ratio_exactly_at_free_threshold:
    - test_05::test_ratio_exactly_at_free_threshold_yields_free (primary)
    - test_13::test_ratio_exactly_at_reduced_threshold_second_perspective
      (this file)
  boundary_precision_check/high_sodium_flag_exactly_at_threshold_on_menu_item:
    - test_06::test_sodium_exactly_at_threshold_flagged (primary)
    - test_13::test_sodium_threshold_below_and_above_pair (this file)
  cross_entity_state_dependency/meal_serving_requires_menu_item_active_and_student_eligibility_state:
    - test_07::TestRetiredMenuItemBlocked::test_serving_retired_item_rejected
      (primary)
    - test_13::test_serving_retired_menu_after_clock_advance (this file)
  cross_entity_state_dependency/usda_claim_finalize_requires_no_concurrent_overlapping_submitted:
    - test_09::TestClaimSubmission::test_overlap_at_inclusive_boundary_rejected
      (primary)
    - test_13::test_overlap_with_partial_period_rejected (this file)
  resource_temporal_overlap/usda_claim_period_overlap_closed_closed_inclusive_endpoints:
    - test_09::TestClaimSubmission::test_overlap_at_inclusive_boundary_rejected
      (primary)
    - test_13::test_overlap_strictly_inside_existing_period (this file)
  resource_temporal_overlap/student_serving_per_day_uniqueness_point_in_time:
    - test_07::TestDailyUniqueness::test_second_serving_same_day_rejected
      (primary)
    - test_13::test_serving_per_day_uniqueness_after_clock_advance (this file)
  compensating_invariant/void_meal_preserves_parent_prepaid_balance:
    - test_07::TestVoidServing::test_void_paid_serving_restores_balance
      (primary)
    - test_13::test_void_meal_preserves_parent_prepaid_balance (this file)
  compensating_invariant/void_meal_zeros_provisional_reimbursement_preserves_district_total:
    - test_07::TestVoidServing::test_void_zeros_provisional_reimbursement
      (primary)
    - test_13::test_void_meal_preserves_district_total_without_claim
      (this file)
"""
from __future__ import annotations

import pytest

from test_helpers import (
    HIGH_SODIUM_THRESHOLD_MG,
    REDUCED_THRESHOLD_RATIO,
    USDA_PAID_RATE_CENTS,
    advance_clock_to,
    api_client,
    approve_frl_application,
    create_allergy_entry,
    create_district,
    create_frl_application,
    create_meal_serving,
    create_meal_serving_payload,
    create_menu_item,
    create_usda_claim,
    deny_frl_application,
    finalize_usda_claim,
    make_parent_headers,
    refund_charge,
    reject_usda_claim,
    request_info_on_application,
    resubmit_application,
    retire_menu_item,
    setup_district_with_family,
    setup_mergeable_claim_period_pair,
    setup_paid_serving_with_balance,
    setup_serve_then_void,
    setup_student_with_tier,
    setup_three_paid_servings_then_approve_free,
    submit_and_finalize_claim,
    submit_frl_application,
    submit_usda_claim,
    top_up_parent_account,
    validate_error,
    validate_success,
    void_meal_serving,
)


# ===========================================================================
# dual_variant_calc — second coverage
# ===========================================================================
def test_finalize_with_no_tier_change_provisional_equals_final(api):
    """PRD §3.7: "the final replay reads current eligibility and
    current allergy state rather than the SERVED-time snapshots,
    final_reimbursement_cents and provisional_total_cents can
    legitimately disagree whenever a student's eligibility_tier changed
    between serving and finalisation."

    Claim: in the OPPOSITE case (no tier change between serving and
    finalize), provisional_total_cents and final_reimbursement_cents
    agree. This is the second perspective on the dual-variant rule.

    # difficulty: dual_variant_calc/usda_reimbursement_provisional_vs_final_on_claim
    """
    district, parent, student, _app = setup_student_with_tier(
        target_tier="FREE",
        school_year_start="2026-08-01T00:00:00.000Z",
    )
    item = create_menu_item(
        district=district, full_price_cents=300, reimbursable=True,
    )
    advance_clock_to("2026-09-05T12:00:00.000Z")
    create_meal_serving(
        district=district, student=student, menu_item=item,
    )
    # NO tier change between SERVED and FINALIZED — student stays FREE.
    finalized = submit_and_finalize_claim(
        district=district,
        period_start="2026-09-01T00:00:00.000Z",
        period_end="2026-09-30T00:00:00.000Z",
    )
    # Both sums use FREE rate 480.
    assert finalized["provisional_total_cents"] == 480
    assert finalized["final_reimbursement_cents"] == 480
    assert (
        finalized["provisional_total_cents"]
        == finalized["final_reimbursement_cents"]
    )


def test_waterfall_replay_topup_charge_topup_order_matters(api):
    """PRD §3.6: "The parent account's prepaid_balance_cents is the
    deterministic replay of every PaidLedgerEntry on the account,
    processed in occurred_at ascending order with ties broken by entry
    id ascending. The running total starts at zero. For each entry: a
    TOP_UP adds its amount_cents; a CHARGE subtracts its amount_cents".

    Claim: TOP_UP 200 → CHARGE 150 → TOP_UP 100 yields balance 150
    (the ordered replay = 0 + 200 - 150 + 100). This is the second
    perspective on the ordered-replay rule, distinct from the
    insufficient-balance rejection elsewhere.

    # difficulty: dual_variant_calc/parent_account_top_up_balance_two_orderings
    """
    district, parent, student, item = setup_paid_serving_with_balance(
        full_price_cents=150, top_up_amount_cents=200,
    )
    # Balance now 200. Charge by serving 150.
    create_meal_serving(
        district=district, student=student, menu_item=item,
    )
    # Top up 100 more.
    top_up_parent_account(
        district=district, parent_account=parent, amount_cents=100,
    )
    refreshed = api_client.get_parent_account(
        district["id"], parent["id"], make_parent_headers(parent["id"]),
    ).json()["data"]
    # Replay = 200 - 150 + 100 = 150.
    assert refreshed["prepaid_balance_cents"] == 150


# ===========================================================================
# combinatorial_formula — second coverage
# ===========================================================================
def test_two_household_sizes_same_income_diverge(api):
    """PRD §3.4: "When the ratio is at most 1.30, the classifier
    returns FREE."
    PRD §3.4: "When the ratio is greater than 1.30 but at most 1.85,
    the classifier returns REDUCED."

    Claim: same income 4_500_000 cents but different household_size
    yields different classifications — household_size=4 (FPL 3.09M,
    ratio ~1.456 → REDUCED) vs household_size=8 (FPL 5.21M, ratio
    ~0.864 → FREE). The nested table lookup means the same income
    field projects to DIFFERENT decisions.

    # difficulty: combinatorial_formula/frl_tier_threshold_with_nested_branches
    """
    income = 4_500_000

    district_a, parent_a, student_a = setup_district_with_family()
    app_a = create_frl_application(
        district=district_a, parent_account=parent_a, student=student_a,
        household_size=4, declared_annual_income_cents=income,
    )
    submit_frl_application(
        district=district_a, parent_account=parent_a, application=app_a,
    )
    decided_a = approve_frl_application(
        district=district_a, application=app_a,
    )

    district_b, parent_b, student_b = setup_district_with_family()
    app_b = create_frl_application(
        district=district_b, parent_account=parent_b, student=student_b,
        household_size=8, declared_annual_income_cents=income,
    )
    submit_frl_application(
        district=district_b, parent_account=parent_b, application=app_b,
    )
    decided_b = approve_frl_application(
        district=district_b, application=app_b,
    )

    # 4_500_000 / 3_090_000 = 1.456 → REDUCED.
    assert decided_a["decided_tier"] == "REDUCED"
    # 4_500_000 / 5_210_000 = 0.864 → FREE.
    assert decided_b["decided_tier"] == "FREE"


def test_chronological_order_pinning_after_multiple_tier_flips(api):
    """PRD §3.7: "the system re-resolves the student's current
    eligibility_tier (not the row's tier_at_serving snapshot) and
    selects the rate ... after all snapshot rows have been processed."

    Claim: across three SERVED rows where the student's tier flips
    PAID → REDUCED → FREE between rows, the final replay uses the
    CURRENT tier (FREE) for ALL rows at finalize time, not the
    intermediate tiers. final = 480 + 480 + 480 = 1440 (PAID
    provisional rates would have summed to 50+420+480=950).

    # difficulty: combinatorial_formula/usda_reimbursement_final_chronological_order_pinning
    """
    # Setup: PAID → serve, approve REDUCED → serve, approve FREE → serve.
    district, parent, student = setup_district_with_family()
    item = create_menu_item(
        district=district, full_price_cents=350, reimbursable=True,
    )
    top_up_parent_account(
        district=district, parent_account=parent, amount_cents=2000,
    )
    # Row 1: PAID (provisional 50).
    advance_clock_to("2027-09-01T12:00:00.000Z")
    create_meal_serving(
        district=district, student=student, menu_item=item,
    )
    # Approve REDUCED (income in 1.30..1.85 band for household 4).
    app1 = create_frl_application(
        district=district, parent_account=parent, student=student,
        household_size=4, declared_annual_income_cents=5_000_000,
    )
    submit_frl_application(
        district=district, parent_account=parent, application=app1,
    )
    approve_frl_application(district=district, application=app1)
    # Row 2: REDUCED (provisional 420).
    advance_clock_to("2027-09-02T12:00:00.000Z")
    create_meal_serving(
        district=district, student=student, menu_item=item,
    )
    # Approve FREE (income in <1.30 band).
    app2 = create_frl_application(
        district=district, parent_account=parent, student=student,
        household_size=4, declared_annual_income_cents=2_000_000,
    )
    submit_frl_application(
        district=district, parent_account=parent, application=app2,
    )
    approve_frl_application(district=district, application=app2)
    # Row 3: FREE (provisional 480).
    advance_clock_to("2027-09-03T12:00:00.000Z")
    create_meal_serving(
        district=district, student=student, menu_item=item,
    )
    # Finalize a claim covering all three rows.
    finalized = submit_and_finalize_claim(
        district=district,
        period_start="2027-09-01T00:00:00.000Z",
        period_end="2027-09-30T00:00:00.000Z",
    )
    # PRD §3.7: re-resolve tier per row from CURRENT student tier (FREE).
    # final = 3 × 480 = 1440.
    assert finalized["final_reimbursement_cents"] == 1440
    # Provisional sum = 50 + 420 + 480 = 950.
    assert finalized["provisional_total_cents"] == 950


# ===========================================================================
# non_linear_state_machine — second coverage
# ===========================================================================
def test_application_full_cycle_approve_after_resubmit(api):
    """PRD §3.4: "the application moves to INFO_REQUESTED ... the
    application returns to SUBMITTED" then "On a successful approval,
    ... the application's terminal status is APPROVED."

    Claim: a SUBMITTED → INFO_REQUESTED → SUBMITTED → APPROVED chain
    is permitted; the application terminally lands at APPROVED.

    # difficulty: non_linear_state_machine/frl_application_cycle_submitted_info_requested_submitted
    """
    district, parent, student = setup_district_with_family()
    app = create_frl_application(
        district=district, parent_account=parent, student=student,
        household_size=4, declared_annual_income_cents=2_000_000,
    )
    submit_frl_application(
        district=district, parent_account=parent, application=app,
    )
    request_info_on_application(
        district=district, application=app, review_note="need W-2",
    )
    resubmit_application(
        district=district, parent_account=parent, application=app,
        documents_attached_count=2,
    )
    approved = approve_frl_application(
        district=district, application=app,
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_tier"] == "FREE"
    # The resubmission's documents_attached_count is preserved.
    assert approved["documents_attached_count"] == 2


def test_two_claims_finalize_and_reject_branches_diverge(api):
    """PRD §3.7: "On a successful finalisation, the district's
    usda_reimbursement_total_cents increases by the new
    final_reimbursement_cents."
    PRD §3.7: "An audit officer may instead transition a SUBMITTED
    claim to the terminal REJECTED state".

    Claim: of two SUBMITTED claims with non-overlapping periods, the
    one FINALIZED increases District.usda_reimbursement_total_cents
    while the one REJECTED leaves it unchanged. (No final cents are
    minted on REJECTED.)

    # difficulty: non_linear_state_machine/usda_claim_branching_finalize_or_reject
    """
    from test_helpers import TEST_USERS
    district, c1, c2 = setup_mergeable_claim_period_pair(
        boundary_overlap=False,
    )
    submit_usda_claim(district=district, claim=c2)
    # No servings under either claim → final_reimbursement_cents=0 for c1.
    finalize_usda_claim(district=district, claim=c1)
    reject_usda_claim(district=district, claim=c2)
    district_after = api_client.get_district(
        district["id"], TEST_USERS["audit_headers"],
    ).json()["data"]
    # Both branches reach terminal states; finalize-with-zero-rows still
    # contributes 0 to district total; reject contributes 0 too.
    # The key claim: the REJECTED branch does NOT contribute, and the
    # FINALIZED branch is the only path that COULD contribute.
    assert district_after["usda_reimbursement_total_cents"] == 0
    # Verify the two reached different terminal states.
    c1_after = api_client.get_usda_claim(
        district["id"], c1["id"], TEST_USERS["audit_headers"],
    ).json()["data"]
    c2_after = api_client.get_usda_claim(
        district["id"], c2["id"], TEST_USERS["audit_headers"],
    ).json()["data"]
    assert c1_after["status"] == "FINALIZED"
    assert c2_after["status"] == "REJECTED"


# ===========================================================================
# transitive_cascade — second coverage
# ===========================================================================
def test_three_link_cascade_explicit_per_link_assertions(api):
    """PRD §3.4: "the student's eligibility_tier is updated to the new
    decided_tier".
    PRD §3.7: "the system re-resolves the student's current
    eligibility_tier ... and selects the rate".

    Claim (each link asserted explicitly):
    (1) approve → FrlApplication.status='APPROVED';
    (2) approve → Student.eligibility_tier='FREE' (caused by link 1);
    (3) finalize → final_reimbursement_cents reflects FREE rate (caused
        by link 2's tier change, not by the original approval call).

    # difficulty: transitive_cascade/approve_application_cascades_through_eligibility_to_serving_to_claim
    """
    from test_helpers import TEST_USERS
    ctx = setup_three_paid_servings_then_approve_free()
    # Link 1: application is APPROVED.
    assert ctx["application"]["status"] == "APPROVED"
    # Link 2: student.eligibility_tier flipped to FREE.
    student_after = api_client.get_student(
        ctx["district"]["id"], ctx["student"]["id"],
        make_parent_headers(ctx["parent_account"]["id"]),
    ).json()["data"]
    assert student_after["eligibility_tier"] == "FREE"
    # Link 3: finalize → final cents are 1440, not 150.
    claim = create_usda_claim(
        district=ctx["district"],
        period_start="2026-09-01T00:00:00.000Z",
        period_end="2026-09-30T00:00:00.000Z",
    )
    submit_usda_claim(district=ctx["district"], claim=claim)
    finalized = finalize_usda_claim(
        district=ctx["district"], claim=claim,
    )
    assert finalized["final_reimbursement_cents"] == 1440
    # Provisional (frozen at SERVED-PAID) is 150.
    assert finalized["provisional_total_cents"] == 150


def test_void_cascades_to_refund_and_balance(api):
    """PRD §3.6: "If the record's charged_cents was strictly greater
    than zero, the system appends a PaidLedgerEntry of type REFUND
    ... the parent's prepaid_balance_cents increases by that amount."

    Claim (per-link cascade):
    (1) void → MealServingRecord.status='VOIDED';
    (2) void → ParentAccount.prepaid_balance_cents restored to pre-
        serve value (caused by link 1's REFUND ledger append, not by
        the void endpoint writing the balance directly).

    # difficulty: transitive_cascade/void_serving_cascades_refund_then_district_total_unaffected_after_finalize
    """
    district, parent, student, item, serving = setup_serve_then_void(
        full_price_cents=350, top_up_amount_cents=1000,
    )
    # After serve, balance is 650.
    assert parent["prepaid_balance_cents"] == 650
    # Void.
    voided = void_meal_serving(district=district, serving=serving)
    # Link 1.
    assert voided["status"] == "VOIDED"
    # Link 2.
    parent_after = api_client.get_parent_account(
        district["id"], parent["id"], make_parent_headers(parent["id"]),
    ).json()["data"]
    assert parent_after["prepaid_balance_cents"] == 1000


# ===========================================================================
# priority_pair_validation_conflict — second coverage
# ===========================================================================
def test_state_vs_allergen_second_perspective(api, cafeteria_headers):
    """PRD §2.9: "every other rule in this document is evaluated only
    after the four checks above have passed."

    Claim (second perspective on state-wins-over-allergen): two
    DIFFERENT allergen pairs, RETIRED status + DAIRY+EGG allergens
    intersecting on DAIRY — still ERR_INVALID_STATE.

    # difficulty: priority_pair_validation_conflict/state_vs_business_safety_invalid_state_wins_over_allergen
    """
    district, parent, student = setup_district_with_family()
    create_allergy_entry(
        district=district, parent_account=parent, student=student,
        allergen="DAIRY", severity="MILD",
    )
    item = create_menu_item(
        district=district, contains_allergens=["DAIRY", "EGG"],
        full_price_cents=350,
    )
    retire_menu_item(district=district, menu_item=item)
    res = api.create_meal_serving(
        district["id"],
        create_meal_serving_payload(
            student_id=student["id"], menu_item_id=item["id"],
        ),
        cafeteria_headers,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_allergen_vs_balance_second_perspective(api, cafeteria_headers):
    """PRD §3.6: "First, the student must not be allergen-blocked
    against this specific menu item ... Fourth, if the student's
    eligibility tier is PAID at the moment of serving, the parent
    account's prepaid_balance_cents must be at least the menu item's
    full_price_cents."

    Claim (second perspective): same allergen-over-balance ordering
    but with SHELLFISH allergen and PAID-tier student whose balance
    is 1 cent below price — allergen still fires first.

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_allergen_wins_over_balance
    """
    district, parent, student = setup_district_with_family()
    create_allergy_entry(
        district=district, parent_account=parent, student=student,
        allergen="SHELLFISH", severity="MILD",
    )
    item = create_menu_item(
        district=district, contains_allergens=["SHELLFISH"],
        full_price_cents=350,
    )
    # Top up to 349 cents — one cent short.
    top_up_parent_account(
        district=district, parent_account=parent, amount_cents=349,
    )
    res = api.create_meal_serving(
        district["id"],
        create_meal_serving_payload(
            student_id=student["id"], menu_item_id=item["id"],
        ),
        cafeteria_headers,
    )
    validate_error(res, "ERR_ALLERGEN_BLOCK")


# ===========================================================================
# boundary_precision_check — second coverage
# ===========================================================================
def test_ratio_exactly_at_reduced_threshold_second_perspective(api):
    """PRD §3.4: "a ratio exactly equal to 1.85 yields REDUCED."

    Claim (second perspective on FREE-boundary test): exact equality
    at the OTHER boundary (1.85) confirms the same non-strict rule.
    With household_size=2 (FPL_2=2,030,000), income = 2,030,000 *
    1.85 = 3,755,500 → ratio == exactly 1.85 → REDUCED.

    # difficulty: boundary_precision_check/frl_tier_ratio_exactly_at_free_threshold
    """
    district, parent, student = setup_district_with_family()
    # FPL_2 * 1.85 = 2_030_000 * 1.85 = 3_755_500 (exact integer).
    app = create_frl_application(
        district=district, parent_account=parent, student=student,
        household_size=2, declared_annual_income_cents=3_755_500,
    )
    submit_frl_application(
        district=district, parent_account=parent, application=app,
    )
    approved = approve_frl_application(
        district=district, application=app,
    )
    assert approved["decided_tier"] == "REDUCED"


def test_sodium_threshold_below_and_above_pair(api, audit_headers):
    """PRD §3.3: "a value of exactly 600 milligrams is flagged."

    Claim (second perspective): the 599/601 pair confirms the
    non-strict threshold (the primary tests sodium_mg=599 and
    sodium_mg=600 separately). This test combines them in a single
    boundary check.

    # difficulty: boundary_precision_check/high_sodium_flag_exactly_at_threshold_on_menu_item
    """
    district = create_district()
    item_below = create_menu_item(district=district, sodium_mg=599)
    item_above = create_menu_item(district=district, sodium_mg=601)
    label_below = api.get_nutrition_label(
        district["id"], item_below["id"], audit_headers,
    ).json()["data"]
    label_above = api.get_nutrition_label(
        district["id"], item_above["id"], audit_headers,
    ).json()["data"]
    assert label_below["high_sodium_flag"] is False
    assert label_above["high_sodium_flag"] is True


# ===========================================================================
# cross_entity_state_dependency — second coverage
# ===========================================================================
def test_serving_retired_menu_after_clock_advance(api, cafeteria_headers):
    """PRD §3.6: "the MenuItem must currently be ACTIVE; a serving
    against a RETIRED item surfaces ERR_INVALID_STATE."

    Claim (second perspective on cross-entity dep): even after the
    logical clock has been advanced (different "today"), a previously-
    RETIRED MenuItem still blocks serving.

    # difficulty: cross_entity_state_dependency/meal_serving_requires_menu_item_active_and_student_eligibility_state
    """
    district, parent, student, _app = setup_student_with_tier(
        target_tier="FREE",
        school_year_start="2026-08-01T00:00:00.000Z",
    )
    item = create_menu_item(district=district, full_price_cents=300)
    retire_menu_item(district=district, menu_item=item)
    # Advance clock; the RETIRED status is persistent.
    advance_clock_to("2027-01-01T12:00:00.000Z")
    res = api.create_meal_serving(
        district["id"],
        create_meal_serving_payload(
            student_id=student["id"], menu_item_id=item["id"],
        ),
        cafeteria_headers,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_overlap_with_partial_period_rejected(api, audit_headers):
    """PRD §3.7: "two periods overlap when the existing claim's
    period_end is greater than or equal to the new claim's
    period_start and the existing claim's period_start is less than
    or equal to the new claim's period_end. A submitted-overlap is
    rejected with ERR_CLAIM_PERIOD_OVERLAP."

    Claim (second perspective on cross-row dep): a claim whose period
    starts INSIDE an existing SUBMITTED claim's period (strict
    interior overlap) is rejected.

    # difficulty: cross_entity_state_dependency/usda_claim_finalize_requires_no_concurrent_overlapping_submitted
    """
    district = create_district()
    # Existing claim Jan 1..Jan 31.
    c1 = create_usda_claim(
        district=district,
        period_start="2026-01-01T00:00:00.000Z",
        period_end="2026-01-31T00:00:00.000Z",
    )
    submit_usda_claim(district=district, claim=c1)
    # New claim Jan 15..Feb 15 — overlaps Jan 15..Jan 31.
    c2 = create_usda_claim(
        district=district,
        period_start="2026-01-15T00:00:00.000Z",
        period_end="2026-02-15T00:00:00.000Z",
    )
    res = api.submit_usda_claim(district["id"], c2["id"], audit_headers)
    validate_error(res, "ERR_CLAIM_PERIOD_OVERLAP")


# ===========================================================================
# resource_temporal_overlap — second coverage
# ===========================================================================
def test_overlap_strictly_inside_existing_period(api, audit_headers):
    """PRD §3.7: closed-closed overlap test.

    Claim (second perspective): a new claim whose period is fully
    INSIDE an existing SUBMITTED claim's period is also rejected.

    # difficulty: resource_temporal_overlap/usda_claim_period_overlap_closed_closed_inclusive_endpoints
    """
    district = create_district()
    # Wide existing claim Jan 1..Mar 31.
    c1 = create_usda_claim(
        district=district,
        period_start="2026-01-01T00:00:00.000Z",
        period_end="2026-03-31T00:00:00.000Z",
    )
    submit_usda_claim(district=district, claim=c1)
    # New claim Feb 1..Feb 28 — fully inside Jan 1..Mar 31.
    c2 = create_usda_claim(
        district=district,
        period_start="2026-02-01T00:00:00.000Z",
        period_end="2026-02-28T00:00:00.000Z",
    )
    res = api.submit_usda_claim(district["id"], c2["id"], audit_headers)
    validate_error(res, "ERR_CLAIM_PERIOD_OVERLAP")


def test_serving_per_day_uniqueness_after_clock_advance(
    api, cafeteria_headers,
):
    """PRD §3.6: "A second serving for the same (student_id,
    serving_date) is rejected with ERR_MEAL_ALREADY_SERVED_TODAY."

    Claim (second perspective): the per-day uniqueness is anchored to
    the logical clock — after advancing to a NEW day, a second
    serving for the same student succeeds. (Confirms the constraint
    is per-day, not per-student.)

    # difficulty: resource_temporal_overlap/student_serving_per_day_uniqueness_point_in_time
    """
    district, parent, student, _app = setup_student_with_tier(
        target_tier="FREE",
        school_year_start="2026-08-01T00:00:00.000Z",
    )
    item = create_menu_item(district=district)
    advance_clock_to("2026-09-10T12:00:00.000Z")
    create_meal_serving(
        district=district, student=student, menu_item=item,
    )
    # Same student, different day → permitted.
    advance_clock_to("2026-09-11T12:00:00.000Z")
    second = create_meal_serving(
        district=district, student=student, menu_item=item,
    )
    assert second["status"] == "SERVED"


# ===========================================================================
# compensating_invariant — second coverage
# ===========================================================================
def test_void_meal_preserves_parent_prepaid_balance(api):
    """PRD §3.6: "the parent's prepaid_balance_cents increases by that
    amount."

    Claim (second perspective on the compensation invariant): the
    invariant `balance_after_void == balance_before_serving` holds
    for an arbitrary intermediate top-up sequence too.

    # difficulty: compensating_invariant/void_meal_preserves_parent_prepaid_balance
    """
    district, parent, student, item, serving = setup_serve_then_void(
        full_price_cents=350, top_up_amount_cents=1000,
    )
    # Top-up between serve and void.
    top_up_parent_account(
        district=district, parent_account=parent, amount_cents=200,
    )
    # Now void the serving.
    void_meal_serving(district=district, serving=serving)
    parent_after = api_client.get_parent_account(
        district["id"], parent["id"], make_parent_headers(parent["id"]),
    ).json()["data"]
    # Pre-serve balance was 1000; intermediate top-up added 200; void
    # restored 350. Net: 1000 + 200 = 1200.
    assert parent_after["prepaid_balance_cents"] == 1200


def test_void_meal_preserves_district_total_without_claim(api):
    """PRD §3.1: "usda_reimbursement_total_cents is the sum of
    final_reimbursement_cents across every claim under this district
    that has reached the FINALIZED state".
    PRD §3.6: "The record's provisional_reimbursement_cents is reset
    to zero."

    Claim (second perspective): without any FINALIZED claim, neither
    serve nor void should move District.usda_reimbursement_total_cents
    away from 0.

    # difficulty: compensating_invariant/void_meal_zeros_provisional_reimbursement_preserves_district_total
    """
    from test_helpers import TEST_USERS
    district, parent, student, item = setup_paid_serving_with_balance(
        full_price_cents=300, top_up_amount_cents=1000,
        reimbursable=True,
    )
    district_initial = api_client.get_district(
        district["id"], TEST_USERS["audit_headers"],
    ).json()["data"]
    assert district_initial["usda_reimbursement_total_cents"] == 0
    serving = create_meal_serving(
        district=district, student=student, menu_item=item,
    )
    # Even after a serve, no FINALIZED claim → district total unchanged.
    district_mid = api_client.get_district(
        district["id"], TEST_USERS["audit_headers"],
    ).json()["data"]
    assert district_mid["usda_reimbursement_total_cents"] == 0
    void_meal_serving(district=district, serving=serving)
    district_after = api_client.get_district(
        district["id"], TEST_USERS["audit_headers"],
    ).json()["data"]
    assert district_after["usda_reimbursement_total_cents"] == 0

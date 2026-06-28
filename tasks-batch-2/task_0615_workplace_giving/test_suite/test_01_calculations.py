"""Calculation correctness: matching gifts (estimated vs finalized, tiered), donation
amount breakdown (round-up + processing-fee tier), dollars-for-doers grants, tax statement
totals, and the payroll-deduction ceiling.

These tests pin the precise arithmetic the PRD prescribes (PRD 2.5, 3.5-3.9).
"""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_success,
    validate_error,
    get_success_data,
    setup_giving_scenario,
    create_settled_donation,
    create_authorized_donation,
    create_pledged_donation,
    create_logged_volunteer_log,
    get_matching_gift_for_donation,
)

PM = TEST_USERS["program_manager_headers"]
GA = TEST_USERS["giving_admin_headers"]


# ===========================================================================
# Difficulty / dual_variant_calc
# ===========================================================================
def test_matching_estimated_diverges_from_finalized_under_cap(api):
    """PRD 3.6: "The `estimated_match_cents` produced at request time uses only committed
    consumption — the employee's matched amounts already in `FINALIZED` or `SETTLED` at that
    moment — and deliberately ignores any other matches still in `REQUESTED` and in flight.
    The `matched_amount_cents` produced when the donation settles uses live consumption at
    settle time, which includes any matches that finalized between this gift's request and this
    settle; consequently the final matched amount may be smaller than the earlier estimate."

    Design: Difficulty/dual_variant_calc/matching_estimated_vs_finalized_diverges_on_cap
    """
    # Program defaults: match_ratio 0.5, annual_match_cap_cents 100000, roundup off.
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})

    # D1 pledged with request_match while consumption is 0 -> estimated = floor(180000*0.5) = 90000.
    d1 = create_pledged_donation(
        s, base_amount_cents=180000, request_match=True, donation_type="ONE_TIME", funding_method="CREDIT"
    )
    mg1_at_request = get_matching_gift_for_donation(d1["id"])
    assert mg1_at_request["estimated_match_cents"] == 90000, (
        f"estimated should be 90000 at request time, got {mg1_at_request['estimated_match_cents']}"
    )

    # D0 base 160000 with request_match, settled first -> consumes 80000 of the cap.
    d0 = create_settled_donation(
        s, base_amount_cents=160000, request_match=True, donation_type="ONE_TIME", funding_method="CREDIT"
    )
    mg0 = get_matching_gift_for_donation(d0["id"])
    assert mg0["matched_amount_cents"] == 80000

    # Now settle D1: live remaining = 100000 - 80000 = 20000, so finalized matched = 20000.
    api.authorize_donation(d1["id"], GA)
    validate_success(api.settle_donation(d1["id"], GA))

    mg1 = api_client.get_matching_gift(mg1_at_request["id"], GA)
    mg1_data = validate_success(mg1)
    assert mg1_data["estimated_match_cents"] == 90000, "estimated stays at its request-time value"
    assert mg1_data["matched_amount_cents"] == 20000, (
        f"finalized matched should clamp to remaining 20000, got {mg1_data['matched_amount_cents']}"
    )
    assert mg1_data["status"] == "FINALIZED"

    emp = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp["match_consumed_ytd_cents"] == 100000


def test_matching_finalized_uses_live_consumption_value(api):
    """PRD 3.6: "The `matched_amount_cents` produced when the donation settles uses live
    consumption at settle time, which includes any matches that finalized between this gift's
    request and this settle; consequently the final matched amount may be smaller than the
    earlier estimate."

    Design: Difficulty/dual_variant_calc/matching_estimated_vs_finalized_diverges_on_cap
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})

    d1 = create_pledged_donation(s, base_amount_cents=180000, request_match=True)
    mg1 = get_matching_gift_for_donation(d1["id"])

    # Consume 80000 of the 100000 cap via D0 before D1 settles.
    create_settled_donation(s, base_amount_cents=160000, request_match=True)

    api.authorize_donation(d1["id"], GA)
    validate_success(api.settle_donation(d1["id"], GA))

    mg1_data = validate_success(api.get_matching_gift(mg1["id"], GA))
    # Live finalized value (20000) is strictly less than the earlier estimate (90000).
    assert mg1_data["matched_amount_cents"] == 20000
    assert mg1_data["matched_amount_cents"] < mg1_data["estimated_match_cents"]


def test_donation_breakdown_with_roundup_enabled(api):
    """PRD 3.5: "First, the round-up increment: if the program has `roundup_enabled` set, the
    increment is the number of cents needed to reach the next whole dollar ... otherwise the
    increment is 100 minus the remainder of the base amount divided by 100 ... Second, the
    subtotal is the base amount plus that increment. Third, the processing-fee rate is selected
    from the subtotal tier: if the subtotal is at or above the program's
    `processing_fee_tier_threshold_cents` the low rate applies, otherwise the high rate applies,
    and the processing fee is the subtotal multiplied by the chosen rate, floored to whole cents.
    Fourth, the total charged is the subtotal plus the processing fee."

    Design: Difficulty/dual_variant_calc/donation_breakdown_roundup_on_vs_off
    """
    # roundup ON; base 1250 -> increment 50 -> subtotal 1300 (< 5000 -> high 0.03)
    # fee = floor(1300*0.03) = 39; total = 1339.
    s = setup_giving_scenario(program_overrides={"roundup_enabled": True})
    don = create_authorized_donation(s, base_amount_cents=1250)
    assert don["roundup_increment_cents"] == 50
    assert don["subtotal_cents"] == 1300
    assert don["processing_fee_cents"] == 39
    assert don["total_charged_cents"] == 1339


def test_donation_breakdown_with_roundup_disabled(api):
    """PRD 3.5: "if round-up is not enabled the increment is 0. Second, the subtotal is the base
    amount plus that increment. Third, the processing-fee rate is selected from the subtotal
    tier: if the subtotal is at or above the program's `processing_fee_tier_threshold_cents` the
    low rate applies, otherwise the high rate applies, and the processing fee is the subtotal
    multiplied by the chosen rate, floored to whole cents. Fourth, the total charged is the
    subtotal plus the processing fee."

    Design: Difficulty/dual_variant_calc/donation_breakdown_roundup_on_vs_off
    """
    # roundup OFF; base 1250 -> increment 0 -> subtotal 1250 (< 5000 -> high 0.03)
    # fee = floor(1250*0.03) = 37; total = 1287.
    s = setup_giving_scenario(program_overrides={"roundup_enabled": False})
    don = create_authorized_donation(s, base_amount_cents=1250)
    assert don["roundup_increment_cents"] == 0
    assert don["subtotal_cents"] == 1250
    assert don["processing_fee_cents"] == 37
    assert don["total_charged_cents"] == 1287


# ===========================================================================
# Difficulty / combinatorial_formula
# ===========================================================================
def test_tiered_match_splits_at_ceiling(api):
    """PRD 3.6: "When tiered matching is enabled, the donation's `base_amount_cents` is split at
    `tier_1_ceiling_cents`: the first portion is the smaller of the base amount and the ceiling,
    the second portion is the base amount minus the ceiling but not below zero, the first portion
    is multiplied by `tier_1_rate` and floored, the second portion is multiplied by `tier_2_rate`
    and floored, and the raw match is the sum of those two floored products."

    Design: Difficulty/combinatorial_formula/tiered_match_ratio_nonlinear_tier_selection
    """
    # base 80000, ceiling 50000, rates 1.0 / 0.5:
    # t1 = floor(50000*1.0)=50000, t2 = floor(30000*0.5)=15000 -> raw 65000 (under cap 100000).
    s = setup_giving_scenario(
        program_overrides={
            "tiered_matching_enabled": True,
            "tier_1_ceiling_cents": 50000,
            "tier_1_rate": 1.0,
            "tier_2_rate": 0.5,
            "annual_match_cap_cents": 100000,
        },
        campaign_overrides={"goal_cents": 1000000},
    )
    don = create_settled_donation(s, base_amount_cents=80000, request_match=True)
    mg = get_matching_gift_for_donation(don["id"])
    assert mg["raw_match_cents"] == 65000
    assert mg["matched_amount_cents"] == 65000

    emp = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp["match_consumed_ytd_cents"] == 65000


def test_tiered_match_raw_match_field_value(api):
    """PRD 3.6: "the first portion is multiplied by `tier_1_rate` and floored, the second portion
    is multiplied by `tier_2_rate` and floored, and the raw match is the sum of those two floored
    products."

    Design: Difficulty/combinatorial_formula/tiered_match_ratio_nonlinear_tier_selection
    """
    s = setup_giving_scenario(
        program_overrides={
            "tiered_matching_enabled": True,
            "tier_1_ceiling_cents": 50000,
            "tier_1_rate": 1.0,
            "tier_2_rate": 0.5,
            "annual_match_cap_cents": 100000,
        },
        campaign_overrides={"goal_cents": 1000000},
    )
    don = create_settled_donation(s, base_amount_cents=80000, request_match=True)
    mg = get_matching_gift_for_donation(don["id"])
    # 50000*1.0 + 30000*0.5 = 65000.
    assert mg["raw_match_cents"] == 65000


def test_disbursement_sum_then_fee_rounding_order(api):
    """PRD 3.8: "First, the gross total is the sum of every staged line's `gross_amount_cents`.
    Second, the single batch-level administrative fee is the gross total multiplied by the
    program's `disbursement_admin_fee_rate`, floored to whole cents; the net total is the gross
    total minus that fee."

    Design: Difficulty/combinatorial_formula/disbursement_sum_then_fee_rounding_order
    """
    # Two SETTLED donations 3333 (created first) + 6667; fee rate 0.025.
    # gross 10000 -> batch fee floor(10000*0.025)=250 (NOT 83+166=249); net 9750.
    from test_helpers import setup_batch_with_donation_grants, lock_batch

    s = setup_giving_scenario(
        program_overrides={"disbursement_admin_fee_rate": 0.025},
        campaign_overrides={"goal_cents": 1000000},
    )
    built = setup_batch_with_donation_grants(s, [3333, 6667])
    lock_batch(built["batch"]["id"])

    settled = validate_success(api.settle_disbursement_batch(built["batch"]["id"], GA))
    assert settled["gross_total_cents"] == 10000
    assert settled["admin_fee_cents"] == 250
    assert settled["net_total_cents"] == 9750


def test_disbursement_per_line_allocation_of_single_fee(api):
    """PRD 3.8: "That single fee is then allocated across the lines rather than recomputed per
    line: each line's `admin_fee_cents` is its own `gross_amount_cents` multiplied by the
    admin-fee rate and floored, the allocated sum of those per-line fees is compared to the
    batch-level fee, and any leftover cents (the batch-level fee minus the allocated sum, which
    is never negative) are distributed one cent at a time to the lines in ascending `created_at`
    order. Each line's `net_amount_cents` is then its `gross_amount_cents` minus its final
    `admin_fee_cents`."

    Design: Difficulty/combinatorial_formula/disbursement_sum_then_fee_rounding_order
    """
    from test_helpers import setup_batch_with_donation_grants, lock_batch

    s = setup_giving_scenario(
        program_overrides={"disbursement_admin_fee_rate": 0.025},
        campaign_overrides={"goal_cents": 1000000},
    )
    built = setup_batch_with_donation_grants(s, [3333, 6667])
    grant_a, grant_b = built["grants"][0], built["grants"][1]
    lock_batch(built["batch"]["id"])
    validate_success(api.settle_disbursement_batch(built["batch"]["id"], GA))

    # per-line floors: floor(3333*0.025)=83, floor(6667*0.025)=166 -> sum 249;
    # leftover 250-249 = 1 cent goes to the first line by created_at ASC -> [84, 166].
    g_a = validate_success(api.get_grant(grant_a["id"], GA))
    g_b = validate_success(api.get_grant(grant_b["id"], GA))
    assert g_a["admin_fee_cents"] == 84 and g_a["net_amount_cents"] == 3249
    assert g_b["admin_fee_cents"] == 166 and g_b["net_amount_cents"] == 6501

    charity = validate_success(api.get_charity(s["charity"]["id"], GA))
    assert charity["total_received_cents"] == 9750


def test_donation_fee_circular_subtotal_tier_order(api):
    """PRD 3.5: "Third, the processing-fee rate is selected from the subtotal tier: if the
    subtotal is at or above the program's `processing_fee_tier_threshold_cents` the low rate
    applies, otherwise the high rate applies, and the processing fee is the subtotal multiplied
    by the chosen rate, floored to whole cents. Fourth, the total charged is the subtotal plus
    the processing fee. The fee is always derived from the subtotal, never from the bare base
    amount."

    Design: Difficulty/combinatorial_formula/donation_fee_circular_subtotal_tier_order
    """
    # base 4960 + roundup 40 = subtotal 5000 (>= threshold 5000) -> low 0.02 -> fee 100 -> total 5100.
    # Deriving the tier from the base (4960<5000 -> 0.03) would wrongly give 150.
    s = setup_giving_scenario(
        program_overrides={
            "roundup_enabled": True,
            "processing_fee_tier_threshold_cents": 5000,
            "processing_fee_low_rate": 0.02,
            "processing_fee_high_rate": 0.03,
        }
    )
    don = create_authorized_donation(s, base_amount_cents=4960)
    assert don["roundup_increment_cents"] == 40
    assert don["subtotal_cents"] == 5000
    assert don["processing_fee_cents"] == 100
    assert don["total_charged_cents"] == 5100


def test_donation_fee_uses_subtotal_not_base_for_tier(api):
    """PRD 3.5: "The fee is always derived from the subtotal, never from the bare base amount."

    Design: Difficulty/combinatorial_formula/donation_fee_circular_subtotal_tier_order
    """
    s = setup_giving_scenario(
        program_overrides={
            "roundup_enabled": True,
            "processing_fee_tier_threshold_cents": 5000,
            "processing_fee_low_rate": 0.02,
            "processing_fee_high_rate": 0.03,
        }
    )
    don = create_authorized_donation(s, base_amount_cents=4960)
    # If the fee had been derived from the base (high tier), it would be floor(5000*0.03)=150.
    assert don["processing_fee_cents"] == 100, "fee must use the subtotal tier (low 0.02), not the base tier"


# ===========================================================================
# Corner / calculations
# ===========================================================================
def test_dfd_grant_uncapped_correct(api):
    """PRD 3.7: "The raw grant is the logged minutes divided by sixty (converting minutes to
    hours) multiplied by the program's `dfd_rate_cents_per_hour`, with that whole product floored
    to whole cents."

    Design: Corner/calculations/dfd_grant_uncapped_correct
    """
    # 120 minutes / 60 * 1500 = 3000 (under cap 25000).
    s = setup_giving_scenario()
    log = create_logged_volunteer_log(s, minutes=120, activity_date="2026-02-10T00:00:00Z")
    approved = validate_success(api.approve_volunteer_log(log["id"], GA))
    assert approved["grant_amount_cents"] == 3000

    emp = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp["dfd_consumed_ytd_cents"] == 3000


def test_dfd_grant_clamped_to_cap(api):
    """PRD 3.7: "The grant is then clamped to the volunteer cap: the employee's remaining cap is
    `dfd_annual_cap_cents` minus their `dfd_consumed_ytd_cents`, and the final `grant_amount_cents`
    is the raw grant but never more than the remaining cap and never below zero."

    Design: Corner/calculations/dfd_grant_clamped_to_cap
    """
    # 1200 minutes / 60 * 1500 = 30000 raw, clamps to cap 25000.
    s = setup_giving_scenario()
    log = create_logged_volunteer_log(s, minutes=1200, activity_date="2026-02-10T00:00:00Z")
    approved = validate_success(api.approve_volunteer_log(log["id"], GA))
    assert approved["raw_grant_cents"] == 30000
    assert approved["grant_amount_cents"] == 25000

    emp = validate_success(api.get_employee(s["employee"]["id"], GA))
    assert emp["dfd_consumed_ytd_cents"] == 25000


def test_tax_statement_totals_filtering(api):
    """PRD 3.9: "The deductible donations total, `deductible_donations_cents`, is the sum of
    `base_amount_cents` over the employee's donations that are `SETTLED`, have `tax_deductible`
    set to true, and whose `settled_at` year equals the program's `tax_year` ... The `line_count`
    is the number of donation lines included in that sum."

    Design: Corner/calculations/tax_statement_totals_filtering
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    create_settled_donation(s, base_amount_cents=5000, tax_deductible=True)
    create_settled_donation(s, base_amount_cents=3000, tax_deductible=True)
    create_settled_donation(s, base_amount_cents=1000, tax_deductible=False)

    stmt = validate_success(
        api.create_tax_statement(s["employee"]["id"], GA), expected_status=201
    )
    assert stmt["deductible_donations_cents"] == 8000
    assert stmt["line_count"] == 2
    assert stmt["tax_year"] == 2026


def test_deduction_ceiling_enforced_on_schedule_create(api):
    """PRD 3.5: "the employee's monthly salary is their `annual_salary_cents` divided by twelve
    and floored, the ceiling is that monthly figure multiplied by twenty percent and floored, and
    the sum of `per_period_amount_cents` over the employee's existing schedules in `ACTIVE` or
    `PAUSED` status plus the new schedule's per-period amount must not exceed that ceiling;
    exceeding it is rejected with `ERR_DEDUCTION_LIMIT_EXCEEDED`."

    Design: Corner/calculations/deduction_ceiling_enforced_on_schedule_create
    """
    # salary 1,200,000 -> monthly 100000 -> ceiling 20000; new per_period 25000 exceeds it.
    s = setup_giving_scenario(
        employee_overrides={"annual_salary_cents": 1200000},
        campaign_overrides={"goal_cents": 1000000},
    )
    from test_helpers import create_payroll_schedule_payload

    payload = create_payroll_schedule_payload(
        s["program"]["id"], s["employee"]["id"], s["campaign"]["id"],
        per_period_amount_cents=25000,
        window_start="2026-01-01T00:00:00Z", window_end="2026-07-01T00:00:00Z",
    )
    resp = api.create_payroll_schedule(payload, GA)
    validate_error(resp, ApiErrorId.ERR_DEDUCTION_LIMIT_EXCEEDED.value)

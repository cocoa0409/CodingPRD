"""Chapter 13 waterfall distribution: strict priority order, fill-in-full
(not pro-rata), created_at tie-break within a class, surplus, and the
conservation invariant that every funded cent is accounted for.

PRD §3.8 governs every assertion in this file.
"""
import pytest

from test_helpers import (
    api_client, validate_success, assert_fund_conserved,
    register_debtor, register_creditor, register_trustee, open_case,
    submit_means_test, add_income_and_expense_schedules, add_debt, petition,
    schedule_meeting, hold_meeting, create_plan, file_plan, confirm_plan,
    record_payment,
    make_trustee_headers,
)


def test_waterfall_fills_in_full_in_priority_order_then_dries_mid_class(api):
    """PRD §3.8: "The classes are filled in the order PRIORITY first, then
    SECURED, then UNSECURED; within a single class, debts are taken in ascending
    created_at ... A fund that runs dry mid-class therefore pays the earlier-
    created debts in that class fully and leaves later ones at zero."

    Design: Difficulty/combinatorial_formula/waterfall_evaluation_order_fill_in_full_mode_c
    """
    debtor = register_debtor(full_name="WF Debtor")
    creditor = register_creditor(name="Cr WF")
    trustee = register_trustee(name="T-WF")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    p_debt = add_debt(debtor, case, creditor, "PRIORITY", 200000)
    s_debt = add_debt(debtor, case, creditor, "SECURED", 250000)
    u1_debt = add_debt(debtor, case, creditor, "UNSECURED", 100000)  # created first
    u2_debt = add_debt(debtor, case, creditor, "UNSECURED", 100000)  # created second
    case = petition(debtor, case)
    plan = create_plan(debtor, case, monthly_payment_cents=50000, plan_duration_months=36)
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-WF",
                               scheduled_start="2026-07-01T09:00:00Z",
                               scheduled_end="2026-07-01T10:00:00Z")
    hold_meeting(trustee, meeting)
    plan = confirm_plan(trustee, plan)
    record_payment(trustee, plan, 500000)

    t_headers = make_trustee_headers(trustee["id"])
    dist = validate_success(api.get_distribution(plan["id"], t_headers), 200)
    # Fund 500000: PRIORITY 200000 full, SECURED 250000 full -> 50000 left;
    # first UNSECURED gets 50000, second gets 0.
    assert dist["distribution"][p_debt["id"]] == 200000
    assert dist["distribution"][s_debt["id"]] == 250000
    assert dist["distribution"][u1_debt["id"]] == 50000
    assert dist["distribution"][u2_debt["id"]] == 0
    assert dist["surplus_cents"] == 0


def test_waterfall_priority_filled_before_secured_when_fund_dries(api):
    """PRD §3.8: "The classes are filled in the order PRIORITY first, then
    SECURED, then UNSECURED ... A fund that runs dry mid-class therefore pays the
    earlier-created debts in that class fully and leaves later ones at zero."
    Here the fund dries before SECURED, proving class order dominates created_at.

    Design: Difficulty/combinatorial_formula/waterfall_evaluation_order_fill_in_full_mode_c
    """
    debtor = register_debtor(full_name="WF2 Debtor")
    creditor = register_creditor(name="Cr WF2")
    trustee = register_trustee(name="T-WF2")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    # SECURED is created BEFORE the PRIORITY debt to prove class rank wins over
    # creation order: PRIORITY must still be paid first.
    s_debt = add_debt(debtor, case, creditor, "SECURED", 200000)
    p_debt = add_debt(debtor, case, creditor, "PRIORITY", 200000)
    case = petition(debtor, case)
    plan = create_plan(debtor, case, monthly_payment_cents=50000, plan_duration_months=36)
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-WF2",
                               scheduled_start="2026-07-13T09:00:00Z",
                               scheduled_end="2026-07-13T10:00:00Z")
    hold_meeting(trustee, meeting)
    plan = confirm_plan(trustee, plan)
    record_payment(trustee, plan, 150000)  # fund dries inside PRIORITY

    t_headers = make_trustee_headers(trustee["id"])
    dist = validate_success(api.get_distribution(plan["id"], t_headers), 200)
    # Fund 150000: PRIORITY gets 150000 (partial), SECURED gets 0 despite being
    # created earlier; class order dominates.
    assert dist["distribution"][p_debt["id"]] == 150000
    assert dist["distribution"][s_debt["id"]] == 0
    assert dist["surplus_cents"] == 0


def test_waterfall_fund_conservation_distribution_plus_surplus(api):
    """PRD §3.8: "each debt receives the smaller of the remaining fund and its
    own allowed_amount_cents, that amount is subtracted from the remaining fund,
    and the walk continues ... Whatever remains after every debt is paid is the
    surplus returned to the debtor."

    Design: Difficulty/compensating_invariant/plan_payment_fund_conservation_distribution_plus_surplus
    """
    debtor = register_debtor(full_name="Inv9b Debtor")
    creditor = register_creditor(name="Cr 9b")
    trustee = register_trustee(name="T-9b")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    p_debt = add_debt(debtor, case, creditor, "PRIORITY", 200000)
    s_debt = add_debt(debtor, case, creditor, "SECURED", 250000)
    case = petition(debtor, case)
    plan = create_plan(debtor, case, monthly_payment_cents=200000, plan_duration_months=36)
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-9b",
                               scheduled_start="2026-07-07T09:00:00Z",
                               scheduled_end="2026-07-07T10:00:00Z")
    hold_meeting(trustee, meeting)
    plan = confirm_plan(trustee, plan)
    record_payment(trustee, plan, 600000)

    t_headers = make_trustee_headers(trustee["id"])
    dist = validate_success(api.get_distribution(plan["id"], t_headers), 200)
    # Fund 600000, total allowed debt 450000 -> 150000 surplus.
    assert dist["distribution"][p_debt["id"]] == 200000
    assert dist["distribution"][s_debt["id"]] == 250000
    assert dist["surplus_cents"] == 150000

    plan_after = validate_success(api.get_plan(plan["id"], t_headers), 200)
    assert plan_after["paid_to_date_cents"] == 600000
    assert_fund_conserved(dist["distribution"], dist["surplus_cents"], 600000)


def test_waterfall_fund_conservation_with_no_surplus(api):
    """PRD §3.8: "each debt receives the smaller of the remaining fund and its own
    allowed_amount_cents, that amount is subtracted from the remaining fund ...
    Whatever remains after every debt is paid is the surplus". When the fund is
    fully consumed the surplus is zero and the distributed total equals
    paid_to_date — the conserved quantity still balances.

    Design: Difficulty/compensating_invariant/plan_payment_fund_conservation_distribution_plus_surplus
    """
    debtor = register_debtor(full_name="Inv9b-nosurplus Debtor")
    creditor = register_creditor(name="Cr 9b-ns")
    trustee = register_trustee(name="T-9b-ns")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    p_debt = add_debt(debtor, case, creditor, "PRIORITY", 200000)
    s_debt = add_debt(debtor, case, creditor, "SECURED", 250000)
    case = petition(debtor, case)
    plan = create_plan(debtor, case, monthly_payment_cents=150000, plan_duration_months=36)
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-9b-ns",
                               scheduled_start="2026-07-14T09:00:00Z",
                               scheduled_end="2026-07-14T10:00:00Z")
    hold_meeting(trustee, meeting)
    plan = confirm_plan(trustee, plan)
    record_payment(trustee, plan, 300000)  # < total allowed debt 450000 -> no surplus

    t_headers = make_trustee_headers(trustee["id"])
    dist = validate_success(api.get_distribution(plan["id"], t_headers), 200)
    # Fund 300000: PRIORITY 200000 full, SECURED 100000 partial, surplus 0.
    assert dist["distribution"][p_debt["id"]] == 200000
    assert dist["distribution"][s_debt["id"]] == 100000
    assert dist["surplus_cents"] == 0
    assert_fund_conserved(dist["distribution"], dist["surplus_cents"], 300000)

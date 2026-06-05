"""Chapter 13 plans: the revision cycle, the chapter-13 gate, plan feasibility
at the priority floor, overpayment, optimistic concurrency on creation, and the
case-confirm dependency on a CONFIRMED plan plus the Chapter 13 discharge gate.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_plan_payload, create_plan_payment_payload,
    register_debtor, register_creditor, register_trustee, open_case,
    submit_means_test, add_income_and_expense_schedules, add_debt, petition,
    setup_filed_case, setup_case_at_meeting_held, file_claim, allow_claim,
    schedule_meeting, hold_meeting, create_plan, file_plan, confirm_plan,
    record_payment, current_case_version,
    make_debtor_headers, make_trustee_headers,
)


# ─── Revision cycle (queue A) ──────────────────────────────────────────────

def test_plan_revision_cycle_denied_then_new_draft(api):
    """PRD §3.7: "Denial advances the plan from FILED to DENIED, sets its
    is_active to false ... a denied plan is superseded, and the debtor drafts a
    fresh plan to start the cycle again." And: "On creation the plan begins in
    DRAFT with is_active true".

    Design: Difficulty/non_linear_state_machine/plan_revision_cycle_denied_then_new_draft
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    trustee = register_trustee(name="T-cycle")
    plan1 = create_plan(debtor, case, monthly_payment_cents=50000, plan_duration_months=36)
    plan1 = file_plan(debtor, plan1)
    t_headers = make_trustee_headers(trustee["id"])
    plan1 = validate_success(api.deny_plan(plan1["id"], t_headers), 200)
    assert plan1["status"] == "DENIED"
    assert plan1["is_active"] is False

    # A fresh draft supersedes; case version advanced by the deny, so re-read it.
    plan2 = create_plan(debtor, case, monthly_payment_cents=60000, plan_duration_months=36)
    assert plan2["status"] == "DRAFT"
    assert plan2["is_active"] is True


def test_denied_plan_is_active_flips_false_and_new_plan_active(api):
    """PRD §3.7: "Because a new draft plan supersedes any prior plan, creating it
    flips the prior active plan's is_active to false". After a denial, a fresh
    plan becomes the active one.

    Design: Difficulty/non_linear_state_machine/plan_revision_cycle_denied_then_new_draft
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    trustee = register_trustee(name="T-cycle2")
    plan1 = create_plan(debtor, case, monthly_payment_cents=50000, plan_duration_months=36)
    plan1 = file_plan(debtor, plan1)
    validate_success(api.deny_plan(plan1["id"], make_trustee_headers(trustee["id"])), 200)
    plan2 = create_plan(debtor, case, monthly_payment_cents=70000, plan_duration_months=48)

    d_headers = make_debtor_headers(debtor["id"])
    fetched1 = validate_success(api.get_plan(plan1["id"], d_headers), 200)
    fetched2 = validate_success(api.get_plan(plan2["id"], d_headers), 200)
    assert fetched1["is_active"] is False
    assert fetched2["is_active"] is True


# ─── Feasibility boundary (queue A) ────────────────────────────────────────

def test_plan_feasibility_exact_priority_floor_is_feasible(api):
    """PRD §3.7: "Before a plan may be confirmed, its total_committed_cents must
    be at least the priority floor ... A plan committing exactly the priority
    floor is feasible".

    Design: Difficulty/boundary_precision_check/plan_feasibility_exact_priority_floor_is_feasible
    """
    debtor = register_debtor(full_name="Bound6b Debtor")
    creditor = register_creditor(name="Cr 6b")
    trustee = register_trustee(name="T-6b")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    p_debt = add_debt(debtor, case, creditor, "PRIORITY", 200000)
    case = petition(debtor, case)
    claim = file_claim(creditor, case, p_debt, 200000)
    plan = create_plan(debtor, case, monthly_payment_cents=5000, plan_duration_months=40)
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-6b",
                               scheduled_start="2026-07-04T09:00:00Z",
                               scheduled_end="2026-07-04T10:00:00Z")
    hold_meeting(trustee, meeting)
    allow_claim(trustee, claim)

    t_headers = make_trustee_headers(trustee["id"])
    res = api.confirm_plan(plan["id"], t_headers)
    confirmed = validate_success(res, 200)
    assert confirmed["total_committed_cents"] == 200000  # 5000 * 40
    assert confirmed["status"] == "CONFIRMED"


def test_plan_feasibility_one_cent_short_of_floor_is_infeasible(api):
    """PRD §3.7: "A plan committing exactly the priority floor is feasible; a plan
    one cent short is infeasible and confirmation is rejected with
    ERR_PLAN_INFEASIBLE (HTTP 409)." This is the X-1 boundary companion to the
    exact-floor (X) feasible case.

    Design: Difficulty/boundary_precision_check/plan_feasibility_exact_priority_floor_is_feasible
    """
    debtor = register_debtor(full_name="Short Floor Debtor")
    creditor = register_creditor(name="Cr short")
    trustee = register_trustee(name="T-short")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    p_debt = add_debt(debtor, case, creditor, "PRIORITY", 200001)
    case = petition(debtor, case)
    claim = file_claim(creditor, case, p_debt, 200001)  # allowed floor = 200001
    plan = create_plan(debtor, case, monthly_payment_cents=5000, plan_duration_months=40)  # 200000
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-short",
                               scheduled_start="2026-07-12T09:00:00Z",
                               scheduled_end="2026-07-12T10:00:00Z")
    hold_meeting(trustee, meeting)
    allow_claim(trustee, claim)

    t_headers = make_trustee_headers(trustee["id"])
    # total_committed 200000 is one cent short of the 200001 priority floor.
    res = api.confirm_plan(plan["id"], t_headers)
    validate_error(res, "ERR_PLAN_INFEASIBLE")


def test_plan_infeasible_below_priority_floor_rejected(api):
    """PRD §3.7: "a plan one cent short is infeasible and confirmation is rejected
    with ERR_PLAN_INFEASIBLE (HTTP 409)."

    Design: Corner/validations/plan_infeasible_below_priority_floor_rejected
    """
    debtor = register_debtor(full_name="Infeas Debtor")
    creditor = register_creditor(name="Cr infeas")
    trustee = register_trustee(name="T-infeas")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    p_debt = add_debt(debtor, case, creditor, "PRIORITY", 200000)
    case = petition(debtor, case)
    claim = file_claim(creditor, case, p_debt, 200000)
    plan = create_plan(debtor, case, monthly_payment_cents=4000, plan_duration_months=40)  # 160000
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-infeas",
                               scheduled_start="2026-09-07T09:00:00Z",
                               scheduled_end="2026-09-07T10:00:00Z")
    hold_meeting(trustee, meeting)
    allow_claim(trustee, claim)

    t_headers = make_trustee_headers(trustee["id"])
    res = api.confirm_plan(plan["id"], t_headers)
    validate_error(res, "ERR_PLAN_INFEASIBLE")
    after = validate_success(api.get_plan(plan["id"], t_headers), 200)
    assert after["status"] == "FILED"


# ─── Chapter 13 gate (queue B) ─────────────────────────────────────────────

def test_not_chapter13_plan_create_rejected_on_chapter7_case(api):
    """PRD §3.7: "every plan operation — creating, filing, or confirming — first
    requires that the case's filed_chapter be CHAPTER_13, and an attempt on a
    Chapter 7 case is rejected with ERR_NOT_CHAPTER_13 (HTTP 409)."

    Design: Corner/validations/not_chapter13_plan_create_rejected_on_chapter7_case
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_7", prior_discharge_within_8y=False)
    d_headers = make_debtor_headers(debtor["id"])
    case_v = current_case_version(debtor, case)
    res = api.create_plan(create_plan_payload(
        case["id"], case_v, monthly_payment_cents=50000, plan_duration_months=36), d_headers)
    validate_error(res, "ERR_NOT_CHAPTER_13")


# ─── Overpayment (queue B) ─────────────────────────────────────────────────

def test_plan_overpayment_rejected(api):
    """PRD §3.8: "A payment that would drive paid_to_date_cents above the plan's
    total_committed_cents is rejected with ERR_PLAN_OVERPAYMENT (HTTP 422): the
    committed fund cannot be overpaid."

    Design: Corner/validations/plan_overpayment_rejected
    """
    debtor = register_debtor(full_name="Over Debtor")
    trustee = register_trustee(name="T-over")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    case = petition(debtor, case)
    plan = create_plan(debtor, case, monthly_payment_cents=5000, plan_duration_months=40)  # 200000
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-over",
                               scheduled_start="2026-09-06T09:00:00Z",
                               scheduled_end="2026-09-06T10:00:00Z")
    hold_meeting(trustee, meeting)
    plan = confirm_plan(trustee, plan)

    t_headers = make_trustee_headers(trustee["id"])
    res = api.create_plan_payment(create_plan_payment_payload(plan["id"], amount_cents=200001), t_headers)
    validate_error(res, "ERR_PLAN_OVERPAYMENT")
    after = validate_success(api.get_plan(plan["id"], t_headers), 200)
    assert after["paid_to_date_cents"] == 0


# ─── OCC stale version (queue B) ───────────────────────────────────────────

def test_occ_stale_case_version_on_plan_create(api):
    """PRD §2.10: "If they match, the create proceeds; if another writer has
    advanced the case's version since the client read it, the create is rejected
    with ERR_STALE_CASE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_case_version_on_plan_create
    """
    debtor, case = setup_filed_case(filed_chapter="CHAPTER_13")
    d_headers = make_debtor_headers(debtor["id"])
    stale_v = current_case_version(debtor, case)
    # First create succeeds and advances Case.version.
    first = api.create_plan(create_plan_payload(
        case["id"], stale_v, monthly_payment_cents=50000, plan_duration_months=36), d_headers)
    validate_success(first, 201)
    # Second create reuses the now-stale version.
    second = api.create_plan(create_plan_payload(
        case["id"], stale_v, monthly_payment_cents=60000, plan_duration_months=36), d_headers)
    validate_error(second, "ERR_STALE_CASE_VERSION")


# ─── Case confirm requires a CONFIRMED plan (queue A) ──────────────────────

def test_case_confirm_requires_confirmed_plan(api):
    """PRD §3.10: "the trustee confirms the case ... this requires that the case
    be MEETING_HELD, that it be a Chapter 13 case, and that it have a plan in
    CONFIRMED status."

    Design: Difficulty/cross_entity_state_dependency/case_confirm_requires_confirmed_plan_pair_case_plan
    """
    debtor = register_debtor(full_name="Cross7a Debtor")
    trustee = register_trustee(name="T-7a")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    case = petition(debtor, case)
    plan = create_plan(debtor, case, monthly_payment_cents=50000, plan_duration_months=36)
    plan = file_plan(debtor, plan)  # FILED, not CONFIRMED
    meeting = schedule_meeting(trustee, case, room_code="R-7a",
                               scheduled_start="2026-07-05T09:00:00Z",
                               scheduled_end="2026-07-05T10:00:00Z")
    hold_meeting(trustee, meeting)

    t_headers = make_trustee_headers(trustee["id"])
    res = api.confirm_case(case["id"], t_headers)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_case(case["id"], make_debtor_headers(debtor["id"])), 200)
    assert after["status"] == "MEETING_HELD"


def test_case_confirm_requires_confirmed_plan_succeeds_when_confirmed(api):
    """PRD §3.10: "the trustee confirms the case, advancing its status from
    MEETING_HELD to CONFIRMED; this requires that the case be MEETING_HELD, that
    it be a Chapter 13 case, and that it have a plan in CONFIRMED status."

    Design: Difficulty/cross_entity_state_dependency/case_confirm_requires_confirmed_plan_pair_case_plan
    """
    debtor = register_debtor(full_name="Cross7a-ok Debtor")
    trustee = register_trustee(name="T-7a-ok")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    case = petition(debtor, case)
    plan = create_plan(debtor, case, monthly_payment_cents=50000, plan_duration_months=36)
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-7a-ok",
                               scheduled_start="2026-07-05T11:00:00Z",
                               scheduled_end="2026-07-05T12:00:00Z")
    hold_meeting(trustee, meeting)
    confirm_plan(trustee, plan)  # no priority debts -> floor 0 -> feasible

    t_headers = make_trustee_headers(trustee["id"])
    res = api.confirm_case(case["id"], t_headers)
    after = validate_success(res, 200)
    assert after["status"] == "CONFIRMED"


# ─── Chapter 13 discharge completion gate (queue B) ────────────────────────

def test_chapter13_discharge_before_full_payment_returns_invalid_state(api):
    """PRD §3.10: "On the Chapter 13 path discharge advances the case from
    CONFIRMED to DISCHARGED and requires that the case be CONFIRMED, be a Chapter
    13 case, and that its active plan have been fully funded — paid_to_date_cents
    must be at least total_committed_cents."

    Design: Corner/state_machines/chapter13_discharge_before_full_payment_returns_invalid_state
    """
    debtor = register_debtor(full_name="Early Debtor")
    trustee = register_trustee(name="T-early")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    case = petition(debtor, case)
    plan = create_plan(debtor, case, monthly_payment_cents=5000, plan_duration_months=40)  # 200000
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-early",
                               scheduled_start="2026-09-04T09:00:00Z",
                               scheduled_end="2026-09-04T10:00:00Z")
    hold_meeting(trustee, meeting)
    confirm_plan(trustee, plan)
    t_headers = make_trustee_headers(trustee["id"])
    validate_success(api.confirm_case(case["id"], t_headers), 200)
    record_payment(trustee, plan, 50000)  # only 50000 of 200000

    res = api.discharge_case(case["id"], t_headers)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_case(case["id"], make_debtor_headers(debtor["id"])), 200)
    assert after["status"] == "CONFIRMED"


def test_chapter13_plan_completed_on_discharge_compensation(api):
    """PRD §3.10: "On the Chapter 13 path the active plan is additionally marked
    COMPLETED." And: discharge "reduces the allowed_amount_cents of every debt of
    class UNSECURED to zero".

    Design: Corner/state_machines/chapter13_plan_completed_on_discharge_compensation
    """
    debtor = register_debtor(full_name="Comp Debtor")
    creditor = register_creditor(name="Cr comp")
    trustee = register_trustee(name="T-comp")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    submit_means_test(debtor, case)
    add_income_and_expense_schedules(debtor, case)
    u_debt = add_debt(debtor, case, creditor, "UNSECURED", 60000)
    case = petition(debtor, case)
    plan = create_plan(debtor, case, monthly_payment_cents=5000, plan_duration_months=40)  # 200000
    plan = file_plan(debtor, plan)
    meeting = schedule_meeting(trustee, case, room_code="R-comp",
                               scheduled_start="2026-09-03T09:00:00Z",
                               scheduled_end="2026-09-03T10:00:00Z")
    hold_meeting(trustee, meeting)
    confirm_plan(trustee, plan)
    t_headers = make_trustee_headers(trustee["id"])
    validate_success(api.confirm_case(case["id"], t_headers), 200)
    record_payment(trustee, plan, 200000)  # fully funded

    res = api.discharge_case(case["id"], t_headers)
    after = validate_success(res, 200)
    assert after["status"] == "DISCHARGED"
    plan_after = validate_success(api.get_plan(plan["id"], t_headers), 200)
    assert plan_after["status"] == "COMPLETED"
    debt_after = validate_success(api.get_debt(u_debt["id"], t_headers), 200)
    assert debt_after["allowed_amount_cents"] == 0

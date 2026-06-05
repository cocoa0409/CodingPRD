"""Validation precedence (state beats business checks) and cross-entity state
dependencies on adjudication / payment, plus week temporal-overlap constraints."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_eligible_claim, make_eligible_week,
    create_employer, create_claimant, add_wage_record,
    create_draft_claim, submit_claim, issue_monetary_determination,
    file_week, adjudicate_week, hold_week,
    make_claimant_headers,
    TEST_USERS,
)

ADJ = TEST_USERS["adjudicator_headers"]
BPO = TEST_USERS["benefit_payment_officer_headers"]


# ── Difficulty: priority_pair_validation_conflict / state_beats_work_search_on_adjudicate ──

def test_state_check_beats_work_search_on_adjudicate(api):
    """PRD §2.10: "then whether the target is in a state from which the requested
    transition is defined (ERR_INVALID_STATE). Only after all of those pass does
    the system evaluate the operation-specific business rules — ... work-search
    sufficiency".
    PRD §3.5: "Adjudication is permitted only when the week is in PENDING or HELD."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_work_search_on_adjudicate
    """
    # Week adjudicated INELIGIBLE first (no work-search contacts). A second
    # adjudicate ELIGIBLE finds the week not in PENDING/HELD -> ERR_INVALID_STATE
    # pre-empts the work-search-insufficient check.
    scenario = make_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"], "2026-04-11")
    adjudicate_week(wc["id"], "INELIGIBLE")
    res = api.adjudicate_weekly_certification(wc["id"], {"decision": "ELIGIBLE"}, ADJ)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_adjudicate_eligible_from_pending_with_insufficient_search_is_work_search_error(api):
    """PRD §3.5: "when work_search_required is true, the number of WorkSearchContact
    rows logged for the week must be at least three, failing which the decision is
    rejected with ERR_WORK_SEARCH_INSUFFICIENT."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_work_search_on_adjudicate
    """
    # Same validation pair, isolated so only the work-search rule can fail: the
    # week is in PENDING (state check passes) but has zero contacts.
    scenario = make_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"], "2026-04-11")
    assert wc["work_search_required"] is True
    res = api.adjudicate_weekly_certification(wc["id"], {"decision": "ELIGIBLE"}, ADJ)
    validate_error(res, "ERR_WORK_SEARCH_INSUFFICIENT", expected_status=422)


# ── Difficulty: cross_entity_state_dependency / weekly_adjudicate_requires_claim_monetarily_eligible ──

def test_adjudicate_eligible_requires_claim_monetarily_eligible(api):
    """PRD §3.5: "Deciding a week ELIGIBLE requires three conditions, evaluated in
    this order: the parent claim must be MONETARILY_ELIGIBLE".

    Design: Difficulty/cross_entity_state_dependency/weekly_adjudicate_requires_claim_monetarily_eligible
    """
    # Claim still MONETARY_PENDING (no determination). File a week (work-search
    # waived), then adjudicate ELIGIBLE -> rejected because parent not eligible.
    employer = create_employer()
    claimant = create_claimant()
    add_wage_record(claimant["id"], employer["id"], "2025-Q4", 780000)
    claim = create_draft_claim(claimant["id"], "2026-04-05")
    submit_claim(claim["id"], claimant["id"])
    wc = get_success_data(api_client.create_weekly_certification(
        {"claim_id": claim["id"], "week_ending_date": "2026-04-11",
         "work_search_waived": True},
        make_claimant_headers(claimant["id"])))
    res = api.adjudicate_weekly_certification(wc["id"], {"decision": "ELIGIBLE"}, ADJ)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_adjudicate_eligible_succeeds_once_claim_is_eligible(api):
    """PRD §3.5: "Deciding a week ELIGIBLE requires three conditions, evaluated in
    this order: the parent claim must be MONETARILY_ELIGIBLE".

    Design: Difficulty/cross_entity_state_dependency/weekly_adjudicate_requires_claim_monetarily_eligible
    """
    # Positive contrast: with the parent claim MONETARILY_ELIGIBLE (determination
    # issued), the same ELIGIBLE adjudication on a work-search-waived week succeeds,
    # confirming the gate is precisely the claim's eligibility state.
    scenario = make_eligible_claim(wages=[("2025-Q4", 130000), ("2025-Q3", 130000)])
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", work_search_waived=True)
    updated = get_success_data(api.adjudicate_weekly_certification(
        wc["id"], {"decision": "ELIGIBLE"}, ADJ))
    assert updated["adjudication_status"] == "ELIGIBLE"


# ── Difficulty: cross_entity_state_dependency / pay_week_requires_adjudication_eligible ──

def test_pay_requires_adjudication_eligible(api):
    """PRD §3.5: "Payment is permitted only when the week's payment_status is
    UNPAID, its adjudication_status is ELIGIBLE, and the parent claim is
    MONETARILY_ELIGIBLE".

    Design: Difficulty/cross_entity_state_dependency/pay_week_requires_adjudication_eligible
    """
    # Week placed on HELD (adjudication axis), still UNPAID. Paying it is rejected
    # because adjudication_status is not ELIGIBLE.
    scenario = make_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", work_search_waived=True)
    hold_week(wc["id"])
    res = api.pay_weekly_certification(wc["id"], {}, BPO)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_pay_pending_unadjudicated_week_rejected(api):
    """PRD §3.5: "Payment is permitted only when the week's payment_status is
    UNPAID, its adjudication_status is ELIGIBLE, and the parent claim is
    MONETARILY_ELIGIBLE".

    Design: Difficulty/cross_entity_state_dependency/pay_week_requires_adjudication_eligible
    """
    # A freshly filed week is PENDING on the adjudication axis (never adjudicated),
    # so paying it is rejected — the same payment->adjudication-axis dependency.
    scenario = make_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
                   "2026-04-11", work_search_waived=True)
    assert wc["adjudication_status"] == "PENDING"
    res = api.pay_weekly_certification(wc["id"], {}, BPO)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ── Difficulty: resource_temporal_overlap / duplicate_week_ending_date_per_claim_rejected ──

def test_duplicate_week_ending_date_rejected(api):
    """PRD §3.5: "The week_ending_date must be a Saturday and must be unique per
    claim — a second certification for the same claim and week is rejected with
    ERR_DUPLICATE_RESOURCE."

    Design: Difficulty/resource_temporal_overlap/duplicate_week_ending_date_per_claim_rejected
    """
    scenario = make_eligible_claim()
    file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
              "2026-04-11", work_search_waived=True)
    res = api.create_weekly_certification(
        {"claim_id": scenario["claim"]["id"], "week_ending_date": "2026-04-11",
         "work_search_waived": True},
        make_claimant_headers(scenario["claimant"]["id"]))
    validate_error(res, "ERR_DUPLICATE_RESOURCE", expected_status=409)


def test_distinct_week_ending_date_on_same_claim_allowed(api):
    """PRD §3.5: "The week_ending_date must be a Saturday and must be unique per
    claim — a second certification for the same claim and week is rejected with
    ERR_DUPLICATE_RESOURCE."

    Design: Difficulty/resource_temporal_overlap/duplicate_week_ending_date_per_claim_rejected
    """
    # The point-interval key is the (claim, week_ending_date) pair: a DIFFERENT
    # Saturday (2026-04-18) on the same claim does not collide and is created.
    scenario = make_eligible_claim()
    file_week(scenario["claim"]["id"], scenario["claimant"]["id"],
              "2026-04-11", work_search_waived=True)
    second = get_success_data(api.create_weekly_certification(
        {"claim_id": scenario["claim"]["id"], "week_ending_date": "2026-04-18",
         "work_search_waived": True},
        make_claimant_headers(scenario["claimant"]["id"])))
    assert second["week_ending_date"] == "2026-04-18"


# ── Difficulty: resource_temporal_overlap / work_search_contact_must_fall_within_week_interval ──

def test_work_search_contact_before_week_window_rejected(api):
    """PRD §3.5: "The contact_date must fall within the certification week — on or
    after the Sunday that opens the week and on or before the week_ending_date —
    and a contact dated outside that window is rejected with ERR_UNTIMELY."

    Design: Difficulty/resource_temporal_overlap/work_search_contact_must_fall_within_week_interval
    """
    # Week ending Sat 2026-04-11 -> window opens Sun 2026-04-05. A contact dated
    # 2026-04-04 (one day before the Sunday) is outside the window -> ERR_UNTIMELY.
    scenario = make_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"], "2026-04-11")
    res = api.create_work_search_contact(
        wc["id"],
        {"contact_type": "EMPLOYER_APPLICATION", "contact_date": "2026-04-04",
         "employer_id": scenario["employer"]["id"]},
        make_claimant_headers(scenario["claimant"]["id"]))
    validate_error(res, "ERR_UNTIMELY", expected_status=422)


def test_work_search_contact_after_week_window_rejected(api):
    """PRD §3.5: "The contact_date must fall within the certification week — on or
    after the Sunday that opens the week and on or before the week_ending_date —
    and a contact dated outside that window is rejected with ERR_UNTIMELY."

    Design: Difficulty/resource_temporal_overlap/work_search_contact_must_fall_within_week_interval
    """
    # The closed interval's upper bound: a contact dated 2026-04-12 (one day after
    # the Saturday week_ending_date 2026-04-11) is outside the window -> ERR_UNTIMELY.
    scenario = make_eligible_claim()
    wc = file_week(scenario["claim"]["id"], scenario["claimant"]["id"], "2026-04-11")
    res = api.create_work_search_contact(
        wc["id"],
        {"contact_type": "INTERVIEW", "contact_date": "2026-04-12"},
        make_claimant_headers(scenario["claimant"]["id"]))
    validate_error(res, "ERR_UNTIMELY", expected_status=422)

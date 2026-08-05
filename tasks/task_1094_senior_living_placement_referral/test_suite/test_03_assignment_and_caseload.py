"""Inquiry priority scoring, advisor assignment/auto-selection, caseload load
indices and their conservation under reassignment.

Difficulty instances carry >=2 tests each; corner instances >=1.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    create_advisor, create_family, create_inquiry, assign_advisor, set_clock,
    setup_advisor_with_caseload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# --- Difficulty: inquiry_priority_score round-then-sum (>=2 tests) ---

def test_inquiry_priority_score_round_then_sum_value(api):
    """PRD §3.2: "The rounding order here is **round-then-sum**: each weighted term
    is first rounded to 2 decimals half up, and only then are the three rounded
    terms added; the resulting sum is reported exactly as that sum and is not
    rounded again."

    Design: Difficulty/combinatorial_formula/inquiry_priority_score_rounds_each_weighted_term_before_summing
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"], requested_care_level="ASSISTED_LIVING",
                             target_move_in_date="2026-06-20",
                             declared_budget_monthly_cents=520000)
    assert inquiry["priority_score"] == 70.59
    assert inquiry["priority_score"] != 70.60


def test_inquiry_priority_score_frozen_at_creation(api):
    """PRD §3.2: "At creation the inquiry's `priority_score` is computed once,
    frozen, and never recomputed."
    PRD §3.2: "A new inquiry begins in `NEW` status with `assigned_advisor_id`
    unset, `match_count` at 0".

    Design: Difficulty/combinatorial_formula/inquiry_priority_score_rounds_each_weighted_term_before_summing
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"], requested_care_level="ASSISTED_LIVING",
                             target_move_in_date="2026-06-20",
                             declared_budget_monthly_cents=520000)
    assert inquiry["status"] == "NEW"
    assert inquiry["assigned_advisor_id"] is None
    fresh = validate_success(api.get_inquiry(inquiry["id"], ADMIN))
    assert fresh["priority_score"] == 70.59


# --- Difficulty: headcount vs weighted load index (>=2 tests) ---

def test_advisor_headcount_load_index_counts_every_assignment_equally(api):
    """PRD §3.9: "The **headcount load index** is the count of active assignments
    divided by the advisor's `caseload_capacity`, rounded half up to 4 decimals;
    it treats every active assignment as exactly 1.0 regardless of the underlying
    inquiry's acuity or urgency".

    Design: Difficulty/dual_variant_calc/advisor_load_index_headcount_vs_acuity_weighted_on_same_caseload
    """
    s = setup_advisor_with_caseload(api, count=2, capacity=3)
    advisor = validate_success(api.get_advisor(s["advisor"]["id"], ADMIN))
    assert advisor["active_caseload_count"] == 2
    assert advisor["headcount_load_index"] == 0.6667


def test_advisor_weighted_load_index_diverges_from_headcount(api):
    """PRD §3.9: "The **weighted load index** sums the frozen `priority_score` of
    each active assignment's inquiry, divides by the product of `caseload_capacity`
    and 100, and rounds half up to 4 decimals; because each case is weighted by its
    priority over 100, a caseload of low-priority cases produces a materially lower
    index than the headcount variant."

    Design: Difficulty/dual_variant_calc/advisor_load_index_headcount_vs_acuity_weighted_on_same_caseload
    """
    s = setup_advisor_with_caseload(api, count=2, capacity=3)
    priorities = sorted(inq["priority_score"] for inq in s["inquiries"])
    assert priorities == [52.03, 70.59]
    advisor = validate_success(api.get_advisor(s["advisor"]["id"], ADMIN))
    assert advisor["weighted_load_index"] == 0.4087
    assert advisor["headcount_load_index"] != advisor["weighted_load_index"]


# --- Difficulty: reassign conserves headcount (>=2 tests) ---

def _two_advisors_one_assignment(api):
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    ben = create_advisor(api, full_name="Ben Cho", is_va_certified=True)
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"], requested_care_level="ASSISTED_LIVING",
                             target_move_in_date="2026-06-20",
                             declared_budget_monthly_cents=520000)
    assign_advisor(api, inquiry["id"], ann["id"])
    return ann, ben, inquiry


def test_reassign_moves_active_slot_between_advisors(api):
    """PRD §3.3: "On success the inquiry's current `ACTIVE` caseload assignment
    moves to `REASSIGNED` with `release_reason` `REASSIGNED` and `released_at` set
    from the clock; the losing advisor's `active_caseload_count` is decremented by 1
    and both its indices recomputed; a fresh `ACTIVE` assignment is created for the
    target advisor; the target's `active_caseload_count` is incremented by 1".

    Design: Difficulty/compensating_invariant/reassign_conserves_total_active_caseload_headcount_across_advisors
    """
    ann, ben, inquiry = _two_advisors_one_assignment(api)
    validate_success(api.reassign_inquiry(inquiry["id"], {"to_advisor_id": ben["id"]}, ADMIN))
    a = validate_success(api.get_advisor(ann["id"], ADMIN))
    b = validate_success(api.get_advisor(ben["id"], ADMIN))
    assert a["active_caseload_count"] == 0
    assert b["active_caseload_count"] == 1
    assert a["active_caseload_count"] + b["active_caseload_count"] == 1
    inq = validate_success(api.get_inquiry(inquiry["id"], ADMIN))
    assert inq["assigned_advisor_id"] == ben["id"]
    assert inq["status"] == "ASSIGNED"


def test_reassign_recomputes_both_load_indices_and_keeps_global_total(api):
    """PRD §3.9: "The **weighted load index** sums the frozen `priority_score` of
    each active assignment's inquiry, divides by the product of `caseload_capacity`
    and 100, and rounds half up to 4 decimals".
    PRD §3.3: "the losing advisor's `active_caseload_count` is decremented by 1 and
    both its indices recomputed".

    Design: Difficulty/compensating_invariant/reassign_conserves_total_active_caseload_headcount_across_advisors
    """
    ann, ben, inquiry = _two_advisors_one_assignment(api)
    validate_success(api.reassign_inquiry(inquiry["id"], {"to_advisor_id": ben["id"]}, ADMIN))
    a = validate_success(api.get_advisor(ann["id"], ADMIN))
    b = validate_success(api.get_advisor(ben["id"], ADMIN))
    assert a["headcount_load_index"] == 0.0 and a["weighted_load_index"] == 0.0
    assert b["headcount_load_index"] == 0.3333 and b["weighted_load_index"] == 0.2353
    _, meta = validate_paginated(api.list_caseload_assignments(ADMIN, params={"status": "ACTIVE"}))
    assert meta["total_count"] == 1
    rows, _ = validate_paginated(api.list_caseload_assignments(ADMIN, params={"inquiry_id": inquiry["id"]}))
    assert len(rows) == 2
    by_status = {r["status"]: r for r in rows}
    assert by_status["REASSIGNED"]["advisor_id"] == ann["id"]
    assert by_status["REASSIGNED"]["release_reason"] == "REASSIGNED"
    assert by_status["ACTIVE"]["advisor_id"] == ben["id"]


# --- Difficulty: assign rejected at exact capacity boundary (>=2 tests) ---

def test_assign_rejected_when_caseload_exactly_equals_capacity(api):
    """PRD §3.3: "the advisor must also have room, meaning `active_caseload_count`
    strictly less than `caseload_capacity`, otherwise `ERR_ADVISOR_CASELOAD_FULL`".

    Design: Difficulty/boundary_precision_check/assign_rejected_when_active_caseload_count_exactly_equals_capacity
    """
    s = setup_advisor_with_caseload(api, count=2, capacity=2)
    resp = api.assign_inquiry(s["next_inquiry"]["id"], {"advisor_id": s["advisor"]["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ADVISOR_CASELOAD_FULL)
    advisor = validate_success(api.get_advisor(s["advisor"]["id"], ADMIN))
    assert advisor["active_caseload_count"] == 2


def test_assign_at_capacity_leaves_inquiry_new_and_headcount_full(api):
    """PRD §3.9: "the headcount load index ... is the variant used as the hard
    eligibility gate (an advisor is assignable only while `active_caseload_count` is
    strictly below `caseload_capacity`)."

    Design: Difficulty/boundary_precision_check/assign_rejected_when_active_caseload_count_exactly_equals_capacity
    """
    s = setup_advisor_with_caseload(api, count=2, capacity=2)
    resp = api.assign_inquiry(s["next_inquiry"]["id"], {"advisor_id": s["advisor"]["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ADVISOR_CASELOAD_FULL)
    advisor = validate_success(api.get_advisor(s["advisor"]["id"], ADMIN))
    assert advisor["headcount_load_index"] == 1.0
    nxt = validate_success(api.get_inquiry(s["next_inquiry"]["id"], ADMIN))
    assert nxt["status"] == "NEW" and nxt["assigned_advisor_id"] is None
    rows, _ = validate_paginated(api.list_caseload_assignments(ADMIN, params={"advisor_id": s["advisor"]["id"]}))
    assert len(rows) == 2


# --- Corner: auto-selection ranking and empty pool ---

def test_auto_selection_ranks_by_lowest_weighted_load_index(api):
    """PRD §3.3: "the candidates are ranked by `weighted_load_index` ascending — the
    least acuity-loaded advisor first — with ties broken first by
    `active_caseload_count` ascending and then by `created_at` ascending (never by
    `id`), and the first candidate wins."

    Design: Corner/calculations/advisor_auto_selection_ranks_by_lowest_weighted_load_index
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    ben = create_advisor(api, full_name="Ben Cho", is_va_certified=True)
    family = create_family(api)
    q1 = create_inquiry(api, family["id"], requested_care_level="ASSISTED_LIVING",
                        target_move_in_date="2026-06-20", declared_budget_monthly_cents=520000)
    assign_advisor(api, q1["id"], ann["id"])  # Ann now weighted 0.2353, Ben still 0.0
    q2 = create_inquiry(api, family["id"], requested_care_level="MEMORY_CARE",
                        target_move_in_date="2026-09-30", declared_budget_monthly_cents=400000)
    result = validate_success(api.assign_inquiry(q2["id"], {}, ADMIN))
    assert result["assigned_advisor_id"] == ben["id"]
    assert result["status"] == "ASSIGNED"
    a = validate_success(api.get_advisor(ann["id"], ADMIN))
    b = validate_success(api.get_advisor(ben["id"], ADMIN))
    assert a["weighted_load_index"] == 0.2353
    assert b["active_caseload_count"] == 1
    assert b["weighted_load_index"] == 0.1734


def test_auto_selection_empty_pool_returns_no_eligible_advisor(api):
    """PRD §3.3: "First it filters to eligible advisors: those whose `status` is
    `ACTIVE`, whose `region_code` equals the inquiry's `region_code`, and whose
    `active_caseload_count` is strictly below their `caseload_capacity`. If that
    candidate pool is empty the request is rejected with `ERR_NO_ELIGIBLE_ADVISOR`."

    Design: Corner/calculations/advisor_auto_selection_with_empty_candidate_pool_returns_no_eligible_advisor
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    cara = create_advisor(api, full_name="Cara Diaz", region_code="TX-DAL", caseload_capacity=5)
    family = create_family(api)
    q1 = create_inquiry(api, family["id"], region_code="TX-AUS")
    resp = api.assign_inquiry(q1["id"], {}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ADVISOR)
    inq = validate_success(api.get_inquiry(q1["id"], ADMIN))
    assert inq["status"] == "NEW" and inq["assigned_advisor_id"] is None
    advisor = validate_success(api.get_advisor(cara["id"], ADMIN))
    assert advisor["active_caseload_count"] == 0


def test_assigning_out_of_region_advisor_returns_not_eligible(api):
    """PRD §3.3: "When an advisor is named explicitly, that advisor must be `ACTIVE`
    and serve the inquiry's `region_code`, otherwise the request is rejected with
    `ERR_ADVISOR_NOT_ELIGIBLE`".

    Design: Corner/validations/assigning_an_out_of_region_advisor_returns_advisor_not_eligible
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    cara = create_advisor(api, full_name="Cara Diaz", region_code="TX-DAL", caseload_capacity=5)
    family = create_family(api)
    q1 = create_inquiry(api, family["id"], region_code="TX-AUS")
    resp = api.assign_inquiry(q1["id"], {"advisor_id": cara["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ADVISOR_NOT_ELIGIBLE)
    inq = validate_success(api.get_inquiry(q1["id"], ADMIN))
    assert inq["status"] == "NEW" and inq["assigned_advisor_id"] is None
    advisor = validate_success(api.get_advisor(cara["id"], ADMIN))
    assert advisor["active_caseload_count"] == 0

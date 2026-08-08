"""Assignment cancellation and settlement: the guaranteed-hour partition across approve
and short-notice cancel, the draft full-waiver, and the inclusive 30-day notice window."""
from test_helpers import (
    validate_success, validate_paginated, TEST_USERS, make_facility_manager_headers,
    assert_guaranteed_hours_partition,
)
from test_helpers.fixtures import (
    setup_active_assignment, provision, submit_timesheet, approve_timesheet,
    get_assignment_data, get_clinician_data, statements_for_assignment,
)

RECRUITER = TEST_USERS["recruiter_headers"]


def _contract(api, asg_id):
    data, _ = validate_paginated(api.list_assignment_contracts(asg_id, RECRUITER))
    return data[0]


def _penalty_statement(api, asg_id):
    data, _ = statements_for_assignment(api, asg_id)
    return next((s for s in data if s["kind"] == "CANCELLATION_PENALTY"), None)


# --- Difficulty: guaranteed-hour partition conserved across approve and short-notice cancel ---
def test_guaranteed_hours_partition_holds_across_approve_and_cancel(api):
    """PRD §3.9: "The shortfall hours are the smaller of the contract's
    weekly_guaranteed_hours multiplied by the shortfall weeks, or the assignment's current
    guaranteed_hours_remaining. Guaranteed hours are then settled by a waterfall:
    guaranteed_hours_consumed increases by the shortfall hours, guaranteed_hours_waived
    increases by the remaining hours minus the shortfall hours, and
    guaranteed_hours_remaining is set to 0."
    PRD §3.9: "otherwise the shortfall is the difference of thirty minus the notice days,
    divided by seven and rounded up to a whole number of weeks."

    Design: Difficulty/compensating_invariant/guaranteed_hours_partition_conserved_across_approve_and_short_notice_cancel
    """
    ctx = setup_active_assignment(api, clock="2026-06-21")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    before = get_assignment_data(api, ctx.asg_id)
    assert before["guaranteed_hours_consumed"] == 36 and before["guaranteed_hours_remaining"] == 432
    assert_guaranteed_hours_partition(before)
    validate_success(api.cancel_assignment(
        ctx.asg_id, {"effective_date": "2026-07-02", "cancellation_reason": "Census decline"},
        make_facility_manager_headers(ctx.fac_id)), 200)
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["cancellation_notice_days"] == 11 and asg["cancellation_penalty_cents"] == 1512000
    assert asg["guaranteed_hours_consumed"] == 144
    assert asg["guaranteed_hours_remaining"] == 0
    assert asg["guaranteed_hours_waived"] == 324
    assert_guaranteed_hours_partition(asg)
    assert asg["staffing_status"] == "CANCELLED"


def test_short_notice_cancel_creates_penalty_statement_and_rolls_ledger(api):
    """PRD §3.9: "When the shortfall hours are greater than 0, a CANCELLATION_PENALTY
    earnings statement is created in the FINALIZED ledger state, priced with no stipend:
    its stipend_variant is NONE, its non_taxable_stipend_cents is 0, its timesheet_id is
    null, its period_key_date is the cancellation_effective_date, and its billable_hours is
    the shortfall hours. ... and cancellation_penalty_cents is that gross_bill_cents. The
    realized ledger and the clinician's year-to-date counters then absorb this penalty
    statement."

    Design: Difficulty/compensating_invariant/guaranteed_hours_partition_conserved_across_approve_and_short_notice_cancel
    """
    ctx = setup_active_assignment(api, clock="2026-06-21")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    validate_success(api.cancel_assignment(
        ctx.asg_id, {"effective_date": "2026-07-02", "cancellation_reason": "Census decline"},
        make_facility_manager_headers(ctx.fac_id)), 200)
    pen = _penalty_statement(api, ctx.asg_id)
    assert pen is not None and pen["timesheet_id"] is None
    assert pen["billable_hours"] == 108 and pen["stipend_variant"] == "NONE"
    assert pen["non_taxable_stipend_cents"] == 0 and pen["taxable_wages_cents"] == 561600
    assert pen["burden_cents"] == 103896 and pen["total_pay_cost_cents"] == 665496
    assert pen["gross_bill_cents"] == 1512000 and pen["gross_margin_cents"] == 846504
    assert pen["margin_pct"] == 0.5599 and pen["period_key_date"] == "2026-07-02"
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["realized_gross_bill_cents"] == 2016000 and asg["realized_pay_cost_cents"] == 1047628
    assert asg["realized_margin_cents"] == 968372 and asg["realized_margin_pct"] == 0.4803
    assert _contract(api, ctx.asg_id)["status"] == "VOIDED"
    clin = get_clinician_data(api, ctx.clin_id)
    assert clin["active_assignment_count"] == 0 and clin["status"] == "AVAILABLE"
    assert clin["ytd_taxable_wages_cents"] == 748800 and clin["ytd_nontaxable_stipend_cents"] == 160300


def test_cancel_draft_assignment_waives_all_hours_and_voids_contract(api):
    """PRD §3.9: "A cancellation from DRAFT — where there was no active work — records
    cancellation_penalty_cents as 0 with no penalty statement, sets guaranteed_hours_waived
    to the full guaranteed_hours_remaining, and sets guaranteed_hours_remaining to 0."
    PRD §3.9: "the linked contract ... moves to VOIDED with its voided_reason set to the
    cancellation reason"

    Design: Corner/state_machines/corner_cancel_draft_assignment_waives_every_guaranteed_hour_and_voids_contract
    """
    ctx = provision(api)  # DRAFT assignment, DRAFT contract, clock at default 2026-05-01
    validate_success(api.cancel_assignment(
        ctx.asg_id, {"effective_date": "2026-06-07", "cancellation_reason": "Requisition pulled"},
        make_facility_manager_headers(ctx.fac_id)), 200)
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["staffing_status"] == "CANCELLED"
    assert asg["cancellation_effective_date"] == "2026-06-07"
    assert asg["cancellation_notice_days"] == 37 and asg["cancellation_penalty_cents"] == 0
    assert asg["guaranteed_hours_consumed"] == 0 and asg["guaranteed_hours_remaining"] == 0
    assert asg["guaranteed_hours_waived"] == 468
    assert_guaranteed_hours_partition(asg)
    con = _contract(api, ctx.asg_id)
    assert con["status"] == "VOIDED" and con["voided_reason"] is not None
    data, _ = statements_for_assignment(api, ctx.asg_id)
    assert data == []
    clin = get_clinician_data(api, ctx.clin_id)
    assert clin["active_assignment_count"] == 0 and clin["status"] == "AVAILABLE"


def test_cancel_with_exactly_thirty_days_notice_waives_without_penalty(api):
    """PRD §3.9: "When notice is at least thirty days — the cancellation-notice window, an
    inclusive comparison, so exactly thirty days is sufficient — the shortfall is zero
    weeks ... When the shortfall hours are 0, cancellation_penalty_cents is 0 and no
    statement is created."

    Design: Corner/validations/corner_cancellation_with_exactly_thirty_days_notice_waives_without_penalty
    """
    ctx = setup_active_assignment(api, clock="2026-06-21")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    validate_success(api.cancel_assignment(
        ctx.asg_id, {"effective_date": "2026-07-21", "cancellation_reason": "Unit closure"},
        make_facility_manager_headers(ctx.fac_id)), 200)
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["cancellation_notice_days"] == 30 and asg["cancellation_penalty_cents"] == 0
    assert asg["guaranteed_hours_consumed"] == 36 and asg["guaranteed_hours_remaining"] == 0
    assert asg["guaranteed_hours_waived"] == 432
    assert_guaranteed_hours_partition(asg)
    data, meta = statements_for_assignment(api, ctx.asg_id)
    assert meta["total_count"] == 1 and data[0]["kind"] == "WEEKLY"
    assert asg["realized_gross_bill_cents"] == 504000 and asg["realized_pay_cost_cents"] == 382132
    assert asg["realized_margin_cents"] == 121868 and asg["realized_margin_pct"] == 0.2418
    assert asg["staffing_status"] == "CANCELLED" and _contract(api, ctx.asg_id)["status"] == "VOIDED"

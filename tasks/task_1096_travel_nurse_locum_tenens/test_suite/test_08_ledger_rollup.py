"""Assignment ledger roll-up: approval cascade + auto-completion, the money-partition
invariant across approve and void, and the empty-statement-set boundary."""
from test_helpers import (
    validate_success, validate_paginated, TEST_USERS, make_facility_manager_headers,
    assert_money_partition, assert_assignment_money_partition,
)
from test_helpers.fixtures import (
    setup_active_assignment, submit_timesheet, approve_timesheet,
    statement_for_timesheet, statements_for_assignment,
    get_assignment_data, get_clinician_data,
)

PAYROLL1 = TEST_USERS["payroll_admin_headers"]
PAYROLL_ADMIN = TEST_USERS["payroll_admin_headers"]


# --- Difficulty: approve timesheet cascades statement -> ledger -> auto-completion ---
def test_approve_creates_statement_and_rolls_up_ledger(api):
    """PRD §3.6: "Approval sets the timesheet to APPROVED, records approved_by_user_id,
    and creates one earnings statement whose kind is WEEKLY in the FINALIZED ledger state
    ..."
    PRD §3.6: "realized_gross_bill_cents is the sum of their gross_bill_cents,
    realized_pay_cost_cents the sum of their total_pay_cost_cents, realized_margin_cents
    the sum of their gross_margin_cents ... The assignment's guaranteed_hours_consumed
    increases by the smaller of the week's worked hours ... or the contract's
    weekly_guaranteed_hours, and guaranteed_hours_remaining decreases by that same amount.
    The clinician's ytd_taxable_wages_cents and ytd_nontaxable_stipend_cents increase by
    the statement's amounts."

    Design: Difficulty/transitive_cascade/approve_timesheet_cascades_statement_ledger_and_autocompletes_assignment_depth4
    """
    ctx = setup_active_assignment(api, clock="2026-06-14", assignment_overrides={"term_weeks": 1})
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approved = approve_timesheet(api, ts["id"], ctx.fac_id)
    assert approved["status"] == "APPROVED" and approved["approved_by_user_id"] == ctx.fac_id
    st = statement_for_timesheet(api, ts["id"])
    assert st["kind"] == "WEEKLY" and st["status"] == "FINALIZED" and st["period_key_date"] == "2026-06-07"
    assert st["gross_bill_cents"] == 504000 and st["total_pay_cost_cents"] == 382132
    assert st["gross_margin_cents"] == 121868 and st["margin_pct"] == 0.2418
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["realized_gross_bill_cents"] == 504000 and asg["realized_pay_cost_cents"] == 382132
    assert asg["realized_margin_cents"] == 121868
    assert asg["guaranteed_hours_consumed"] == 36 and asg["guaranteed_hours_remaining"] == 0
    clin = get_clinician_data(api, ctx.clin_id)
    assert clin["ytd_taxable_wages_cents"] == 187200 and clin["ytd_nontaxable_stipend_cents"] == 160300


def test_approve_autocompletes_assignment_on_zero_remaining(api):
    """PRD §3.6: "If guaranteed_hours_remaining has now reached exactly 0, the assignment's
    staffing_status advances from ACTIVE to COMPLETED, the clinician's
    active_assignment_count decrements, and when that count reaches 0 the clinician's status
    returns to AVAILABLE."

    Design: Difficulty/transitive_cascade/approve_timesheet_cascades_statement_ledger_and_autocompletes_assignment_depth4
    """
    ctx = setup_active_assignment(api, clock="2026-06-14", assignment_overrides={"term_weeks": 1})
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["staffing_status"] == "COMPLETED"
    clin = get_clinician_data(api, ctx.clin_id)
    assert clin["active_assignment_count"] == 0 and clin["status"] == "AVAILABLE"


# --- Difficulty: money partition conserved across approve and compensating void ---
def test_ledger_after_two_approvals_holds_money_partition(api):
    """PRD §3.6: "the assignment's realized ledger is re-summed over its statements whose
    ledger status is FINALIZED or POSTED (reversed statements are excluded)"
    PRD §2.7: "the money-partition and guaranteed-hour partition invariants hold after both
    a forward action and its compensating reversal."

    Design: Difficulty/compensating_invariant/money_partition_conserved_across_timesheet_approve_and_void
    """
    ctx = setup_active_assignment(api, clock="2026-06-21")
    ts1 = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts1["id"], ctx.fac_id)
    ts2 = submit_timesheet(api, ctx.asg_id, "2026-06-14", [0, 11, 11, 11, 11, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts2["id"], ctx.fac_id)
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["realized_gross_bill_cents"] == 1148000
    assert asg["realized_pay_cost_cents"] == 825884
    assert asg["realized_margin_cents"] == 322116
    assert_assignment_money_partition(asg)
    clin = get_clinician_data(api, ctx.clin_id)
    assert clin["ytd_taxable_wages_cents"] == 426400 and clin["ytd_nontaxable_stipend_cents"] == 320600


def test_ledger_restored_with_zero_drift_after_void(api):
    """PRD §3.6: "Voiding sets the timesheet to VOIDED and the linked statement's ledger
    status from FINALIZED to REVERSED, dropping it from every finalized-or-posted roll-up.
    Every ledger increment from approval is then exactly undone: the assignment's
    realized_gross_bill_cents, realized_pay_cost_cents, and realized_margin_cents decrease
    by that statement's amounts and realized_margin_pct is recomputed ... and the
    clinician's ytd_taxable_wages_cents and ytd_nontaxable_stipend_cents decrease by the
    statement's amounts."

    Design: Difficulty/compensating_invariant/money_partition_conserved_across_timesheet_approve_and_void
    """
    ctx = setup_active_assignment(api, clock="2026-06-21")
    ts1 = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts1["id"], ctx.fac_id)
    ts2 = submit_timesheet(api, ctx.asg_id, "2026-06-14", [0, 11, 11, 11, 11, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts2["id"], ctx.fac_id)
    voided = validate_success(api.transition_timesheet(ts1["id"], {"to": "VOIDED"}, PAYROLL1), 200)
    assert voided["status"] == "VOIDED"
    st1 = statement_for_timesheet(api, ts1["id"])
    st2 = statement_for_timesheet(api, ts2["id"])
    assert st1["status"] == "REVERSED" and st2["status"] == "FINALIZED"
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["realized_gross_bill_cents"] == 644000
    assert asg["realized_pay_cost_cents"] == 443752
    assert asg["realized_margin_cents"] == 200248
    assert asg["realized_margin_pct"] == 0.3109
    assert_assignment_money_partition(asg)
    clin = get_clinician_data(api, ctx.clin_id)
    assert clin["ytd_taxable_wages_cents"] == 239200 and clin["ytd_nontaxable_stipend_cents"] == 160300


# --- Difficulty: realized margin is 0 (not undefined) on an empty statement set ---
def test_realized_margin_is_zero_on_empty_statement_set(api):
    """PRD §3.6: "realized_margin_pct is the realized margin divided by the realized gross
    bill rounded half up to four decimal places, or exactly 0 when the realized gross bill
    is 0."

    Design: Difficulty/boundary_precision_check/realized_margin_is_zero_not_undefined_on_empty_statement_set
    """
    ctx = setup_active_assignment(api, clock="2026-06-14")
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["realized_gross_bill_cents"] == 0
    assert asg["realized_pay_cost_cents"] == 0
    assert asg["realized_margin_cents"] == 0
    assert asg["realized_margin_pct"] == 0


def test_projected_fields_populated_with_no_statements(api):
    """PRD §3.3: "Multiplying each weekly figure by term_weeks gives
    projected_pay_cost_cents and projected_gross_bill_cents; projected_margin_cents is the
    projected gross bill minus the projected pay cost; and projected_margin_pct is the
    projected margin divided by the projected gross bill, rounded half up to four decimal
    places, as a display value only."

    Design: Difficulty/boundary_precision_check/realized_margin_is_zero_not_undefined_on_empty_statement_set
    """
    ctx = setup_active_assignment(api, clock="2026-06-14")
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["projected_gross_bill_cents"] == 6552000
    assert asg["projected_pay_cost_cents"] == 4967716
    assert asg["projected_margin_cents"] == 1584284
    assert asg["projected_margin_pct"] == 0.2418
    data, meta = statements_for_assignment(api, ctx.asg_id)
    assert data == [] and meta["total_count"] == 0 and meta["has_more"] is False

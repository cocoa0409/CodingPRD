"""Time logging, hour-bank accounting, and invoice pricing.

Translates difficulty instances time_entry_billable (boundary 6.B), invoice
dual-variant (1.A) and round-per-tier (2.A), plus corner calculations
(cycle_balance, invoice with surcharge+credit), the derived-field billed_hours
reconciliation, and the time-entry / assign / complete / invoice validations.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_time_entry_payload, create_invoice_payload, create_task_payload,
    setup_active_client_engagement, setup_active_client_with_active_addon,
    create_assigned_task, create_in_progress_task, create_task,
    log_time, log_and_approve_time, open_cycle_for_client, close_open_cycle,
    create_sla_policy_payload,
    assert_time_entry, assert_invoice,
    TEST_USERS, make_client_headers,
)

SM = TEST_USERS["staffing_manager_headers"]


# ─── time_entry_billable ceil-at-grid (difficulty 6.B) ──────────────────────
def test_time_entry_billable_ceil_at_fifteen_minute_grid(api):
    """PRD §3.5: "Billable hours round the raw wall-time **up** onto a 15-minute grid: the raw minutes are divided by 15 and rounded up to the next whole number of quarter-hours, and that quarter-hour count is multiplied by 0.25 to yield hours. Thus 1 minute and 15 minutes both bill as 0.25 hour, while 16 minutes bills as 0.5 hour"

    Design: Difficulty/boundary_precision_check/time_entry_billable_ceil_at_fifteen_minute_grid
    """
    ctx = setup_active_client_engagement(skill_code="TRANSCRIPTION")
    task = create_in_progress_task(ctx)
    te15 = validate_success(api.create_time_entry(
        create_time_entry_payload(task["id"], raw_minutes=15), ctx["va_headers"]), 201)
    assert_time_entry(te15)
    assert te15["billable_hours"] == pytest.approx(0.25, abs=1e-9)
    te16 = validate_success(api.create_time_entry(
        create_time_entry_payload(task["id"], raw_minutes=16), ctx["va_headers"]), 201)
    assert te16["billable_hours"] == pytest.approx(0.5, abs=1e-9)


def test_time_entry_billable_one_minute_bills_quarter_hour(api):
    """PRD §3.5: "Thus 1 minute and 15 minutes both bill as 0.25 hour, while 16
    minutes bills as 0.5 hour."

    Design: Difficulty/boundary_precision_check/time_entry_billable_ceil_at_fifteen_minute_grid
    """
    ctx = setup_active_client_engagement(skill_code="TRANSCRIPTION2")
    task = create_in_progress_task(ctx)
    te = validate_success(api.create_time_entry(
        create_time_entry_payload(task["id"], raw_minutes=1), ctx["va_headers"]), 201)
    assert te["billable_hours"] == pytest.approx(0.25, abs=1e-9)


# ─── cycle_balance input-set filtering (corner) ─────────────────────────────
def test_cycle_balance_excludes_logged_and_rejected_entries(api):
    """PRD §3.5: "The cycle balance is an aggregation over **only** the `APPROVED` entries pinned to that cycle (`LOGGED` and `REJECTED` entries are excluded): `consumed_hours` is the sum of those entries' `billable_hours`; the cycle's notional bank is its `granted_hours` plus its `rolled_in_hours`; `available_hours` is the bank minus `consumed_hours` but never below 0; and `overage_hours` is `consumed_hours` minus the bank but never below 0"

    Design: Corner/calculations/cycle_balance_excludes_logged_and_rejected_entries
    """
    ctx = setup_active_client_engagement(skill_code="LEDGER")
    task = create_in_progress_task(ctx, estimated_hours=6)
    # APPROVED 4.0h
    log_and_approve_time(ctx, task["id"], 240)
    # LOGGED 2.0h (left un-approved)
    log_time(ctx, task["id"], 120)
    # REJECTED 1.0h
    rej = log_time(ctx, task["id"], 60)
    validate_success(api.reject_time_entry(rej["id"], ctx["client_headers"]), 200)
    cyc = open_cycle_for_client(ctx["client"]["id"])
    cyc = validate_success(api.get_cycle(cyc["id"], SM), 200)
    assert cyc["consumed_hours"] == pytest.approx(4.0, abs=1e-9)
    assert cyc["available_hours"] == pytest.approx(6.0, abs=1e-9)
    assert cyc["overage_hours"] == pytest.approx(0.0, abs=1e-9)


# ─── billed_hours derived-field reconciliation (corner) ─────────────────────
def test_task_billed_hours_reconciled_after_approval(api):
    """PRD §3.5: "The task's `billed_hours` is the sum of `billable_hours` over its `APPROVED` entries"

    Design: Corner/cross_cutting_complexity_layers/task_billed_hours_reconciled_after_approval
    """
    ctx = setup_active_client_engagement(skill_code="DFR_SK")
    task = create_in_progress_task(ctx)
    log_and_approve_time(ctx, task["id"], 60)  # raw 60 -> 1.0h
    after = validate_success(api.get_task(task["id"], SM), 200)
    assert after["billed_hours"] == pytest.approx(1.0, abs=1e-9)


# ─── Invoice dual variant: PROVISIONAL vs FINAL (difficulty 1.A) ────────────
def test_invoice_provisional_counts_logged_final_excludes_logged(api):
    """PRD §3.8: "PROVISIONAL` counts every time entry on the cycle whose status is either `LOGGED` or `APPROVED` (it optimistically counts hours not yet approved, so with any logged entry present a provisional total is at least the final total for the same data), whereas `FINAL` counts only `APPROVED` entries"
    PRD §3.8: "base_charge_cents` is within-bank hours times the client's `base_rate_cents".

    Design: Difficulty/dual_variant_calc/invoice_provisional_counts_logged_final_excludes_logged
    """
    ctx = setup_active_client_engagement(
        skill_code="BOOKKEEPING", monthly_retainer_hours=8,
        base_rate_cents=5000, overage_rate_cents=8000)
    task = create_in_progress_task(ctx, estimated_hours=4)
    log_and_approve_time(ctx, task["id"], 240)  # APPROVED 4.0h
    log_time(ctx, task["id"], 120)              # LOGGED 2.0h
    cyc = open_cycle_for_client(ctx["client"]["id"])
    # PROVISIONAL while cycle OPEN: billed = 4.0 + 2.0 = 6.0h within 8h bank.
    inv = validate_success(api.create_invoice(
        create_invoice_payload(ctx["client"]["id"], cyc["id"], variant="PROVISIONAL"), SM), 201)
    assert_invoice(inv)
    assert inv["variant"] == "PROVISIONAL"
    assert inv["base_charge_cents"] == 30000
    assert inv["overage_charge_cents"] == 0
    assert inv["total_cents"] == 30000


def test_invoice_final_excludes_logged_entries(api):
    """PRD §3.8: "FINAL counts only APPROVED entries."
    PRD §3.8: "a `FINAL` invoice is drawn after the cycle is sealed to actually bill the client and requires the cycle to be `CLOSED".

    Design: Difficulty/dual_variant_calc/invoice_provisional_counts_logged_final_excludes_logged
    """
    ctx = setup_active_client_engagement(
        skill_code="BOOKKEEPING_F", monthly_retainer_hours=8,
        base_rate_cents=5000, overage_rate_cents=8000)
    task = create_in_progress_task(ctx, estimated_hours=4)
    log_and_approve_time(ctx, task["id"], 240)  # APPROVED 4.0h
    # No LOGGED entry left un-approved (a LOGGED entry would block cycle close).
    _, cyc = close_open_cycle(ctx["client"]["id"])
    inv = validate_success(api.create_invoice(
        create_invoice_payload(ctx["client"]["id"], cyc["id"], variant="FINAL"), SM), 201)
    assert inv["variant"] == "FINAL"
    # Only APPROVED 4.0h billed: 4.0 * 5000 = 20000.
    assert inv["base_charge_cents"] == 20000
    assert inv["total_cents"] == 20000


# ─── Invoice round-per-tier-then-sum (difficulty 2.A) ───────────────────────
def test_invoice_round_per_tier_then_sum_pinned_order(api):
    """PRD §3.8: "Each tier is then priced and rounded half-up to whole cents before any summing: `base_charge_cents` is within-bank hours times the client's `base_rate_cents`, and `overage_charge_cents` is overage hours times the client's `overage_rate_cents"
    PRD §3.8: "Finally `utilization_pct` is the billed hours divided by the bank, rounded half-up to four decimal places"

    Design: Difficulty/combinatorial_formula/invoice_round_per_tier_then_sum_pinned_order
    """
    ctx = setup_active_client_engagement(
        skill_code="DATA_ENTRY", monthly_retainer_hours=10,
        base_rate_cents=5000, overage_rate_cents=8000)
    task = create_in_progress_task(ctx, estimated_hours=6)
    log_and_approve_time(ctx, task["id"], 360)  # APPROVED 6.0h
    log_and_approve_time(ctx, task["id"], 360)  # APPROVED 6.0h -> billed 12.0h
    _, cyc = close_open_cycle(ctx["client"]["id"])
    inv = validate_success(api.create_invoice(
        create_invoice_payload(ctx["client"]["id"], cyc["id"], variant="FINAL"), SM), 201)
    # within-bank 10h * 5000 = 50000; overage 2h * 8000 = 16000; total 66000.
    assert inv["base_charge_cents"] == 50000
    assert inv["overage_charge_cents"] == 16000
    assert inv["total_cents"] == 66000
    assert inv["utilization_pct"] == pytest.approx(1.2, abs=1e-9)


def test_invoice_within_bank_only_has_zero_overage_tier(api):
    """PRD §3.8: "those hours are split into a within-bank tier and an overage tier: within-bank hours are the lesser of billed hours and the cycle's bank (`granted_hours` plus `rolled_in_hours`), and overage hours are billed hours minus the bank, floored at 0"
    PRD §3.8: "base_charge_cents` is within-bank hours times the client's `base_rate_cents".

    Design: Difficulty/combinatorial_formula/invoice_round_per_tier_then_sum_pinned_order
    """
    ctx = setup_active_client_engagement(
        skill_code="DATA_ENTRY2", monthly_retainer_hours=10,
        base_rate_cents=5000, overage_rate_cents=8000)
    task = create_in_progress_task(ctx, estimated_hours=6)
    log_and_approve_time(ctx, task["id"], 360)  # APPROVED 6.0h, all within the 10h bank
    _, cyc = close_open_cycle(ctx["client"]["id"])
    inv = validate_success(api.create_invoice(
        create_invoice_payload(ctx["client"]["id"], cyc["id"], variant="FINAL"), SM), 201)
    # within-bank 6h * 5000 = 30000; no overage tier.
    assert inv["base_charge_cents"] == 30000
    assert inv["overage_charge_cents"] == 0
    assert inv["total_cents"] == 30000


# ─── Invoice surcharge + SLA credit (corner) ────────────────────────────────
def test_invoice_with_surcharge_and_sla_credit_correct_total(api):
    """PRD §3.8: "Next, `surcharge_cents` is computed: for each counted entry whose task's `required_skill_tag_id` matches the `skill_tag_id` of an `ACTIVE` add-on on the engagement, that entry's `billable_hours` is multiplied by that add-on's `surcharge_rate_cents`, the products are summed, and the sum is rounded half-up to whole cents"
    PRD §3.8: "The credit aggregates, over every task of the client that has at least one `APPROVED` time entry charged to the billed cycle and whose `sla_state` is `RESOLUTION_BREACHED`, the product of that task's `billed_hours`, the client's `base_rate_cents`, and the breach penalty fraction from the SLA policy for that task's priority; the sum is rounded half-up to whole cents"
    PRD §3.8: "The `total_cents` is `base_charge_cents` plus `overage_charge_cents` plus `surcharge_cents` minus `sla_credit_cents`, floored at 0"

    Design: Corner/calculations/invoice_with_surcharge_and_sla_credit_correct_total
    """
    ctx = setup_active_client_with_active_addon(
        skill_code="SPECIALIZED_TAX", surcharge_rate_cents=3000, breach_penalty_pct=0.25)
    task = create_in_progress_task(ctx, estimated_hours=4)
    log_and_approve_time(ctx, task["id"], 240)  # APPROVED 4.0h
    # Complete after resolution_due so sla_state latches RESOLUTION_BREACHED.
    validate_success(api.set_clock("2026-03-02T00:00:01Z", SM), 200)
    done = validate_success(api.complete_task(task["id"], ctx["va_headers"]), 200)
    assert done["sla_state"] == "RESOLUTION_BREACHED"
    _, cyc = close_open_cycle(ctx["client"]["id"])
    inv = validate_success(api.create_invoice(
        create_invoice_payload(ctx["client"]["id"], cyc["id"], variant="FINAL"), SM), 201)
    # base 4.0*5000=20000; surcharge 4.0*3000=12000; credit 4.0*5000*0.25=5000;
    # total 20000+12000-5000 = 27000; utilization 4/10 = 0.4.
    assert inv["base_charge_cents"] == 20000
    assert inv["surcharge_cents"] == 12000
    assert inv["sla_credit_cents"] == 5000
    assert inv["total_cents"] == 27000
    assert inv["utilization_pct"] == pytest.approx(0.4, abs=1e-9)


# ─── Validations on the time / assign / complete / invoice paths (corner) ───
def test_assign_without_sla_policy_returns_sla_policy_missing(api):
    """PRD §3.4: "Assignment may proceed only when the client is `ACTIVE` and has a non-null `active_engagement_id` (otherwise `ERR_CLIENT_NOT_ACTIVE`); when an SLA policy exists for the task's `priority` tier (otherwise `ERR_SLA_POLICY_MISSING".

    Design: Corner/validations/assign_without_sla_policy_returns_sla_policy_missing
    """
    # STANDARD policy exists by default; create a PRIORITY task with no PRIORITY policy.
    ctx = setup_active_client_engagement(skill_code="SLA_SK")
    task = create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], priority="PRIORITY",
                       title="Pri task", as_headers=ctx["client_headers"])
    res = api.assign_task(task["id"], SM)
    validate_error(res, "ERR_SLA_POLICY_MISSING", expected_status=409)


def test_log_time_on_unassigned_task_returns_task_not_workable(api):
    """PRD §3.5: "An entry may be logged only on a task that is `ASSIGNED` or `IN_PROGRESS`, and only by the VA of that task's active engagement (otherwise `ERR_TASK_NOT_WORKABLE".

    Design: Corner/validations/log_time_on_unassigned_task_returns_task_not_workable
    """
    ctx = setup_active_client_engagement(skill_code="TNW_SK")
    task = create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], title="Tnw task",
                       as_headers=ctx["client_headers"])  # QUEUED, never assigned
    res = api.create_time_entry(create_time_entry_payload(task["id"], raw_minutes=30),
                                ctx["va_headers"])
    validate_error(res, "ERR_TASK_NOT_WORKABLE", expected_status=409)


def test_complete_without_approved_time_returns_no_approved_time(api):
    """PRD §3.4: "The VA **completes** an in-progress task (`IN_PROGRESS → DONE`), which is allowed only if the task already has at least one `APPROVED` time entry (otherwise `ERR_NO_APPROVED_TIME".

    Design: Corner/validations/complete_without_approved_time_returns_no_approved_time
    """
    ctx = setup_active_client_engagement(skill_code="NAT_SK")
    task = create_in_progress_task(ctx)
    log_time(ctx, task["id"], 30)  # LOGGED only, never approved
    res = api.complete_task(task["id"], ctx["va_headers"])
    validate_error(res, "ERR_NO_APPROVED_TIME", expected_status=409)


def test_addon_required_blocks_specialized_assign(api):
    """PRD §3.4: "when the task's `required_skill_tag_id` names a specialized skill, when the active engagement holds an `ACTIVE` add-on for that skill (otherwise `ERR_ADDON_REQUIRED"

    Design: Corner/validations/addon_required_blocks_specialized_assign
    """
    ctx = setup_active_client_engagement(skill_code="SPEC_BLK", is_specialized=True)
    task = create_task(ctx["client"]["id"], skill_id=ctx["skill"]["id"], title="Sb task",
                       as_headers=ctx["client_headers"])
    res = api.assign_task(task["id"], SM)
    validate_error(res, "ERR_ADDON_REQUIRED", expected_status=409)


def test_addon_against_non_specialized_skill_returns_not_specialized(api):
    """PRD §3.6: "The referenced skill must be one whose `is_specialized` is true; requesting an add-on against a non-specialized skill is rejected with `ERR_NOT_SPECIALIZED"

    Design: Corner/validations/addon_against_non_specialized_skill_returns_not_specialized
    """
    from test_helpers import (create_skill_tag_payload, create_virtual_assistant_payload,
                              create_client_payload, scope_client_payload,
                              create_engagement_payload, unique_email)
    skill = validate_success(api.create_skill_tag(
        create_skill_tag_payload(code="PLAIN_SK", name="Plain", is_specialized=False), SM), 201)
    va = validate_success(api.create_virtual_assistant(
        create_virtual_assistant_payload(full_name="Va Ns", email=unique_email("vans"),
                                         skill_tag_ids=[skill["id"]]), SM), 201)
    client = validate_success(api.create_client(create_client_payload(company_name="Nsc"), SM), 201)
    ch = make_client_headers(client["id"])
    validate_success(api.scope_client(client["id"],
        scope_client_payload(required_skill_tag_ids=[skill["id"]]), ch), 200)
    eng = validate_success(api.create_engagement(
        create_engagement_payload(client["id"], va["id"]), SM), 201)
    res = api.create_addon(
        {"engagement_id": eng["id"], "skill_tag_id": skill["id"], "surcharge_rate_cents": 3000}, ch)
    validate_error(res, "ERR_NOT_SPECIALIZED", expected_status=422)


def test_final_invoice_on_open_cycle_returns_variant_state(api):
    """PRD §3.8: "Drawing the wrong variant for the cycle's state is rejected with `ERR_INVOICE_VARIANT_STATE"
    PRD §3.8: "a `FINAL` invoice is drawn after the cycle is sealed to actually bill the client and requires the cycle to be `CLOSED"

    Design: Corner/validations/final_invoice_on_open_cycle_returns_variant_state
    """
    ctx = setup_active_client_engagement(skill_code="IVS_SK")
    cyc = open_cycle_for_client(ctx["client"]["id"])  # still OPEN
    res = api.create_invoice(
        create_invoice_payload(ctx["client"]["id"], cyc["id"], variant="FINAL"), SM)
    validate_error(res, "ERR_INVOICE_VARIANT_STATE", expected_status=409)

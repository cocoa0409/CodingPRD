"""Compensating invariants: invoice voiding restores billed conservation, and
shot-report reversal restores lifetime-shot conservation (PRD §3.5, §3.7,
§3.9)."""
from test_helpers import (
    AFTER_PRESS_WINDOW,
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_eco,
    assess_eco,
    assert_build_job_invariants,
    complete_milestones_seq,
    file_eco,
    file_shot_report,
    file_warranty_claim,
    get_success_data,
    invoice_milestones_seq,
    make_customer_headers,
    set_clock,
    setup_booked_job,
    setup_tool_in_production,
    start_build,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]


def _setup_invoiced_job_with_eco():
    """Job IN_BUILD with milestone 1 EARNED then INVOICED (2,100,000); ECO
    (SHOP, affects_from_milestone_seq 1) assessed at 8.0 h / 100,000 /
    0 weeks -> total_charge 215,000."""
    ctx = setup_booked_job(company_name="Conserve Co", part_number="PN-1201")
    start_build(ctx["job"]["id"])
    complete_milestones_seq(ctx["milestones"], ctx["customer"]["id"], seqs=(1,))
    invoices = invoice_milestones_seq(ctx["milestones"], seqs=(1,))
    eco = file_eco(ctx["job"]["id"], requested_by="SHOP", affects_from_milestone_seq=1,
                   description="resize core")
    eco = assess_eco(eco["id"], rework_hours=8.0, scrapped_material_cost_cents=100_000,
                     lead_extension_weeks=0)
    assert eco["total_charge_cents"] == 215_000, (
        f"Setup step failed: ECO total_charge_cents {eco['total_charge_cents']} != 215000"
    )
    ctx["invoices"] = invoices
    ctx["eco"] = eco
    return ctx


def test_invoice_void_restores_billed_conservation(api):
    """PRD §3.4: "`billed_cents` is the sum of `amount_cents` over the job's
    invoices not in `VOID`"
    PRD §3.7: "Each reopened milestone's invoices in `ISSUED` or
    `PARTIALLY_PAID` transition to `VOID` with `void_reason` set to
    ECO_REWORK."

    Design: Difficulty/compensating_invariant/invoice_void_restores_billed_conservation
    """
    ctx = _setup_invoiced_job_with_eco()
    job_id = ctx["job"]["id"]
    invoice_id = ctx["invoices"][1]["id"]

    job_before = get_success_data(api_client.get_build_job(job_id, PM))
    assert job_before["billed_cents"] == 2_100_000, (
        f"Setup step failed: billed_cents {job_before['billed_cents']} != 2100000"
    )

    approve_eco(ctx["eco"]["id"], ctx["customer"]["id"])

    invoice = get_success_data(api_client.get_progress_invoice(invoice_id, PM))
    assert invoice["status"] == "VOID"
    assert invoice["void_reason"] == "ECO_REWORK"

    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["billed_cents"] == 0, (
        f"compensating void must restore billed_cents to 0, got {job['billed_cents']}"
    )
    milestone = get_success_data(
        api_client.get_build_milestone(ctx["milestones"][0]["id"], PM)
    )
    assert milestone["status"] == "REOPENED"
    assert milestone["completed_at"] is None
    assert_build_job_invariants(job)


def test_replan_after_void_sums_exactly_to_rebaselined_contract(api):
    """PRD §3.7: "Replanning follows the pinned rounding order of §3.5 against
    the new contract value: milestones in `PENDING` or `REOPENED` get fresh
    per-line amounts rounded half-up, milestones in `EARNED`, `INVOICED`, or
    `PAID` keep their locked `planned_amount_cents`, and the highest-`seq`
    milestone in the replanned set absorbs the remainder so all six planned
    amounts sum exactly to the new `contract_value_cents`."
    PRD §3.7: "The job's `contract_value_cents` increases by
    `total_charge_cents`."

    Design: Difficulty/compensating_invariant/invoice_void_restores_billed_conservation
    """
    ctx = _setup_invoiced_job_with_eco()
    job_id = ctx["job"]["id"]

    approve_eco(ctx["eco"]["id"], ctx["customer"]["id"])

    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["contract_value_cents"] == 10_715_000

    milestones = {m["seq"]: m for m in
                  get_success_data(api_client.list_build_milestones(
                      PM, params={"build_job_id": job_id, "limit": 100}))}
    assert milestones[1]["planned_amount_cents"] == 2_143_000
    assert milestones[2]["planned_amount_cents"] == 2_678_750
    assert milestones[3]["planned_amount_cents"] == 2_678_750
    assert milestones[4]["planned_amount_cents"] == 1_607_250
    assert milestones[5]["planned_amount_cents"] == 1_071_500
    # Seq 6 is the highest-seq replanned milestone and absorbs the remainder.
    assert milestones[6]["planned_amount_cents"] == 535_750
    total = sum(m["planned_amount_cents"] for m in milestones.values())
    assert total == 10_715_000 == job["contract_value_cents"], (
        f"planned amounts must sum exactly to the contract, got {total}"
    )


def test_shot_report_reversal_restores_lifetime_shots(api):
    """PRD §3.9: "A report can be backed out only by the compensating reverse
    action, which moves it from `ACTIVE` to `REVERSED` (reversing a
    non-`ACTIVE` report is `ERR_INVALID_STATE`) and subtracts its shots from
    `reported_shots`. Reversal is a conserved-quantity operation — a report
    followed by its own reversal leaves `lifetime_shots` unchanged"

    Design: Difficulty/compensating_invariant/shot_report_reversal_conserves_lifetime_shots
    """
    ctx = setup_tool_in_production(
        company_name="Shots Co", part_number="PN-1202", tracking_number="TRK-SH1"
    )
    set_clock(AFTER_PRESS_WINDOW)
    tool_id = ctx["tool"]["id"]
    customer_id = ctx["customer"]["id"]

    report = file_shot_report(tool_id, customer_id,
                              report_period_end="2026-08-20T00:00:00Z",
                              shots_in_period=50_000)
    tool = get_success_data(api_client.get_tool_asset(tool_id, PM))
    assert tool["lifetime_shots"] == 50_500, (
        f"500 tryout + 50,000 reported, got {tool['lifetime_shots']}"
    )

    reversed_report = validate_success(
        api_client.reverse_shot_report(report["id"], make_customer_headers(customer_id)),
        200,
    )
    assert reversed_report["status"] == "REVERSED"

    tool = get_success_data(api_client.get_tool_asset(tool_id, PM))
    assert tool["lifetime_shots"] == 500, (
        f"reversal must restore the conserved quantity exactly, got "
        f"{tool['lifetime_shots']}"
    )
    assert tool["reported_shots"] == 0
    assert tool["tryout_shots"] == 500


def test_reversal_blocked_when_it_would_invalidate_a_filed_claim(api):
    """PRD §3.9: "Reversal is a conserved-quantity operation — a report
    followed by its own reversal leaves `lifetime_shots` unchanged — and it is
    guarded: reversing a report of S shots is blocked with
    `ERR_SHOT_REVERSAL_BLOCKED` whenever any warranty claim against the tool
    in `FILED` or `REPAIR_SCHEDULED` carries a `claimed_at_shot_count`
    strictly greater than the tool's `lifetime_shots` minus S, because the
    reversal would invalidate a claim already filed in good faith."

    Design: Difficulty/compensating_invariant/shot_report_reversal_conserves_lifetime_shots
    """
    ctx = setup_tool_in_production(
        company_name="Shots Co", part_number="PN-1202", tracking_number="TRK-SH1"
    )
    set_clock(AFTER_PRESS_WINDOW)
    tool_id = ctx["tool"]["id"]
    customer_id = ctx["customer"]["id"]

    report = file_shot_report(tool_id, customer_id,
                              report_period_end="2026-08-21T00:00:00Z",
                              shots_in_period=60_000)
    tool = get_success_data(api_client.get_tool_asset(tool_id, PM))
    assert tool["lifetime_shots"] == 60_500

    claim = validate_success(
        file_warranty_claim(tool_id, customer_id, estimated_repair_cost_cents=80_000,
                            defect_description="wear"),
        201,
    )
    assert claim["claimed_at_shot_count"] == 60_500

    # Reversing 60,000 shots would leave 500 < the claim's 60,500 snapshot.
    res = api_client.reverse_shot_report(report["id"], make_customer_headers(customer_id))
    error = validate_error(res, ApiErrorId.ERR_SHOT_REVERSAL_BLOCKED)
    assert error["error_id"] == "ERR_SHOT_REVERSAL_BLOCKED"
    assert res.status_code == 409

    tool = get_success_data(api_client.get_tool_asset(tool_id, PM))
    assert tool["lifetime_shots"] == 60_500, (
        "a blocked reversal must leave lifetime_shots unchanged"
    )
    report_after = get_success_data(api_client.get_shot_report(report["id"], PM))
    assert report_after["status"] == "ACTIVE"

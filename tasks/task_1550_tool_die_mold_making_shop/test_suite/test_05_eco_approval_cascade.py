"""ECO approval four-hop cascade: authorization, re-baseline, invoice voids,
job/tool regression (PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    approve_eco,
    assess_eco,
    assert_build_job_invariants,
    drive_job_to_buyoff_passed,
    file_eco,
    get_success_data,
    invoice_milestones_seq,
    setup_booked_job,
)

PM = TEST_USERS["project_manager_headers"]


def _setup_assessed_eco():
    """Job at BUYOFF_PASSED (contract 10,500,000): milestones 1-5 EARNED,
    milestone 4 INVOICED with an open 1,575,000 invoice; ECO (SHOP,
    affects_from_milestone_seq 4) assessed at 4.0 h / 50,000 / 1 week ->
    total_charge 107,500."""
    ctx = setup_booked_job(company_name="Cascade Co", part_number="PN-6001")
    drive_job_to_buyoff_passed(ctx)
    invoices = invoice_milestones_seq(ctx["milestones"], seqs=(4,))
    eco = file_eco(ctx["job"]["id"], requested_by="SHOP", affects_from_milestone_seq=4,
                   description="core pullback change")
    eco = assess_eco(eco["id"], rework_hours=4.0, scrapped_material_cost_cents=50_000,
                     lead_extension_weeks=1)
    assert eco["total_charge_cents"] == 107_500, (
        f"Setup step failed: ECO total_charge_cents {eco['total_charge_cents']} != 107500"
    )
    ctx["invoices"] = invoices
    ctx["eco"] = eco
    return ctx


def test_approval_creates_authorization_and_rebaselines_milestones(api):
    """PRD §3.7: "Exactly one rework authorization is created for the change,
    starting in `AUTHORIZED` with `authorized_cost_cents` snapshotted from
    `total_charge_cents` and both `engineering_change_id` and `build_job_id`
    set."
    PRD §3.7: "The job's `contract_value_cents` increases by
    `total_charge_cents`. Every milestone whose `seq` is at or beyond
    `affects_from_milestone_seq` and whose status is `EARNED` or `INVOICED`
    reopens to `REOPENED`, clearing `completed_at` to null; milestones in
    `PENDING` at or beyond that sequence keep their status but are replanned."
    PRD §3.4: "`open_eco_count` counts the job's engineering changes sitting
    in `SUBMITTED`, `IMPACT_ASSESSED`, or `APPROVED`."

    Design: Difficulty/transitive_cascade/eco_approval_four_hop_cascade
    """
    ctx = _setup_assessed_eco()
    eco = ctx["eco"]
    job_id = ctx["job"]["id"]

    approve_eco(eco["id"], ctx["customer"]["id"])

    # Hop 1: exactly one authorization, snapshotted at total_charge_cents.
    auths = get_success_data(
        api_client.list_rework_authorizations(
            PM, params={"engineering_change_id": eco["id"], "limit": 100}
        )
    )
    assert len(auths) == 1, f"expected exactly 1 rework authorization, got {len(auths)}"
    assert auths[0]["status"] == "AUTHORIZED"
    assert auths[0]["authorized_cost_cents"] == 107_500
    assert auths[0]["build_job_id"] == job_id

    # Hop 2: contract re-baselined; m4/m5 reopened; m6 replanned as absorber.
    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["contract_value_cents"] == 10_607_500
    assert job["open_eco_count"] == 1

    milestones = {m["seq"]: m for m in
                  get_success_data(api_client.list_build_milestones(
                      PM, params={"build_job_id": job_id, "limit": 100}))}
    assert milestones[4]["status"] == "REOPENED"
    assert milestones[4]["completed_at"] is None
    assert milestones[5]["status"] == "REOPENED"
    assert milestones[4]["planned_amount_cents"] == 1_591_125
    assert milestones[5]["planned_amount_cents"] == 1_060_750
    # The highest-seq replanned milestone absorbs the remainder so the six
    # planned amounts sum exactly to the new contract (PRD §3.7 hop 2).
    assert milestones[6]["status"] == "PENDING"
    assert milestones[6]["planned_amount_cents"] == 605_625
    total = sum(m["planned_amount_cents"] for m in milestones.values())
    assert total == 10_607_500, f"planned amounts must sum to contract, got {total}"
    # Milestones below the reopen scope are untouched and keep locked amounts.
    assert milestones[1]["status"] == "EARNED"
    assert milestones[1]["planned_amount_cents"] == 2_100_000


def test_approval_voids_open_invoices_and_regresses_job_and_tool(api):
    """PRD §3.7: "Each reopened milestone's invoices in `ISSUED` or
    `PARTIALLY_PAID` transition to `VOID` with `void_reason` set to
    ECO_REWORK."
    PRD §3.7: "The job's `billed_cents` is recomputed and drops the voided
    amounts."
    PRD §3.7: "If at least one milestone was reopened and the job was in
    `TRYOUT_PHASE`, `BUYOFF_PASSED`, or `READY_TO_SHIP`, the job regresses to
    `IN_BUILD`, and the tool regresses with it — `physical_status` from
    `TRYOUT` or `AWAITING_SHIPMENT` back to `IN_BUILD`."

    Design: Difficulty/transitive_cascade/eco_approval_four_hop_cascade
    """
    ctx = _setup_assessed_eco()
    eco = ctx["eco"]
    job_id = ctx["job"]["id"]
    invoice_id = ctx["invoices"][4]["id"]

    job_before = get_success_data(api_client.get_build_job(job_id, PM))
    assert job_before["billed_cents"] == 1_575_000

    approve_eco(eco["id"], ctx["customer"]["id"])

    invoice = get_success_data(api_client.get_progress_invoice(invoice_id, PM))
    assert invoice["status"] == "VOID", (
        f"open invoice of a reopened milestone must void, got {invoice['status']}"
    )
    assert invoice["void_reason"] == "ECO_REWORK"

    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["billed_cents"] == 0, (
        f"billed_cents must drop the voided amount, got {job['billed_cents']}"
    )
    assert job["status"] == "IN_BUILD", (
        f"job must regress from BUYOFF_PASSED to IN_BUILD, got {job['status']}"
    )

    tool = get_success_data(api_client.get_tool_asset(ctx["tool"]["id"], PM))
    assert tool["physical_status"] == "IN_BUILD", (
        f"tool must regress from AWAITING_SHIPMENT to IN_BUILD, got "
        f"{tool['physical_status']}"
    )
    assert_build_job_invariants(job)

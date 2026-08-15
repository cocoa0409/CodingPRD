"""Gang-run final invoice variant vs the provisional snapshot."""
from test_helpers import (
    TEST_USERS,
    accept_estimate,
    approve_proof,
    complete_bindery_and_deliver,
    complete_press_run,
    create_customer,
    create_estimate,
    create_gang_with_members,
    create_press,
    create_received_stock,
    gang_pair_signatures,
    get_success_data,
    lock_gang,
    quote_estimate,
    schedule_press_run,
    upload_proof,
    validate_success,
)

_PM = TEST_USERS["plant_manager_headers"]


def _setup_gang_pair(api):
    """Two PLATED jobs on stock S: J1 Q=4000 MR=100000 PERF, J2 Q=6000
    MR=120000 SCORE; gang on S/WEB/anchor 2026-08-20 with both members,
    LOCKED; gang run 10000 completed; J1 delivered 4000; invoice generated."""
    cust = create_customer(name="Gang Cust")
    stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=10000)
    est1 = create_estimate(
        cust["id"], gang_pair_signatures(stock["id"], 100000), quantity_ordered=4000,
        press_spoilage_pct=3, bindery_spoilage_pct=2, finishing_options=["PERF"],
        due_date="2026-08-20T00:00:00Z", job_name="G1",
    )
    est2 = create_estimate(
        cust["id"], gang_pair_signatures(stock["id"], 120000), quantity_ordered=6000,
        press_spoilage_pct=3, bindery_spoilage_pct=2, finishing_options=["SCORE"],
        due_date="2026-08-21T00:00:00Z", job_name="G2",
    )
    quote_estimate(est1["id"])
    quote_estimate(est2["id"])
    j1 = accept_estimate(est1["id"], cust["id"])
    j2 = accept_estimate(est2["id"], cust["id"])
    # Drive both to PLATED
    for job in (j1, j2):
        p = upload_proof(job["id"], file_uri=f"s3://{job['id']}.pdf")
        approve_proof(p["id"], cust["id"])
    gang = create_gang_with_members(stock["id"], [j1["id"], j2["id"]])
    gang = lock_gang(gang["id"])
    press = create_press(name="W1")
    run = schedule_press_run(press, gang_run_id=gang["id"], run_quantity=10000)
    complete_press_run(run["id"], gross_impressions=5000, sheets_used=5254, waste_sheets=100)
    complete_bindery_and_deliver(j1["id"], delivered_quantity=4000, pieces_completed=4000)
    inv = get_success_data(api.create_invoice({"job_id": j1["id"]}, _PM))
    return cust, stock, j1, j2, gang, inv


class TestGangFinalInvoiceVariant:
    def test_provisional_snapshot_unchanged_and_allocation_recorded(self, api):
        """PRD §3.3: on accept the job snapshots "`total_price_cents`" (the
        provisional value); PRD §3.7: "each member's
        `allocated_make_ready_cents` is computed by a waterfall" — the
        earliest-created member receives the remainder, giving 48000/72000
        against the max make-ready 120000.

        Design: Difficulty/dual_variant_calc/estimate_provisional_vs_gang_final_invoice
        """
        cust, stock, j1, j2, gang, inv = _setup_gang_pair(api)
        job_after = get_success_data(api.get_job(j1["id"], _PM))
        assert job_after["total_price_cents"] == 211418, (
            f"provisional snapshot must remain 211418, got {job_after['total_price_cents']}"
        )
        gang_after = get_success_data(api.get_gang_run(gang["id"], TEST_USERS["scheduler_headers"]))
        allocs = {m["job_id"]: m["allocated_make_ready_cents"] for m in gang_after["members"]}
        assert allocs[j1["id"]] == 48000
        assert allocs[j2["id"]] == 72000
        assert inv["gang_make_ready_allocated_cents"] == 48000

    def test_final_invoice_variant_rederives_tier_from_adjusted_subtotal(self, api):
        """PRD §3.12: "The gang-adjusted total re-runs the provisional pricing
        pipeline with the member's `allocated_make_ready_cents` substituted
        for the standalone make-ready total, and re-derives the discount tier
        from the adjusted subtotal before applying it." Substituting 48000 for
        100000 drops the adjusted subtotal to 159418 (0% tier), so
        base_amount_cents = 159418 — diverging from the 211418 provisional
        snapshot purely by variant selection.

        Design: Difficulty/dual_variant_calc/estimate_provisional_vs_gang_final_invoice
        """
        cust, stock, j1, j2, gang, inv = _setup_gang_pair(api)
        assert inv["base_amount_cents"] == 159418, (
            f"final variant must yield 159418, got {inv['base_amount_cents']}"
        )
        job_after = get_success_data(api.get_job(j1["id"], _PM))
        assert inv["base_amount_cents"] != job_after["total_price_cents"]
        assert inv["billable_quantity"] == 4000
        assert inv["total_due_cents"] == 159418

"""Final payment cascade: waterfall drives invoices to PAID, milestones
bubble up, and the lien release closes the job (PRD §3.5, §3.8)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_build_job_invariants,
    complete_milestones_seq,
    get_success_data,
    invoice_milestones_seq,
    record_job_payment,
    setup_tool_in_production,
)

PM = TEST_USERS["project_manager_headers"]


def _setup_delivered_job_with_final_invoices():
    """Tool IN_PRODUCTION, job SHIPPED, ownership SHOP_RETAINED; milestones
    1-4 PAID via the 8,925,000 payment; milestone 6 EARNED after delivery;
    invoices for milestones 5 (1,050,000) and 6 (525,000) ISSUED."""
    ctx = setup_tool_in_production(
        company_name="Payoff Co", part_number="PN-7001", tracking_number="TRK-C2"
    )
    complete_milestones_seq(ctx["milestones"], ctx["customer"]["id"], seqs=(6,))
    ctx["invoices"] = invoice_milestones_seq(ctx["milestones"], seqs=(5, 6))
    return ctx


def test_waterfall_pays_invoices_and_bubbles_milestones(api):
    """PRD §3.5: "An invoice whose balance is fully covered moves to `PAID` —
    with `paid_cents` equal to `amount_cents` and `balance_due_cents` zeroed —
    and an invoice partially covered moves from `ISSUED` to `PARTIALLY_PAID`;
    both recompute `paid_cents` and `balance_due_cents`. When every non-`VOID`
    invoice of a milestone is `PAID`, the milestone itself bubbles up from
    `INVOICED` to `PAID`."

    Design: Difficulty/transitive_cascade/final_payment_ownership_transfer_cascade
    """
    ctx = _setup_delivered_job_with_final_invoices()
    job_id = ctx["job"]["id"]

    record_job_payment(job_id, 1_575_000)

    for seq, amount in ((5, 1_050_000), (6, 525_000)):
        invoice = get_success_data(
            api_client.get_progress_invoice(ctx["invoices"][seq]["id"], PM)
        )
        assert invoice["status"] == "PAID", (
            f"invoice for milestone {seq} must be PAID, got {invoice['status']}"
        )
        assert invoice["paid_cents"] == amount
        assert invoice["balance_due_cents"] == 0

    milestones = {m["seq"]: m for m in
                  get_success_data(api_client.list_build_milestones(
                      PM, params={"build_job_id": job_id, "limit": 100}))}
    assert milestones[5]["status"] == "PAID"
    assert milestones[6]["status"] == "PAID"

    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["paid_cents"] == 10_500_000
    assert job["net_paid_cents"] == 10_500_000
    assert_build_job_invariants(job)


def test_final_payment_releases_lien_and_closes_job(api):
    """PRD §3.8: "The retention lien is released — `ownership_status` moving
    one-way from `SHOP_RETAINED` to `TRANSFERRED` — only when both conditions
    hold: `net_paid_cents` is at least `contract_value_cents`, an exact-cent
    test, and the tool's `physical_status` is `IN_PRODUCTION`. The evaluation
    runs after every recorded payment and at delivery; when transfer succeeds
    while the job is in `SHIPPED`, the job closes — `SHIPPED` to `CLOSED`."

    Design: Difficulty/transitive_cascade/final_payment_ownership_transfer_cascade
    """
    ctx = _setup_delivered_job_with_final_invoices()
    job_id = ctx["job"]["id"]
    tool_id = ctx["tool"]["id"]

    record_job_payment(job_id, 1_575_000)

    tool = get_success_data(api_client.get_tool_asset(tool_id, PM))
    assert tool["ownership_status"] == "TRANSFERRED", (
        f"lien must release at full payment in production, got {tool['ownership_status']}"
    )
    assert tool["physical_status"] == "IN_PRODUCTION"

    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["status"] == "CLOSED", (
        f"job must close when ownership transfers while SHIPPED, got {job['status']}"
    )
    assert job["paid_cents"] == 10_500_000
    assert job["net_paid_cents"] == 10_500_000

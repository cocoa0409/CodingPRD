"""ToolAsset parallel state dimensions: physical_status and ownership_status
advance on different triggers without disturbing each other (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_build_job_invariants,
    complete_milestones_seq,
    deliver_tool,
    drive_job_to_ready_to_ship,
    get_success_data,
    invoice_milestones_seq,
    record_job_payment,
    setup_booked_job,
    ship_tool,
)

PM = TEST_USERS["project_manager_headers"]


def test_ship_and_deliver_move_physical_status_while_ownership_stays_retained(api):
    """PRD §3.8: "Shipping stamps `shipped_at` alongside the carrier details,
    moves the tool from `AWAITING_SHIPMENT` to `IN_TRANSIT`, and moves the job
    from `READY_TO_SHIP` to `SHIPPED`."
    PRD §3.8: "The retention lien is released — `ownership_status` moving
    one-way from `SHOP_RETAINED` to `TRANSFERRED` — only when both conditions
    hold: `net_paid_cents` is at least `contract_value_cents`, an exact-cent
    test, and the tool's `physical_status` is `IN_PRODUCTION`."

    Design: Difficulty/non_linear_state_machine/tool_asset_parallel_dimensions_independent
    """
    ctx = setup_booked_job(company_name="Parallel Co", part_number="PN-5001")
    drive_job_to_ready_to_ship(ctx)
    tool_id = ctx["tool"]["id"]

    shipped = ship_tool(tool_id, tracking_number="TRK-P1")
    assert shipped["physical_status"] == "IN_TRANSIT"
    assert shipped["ownership_status"] == "SHOP_RETAINED", (
        "the lien survives shipment while the job is not fully paid"
    )
    job = get_success_data(api_client.get_build_job(ctx["job"]["id"], PM))
    assert job["status"] == "SHIPPED"

    delivered = deliver_tool(tool_id)
    assert delivered["physical_status"] == "IN_PRODUCTION"
    # net_paid 8,925,000 < contract 10,500,000: ownership must NOT transfer.
    assert delivered["ownership_status"] == "SHOP_RETAINED", (
        f"ownership must stay SHOP_RETAINED until paid in full, got "
        f"{delivered['ownership_status']}"
    )
    job = get_success_data(api_client.get_build_job(ctx["job"]["id"], PM))
    assert job["status"] == "SHIPPED"
    assert_build_job_invariants(job)


def test_final_payment_flips_ownership_while_physical_status_stays(api):
    """PRD §3.8: "The evaluation runs after every recorded payment and at
    delivery; when transfer succeeds while the job is in `SHIPPED`, the job
    closes — `SHIPPED` to `CLOSED`."
    PRD §3.8: "The retention lien is released — `ownership_status` moving
    one-way from `SHOP_RETAINED` to `TRANSFERRED` — only when both conditions
    hold: `net_paid_cents` is at least `contract_value_cents`, an exact-cent
    test, and the tool's `physical_status` is `IN_PRODUCTION`."

    Design: Difficulty/non_linear_state_machine/tool_asset_parallel_dimensions_independent
    """
    ctx = setup_booked_job(company_name="Parallel Co", part_number="PN-5001")
    drive_job_to_ready_to_ship(ctx)
    tool_id = ctx["tool"]["id"]
    job_id = ctx["job"]["id"]
    ship_tool(tool_id, tracking_number="TRK-P1")
    deliver_tool(tool_id)

    complete_milestones_seq(ctx["milestones"], ctx["customer"]["id"], seqs=(6,))
    invoice_milestones_seq(ctx["milestones"], seqs=(5, 6))
    record_job_payment(job_id, 1_575_000)

    tool = get_success_data(api_client.get_tool_asset(tool_id, PM))
    assert tool["ownership_status"] == "TRANSFERRED", (
        f"ownership must transfer once paid in full in production, got "
        f"{tool['ownership_status']}"
    )
    assert tool["physical_status"] == "IN_PRODUCTION"

    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["paid_cents"] == 10_500_000
    assert job["net_paid_cents"] == 10_500_000
    assert job["status"] == "CLOSED", (
        f"job must close on ownership transfer while SHIPPED, got {job['status']}"
    )
    milestones = {m["seq"]: m for m in
                  get_success_data(api_client.list_build_milestones(
                      PM, params={"build_job_id": job_id, "limit": 100}))}
    assert milestones[5]["status"] == "PAID"
    assert milestones[6]["status"] == "PAID"
    assert_build_job_invariants(job)

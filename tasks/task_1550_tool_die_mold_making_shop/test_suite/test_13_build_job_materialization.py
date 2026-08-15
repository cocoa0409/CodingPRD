"""Build-job creation materializes six milestones and one tool asset
(PRD §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_build_job,
    assert_build_job_invariants,
    assert_build_milestone,
    assert_tool_asset,
    create_accepted_quote,
    create_customer,
    create_released_design,
    get_success_data,
    list_job_milestones,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]


def test_build_job_creation_materializes_milestones_and_tool(api):
    """PRD §3.4: "Booking mints two things. First, the six canonical
    milestones, in `seq` order 1 through 6 with `code` values
    `DESIGN_COMPLETE`, `MATERIAL_STAGED`, `MACHINING_COMPLETE`,
    `T1_TRYOUT_DONE`, `BUYOFF_SIGNED`, and `DELIVERY_ACCEPTED`, carrying
    `billing_pct` values of 20, 25, 25, 15, 10, and 5 percent respectively."
    PRD §3.4: "Second, exactly one tool asset per job: a server-minted
    `serial_number` of the form TLT-<n>, `physical_status` `IN_BUILD`,
    `ownership_status` `SHOP_RETAINED`, `die_class` copied from the job,
    `warranty_terms` copied from the quote, `warranty_shot_limit` set by die
    class — 1,000,000 shots for `CLASS_101`, 500,000 for `CLASS_102`, 250,000
    for `CLASS_103`, 100,000 for `CLASS_104`, 10,000 for `CLASS_105` —
    `contract_snapshot_cents` equal to the contract value at creation, and
    `tryout_shots`, `reported_shots`, and `lifetime_shots` all zero with
    `warranty_expires_at` still null."
    PRD §3.5: "At job creation the planned amounts are computed in this pinned
    order: for sequences 1 through 5, the planned amount is the job's
    `contract_value_cents` multiplied by the line's `billing_pct` and divided
    by one hundred, rounded half-up to integer cents per line; sequence 6 then
    absorbs the remainder, so the six planned amounts sum exactly to the
    contract value."

    Design: Corner/entities/build_job_creation_materializes_milestones_and_tool
    """
    customer = create_customer(company_name="Mat Co")
    design = create_released_design(customer["id"], part_number="PN-MT1")
    quote = create_accepted_quote(customer["id"], design["id"], quote_kind="FIRM",
                                  requested_lead_weeks=12)
    assert quote["total_price_cents"] == 10_500_000

    res = api_client.create_build_job({"quote_id": quote["id"]}, PM)
    job = validate_success(res, 201)
    assert_build_job(job)
    assert job["status"] == "BOOKED"
    assert job["contract_value_cents"] == 10_500_000
    assert isinstance(job["version"], int)
    assert_build_job_invariants(job)

    milestones = list_job_milestones(job["id"])
    assert [m["seq"] for m in milestones] == [1, 2, 3, 4, 5, 6]
    assert [m["code"] for m in milestones] == [
        "DESIGN_COMPLETE", "MATERIAL_STAGED", "MACHINING_COMPLETE",
        "T1_TRYOUT_DONE", "BUYOFF_SIGNED", "DELIVERY_ACCEPTED",
    ]
    assert [m["billing_pct"] for m in milestones] == [20, 25, 25, 15, 10, 5]
    assert [m["planned_amount_cents"] for m in milestones] == [
        2_100_000, 2_625_000, 2_625_000, 1_575_000, 1_050_000, 525_000,
    ]
    for milestone in milestones:
        assert_build_milestone(milestone)
        assert milestone["status"] == "PENDING"
    assert sum(m["planned_amount_cents"] for m in milestones) == 10_500_000

    tools = get_success_data(
        api_client.list_tool_assets(PM, params={"build_job_id": job["id"], "limit": 100})
    )
    assert len(tools) == 1, f"exactly one tool asset per job, got {len(tools)}"
    tool = tools[0]
    assert_tool_asset(tool)
    assert tool["physical_status"] == "IN_BUILD"
    assert tool["ownership_status"] == "SHOP_RETAINED"
    assert tool["warranty_shot_limit"] == 250_000
    assert tool["contract_snapshot_cents"] == 10_500_000
    assert tool["tryout_shots"] == 0
    assert tool["reported_shots"] == 0
    assert tool["lifetime_shots"] == 0
    assert tool["warranty_expires_at"] is None
    assert tool["serial_number"] is not None
    assert tool["serial_number"].startswith("TLT-"), (
        f"serial_number must be of the form TLT-<n>, got {tool['serial_number']!r}"
    )

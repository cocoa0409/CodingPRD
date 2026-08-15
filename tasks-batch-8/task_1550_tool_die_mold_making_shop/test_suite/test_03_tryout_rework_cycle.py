"""Tryout rework cycle: REJECTED loops back to SCHEDULED with round_number
incremented and per-round fields reset (PRD §3.6)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_tryout_sample,
    buyoff_tryout_round,
    get_success_data,
    schedule_tryout_round,
    setup_booked_job,
    start_build,
    submit_tryout_round,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]


def _setup_rejected_round_one():
    """Job in TRYOUT_PHASE with round 1 submitted (500 shots) then REJECTED."""
    ctx = setup_booked_job(company_name="Cycle Co", part_number="PN-4001")
    start_build(ctx["job"]["id"])
    press, sample = schedule_tryout_round(ctx["job"]["id"])
    submit_tryout_round(
        sample["id"], sample_qty=30, shots_used=500, measured_report_ref="LAY-R1"
    )
    sample = buyoff_tryout_round(sample["id"], "REJECTED", defect_codes=["DIM_X_OUT"])
    ctx["sample"] = sample
    return ctx


def test_initiate_rework_increments_round_and_resets_round_fields(api):
    """PRD §3.6: "Initiating rework on a `REJECTED` sample returns it to
    `SCHEDULED`: `round_number` increases by one (T2, T3, and so on), and
    `sample_qty`, `shots_used`, `measured_report_ref`, and `defect_codes` are
    all reset to null for the new round."

    Design: Difficulty/non_linear_state_machine/tryout_rework_cycle_round_increment
    """
    ctx = _setup_rejected_round_one()
    sample_id = ctx["sample"]["id"]
    assert ctx["sample"]["status"] == "REJECTED"
    assert ctx["sample"]["round_number"] == 1

    reworked = validate_success(api_client.initiate_rework(sample_id, {}, PM), 200)

    assert_tryout_sample(reworked)
    assert reworked["round_number"] == 2, (
        f"round_number should increment to 2, got {reworked['round_number']}"
    )
    assert reworked["status"] == "SCHEDULED"
    for field in ("sample_qty", "shots_used", "measured_report_ref", "defect_codes"):
        assert reworked[field] is None, (
            f"{field} must be reset to null for the new round, got {reworked[field]!r}"
        )


def test_second_round_submit_accumulates_shots_and_buyoff_bubbles(api):
    """PRD §3.6: "Submission feeds the tool's life accounting: the tool's
    `tryout_shots` increases by `shots_used`, `lifetime_shots` is recomputed,
    and on the first submit the tool's `physical_status` moves from
    `IN_BUILD` to `TRYOUT`."
    PRD §3.6: "A `BOUGHT_OFF` decision moves the sample to its terminal state
    and bubbles upward — if the job is in `TRYOUT_PHASE` it advances to
    `BUYOFF_PASSED`, the tool moves from `TRYOUT` to `AWAITING_SHIPMENT`, and
    the warranty clock starts: `warranty_expires_at` is set to the buyoff
    instant plus 730 days."

    Design: Difficulty/non_linear_state_machine/tryout_rework_cycle_round_increment
    """
    ctx = _setup_rejected_round_one()
    sample_id = ctx["sample"]["id"]
    job_id = ctx["job"]["id"]
    tool_id = ctx["tool"]["id"]

    validate_success(api_client.initiate_rework(sample_id, {}, PM), 200)
    submit_tryout_round(
        sample_id, sample_qty=25, shots_used=300, measured_report_ref="LAY-R2"
    )
    final_sample = buyoff_tryout_round(sample_id, "BOUGHT_OFF")

    assert_tryout_sample(final_sample)
    assert final_sample["round_number"] == 2
    assert final_sample["status"] == "BOUGHT_OFF"
    assert final_sample["sample_qty"] == 25
    assert final_sample["defect_codes"] is None

    tool = get_success_data(api_client.get_tool_asset(tool_id, PM))
    assert tool["tryout_shots"] == 800, (
        f"tryout_shots should accumulate across rounds (500 + 300), got {tool['tryout_shots']}"
    )
    assert tool["lifetime_shots"] == 800
    assert tool["physical_status"] == "AWAITING_SHIPMENT"

    job = get_success_data(api_client.get_build_job(job_id, PM))
    assert job["status"] == "BUYOFF_PASSED", (
        f"buyoff should bubble the job to BUYOFF_PASSED, got {job['status']}"
    )

"""Where the rework loop stops and where the changeover clock bites: a fourth deink
pass on a batch already held three times, and a sixty-minute gap asked to swallow a
sixty-six-minute grade change.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, declare_tl_140, declare_tis_16, register_machine, register_permit,
    setup_cleaned_deink_batch, run_deink_pass, record_brightness, solids_rows,
    setup_approved_batch, schedule_run, queue_batch, furnish_line,
    machine_version, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
OPERATOR = TEST_USERS["operator_headers"]
ENV = TEST_USERS["env_officer_headers"]

PM_NAMEPLATE = {"wire_width_mm": 5600, "max_tons_per_hour": 20.00,
                "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
PASS_CHARGES = (40.0, 25.0, 5.0)


def test_a_fourth_deink_pass_is_refused_after_three_recorded_holds():
    """PRD §3.3: "Moving `DEINK_HOLD → DEINKING` requires the batch to be in `DEINK_HOLD`
    and requires `deink_pass_count` to be below 3; it replaces `caustic_kg`,
    `peroxide_kg` and `surfactant_kg` with the new pass's charges. Since the counter
    starts at 0, this allows three passes in total, and the pass that would be the fourth
    — attempted when `deink_pass_count` already reads 3 — is rejected with
    `ERR_DEINK_PASS_LIMIT` (HTTP 409)."
    PRD §3.3: "If the measured brightness falls short of `min_brightness_iso`, the batch
    goes `DEINKING → DEINK_HOLD` instead."
    PRD §3.3: "Both outcomes require the batch to be in `DEINKING`, or the request is
    rejected with `ERR_PULP_BATCH_INVALID_STATE`, and both share three side effects:
    `deink_pass_count` is incremented by one, the pass's chemical cost is added into
    `cumulative_chemical_cost`, and one solids-ledger row is appended with `source_kind`
    of `DEINK_SLUDGE`, `source_ref_id` pointing at this batch, `dry_solids_tons` equal to
    the pass's computed sludge tonnage, and `disposition` of `PENDING`."
    PRD §3.3: "A batch that cannot be brought to brightness is written off instead: a
    `MillPlanner` diverts it, `DEINK_HOLD → DIVERTED`, which requires the batch to be in
    `DEINK_HOLD` and sets both `final_accepted_tons` and `available_tons` to 0.000."

    Design: Corner/errors/a_fourth_deink_pass_is_refused_after_three_recorded_holds
    """
    set_clock("2026-08-01T00:00:00Z")
    bundle = setup_cleaned_deink_batch(tons_charged=1.000, measured_reject_tons=0.300,
                                       spec_overrides={"min_brightness_iso": 85.0})
    batch_id = bundle["batch"]["id"]
    for short_of_the_floor in (70.0, 75.0, 80.0):
        run_deink_pass(batch_id, *PASS_CHARGES)
        held = record_brightness(batch_id, short_of_the_floor)
        assert held["status"] == "DEINK_HOLD"

    response = api_client.deink_pulp_batch(
        batch_id, {"caustic_kg": 40.0, "peroxide_kg": 25.0, "surfactant_kg": 5.0},
        OPERATOR)
    validate_error(response, ApiErrorId.ERR_DEINK_PASS_LIMIT.value, 409)

    stuck = get_success_data(api_client.get_pulp_batch(batch_id, OPERATOR))
    assert stuck["status"] == "DEINK_HOLD", "the refused pass did not reopen the loop"
    assert stuck["deink_pass_count"] == 3
    assert stuck["brightness_iso"] == pytest.approx(80.0, abs=1e-6)
    assert stuck["final_accepted_tons"] is None
    sludge = solids_rows(source_ref_id=batch_id, source_kind="DEINK_SLUDGE")
    assert len(sludge) == 3, "three passes charged, three sludge rows, no fourth"
    assert all(row["disposition"] == "PENDING" for row in sludge)

    written_off = validate_success(api_client.divert_pulp_batch(batch_id, PLANNER))
    assert written_off["status"] == "DIVERTED", "diversion is the only way out"
    assert written_off["final_accepted_tons"] == pytest.approx(0.000, abs=1e-6)
    assert written_off["available_tons"] == pytest.approx(0.000, abs=1e-6)


def test_a_gap_six_minutes_short_of_the_changeover_refuses_the_grade_change():
    """PRD §3.4: "The plan must physically fit. The gap between the outgoing run's
    `window_end` and the incoming run's `window_start`, measured in whole minutes, must be
    at least the computed `transition_minutes`; the boundary is inclusive, so a gap exactly
    equal to the computed duration is acceptable, while a shorter gap is rejected with
    `ERR_TRANSITION_GAP_TOO_SHORT` (HTTP 409). Planning a grade change bumps the machine's
    `version` by one."
    PRD §3.4: "The sum of the base tier and the brightness penalty is then multiplied by
    the family multiplier and by the direction multiplier, the product is capped at a
    ceiling of 12.000 tons, and the result rounded half up to three decimal places becomes
    `transition_waste_tons`."
    PRD §3.4: "Finally, `transition_minutes` is the waste tonnage divided by the machine's
    `max_tons_per_hour` and multiplied by 60, rounded **up** to the next whole minute, plus
    the machine's `changeover_buffer_minutes` — the ceiling is applied after the tonnage has
    been rounded to three decimal places, not before."

    Design: Corner/errors/a_grade_change_gap_six_minutes_short_of_the_computed_transition_is_refused
    """
    set_clock("2026-08-01T00:00:00Z")
    register_permit()
    declare_tl_140(moisture_tolerance_pct=0.50, min_sct_kn_m=2.50, rank_order=10)
    tight = register_machine(name="PM1", **PM_NAMEPLATE)
    roomy = register_machine(name="PM3", **PM_NAMEPLATE)
    bundle = setup_approved_batch(tons_charged=20.000, measured_reject_tons=2.000,
                                  declare_spec=False)
    declare_tis_16(min_brightness_iso=85.0, requires_deink_pulp=True, rank_order=12)
    dip_batch = queue_batch("TIS_16", [furnish_line(bundle["lot"]["id"], 1.000)],
                            pulper_line="DIP_LINE")
    plans = {}
    for machine, incoming_start in ((tight, "2026-09-01T15:00:00Z"),
                                    (roomy, "2026-09-01T15:06:00Z")):
        outgoing = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                                window_start="2026-09-01T06:00:00Z",
                                window_end="2026-09-01T14:00:00Z", pulp_draw_tons=5.000)
        incoming = schedule_run(machine["id"], "TIS_16", dip_batch["id"],
                                window_start=incoming_start,
                                window_end="2026-09-01T19:00:00Z", pulp_draw_tons=0.500)
        plans[machine["id"]] = (outgoing, incoming, machine_version(machine["id"]))

    outgoing, incoming, version_before = plans[tight["id"]]
    response = api_client.create_grade_change(
        tight["id"], {"from_run_id": outgoing["id"], "to_run_id": incoming["id"],
                      "expected_machine_version": version_before}, PLANNER)
    validate_error(response, ApiErrorId.ERR_TRANSITION_GAP_TOO_SHORT.value, 409)
    assert machine_version(tight["id"]) == version_before, \
        "the refused plan bumped nothing"

    outgoing3, incoming3, version_before3 = plans[roomy["id"]]
    fits = validate_success(api_client.create_grade_change(
        roomy["id"], {"from_run_id": outgoing3["id"], "to_run_id": incoming3["id"],
                      "expected_machine_version": version_before3}, PLANNER), 201)

    assert fits["status"] == "PLANNED"
    assert fits["transition_waste_tons"] == pytest.approx(12.000, abs=1e-6)
    assert fits["transition_minutes"] == 66, \
        "sixty-six minutes is exactly what the identical machine was given"
    assert fits["from_product_code"] == "TL_140"
    assert fits["to_product_code"] == "TIS_16"
    assert machine_version(roomy["id"]) == version_before3 + 1

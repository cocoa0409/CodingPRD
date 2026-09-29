"""The two hardness indices, per-run margins, and the rework revision cycle."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_lot,
    api_client,
    assert_specimen_ledger,
    certify_lot,
    create_chamber,
    read_lot,
    read_test_run,
    rework_payload,
    schedule_test_run,
    setup_lot_with_completed_campaign,
    submit_results,
    validate_error,
    validate_success,
)

PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]

PRO_WRENCH = {
    "sku_code": "WR-17-PRO",
    "tool_family": "WRENCH",
    "channel": "PROFESSIONAL",
    "nominal_size_mm": 17,
    "alloy_grade": "CR_MO",
    "list_price_cents": 4200,
    "warranty_tier": "LIFETIME",
}
PRO_FURNACE = {
    "furnace_code": "FCE-1",
    "max_charge_kg": 900,
    "alloy_grades_supported": ["CR_V", "CR_MO", "S2"],
}
PRO_LOT = {"lot_code": "LOT-PRO-A", "unit_count": 500, "specimen_pool_total": 40}

HARDNESS_A_WINDOW = ("2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
HARDNESS_B_WINDOW = ("2026-08-03T09:30:00Z", "2026-08-03T10:30:00Z")
PRO_TORQUE_WINDOW = ("2026-08-03T11:00:00Z", "2026-08-03T12:00:00Z")
PRO_DIMENSIONAL_WINDOW = ("2026-08-03T13:00:00Z", "2026-08-03T14:00:00Z")
PRO_SALT_SPRAY_WINDOW = ("2026-08-04T00:00:00Z", "2026-08-11T00:00:00Z")
BAD_HARDNESS_WINDOW = ("2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")

REWORK_NOTE = "Regrind flats and re-temper the batch"


def _professional_wrench_battery():
    """A PROFESSIONAL CR_MO wrench lot walked to ASSEMBLED and put through its
    whole mandatory battery, with two HARDNESS runs of very different specimen
    counts so the two indices cannot coincide."""
    ctx = setup_lot_with_completed_campaign(
        sku_overrides=PRO_WRENCH,
        lot_overrides=PRO_LOT,
        furnace_overrides=PRO_FURNACE,
        charge_kg=800,
        soak_minutes=120,
    )
    chamber = create_chamber(chamber_code="SSC-1", coupon_capacity=24)
    lot_id = ctx["lot"]["id"]
    for stage in ("HEAT_TREATED", "MACHINED", "PLATED", "ASSEMBLED"):
        advance_lot(lot_id, stage)

    runs = {}
    runs["hardness_a"] = schedule_test_run(lot_id, "HARDNESS", 1, HARDNESS_A_WINDOW)
    submit_results(runs["hardness_a"]["id"], [50.0])
    runs["hardness_b"] = schedule_test_run(lot_id, "HARDNESS", 9, HARDNESS_B_WINDOW)
    submit_results(runs["hardness_b"]["id"], [53.0] * 9)
    runs["torque"] = schedule_test_run(lot_id, "PROOF_TORQUE", 2, PRO_TORQUE_WINDOW)
    submit_results(runs["torque"]["id"], [140.0, 141.0])
    runs["dimensional"] = schedule_test_run(lot_id, "DIMENSIONAL", 3, PRO_DIMENSIONAL_WINDOW)
    submit_results(runs["dimensional"]["id"], [0.04, -0.05, 0.03])
    runs["salt_spray"] = schedule_test_run(
        lot_id, "SALT_SPRAY", 2, PRO_SALT_SPRAY_WINDOW, chamber_id=chamber["id"]
    )
    submit_results(runs["salt_spray"]["id"], [180.0, 192.0])

    ctx["chamber"] = chamber
    ctx["runs"] = runs
    ctx["lot"] = read_lot(lot_id)
    return ctx


def test_pooled_and_sample_hardness_indices_diverge_on_the_same_lot():
    """A one-specimen run at 50.0 and a nine-specimen run at 53.0 give an
    equal-weight sample index of 51.50 and a specimen-weighted pooled index of
    52.70 from the identical input set.

    PRD §3.4: "`hardness_index_sample` is the **provisional in-process
    reading**: each qualifying run's mean is rounded half up to one decimal
    place first, and then those per-run means are averaged with equal weight and
    the average rounded half up to two decimal places, so a single-specimen run
    counts exactly as much as a nine-specimen run."

    Design: Difficulty/dual_variant_calc/lot_hardness_pooled_vs_sample_divergence
    """
    ctx = _professional_wrench_battery()
    lot = ctx["lot"]

    assert lot["hardness_index_sample"] == pytest.approx(51.50, abs=0.01)
    assert lot["hardness_index_pooled"] == pytest.approx(52.70, abs=0.01)
    assert lot["hardness_index_sample"] != lot["hardness_index_pooled"]


def test_only_the_pooled_hardness_index_is_allowed_to_certify():
    """The PROFESSIONAL CR_MO bar is 52.5 points; the sample index of 51.50
    falls short of it while the pooled index of 52.70 clears it, and the lot
    certifies.

    PRD §3.4: "Both are stored on every recompute and both are visible on the
    lot, but only the pooled figure is allowed to certify."

    Design: Difficulty/dual_variant_calc/lot_hardness_pooled_vs_sample_divergence
    """
    ctx = _professional_wrench_battery()
    assert ctx["lot"]["hardness_index_sample"] < 52.5
    assert ctx["lot"]["hardness_index_pooled"] >= 52.5

    certified = certify_lot(ctx["lot"]["id"])

    assert certified["cert_status"] == "CERTIFIED"
    assert certified["hardness_index_pooled"] == pytest.approx(52.70, abs=0.01)
    assert certified["hardness_index_sample"] == pytest.approx(51.50, abs=0.01)


def test_the_full_battery_records_its_signed_margins_and_closes_the_specimen_ledger():
    """A 17 mm PROFESSIONAL CR_MO wrench carries a 128.1 Nm bar, and each run's
    signed headroom is measured against its own pinned requirement.

    PRD §3.4: "The run also records `result_margin_pct`, a signed percentage of
    headroom rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/lot_hardness_pooled_vs_sample_divergence
    """
    ctx = _professional_wrench_battery()
    lot = ctx["lot"]
    runs = ctx["runs"]

    assert lot["proof_torque_required_nm"] == pytest.approx(128.1, abs=0.01)

    expected_margins = {
        "hardness_a": 0.00,
        "hardness_b": 6.00,
        "torque": 9.29,
        "dimensional": 66.67,
        "salt_spray": 7.14,
    }
    for key, margin in expected_margins.items():
        run = read_test_run(runs[key]["id"])
        assert run["status"] == "PASSED", f"{key} must pass"
        assert run["result_margin_pct"] == pytest.approx(margin, abs=0.01), key

    assert lot["specimens_consumed"] == 17
    assert lot["specimens_available"] == 23
    assert lot["specimens_committed"] == 0
    assert_specimen_ledger(lot)


def _rejected_wrench_lot():
    """A default BRANDED CR_MO wrench lot at MACHINED with one passing HARDNESS
    run and one failing one, so the mandatory-failure cascade has rejected it."""
    ctx = setup_lot_with_completed_campaign(lot_overrides={"specimen_pool_total": 40})
    lot_id = ctx["lot"]["id"]
    advance_lot(lot_id, "HEAT_TREATED")
    advance_lot(lot_id, "MACHINED")

    good = schedule_test_run(lot_id, "HARDNESS", 2, HARDNESS_A_WINDOW)
    ctx["good_run"] = submit_results(good["id"], [52.0, 53.0])
    bad = schedule_test_run(lot_id, "HARDNESS", 2, BAD_HARDNESS_WINDOW)
    ctx["bad_run"] = submit_results(bad["id"], [40.0, 41.0])
    ctx["lot"] = read_lot(lot_id)
    return ctx


def _rework(lot_id: str) -> dict:
    return validate_success(
        api_client.rework_production_lot(lot_id, rework_payload(rework_note=REWORK_NOTE), PP)
    )


def test_a_failing_hardness_run_reports_negative_headroom_against_the_alloy_minimum():
    """A CR_MO mean of 40.5 against a 50.0 point minimum is 19 percent short.

    PRD §3.4: "For the four pass-when-at-least types it is the governing
    statistic minus the requirement, divided by the requirement, multiplied by
    one hundred."

    Design: Difficulty/non_linear_state_machine/lot_parallel_process_and_cert_dimensions_with_rework_cycle
    """
    bad = _rejected_wrench_lot()["bad_run"]

    assert bad["status"] == "FAILED"
    assert bad["mean_reading"] == pytest.approx(40.5, abs=0.01)
    assert bad["governing_statistic"] == pytest.approx(40.5, abs=0.01)
    assert bad["requirement_value"] == pytest.approx(50.0, abs=0.01)
    assert bad["result_margin_pct"] == pytest.approx(-19.00, abs=0.01)


def test_the_rejection_moves_the_dossier_and_material_dimensions_but_not_the_routing_one():
    """The lot was advanced only as far as MACHINED; the mandatory failure
    rejects and quarantines it while the routing dimension stays put.

    PRD §3.2: "The dimensions evolve independently: a lot may sit at `ASSEMBLED`
    while its dossier is still `DRAFT`, or be `IN_TEST` while the metal has only
    reached `PLATED`."

    Design: Difficulty/non_linear_state_machine/lot_parallel_process_and_cert_dimensions_with_rework_cycle
    """
    lot = _rejected_wrench_lot()["lot"]

    assert lot["process_status"] == "MACHINED"
    assert lot["cert_status"] == "REJECTED"
    assert lot["disposition"] == "QUARANTINED"
    assert lot["rework_cycle_count"] == 0


def test_rework_regresses_routing_lifts_quarantine_and_discards_the_metallurgy():
    """Rework touches all three dimensions in one operation and wipes the
    hardness history the passing run had written.

    PRD §3.5: "Both hardness indices are reset to null, discarding the dossier's
    metallurgical history, and `rework_cycle_count` increments."

    Design: Difficulty/non_linear_state_machine/lot_parallel_process_and_cert_dimensions_with_rework_cycle
    """
    ctx = _rejected_wrench_lot()
    assert ctx["lot"]["hardness_index_pooled"] is not None

    reworked = _rework(ctx["lot"]["id"])

    assert reworked["process_status"] == "MACHINED"
    assert reworked["cert_status"] == "DRAFT"
    assert reworked["disposition"] == "IN_PROCESS"
    assert reworked["rework_cycle_count"] == 1
    assert reworked["hardness_index_sample"] is None
    assert reworked["hardness_index_pooled"] is None


def test_rework_does_not_return_destroyed_specimens_to_the_pool():
    """Four specimens were consumed by the two resolved runs; rework rewinds the
    dossier but destroyed material stays destroyed.

    PRD §3.4: "The run's `specimen_count` moves out of the lot's
    `specimens_committed` and into `specimens_consumed` — destroyed material
    does not come back."

    Design: Difficulty/non_linear_state_machine/lot_parallel_process_and_cert_dimensions_with_rework_cycle
    """
    reworked = _rework(_rejected_wrench_lot()["lot"]["id"])

    assert reworked["specimens_consumed"] == 4
    assert reworked["specimens_available"] == 36
    assert reworked["specimens_committed"] == 0
    assert reworked["specimen_pool_total"] == 40
    assert_specimen_ledger(reworked)


def test_the_reworked_dossier_reopens_only_when_the_next_run_is_scheduled():
    """Straight after rework the dossier is DRAFT, so certification is refused;
    scheduling the next run walks it back into IN_TEST.

    PRD §3.5: "Because the dossier is back at `DRAFT`, scheduling the next test
    run re-opens it into `IN_TEST`, and the revision cycle `DRAFT → IN_TEST →
    REJECTED → DRAFT` may be traversed until the rework limit bites."

    Design: Difficulty/non_linear_state_machine/lot_parallel_process_and_cert_dimensions_with_rework_cycle
    """
    lot_id = _rejected_wrench_lot()["lot"]["id"]
    _rework(lot_id)

    validate_error(
        api_client.certify_production_lot(lot_id, QE),
        ApiErrorId.ERR_LOT_CERT_STATE_INVALID,
        409,
    )
    assert read_lot(lot_id)["cert_status"] == "DRAFT"

    schedule_test_run(lot_id, "HARDNESS", 2, HARDNESS_A_WINDOW)

    assert read_lot(lot_id)["cert_status"] == "IN_TEST"

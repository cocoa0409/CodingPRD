"""The quality axis moving while the run axis stands still, and the two compensations —
the abort that returns everything the start took, and the rewinder's hard stop.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS,
    register_customer, register_machine, register_permit, setup_approved_batch,
    schedule_run, start_run, complete_run, wind_roll_set, wrap_roll_set,
    submit_order, schedule_order, solids_rows, solids_summary, fiber_balance,
    setup_available_lot, sublot, reel_reading,
)

PLANNER = TEST_USERS["planner_headers"]
LAB = TEST_USERS["lab_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
OPERATOR = TEST_USERS["operator_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
GULF_COAST = {"name": "Gulf Coast Box Co", "allocation_priority_tier": "P1",
              "max_roll_diameter_mm": 1400, "max_roll_width_mm": 2400,
              "wrap_spec": "KRAFT_ONLY"}
# Perfect endpoints, a heavy 20-ton middle reel exactly 10.0% over basis weight: the
# provisional pair never sees it, the tonnage-weighted mean cannot avoid it.
OFF_SPEC_MIDDLE_REELS = [reel_reading(1, 5.000, 140.0, 7.50, 2.50),
                         reel_reading(2, 20.000, 154.0, 7.50, 2.50),
                         reel_reading(3, 5.000, 140.0, 7.50, 2.50)]
# One 22.000-ton net sublot at 2.00 percent contamination: the mill fiber balance
# and the book-yield projection below are both stated against this single lot.
TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]


def _run_with_a_sequenced_order_and_a_wound_set():
    """RUNNING run on PM1 drawing 15.000 of an 18.000-ton batch, one 6.000-ton set."""
    register_permit()
    machine = register_machine(**PM1)
    bundle = setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000,
        lot_bundle=setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT))
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       pulp_draw_tons=15.000)
    customer = register_customer(**GULF_COAST)
    order = submit_order(customer, "TL_140", ordered_tons=6.00, roll_width_mm=2200,
                         roll_diameter_mm=1200, wrap_spec="KRAFT_ONLY")
    schedule_order(order["id"], run["id"])
    start_run(machine["id"], run["id"])
    roll_set = wind_roll_set(run["id"], slit_width_mm=2200, diameter_mm=1200,
                            roll_count=3, net_tons=6.000)
    return machine, bundle["batch"], run, order, roll_set


def _held_run_with_a_quarantined_set():
    machine, batch, run, order, roll_set = _run_with_a_sequenced_order_and_a_wound_set()
    complete_run(machine["id"], run["id"], OFF_SPEC_MIDDLE_REELS)
    wrap_roll_set(roll_set["id"], "KRAFT_ONLY")
    held = validate_success(api_client.hold_run(machine["id"], run["id"], LAB))
    return machine, run, order, roll_set, held


def test_the_hold_strikes_an_index_anyway_and_quarantines_the_wrapped_set():
    """PRD §3.5: "Holding, `PROVISIONAL → HELD`, is the mirror branch: it requires the
    quality axis to read `PROVISIONAL` and requires that the run has at least one off-spec
    reel or a certified quality index below 85.00."
    PRD §3.5: "It also computes and stores `certified_quality_index` — the number is
    struck whichever way the verdict goes."
    PRD §3.5: "Hop one flips every roll set of the run whose status is `WOUND`, `WRAPPED`
    or `ALLOCATED` to `QUARANTINED`, setting `quarantine_reason` to `RUN_HELD` and clearing
    `allocated_order_id`."

    Design: Corner/state_machines/quality_hold_quarantines_every_roll_set_of_the_run
    """
    machine, run, order, roll_set, held = _held_run_with_a_quarantined_set()

    assert held["quality_status"] == "HELD"
    assert held["run_status"] == "COMPLETED"
    assert held["provisional_quality_index"] == pytest.approx(100.00, abs=1e-6)
    assert held["certified_quality_index"] == pytest.approx(73.33, abs=1e-6)
    assert held["off_spec_reel_count"] == 1

    quarantined = get_success_data(api_client.get_roll_set(roll_set["id"], LAB))
    assert quarantined["status"] == "QUARANTINED"
    assert quarantined["quarantine_reason"] == "RUN_HELD"
    assert quarantined["allocated_order_id"] is None
    assert quarantined["rewind_count"] == 0

    untouched = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert untouched["status"] == "IN_PRODUCTION"
    assert untouched["allocated_tons"] == pytest.approx(0.000, abs=1e-6)
    assert untouched["shortfall_tons"] == pytest.approx(6.000, abs=1e-6)


def test_certifying_a_held_run_fails_on_the_quality_axis_not_the_run_axis():
    """PRD §3.5: "The two axes are checked separately, and this has a concrete consequence
    for error selection: a run that is `COMPLETED` on the run axis but `HELD` on the
    quality axis rejects a certification attempt on the **quality** axis with
    `ERR_QUALITY_INVALID_STATE` (HTTP 409), not on the run axis."
    PRD §3.5: "Certification, `PROVISIONAL → CERTIFIED`, is a `QualityLab` act with four
    requirements evaluated in this order: the quality axis must read `PROVISIONAL`; the
    acting `X-User-ID` must differ from the run's `started_by_user_id`, and an operator
    certifying their own run is rejected with `ERR_SOD_SAME_OPERATOR` (HTTP 409);
    `off_spec_reel_count` must be exactly 0; and the certified quality index must be at
    least 85.00."

    Design: Corner/state_machines/certify_on_a_completed_run_whose_quality_axis_is_held_hits_quality_state_rule
    """
    machine, run, _, _, held = _held_run_with_a_quarantined_set()
    assert held["started_by_user_id"] == OPERATOR["X-User-ID"]

    response = api_client.certify_run(machine["id"], run["id"], CERTIFIER)
    validate_error(response, ApiErrorId.ERR_QUALITY_INVALID_STATE.value, 409)

    after = get_success_data(api_client.get_run(run["id"], LAB))
    assert after["run_status"] == "COMPLETED"
    assert after["quality_status"] == "HELD"
    assert after["certified_by_user_id"] is None


def test_the_abort_returns_the_final_yield_scraps_the_rolls_and_frees_the_order():
    """PRD §3.5: "Aborting a run, `RUNNING → ABORTED`, is the planner's emergency stop and
    is the compensating action for the pulp draw. It subtracts `pulp_draw_tons` back out of
    the batch's `consumed_tons` and recomputes `available_tons`, so total fiber tonnage is
    conserved. Every roll set of the run in `WOUND` or `WRAPPED` flips to `SCRAPPED`, each
    appending a `MACHINE_BROKE` solids row carrying that set's `net_tons`. The quality axis
    is forced to `CONDEMNED` regardless of what it read before. Every customer order whose
    `scheduled_run_id` is this run returns to `SUBMITTED` with `scheduled_run_id` cleared
    and `deschedule_count` incremented."
    PRD §3.3: "`available_tons` is `final_accepted_tons` minus `consumed_tons` rounded to
    three decimal places while the batch is `APPROVED`, and reads 0.000 in every other
    status; at the instant of approval `consumed_tons` is still 0.000, so `available_tons`
    opens equal to `final_accepted_tons`."

    Design: Corner/state_machines/aborting_a_running_run_reverses_every_side_effect_of_start_with_no_drift
    """
    machine, batch, run, order, roll_set = _run_with_a_sequenced_order_and_a_wound_set()

    aborted = validate_success(api_client.abort_run(machine["id"], run["id"], PLANNER))
    assert aborted["run_status"] == "ABORTED"
    assert aborted["quality_status"] == "CONDEMNED"

    restored = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert restored["consumed_tons"] == pytest.approx(0.000, abs=1e-6)
    assert restored["available_tons"] == pytest.approx(18.000, abs=1e-6)
    assert restored["final_accepted_tons"] == pytest.approx(18.000, abs=1e-6)
    assert restored["provisional_accepted_tons"] == pytest.approx(16.880, abs=1e-6)

    scrapped = get_success_data(api_client.get_roll_set(roll_set["id"], OPERATOR))
    assert scrapped["status"] == "SCRAPPED"
    assert scrapped["net_tons"] == pytest.approx(6.000, abs=1e-6)

    broke = solids_rows(source_ref_id=run["id"], source_kind="MACHINE_BROKE")
    assert len(broke) == 1
    assert broke[0]["dry_solids_tons"] == pytest.approx(6.000, abs=1e-6)
    assert broke[0]["disposition"] == "PENDING"

    freed = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert freed["status"] == "SUBMITTED"
    assert freed["scheduled_run_id"] is None
    assert freed["deschedule_count"] == 1
    assert freed["allocated_tons"] == pytest.approx(0.000, abs=1e-6)
    assert freed["shortfall_tons"] == pytest.approx(6.000, abs=1e-6)

    balance = fiber_balance()
    assert balance["total_received_tons"] == pytest.approx(22.000, abs=1e-6)
    assert balance["total_consumed_tons"] == pytest.approx(20.000, abs=1e-6)
    assert balance["total_available_tons"] == pytest.approx(2.000, abs=1e-6)
    assert balance["imbalance_tons"] == pytest.approx(0.000, abs=1e-6)

    summary = solids_summary()
    assert summary["gross_solids_tons"] == pytest.approx(8.000, abs=1e-6)
    assert summary["reversed_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(8.000, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(8.000, abs=1e-6)


def test_two_laps_through_the_rewinder_are_enough_and_the_third_is_refused():
    """PRD §3.6: "A quarantined set goes to the rewinder, `QUARANTINED → REWOUND`, which
    requires `rewind_count` to be below 2 and increments it by one; two rewinds are
    therefore permitted and the third attempt, made when `rewind_count` already reads 2, is
    rejected with `ERR_REWIND_LIMIT` (HTTP 409)."
    PRD §3.6: "Completion replaces the four geometry and tonnage fields, clears
    `quarantine_reason`, recomputes the run's `produced_tons`, and — when the pre-rewind
    `net_tons` exceeds the new `net_tons` — appends one solids-ledger row with `source_kind`
    of `MACHINE_BROKE`, `source_ref_id` pointing at the producing run, and `dry_solids_tons`
    equal to exactly that difference, so solids are conserved across the rewind; when the
    difference is 0.000 no row is appended."

    Design: Corner/state_machines/third_rewind_of_the_same_roll_set_is_stopped_by_the_rewind_limit
    """
    machine, _, run, _, roll_set = _run_with_a_sequenced_order_and_a_wound_set()
    for slit, rolls, tons in ((1200, 8, 5.800), (1100, 16, 5.700)):
        validate_success(api_client.quarantine_roll_set(
            roll_set["id"], {"quarantine_reason": "SPEC_MISMATCH"}, LAB))
        validate_success(api_client.rewind_roll_set(roll_set["id"], OPERATOR))
        validate_success(api_client.rewind_complete_roll_set(
            roll_set["id"], {"slit_width_mm": slit, "diameter_mm": 1200,
                             "roll_count": rolls, "net_tons": tons}, OPERATOR))
    validate_success(api_client.quarantine_roll_set(
        roll_set["id"], {"quarantine_reason": "SPEC_MISMATCH"}, LAB))

    response = api_client.rewind_roll_set(roll_set["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_REWIND_LIMIT.value, 409)

    stuck = get_success_data(api_client.get_roll_set(roll_set["id"], OPERATOR))
    assert stuck["status"] == "QUARANTINED"
    assert stuck["rewind_count"] == 2
    assert stuck["slit_width_mm"] == 1100
    assert stuck["roll_count"] == 16
    assert stuck["net_tons"] == pytest.approx(5.700, abs=1e-6)
    assert stuck["quarantine_reason"] == "SPEC_MISMATCH"

    broke = solids_rows(source_ref_id=run["id"], source_kind="MACHINE_BROKE")
    assert sorted(row["dry_solids_tons"] for row in broke) == \
        [pytest.approx(0.100, abs=1e-6), pytest.approx(0.200, abs=1e-6)]
    assert solids_summary()["net_solids_tons"] == pytest.approx(2.300, abs=1e-6)

"""Nothing in this mill settles late: the body of a write already carries the figures it
caused, and a compensating cascade is complete before the aborting call returns.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    declare_tl_140, register_customer, register_machine, register_permit,
    setup_available_lot, queue_batch, furnish_line, schedule_run, start_run,
    wind_roll_set, submit_order, schedule_order, solids_rows, solids_summary,
    sublot, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
OPERATOR = TEST_USERS["operator_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
MILL_PERMIT = {"permit_number": "MILL-NPDES-1", "bod_limit_kg_per_day": 500.00,
               "tss_limit_kg_per_day": 400.00, "flow_limit_m3_per_day": 9000.00,
               "rolling_window_days": 30}
CLEAN_TRUCK = [sublot(1, 30.000, 8.000, 10.00, 2.00)]
SETTLED_FIELDS = ("status", "final_accepted_tons", "yield_variance_tons",
                  "available_tons", "provisional_accepted_tons", "version")


def test_the_clean_and_approve_bodies_already_carry_the_figures_they_caused():
    """PRD §3.3: "Cleaning stores the value and appends one row to the solids ledger with
    `source_kind` of `PULP_REJECT`, `source_ref_id` pointing at this batch, `dry_solids_tons`
    equal to `measured_reject_tons`, and `disposition` of `PENDING`."
    PRD §3.3: "`yield_variance_tons` is `final_accepted_tons` minus
    `provisional_accepted_tons`, rounded to three decimal places and signed — it may
    legitimately be negative."
    PRD §3.3: "`available_tons` is `final_accepted_tons` minus `consumed_tons` rounded to three
    decimal places while the batch is `APPROVED`, and reads 0.000 in every other status; at the
    instant of approval `consumed_tons` is still 0.000, so `available_tons` opens equal to
    `final_accepted_tons`."
    PRD §2.9: "Three ledgers in this system are conserved quantities and must balance at every
    observable instant, not merely eventually."

    Design: Corner/consistency_model/the_response_to_a_write_already_carries_every_derived_field_it_caused
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_tl_140()
    bundle = setup_available_lot(sublots_list=CLEAN_TRUCK)
    batch = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], 20.000)])
    validate_success(api_client.start_pulp_batch(batch["id"], OPERATOR))
    validate_success(api_client.screen_pulp_batch(batch["id"], OPERATOR))

    cleaned = validate_success(api_client.clean_pulp_batch(
        batch["id"], {"measured_reject_tons": 2.000}, OPERATOR))

    assert cleaned["status"] == "CLEANED"
    assert cleaned["measured_reject_tons"] == pytest.approx(2.000, abs=1e-6)
    right_away = solids_summary()
    assert right_away["gross_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert right_away["net_solids_tons"] == pytest.approx(2.000, abs=1e-6)
    assert right_away["unmanifested_dry_solids_tons"] == pytest.approx(2.000, abs=1e-6), \
        "the reject row is queryable with no settling period"
    assert len(solids_rows(source_ref_id=batch["id"], source_kind="PULP_REJECT")) == 1

    approved = validate_success(api_client.approve_pulp_batch(batch["id"], CERTIFIER))

    assert approved["status"] == "APPROVED"
    assert approved["final_accepted_tons"] == pytest.approx(18.000, abs=1e-6)
    assert approved["yield_variance_tons"] == pytest.approx(1.120, abs=1e-6)
    assert approved["available_tons"] == pytest.approx(18.000, abs=1e-6)
    assert approved["provisional_accepted_tons"] == pytest.approx(16.880, abs=1e-6)
    reread = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    for field in SETTLED_FIELDS:
        assert reread[field] == approved[field], \
            "field %s settled after the write returned" % field


def test_the_abort_cascade_is_complete_before_the_call_returns():
    """PRD §3.5: "It subtracts `pulp_draw_tons` back out of the batch's `consumed_tons` and
    recomputes `available_tons`, so total fiber tonnage is conserved. Every roll set of the run
    in `WOUND` or `WRAPPED` flips to `SCRAPPED`, each appending a `MACHINE_BROKE` solids row
    carrying that set's `net_tons`. The quality axis is forced to `CONDEMNED` regardless of
    what it read before. Every customer order whose `scheduled_run_id` is this run returns to
    `SUBMITTED` with `scheduled_run_id` cleared and `deschedule_count` incremented."
    PRD §2.9: "That imbalance must read exactly zero at every point at which it can be
    observed, including immediately after a pulp batch cancellation releases a reservation and
    immediately after an aborted run returns its drawn pulp."
    PRD §2.9: "The invariant is that `net_solids_tons` equals the sum of
    `manifested_dry_solids_tons` and `unmanifested_dry_solids_tons` rounded to 3 decimal
    places, which holds because every repulped row is matched by exactly one reversal row of
    equal tonnage."

    Design: Corner/consistency_model/a_cascade_is_fully_settled_inside_the_call_that_triggered_it
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_tl_140()
    register_permit(**MILL_PERMIT)
    machine = register_machine(**PM1)
    bundle = setup_available_lot(sublots_list=CLEAN_TRUCK)
    batch = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], 20.000)])
    validate_success(api_client.start_pulp_batch(batch["id"], OPERATOR))
    validate_success(api_client.screen_pulp_batch(batch["id"], OPERATOR))
    validate_success(api_client.clean_pulp_batch(
        batch["id"], {"measured_reject_tons": 2.000}, OPERATOR))
    validate_success(api_client.approve_pulp_batch(batch["id"], CERTIFIER))
    customer = register_customer(name="Great Lakes Converting",
                                 allocation_priority_tier="P1",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    order = submit_order(customer, "TL_140", ordered_tons=6.00, roll_width_mm=2200,
                         roll_diameter_mm=1300, wrap_spec="KRAFT_ONLY")
    run = schedule_run(machine["id"], "TL_140", batch["id"],
                       window_start="2026-09-01T06:00:00Z",
                       window_end="2026-09-01T14:00:00Z", pulp_draw_tons=15.000)
    schedule_order(order["id"], run["id"])
    start_run(machine["id"], run["id"])
    roll_set = wind_roll_set(run["id"], slit_width_mm=2200, diameter_mm=1200,
                             roll_count=8, net_tons=6.000)
    assert get_success_data(api_client.get_pulp_batch(
        batch["id"], OPERATOR))["consumed_tons"] == pytest.approx(15.000, abs=1e-6)

    aborted = validate_success(api_client.abort_run(machine["id"], run["id"], PLANNER))

    assert aborted["run_status"] == "ABORTED"
    assert aborted["quality_status"] == "CONDEMNED"
    returned = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert returned["consumed_tons"] == pytest.approx(0.000, abs=1e-6)
    assert returned["available_tons"] == pytest.approx(18.000, abs=1e-6)
    assert get_success_data(api_client.get_roll_set(
        roll_set["id"], PLANNER))["status"] == "SCRAPPED"
    broke = solids_rows(source_ref_id=run["id"], source_kind="MACHINE_BROKE")
    assert len(broke) == 1
    assert broke[0]["dry_solids_tons"] == pytest.approx(6.000, abs=1e-6)
    assert broke[0]["disposition"] == "PENDING"
    unsequenced = get_success_data(api_client.get_customer_order(order["id"], PLANNER))
    assert unsequenced["status"] == "SUBMITTED"
    assert unsequenced["scheduled_run_id"] is None
    assert unsequenced["deschedule_count"] == 1
    assert unsequenced["allocated_tons"] == pytest.approx(0.000, abs=1e-6)
    summary = solids_summary()
    assert summary["gross_solids_tons"] == pytest.approx(8.000, abs=1e-6)
    assert summary["reversed_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["net_solids_tons"] == pytest.approx(8.000, abs=1e-6)
    assert summary["manifested_dry_solids_tons"] == pytest.approx(0.000, abs=1e-6)
    assert summary["unmanifested_dry_solids_tons"] == pytest.approx(8.000, abs=1e-6)
    balance = get_success_data(api_client.get_fiber_balance(PLANNER))
    assert balance["imbalance_tons"] == pytest.approx(0.000, abs=1e-6), \
        "the released reservation is visible in the very next read"

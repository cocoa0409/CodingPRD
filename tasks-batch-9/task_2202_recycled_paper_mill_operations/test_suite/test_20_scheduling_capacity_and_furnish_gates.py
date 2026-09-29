"""Where two bookings meet: the closed machine interval widened by the buffer, the run's
booked tonnage, the inclusive blend ceiling, and the deink-only pulper line.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, declare_fiber_grade, declare_tl_140, declare_tis_16, publish_quote,
    register_machine, register_customer, setup_available_lot, setup_approved_batch,
    schedule_run, queue_batch, submit_order, schedule_order, machine_version,
    order_version, create_run_payload, furnish_line, sublot, fiber_balance,
)

PLANNER = TEST_USERS["planner_headers"]
OPERATOR = TEST_USERS["operator_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
TWENTY_TWO_TON_SUBLOT = [sublot(1, 30.000, 8.000, 10.00, 2.00)]


def _machine_holding_a_day_shift(pulp_draw_tons=15.000):
    declare_tl_140()
    machine = register_machine(**PM1)
    bundle = setup_approved_batch(
        tons_charged=20.000, measured_reject_tons=2.000, declare_spec=False,
        lot_bundle=setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT))
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       window_start="2026-09-01T06:00:00Z",
                       window_end="2026-09-01T14:00:00Z",
                       pulp_draw_tons=pulp_draw_tons)
    return machine, bundle["batch"], run


def test_a_run_starting_exactly_one_buffer_after_the_last_one_still_collides():
    """PRD §3.4: "Machine occupancy is a **closed interval, widened by the changeover buffer
    on both ends**."
    PRD §3.4: "The requested window, extended earlier by `changeover_buffer_minutes` and later
    by the same amount, must not intersect the unwidened closed window of any other run on the
    same machine whose `run_status` is `SCHEDULED` or `RUNNING`."
    PRD §3.4: "Because the intervals are closed, two windows that merely touch at an endpoint
    do collide, and any intersection at all — including a single shared instant — is rejected
    with `ERR_MACHINE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Corner/validations/changeover_buffer_makes_a_run_thirty_minutes_after_the_last_one_collide
    """
    machine, batch, first = _machine_holding_a_day_shift()
    version_after_first = machine_version(machine["id"])

    response = api_client.create_run(machine["id"], create_run_payload(
        "TL_140", batch["id"], version_after_first,
        window_start="2026-09-01T14:30:00Z", window_end="2026-09-01T18:00:00Z",
        pulp_draw_tons=3.000), PLANNER)
    validate_error(response, ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT.value, 409)

    listing = api_client.list_machine_runs(machine["id"], PLANNER).json()
    assert listing["meta"]["total_count"] == 1
    assert machine_version(machine["id"]) == version_after_first, \
        "a rejected schedule must not bump the machine version"


def test_one_minute_more_of_daylight_lets_the_same_run_onto_the_machine():
    """PRD §3.4: "The requested window, extended earlier by `changeover_buffer_minutes` and
    later by the same amount, must not intersect the unwidened closed window of any other run
    on the same machine whose `run_status` is `SCHEDULED` or `RUNNING`."
    PRD §3.4: "Scheduling a run is a planner act that creates the run in `run_status` of
    `SCHEDULED` and `quality_status` of `PENDING`."
    PRD §3.4: "The run's `machine_id` comes from the path rather than the body."

    Design: Corner/validations/one_minute_past_the_buffer_the_same_run_schedules_cleanly
    """
    machine, batch, first = _machine_holding_a_day_shift()

    second = validate_success(api_client.create_run(machine["id"], create_run_payload(
        "TL_140", batch["id"], machine_version(machine["id"]),
        window_start="2026-09-01T14:31:00Z", window_end="2026-09-01T18:01:00Z",
        pulp_draw_tons=3.000), PLANNER), 201)

    assert second["run_status"] == "SCHEDULED"
    assert second["quality_status"] == "PENDING"
    assert second["machine_id"] == machine["id"]
    assert second["pulp_draw_tons"] == pytest.approx(3.000, abs=1e-6)
    assert second["produced_tons"] == pytest.approx(0.000, abs=1e-6)

    listing = api_client.list_machine_runs(machine["id"], PLANNER).json()
    assert listing["meta"]["total_count"] == 2
    reserved = get_success_data(api_client.get_pulp_batch(batch["id"], OPERATOR))
    assert reserved["consumed_tons"] == pytest.approx(0.000, abs=1e-6), \
        "scheduling reserves nothing; only the start draws pulp"


def test_two_orders_that_each_fit_the_run_cannot_both_be_sequenced_onto_it():
    """PRD §3.6: "It also respects the run's booked capacity: the sum of `ordered_tons` over
    the orders already holding this run as their `scheduled_run_id`, plus this order's own
    `ordered_tons`, must not exceed the run's `pulp_draw_tons`, and an over-booking is
    rejected with `ERR_RUN_CAPACITY_EXCEEDED` (HTTP 409); the boundary is inclusive, so
    filling the run exactly is allowed."
    PRD §3.6: "Descheduling, `SCHEDULED → SUBMITTED`, returns the order to the unscheduled
    pool."

    Design: Corner/validations/two_individually_valid_orders_overrun_the_runs_pulp_draw_together
    """
    machine, batch, run = _machine_holding_a_day_shift()
    customer = register_customer(name="Gulf Coast Box Co", allocation_priority_tier="P2",
                                 max_roll_diameter_mm=1400, max_roll_width_mm=2400,
                                 wrap_spec="KRAFT_ONLY")
    first = submit_order(customer, "TL_140", ordered_tons=8.00, roll_width_mm=2400,
                         roll_diameter_mm=1400, wrap_spec="KRAFT_ONLY")
    second = submit_order(customer, "TL_140", ordered_tons=8.00, roll_width_mm=2400,
                          roll_diameter_mm=1400, wrap_spec="KRAFT_ONLY")
    schedule_order(first["id"], run["id"])
    version_before = order_version(second["id"])

    response = api_client.schedule_customer_order(
        second["id"],
        {"run_id": run["id"], "expected_order_version": version_before}, PLANNER)
    validate_error(response, ApiErrorId.ERR_RUN_CAPACITY_EXCEEDED.value, 409)

    turned_away = get_success_data(api_client.get_customer_order(second["id"], PLANNER))
    assert turned_away["status"] == "SUBMITTED"
    assert turned_away["scheduled_run_id"] is None
    assert turned_away["deschedule_count"] == 0, \
        "a refused sequencing is not a deschedule"
    assert turned_away["version"] == version_before
    kept = get_success_data(api_client.get_customer_order(first["id"], PLANNER))
    assert kept["status"] == "SCHEDULED"
    assert kept["scheduled_run_id"] == run["id"]


def test_a_blend_landing_exactly_on_three_and_a_half_percent_goes_to_the_pulper():
    """PRD §3.3: "And the blend must be clean enough: the batch's computed
    `blend_contamination_pct` must be no greater than 3.500, and a dirtier blend is rejected
    with `ERR_FURNISH_CONTAMINATION_EXCEEDED` (HTTP 409)."
    PRD §3.3: "Each line then contributes its `tons_charged` multiplied by that effective
    yield and divided by 100, rounded half up to three decimal places, and
    `provisional_accepted_tons` is the sum of those per-line contributions rounded half up to
    three decimal places."
    PRD §2.9: "The mill fiber balance reports `total_received_tons`, `total_consumed_tons`,
    `total_available_tons`, and `imbalance_tons`, where the first three are the sums, each
    rounded to 3 decimal places, of `tons_received`, `tons_consumed` and `tons_available`
    across every fiber inventory lot regardless of lot status — quarantined and depleted lots
    included — and `imbalance_tons` is the total received minus the total consumed minus the
    total available, rounded to 3 decimal places."

    Design: Corner/validations/blend_contamination_exactly_at_three_point_five_hundred_starts_pulping
    """
    declare_tl_140()
    clean = setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT)
    declare_fiber_grade(grade_code="SOP_37", index_symbol="PPI_SOP",
                        max_contamination_pct=6.00, max_moisture_pct=14.00,
                        nominal_yield_pct=80.00, rank_order=6)
    publish_quote(index_symbol="PPI_SOP", effective_month="2026-07",
                  published_price_per_ton=120.00)
    dirty = setup_available_lot(sublots_list=[sublot(1, 30.000, 8.000, 10.00, 5.00)],
                                grade_code="SOP_37",
                                supplier_name="Sorted Office Paper Co",
                                declare_grades=False, publish_index=False)
    batch = queue_batch("TL_140", [furnish_line(clean["lot"]["id"], 10.000),
                                   furnish_line(dirty["lot"]["id"], 10.000)])

    charged = validate_success(api_client.start_pulp_batch(batch["id"], OPERATOR))

    assert charged["status"] == "PULPING"
    assert charged["charged_tons"] == pytest.approx(20.000, abs=1e-6)
    assert charged["blend_contamination_pct"] == pytest.approx(3.500, abs=1e-6)
    assert charged["provisional_accepted_tons"] == pytest.approx(15.540, abs=1e-6), \
        "8.440 from the clean line plus 7.100 from the dirty one, line by line"
    assert charged["final_accepted_tons"] is None

    for lot_id in (clean["lot"]["id"], dirty["lot"]["id"]):
        lot = get_success_data(api_client.get_inventory_lot(lot_id, OPERATOR))
        assert lot["tons_consumed"] == pytest.approx(10.000, abs=1e-6)
        assert lot["tons_available"] == pytest.approx(12.000, abs=1e-6)
        assert lot["status"] == "AVAILABLE"

    balance = fiber_balance()
    assert balance["total_received_tons"] == pytest.approx(44.000, abs=1e-6)
    assert balance["total_consumed_tons"] == pytest.approx(20.000, abs=1e-6)
    assert balance["total_available_tons"] == pytest.approx(24.000, abs=1e-6)
    assert balance["imbalance_tons"] == pytest.approx(0.000, abs=1e-6)


def test_tissue_furnish_charged_on_the_brown_line_never_reaches_the_yield_maths():
    """PRD §3.3: "One line-routing rule joins them: when the target product's specification
    requires deinked pulp, the batch's `pulper_line` must be `DIP_LINE`, and a deink-required
    furnish charged on `OCC_LINE` is rejected with `ERR_WRONG_PULPER_LINE` (HTTP 409)."
    PRD §3.3: "Each line's `tons_charged` must be covered by that lot's `tons_available`, with
    the boundary inclusive so charging exactly the remaining tonnage is allowed; charging more
    is rejected with `ERR_INSUFFICIENT_FIBER` (HTTP 409)."

    Design: Corner/validations/occ_line_furnish_cannot_start_against_a_deink_only_grade
    """
    declare_tl_140()
    declare_tis_16()
    bundle = setup_available_lot(sublots_list=TWENTY_TWO_TON_SUBLOT)
    brown = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], 20.000)])
    validate_success(api_client.start_pulp_batch(brown["id"], OPERATOR))
    tissue = queue_batch("TIS_16", [furnish_line(bundle["lot"]["id"], 1.000)],
                         pulper_line="OCC_LINE")

    response = api_client.start_pulp_batch(tissue["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_WRONG_PULPER_LINE.value, 409)

    unstarted = get_success_data(api_client.get_pulp_batch(tissue["id"], OPERATOR))
    assert unstarted["status"] == "QUEUED"
    assert unstarted["provisional_accepted_tons"] is None, \
        "the routing rule fires before any yield is projected"
    assert unstarted["deink_pass_count"] == 0
    lot = get_success_data(api_client.get_inventory_lot(bundle["lot"]["id"], OPERATOR))
    assert lot["status"] == "AVAILABLE", \
        "tonnage remains, so the availability gate was satisfied"

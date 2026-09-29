"""Two subsystems, two interval geometries: machine occupancy is closed and widened
by the changeover buffer, while the steam header is half-open and strict, so the very
same pair of timestamps collides on one and coexists on the other.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    declare_standard_grades, declare_tl_140, declare_paper_grade_spec,
    setup_available_lot, queue_batch, furnish_line, register_machine,
    machine_version, schedule_run, request_steam, assert_same_instant, TEST_USERS,
)

PLANNER = TEST_USERS["planner_headers"]
ENERGY = TEST_USERS["energy_headers"]


def _machine_with_an_incumbent_run(buffer_minutes, name, day):
    """A SCHEDULED run holding 00:00..06:00 on a machine with the given buffer."""
    declare_tl_140()
    bundle = setup_available_lot()
    batch = queue_batch("TL_140", [furnish_line(bundle["lot"]["id"], 30.000)])
    machine = register_machine(name=name, wire_width_mm=4200, max_tons_per_hour=20.00,
                               changeover_buffer_minutes=buffer_minutes,
                               steam_tph_per_ton=1.400)
    incumbent = schedule_run(machine["id"], "TL_140", batch["id"],
                             window_start=f"{day}T00:00:00Z",
                             window_end=f"{day}T06:00:00Z", pulp_draw_tons=10.000)
    return machine, batch, incumbent


def _attempt_window(machine, batch, start, end):
    return api_client.create_run(machine["id"], {
        "product_code": "TL_140", "pulp_batch_id": batch["id"],
        "window_start": start, "window_end": end, "pulp_draw_tons": 10.000,
        "expected_machine_version": machine_version(machine["id"])}, PLANNER)


def _runs_on(machine):
    return api_client.list_machine_runs(machine["id"], PLANNER).json()["meta"]["total_count"]


def test_the_buffer_reaches_backwards_so_a_half_hour_gap_still_conflicts():
    """PRD §3.4: "The requested window, extended earlier by
    `changeover_buffer_minutes` and later by the same amount, must not intersect the
    unwidened closed window of any other run on the same machine whose `run_status` is
    `SCHEDULED` or `RUNNING`."

    Design: Difficulty/resource_temporal_overlap/machine_occupancy_widened_by_changeover_buffer_on_both_ends
    """
    machine, batch, incumbent = _machine_with_an_incumbent_run(60, "PM1", "2026-08-02")
    assert incumbent["run_status"] == "SCHEDULED"

    response = _attempt_window(machine, batch, "2026-08-02T06:30:00Z",
                               "2026-08-02T12:00:00Z")
    validate_error(response, ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT.value, 409)
    assert _runs_on(machine) == 1, "the refused request left no run behind"
    assert_same_instant(
        get_success_data(api_client.get_run(incumbent["id"], PLANNER))["window_end"],
        "2026-08-02T06:00:00Z", "the incumbent window is never widened in storage")


def test_the_widened_start_must_clear_the_incumbent_end_by_a_whole_minute():
    """PRD §3.4: "Because the intervals are closed, two windows that merely touch at an
    endpoint do collide, and any intersection at all — including a single shared instant
    — is rejected with `ERR_MACHINE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/machine_occupancy_widened_by_changeover_buffer_on_both_ends
    """
    machine, batch, _incumbent = _machine_with_an_incumbent_run(60, "PM1", "2026-08-02")

    touching = _attempt_window(machine, batch, "2026-08-02T07:00:00Z",
                               "2026-08-02T12:00:00Z")
    validate_error(touching, ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT.value, 409)

    clear = _attempt_window(machine, batch, "2026-08-02T07:01:00Z",
                            "2026-08-02T12:00:00Z")
    validate_success(clear, expected_status=201)
    accepted = get_success_data(clear)
    assert accepted["run_status"] == "SCHEDULED"
    assert_same_instant(accepted["window_start"], "2026-08-02T07:01:00Z")
    assert _runs_on(machine) == 2


def test_back_to_back_windows_collide_on_a_machine_with_no_buffer_at_all():
    """PRD §3.4: "Machine occupancy is a **closed interval, widened by the changeover
    buffer on both ends**."

    Design: Difficulty/resource_temporal_overlap/machine_occupancy_touching_endpoints_collide_with_zero_buffer
    """
    machine, batch, _incumbent = _machine_with_an_incumbent_run(0, "PM3", "2026-08-12")
    assert machine["changeover_buffer_minutes"] == 0

    response = _attempt_window(machine, batch, "2026-08-12T06:00:00Z",
                               "2026-08-12T12:00:00Z")
    validate_error(response, ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT.value, 409)
    assert _runs_on(machine) == 1


def test_one_minute_of_daylight_is_enough_when_the_buffer_is_zero():
    """PRD §3.4: "This is deliberately stricter than the steam header's geometry
    described in §3.7, where the same two timestamps would coexist."

    Design: Difficulty/resource_temporal_overlap/machine_occupancy_touching_endpoints_collide_with_zero_buffer
    """
    machine, batch, _incumbent = _machine_with_an_incumbent_run(0, "PM3", "2026-08-12")

    response = _attempt_window(machine, batch, "2026-08-12T06:01:00Z",
                               "2026-08-12T12:00:00Z")
    validate_success(response, expected_status=201)
    accepted = get_success_data(response)
    assert accepted["run_status"] == "SCHEDULED"
    assert_same_instant(accepted["window_start"], "2026-08-12T06:01:00Z")
    assert _runs_on(machine) == 2


A1 = {"consumer_kind": "EVAPORATOR", "window_start": "2026-08-01T08:00:00Z",
      "window_end": "2026-08-01T12:00:00Z", "demand_tph": 120.000, "priority_rank": 1}
A2 = {"consumer_kind": "DEINK_PLANT", "window_start": "2026-08-01T09:00:00Z",
      "window_end": "2026-08-01T11:00:00Z", "demand_tph": 70.000, "priority_rank": 2}


def _header_loaded_to_capacity():
    """120.000 tph granted across 08:00..12:00 and a curtailed 60.000 tph inside it."""
    return request_steam(**A1), request_steam(**A2)


def test_the_curtailed_neighbour_fills_the_header_and_the_next_window_is_saturated():
    """PRD §3.8: "Otherwise the request is partially served: `granted_tph` equals the
    remaining headroom and `status` becomes `CURTAILED`." PRD §3.8: "If the remaining
    headroom is 0.000 or less, the request is rejected with `ERR_STEAM_HEADER_SATURATED`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/steam_header_half_open_waterfall_with_touching_reuse_after_release
    """
    first, second = _header_loaded_to_capacity()
    assert first["status"] == "GRANTED"
    assert first["granted_tph"] == pytest.approx(120.000, abs=1e-6)
    assert first["curtailed_tph"] == pytest.approx(0.000, abs=1e-6)
    assert first["cogen_credit_usd"] == pytest.approx(1302.00, abs=1e-6), \
        "60.000 tph exported over 4.0000 h: 492.0000 plus 810.0000 plus 0.0000"
    assert second["status"] == "CURTAILED"
    assert second["granted_tph"] == pytest.approx(60.000, abs=1e-6)
    assert second["curtailed_tph"] == pytest.approx(10.000, abs=1e-6)
    assert second["cogen_credit_usd"] == pytest.approx(0.00, abs=1e-6), \
        "the header is fully consumed, so there is nothing to export"

    response = api_client.create_steam_allocation(
        {"consumer_kind": "EVAPORATOR", "window_start": "2026-08-01T09:30:00Z",
         "window_end": "2026-08-01T10:30:00Z", "demand_tph": 20.000,
         "priority_rank": 3}, ENERGY)
    validate_error(response, ApiErrorId.ERR_STEAM_HEADER_SATURATED.value, 409)
    listing = api_client.list_steam_allocations(ENERGY, {"status": "REQUESTED"})
    assert listing.json()["meta"]["total_count"] == 0, \
        "a rejected dispatch leaves no allocation row"


def test_a_window_starting_on_a_neighbours_end_instant_contends_with_nothing():
    """PRD §3.8: "Two allocations therefore overlap only when the first begins strictly
    before the second ends and ends strictly after the second begins, which means
    back-to-back allocations sharing an endpoint never contend and consume nothing from
    each other."

    Design: Difficulty/resource_temporal_overlap/steam_header_half_open_waterfall_with_touching_reuse_after_release
    """
    _header_loaded_to_capacity()

    touching = request_steam(consumer_kind="DEINK_PLANT",
                             window_start="2026-08-01T12:00:00Z",
                             window_end="2026-08-01T13:00:00Z",
                             demand_tph=20.000, priority_rank=1)
    assert touching["status"] == "GRANTED"
    assert touching["granted_tph"] == pytest.approx(20.000, abs=1e-6)
    assert touching["curtailed_tph"] == pytest.approx(0.000, abs=1e-6)
    assert touching["cogen_credit_usd"] == pytest.approx(1245.50, abs=1e-6), \
        "160.000 tph exported over 1.0000 h: 123.0000 plus 202.5000 plus 920.0000"


def test_released_capacity_serves_later_requests_without_re_dispatching_neighbours():
    """PRD §3.8: "It requires the allocation's `status` to be `GRANTED` or `CURTAILED`,
    failing with `ERR_ENV_RECORD_INVALID_STATE` otherwise, and moves the status to
    `RELEASED` with `granted_tph` set to 0.000 and `curtailed_tph` set to the full
    `demand_tph`." PRD §3.8: "The freed capacity is available to requests that arrive
    afterwards, but **existing allocations are not re-dispatched** — a curtailed
    neighbour stays curtailed until it is itself replaced."

    Design: Difficulty/resource_temporal_overlap/steam_header_half_open_waterfall_with_touching_reuse_after_release
    """
    first, second = _header_loaded_to_capacity()

    released = get_success_data(
        api_client.release_steam_allocation(first["id"], ENERGY))
    assert released["status"] == "RELEASED"
    assert released["granted_tph"] == pytest.approx(0.000, abs=1e-6)
    assert released["curtailed_tph"] == pytest.approx(120.000, abs=1e-6)

    reuse = request_steam(consumer_kind="EVAPORATOR",
                          window_start="2026-08-01T08:00:00Z",
                          window_end="2026-08-01T09:00:00Z",
                          demand_tph=150.000, priority_rank=1)
    assert reuse["status"] == "GRANTED"
    assert reuse["granted_tph"] == pytest.approx(150.000, abs=1e-6)
    assert reuse["cogen_credit_usd"] == pytest.approx(123.00, abs=1e-6), \
        "the 09:00 endpoint only touches the curtailed neighbour, so consumed is 0.000"

    unchanged = get_success_data(api_client.get_steam_allocation(second["id"], ENERGY))
    assert unchanged["granted_tph"] == pytest.approx(60.000, abs=1e-6)
    assert unchanged["curtailed_tph"] == pytest.approx(10.000, abs=1e-6)


PM2 = {"name": "PM2", "wire_width_mm": 3800, "max_tons_per_hour": 12.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 1.350}


def _two_transition_pairs_on_pm2():
    """PM2 carrying two independent TL_140 -> MED_112 pairs, one separated by a
    44-minute idle gap and one by 45 minutes."""
    declare_tl_140()
    declare_paper_grade_spec(product_code="MED_112", family="CONTAINERBOARD",
                            basis_weight_gsm=112.0, target_moisture_pct=8.00,
                            moisture_tolerance_pct=0.80, min_sct_kn_m=1.80,
                            min_brightness_iso=None, requires_deink_pulp=False,
                            rank_order=6)
    bundle = setup_available_lot()
    lot_id = bundle["lot"]["id"]
    outgoing_batch = queue_batch("TL_140", [furnish_line(lot_id, 15.000)])
    incoming_batch = queue_batch("MED_112", [furnish_line(lot_id, 15.000)])
    machine = register_machine(**PM2)
    pairs = []
    for day, incoming_start in (("2026-08-04", "04:44:00Z"), ("2026-08-05", "04:45:00Z")):
        outgoing = schedule_run(machine["id"], "TL_140", outgoing_batch["id"],
                                window_start=f"{day}T00:00:00Z",
                                window_end=f"{day}T04:00:00Z", pulp_draw_tons=8.000)
        incoming = schedule_run(machine["id"], "MED_112", incoming_batch["id"],
                                window_start=f"{day}T{incoming_start}",
                                window_end=f"{day}T08:00:00Z", pulp_draw_tons=8.000)
        pairs.append((outgoing, incoming))
    return machine, pairs


def _plan_transition(machine, outgoing, incoming, expected_version):
    return api_client.create_grade_change(machine["id"], {
        "from_run_id": outgoing["id"], "to_run_id": incoming["id"],
        "expected_machine_version": expected_version}, PLANNER)


def test_a_forty_four_minute_idle_gap_is_one_minute_short_of_the_transition():
    """PRD §3.4: "The gap between the outgoing run's `window_end` and the incoming
    run's `window_start`, measured in whole minutes, must be at least the computed
    `transition_minutes`; the boundary is inclusive, so a gap exactly equal to the
    computed duration is acceptable, while a shorter gap is rejected with
    `ERR_TRANSITION_GAP_TOO_SHORT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/grade_change_gap_inclusive_against_computed_transition_minutes
    """
    machine, pairs = _two_transition_pairs_on_pm2()
    outgoing, incoming = pairs[0]

    response = _plan_transition(machine, outgoing, incoming,
                                machine_version(machine["id"]))
    validate_error(response, ApiErrorId.ERR_TRANSITION_GAP_TOO_SHORT.value, 409)

    listing = api_client.list_grade_changes(PLANNER, {"from_run_id": outgoing["id"]})
    assert listing.json()["meta"]["total_count"] == 0, \
        "the refused plan stored nothing"


def test_a_forty_five_minute_gap_exactly_covers_the_up_sequence_transition():
    """PRD §3.4: "Fourth, a **direction multiplier** of 1.15 applies when the incoming
    spec's `rank_order` is strictly lower than the outgoing spec's — running the
    sequence backwards costs an extra fifteen percent — and 1.00 otherwise, which is why
    the same pair of products produces different waste in the two directions." PRD §3.4:
    "Finally, `transition_minutes` is the waste tonnage divided by the machine's
    `max_tons_per_hour` and multiplied by 60, rounded **up** to the next whole minute,
    plus the machine's `changeover_buffer_minutes` — the ceiling is applied after the
    tonnage has been rounded to three decimal places, not before."

    Design: Difficulty/resource_temporal_overlap/grade_change_gap_inclusive_against_computed_transition_minutes
    """
    machine, pairs = _two_transition_pairs_on_pm2()
    version_before = machine_version(machine["id"])
    validate_error(_plan_transition(machine, pairs[0][0], pairs[0][1], version_before),
                   ApiErrorId.ERR_TRANSITION_GAP_TOO_SHORT.value, 409)

    response = _plan_transition(machine, pairs[1][0], pairs[1][1], version_before)
    validate_success(response, expected_status=201)
    planned = get_success_data(response)
    assert planned["transition_waste_tons"] == pytest.approx(2.875, abs=1e-6), \
        "the 2.500-ton tier lifted fifteen percent by the reversed rank order"
    assert planned["transition_minutes"] == 45
    assert planned["status"] == "PLANNED"
    assert planned["from_product_code"] == "TL_140"
    assert planned["to_product_code"] == "MED_112"
    assert machine_version(machine["id"]) == version_before + 1, \
        "only the accepted plan moved the machine version"

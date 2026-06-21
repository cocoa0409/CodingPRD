"""Second-angle depth tests for every difficulty-design instance.

Each test here exercises the same rule as its first-angle counterpart in
test_01..test_04, from a complementary scenario (the other side of a boundary,
an alternate valid branch, or a conservation via a different terminal path).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_customer_property,
    setup_customer_property_system,
    setup_approved_quote_workorder,
    setup_backflow_ready,
    record_backflow_test,
    create_customer,
    create_property,
    create_system,
    create_zone,
    create_technician,
    create_work_order,
    create_route,
    create_route_stop,
    create_program,
    schedule_work_order,
    fill_route_with_stops,
    winterize_then_startup_system,
    winterize_system,
    complete_work_order_full,
    make_technician_headers,
    make_customer_headers,
    make_backflow_tester_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# dual_variant_calc
# ===========================================================================
def test_quote_estimated_single_round_after_summing(api):
    """PRD §3.3: "for each line item the per-line amount is its `quantity` multiplied by its
    `unit_rate_cents` — an exact integer-cents product — and these per-line amounts are
    summed into a subtotal. That whole subtotal is then multiplied by one plus the tax rate
    of 8% (a factor of 1.08), and the single resulting figure is rounded half up to whole
    cents to give `estimated_total_cents`. The estimate rounds exactly once, after the
    entire subtotal has been formed."

    Design: Difficulty/dual_variant_calc/quote_estimated_vs_final_total_diverge
    """
    # subtotal = 1431 + 806 = 2237 ; 2237 * 1.08 = 2415.96 -> round half up -> 2416
    _cust, prop = setup_customer_property(company_name="EstOnly Co")
    quote = validate_success(api.create_quote(
        {"property_id": prop["id"], "quote_type": "REPAIR",
         "line_items": [{"description": "valve", "quantity": 1, "unit_rate_cents": 1431},
                        {"description": "fitting", "quantity": 1, "unit_rate_cents": 806}]},
        DISPATCHER), expected_status=201)
    sent = validate_success(api.send_quote(quote["id"], DISPATCHER))
    assert sent["estimated_total_cents"] == 2416, (
        f"estimated_total_cents should be 2416 (single round after summing), "
        f"got {sent['estimated_total_cents']}")


def test_winter_risk_provisional_equals_assessed_before_winterization(api):
    """PRD §3.8: "It treats the zones as drained once the system has been blown out: if the
    system has no completed winterization work order, the drained exposure is the same
    plant-type-weighted sum over non-archived zones". PRD §3.8: "it sums the plant-type
    weight times `head_count` across all non-archived zones to form the exposure, multiplies
    that exposure by the pressure factor, and takes the smaller of that product and the
    1000-point cap."

    Design: Difficulty/dual_variant_calc/system_winter_risk_provisional_vs_assessed_diverge
    """
    # static_psi=90 -> factor 2 ; TURF(4)*10 + ROTOR(3)*6 = 58 ; *2 = 116 for both figures.
    cust = create_customer(company_name="PreWint Co")
    prop = create_property(cust["id"])
    sys = validate_success(api.create_system(
        {"property_id": prop["id"], "controller_model": "Hunter", "static_psi": 90}, DISPATCHER),
        expected_status=201)
    create_zone(sys["id"], 1, plant_type="TURF", head_count=10, gpm_per_head=18)
    create_zone(sys["id"], 2, plant_type="ROTOR", head_count=6, gpm_per_head=22)

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["provisional_winter_risk"] == 116, (
        f"provisional should be 116, got {system['provisional_winter_risk']}")
    assert system["assessed_winter_risk"] == 116, (
        f"assessed should equal provisional (116) before any completed winterization, "
        f"got {system['assessed_winter_risk']}")


# ===========================================================================
# combinatorial_formula
# ===========================================================================
def test_blowout_price_tier3_with_capped_psi_surcharge(api):
    """PRD §3.8: "when the count is 11 or more the rate is 850 cents per zone. A pressure
    surcharge is computed as the system's `static_psi` minus the high-pressure threshold of
    80, multiplied by 50 cents per PSI, then floored at 0 and capped at 3000 cents". PRD
    §3.8: "The `blowout_price_cents` is the base fee of 4500 cents, plus the per-zone rate
    times the zone count, plus the pressure surcharge."

    Design: Difficulty/combinatorial_formula/blowout_price_tiered_with_psi_surcharge
    """
    # 11 zones tier3 850 ; psi 200 -> (200-80)*50 = 6000 capped to 3000.
    # 4500 + 850*11 + 3000 = 4500 + 9350 + 3000 = 16850
    cust = create_customer(company_name="Tier3 Co")
    prop = create_property(cust["id"])
    sys = validate_success(api.create_system(
        {"property_id": prop["id"], "controller_model": "RainBird", "static_psi": 200}, DISPATCHER),
        expected_status=201)
    for zn in range(1, 12):
        create_zone(sys["id"], zn, plant_type="DRIP", head_count=2, gpm_per_head=5)

    data = validate_success(api.get_blowout_quote(sys["id"], DISPATCHER))
    assert data["zone_count"] == 11
    assert data["blowout_price_cents"] == 16850, (
        f"blowout_price_cents should be 16850 (tier3 + capped surcharge), "
        f"got {data['blowout_price_cents']}")


def test_final_total_per_line_rounding_differs_from_sum_then_round(api):
    """PRD §3.4: "The labor component is the `actual_labor_cents` multiplied by the 1.08 tax
    factor and rounded half up to whole cents; the parts component is the `actual_parts_cents`
    multiplied by the same 1.08 factor and rounded half up to whole cents; and
    `final_total_cents` is the sum of those two already-rounded components."

    Design: Difficulty/combinatorial_formula/quote_final_round_per_line_then_sum
    """
    # labor 1431*1.08 = 1545.48 -> 1545 ; parts 801*1.08 = 865.08 -> 865 ; sum = 2410.
    cust, prop, sys = setup_customer_property_system(company_name="Round2 Co")
    tech = create_technician(full_name="Round2 Tech")
    line_items = [
        {"description": "valve", "quantity": 1, "unit_rate_cents": 1431},
        {"description": "fitting", "quantity": 1, "unit_rate_cents": 806},
    ]
    _approved, wo_id = setup_approved_quote_workorder(
        cust["id"], prop["id"], quote_type="REPAIR", line_items=line_items)
    tech_headers = make_technician_headers(tech["id"])
    route = create_route(tech["id"], route_date="2026-04-03")
    create_route_stop(route["id"], wo_id, route["version"], arrival_start_sec=28800, window_minutes=60)
    validate_success(api.depart_work_order(wo_id, tech_headers))
    validate_success(api.arrive_work_order(wo_id, tech_headers))
    validate_success(api.complete_work_order(
        wo_id, {"actual_labor_cents": 1431, "actual_parts_cents": 801}, tech_headers))

    quote = validate_success(api.get_quote(_approved["id"], DISPATCHER))
    assert quote["final_total_cents"] == 2410, (
        f"final_total_cents should be 2410, got {quote['final_total_cents']}")


def test_plan_dues_no_discount_below_loyalty_floor(api):
    """PRD §3.7: "The per-visit base rate is fixed by tier: 6000 cents for `BASIC`". PRD
    §3.7: "if the gross is at least 120000 cents the discount is 15%, otherwise if the gross
    is at least 60000 cents the discount is 8%, otherwise there is no discount. The
    `annual_dues_cents` is the gross multiplied by one minus that discount fraction, rounded
    half up to whole cents once at the end."

    Design: Difficulty/combinatorial_formula/plan_dues_circular_tier_evaluation_order
    """
    # BASIC @ 4 visits: gross = 6000*4 = 24000 < 60000 -> no discount -> 24000.
    _cust, prop = setup_customer_property(company_name="NoDisc Co")
    plan = validate_success(api.create_plan(
        {"property_id": prop["id"], "tier": "BASIC", "visits_per_year": 4}, DISPATCHER),
        expected_status=201)
    assert plan["annual_dues_cents"] == 24000, (
        f"annual_dues_cents should be 24000 (gross below loyalty floor), "
        f"got {plan['annual_dues_cents']}")


# ===========================================================================
# non_linear_state_machine
# ===========================================================================
def test_quote_intermediate_states_through_revision_cycle(api):
    """PRD §3.3: "They may request changes, moving the quote `SENT → CHANGES_REQUESTED`".
    PRD §3.3: "the Dispatcher revises the quote by submitting a fresh `line_items` array,
    which replaces the prior list and moves the quote `CHANGES_REQUESTED → DRAFT`".

    Design: Difficulty/non_linear_state_machine/quote_cyclic_revision_loop
    """
    cust, prop = setup_customer_property(company_name="LoopState Co")
    quote = validate_success(api.create_quote(
        {"property_id": prop["id"], "quote_type": "INSTALL",
         "line_items": [{"description": "heads", "quantity": 1, "unit_rate_cents": 5000}]},
        DISPATCHER), expected_status=201)
    validate_success(api.send_quote(quote["id"], DISPATCHER))
    cust_headers = make_customer_headers(cust["id"])
    changed = validate_success(api.request_changes_quote(quote["id"], cust_headers))
    assert changed["quote_state"] == "CHANGES_REQUESTED", (
        f"quote_state should be CHANGES_REQUESTED, got {changed['quote_state']}")
    revised = validate_success(api.revise_quote_line_items(
        quote["id"], {"line_items": [{"description": "heads", "quantity": 2, "unit_rate_cents": 50}]},
        DISPATCHER))
    assert revised["quote_state"] == "DRAFT", (
        f"revision should return quote to DRAFT, got {revised['quote_state']}")


def test_workorder_depart_advances_only_dispatch_axis(api):
    """PRD §3.4: "Departing for the job advances `SCHEDULED → EN_ROUTE`". PRD §3.4: "The two
    axes evolve independently except where a precondition on one explicitly references the
    other."

    Design: Difficulty/non_linear_state_machine/workorder_parallel_dispatch_and_completion_dimensions
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Par2 Co")
    tech = create_technician(full_name="Par2 Tech")
    wo_id, _route_id, _ = schedule_work_order(
        sys["id"], tech["id"], job_type="LEAK_REPAIR", route_date="2026-05-13")
    tech_headers = make_technician_headers(tech["id"])
    wo = validate_success(api.depart_work_order(wo_id, tech_headers))
    assert wo["dispatch_status"] == "EN_ROUTE", (
        f"dispatch_status should be EN_ROUTE, got {wo['dispatch_status']}")
    assert wo["completion_status"] == "PENDING", (
        f"completion_status should remain PENDING after depart, got {wo['completion_status']}")


# ===========================================================================
# transitive_cascade
# ===========================================================================
def test_decommission_credits_committed_cost_and_removes_stop(api):
    """PRD §3.5: "every work order on the system whose `completion_status` is not already
    one of `COMPLETED`, `FAILED`, or `CANCELLED` is cancelled — and each such cancellation
    runs the full work-order cancellation behaviour from Section 3.4, crediting the system's
    `committed_cost_cents` back by that work order's `estimated_cost_cents` and removing any
    `SCHEDULED` route stop that referenced it."

    Design: Difficulty/transitive_cascade/system_decommission_depth3_zone_program_workorder_chain
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Casc2 Co")
    tech = create_technician(full_name="Casc2 Tech")
    wo = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=20, estimated_cost_cents=3000)
    route = create_route(tech["id"], route_date="2026-05-14")
    route_after = create_route_stop(route["id"], wo["id"], route["version"],
                                    arrival_start_sec=28800, window_minutes=60)
    assert route_after["stops_used"] == 1
    before = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert before["committed_cost_cents"] == 3000

    validate_success(api.decommission_system(sys["id"], DISPATCHER))

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["committed_cost_cents"] == 0, (
        f"committed_cost_cents should be credited back to 0 by the cascade, "
        f"got {system['committed_cost_cents']}")
    route_now = validate_success(api.get_route(route["id"], DISPATCHER))
    assert route_now["stops_used"] == 0, (
        f"route stop should be removed by the cascade, stops_used got {route_now['stops_used']}")


def test_property_stays_non_compliant_until_every_system_certified(api):
    """PRD §3.5: "A `PASS` sets the system's `backflow_status` to `CERTIFIED`, then
    recomputes the property's `compliance_status` — which becomes `COMPLIANT` only if every
    non-decommissioned system on that property is now `CERTIFIED`."

    Design: Difficulty/transitive_cascade/backflow_pass_bubbles_up_system_then_property_compliance
    """
    cust = create_customer(company_name="TwoSys Co")
    prop = create_property(cust["id"])
    sys1 = create_system(prop["id"], static_psi=60, has_backflow_device=True)
    create_system(prop["id"], static_psi=60, has_backflow_device=True)  # second, stays UNTESTED
    tester = create_technician(full_name="TwoSys Tester", backflow_certified=True)

    record_backflow_test(sys1["id"], tester["id"], relief_open_psi=5, checkvalve_hold_psi=3)

    s1 = validate_success(api.get_system(sys1["id"], DISPATCHER))
    assert s1["backflow_status"] == "CERTIFIED"
    property_ = validate_success(api.get_property(prop["id"], DISPATCHER))
    assert property_["compliance_status"] == "NON_COMPLIANT", (
        "property must stay NON_COMPLIANT while a second system is still UNTESTED, "
        f"got {property_['compliance_status']}")


# ===========================================================================
# priority_pair_validation_conflict
# ===========================================================================
def test_already_scheduled_error_even_when_window_fits_capacity(api):
    """PRD §3.6: "its `dispatch_status` must be `UNSCHEDULED` (otherwise
    `ERR_WORKORDER_ALREADY_SCHEDULED`)." PRD §2.5: "State preconditions for the requested
    transition are checked fifth, yielding the state-specific conflict error described
    alongside each workflow. Then come the domain-specific business gates".

    Design: Difficulty/priority_pair_validation_conflict/schedule_state_beats_capacity_fiscal
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="PP1b Co")
    tech = create_technician(full_name="PP1b Tech", shift_start_sec=0, shift_end_sec=86399)
    wo = create_work_order(sys["id"], job_type="LEAK_REPAIR",
                           estimated_minutes=30, estimated_cost_cents=4000)
    route = create_route(tech["id"], route_date="2026-05-15")
    route_after = create_route_stop(route["id"], wo["id"], route["version"],
                                    arrival_start_sec=0, window_minutes=30)
    route_now = validate_success(api.get_route(route["id"], DISPATCHER))
    # A small window that would fit capacity, but the work order is already SCHEDULED.
    resp = api.create_route_stop(
        {"route_id": route["id"], "work_order_id": wo["id"], "arrival_start_sec": 7200,
         "window_minutes": 30, "expected_route_version": route_now["version"]}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_WORKORDER_ALREADY_SCHEDULED.value)


def test_no_device_error_when_tester_is_certified(api):
    """PRD §3.5: "the system must actually have a backflow device, that is its
    `has_backflow_device` must be true (otherwise `ERR_NO_BACKFLOW_DEVICE`, HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/backflow_safety_beats_referential
    """
    cust = create_customer(company_name="PP2b Co")
    prop = create_property(cust["id"])
    sys = create_system(prop["id"], static_psi=60, has_backflow_device=False)
    tester = create_technician(full_name="Cert Tech", backflow_certified=True)
    headers = make_backflow_tester_headers(tester["id"])
    # Safety gate passes (certified); the device gate is what remains.
    resp = api.create_backflow_test(
        {"system_id": sys["id"], "tester_technician_id": tester["id"],
         "relief_open_psi": 5, "checkvalve_hold_psi": 3}, headers)
    validate_error(resp, ApiErrorId.ERR_NO_BACKFLOW_DEVICE.value)


# ===========================================================================
# boundary_precision_check
# ===========================================================================
def test_eighth_route_stop_at_capacity_boundary_accepted(api):
    """PRD §3.6: "the route's prospective stop count — its current `stops_used` plus one —
    would exceed the per-route maximum of 8 stops". PRD §3.6: "The stop-count limit bites
    only when the prospective count is strictly greater than 8."

    Design: Difficulty/boundary_precision_check/route_capacity_max_stops_boundary
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Cap2 Co")
    tech = create_technician(full_name="Cap2 Tech", shift_start_sec=0, shift_end_sec=86399)
    # Place 7 stops, then add the 8th (prospective_stops=8, NOT > 8) -> accepted.
    route_id, version, _ = fill_route_with_stops(
        sys["id"], tech["id"], n_stops=7, route_date="2026-05-16",
        window_minutes=10, start_spacing_sec=3600, first_start_sec=0)
    w8 = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=10, estimated_cost_cents=1000)
    stop = validate_success(api.create_route_stop(
        {"route_id": route_id, "work_order_id": w8["id"], "arrival_start_sec": 25200,
         "window_minutes": 10, "expected_route_version": version}, DISPATCHER), expected_status=201)
    assert stop["stop_state"] == "SCHEDULED"
    route = validate_success(api.get_route(route_id, DISPATCHER))
    assert route["stops_used"] == 8, f"8th stop should be accepted, stops_used got {route['stops_used']}"


def test_empty_program_rejected_even_when_season_active(api):
    """PRD §3.2: "Activating a draft program is a technician action and is gated by four
    preconditions evaluated together: the program must be in `DRAFT` (otherwise
    `ERR_PROGRAM_NOT_DRAFT`); its `slots` array must be non-empty (otherwise
    `ERR_EMPTY_PROGRAM`); the system's `season_state` must be `ACTIVE` (otherwise
    `ERR_SEASON_STATE_BLOCKS_PROGRAM`)".

    Design: Difficulty/boundary_precision_check/empty_program_zero_slots_rejected
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Emp2 Co")
    tech = create_technician(full_name="Emp2 Tech")
    # Bring the season to ACTIVE so the empty-slots gate is isolated.
    winterize_then_startup_system(sys["id"], tech["id"], route_date="2026-10-03")
    prog = create_program(sys["id"], [])
    tech_headers = make_technician_headers(tech["id"])
    resp = api.activate_program(prog["id"], tech_headers)
    validate_error(resp, ApiErrorId.ERR_EMPTY_PROGRAM.value)


# ===========================================================================
# cross_entity_state_dependency
# ===========================================================================
def test_startup_stop_accepted_after_system_winterized(api):
    """PRD §3.6: "If the work order's `job_type` is `STARTUP`, the serviced system's
    `season_state` must be `WINTERIZED` (otherwise `ERR_SEASON_STATE_BLOCKS_STARTUP`) — a
    system can only be started up after it has been winterized."

    Design: Difficulty/cross_entity_state_dependency/startup_schedule_requires_system_winterized
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Ce1b Co")
    tech = create_technician(full_name="Ce1b Tech", shift_start_sec=0, shift_end_sec=86399)
    # Winterize the system (season_state -> WINTERIZED) on its own route.
    winterize_system(sys["id"], tech["id"], route_date="2026-10-04")
    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["season_state"] == "WINTERIZED"

    startup = create_work_order(sys["id"], job_type="STARTUP",
                                estimated_minutes=30, estimated_cost_cents=6000)
    route2 = create_route(tech["id"], route_date="2026-10-05")
    stop = validate_success(api.create_route_stop(
        {"route_id": route2["id"], "work_order_id": startup["id"], "arrival_start_sec": 28800,
         "window_minutes": 60, "expected_route_version": route2["version"]}, DISPATCHER),
        expected_status=201)
    assert stop["stop_state"] == "SCHEDULED", (
        "STARTUP stop should be accepted once the system is WINTERIZED")


def test_program_activate_blocked_when_season_winterized(api):
    """PRD §3.2: "the system's `season_state` must be `ACTIVE` (otherwise
    `ERR_SEASON_STATE_BLOCKS_PROGRAM`)". PRD §2.9: "a controller program cannot be activated
    on a system that is not in its active growing season."

    Design: Difficulty/cross_entity_state_dependency/program_activate_requires_season_active
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Ce2b Co")
    zone = create_zone(sys["id"], 1, plant_type="TURF", head_count=8, gpm_per_head=18)
    tech = create_technician(full_name="Ce2b Tech", shift_start_sec=0, shift_end_sec=86399)
    # WINTERIZED is also not ACTIVE, so activation is still blocked.
    winterize_system(sys["id"], tech["id"], route_date="2026-10-06")
    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["season_state"] == "WINTERIZED"

    prog = create_program(sys["id"], [{"zone_id": zone["id"], "start_sec": 21600, "run_minutes": 20}])
    tech_headers = make_technician_headers(tech["id"])
    resp = api.activate_program(prog["id"], tech_headers)
    validate_error(resp, ApiErrorId.ERR_SEASON_STATE_BLOCKS_PROGRAM.value)


# ===========================================================================
# resource_temporal_overlap
# ===========================================================================
def test_route_stop_adjacent_to_existing_window_allowed(api):
    """PRD §3.6: "The stop occupies the half-open interval beginning at `arrival_start_sec`
    and ending at `arrival_start_sec` plus `window_minutes` times sixty seconds." PRD §3.6:
    "The new stop's window must not overlap the half-open window of any other `SCHEDULED`
    stop already on the same route (otherwise `ERR_ROUTESTOP_TIME_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/route_stop_half_open_overlap_rejected_adjacent_allowed
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="To1b Co")
    tech = create_technician(full_name="To1b Tech", shift_start_sec=0, shift_end_sec=86399)
    w1 = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=60, estimated_cost_cents=2000)
    w2 = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=60, estimated_cost_cents=2000)
    route = create_route(tech["id"], route_date="2026-05-17")
    # First stop occupies [28800, 32400).
    route_after = create_route_stop(route["id"], w1["id"], route["version"],
                                    arrival_start_sec=28800, window_minutes=60)
    # Second stop starts exactly at 32400 (the first's end) -> adjacency, gap=0, allowed.
    stop = validate_success(api.create_route_stop(
        {"route_id": route["id"], "work_order_id": w2["id"], "arrival_start_sec": 32400,
         "window_minutes": 30, "expected_route_version": route_after["version"]}, DISPATCHER),
        expected_status=201)
    assert stop["stop_state"] == "SCHEDULED", "adjacency (gap=0) must be allowed under half-open"


def test_program_slots_with_sufficient_buffer_activate(api):
    """PRD §3.2: "a conflict exists when the gap between the earlier slot's end and the
    later slot's start is less than the valve-switch buffer of 120 seconds." PRD §3.2: "When
    activation succeeds, the program moves `DRAFT → ACTIVE`, every zone referenced in its
    slots whose `zone_state` is `MAPPED` is promoted to `ACTIVE`".

    Design: Difficulty/resource_temporal_overlap/program_slot_buffered_overlap_rejected
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="To2b Co")
    z1 = create_zone(sys["id"], 1, plant_type="TURF", head_count=8, gpm_per_head=18)
    z2 = create_zone(sys["id"], 2, plant_type="SHRUB", head_count=4, gpm_per_head=12)
    tech = create_technician(full_name="To2b Tech", shift_start_sec=0, shift_end_sec=86399)
    winterize_then_startup_system(sys["id"], tech["id"], route_date="2026-10-07")

    # Slot A [21600, 22800); Slot B starts at 22920 -> gap 120s == buffer (not < buffer) -> OK.
    prog = create_program(sys["id"], [
        {"zone_id": z1["id"], "start_sec": 21600, "run_minutes": 20},
        {"zone_id": z2["id"], "start_sec": 22920, "run_minutes": 20},
    ])
    tech_headers = make_technician_headers(tech["id"])
    activated = validate_success(api.activate_program(prog["id"], tech_headers))
    assert activated["program_state"] == "ACTIVE", (
        f"program with a >=120s gap should activate, got {activated['program_state']}")


# ===========================================================================
# compensating_invariant
# ===========================================================================
def test_committed_cost_credited_back_on_completion(api):
    """PRD §3.4: "On success the `completion_status` moves to `COMPLETED`, and four things
    follow. First, because the job is no longer an open commitment, the system's
    `committed_cost_cents` is credited back by this work order's `estimated_cost_cents`."

    Design: Difficulty/compensating_invariant/committed_cost_conserved_on_cancel
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Inv1b Co")
    tech = create_technician(full_name="Inv1b Tech")
    before = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert before["committed_cost_cents"] == 0
    # Create + complete a HEAD_REPAIR; committed cost should return to 0.
    complete_work_order_full(sys["id"], tech["id"], job_type="HEAD_REPAIR",
                             actual_labor_cents=1000, actual_parts_cents=500,
                             estimated_cost_cents=3000, route_date="2026-05-18")
    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["committed_cost_cents"] == 0, (
        f"committed_cost_cents should be credited back to 0 on completion, "
        f"got {system['committed_cost_cents']}")


def test_route_minutes_committed_freed_on_stop_removal(api):
    """PRD §3.6: "its `minutes_committed` is the sum of `window_minutes` over those
    scheduled stops." PRD §3.4: "Cancellation... additionally drives any `SCHEDULED` route
    stop that references this work order to `REMOVED`, recomputing that stop's route
    `stops_used` and `minutes_committed`."

    Design: Difficulty/compensating_invariant/route_slot_count_conserved_on_stop_removal
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Inv2b Co")
    tech = create_technician(full_name="Inv2b Tech")
    wo = create_work_order(sys["id"], job_type="HEAD_REPAIR",
                           estimated_minutes=20, estimated_cost_cents=3000)
    route = create_route(tech["id"], route_date="2026-05-19")
    route_after = create_route_stop(route["id"], wo["id"], route["version"],
                                    arrival_start_sec=28800, window_minutes=60)
    assert route_after["minutes_committed"] == 60

    validate_success(api.cancel_work_order(wo["id"], DISPATCHER))

    route_now = validate_success(api.get_route(route["id"], DISPATCHER))
    assert route_now["minutes_committed"] == 0, (
        f"minutes_committed should return to 0 after stop removal, "
        f"got {route_now['minutes_committed']}")

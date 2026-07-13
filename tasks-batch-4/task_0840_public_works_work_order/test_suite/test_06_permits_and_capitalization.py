"""Right-of-way permits (segment conflict, dispatch clearance gate) and cost
settlement (capital vs maintenance ledgers, betterment reclassification)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, make_asset, make_crew, make_yard, make_material_item, make_work_order,
    schedule_work_order, reserve_crew, make_row_permit, setup_in_progress_work_order,
    dispatcher_headers, crewlead_headers, coordinator_headers,
)

CLOCK = "2026-06-01T00:00:00Z"
DISP = dispatcher_headers()
CREW = crewlead_headers()
COORD = coordinator_headers()


def _complete(api, wo_id):
    return validate_success(api.complete_work_order(wo_id, CREW))


# --- Difficulty: ROW segment closed-interval adjacency conflict ----------

def _two_permits_on_segment(api, second_window):
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="ROAD", gis_segment_id="SEG-X")
    wo = make_work_order(api, asset["id"], work_type="CAPITAL")
    a = make_row_permit(api, wo["id"], permit_type="LANE_CLOSURE", gis_segment_id="SEG-X",
                        window_start="2026-06-02T08:00:00Z", window_end="2026-06-02T12:00:00Z")
    validate_success(api.decide_row_permit(a["id"], {"decision": "APPROVE"}, COORD))
    b = make_row_permit(api, wo["id"], permit_type="LANE_CLOSURE", gis_segment_id="SEG-X",
                        window_start=second_window[0], window_end=second_window[1])
    return b


def test_row_permit_touching_window_conflict_rejected(api):
    """PRD §3.7: "An approval moves it `REQUESTED → APPROVED`, but only if it does not collide on its segment: no other permit on the same `gis_segment_id` in status `APPROVED` or `ACTIVE` may have a closed occupation window `[window_start, window_end]` that intersects this permit's closed window, where adjacency (touching endpoints) counts as an intersection. A collision is rejected with `ERR_ROW_SEGMENT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/row_permit_segment_closed_adjacency_conflict
    """
    b = _two_permits_on_segment(api, ("2026-06-02T12:00:00Z", "2026-06-02T16:00:00Z"))
    validate_error(api.decide_row_permit(b["id"], {"decision": "APPROVE"}, COORD),
                   ApiErrorId.ERR_ROW_SEGMENT_CONFLICT)


def test_row_permit_separated_window_approves(api):
    """PRD §3.7: "no other permit on the same `gis_segment_id` in status `APPROVED` or `ACTIVE` may have a closed occupation window `[window_start, window_end]` that intersects this permit's closed window, where adjacency (touching endpoints) counts as an intersection."

    Design: Difficulty/resource_temporal_overlap/row_permit_segment_closed_adjacency_conflict
    """
    b = _two_permits_on_segment(api, ("2026-06-02T13:00:00Z", "2026-06-02T16:00:00Z"))
    approved = validate_success(api.decide_row_permit(b["id"], {"decision": "APPROVE"}, COORD))
    assert approved["status"] == "APPROVED", f"expected APPROVED, got {approved['status']}"


# --- Difficulty: dispatch blocked until clearance permit approved --------

def _scheduled_wo_with_dispatch_and_pending_permit(api):
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="ROAD", gis_segment_id="SEG-12")
    crew = make_crew(api, name="Paving F")
    wo = make_work_order(api, asset["id"], work_type="CAPITAL")
    schedule_work_order(api, wo["id"])
    reserve_crew(api, wo["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", labor_hours=4)
    permit = make_row_permit(api, wo["id"], permit_type="EXCAVATION", gis_segment_id="SEG-12",
                             window_start="2026-06-02T06:00:00Z", window_end="2026-06-02T20:00:00Z",
                             clearance_required=True)
    return wo, permit


def test_dispatch_blocked_while_clearance_permit_pending(api):
    """PRD §3.8: "And every permit on the work order whose `clearance_required` is true must be `APPROVED`, or it is rejected with `ERR_ROW_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_until_row_permit_approved
    """
    wo, _permit = _scheduled_wo_with_dispatch_and_pending_permit(api)
    validate_error(api.dispatch_work_order(wo["id"], DISP), ApiErrorId.ERR_ROW_NOT_APPROVED)


def test_dispatch_succeeds_after_clearance_permit_approved(api):
    """PRD §3.8: "Once a work order is `SCHEDULED`, has crews reserved and any required permits approved, a `Dispatcher` dispatches it, advancing it `SCHEDULED → DISPATCHED`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_until_row_permit_approved
    """
    wo, permit = _scheduled_wo_with_dispatch_and_pending_permit(api)
    validate_error(api.dispatch_work_order(wo["id"], DISP), ApiErrorId.ERR_ROW_NOT_APPROVED)
    validate_success(api.decide_row_permit(permit["id"], {"decision": "APPROVE"}, COORD))
    dispatched = validate_success(api.dispatch_work_order(wo["id"], DISP))
    assert dispatched["status"] == "DISPATCHED", f"expected DISPATCHED, got {dispatched['status']}"


# --- Difficulty: capital vs maintenance ledger posting ------------------

def _two_ledger_asset(api):
    set_clock(api, CLOCK)
    asset = make_asset(api, asset_class="ROAD", gis_segment_id="SEG-2",
                       install_date="2024-01-01T00:00:00Z", replacement_value_cents=200000)
    crew = make_crew(api, name="Paving A", hourly_rate_cents=6000)
    # WO_A: CAPITAL, 5-hour dispatch -> cost 30000, capitalized outright
    wo_a = make_work_order(api, asset["id"], work_type="CAPITAL")
    schedule_work_order(api, wo_a["id"])
    reserve_crew(api, wo_a["id"], crew["id"], "2026-06-02T08:00:00Z", "2026-06-02T13:00:00Z", labor_hours=5)
    validate_success(api.dispatch_work_order(wo_a["id"], DISP))
    validate_success(api.start_work_order(wo_a["id"], CREW))
    wo_a = _complete(api, wo_a["id"])
    # WO_B: MAINTENANCE, 5-hour dispatch -> cost 30000, below the 500000 floor
    wo_b = make_work_order(api, asset["id"], work_type="MAINTENANCE")
    schedule_work_order(api, wo_b["id"])
    reserve_crew(api, wo_b["id"], crew["id"], "2026-06-03T08:00:00Z", "2026-06-03T13:00:00Z", labor_hours=5)
    validate_success(api.dispatch_work_order(wo_b["id"], DISP))
    validate_success(api.start_work_order(wo_b["id"], CREW))
    wo_b = _complete(api, wo_b["id"])
    asset = get_success_data(api.get_asset(asset["id"], DISP))
    return {"asset": asset, "wo_a": wo_a, "wo_b": wo_b}


def test_capital_workorder_posts_capital_ledger(api):
    """PRD §3.8: "If the declared `work_type` is `CAPITAL`, the order is capitalized outright."
    PRD §3.8: "if `capitalized` is true, `actual_cost_cents` is added to the asset's `capital_cost_to_date_cents`; otherwise it is added to the asset's `maintenance_cost_to_date_cents`."

    Design: Difficulty/dual_variant_calc/capitalization_capital_vs_maintenance_ledger
    """
    ctx = _two_ledger_asset(api)
    assert ctx["wo_a"]["capitalized"] is True, f"expected capitalized true, got {ctx['wo_a']['capitalized']}"
    assert ctx["wo_a"]["actual_cost_cents"] == 30000, f"expected 30000, got {ctx['wo_a']['actual_cost_cents']}"
    assert ctx["asset"]["capital_cost_to_date_cents"] == 30000, \
        f"expected capital ledger 30000, got {ctx['asset']['capital_cost_to_date_cents']}"


def test_maintenance_below_floor_posts_maintenance_ledger(api):
    """PRD §3.8: "When either fails, the `MAINTENANCE` order stays an expense: its total goes to `maintenance_cost_to_date_cents` and the capital ledger is untouched."
    PRD §3.8: "the order is reclassified as capital only when `actual_cost_cents` is at least a capitalization floor of 500,000 cents (5,000 dollars) *and* is at least the asset's `replacement_value_cents` multiplied by a betterment fraction of 0.25 (rounded half up to whole cents)."

    Design: Difficulty/dual_variant_calc/capitalization_capital_vs_maintenance_ledger
    """
    ctx = _two_ledger_asset(api)
    assert ctx["wo_b"]["capitalized"] is False, f"expected capitalized false, got {ctx['wo_b']['capitalized']}"
    assert ctx["wo_b"]["actual_cost_cents"] == 30000, f"expected 30000, got {ctx['wo_b']['actual_cost_cents']}"
    assert ctx["asset"]["maintenance_cost_to_date_cents"] == 30000, \
        f"expected maintenance ledger 30000, got {ctx['asset']['maintenance_cost_to_date_cents']}"


# --- Corner: betterment reclassification, dispatch guard, permit terminal -

def test_betterment_reclassifies_maintenance_to_capital(api):
    """PRD §3.8: "the order is reclassified as capital only when `actual_cost_cents` is at least a capitalization floor of 500,000 cents (5,000 dollars) *and* is at least the asset's `replacement_value_cents` multiplied by a betterment fraction of 0.25 (rounded half up to whole cents). Both comparisons are inclusive lower bounds, and both must hold."
    PRD §3.8: "if `capitalized` is true, `actual_cost_cents` is added to the asset's `capital_cost_to_date_cents`; otherwise it is added to the asset's `maintenance_cost_to_date_cents`."

    Design: Corner/calculations/capitalization_betterment_reclassifies_maintenance_to_capital
    """
    item = make_material_item(api, material_type="ASPHALT_TON", unit="TON", on_hand_qty=200, unit_cost_cents=6000)
    ctx = setup_in_progress_work_order(
        api, clock=CLOCK,
        asset_overrides={"asset_class": "ROAD", "gis_segment_id": "SEG-B3",
                         "install_date": "2022-01-01T00:00:00Z", "replacement_value_cents": 1000000},
        crew_overrides={"name": "Paving X", "hourly_rate_cents": 6000},
        wo_overrides={"work_type": "MAINTENANCE"}, labor_hours=1,
        window=("2026-06-02T08:00:00Z", "2026-06-02T10:00:00Z"),
        reservations=[{"item_id": item["id"], "qty": 100}],
    )
    wo = _complete(api, ctx["wo"]["id"])
    assert wo["actual_cost_cents"] == 606000, f"expected 606000, got {wo['actual_cost_cents']}"
    assert wo["capitalized"] is True, f"expected capitalized true, got {wo['capitalized']}"
    asset = get_success_data(api.get_asset(ctx["asset"]["id"], DISP))
    assert asset["capital_cost_to_date_cents"] == 606000, \
        f"expected capital ledger 606000, got {asset['capital_cost_to_date_cents']}"
    assert asset["maintenance_cost_to_date_cents"] == 0, \
        f"expected maintenance ledger 0, got {asset['maintenance_cost_to_date_cents']}"


def test_dispatch_without_reserved_dispatch_rejected(api):
    """PRD §3.8: "There must be at least one `RESERVED` dispatch for the work order, or it is rejected with `ERR_NO_DISPATCH_FOR_WORKORDER`."

    Design: Corner/validations/dispatch_workorder_without_reserved_dispatch_rejected
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-B8")
    wo = make_work_order(api, asset["id"])
    schedule_work_order(api, wo["id"])
    validate_error(api.dispatch_work_order(wo["id"], DISP), ApiErrorId.ERR_NO_DISPATCH_FOR_WORKORDER)


def test_release_denied_permit_returns_already_terminal(api):
    """PRD §3.7: "A denial moves the permit `REQUESTED → DENIED`, a terminal state."
    PRD §2.10: "attempting any action on a terminal resource returns `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/row_permit_release_after_denied_returns_invalid_or_terminal
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-B2")
    wo = make_work_order(api, asset["id"], work_type="CAPITAL")
    permit = make_row_permit(api, wo["id"], permit_type="UTILITY_COORD", gis_segment_id="SEG-B2",
                             window_start="2026-06-02T08:00:00Z", window_end="2026-06-02T12:00:00Z",
                             clearance_required=False)
    validate_success(api.decide_row_permit(permit["id"], {"decision": "DENY"}, COORD))
    validate_error(api.release_row_permit(permit["id"], COORD), ApiErrorId.ERR_ALREADY_TERMINAL)

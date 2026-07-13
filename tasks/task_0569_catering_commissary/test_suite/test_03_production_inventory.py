"""Production scheduling, station capacity, ingredient commitment/release, cascade.

Translates queue-A instances (non_linear_state_machine/production_run_reschedule_cycle,
transitive_cascade/order_cancel_run_cancel_ingredient_release,
priority_pair_validation_conflict/schedule_run_state_beats_inventory,
cross_entity_state_dependency/pack_requires_all_runs_done,
compensating_invariant/ingredient_qty_conserved_on_schedule_cancel) and queue-B corner
instances (state_machines, validations, endpoints, errors).
"""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID
from test_helpers import fixtures as fx
from test_helpers.constants import dt
from test_helpers.factories import create_production_run_payload


# --------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / production_run_reschedule_cycle
# --------------------------------------------------------------------------
def test_reschedule_returns_run_to_scheduled(api, kitchen_manager_headers):
    """PRD §3.4: "An `IN_PROGRESS` run can be rescheduled back to `SCHEDULED`; the
    reschedule may optionally supply a new `scheduled_start` and `scheduled_end`, and
    when it does, the new window must still keep the station's overlap count within
    `concurrent_capacity` (else `ERR_STATION_OVERBOOKED`) before the window is
    overwritten."

    Design: Difficulty/non_linear_state_machine/production_run_reschedule_cycle
    """
    ctx = fx.run_in_progress(api, run_portions=40)
    data = validate_success(
        api.reschedule_run(ctx["run_id"], kitchen_manager_headers,
                           payload={"scheduled_start": dt(6, 30), "scheduled_end": dt(8, 30)})
    )
    assert data["status"] == "SCHEDULED", f"reschedule must return run to SCHEDULED, got {data['status']}"


def test_reschedule_overwrites_run_window(api, kitchen_manager_headers):
    """PRD §3.4: "the reschedule may optionally supply a new `scheduled_start` and
    `scheduled_end`, and when it does, the new window must still keep the station's
    overlap count within `concurrent_capacity` (else `ERR_STATION_OVERBOOKED`) before the
    window is overwritten."

    Design: Difficulty/non_linear_state_machine/production_run_reschedule_cycle
    """
    ctx = fx.run_in_progress(api, run_portions=40)
    validate_success(
        api.reschedule_run(ctx["run_id"], kitchen_manager_headers,
                           payload={"scheduled_start": dt(6, 30), "scheduled_end": dt(8, 30)})
    )
    run = validate_success(api.get_production_run(ctx["run_id"], kitchen_manager_headers))
    # Window overwritten to the new 06:30 start (format-robust substring match).
    assert "06:30" in run["scheduled_start"], f"window must be overwritten to 06:30, got {run['scheduled_start']}"
    assert run["status"] == "SCHEDULED"


# --------------------------------------------------------------------------
# Difficulty: transitive_cascade / order_cancel_run_cancel_ingredient_release
# --------------------------------------------------------------------------
def test_order_cancel_cascades_run_to_cancelled(api, sales_manager_headers, kitchen_manager_headers):
    """PRD §3.9: "the cancellation cascades across the order's dependents in the same
    transaction: every non-terminal production run is driven to `CANCELLED`, which itself
    releases that run's committed ingredients back to inventory"

    Design: Difficulty/transitive_cascade/order_cancel_run_cancel_ingredient_release
    """
    ctx = fx.scheduled_run(api, run_portions=50, on_hand_qty=100000, qty_per_portion=5)
    order = validate_success(api.cancel_order(ctx["order_id"], sales_manager_headers, payload={"reason": "client cancelled"}))
    assert order["status"] == "CANCELLED", f"order must be CANCELLED, got {order['status']}"
    run = validate_success(api.get_production_run(ctx["run_id"], kitchen_manager_headers))
    assert run["status"] == "CANCELLED", f"run must cascade to CANCELLED, got {run['status']}"


def test_order_cancel_releases_committed_ingredients(api, sales_manager_headers, admin_headers):
    """PRD §3.9: "every non-terminal production run is driven to `CANCELLED`, which itself
    releases that run's committed ingredients back to inventory (each affected
    ingredient's `on_hand_qty` rises and its `committed_qty` falls by the run's required
    amounts)"

    Design: Difficulty/transitive_cascade/order_cancel_run_cancel_ingredient_release
    """
    ctx = fx.scheduled_run(api, run_portions=50, on_hand_qty=100000, qty_per_portion=5)
    validate_success(api.cancel_order(ctx["order_id"], sales_manager_headers))
    ingredient = validate_success(api.get_ingredient(ctx["ingredient_id"], admin_headers))
    assert ingredient["on_hand_qty"] == 100000, f"on_hand must be restored to 100000, got {ingredient['on_hand_qty']}"
    assert ingredient["committed_qty"] == 0, f"committed must return to 0, got {ingredient['committed_qty']}"


# --------------------------------------------------------------------------
# Difficulty: compensating_invariant / ingredient_qty_conserved_on_schedule_cancel
# --------------------------------------------------------------------------
def test_scheduling_run_commits_ingredients(api, admin_headers):
    """PRD §3.4: "When the check passes, each ingredient's `on_hand_qty` is decreased by
    its required amount and its `committed_qty` is increased by the same, keeping the
    on-hand-plus-committed total conserved."

    Design: Difficulty/compensating_invariant/ingredient_qty_conserved_on_schedule_cancel
    """
    ctx = fx.scheduled_run(api, run_portions=50, on_hand_qty=100000, qty_per_portion=5)  # need 250
    ingredient = validate_success(api.get_ingredient(ctx["ingredient_id"], admin_headers))
    assert ingredient["on_hand_qty"] == 99750, f"100000-250, got {ingredient['on_hand_qty']}"
    assert ingredient["committed_qty"] == 250, f"0+250, got {ingredient['committed_qty']}"


def test_cancelling_run_restores_ingredient_inventory(api, kitchen_manager_headers, admin_headers):
    """PRD §3.4: "cancellation releases its committed ingredients — for each recipe line,
    the ingredient's `on_hand_qty` is increased by the required amount and its
    `committed_qty` decreased by the same, the exact inverse of the commitment."

    Design: Difficulty/compensating_invariant/ingredient_qty_conserved_on_schedule_cancel
    """
    ctx = fx.scheduled_run(api, run_portions=50, on_hand_qty=100000, qty_per_portion=5)
    validate_success(api.cancel_run(ctx["run_id"], kitchen_manager_headers))
    ingredient = validate_success(api.get_ingredient(ctx["ingredient_id"], admin_headers))
    assert ingredient["on_hand_qty"] == 100000, f"on_hand restored, got {ingredient['on_hand_qty']}"
    assert ingredient["committed_qty"] == 0, f"committed restored, got {ingredient['committed_qty']}"


# --------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / schedule_run_state_beats_inventory
# --------------------------------------------------------------------------
def _draft_order_with_recipe(api, *, on_hand_qty):
    ingredient = fx.create_ingredient(api, on_hand_qty=on_hand_qty)
    menu_item = fx.create_menu_item(api)
    fx.add_recipe_line(api, menu_item["id"], ingredient["id"], qty_per_portion=5)
    station = fx.create_station(api)
    order = fx.create_event_order(api, guest_count=50, service_charge_pct=0.10, gratuity_pct=0.10)
    return order["id"], station["id"], menu_item["id"]


def test_schedule_run_on_draft_reports_state_before_inventory(api, kitchen_manager_headers):
    """PRD §3.4: "A run may only be scheduled while its parent order is `CONFIRMED`;
    otherwise the attempt is an `ERR_INVALID_STATE` conflict."
    PRD §2.6: "the checks are evaluated in a fixed priority order, and the first failure
    encountered is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/schedule_run_state_beats_inventory
    """
    order_id, station_id, menu_item_id = _draft_order_with_recipe(api, on_hand_qty=1)  # need 250 > 1
    resp = api.create_production_run(
        create_production_run_payload(order_id, station_id, menu_item_id, portions=50), kitchen_manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_schedule_run_on_draft_with_ample_inventory_still_state(api, kitchen_manager_headers):
    """PRD §3.4: "A run may only be scheduled while its parent order is `CONFIRMED`;
    otherwise the attempt is an `ERR_INVALID_STATE` conflict."

    Design: Difficulty/priority_pair_validation_conflict/schedule_run_state_beats_inventory
    """
    order_id, station_id, menu_item_id = _draft_order_with_recipe(api, on_hand_qty=100000)  # inventory fine
    resp = api.create_production_run(
        create_production_run_payload(order_id, station_id, menu_item_id, portions=50), kitchen_manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# --------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / pack_requires_all_runs_done
# --------------------------------------------------------------------------
def test_pack_with_in_progress_run_rejected(api, kitchen_manager_headers):
    """PRD §3.4: "packing requires that every non-`CANCELLED` run of the order be `DONE`,
    and otherwise fails with `ERR_PRODUCTION_NOT_COMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/pack_requires_all_runs_done
    """
    ctx = fx.run_in_progress(api, run_portions=40)  # run is IN_PROGRESS, not DONE
    validate_error(api.pack_order(ctx["order_id"], kitchen_manager_headers),
                   ApiErrorId.ERR_PRODUCTION_NOT_COMPLETE)


def test_pack_with_all_runs_done_succeeds(api, kitchen_manager_headers):
    """PRD §3.4: "Once all runs are `DONE`, the kitchen manager packs the order,
    advancing it `IN_PRODUCTION → PACKED`"

    Design: Difficulty/cross_entity_state_dependency/pack_requires_all_runs_done
    """
    ctx = fx.run_in_progress(api, run_portions=40)
    validate_success(api.complete_run(ctx["run_id"], kitchen_manager_headers))
    order = validate_success(api.pack_order(ctx["order_id"], kitchen_manager_headers))
    assert order["status"] == "PACKED", f"pack must advance to PACKED, got {order['status']}"


# --------------------------------------------------------------------------
# Corner: state_machines / validations / endpoints / errors
# --------------------------------------------------------------------------
def test_production_run_starts_in_scheduled_initial_state(api, kitchen_manager_headers):
    """PRD §3.4: "and references the order (`event_order_id`), the executing station
    (`station_id`), the item being made (`menu_item_id`), the number of `portions` to
    produce, and its `scheduled_start` and `scheduled_end` window; it begins in
    `SCHEDULED` status."

    Design: Corner/state_machines/production_run_starts_in_scheduled_initial_state
    """
    ctx = fx.scheduled_run(api, run_portions=40)
    run = validate_success(api.get_production_run(ctx["run_id"], kitchen_manager_headers))
    assert run["status"] == "SCHEDULED", f"new run must be SCHEDULED, got {run['status']}"


def test_insufficient_inventory_on_confirmed_order_returns_422(api, kitchen_manager_headers):
    """PRD §3.4: "Before committing, the system requires the referenced ingredient's
    `on_hand_qty` to be at least that required amount; if any ingredient falls short, the
    whole run is rejected with `ERR_INSUFFICIENT_INVENTORY`."

    Design: Corner/validations/insufficient_inventory_on_confirmed_order_returns_422
    """
    ctx = fx.confirmed_order_for_production(api, on_hand_qty=100, qty_per_portion=5)  # need 250 > 100
    resp = api.create_production_run(
        create_production_run_payload(ctx["order_id"], ctx["station_id"], ctx["menu_item_id"], portions=50),
        kitchen_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)


def test_station_overbooked_second_overlapping_run_returns_409(api, kitchen_manager_headers):
    """PRD §3.4: "at every instant within the new run's window, the count of overlapping
    non-`CANCELLED` runs already on that station, plus this one, must not exceed the
    station's `concurrent_capacity`; a violation is rejected with `ERR_STATION_OVERBOOKED`."

    Design: Corner/validations/station_overbooked_second_overlapping_run_returns_409
    """
    ctx = fx.scheduled_run(api, run_portions=20, station_capacity=1,
                           scheduled_start=dt(6), scheduled_end=dt(8))
    resp = api.create_production_run(
        create_production_run_payload(ctx["order_id"], ctx["station_id"], ctx["menu_item_id"],
                                      portions=20, scheduled_start=dt(7), scheduled_end=dt(9)),
        kitchen_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STATION_OVERBOOKED)


def test_list_production_runs_by_event_order_fk(api, kitchen_manager_headers):
    """PRD §3.4: "Production runs may be listed filtered by `event_order_id`,
    `station_id`, and/or `menu_item_id`."

    Design: Corner/endpoints/list_production_runs_by_event_order_fk
    """
    ctx = fx.scheduled_run(api, run_portions=40)
    data, _ = validate_paginated(
        api.list_production_runs(kitchen_manager_headers, params={"event_order_id": ctx["order_id"]})
    )
    ids = {run["id"] for run in data}
    assert ctx["run_id"] in ids, "scheduled run must be discoverable via event_order_id filter"


def test_production_run_unknown_menu_item_returns_not_found(api, kitchen_manager_headers):
    """PRD §2.9: "a missing menu item with `ERR_MENU_ITEM_NOT_FOUND`"

    Design: Corner/errors/production_run_unknown_menu_item_returns_not_found
    """
    ctx = fx.confirmed_order_for_production(api)
    resp = api.create_production_run(
        create_production_run_payload(ctx["order_id"], ctx["station_id"], NON_EXISTENT_UUID, portions=20),
        kitchen_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_MENU_ITEM_NOT_FOUND)


def test_start_unknown_production_run_returns_resource_not_found(api, kitchen_manager_headers):
    """PRD §2.9: "When the target of a child action or a fetch-by-id — an order line,
    production run, rental reservation, staff assignment, or quote — does not resolve, the
    error is `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/errors/start_unknown_production_run_returns_resource_not_found
    """
    validate_error(api.start_run(NON_EXISTENT_UUID, kitchen_manager_headers), ApiErrorId.ERR_RESOURCE_NOT_FOUND)

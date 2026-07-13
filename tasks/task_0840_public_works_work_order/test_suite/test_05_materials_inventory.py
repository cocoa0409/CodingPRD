"""Materials & yard inventory: per-line rounding on completion, the
availability boundary, the reserve/release conservation invariant, reservation
state/existence guards, OCC, restock, and lookups."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    set_clock, make_asset, make_yard, make_material_item, make_crew,
    make_work_order, schedule_work_order, reserve_crew, reserve_material,
    setup_scheduled_work_order, setup_in_progress_work_order,
    supervisor_headers, dispatcher_headers, crewlead_headers,
)

CLOCK = "2026-06-01T00:00:00Z"
SUP = supervisor_headers()
DISP = dispatcher_headers()
CREW = crewlead_headers()


def _item_version(api, item_id):
    return get_success_data(api.get_material_item(item_id, DISP))["version"]


# --- Difficulty: per-line rounding then sum on completion ---------------

def _completed_rounding_wo(api):
    item = make_material_item(api, material_type="ASPHALT_TON", unit="TON",
                              on_hand_qty=100, unit_cost_cents=1233)
    ctx = setup_in_progress_work_order(
        api, clock=CLOCK, asset_overrides={"gis_segment_id": "SEG-4"},
        wo_overrides={"work_type": "MAINTENANCE"}, labor_hours=1,
        window=("2026-06-02T08:00:00Z", "2026-06-02T10:00:00Z"),
        reservations=[{"item_id": item["id"], "qty": 2.5}, {"item_id": item["id"], "qty": 1.5}],
    )
    return validate_success(api.complete_work_order(ctx["wo"]["id"], CREW))


def test_material_cost_rounds_each_line_before_summing(api):
    """PRD §3.8: "The `material_cost_cents` is the sum, over the work order's `CONSUMED` reservations, of each reservation's line cost computed as `qty` times the item's `unit_cost_cents` rounded half up to whole cents — each line is rounded before the lines are summed, never after, because summing first and rounding once can differ by a cent."

    Design: Difficulty/combinatorial_formula/material_round_per_line_then_sum
    """
    wo = _completed_rounding_wo(api)
    assert wo["material_cost_cents"] == 4933, f"expected 4933, got {wo['material_cost_cents']}"


def test_actual_cost_is_labor_plus_material(api):
    """PRD §3.8: "The `actual_cost_cents` is `labor_cost_cents` plus `material_cost_cents`."

    Design: Difficulty/combinatorial_formula/material_round_per_line_then_sum
    """
    wo = _completed_rounding_wo(api)
    assert wo["actual_cost_cents"] == wo["labor_cost_cents"] + wo["material_cost_cents"]
    assert wo["actual_cost_cents"] == 10933, f"expected 10933 (6000 labor + 4933 material), got {wo['actual_cost_cents']}"


# --- Difficulty: availability boundary (qty == available) ----------------

def test_reserve_exactly_available_qty_succeeds(api):
    """PRD §3.6: "The requested `qty` must not exceed the item's current `available_qty`; an over-reservation is rejected with `ERR_INSUFFICIENT_MATERIAL`."

    Design: Difficulty/boundary_precision_check/material_reservation_exact_available_inclusive
    """
    ctx = setup_scheduled_work_order(api, clock=CLOCK, asset_overrides={"asset_class": "SIGN", "gis_segment_id": "SEG-11"})
    item = make_material_item(api, material_type="SIGN_BLANK", unit="EACH", on_hand_qty=10, unit_cost_cents=2500)
    res = reserve_material(api, ctx["wo"]["id"], item["id"], 10)
    assert res["status"] == "RESERVED", f"expected RESERVED, got {res['status']}"


def test_reserve_exactly_available_drives_available_to_zero(api):
    """PRD §3.6: "A material item tracks a computed `reserved_qty` (the sum of `qty` over its `RESERVED` reservations, starting at 0) and a computed `available_qty` equal to `on_hand_qty` minus `reserved_qty`."

    Design: Difficulty/boundary_precision_check/material_reservation_exact_available_inclusive
    """
    ctx = setup_scheduled_work_order(api, clock=CLOCK, asset_overrides={"asset_class": "SIGN", "gis_segment_id": "SEG-11"})
    item = make_material_item(api, material_type="SIGN_BLANK", unit="EACH", on_hand_qty=10, unit_cost_cents=2500)
    reserve_material(api, ctx["wo"]["id"], item["id"], 10)
    item = get_success_data(api.get_material_item(item["id"], DISP))
    assert item["reserved_qty"] == 10, f"expected reserved_qty 10, got {item['reserved_qty']}"
    assert item["available_qty"] == 0, f"expected available_qty 0, got {item['available_qty']}"


# --- Difficulty: reserve then release conserves inventory ---------------

def _reserved_then_released_item(api):
    ctx = setup_scheduled_work_order(api, clock=CLOCK, asset_overrides={"gis_segment_id": "SEG-15"})
    item = make_material_item(api, material_type="ASPHALT_TON", unit="TON", on_hand_qty=100, unit_cost_cents=1200)
    res = reserve_material(api, ctx["wo"]["id"], item["id"], 30)
    validate_success(api.release_material_reservation(res["id"], DISP))
    return get_success_data(api.get_material_item(item["id"], DISP))


def test_release_leaves_on_hand_unchanged(api):
    """PRD §3.6: "Release returns the held quantity — the item's `reserved_qty` is decreased by `qty` while `on_hand_qty` is left unchanged — and increments the item's `version` and the reservation's `version`."

    Design: Difficulty/compensating_invariant/material_reserve_then_release_conserves_on_hand
    """
    item = _reserved_then_released_item(api)
    assert item["on_hand_qty"] == 100, f"expected on_hand_qty 100, got {item['on_hand_qty']}"


def test_release_restores_reserved_and_available(api):
    """PRD §3.6: "Release returns the held quantity — the item's `reserved_qty` is decreased by `qty` while `on_hand_qty` is left unchanged — and increments the item's `version` and the reservation's `version`."

    Design: Difficulty/compensating_invariant/material_reserve_then_release_conserves_on_hand
    """
    item = _reserved_then_released_item(api)
    assert item["reserved_qty"] == 0, f"expected reserved_qty 0, got {item['reserved_qty']}"
    assert item["available_qty"] == 100, f"expected available_qty 100, got {item['available_qty']}"


# --- Difficulty: reservation requires a non-DRAFT work order ------------

def test_reservation_against_draft_workorder_rejected(api):
    """PRD §3.6: "The referenced work order must be in one of `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `ON_HOLD` — a `DRAFT`, `COMPLETED`, or `CANCELLED` work order cannot receive reservations, and a violation is an illegal-state condition (`ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/reservation_requires_workorder_scheduled
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-13")
    item = make_material_item(api, material_type="ASPHALT_TON", unit="TON", on_hand_qty=50, unit_cost_cents=1200)
    wo = make_work_order(api, asset["id"])  # DRAFT
    payload = {"work_order_id": wo["id"], "material_item_id": item["id"], "qty": 5,
               "expected_material_item_version": _item_version(api, item["id"])}
    validate_error(api.create_material_reservation(payload, DISP), ApiErrorId.ERR_INVALID_STATE)


def test_reservation_succeeds_once_workorder_scheduled(api):
    """PRD §3.6: "On success the reservation is created `RESERVED` with `consumed_cost_cents` at 0, the item's `reserved_qty` is increased by `qty`, and the item's `version` is incremented."

    Design: Difficulty/cross_entity_state_dependency/reservation_requires_workorder_scheduled
    """
    set_clock(api, CLOCK)
    asset = make_asset(api, gis_segment_id="SEG-13")
    item = make_material_item(api, material_type="ASPHALT_TON", unit="TON", on_hand_qty=50, unit_cost_cents=1200)
    wo = make_work_order(api, asset["id"])
    schedule_work_order(api, wo["id"])
    res = reserve_material(api, wo["id"], item["id"], 5)
    assert res["status"] == "RESERVED", f"expected RESERVED, got {res['status']}"


# --- Difficulty: existence check beats insufficient-material ------------

def test_reservation_existence_beats_insufficient_material(api):
    """PRD §2.6: "Existence — every path `id` and every foreign-key `id` in the body exists, validated left-to-right in the order `asset_id`, `work_order_id`, `crew_id`, `material_item_id`, `service_request_id`, `duplicate_of_id`; a miss yields the resource-specific not-found error (see §5) at HTTP 404."
    PRD §2.6: "and finally the sufficient-material check on reservation creation (`ERR_INSUFFICIENT_MATERIAL`)."

    Design: Difficulty/priority_pair_validation_conflict/reservation_existence_beats_insufficient_material
    """
    set_clock(api, CLOCK)
    item = make_material_item(api, material_type="SIGN_BLANK", unit="EACH", on_hand_qty=5, unit_cost_cents=1000)
    payload = {"work_order_id": NON_EXISTENT_UUID, "material_item_id": item["id"], "qty": 999,
               "expected_material_item_version": _item_version(api, item["id"])}
    validate_error(api.create_material_reservation(payload, DISP), ApiErrorId.ERR_WORK_ORDER_NOT_FOUND)


def test_reservation_missing_workorder_not_found_isolated(api):
    """PRD §2.6: "Existence — every path `id` and every foreign-key `id` in the body exists, validated left-to-right in the order `asset_id`, `work_order_id`, `crew_id`, `material_item_id`, `service_request_id`, `duplicate_of_id`; a miss yields the resource-specific not-found error (see §5) at HTTP 404."

    Design: Difficulty/priority_pair_validation_conflict/reservation_existence_beats_insufficient_material
    """
    set_clock(api, CLOCK)
    item = make_material_item(api, material_type="SIGN_BLANK", unit="EACH", on_hand_qty=5, unit_cost_cents=1000)
    payload = {"work_order_id": NON_EXISTENT_UUID, "material_item_id": item["id"], "qty": 3,
               "expected_material_item_version": _item_version(api, item["id"])}
    validate_error(api.create_material_reservation(payload, DISP), ApiErrorId.ERR_WORK_ORDER_NOT_FOUND)


# --- Corner: computed field, over-available, restock, filter, OCC -------

def test_material_item_available_qty_computed(api):
    """PRD §3.6: "A material item tracks a computed `reserved_qty` (the sum of `qty` over its `RESERVED` reservations, starting at 0) and a computed `available_qty` equal to `on_hand_qty` minus `reserved_qty`."

    Design: Corner/entities/material_item_available_qty_computed
    """
    item = make_material_item(api, material_type="SIGNAL_LAMP", unit="EACH", on_hand_qty=40, unit_cost_cents=900)
    assert item["reserved_qty"] == 0, f"expected reserved_qty 0, got {item['reserved_qty']}"
    assert item["available_qty"] == 40, f"expected available_qty 40, got {item['available_qty']}"


def test_reserve_over_available_rejected(api):
    """PRD §3.6: "The requested `qty` must not exceed the item's current `available_qty`; an over-reservation is rejected with `ERR_INSUFFICIENT_MATERIAL`."

    Design: Corner/validations/material_reservation_over_available_rejected
    """
    ctx = setup_scheduled_work_order(api, clock=CLOCK, asset_overrides={"asset_class": "SIGN", "gis_segment_id": "SEG-B9"})
    item = make_material_item(api, material_type="SIGN_BLANK", unit="EACH", on_hand_qty=10, unit_cost_cents=2500)
    payload = {"work_order_id": ctx["wo"]["id"], "material_item_id": item["id"], "qty": 11,
               "expected_material_item_version": _item_version(api, item["id"])}
    validate_error(api.create_material_reservation(payload, DISP), ApiErrorId.ERR_INSUFFICIENT_MATERIAL)


def test_restock_increases_on_hand(api):
    """PRD §3.6: "A `Supervisor` restocks an item by supplying a `qty` to add, which increases `on_hand_qty` by that amount and increments the item's `version`."

    Design: Corner/endpoints/material_item_restock_increases_on_hand
    """
    item = make_material_item(api, material_type="SIGNAL_LAMP", unit="EACH", on_hand_qty=30, unit_cost_cents=800)
    updated = validate_success(api.restock_material_item(item["id"], {"qty": 20}, SUP))
    assert updated["on_hand_qty"] == 50, f"expected on_hand_qty 50, got {updated['on_hand_qty']}"


def test_material_items_filtered_by_yard(api):
    """PRD §3.6: "Yards and material items can be fetched and listed; the material-items list filters on `material_type` and on `yard_id`."

    Design: Corner/endpoints/material_items_filtered_by_yard_reverse_reachability
    """
    yard = make_yard(api, name="North Yard", location_desc="North")
    item = make_material_item(api, yard_id=yard["id"], material_type="ASPHALT_TON", unit="TON",
                              on_hand_qty=20, unit_cost_cents=1200)
    data, _meta = validate_paginated(api.list_material_items(SUP, params={"yard_id": yard["id"]}))
    assert len(data) == 1, f"expected one item for yard, got {len(data)}"
    assert data[0]["id"] == item["id"]
    assert data[0]["yard_id"] == yard["id"]


def test_stale_material_version_rejected(api):
    """PRD §2.5: "When reserving material (creating a `MaterialReservation`), the request body must include `expected_material_item_version`, carrying the client's last-observed `version` of the target `MaterialItem`. If that value does not equal the item's current `version` ... the reservation is rejected with `ERR_STALE_MATERIAL_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_material_version_rejected
    """
    ctx = setup_scheduled_work_order(api, clock=CLOCK, asset_overrides={"gis_segment_id": "SEG-C5"})
    item = make_material_item(api, material_type="ASPHALT_TON", unit="TON", on_hand_qty=100, unit_cost_cents=1200)
    v0 = item["version"]  # 1
    reserve_material(api, ctx["wo"]["id"], item["id"], 5)  # advances item version to 2
    stale = {"work_order_id": ctx["wo"]["id"], "material_item_id": item["id"], "qty": 5,
             "expected_material_item_version": v0}
    validate_error(api.create_material_reservation(stale, DISP), ApiErrorId.ERR_STALE_MATERIAL_VERSION)

"""Fair booth reservations (overlap + capacity) and shipment cost + packing buffer."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_fair_event_payload, create_booth_slot_payload,
    create_sale_order_payload, create_shipment_payload, TEST_USERS,
)
from test_helpers.fixtures import make_fair_with_slot, make_empty_sale_order
from test_helpers.api_client import api_client

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["storeclerk_headers"]


def _new_shipment(api, packing_station_label, pack_start, pack_end, weight_grams=400, zone=1):
    order = make_empty_sale_order(channel="ONLINE")
    payload = create_shipment_payload(packing_station_label, weight_grams, zone, pack_start, pack_end)
    return order, api.create_shipment(order["id"], payload, CLERK)


# ── shipping cost (nested min/max) ──────────────────────────────────────────

def test_shipping_cost_carriage_and_insurance(api):
    """PRD §3.9: "Carriage is the zone base plus 150 cents per step, then clamped to
    lie between a floor of 500 cents and a cap of 6000 cents ... When it is insured,
    insurance is the `declared_value_cents` multiplied by an insurance rate of 0.02,
    rounded half up to whole cents, then held between a minimum of 200 cents and a
    maximum of 5000 cents ... The final `shipping_cost_cents` is the clamped carriage
    plus this insurance."

    Design: Difficulty/combinatorial_formula/shipping_cost_nested_min_max_mode_a
    """
    order = make_empty_sale_order(channel="ONLINE")
    payload = create_shipment_payload("S1", 900, 2, "2026-07-01T10:00:00.000Z",
                                      "2026-07-01T11:00:00.000Z",
                                      declared_value_cents=100000, insured=True)
    shipment = validate_success(api.create_shipment(order["id"], payload, CLERK), 201)
    assert shipment["shipping_cost_cents"] == 3100


def test_shipping_cost_insurance_capped(api):
    """PRD §3.9: "When it is insured, insurance is the `declared_value_cents`
    multiplied by an insurance rate of 0.02, rounded half up to whole cents, then held
    between a minimum of 200 cents and a maximum of 5000 cents — a computed value
    below 200 is raised to 200 and one above 5000 is lowered to 5000. The final
    `shipping_cost_cents` is the clamped carriage plus this insurance."

    Design: Difficulty/combinatorial_formula/shipping_cost_nested_min_max_mode_a
    """
    # carriage: base 1800 (zone4) + ceil(700/250)=3 steps * 150 = 2250; insurance
    # round(300000*0.02)=6000 -> capped to 5000; total 2250 + 5000 = 7250.
    order = make_empty_sale_order(channel="ONLINE")
    payload = create_shipment_payload("S2", 1200, 4, "2026-07-02T10:00:00.000Z",
                                      "2026-07-02T11:00:00.000Z",
                                      declared_value_cents=300000, insured=True)
    shipment = validate_success(api.create_shipment(order["id"], payload, CLERK), 201)
    assert shipment["shipping_cost_cents"] == 7250


def test_shipping_cost_floor_at_min_weight(api):
    """PRD §3.9: "Carriage is the zone base plus 150 cents per step, then clamped to
    lie between a floor of 500 cents and a cap of 6000 cents — values below the floor
    are raised to 500, values above the cap are lowered to 6000. Insurance is 0 when
    the shipment is not insured."

    Design: Corner/calculations/shipping_cost_floor_applies_at_min_weight
    """
    order = make_empty_sale_order(channel="ONLINE")
    payload = create_shipment_payload("SF", 500, 1, "2026-07-01T08:00:00.000Z",
                                      "2026-07-01T08:30:00.000Z", insured=False)
    shipment = validate_success(api.create_shipment(order["id"], payload, CLERK), 201)
    assert shipment["shipping_cost_cents"] == 500


# ── booth slot half-open adjacency (accepted) ───────────────────────────────

def test_booth_adjacent_slot_accepted_after(api):
    """PRD §3.7: "touching intervals, where one window's end equals the other's start,
    do not overlap. A conflict is rejected with `ERR_BOOTH_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/booth_slot_half_open_adjacency_accepted
    """
    ctx = make_fair_with_slot(table_capacity=10, booth_table="T1",
                              window_start="2026-07-11T10:00:00.000Z",
                              window_end="2026-07-11T12:00:00.000Z", display_item_count=1)
    payload = create_booth_slot_payload("T1", "2026-07-11T12:00:00.000Z",
                                        "2026-07-11T14:00:00.000Z", display_item_count=1)
    slot2 = validate_success(api.create_booth_slot(ctx["fair"]["id"], payload, CLERK), 201)
    assert slot2["status"] == "RESERVED"


def test_booth_adjacent_slot_accepted_before(api):
    """PRD §3.7: "touching intervals, where one window's end equals the other's start,
    do not overlap. A conflict is rejected with `ERR_BOOTH_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/booth_slot_half_open_adjacency_accepted
    """
    ctx = make_fair_with_slot(table_capacity=10, booth_table="T1",
                              window_start="2026-07-11T10:00:00.000Z",
                              window_end="2026-07-11T12:00:00.000Z", display_item_count=1)
    payload = create_booth_slot_payload("T1", "2026-07-11T08:00:00.000Z",
                                        "2026-07-11T10:00:00.000Z", display_item_count=1)
    slot2 = validate_success(api.create_booth_slot(ctx["fair"]["id"], payload, CLERK), 201)
    assert slot2["status"] == "RESERVED"


# ── booth temporal overlap outranks aggregate capacity ──────────────────────

def test_booth_overlap_outranks_capacity_v1(api):
    """PRD §2.8: "On booth-slot reservation, the temporal overlap check (yielding
    `ERR_BOOTH_SLOT_CONFLICT`) outranks the aggregate-capacity check (yielding
    `ERR_FAIR_CAPACITY_EXCEEDED`). If both fail, the overlap error is reported."

    Design: Difficulty/priority_pair_validation_conflict/booth_temporal_outranks_capacity_constraint
    """
    ctx = make_fair_with_slot(table_capacity=1, booth_table="T1",
                              window_start="2026-07-10T10:00:00.000Z",
                              window_end="2026-07-10T12:00:00.000Z", display_item_count=1)
    payload = create_booth_slot_payload("T1", "2026-07-10T11:00:00.000Z",
                                        "2026-07-10T13:00:00.000Z", display_item_count=5)
    res = api.create_booth_slot(ctx["fair"]["id"], payload, CLERK)
    validate_error(res, "ERR_BOOTH_SLOT_CONFLICT", expected_status=409)


def test_booth_overlap_outranks_capacity_v2(api):
    """PRD §2.8: "On booth-slot reservation, the temporal overlap check (yielding
    `ERR_BOOTH_SLOT_CONFLICT`) outranks the aggregate-capacity check (yielding
    `ERR_FAIR_CAPACITY_EXCEEDED`). If both fail, the overlap error is reported."

    Design: Difficulty/priority_pair_validation_conflict/booth_temporal_outranks_capacity_constraint
    """
    ctx = make_fair_with_slot(table_capacity=1, booth_table="T1",
                              window_start="2026-07-10T10:00:00.000Z",
                              window_end="2026-07-10T12:00:00.000Z", display_item_count=1)
    payload = create_booth_slot_payload("T1", "2026-07-10T11:00:00.000Z",
                                        "2026-07-10T13:00:00.000Z", display_item_count=10)
    res = api.create_booth_slot(ctx["fair"]["id"], payload, CLERK)
    validate_error(res, "ERR_BOOTH_SLOT_CONFLICT", expected_status=409)


def test_booth_overlap_same_table_rejected(api):
    """PRD §3.7: "The overlap guard treats windows as half-open: a new slot conflicts
    with an existing slot on the same `fair_event_id` and same `booth_table` when the
    existing slot starts before the new slot ends and the new slot starts before the
    existing slot ends".

    Design: Corner/validations/booth_overlap_same_table_returns_409
    """
    ctx = make_fair_with_slot(table_capacity=10, booth_table="T1",
                              window_start="2026-07-14T10:00:00.000Z",
                              window_end="2026-07-14T12:00:00.000Z", display_item_count=1)
    payload = create_booth_slot_payload("T1", "2026-07-14T11:00:00.000Z",
                                        "2026-07-14T13:00:00.000Z", display_item_count=1)
    res = api.create_booth_slot(ctx["fair"]["id"], payload, CLERK)
    validate_error(res, "ERR_BOOTH_SLOT_CONFLICT", expected_status=409)


def test_fair_capacity_exceeded_across_tables(api):
    """PRD §3.7: "The capacity guard sums the `display_item_count` of all existing
    slots on the same `fair_event_id` whose window overlaps the new window (half-open),
    adds the new slot's `display_item_count`, and rejects the reservation with
    `ERR_FAIR_CAPACITY_EXCEEDED` when that total exceeds the fair's `table_capacity`."

    Design: Corner/validations/fair_capacity_exceeded_across_tables_returns_409
    """
    ctx = make_fair_with_slot(table_capacity=3, booth_table="T1",
                              window_start="2026-07-13T10:00:00.000Z",
                              window_end="2026-07-13T12:00:00.000Z", display_item_count=2)
    payload = create_booth_slot_payload("T2", "2026-07-13T10:30:00.000Z",
                                        "2026-07-13T11:30:00.000Z", display_item_count=2)
    res = api.create_booth_slot(ctx["fair"]["id"], payload, CLERK)
    validate_error(res, "ERR_FAIR_CAPACITY_EXCEEDED", expected_status=409)


def test_booth_window_end_before_start_rejected(api):
    """PRD §3.7: "A slot's window must be well-formed — `window_end` strictly after
    `window_start`, else `ERR_INVALID_WINDOW` — and every slot is created directly in
    `RESERVED`."

    Design: Corner/validations/booth_window_end_before_start_returns_invalid_request
    """
    fair = validate_success(api.create_fair_event(
        create_fair_event_payload(name="Bad Window Fair", table_capacity=5), MANAGER), 201)
    payload = create_booth_slot_payload("T1", "2026-07-15T12:00:00.000Z", "2026-07-15T10:00:00.000Z")
    res = api.create_booth_slot(fair["id"], payload, CLERK)
    validate_error(res, "ERR_INVALID_WINDOW", expected_status=400)


# ── packing-slot buffer (rejected within buffer) ────────────────────────────

def test_packing_slot_within_buffer_rejected_after(api):
    """PRD §3.9: "A new shipment is accepted only when it is clear of every other
    shipment on that same station by at least the buffer — that is, either the new
    packing slot's `pack_start` is at least 15 minutes at or after the other
    shipment's `pack_end`, or the other shipment's `pack_start` is at least 15 minutes
    at or after the new slot's `pack_end`. Being exactly the buffer apart is accepted;
    any closer overlap is rejected with `ERR_PACKING_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/packing_slot_within_buffer_rejected
    """
    _new_shipment(api, "S9", "2026-07-12T10:00:00.000Z", "2026-07-12T11:00:00.000Z")
    _, res = _new_shipment(api, "S9", "2026-07-12T11:10:00.000Z", "2026-07-12T12:00:00.000Z")
    validate_error(res, "ERR_PACKING_SLOT_CONFLICT", expected_status=409)


def test_packing_slot_within_buffer_rejected_before(api):
    """PRD §3.9: "A new shipment is accepted only when it is clear of every other
    shipment on that same station by at least the buffer — that is, either the new
    packing slot's `pack_start` is at least 15 minutes at or after the other
    shipment's `pack_end`, or the other shipment's `pack_start` is at least 15 minutes
    at or after the new slot's `pack_end`. Being exactly the buffer apart is accepted;
    any closer overlap is rejected with `ERR_PACKING_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/packing_slot_within_buffer_rejected
    """
    _new_shipment(api, "S8", "2026-07-12T11:00:00.000Z", "2026-07-12T12:00:00.000Z")
    _, res = _new_shipment(api, "S8", "2026-07-12T10:00:00.000Z", "2026-07-12T10:50:00.000Z")
    validate_error(res, "ERR_PACKING_SLOT_CONFLICT", expected_status=409)

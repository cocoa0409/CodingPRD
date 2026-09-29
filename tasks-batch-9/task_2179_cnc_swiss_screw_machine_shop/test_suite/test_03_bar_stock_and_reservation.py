"""Bar stock receipt, mill certification and the conserved length ledger."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_bar_length_ledger,
    cancel_work_order,
    certify_bar_lot,
    machine_version,
    make_quality_manager_headers,
    make_shop_planner_headers,
    read_bar_lot,
    read_work_order,
    receive_bar_lot,
    register_part,
    set_clock,
    setup_scheduled_work_order,
    setup_shop_floor,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = make_shop_planner_headers()
QUALITY = make_quality_manager_headers()


class TestBarLengthConservation:
    """Millimetres of bar move between buckets and are never created or lost."""

    def test_scheduling_moves_length_from_available_into_reserved(self):
        """PRD 3.5: "When every gate passes, the reservation is booked: the
        reserved length is subtracted from the lot's `available_length_mm` and
        added to its `reserved_length_mm`, leaving the conserved total of §2.7
        intact."
        PRD 2.7: "At every instant, `available_length_mm` plus
        `reserved_length_mm` plus `consumed_length_mm` equals `total_length_mm`
        exactly."

        Design: Difficulty/compensating_invariant/bar_length_conserved_across_reserve_and_cancel
        """
        shop = setup_scheduled_work_order()

        lot = read_bar_lot(shop.lot_id)
        assert lot["total_length_mm"] == 72000
        assert lot["available_length_mm"] == 64800
        assert lot["reserved_length_mm"] == 7200
        assert lot["consumed_length_mm"] == 0
        assert_bar_length_ledger(lot)

    def test_cancelling_returns_the_reserved_length_and_conserves_the_total(self):
        """PRD 3.6: "The reserved bar length is returned from the lot's
        `reserved_length_mm` to its `available_length_mm`, leaving
        `consumed_length_mm` untouched so the length ledger stays conserved, and
        both the machine window and the bar-lot staging interval are released for
        reuse by later candidates."
        PRD 2.7: "The lot's `total_length_mm` is fixed at receipt and is immutable
        thereafter."

        Design: Difficulty/compensating_invariant/bar_length_conserved_across_reserve_and_cancel
        """
        shop = setup_scheduled_work_order()

        cancelled = cancel_work_order(shop.work_order_id, "CUSTOMER_PULL_IN")
        assert cancelled["machining_status"] == "CANCELLED"

        lot = read_bar_lot(shop.lot_id)
        assert lot["available_length_mm"] == 72000
        assert lot["reserved_length_mm"] == 0
        assert lot["consumed_length_mm"] == 0
        assert lot["total_length_mm"] == 72000
        assert lot["status"] == "CERTIFIED"
        assert_bar_length_ledger(lot)


def test_recording_a_certificate_moves_the_lot_to_certified():
    """PRD 3.2: "Recording a `certificate_number` against a lot in `RECEIVED`
    moves it `RECEIVED → CERTIFIED` and stores the number."

    Design: Corner/state_machines/certify_moves_bar_stock_lot_received_to_certified
    """
    set_clock()
    lot = receive_bar_lot()

    certified = validate_success(
        api_client.certify_bar_stock_lot(lot["id"], {"certificate_number": "CERT-1"}, QUALITY),
        200,
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certificate_number"] == "CERT-1"
    assert certified["available_length_mm"] == 72000


def test_second_certificate_on_a_certified_lot_is_rejected():
    """PRD 3.2: "Certification is only declared from `RECEIVED`; attempting it
    against a lot already `CERTIFIED`, `QUARANTINED` or `DEPLETED` is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/second_certify_on_a_certified_lot_is_rejected
    """
    set_clock()
    lot = receive_bar_lot()
    certify_bar_lot(lot["id"], "CERT-1")

    response = api_client.certify_bar_stock_lot(
        lot["id"], {"certificate_number": "CERT-2"}, QUALITY
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    stored = read_bar_lot(lot["id"])
    assert stored["certificate_number"] == "CERT-1"
    assert stored["status"] == "CERTIFIED"


def test_omitted_optional_fields_take_their_declared_defaults():
    """PRD 3.2: "An optional `feeder_slots` value declares how many work orders
    may have intersecting staging intervals on this lot's bar feeder; it defaults
    to 1 and must be at least 1."
    PRD 3.2: "`available_length_mm` is set to the same figure, while
    `reserved_length_mm` and `consumed_length_mm` both start at 0."
    PRD 3.1: "Two values may be omitted: `cpk_min`, the minimum short-term
    capability index a subgroup must reach to be dispositioned as acceptable,
    defaults to 1.33 and must be greater than zero; and `subgroup_size`, the
    number of measurements every subgroup for this characteristic must contain,
    defaults to 5 and must be either 3 or 5."

    Design: Corner/entities/omitting_feeder_slots_defaults_to_one
    """
    set_clock()
    part = register_part()

    lot = validate_success(
        api_client.create_bar_stock_lot(
            {
                "heat_number": "H-70001",
                "alloy_code": "303SS",
                "bar_diameter_mm": 12.7,
                "bar_length_mm": 3600,
                "bars_received": 20,
                "mass_kg_per_meter": 0.995,
            },
            PLANNER,
        ),
        201,
    )
    assert lot["feeder_slots"] == 1
    assert lot["status"] == "RECEIVED"
    assert lot["total_length_mm"] == 72000
    assert lot["available_length_mm"] == 72000

    characteristic = validate_success(
        api_client.create_characteristic(
            {
                "part_id": part["id"],
                "char_code": "OD-A",
                "nominal": 6.35,
                "usl": 6.375,
                "lsl": 6.325,
                "sample_freq_pieces": 200,
                "required_gauge_type": "MICROMETER",
            },
            PLANNER,
        ),
        201,
    )
    assert characteristic["cpk_min"] == 1.33
    assert characteristic["subgroup_size"] == 5


def test_work_order_length_fields_are_derived_from_the_part_and_the_lot():
    """PRD 3.5: "`required_length_mm` is the ordered quantity multiplied by the
    sum of the part's `cut_off_length_mm` and the 2.0-millimetre part-off kerf,
    plus a flat 300 millimetres of setup scrap."
    PRD 3.5: "The work order's own `reserved_length_mm` is `bars_reserved`
    multiplied by the lot's full `bar_length_mm`, because whole bars leave the
    rack including the remnant that will never be cut."

    Design: Corner/entities/work_order_length_fields_are_computed_from_part_and_lot
    """
    shop = setup_scheduled_work_order()

    work_order = read_work_order(shop.work_order_id)
    assert work_order["required_length_mm"] == 6000
    assert work_order["bars_reserved"] == 2
    assert work_order["reserved_length_mm"] == 7200

    lot = read_bar_lot(shop.lot_id)
    assert lot["available_length_mm"] == 64800
    assert lot["reserved_length_mm"] == 7200


def test_partial_bars_are_rounded_up_to_whole_bars():
    """PRD 3.5: "Because a bar cannot be fed to its very end, only the lot's
    `bar_length_mm` less a 150-millimetre remnant is usable from each bar."
    PRD 2.6: "Bar length in millimetres is exact and is never rounded; only the
    count of whole bars drawn from a lot is rounded, and that is always a
    ceiling."

    Design: Corner/calculations/bar_reservation_ceils_partial_bars_to_whole_bars
    """
    shop = setup_scheduled_work_order()

    work_order = read_work_order(shop.work_order_id)
    assert work_order["required_length_mm"] == 6000
    assert work_order["bars_reserved"] == 2, (
        "6000 mm over a usable 3450 mm per bar must round up to two whole bars"
    )
    assert work_order["reserved_length_mm"] == 7200

    lot = read_bar_lot(shop.lot_id)
    assert lot["available_length_mm"] == 64800
    assert lot["consumed_length_mm"] == 0


def test_new_work_order_opens_scheduled_and_pending_inspection():
    """PRD 3.5: "A new work order opens with `machining_status` `SCHEDULED` and
    `quality_status` `PENDING_INSPECTION`, with `machinist_operator_id` null,
    `actual_run_seconds` null, `qty_good` and `qty_scrap` at 0, `chip_kg` at 0 and
    `cancel_reason` null."
    PRD 2.4: "`version`, an integer that begins at 1 on creation and increases by
    exactly one on every mutation of that row."

    Design: Corner/state_machines/new_work_order_starts_scheduled_and_pending_inspection
    """
    shop = setup_shop_floor()
    version = machine_version(shop.machine_id)

    response = api_client.create_work_order(
        {
            "release_id": shop.release_id,
            "machine_id": shop.machine_id,
            "bar_lot_id": shop.lot_id,
            "qty_ordered": 200,
            "scheduled_start_at": "2026-09-02T06:00:00Z",
            "scheduled_end_at": "2026-09-02T14:00:00Z",
            "expected_machine_version": version,
            "lights_out_hours": 4,
        },
        PLANNER,
    )
    work_order = validate_success(response, 201)
    assert work_order["machining_status"] == "SCHEDULED"
    assert work_order["quality_status"] == "PENDING_INSPECTION"
    assert work_order["machinist_operator_id"] is None
    assert work_order["qty_good"] == 0
    assert work_order["actual_run_seconds"] is None
    assert work_order["version"] == 1


def test_work_order_is_reachable_through_each_of_its_foreign_keys():
    """PRD 3.5: "Work orders may be listed with any combination of `release_id`,
    `machine_id`, `bar_lot_id`, `part_id`, `machinist_operator_id` and
    `machining_status` as filters."
    PRD 3.5: "The `part_id` is not supplied; it is copied from the blanket order
    behind the named release."

    Design: Corner/entities/work_order_graph_resolves_all_five_foreign_keys
    """
    shop = setup_scheduled_work_order()

    for params in (
        {"release_id": shop.release_id},
        {"machine_id": shop.machine_id},
        {"bar_lot_id": shop.lot_id},
    ):
        rows, meta = validate_paginated(api_client.list_work_orders(PLANNER, params))
        assert meta["total_count"] == 1, f"filter {params} must match exactly one job"
        assert rows[0]["id"] == shop.work_order_id

    assert read_work_order(shop.work_order_id)["part_id"] == shop.part_id


def test_schedule_is_refused_when_the_lot_cannot_yield_the_whole_bars():
    """PRD 3.5: "If that reserved length exceeds the lot's `available_length_mm`,
    the schedule is rejected with `ERR_BAR_STOCK_INSUFFICIENT` (HTTP 409)."

    Design: Corner/errors/bar_stock_insufficient_when_the_lot_cannot_yield_the_whole_bars
    """
    shop = setup_shop_floor()
    thin_lot = receive_bar_lot(heat_number="H-77003", bars_received=1)
    certify_bar_lot(thin_lot["id"], "CERT-T")
    version = machine_version(shop.machine_id)

    response = api_client.create_work_order(
        {
            "release_id": shop.release_id,
            "machine_id": shop.machine_id,
            "bar_lot_id": thin_lot["id"],
            "qty_ordered": 200,
            "scheduled_start_at": "2026-09-02T06:00:00Z",
            "scheduled_end_at": "2026-09-02T14:00:00Z",
            "expected_machine_version": version,
            "lights_out_hours": 0,
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_BAR_STOCK_INSUFFICIENT.value)

    stored = read_bar_lot(thin_lot["id"])
    assert stored["available_length_mm"] == 3600
    assert stored["reserved_length_mm"] == 0

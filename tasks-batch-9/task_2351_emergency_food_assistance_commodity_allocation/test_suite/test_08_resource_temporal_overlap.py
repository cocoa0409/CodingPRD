"""The three booking geometries: a buffered dock, and the agency freezer that counts touches."""

from test_helpers import (
    AppointmentStatus,
    ApiErrorId,
    FormulaVariant,
    OrderStatus,
    factories as f,
    fixtures as fx,
    make_warehouse_operator_headers,
    validate_error,
    validate_success,
)

PEACH_CODE = "CANNED_PEACHES"
CHICKEN_CODE = "FROZEN_CHICKEN"


def _book(api, warehouse_id, order_id, window_start, window_end, dock_number=1):
    return api.create_delivery_appointment(
        f.delivery_appointment_payload(order_id, dock_number, window_start, window_end),
        headers=make_warehouse_operator_headers(warehouse_id),
    )


def _approved_order(api, cycle_id, agency_id, warehouse_id, commodity_id, cases):
    order = fx.create_order(api, cycle_id, agency_id, warehouse_id)
    fx.add_line(api, order["id"], agency_id, commodity_id, cases)
    fx.submit_order(api, order["id"], agency_id)
    return fx.approve_order(api, order["id"])


def _one_dock_already_booked_until_noon(api):
    """Order A occupies dock 1 of WH North from 10:00 to 12:00; order B wants the same dock."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area One", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency One",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    peaches = fx.create_canned_peaches(api, entitlement_value_cents_per_case=1800)
    warehouse = fx.create_warehouse(api, name="WH North")
    fx.create_posted_lot(
        api,
        peaches["id"],
        warehouse["id"],
        federal_lot_code="FL-P-001",
        cases_received=300,
        pack_date="2026-05-01",
        best_by_date="2028-05-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27DOCK",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[PEACH_CODE],
        order_window_open_at="2026-08-05T00:00:00Z",
        order_window_close_at="2026-08-30T00:00:00Z",
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-08T00:00:00Z")

    order_a = _approved_order(
        api, cycle["id"], agency["id"], warehouse["id"], peaches["id"], 10
    )
    order_b = _approved_order(
        api, cycle["id"], agency["id"], warehouse["id"], peaches["id"], 10
    )
    appointment_a = validate_success(
        _book(
            api,
            warehouse["id"],
            order_a["id"],
            "2026-08-10T10:00:00Z",
            "2026-08-10T12:00:00Z",
        ),
        201,
    )
    return {
        "agency": agency,
        "warehouse": warehouse,
        "order_b": order_b,
        "appointment_a": appointment_a,
    }


def test_01_a_start_one_minute_inside_the_turnaround_buffer_conflicts(api):
    """PRD §3.7: "A conflict exists when the new window starts before an existing
    window's end extended by the half-hour turnaround (30 minutes) *and* that existing
    window starts before the new window's end extended by the same half-hour." PRD
    §3.7: "A new window starting exactly 30 minutes after an existing window's end is
    accepted; starting one minute earlier than that is rejected with
    `ERR_DOCK_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/dock_turnaround_buffer_rejects_29_minute_gap_and_accepts_30
    """
    env = _one_dock_already_booked_until_noon(api)

    response = _book(
        api,
        env["warehouse"]["id"],
        env["order_b"]["id"],
        "2026-08-10T12:29:00Z",
        "2026-08-10T13:00:00Z",
    )

    validate_error(response, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT, 409)


def test_02_the_refused_booking_leaves_the_order_unscheduled(api):
    """PRD §3.7: "The appointment lands in `status` `SCHEDULED` with
    `delivered_pounds` 0.0 and both `confirmed_by_user_id` and `cancel_reason` null,
    and it moves its order `APPROVED → SCHEDULED`, incrementing the order's
    `version`."

    Design: Difficulty/resource_temporal_overlap/dock_turnaround_buffer_rejects_29_minute_gap_and_accepts_30
    """
    env = _one_dock_already_booked_until_noon(api)

    _book(
        api,
        env["warehouse"]["id"],
        env["order_b"]["id"],
        "2026-08-10T12:29:00Z",
        "2026-08-10T13:00:00Z",
    )

    order = fx.read_order(api, env["order_b"]["id"])
    assert order["status"] == OrderStatus.APPROVED, (
        f"order B must stay APPROVED but got {order['status']}"
    )
    _rows, meta = fx.list_rows_and_meta(
        api.list_delivery_appointments(
            headers=fx.ADMIN, params={"order_id": env["order_b"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"order B may hold no appointment but total_count is {meta['total_count']}"
    )


def test_03_a_start_exactly_thirty_minutes_past_the_end_is_accepted(api):
    """PRD §3.7: "The `warehouse_id` and `agency_id` of the appointment are copied
    from the order rather than supplied, and the appointment's three per-class pallet
    loads are summed from the order's lines: `dry_pallets` is the sum of
    `line_pallets` over the order's `DRY` lines, `cold_pallets` the sum over its
    `COLD` lines, and `frozen_pallets` the sum over its `FROZEN` lines."

    Design: Difficulty/resource_temporal_overlap/dock_turnaround_buffer_rejects_29_minute_gap_and_accepts_30
    """
    env = _one_dock_already_booked_until_noon(api)
    _book(
        api,
        env["warehouse"]["id"],
        env["order_b"]["id"],
        "2026-08-10T12:29:00Z",
        "2026-08-10T13:00:00Z",
    )

    appointment = validate_success(
        _book(
            api,
            env["warehouse"]["id"],
            env["order_b"]["id"],
            "2026-08-10T12:30:00Z",
            "2026-08-10T14:00:00Z",
        ),
        201,
    )

    assert appointment["status"] == AppointmentStatus.SCHEDULED, (
        f"status expected SCHEDULED but got {appointment['status']}"
    )
    assert appointment["dock_number"] == 1, (
        f"dock_number expected 1 but got {appointment['dock_number']}"
    )
    assert appointment["dry_pallets"] == 1, (
        f"dry_pallets expected 1 but got {appointment['dry_pallets']}"
    )
    assert appointment["cold_pallets"] == 0, (
        f"cold_pallets expected 0 but got {appointment['cold_pallets']}"
    )
    assert appointment["frozen_pallets"] == 0, (
        f"frozen_pallets expected 0 but got {appointment['frozen_pallets']}"
    )
    assert appointment["warehouse_id"] == env["warehouse"]["id"], (
        f"warehouse_id expected {env['warehouse']['id']} but got {appointment['warehouse_id']}"
    )
    assert appointment["agency_id"] == env["agency"]["id"], (
        f"agency_id expected {env['agency']['id']} but got {appointment['agency_id']}"
    )
    order = fx.read_order(api, env["order_b"]["id"])
    assert order["status"] == OrderStatus.SCHEDULED, (
        f"order B expected SCHEDULED but got {order['status']}"
    )
    earlier = fx.read_appointment(api, env["appointment_a"]["id"])
    assert earlier["status"] == AppointmentStatus.SCHEDULED, (
        f"the first appointment must stay SCHEDULED but got {earlier['status']}"
    )


def _frozen_load_at_two_warehouses(api):
    """One frozen pallet booked at WH A until noon; two more wanted at WH B from noon."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area One", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency One",
        cold_storage_pallet_capacity=2,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    chicken = fx.create_frozen_chicken(api)
    warehouse_a = fx.create_warehouse(api, name="WH A")
    warehouse_b = fx.create_warehouse(api, name="WH B")
    for warehouse, code in ((warehouse_a, "FL-CA-001"), (warehouse_b, "FL-CB-001")):
        fx.create_posted_lot(
            api,
            chicken["id"],
            warehouse["id"],
            federal_lot_code=code,
            cases_received=100,
            pack_date="2026-06-01",
            best_by_date="2027-06-01",
        )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27COLD",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[CHICKEN_CODE],
        order_window_open_at="2026-08-05T00:00:00Z",
        order_window_close_at="2026-08-30T00:00:00Z",
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-08T00:00:00Z")

    order_a = _approved_order(
        api, cycle["id"], agency["id"], warehouse_a["id"], chicken["id"], 23
    )
    order_b = _approved_order(
        api, cycle["id"], agency["id"], warehouse_b["id"], chicken["id"], 50
    )
    appointment_a = validate_success(
        _book(
            api,
            warehouse_a["id"],
            order_a["id"],
            "2026-08-10T10:00:00Z",
            "2026-08-10T12:00:00Z",
        ),
        201,
    )
    return {
        "agency": agency,
        "warehouse_a": warehouse_a,
        "warehouse_b": warehouse_b,
        "order_b": order_b,
        "appointment_a": appointment_a,
    }


def _book_at_noon(api, env):
    return _book(
        api,
        env["warehouse_b"]["id"],
        env["order_b"]["id"],
        "2026-08-10T12:00:00Z",
        "2026-08-10T14:00:00Z",
    )


def test_04_windows_that_merely_touch_still_share_the_agency_freezer(api):
    """PRD §3.7: "The resource here is the receiving agency, not a warehouse, and the
    peers span *every* warehouse: appointments with the same `agency_id` whose
    `status` is `SCHEDULED` or `BLOCKED` and which overlap the new window in the
    closed sense — the peer starts at or before the new window's end *and* the new
    window starts at or before the peer's end — so windows that touch at an endpoint
    *do* interact." PRD §3.7: "The new appointment's `frozen_pallets` plus the sum of
    `frozen_pallets` over those peers must not exceed the agency's
    `cold_storage_pallet_capacity`, otherwise `ERR_AGENCY_COLD_STORAGE_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/agency_frozen_ceiling_counts_touching_windows_across_warehouses
    """
    env = _frozen_load_at_two_warehouses(api)

    response = _book_at_noon(api, env)

    validate_error(response, ApiErrorId.ERR_AGENCY_COLD_STORAGE_EXCEEDED, 409)


def test_05_the_per_warehouse_pool_test_never_fires_on_this_booking(api):
    """PRD §3.7: "The peers are appointments at the same `warehouse_id` whose `status`
    is `SCHEDULED` or `BLOCKED` — a delivered appointment no longer consumes staging —
    and which overlap the new window in the half-open sense: the peer starts strictly
    before the new window ends *and* the new window starts strictly before the peer
    ends, so windows that merely touch at an endpoint do not interact."

    Design: Difficulty/resource_temporal_overlap/agency_frozen_ceiling_counts_touching_windows_across_warehouses
    """
    env = _frozen_load_at_two_warehouses(api)

    _book_at_noon(api, env)

    warehouse_b = fx.read_warehouse(api, env["warehouse_b"]["id"])
    assert warehouse_b["frozen_pallet_capacity"] == 20, (
        "WH B frozen_pallet_capacity expected 20 but got "
        f"{warehouse_b['frozen_pallet_capacity']}"
    )
    _peers, peer_meta = fx.list_rows_and_meta(
        api.list_delivery_appointments(
            headers=fx.ADMIN, params={"warehouse_id": env["warehouse_b"]["id"]}
        )
    )
    assert peer_meta["total_count"] == 0, (
        f"WH B may hold no appointment but total_count is {peer_meta['total_count']}"
    )
    _rows, meta = fx.list_rows_and_meta(
        api.list_delivery_appointments(
            headers=fx.ADMIN, params={"order_id": env["order_b"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"order B may hold no appointment but total_count is {meta['total_count']}"
    )
    order = fx.read_order(api, env["order_b"]["id"])
    assert order["status"] == OrderStatus.APPROVED, (
        f"order B must stay APPROVED but got {order['status']}"
    )


def test_06_raising_the_agency_ceiling_lets_the_touching_window_through(api):
    """PRD §3.7: "This is the aggregate ceiling that stops an agency from accepting
    more frozen product across concurrent appointments than its own freezer can hold."
    PRD §3.7: "The `warehouse_id` and `agency_id` of the appointment are copied from
    the order rather than supplied, and the appointment's three per-class pallet loads
    are summed from the order's lines: `dry_pallets` is the sum of `line_pallets` over
    the order's `DRY` lines, `cold_pallets` the sum over its `COLD` lines, and
    `frozen_pallets` the sum over its `FROZEN` lines."

    Design: Difficulty/resource_temporal_overlap/agency_frozen_ceiling_counts_touching_windows_across_warehouses
    """
    env = _frozen_load_at_two_warehouses(api)
    _book_at_noon(api, env)

    validate_success(
        api.patch_agency(
            env["agency"]["id"], {"cold_storage_pallet_capacity": 3}, headers=fx.ADMIN
        )
    )

    appointment = validate_success(_book_at_noon(api, env), 201)
    assert appointment["status"] == AppointmentStatus.SCHEDULED, (
        f"status expected SCHEDULED but got {appointment['status']}"
    )
    assert appointment["frozen_pallets"] == 2, (
        f"frozen_pallets expected 2 but got {appointment['frozen_pallets']}"
    )
    assert appointment["warehouse_id"] == env["warehouse_b"]["id"], (
        f"warehouse_id expected {env['warehouse_b']['id']} but got {appointment['warehouse_id']}"
    )
    earlier = fx.read_appointment(api, env["appointment_a"]["id"])
    assert earlier["frozen_pallets"] == 1, (
        f"the WH A appointment frozen_pallets expected 1 but got {earlier['frozen_pallets']}"
    )
    order = fx.read_order(api, env["order_b"]["id"])
    assert order["status"] == OrderStatus.SCHEDULED, (
        f"order B expected SCHEDULED but got {order['status']}"
    )

"""Tariff effective windows and the provisional-vs-final landed cost
waterfall."""
from test_helpers import (
    TEST_USERS,
    add_container_line,
    api_client,
    assert_inventory_lot,
    book_container,
    create_module_product,
    create_inverter_product,
    create_tariff,
    create_tariff_rate_payload,
    get_lot,
    receive_container,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]


def _two_line_received_container():
    """Module line 10 x 30000c declared (10% duty) and inverter line
    1 x 700000c declared (5% duty) on one container with freight 100000c and
    insurance 20000c; received complete. Returns (lot_mod, lot_inv)."""
    set_clock("2026-08-01T00:00:00Z")
    create_tariff("8541.43", 1000)
    create_tariff("8504.40", 500)
    module = create_module_product(sku="MOD-X")
    inverter = create_inverter_product(sku="INV-Y")
    container = book_container(freight_cost_cents=100000,
                               insurance_cost_cents=20000,
                               eta_utc="2026-08-10T00:00:00Z")
    line_mod = add_container_line(container["id"], module["id"], 10, 30000)
    line_inv = add_container_line(container["id"], inverter["id"], 1, 700000)
    receive_container(container["id"], [
        {"container_line_id": line_mod["id"], "qty_received": 10,
         "qty_damaged": 0},
        {"container_line_id": line_inv["id"], "qty_received": 1,
         "qty_damaged": 0},
    ])
    return (get_lot(line_mod["inventory_lot_id"]),
            get_lot(line_inv["inventory_lot_id"]))


def test_tariff_window_overlap_rejected(api):
    """PRD section 3.1: "Creation is rejected with `ERR_TARIFF_WINDOW_OVERLAP`
    when another `ACTIVE` rate for the same `hts_code` already covers any part
    of the proposed window." The existing rate covers
    [2026-07-01, 2026-08-15); a new rate starting 2026-08-10 intersects it.

    Design: Difficulty/resource_temporal_overlap/tariff_window_overlap_rejected_half_open
    """
    set_clock("2026-08-01T00:00:00Z")
    create_tariff("8541.43", 1000, effective_from="2026-07-01T00:00:00Z",
                  effective_to="2026-08-15T00:00:00Z")
    resp = api.create_tariff_rate(
        create_tariff_rate_payload(
            hts_code="8541.43", duty_rate_bp=2000,
            effective_from="2026-08-10T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_TARIFF_WINDOW_OVERLAP)


def test_tariff_window_adjacent_half_open_allowed(api):
    """PRD section 3.1: "it selects the rate whose `hts_code` matches the
    product's `hts_code`, whose `effective_from` is at or before the instant,
    and whose window has not yet closed (`effective_to` null, or the instant
    strictly before `effective_to`)". Under these half-open windows the
    existing rate covers no instant at or after 2026-08-15, so a new rate
    starting exactly at the existing rate's `effective_to` shares no covered
    instant and is accepted.

    Design: Difficulty/resource_temporal_overlap/tariff_window_overlap_rejected_half_open
    """
    set_clock("2026-08-01T00:00:00Z")
    create_tariff("8541.43", 1000, effective_from="2026-07-01T00:00:00Z",
                  effective_to="2026-08-15T00:00:00Z")
    resp = api.create_tariff_rate(
        create_tariff_rate_payload(
            hts_code="8541.43", duty_rate_bp=2000,
            effective_from="2026-08-15T00:00:00Z",
        ),
        ADMIN,
    )
    rate = validate_success(resp, 201)
    assert rate["status"] == "ACTIVE"
    assert rate["duty_rate_bp"] == 2000


def _tariff_change_scenario():
    """Booking-time rate 10% [07-01, 08-15); arrival-time rate 20% from
    08-15. Container booked 2026-08-01 with freight 100000c, insurance
    20000c, one module line 10 x 50000c declared."""
    set_clock("2026-08-01T00:00:00Z")
    create_tariff("8541.43", 1000, effective_from="2026-07-01T00:00:00Z",
                  effective_to="2026-08-15T00:00:00Z")
    create_tariff("8541.43", 2000, effective_from="2026-08-15T00:00:00Z")
    module = create_module_product(sku="MOD-400")
    container = book_container(freight_cost_cents=100000,
                               insurance_cost_cents=20000,
                               eta_utc="2026-08-20T00:00:00Z")
    line = add_container_line(container["id"], module["id"], 10, 50000)
    return container, line


def test_provisional_cost_uses_booking_time_tariff(api):
    """PRD section 3.4: "The **provisional** landed cost, computed at booking
    time and refreshed by pre-receipt edits, is stored as
    `unit_cost_cents_provisional`; it uses the tariff rate effective at the
    container's booking time (its `created_at`)". Booked 2026-08-01 under the
    10% rate: base 500000 + duty 50000 + freight 100000 + insurance 20000 =
    670000 over 10 booked units = 67000c per unit.

    Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_final_differ_on_tariff_change
    """
    container, line = _tariff_change_scenario()
    lot = get_lot(line["inventory_lot_id"])
    assert_inventory_lot(lot)
    assert lot["status"] == "IN_TRANSIT"
    assert lot["unit_cost_cents_provisional"] == 67000, (
        f"provisional unit cost must be 67000, "
        f"got {lot['unit_cost_cents_provisional']}"
    )
    assert lot["unit_cost_cents_final"] is None


def test_final_cost_uses_arrival_time_tariff(api):
    """PRD section 3.4: "The **final** landed cost, computed at receipt and
    stored as `unit_cost_cents_final`, uses the tariff rate effective at the
    container's `actual_arrival_utc` (window and tie-breaking per §3.1) and
    divides the landed total by the line's *received* quantity — not the
    booked quantity — rounding half up to a whole cent." Arriving 2026-08-20
    under the 20% rate: base 500000 + duty 100000 + freight 100000 +
    insurance 20000 = 720000 over 10 received units = 72000c per unit, which
    diverges from the 67000c provisional figure.

    Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_final_differ_on_tariff_change
    """
    container, line = _tariff_change_scenario()
    set_clock("2026-08-05T00:00:00Z")
    # depart stamps no arrival time; arrival at 2026-08-20 picks up the 20% rate.
    api_client.depart_container(container["id"], ADMIN)
    set_clock("2026-08-20T00:00:00Z")
    arrived = validate_success(api_client.arrive_container(container["id"], ADMIN), 200)
    received = validate_success(
        api_client.receive_container(container["id"], {
            "expected_container_version": arrived["version"],
            "line_receipts": [{"container_line_id": line["id"],
                               "qty_received": 10, "qty_damaged": 0}],
        }, ADMIN),
        200,
    )
    assert received["status"] == "RECEIVED"

    lot = get_lot(line["inventory_lot_id"])
    assert lot["unit_cost_cents_final"] == 72000, (
        f"final unit cost must be 72000, got {lot['unit_cost_cents_final']}"
    )
    assert lot["unit_cost_cents_provisional"] == 67000
    assert lot["unit_cost_cents_final"] != lot["unit_cost_cents_provisional"]
    assert lot["status"] == "ON_HAND"
    assert lot["received_at"] is not None


def test_landed_cost_waterfall_module_line(api):
    """PRD section 3.4: "For each line, the base cost is the booked quantity
    multiplied by the declared per-unit customs value. The duty is the base
    cost multiplied by the applicable `duty_rate_bp` and divided by ten
    thousand, rounded half up to a whole cent. The freight share is the
    container's total `freight_cost_cents` multiplied by the proportion that
    this line's base cost bears to the total declared value across all of the
    container's lines, rounded half up; the insurance share is the same
    construction over `insurance_cost_cents`, also rounded half up."
    Module line: base 300000, duty 30000, freight share 30000, insurance
    share 6000; landed 366000 over 10 received units = 36600c.

    Design: Difficulty/combinatorial_formula/landed_cost_nested_min_max_per_line_then_sum
    """
    lot_mod, _ = _two_line_received_container()
    assert lot_mod["unit_cost_cents_final"] == 36600, (
        f"module line final unit cost must be 36600, "
        f"got {lot_mod['unit_cost_cents_final']}"
    )


def test_landed_cost_waterfall_inverter_line(api):
    """PRD section 3.4: "The landed total is the sum of the base cost, the
    duty, the freight share, and the insurance share." Inverter line: base
    700000, duty 35000 (5%), freight share 70000, insurance share 14000;
    landed 819000 over 1 received unit = 819000c. Total declared value across
    the container is 300000 + 700000 = 1000000, so the shares are 30/70.

    Design: Difficulty/combinatorial_formula/landed_cost_nested_min_max_per_line_then_sum
    """
    _, lot_inv = _two_line_received_container()
    assert lot_inv["unit_cost_cents_final"] == 819000, (
        f"inverter line final unit cost must be 819000, "
        f"got {lot_inv['unit_cost_cents_final']}"
    )

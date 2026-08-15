"""Milling yield dual variant, packaging lines and consumption, byproduct
orders, and the season inventory ledger (PRD §2.10, §3.6)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    assert_cwt,
    assert_inventory_row,
    ApiErrorId,
    TEST_USERS,
    create_open_season,
    create_grower,
    create_bin,
    get_bin,
    create_spot_lot,
    grade_lot,
    store_lot,
    create_drying_run,
    cancel_drying_run,
    create_mill_run,
    get_mill_run,
    start_mill_run,
    create_packaging_run,
    create_byproduct_order,
    create_binned_spot_lot,
    get_inventory,
    setup_completed_mill_run,
    create_packaging_run_payload,
    create_byproduct_order_payload,
)

MERCH = TEST_USERS["merchandiser_headers"]
SCALE = TEST_USERS["scale_operator_headers"]
LAB = TEST_USERS["quality_lab_tech_headers"]
DRYER = TEST_USERS["dryer_operator_headers"]
SUPERVISOR = TEST_USERS["mill_supervisor_headers"]


# ---------------------------------------------------------------------------
# Dual variant: estimated (standard-yield) vs actual (measured) mill outputs
# ---------------------------------------------------------------------------

def test_mill_run_complete_credits_standard_estimates(api):
    """PRD §3.6: "Total rice is the input multiplied by 0.68 for `LONG_GRAIN` or
    0.72 for `MEDIUM_GRAIN`, rounded half-up to 2 decimal places. From that
    total, estimated head rice `est_head_cwt` is total rice multiplied by 0.60
    for long grain or 0.66 for medium grain, and estimated brewers
    `est_brewers_cwt` is total rice multiplied by 0.05 — both rounded half-up to
    2 decimals — while estimated broken `est_broken_cwt` is whatever of the
    total rice remains after head and brewers, an unrounded plug. Estimated bran
    `est_bran_cwt` is the input multiplied by 0.08 and estimated loss
    `est_loss_cwt` the input multiplied by 0.02, each rounded half-up to 2
    decimals; estimated hull `est_hull_cwt` is the global plug — whatever of the
    input remains after total rice, bran, and loss."

    Design: Difficulty/dual_variant_calc/mill_yield_estimated_vs_actual
    """
    scn = setup_completed_mill_run(input_cwt=200.00, variety="LONG_GRAIN")
    run = scn["mill_run"]
    assert run["status"] == "COMPLETED"
    assert_cwt(run["est_head_cwt"], 81.60, "est_head_cwt")
    assert_cwt(run["est_brewers_cwt"], 6.80, "est_brewers_cwt")
    assert_cwt(run["est_broken_cwt"], 47.60, "est_broken_cwt (plug within rice)")
    assert_cwt(run["est_bran_cwt"], 16.00, "est_bran_cwt")
    assert_cwt(run["est_loss_cwt"], 4.00, "est_loss_cwt")
    assert_cwt(run["est_hull_cwt"], 44.00, "est_hull_cwt (global plug)")
    total = (float(run["est_head_cwt"]) + float(run["est_broken_cwt"])
             + float(run["est_brewers_cwt"]) + float(run["est_bran_cwt"])
             + float(run["est_hull_cwt"]) + float(run["est_loss_cwt"]))
    assert total == pytest.approx(200.00, abs=1e-6), "estimates must conserve the input"


def test_mill_run_verify_replaces_estimates_with_actuals(api, mill_supervisor_headers):
    """PRD §3.6: "Verifying a `COMPLETED` run takes the measured
    `act_head_cwt`, `act_broken_cwt`, `act_brewers_cwt`, `act_bran_cwt`, and
    `act_hull_cwt`; the system derives `act_loss_cwt` as the input minus those
    five actuals, another unrounded plug. Every product's inventory is then
    adjusted by the signed difference between actual and estimate"
    PRD §2.10: "**produced** is the sum of estimated outputs from mill runs in
    `COMPLETED` status plus the sum of actual measured outputs from runs in
    `VERIFIED` status (a verified run's actuals replace its estimates, which no
    longer count)"

    Design: Difficulty/dual_variant_calc/mill_yield_estimated_vs_actual
    """
    scn = setup_completed_mill_run(input_cwt=200.00, variety="LONG_GRAIN")
    run = scn["mill_run"]
    verified = validate_success(
        api.verify_mill_run(
            run["id"],
            {"act_head_cwt": 80.00, "act_broken_cwt": 48.00, "act_brewers_cwt": 7.00,
             "act_bran_cwt": 16.50, "act_hull_cwt": 44.50},
            mill_supervisor_headers,
        )
    )
    assert verified["status"] == "VERIFIED"
    assert_cwt(verified["act_loss_cwt"], 4.00, "act_loss_cwt plug (200.00 - 196.00)")

    inventory = get_inventory(scn["season"]["id"])
    # Actuals replace estimates: HEAD_RICE produced 80.00 (delta -1.60),
    # BRAN produced 16.50 (delta +0.50).
    assert_inventory_row(inventory["HEAD_RICE"], produced=80.00, available=80.00)
    assert_inventory_row(inventory["BRAN"], produced=16.50, available=16.50)


# ---------------------------------------------------------------------------
# Temporal overlap: packaging line changeover buffer
# ---------------------------------------------------------------------------

def _season_with_line1_run():
    season = create_open_season()
    create_packaging_run(season["id"], line_id="LINE_1", brand_label="MillHouse",
                         package_size_kg=25, units_planned=100,
                         starts_at="2026-08-20T08:00:00Z",
                         ends_at="2026-08-20T10:00:00Z")
    return season


def test_packaging_changeover_buffer_29_minutes_rejected_30_allowed(api, mill_supervisor_headers):
    """PRD §3.6: "The line is a serialized resource with a thirty-minute
    changeover buffer applied at both ends: a new run conflicts with any other
    `SCHEDULED` run on the same line in the same season when the new start falls
    before the existing run's end plus thirty minutes and the existing run's
    start falls before the new end plus thirty minutes — so a gap of exactly
    thirty minutes between windows is allowed, and `COMPLETED` or `CANCELLED`
    runs never conflict. A conflicting schedule is rejected with
    `ERR_LINE_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/packaging_line_changeover_buffer
    """
    season = _season_with_line1_run()
    # 10:29 start: 29 minutes after the predecessor's end -> inside the buffer.
    resp = api.create_packaging_run(
        create_packaging_run_payload(
            season["id"], line_id="LINE_1", brand_label="StoreBrand",
            package_size_kg=10, units_planned=50,
            starts_at="2026-08-20T10:29:00Z", ends_at="2026-08-20T11:30:00Z"),
        mill_supervisor_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LINE_SCHEDULE_CONFLICT)

    # 10:30 start: exactly one changeover buffer after the end -> allowed.
    ok = validate_success(
        api.create_packaging_run(
            create_packaging_run_payload(
                season["id"], line_id="LINE_1", brand_label="StoreBrand",
                package_size_kg=10, units_planned=50,
                starts_at="2026-08-20T10:30:00Z", ends_at="2026-08-20T11:30:00Z"),
            mill_supervisor_headers,
        ),
        expected_status=201,
    )
    assert ok["status"] == "SCHEDULED"


def test_packaging_overlap_on_other_line_allowed(api, mill_supervisor_headers):
    """PRD §3.6: "a new run conflicts with any other `SCHEDULED` run on the same
    line in the same season"

    Design: Difficulty/resource_temporal_overlap/packaging_line_changeover_buffer
    """
    season = _season_with_line1_run()
    # Full time overlap with the LINE_1 run, but on LINE_2: never a conflict.
    other = validate_success(
        api.create_packaging_run(
            create_packaging_run_payload(
                season["id"], line_id="LINE_2", brand_label="ChefLabel",
                package_size_kg=5, units_planned=40,
                starts_at="2026-08-20T09:00:00Z", ends_at="2026-08-20T10:00:00Z"),
            mill_supervisor_headers,
        ),
        expected_status=201,
    )
    assert other["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Non-linear machine: byproduct reserve -> release cycle
# ---------------------------------------------------------------------------

def test_byproduct_exact_fit_reservation_allowed(api, merchandiser_headers):
    """PRD §3.6: "Reserving an `OPEN` order requires the product's available
    inventory to cover the quantity (`ERR_INSUFFICIENT_BYPRODUCT_INVENTORY`) and
    moves it to `RESERVED`, adding the quantity to the product's reserved
    tally."
    PRD §2.10: "A product's **available** quantity is produced minus consumed
    minus reserved minus shipped."

    Design: Difficulty/non_linear_state_machine/byproduct_reserve_release_cycle
    """
    scn = setup_completed_mill_run(input_cwt=200.00)  # est bran 16.00
    order = create_byproduct_order(scn["season"]["id"], product="BRAN",
                                   quantity_cwt=16.00)
    reserved = validate_success(api.reserve_byproduct_order(order["id"], merchandiser_headers))
    assert reserved["status"] == "RESERVED", "16.00 <= 16.00 available: exact fit allowed"

    bran = get_inventory(scn["season"]["id"])["BRAN"]
    assert_inventory_row(bran, produced=16.00, reserved=16.00, available=0.00)


def test_byproduct_release_returns_order_to_open(api, merchandiser_headers):
    """PRD §3.6: "A reserved order may be released back to `OPEN`, unwinding the
    reservation"

    Design: Difficulty/non_linear_state_machine/byproduct_reserve_release_cycle
    """
    scn = setup_completed_mill_run(input_cwt=200.00)
    order = create_byproduct_order(scn["season"]["id"], product="BRAN",
                                   quantity_cwt=16.00)
    validate_success(api.reserve_byproduct_order(order["id"], merchandiser_headers))

    released = validate_success(api.release_byproduct_order(order["id"], merchandiser_headers))
    assert released["status"] == "OPEN"

    bran = get_inventory(scn["season"]["id"])["BRAN"]
    assert_inventory_row(bran, produced=16.00, reserved=0.00, available=16.00)


# ---------------------------------------------------------------------------
# Corner: medium-grain standards and the computed inventory read
# ---------------------------------------------------------------------------

def test_milling_medium_grain_standards(api, mill_supervisor_headers):
    """PRD §3.6: "Total rice is the input multiplied by 0.68 for `LONG_GRAIN` or
    0.72 for `MEDIUM_GRAIN`, rounded half-up to 2 decimal places. From that
    total, estimated head rice `est_head_cwt` is total rice multiplied by 0.60
    for long grain or 0.66 for medium grain"
    PRD §3.6: "the run copies its `variety` from the bin's current
    `variety_lock` and stands `SCHEDULED`."

    Design: Corner/calculations/milling_medium_grain_standards
    """
    season = create_open_season()
    grower = create_grower(season["id"])
    bin_ = create_bin(season["id"], capacity_cwt=500.00)
    create_binned_spot_lot(season["id"], grower["id"], bin_["id"],
                           gross_weight_lbs=27000, tare_weight_lbs=12000,
                           variety="MEDIUM_GRAIN", spot_price_cents_per_cwt=1350)

    run = create_mill_run(season["id"], bin_["id"], 150.00)
    assert run["variety"] == "MEDIUM_GRAIN", "variety copied from the bin lock"
    start_mill_run(run["id"])
    completed = validate_success(api.complete_mill_run(run["id"], mill_supervisor_headers))

    # total rice 150.00 * 0.72 = 108.00; head 108 * 0.66; brewers 108 * 0.05.
    assert_cwt(completed["est_head_cwt"], 71.28, "est_head_cwt")
    assert_cwt(completed["est_brewers_cwt"], 5.40, "est_brewers_cwt")
    assert_cwt(completed["est_broken_cwt"], 31.32, "est_broken_cwt (plug)")
    assert_cwt(completed["est_bran_cwt"], 12.00, "est_bran_cwt")
    assert_cwt(completed["est_loss_cwt"], 3.00, "est_loss_cwt")
    assert_cwt(completed["est_hull_cwt"], 27.00, "est_hull_cwt (global plug)")
    total = (float(completed["est_head_cwt"]) + float(completed["est_broken_cwt"])
             + float(completed["est_brewers_cwt"]) + float(completed["est_bran_cwt"])
             + float(completed["est_hull_cwt"]) + float(completed["est_loss_cwt"]))
    assert total == pytest.approx(150.00, abs=1e-6)


def test_inventory_computed_read(api, mill_supervisor_headers):
    """PRD §2.10: "**produced** is the sum of estimated outputs from mill runs
    in `COMPLETED` status plus the sum of actual measured outputs from runs in
    `VERIFIED` status (a verified run's actuals replace its estimates, which no
    longer count); **consumed** applies only to `HEAD_RICE` and accumulates the
    head rice drawn by completed packaging runs; **reserved** accumulates the
    quantities of byproduct sale orders in `RESERVED` status; **shipped**
    accumulates the quantities of orders in `SHIPPED` status. A product's
    **available** quantity is produced minus consumed minus reserved minus
    shipped. A read-only inventory capability on the season reports all five
    products with these components."

    Design: Corner/endpoints/inventory_computed_read
    """
    scn = setup_completed_mill_run(input_cwt=200.00, variety="LONG_GRAIN")
    inventory = validate_success(
        api.get_byproduct_inventory(scn["season"]["id"], mill_supervisor_headers)
    )
    for product in ("HEAD_RICE", "BROKEN", "BREWERS", "BRAN", "HULL"):
        assert product in inventory, f"inventory must report {product}"

    assert_inventory_row(inventory["HEAD_RICE"], produced=81.60, consumed=0.00,
                         reserved=0.00, shipped=0.00, available=81.60)
    assert_inventory_row(inventory["BROKEN"], produced=47.60, reserved=0.00,
                         shipped=0.00, available=47.60)
    assert_inventory_row(inventory["BREWERS"], produced=6.80, reserved=0.00,
                         shipped=0.00, available=6.80)
    assert_inventory_row(inventory["BRAN"], produced=16.00, reserved=0.00,
                         shipped=0.00, available=16.00)
    assert_inventory_row(inventory["HULL"], produced=44.00, reserved=0.00,
                         shipped=0.00, available=44.00)


# ---------------------------------------------------------------------------
# Corner: capacity / inventory violation guards
# ---------------------------------------------------------------------------

def test_mill_input_exceeds_bin_stock_rejected(api, mill_supervisor_headers):
    """PRD §3.6: "sufficient physical stock — `input_cwt` must not exceed the
    bin's `stock_cwt` (`ERR_MILL_INPUT_EXCEEDS_BIN_STOCK`). The draw debits
    `stock_cwt` by the input amount at start"

    Design: Corner/validations/mill_input_exceeds_bin_stock_rejected
    """
    season = create_open_season()
    grower = create_grower(season["id"])
    bin_ = create_bin(season["id"], capacity_cwt=500.00)
    create_binned_spot_lot(season["id"], grower["id"], bin_["id"],
                           gross_weight_lbs=22000, tare_weight_lbs=12000)
    run = create_mill_run(season["id"], bin_["id"], 150.00)

    resp = api.start_mill_run(run["id"], mill_supervisor_headers)
    validate_error(resp, ApiErrorId.ERR_MILL_INPUT_EXCEEDS_BIN_STOCK)

    assert_cwt(get_bin(bin_["id"])["stock_cwt"], 100.00,
               "a failed start debits nothing")


def test_packaging_consumption_and_insufficiency(api, mill_supervisor_headers):
    """PRD §3.6: "Completing a scheduled run — from any other state,
    `ERR_PACKAGING_RUN_INVALID_STATE` — takes the `units_produced` count and
    converts it to consumed head rice: packages produced multiplied by kilograms
    per package, converted to pounds at 2.20462262 pounds per kilogram, divided
    by one hundred into hundredweight, and rounded half-up to 2 decimals as
    `head_rice_consumed_cwt`. The head-rice inventory must hold at least that
    much available, or completion fails with `ERR_INSUFFICIENT_MILLED_RICE`"

    Design: Corner/calculations/packaging_consumption_and_insufficiency
    """
    scn = setup_completed_mill_run(input_cwt=200.00)  # head rice 81.60
    season_id = scn["season"]["id"]
    run1 = create_packaging_run(season_id, line_id="LINE_1", brand_label="MillHouse",
                                package_size_kg=25, units_planned=100,
                                starts_at="2026-08-20T08:00:00Z",
                                ends_at="2026-08-20T09:00:00Z")
    run2 = create_packaging_run(season_id, line_id="LINE_1", brand_label="StoreBrand",
                                package_size_kg=25, units_planned=60,
                                starts_at="2026-08-20T10:00:00Z",
                                ends_at="2026-08-20T11:00:00Z")

    completed = validate_success(
        api.complete_packaging_run(run1["id"], {"units_produced": 100},
                                   mill_supervisor_headers)
    )
    # 100 * 25 kg * 2.20462262 / 100 = 55.1156 -> 55.12.
    assert_cwt(completed["head_rice_consumed_cwt"], 55.12, "head_rice_consumed_cwt")

    head = get_inventory(season_id)["HEAD_RICE"]
    assert_inventory_row(head, produced=81.60, consumed=55.12, available=26.48)

    # Second run needs 60 * 25 * 2.20462262 / 100 = 33.07 > 26.48 remaining.
    resp = api.complete_packaging_run(run2["id"], {"units_produced": 60},
                                      mill_supervisor_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MILLED_RICE)


def test_byproduct_reserve_over_available_rejected(api, merchandiser_headers):
    """PRD §3.6: "Reserving an `OPEN` order requires the product's available
    inventory to cover the quantity (`ERR_INSUFFICIENT_BYPRODUCT_INVENTORY`)"
    PRD §2.10: "reserving more than the available quantity is refused"

    Design: Corner/validations/byproduct_reserve_over_available_rejected
    """
    scn = setup_completed_mill_run(input_cwt=200.00)  # bran available 16.00
    season_id = scn["season"]["id"]
    big = create_byproduct_order(season_id, product="BRAN", quantity_cwt=16.01)
    fit = create_byproduct_order(season_id, product="BRAN", quantity_cwt=16.00)

    resp = api.reserve_byproduct_order(big["id"], merchandiser_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BYPRODUCT_INVENTORY)

    reserved = validate_success(api.reserve_byproduct_order(fit["id"], merchandiser_headers))
    assert reserved["status"] == "RESERVED"


def test_byproduct_reserve_then_ship_moves_ledgers(api, merchandiser_headers):
    """PRD §3.6: "Reserving an `OPEN` order requires the product's available
    inventory to cover the quantity (`ERR_INSUFFICIENT_BYPRODUCT_INVENTORY`) and
    moves it to `RESERVED`, adding the quantity to the product's reserved tally.
    A reserved order may be released back to `OPEN`, unwinding the reservation,
    or shipped, moving `RESERVED` → `SHIPPED` as the quantity leaves the
    reserved tally and lands in the shipped tally."

    Design: Corner/endpoints/byproduct_reserve_ship_flow
    """
    scn = setup_completed_mill_run(input_cwt=200.00)  # bran 16.00
    season_id = scn["season"]["id"]
    order = create_byproduct_order(season_id, product="BRAN", quantity_cwt=16.00)

    validate_success(api.reserve_byproduct_order(order["id"], merchandiser_headers))
    bran_mid = get_inventory(season_id)["BRAN"]
    assert_inventory_row(bran_mid, reserved=16.00, available=0.00)

    shipped = validate_success(api.ship_byproduct_order(order["id"], merchandiser_headers))
    assert shipped["status"] == "SHIPPED"
    bran_end = get_inventory(season_id)["BRAN"]
    assert_inventory_row(bran_end, shipped=16.00, reserved=0.00, available=0.00)


def test_void_after_ship_negative_inventory_rejected(api, mill_supervisor_headers):
    """PRD §3.6: "Voiding is the emergency brake on a `COMPLETED` run: it
    removes the run's estimated outputs from inventory under the same
    non-negativity guard, moves the run to `VOIDED`, and pointedly does not
    restore the drawn paddy to the input bin."
    PRD §2.10: "any mill-run verification or voiding whose adjustments would
    drive any product's available quantity below zero is refused outright."

    Design: Corner/validations/void_after_ship_negative_inventory_rejected
    """
    scn = setup_completed_mill_run(input_cwt=200.00)  # est bran 16.00
    season_id = scn["season"]["id"]
    order = create_byproduct_order(season_id, product="BRAN", quantity_cwt=16.00)
    validate_success(api.reserve_byproduct_order(order["id"], MERCH))
    validate_success(api.ship_byproduct_order(order["id"], MERCH))

    # Voiding would make available BRAN -16.00 after the shipment.
    resp = api.void_mill_run(scn["mill_run"]["id"], mill_supervisor_headers)
    validate_error(resp, ApiErrorId.ERR_INVENTORY_ADJUSTMENT_NEGATIVE)
    assert get_mill_run(scn["mill_run"]["id"])["status"] == "COMPLETED"


def test_run_and_order_invalid_transitions(api, dryer_operator_headers,
                                           mill_supervisor_headers,
                                           merchandiser_headers):
    """PRD §3.5: "Completing a run is the operator's report of reality: the run
    must stand `PLANNED` (`ERR_DRYING_RUN_NOT_PLANNED`)"
    PRD §3.6: "Completing an `IN_PROCESS` run (again `ERR_MILL_RUN_INVALID_STATE`
    from any other state)"
    PRD §3.6: "Cancellation is allowed from `OPEN` or `RESERVED` — any other
    state draws `ERR_ORDER_INVALID_STATE`"
    PRD §3.6: "Completing a scheduled run — from any other state,
    `ERR_PACKAGING_RUN_INVALID_STATE`"

    Design: Corner/state_machines/run_and_order_invalid_transitions
    """
    season = create_open_season()
    grower = create_grower(season["id"])
    bin_ = create_bin(season["id"], bin_code="B-01", capacity_cwt=800.00)
    create_binned_spot_lot(season["id"], grower["id"], bin_["id"],
                           gross_weight_lbs=42000, tare_weight_lbs=12000)
    lot2 = create_spot_lot(season["id"], grower["id"], gross_weight_lbs=42000,
                           tare_weight_lbs=12000, scheduled_date="2026-08-11",
                           moisture_pct_handheld=16.0)
    grade_lot(lot2["id"], moisture_pct_official=16.0, foreign_matter_pct=0.4,
              damage_pct=0.4, broken_pct=2.0)
    run = create_drying_run(season["id"], [lot2["id"]], bin_["id"])
    cancel_drying_run(run["id"])
    mill_run = create_mill_run(season["id"], bin_["id"], 100.00)  # never started
    order = create_byproduct_order(season["id"], product="BRAN", quantity_cwt=5.00)
    pack = create_packaging_run(season["id"], line_id="LINE_1",
                                package_size_kg=10, units_planned=10,
                                starts_at="2026-08-20T08:00:00Z",
                                ends_at="2026-08-20T09:00:00Z")

    # complete on a CANCELLED drying run.
    resp = api.complete_drying_run(run["id"], {"actual_output_cwt": 288.16},
                                   dryer_operator_headers)
    validate_error(resp, ApiErrorId.ERR_DRYING_RUN_NOT_PLANNED)

    # complete on a SCHEDULED (never started) mill run.
    resp = api.complete_mill_run(mill_run["id"], mill_supervisor_headers)
    validate_error(resp, ApiErrorId.ERR_MILL_RUN_INVALID_STATE)

    # ship on an OPEN byproduct order.
    resp = api.ship_byproduct_order(order["id"], merchandiser_headers)
    validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

    # complete a SCHEDULED packaging run with no head-rice inventory.
    resp = api.complete_packaging_run(pack["id"], {"units_produced": 10},
                                      mill_supervisor_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MILLED_RICE)

    # cancel succeeds once, then the terminal state rejects a second cancel.
    cancelled = validate_success(api.cancel_packaging_run(pack["id"],
                                                          mill_supervisor_headers))
    assert cancelled["status"] == "CANCELLED"
    resp = api.cancel_packaging_run(pack["id"], mill_supervisor_headers)
    validate_error(resp, ApiErrorId.ERR_PACKAGING_RUN_INVALID_STATE)

"""Rungs of the rejection ladder, and the satisfaction half of each rule.

A request that breaks several rules at once must report the highest rung, and
every refusal must leave the plant exactly as it found it. Each test here walks
one rung: first the refusal, then the corrected call that clears it.
"""

import pytest

from test_helpers import (
    BILLING,
    CLERK,
    ENGINEER,
    NO_AUTH_HEADERS,
    QE_DISPOSITIONER,
    QE_RELEASER,
    QE_TESTER,
    SENTINEL_UUID,
    TEST_USERS,
    THHN_12_CU_MARKING,
    advance_lot_to_extruded,
    advance_lot_to_stranded,
    advance_lot_to_tested,
    create_customer,
    create_customer_order_payload,
    create_lot,
    create_reel,
    create_rod_lot,
    current_order_version,
    current_rod_lot_version,
    get_success_data,
    read_customer,
    read_lot,
    read_order,
    read_reel,
    read_rod_lot,
    release_lot,
    setup_baseline,
    setup_definitions_and_rod,
    setup_lv_catalog,
    setup_mv_catalog,
    setup_released_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

WRONG_MARKING_TEXT = "UL E12345 12AWG THHN 90C 600 V"


def test_missing_headers_and_malformed_bodies_answer_before_anything_is_looked_up(api):
    """The same unknown identifier produces three different answers depending on who
    asks and how, because authentication and shape sit above existence.

    PRD 2.11: "Header presence — `ERR_UNAUTHENTICATED`."

    PRD 2.11: "Request shape: required fields present, types correct, enum members
    recognised, numeric bounds from the field definitions respected, a scheduled
    line window whose end is strictly later than its start, a non-empty requested
    cut list on a cut-to-length order, partial-discharge level present on a
    partial-discharge test, applied test voltage present on a high-potential test,
    and pagination bounds respected — `ERR_INVALID_REQUEST`."

    Design: Corner/validations/auth_and_shape_checks_are_evaluated_before_existence_checks
    """
    world = setup_definitions_and_rod(api)
    rod_version = current_rod_lot_version(api, world["rod_lot"]["id"])

    validate_error(
        api.get_production_lot(SENTINEL_UUID, NO_AUTH_HEADERS),
        "ERR_UNAUTHENTICATED", 401,
    )
    validate_error(
        api.get_production_lot(SENTINEL_UUID, TEST_USERS["customer_headers"]),
        "ERR_UNAUTHORIZED", 403,
    )
    validate_error(
        api.create_production_lot(
            {"product_id": SENTINEL_UUID, "rod_lot_id": world["rod_lot"]["id"],
             "lot_code": "LOT-BAD", "planned_length_ft": -5, "line_code": "EXT-1",
             "scheduled_start_at": "2026-08-02T08:00:00Z",
             "scheduled_end_at": "2026-08-02T12:00:00Z",
             "expected_rod_lot_version": rod_version},
            ENGINEER,
        ),
        "ERR_INVALID_REQUEST", 400,
    )
    validate_error(
        api.get_production_lot(SENTINEL_UUID, ENGINEER), "ERR_LOT_NOT_FOUND", 404
    )

    rod = read_rod_lot(api, world["rod_lot"]["id"])
    assert rod["version"] == rod_version, "the rejected schedule allocated nothing"
    assert rod["committed_lbs"] == pytest.approx(0.00, abs=0.01)


def test_a_stale_expected_version_is_reported_ahead_of_state_and_scheduling(api):
    """Optimistic concurrency sits above both the state check and the line-occupancy
    check, so a request that is stale as well as illegal reports the staleness.

    PRD 2.6: "If the supplied value does not equal that rod lot's current
    `version`, the request is rejected with `ERR_STALE_ROD_LOT_VERSION` (HTTP 412)
    and nothing is created."

    PRD 2.11: "Optimistic concurrency — `ERR_STALE_ROD_LOT_VERSION` or
    `ERR_STALE_ORDER_VERSION`, both HTTP 412."

    Design: Corner/validations/stale_expected_versions_are_reported_before_state_and_scheduling
    """
    world = setup_baseline(api)
    stale_rod_version = current_rod_lot_version(api, world["rod_lot"]["id"])
    lot_a = create_lot(api, world, lot_code="LOT-A", planned_length_ft=5000)

    validate_error(
        api.create_production_lot(
            {"product_id": world["product"]["id"], "rod_lot_id": world["rod_lot"]["id"],
             "lot_code": "LOT-B", "planned_length_ft": 1000, "line_code": "EXT-1",
             "scheduled_start_at": "2026-08-02T09:00:00Z",
             "scheduled_end_at": "2026-08-02T10:00:00Z",
             "expected_rod_lot_version": stale_rod_version},
            ENGINEER,
        ),
        "ERR_STALE_ROD_LOT_VERSION", 412,
    )
    rows, meta = validate_paginated(api.list_production_lots(ENGINEER))
    assert meta["total_count"] == 1, "the stale schedule created no second lot"
    assert read_rod_lot(api, world["rod_lot"]["id"])["committed_lbs"] == pytest.approx(
        99.00, abs=0.01
    ), "only LOT-A holds committed mass, and the overlap never got a chance to speak"

    advance_lot_to_tested(api, lot_a["id"])
    release_lot(api, lot_a["id"], 5000)
    reel = create_reel(api)
    get_success_data(
        api.load_reel(
            reel["id"],
            {"lot_id": lot_a["id"], "load_length_ft": 5000,
             "occupancy_start_at": "2026-08-03T00:00:00Z"},
            CLERK,
        )
    )
    stale_order_version = current_order_version(api, world["order"]["id"])
    get_success_data(api.cancel_customer_order(world["order"]["id"], BILLING))

    validate_error(
        api.create_shipment(
            {"order_id": world["order"]["id"], "lot_id": lot_a["id"],
             "reel_id": reel["id"], "shipped_length_ft": 5000,
             "ship_date": "2026-08-01", "cuts_count": 0,
             "expected_order_version": stale_order_version},
            CLERK,
        ),
        "ERR_STALE_ORDER_VERSION", 412,
    )
    assert read_reel(api, reel["id"])["status"] == "LOADED", (
        "the stale staging never moved the reel out of the plant"
    )
    assert read_customer(api, world["customer"]["id"])[
        "reel_deposit_balance_usd"
    ] == pytest.approx(0.00, abs=0.01), "no deposit was charged"


def test_an_unknown_reference_answers_before_state_or_any_business_rule(api):
    """Existence is settled path-first and then body-first in the declared key order,
    so the earliest unresolvable reference is the one reported.

    PRD 2.10: "Once path segments resolve, references carried in the request body
    are resolved in a fixed order: `rod_lot_id`, then `product_id`, then
    `order_id`, then `lot_id`, then `reel_id`, then `shipment_id`, then
    `customer_id`, then `insulation_compound_id`, then `jacket_compound_id`, then
    `listing_certification_id`."

    Design: Corner/validations/unknown_foreign_keys_are_reported_before_state_and_business_rules
    """
    world = setup_baseline(api)
    order = get_success_data(api.cancel_customer_order(world["order"]["id"], BILLING))
    assert order["fulfillment_status"] == "CANCELLED"

    validate_error(
        api.create_shipment(
            {"order_id": world["order"]["id"], "lot_id": SENTINEL_UUID,
             "reel_id": SENTINEL_UUID, "shipped_length_ft": 5000,
             "ship_date": "2026-08-01", "cuts_count": 0,
             "expected_order_version": order["version"]},
            CLERK,
        ),
        "ERR_LOT_NOT_FOUND", 404,
    )
    validate_error(
        api.load_reel(
            SENTINEL_UUID,
            {"lot_id": SENTINEL_UUID, "load_length_ft": 5000,
             "occupancy_start_at": "2026-08-01T00:00:00Z"},
            CLERK,
        ),
        "ERR_REEL_NOT_FOUND", 404,
    )
    final = read_order(api, world["order"]["id"])
    assert final["fulfillment_status"] == "CANCELLED"
    assert final["version"] == order["version"], "both refusals wrote nothing"


def test_the_extrusion_print_must_equal_the_skus_required_marking_exactly(api):
    """Traceability marking is compared character for character, so a single stray
    space is a violation — and the check runs before the measurements matter.

    PRD 3.6: "When the SKU's `marking_required` is true, the supplied
    `surface_marking_text` must equal the SKU's `required_marking_text` exactly,
    character for character and case for case; anything else is refused with
    `ERR_MARKING_MISMATCH`."

    Design: Corner/validations/extrusion_marking_text_must_match_the_products_required_marking
    """
    world = setup_definitions_and_rod(api)
    lot = create_lot(api, world, lot_code="LOT-MARK", planned_length_ft=5000)
    get_success_data(api.create_process_step(lot["id"], {"step": "DRAWING"}, ENGINEER))
    get_success_data(api.create_process_step(lot["id"], {"step": "STRANDING"}, ENGINEER))

    validate_error(
        api.create_process_step(
            lot["id"],
            {"step": "EXTRUSION", "measured_min_wall_mils": 25.5,
             "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
             "surface_marking_text": WRONG_MARKING_TEXT},
            ENGINEER,
        ),
        "ERR_MARKING_MISMATCH", 422,
    )
    refused = read_lot(api, lot["id"])
    assert refused["process_state"] == "STRANDED", "the refused step did not advance the lot"
    assert refused["surface_marking_text"] is None, "no print was stored"
    assert refused["concentricity_pct"] is None, "no measurement was stored"

    accepted = validate_success(
        api.create_process_step(
            lot["id"],
            {"step": "EXTRUSION", "measured_min_wall_mils": 25.5,
             "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
             "surface_marking_text": THHN_12_CU_MARKING},
            ENGINEER,
        ),
        200,
    )
    assert accepted["process_state"] == "EXTRUDED"
    assert accepted["surface_marking_text"] == THHN_12_CU_MARKING
    assert accepted["concentricity_pct"] == pytest.approx(85.00, abs=0.005), (
        "100 x 25.5 / 30.0 rounded half up to two decimals"
    )
    assert accepted["quality_state"] == "PENDING", "85.00 sits exactly on the SKU minimum"


def test_release_reports_lot_state_first_and_then_the_retained_failed_test(api):
    """The identical release call is refused three times for three different reasons,
    and the last of them is the failure row a rework could not erase.

    PRD 3.7: "The **failed-test** gate then scans *every* test row on the lot, not
    merely the latest per type, and refuses release with `ERR_LOT_TEST_FAILED` if
    any of them reads `FAIL`."

    PRD 3.7: "A re-test likewise supersedes its predecessor for the promotion
    decision only: the superseded row is never deleted, and a lot carrying any
    failed row can be re-tested back to `TESTED` yet can never be released — it
    can only be reworked or scrapped."

    Design: Corner/validations/release_ladder_walks_lot_state_then_retained_test_failure
    """
    world = setup_definitions_and_rod(api)
    lot = create_lot(api, world, lot_code="LOT-LADDER", planned_length_ft=5000)
    advance_lot_to_extruded(api, lot["id"])

    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_RELEASER),
        "ERR_INVALID_LOT_STATE", 409,
    )

    get_success_data(
        api.create_cable_test(
            lot["id"], {"test_type": "SPARK", "faults_detected": 0, "duration_sec": 60},
            QE_TESTER,
        )
    )
    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_RELEASER),
        "ERR_INVALID_LOT_STATE", 409,
    )

    failed = get_success_data(
        api.create_cable_test(
            lot["id"], {"test_type": "HIPOT", "test_voltage_kv": 2.4,
                        "breakdown_detected": False, "duration_sec": 300},
            QE_TESTER,
        )
    )
    assert failed["result"] == "FAIL"
    nonconforming = read_lot(api, lot["id"])
    assert nonconforming["quality_state"] == "NONCONFORMING"
    assert nonconforming["process_state"] == "EXTRUDED"

    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_RELEASER),
        "ERR_INVALID_LOT_STATE", 409,
    )

    reworked = get_success_data(
        api.disposition_production_lot(
            lot["id"],
            {"disposition": "REWORK", "rewind_to": "STRANDED",
             "reason": "hipot short of 2.5 kV"},
            QE_DISPOSITIONER,
        )
    )
    assert reworked["rework_count"] == 1
    assert reworked["process_state"] == "STRANDED"
    for cleared in ("measured_min_wall_mils", "measured_max_wall_mils",
                     "measured_avg_od_mm", "concentricity_pct", "surface_marking_text"):
        assert reworked[cleared] is None, f"rework clears {cleared}"

    get_success_data(
        api.create_process_step(
            lot["id"],
            {"step": "EXTRUSION", "measured_min_wall_mils": 25.5,
             "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
             "surface_marking_text": THHN_12_CU_MARKING},
            ENGINEER,
        )
    )
    get_success_data(
        api.create_cable_test(
            lot["id"], {"test_type": "HIPOT", "test_voltage_kv": 2.5,
                        "breakdown_detected": False, "duration_sec": 300},
            QE_TESTER,
        )
    )
    retested = read_lot(api, lot["id"])
    assert retested["process_state"] == "TESTED", (
        "the retained SPARK pass and the fresh HIPOT pass are the latest of their types"
    )
    assert retested["quality_state"] == "PENDING"
    rows, meta = validate_paginated(api.list_cable_tests(lot["id"], QE_TESTER))
    assert meta["total_count"] == 3, "the superseded failure row was never deleted"
    assert sum(1 for row in rows if row["result"] == "FAIL") == 1

    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_RELEASER),
        "ERR_LOT_TEST_FAILED", 422,
    )
    final = read_lot(api, lot["id"])
    assert final["quality_state"] == "PENDING"
    assert final["packaged_length_ft"] == 0, "the refused release certified no length"


def test_the_third_rework_is_refused_and_scrapping_is_the_only_way_out(api):
    """Two rewinds are allowed, the third is not, and the stuck lot's only remaining
    move writes its mass off to scrap.

    PRD 3.7: "A `REWORK` disposition is available from process state `EXTRUDED`
    and is refused once `rework_count` has already reached the limit of 2 — at
    that point the lot must be scrapped — with `ERR_REWORK_LIMIT_EXCEEDED`."

    PRD 3.7: "On the quality dimension the lot passes through `REWORK` and ends
    the same request at `PENDING`: `REWORK` is observable only as the transient
    the disposition response reports, and the persisted end state is always
    `PENDING`."

    Design: Corner/validations/rework_limit_of_two_is_enforced_then_the_lot_must_be_scrapped
    """
    world = setup_definitions_and_rod(api)
    lot = create_lot(api, world, lot_code="LOT-RWK", planned_length_ft=5000)
    eccentric = {"step": "EXTRUSION", "measured_min_wall_mils": 24.0,
                  "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
                  "surface_marking_text": THHN_12_CU_MARKING}
    rework = {"disposition": "REWORK", "rewind_to": "STRANDED", "reason": "eccentric wall"}

    advance_lot_to_extruded(api, lot["id"], extrusion_overrides={
        "measured_min_wall_mils": 24.0})
    assert read_lot(api, lot["id"])["concentricity_pct"] == pytest.approx(80.00, abs=0.005)
    assert read_lot(api, lot["id"])["quality_state"] == "NONCONFORMING"

    first = get_success_data(
        api.disposition_production_lot(lot["id"], rework, QE_DISPOSITIONER)
    )
    assert first["rework_count"] == 1
    assert first["quality_state"] == "REWORK", (
        "REWORK is observable only as the transient the disposition response reports"
    )
    assert first["process_state"] == "STRANDED"
    assert read_lot(api, lot["id"])["quality_state"] == "PENDING", (
        "the persisted end state is always PENDING"
    )

    get_success_data(api.create_process_step(lot["id"], eccentric, ENGINEER))
    second = get_success_data(
        api.disposition_production_lot(lot["id"], rework, QE_DISPOSITIONER)
    )
    assert second["rework_count"] == 2, "the second rewind is still within the limit"

    get_success_data(api.create_process_step(lot["id"], eccentric, ENGINEER))
    validate_error(
        api.disposition_production_lot(lot["id"], rework, QE_DISPOSITIONER),
        "ERR_REWORK_LIMIT_EXCEEDED", 422,
    )
    stuck = read_lot(api, lot["id"])
    assert stuck["rework_count"] == 2, "the refused rework did not increment the counter"
    assert stuck["quality_state"] == "NONCONFORMING"
    assert stuck["process_state"] == "EXTRUDED"

    scrapped = get_success_data(
        api.disposition_production_lot(
            lot["id"], {"disposition": "SCRAPPED", "reason": "three failed attempts"},
            QE_DISPOSITIONER,
        )
    )
    assert scrapped["process_state"] == "SCRAP_CLOSED"
    assert scrapped["quality_state"] == "SCRAPPED"

    rod = read_rod_lot(api, world["rod_lot"]["id"])
    assert rod["committed_lbs"] == pytest.approx(0.00, abs=0.01)
    assert rod["scrapped_lbs"] == pytest.approx(99.00, abs=0.01)
    assert rod["remaining_lbs"] == pytest.approx(19901.00, abs=0.01)
    assert rod["status"] == "RECEIVED", (
        "99.00 of 20000.00 lbs is 0.50 percent, nowhere near the ten percent alarm"
    )


def test_reel_capacity_and_the_orders_unshipped_balance_each_bound_the_delivery(api):
    """Two independent ceilings guard the same physical move, and each refusal is
    inert while the corrected figure clears the same rule.

    PRD 3.8: "Only after occupancy clears is capacity checked: `loaded_length_ft`
    plus the requested `load_length_ft` must not exceed `capacity_ft`, and an
    overload is refused with `ERR_REEL_CAPACITY_EXCEEDED`."

    PRD 3.8: "Quantity is then checked on two axes at once: the order's
    `shipped_kft` plus this shipment's `shipped_length_ft` divided by 1000 must
    not exceed `ordered_kft`, and `shipped_length_ft` must not exceed the lot's
    `packaged_length_ft`; either overrun is refused with
    `ERR_SHIPMENT_EXCEEDS_ORDER`."

    Design: Corner/validations/reel_capacity_and_order_quantity_limits_bound_the_shipment
    """
    world, lot = setup_released_lot(
        api, planned_length_ft=5000,
        order_overrides={"order_number": "SO-1001", "ordered_kft": 4.0},
    )
    reel = create_reel(api, capacity_ft=6000)

    validate_error(
        api.load_reel(
            reel["id"],
            {"lot_id": lot["id"], "load_length_ft": 7000,
             "occupancy_start_at": "2026-08-01T00:00:00Z"},
            CLERK,
        ),
        "ERR_REEL_CAPACITY_EXCEEDED", 422,
    )
    idle = read_reel(api, reel["id"])
    assert idle["status"] == "AVAILABLE"
    assert idle["loaded_length_ft"] == 0

    loaded = get_success_data(
        api.load_reel(
            reel["id"],
            {"lot_id": lot["id"], "load_length_ft": 5000,
             "occupancy_start_at": "2026-08-01T00:00:00Z"},
            CLERK,
        )
    )
    assert loaded["status"] == "LOADED"
    assert loaded["loaded_length_ft"] == 5000
    assert read_lot(api, lot["id"])["process_state"] == "PACKAGED"

    order_version = current_order_version(api, world["order"]["id"])
    over_quantity = {"order_id": world["order"]["id"], "lot_id": lot["id"],
                      "reel_id": reel["id"], "shipped_length_ft": 5000,
                      "ship_date": "2026-08-01", "cuts_count": 0,
                      "expected_order_version": order_version}
    validate_error(
        api.create_shipment(over_quantity, CLERK), "ERR_SHIPMENT_EXCEEDS_ORDER", 422
    )
    assert read_customer(api, world["customer"]["id"])[
        "reel_deposit_balance_usd"
    ] == pytest.approx(0.00, abs=0.01), "the refused staging charged no deposit"
    untouched_order = read_order(api, world["order"]["id"])
    assert untouched_order["shipped_kft"] == pytest.approx(0.0, abs=0.0005)
    assert untouched_order["version"] == order_version

    shipment = validate_success(
        api.create_shipment(dict(over_quantity, shipped_length_ft=4000), CLERK), 201
    )
    assert shipment["status"] == "STAGED"
    assert shipment["deposit_charged_usd"] == pytest.approx(450.00, abs=0.01)
    settled_order = read_order(api, world["order"]["id"])
    assert settled_order["shipped_kft"] == pytest.approx(4.0, abs=0.0005)
    assert settled_order["fulfillment_status"] == "FULFILLED"


def test_an_allocation_may_drain_the_heat_to_zero_but_never_past_it(api):
    """The rod guard is inclusive, so a lot that consumes the heat exactly is
    accepted while the next lot of any size at all is refused.

    PRD 3.6: "The rod lot's `remaining_lbs` must be at least the
    `consumed_rod_lbs` the new lot would draw; anything less is rejected with
    `ERR_INSUFFICIENT_ROD_QUANTITY`, since the uncommitted bucket may never go
    negative."

    Design: Corner/validations/rod_allocation_may_exhaust_but_not_exceed_remaining_mass
    """
    world = setup_definitions_and_rod(api, rod_overrides={"purchase_weight_lbs": 138.60})

    lot_a = create_lot(api, world, lot_code="LOT-A", planned_length_ft=7000)
    assert lot_a["consumed_rod_lbs"] == pytest.approx(138.60, abs=0.01), (
        "7000 / 1000 x 19.8 lbs per thousand feet"
    )
    assert lot_a["traceability_code"] == "H-77Q-LOT-A"

    exhausted = read_rod_lot(api, world["rod_lot"]["id"])
    assert exhausted["remaining_lbs"] == pytest.approx(0.00, abs=0.01)
    assert exhausted["committed_lbs"] == pytest.approx(138.60, abs=0.01)
    assert exhausted["scrapped_lbs"] == pytest.approx(0.00, abs=0.01)
    assert exhausted["status"] == "CONSUMED", (
        "the allocation landed remaining_lbs on exactly zero"
    )

    rod_version = exhausted["version"]
    validate_error(
        api.create_production_lot(
            {"product_id": world["product"]["id"], "rod_lot_id": world["rod_lot"]["id"],
             "lot_code": "LOT-B", "planned_length_ft": 100, "line_code": "EXT-2",
             "scheduled_start_at": "2026-08-03T08:00:00Z",
             "scheduled_end_at": "2026-08-03T10:00:00Z",
             "expected_rod_lot_version": rod_version},
            ENGINEER,
        ),
        "ERR_INSUFFICIENT_ROD_QUANTITY", 422,
    )
    rows, meta = validate_paginated(api.list_production_lots(ENGINEER))
    assert meta["total_count"] == 1, "a 1.98 lb lot cannot be drawn from an empty heat"
    assert read_rod_lot(api, world["rod_lot"]["id"])["version"] == rod_version, (
        "the version the caller sent was current, so the 412 rung never fired"
    )


def test_booking_needs_a_settlement_no_later_than_the_order_date(api):
    """The metal lookup is bounded by the order date, so an order dated one day
    before the only published settlement cannot be priced at all.

    PRD 3.5: "`order_date` is the effective pricing date in `YYYY-MM-DD` form and
    selects which settlement price the quote reads; it may legitimately be earlier
    than the logical clock's date."

    PRD 3.5: "If there is no candidate at all the order is refused outright with
    `ERR_NO_METAL_QUOTE` and nothing is created."

    Design: Corner/validations/order_requires_a_metal_quote_dated_no_later_than_the_order_date
    """
    world = setup_lv_catalog(api)
    customer = create_customer(api)

    validate_error(
        api.create_customer_order(
            create_customer_order_payload(
                customer["id"], world["product"]["id"], order_number="SO-EARLY",
                order_date="2026-07-29",
            ),
            BILLING,
        ),
        "ERR_NO_METAL_QUOTE", 422,
    )

    accepted = validate_success(
        api.create_customer_order(
            create_customer_order_payload(
                customer["id"], world["product"]["id"], order_number="SO-EARLY",
                order_date="2026-07-30",
            ),
            BILLING,
        ),
        201,
    )
    rows, meta = validate_paginated(api.list_customer_orders(BILLING))
    assert meta["total_count"] == 1, (
        "the refused booking created nothing, so the order number was free to reuse"
    )
    assert accepted["quoted_metal_price_usd_per_lb"] == pytest.approx(4.1000, abs=0.00005), (
        "an effective date equal to the order date is inside the candidate set"
    )
    assert accepted["quoted_unit_price_usd_per_kft"] == pytest.approx(106.7800, abs=0.00005)
    assert accepted["quoted_total_usd"] == pytest.approx(544.58, abs=0.01)


def test_a_medium_voltage_lot_cannot_be_released_without_its_laboratory_result(api):
    """Medium-voltage cable reaches TESTED on the in-line pair alone, and it is the
    release gate — not the promotion gate — that waits for partial discharge.

    PRD 3.7: "The **test-completeness** gate requires the latest row for every
    release-required test type to exist and to read `PASS`: `SPARK` and `HIPOT`
    always, plus `PARTIAL_DISCHARGE` whenever the SKU's `pd_test_required` is
    true."

    PRD 3.7: "A medium-voltage lot therefore reaches `TESTED` on the in-line pair
    alone, with its partial-discharge result still outstanding, and it is the
    release gate rather than the promotion gate that refuses to let it go further."

    Design: Corner/validations/mv_release_requires_the_offline_partial_discharge_result
    """
    world = setup_mv_catalog(api)
    world["customer"] = None
    world["order"] = None
    world["rod_lot"] = create_rod_lot(api)
    lot = create_lot(api, world, lot_code="LOT-MV", planned_length_ft=2000)
    advance_lot_to_stranded(api, lot["id"])
    extruded = get_success_data(
        api.create_process_step(
            lot["id"],
            {"step": "EXTRUSION", "measured_min_wall_mils": 160.0,
             "measured_max_wall_mils": 175.0, "measured_avg_od_mm": 22.0},
            ENGINEER,
        )
    )
    assert extruded["concentricity_pct"] == pytest.approx(91.43, abs=0.005), (
        "100 x 160.0 / 175.0 rounded half up, comfortably over the 85 minimum"
    )
    assert extruded["surface_marking_text"] is None, (
        "an MV_105 rating is marking-exempt, so no print was applied"
    )

    get_success_data(
        api.create_cable_test(
            lot["id"], {"test_type": "SPARK", "faults_detected": 0, "duration_sec": 60},
            QE_TESTER,
        )
    )
    get_success_data(
        api.create_cable_test(
            lot["id"], {"test_type": "HIPOT", "test_voltage_kv": 35.0,
                        "breakdown_detected": False, "duration_sec": 300},
            QE_TESTER,
        )
    )
    promoted = read_lot(api, lot["id"])
    assert promoted["process_state"] == "TESTED", (
        "the in-line pair promotes even though this SKU also owes a laboratory result"
    )
    assert promoted["quality_state"] == "PENDING"

    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 2000}, QE_RELEASER),
        "ERR_REQUIRED_TESTS_INCOMPLETE", 422,
    )
    inert = read_lot(api, lot["id"])
    assert inert["quality_state"] == "PENDING"
    assert inert["packaged_length_ft"] == 0, "the refused release certified no length"

    pd_row = get_success_data(
        api.create_cable_test(
            lot["id"], {"test_type": "PARTIAL_DISCHARGE", "pd_level_pc": 5.0,
                        "duration_sec": 600},
            QE_TESTER,
        )
    )
    assert pd_row["result"] == "PASS", "5.0 pC sits exactly on the MV_15KV limit"
    assert read_lot(api, lot["id"])["process_state"] == "TESTED", (
        "a partial-discharge row never moves the process dimension"
    )

    released = validate_success(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 2000}, QE_RELEASER),
        200,
    )
    assert released["quality_state"] == "CONFORMING"
    assert released["packaged_length_ft"] == 2000

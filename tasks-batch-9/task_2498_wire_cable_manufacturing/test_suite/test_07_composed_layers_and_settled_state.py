"""Requests that carry several independent layers at once, and the immediacy of
everything they settle.

The interesting question in this file is never whether one rule works. It is
whether a request that trips a version guard, a quantity ceiling and a fiscal
ceiling simultaneously answers with the earliest rung and leaves nothing behind,
whether a threshold that lands exactly on its limit stays quiet while the very
next pound tips a three-hop cascade, and whether every computed field and every
cross-aggregate side effect is final in the response of the call that caused it.
"""

import pytest

from test_helpers import (
    BILLING,
    BUYER,
    CERT_OFFICER,
    CLERK,
    ENGINEER,
    QE_TESTER,
    advance_lot_to_extruded,
    advance_lot_to_tested,
    assert_deposit_ledger_identity,
    assert_money,
    assert_rod_mass_conserved,
    create_catalog_product_payload,
    create_customer,
    create_customer_order_payload,
    create_insulation_compound_payload,
    create_lot,
    create_metal_quote,
    create_production_lot_payload,
    create_qualified_compound,
    create_reel,
    create_reel_return_payload,
    create_rod_lot,
    create_shipment_payload,
    current_order_version,
    current_rod_lot_version,
    get_success_data,
    hipot_test_payload,
    load_reel_payload,
    lower_credit_limit,
    read_certification,
    read_customer,
    read_lot,
    read_order,
    read_reel,
    read_rod_lot,
    record_inline_tests,
    release_lot,
    scrap_lot,
    set_clock,
    setup_baseline,
    setup_definitions_and_rod,
    setup_released_lot,
    setup_scrap_boundary_world,
    spark_test_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_LINE_WINDOW = {
    "line_code": "EXT-2",
    "scheduled_start_at": "2026-08-02T08:00:00Z",
    "scheduled_end_at": "2026-08-02T10:00:00Z",
}
THIRD_LINE_WINDOW = {
    "line_code": "EXT-3",
    "scheduled_start_at": "2026-08-02T08:00:00Z",
    "scheduled_end_at": "2026-08-02T10:00:00Z",
}


def test_a_stale_heat_version_refuses_an_otherwise_perfect_allocation(api):
    """The second allocation is legitimate in every respect except the version the
    client carries, the refusal burns no version and no mass, and the retry with
    the freshly read version succeeds unchanged.

    PRD 2.6: "If the supplied value does not equal that rod lot's current
    `version`, the request is rejected with `ERR_STALE_ROD_LOT_VERSION` (HTTP 412)
    and nothing is created."

    PRD 2.6: "The guard cannot be replaced by a state precondition: allocating rod
    to a second lot is perfectly legitimate on its own, since the rod lot remains
    `RECEIVED` and may still hold ample uncommitted mass, so the only thing
    distinguishing a safe allocation from one computed against a superseded mass
    ledger is the version the client carries."

    PRD 3.6: "A successful scheduling request moves `consumed_rod_lbs` out of the
    rod lot's `remaining_lbs` and into its `committed_lbs`, increments that rod
    lot's `version` by one, and — if the movement leaves `remaining_lbs` at
    exactly zero — carries the rod lot on to `CONSUMED` as described in §3.1."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency
    """
    world = setup_definitions_and_rod(api)
    rod_id = world["rod_lot"]["id"]
    stale_version = world["rod_lot"]["version"]
    assert_money(world["rod_lot"]["remaining_lbs"], 20000.00, "arrival mass")

    lot_a = create_lot(api, world, lot_code="LOT-A", planned_length_ft=5000)
    assert_money(lot_a["consumed_rod_lbs"], 99.00, "5.000 kft at 19.8 lbs/kft")

    after_first = read_rod_lot(api, rod_id)
    assert after_first["version"] == stale_version + 1, (
        "a successful allocation increments the heat's version by one"
    )
    assert_money(after_first["remaining_lbs"], 19901.00, "uncommitted mass")
    assert after_first["status"] == "RECEIVED", (
        "the heat still has mass left, so it has not reached CONSUMED"
    )

    refused = api.create_production_lot(
        create_production_lot_payload(
            world["product"]["id"], rod_id, stale_version,
            lot_code="LOT-B", planned_length_ft=1000, **SECOND_LINE_WINDOW,
        ),
        ENGINEER,
    )
    validate_error(refused, "ERR_STALE_ROD_LOT_VERSION", 412)

    after_refusal = read_rod_lot(api, rod_id)
    assert after_refusal["version"] == after_first["version"], (
        "a rejected write burns no version"
    )
    assert_money(after_refusal["remaining_lbs"], 19901.00, "uncommitted mass")
    assert_money(after_refusal["committed_lbs"], 99.00, "committed mass")
    assert after_refusal["status"] == "RECEIVED", (
        "no state rung could have caught this write: the heat is still RECEIVED "
        "and still holds ample uncommitted mass"
    )

    rows, meta = validate_paginated(api.list_production_lots(ENGINEER))
    assert len(rows) == 1, "the refused allocation created no phantom lot"
    assert meta["total_count"] == 1

    lot_b = create_lot(
        api, world, lot_code="LOT-B", planned_length_ft=1000, **SECOND_LINE_WINDOW
    )
    assert_money(lot_b["consumed_rod_lbs"], 19.80, "1.000 kft at 19.8 lbs/kft")

    final = read_rod_lot(api, rod_id)
    assert final["version"] == after_refusal["version"] + 1, (
        "the retry with the fresh version is the write that moves the ledger"
    )
    assert_money(final["remaining_lbs"], 19881.20, "uncommitted mass")
    assert_money(final["committed_lbs"], 118.80, "committed mass")
    assert_money(final["scrapped_lbs"], 0.00, "nothing was drawn and written off")
    assert_rod_mass_conserved(final)
    assert final["status"] == "RECEIVED", (
        "remaining_lbs never reached zero, so the CONSUMED transition did not fire"
    )


def test_a_scrap_of_exactly_ten_percent_stays_quiet_and_the_next_pound_tips_it(api):
    """The quarantine trigger is a strict greater-than on a rounded percentage, so a
    scrap landing on exactly 10.00 percent leaves the heat and its sibling lots
    alone, and the next scrap of ten pounds fires all three cascade hops.

    PRD 3.7: "Second, caused by that mass mutation rather than by the disposition
    request itself, the rod lot auto-transitions `RECEIVED` → `QUARANTINED` when
    its scrap percentage — one hundred multiplied by `scrapped_lbs` divided by
    `purchase_weight_lbs`, rounded half up to two decimals — is strictly greater
    than 10.00."

    PRD 3.7: "Third, caused by that quarantine, every other production lot drawn
    from the same rod lot whose quality dimension reads `PENDING`, processed in
    ascending `created_at` order, moves to `QUARANTINED`."

    PRD 3.6: "Drawing advances the lot `QUEUED` → `DRAWN` on the process dimension.
    It requires the quality dimension to read either `PENDING` or `REWORK` — so a
    lot that has just been rewound for rework may be drawn again — and it requires
    the lot's SKU to be `RELEASED` at that moment, which is where a suspended SKU
    stops work that had not yet started."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_triggers
    """
    world = setup_scrap_boundary_world(api)
    rod_id = world["rod_lot"]["id"]
    marking = world["product"]["required_marking_text"]
    measurements = {
        "measured_min_wall_mils": 27.5,
        "measured_max_wall_mils": 32.0,
        "measured_avg_od_mm": 4.60,
        "surface_marking_text": marking,
    }

    lot_s1 = create_lot(api, world, lot_code="LOT-S1", planned_length_ft=5000)
    lot_s2 = create_lot(
        api, world, lot_code="LOT-S2", planned_length_ft=500, **SECOND_LINE_WINDOW
    )
    lot_s3 = create_lot(
        api, world, lot_code="LOT-S3", planned_length_ft=1000, **THIRD_LINE_WINDOW
    )
    assert_money(lot_s1["consumed_rod_lbs"], 100.00, "5.000 kft at 20.0 lbs/kft")
    assert_money(lot_s2["consumed_rod_lbs"], 10.00, "0.500 kft at 20.0 lbs/kft")
    assert_money(lot_s3["consumed_rod_lbs"], 20.00, "1.000 kft at 20.0 lbs/kft")

    extruded = advance_lot_to_extruded(
        api, lot_s1["id"], extrusion_overrides=measurements
    )
    assert extruded["concentricity_pct"] == pytest.approx(85.94, abs=0.01), (
        "27.5 of a 32.0 maximum wall clears the concentricity floor, so this lot "
        "fails on the electrical test rather than on its dimensions"
    )
    tests = record_inline_tests(
        api, lot_s1["id"], hipot_overrides={"test_voltage_kv": 2.4}
    )
    assert tests["hipot"]["result"] == "FAIL", (
        "2.4 kV falls short of the 2.5 kV an LV_600 class demands"
    )

    scrapped = scrap_lot(
        api, lot_s1["id"], reason="hipot below required withstand voltage"
    )
    assert scrapped["process_state"] == "SCRAP_CLOSED"
    assert scrapped["quality_state"] == "SCRAPPED"

    at_boundary = read_rod_lot(api, rod_id)
    assert_money(at_boundary["scrapped_lbs"], 100.00, "written-off mass")
    assert_money(at_boundary["committed_lbs"], 30.00, "the two surviving lots")
    assert_money(at_boundary["remaining_lbs"], 870.00, "uncommitted mass")
    assert_rod_mass_conserved(at_boundary)
    assert at_boundary["status"] == "RECEIVED", (
        "100.00 of 1000.00 lbs is exactly 10.00 percent, which is not strictly "
        "greater than the threshold, so the heat is not quarantined"
    )
    assert read_lot(api, lot_s3["id"])["quality_state"] == "PENDING", (
        "with no quarantine there is no third hop to reach the sibling lot"
    )

    advance_lot_to_extruded(api, lot_s2["id"], extrusion_overrides=measurements)
    record_inline_tests(api, lot_s2["id"], hipot_overrides={"test_voltage_kv": 2.4})
    second_scrap = scrap_lot(
        api, lot_s2["id"], reason="hipot below required withstand voltage"
    )
    assert second_scrap["quality_state"] == "SCRAPPED"

    tipped = read_rod_lot(api, rod_id)
    assert_money(tipped["scrapped_lbs"], 110.00, "written-off mass")
    assert tipped["status"] == "QUARANTINED", (
        "110.00 of 1000.00 lbs rounds to 11.00 percent, which is strictly greater "
        "than the threshold"
    )
    assert_money(tipped["remaining_lbs"], 870.00, "uncommitted mass is untouched")
    assert_money(tipped["committed_lbs"], 20.00, "only the queued lot is still committed")
    assert_rod_mass_conserved(tipped)

    bystander = read_lot(api, lot_s3["id"])
    assert bystander["quality_state"] == "QUARANTINED", (
        "the third hop reaches the lot nobody dispositioned"
    )
    assert bystander["process_state"] == "QUEUED", (
        "the cascade moves the quality dimension only"
    )
    assert read_lot(api, lot_s1["id"])["quality_state"] == "SCRAPPED", (
        "the cascade skips lots whose quality dimension is not PENDING"
    )
    assert read_lot(api, lot_s2["id"])["quality_state"] == "SCRAPPED", (
        "the lot that caused the quarantine is not rewritten to QUARANTINED"
    )

    refused = api.create_process_step(lot_s3["id"], {"step": "DRAWING"}, ENGINEER)
    validate_error(refused, "ERR_INVALID_LOT_STATE", 409)


def test_a_version_guard_a_quantity_ceiling_and_a_credit_ceiling_answer_in_order(api):
    """One staging request carries a stale version, a quantity overrun and an account
    on hold at once. Only the earliest rung speaks, the refusal runs nothing, and
    each repair exposes exactly the next layer.

    PRD 2.11: "When a single request would violate more than one rule, the error the
    caller receives is fixed, not arbitrary. Checks are evaluated in the following
    order, and the first failure ends the request with no persisted effect
    whatsoever:"

    PRD 2.6: "If it does not equal the order's current `version`, the request is
    rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) and no shipment is created."

    PRD 3.8: "Quantity is then checked on two axes at once: the order's `shipped_kft`
    plus this shipment's `shipped_length_ft` divided by 1000 must not exceed
    `ordered_kft`, and `shipped_length_ft` must not exceed the lot's
    `packaged_length_ft`; either overrun is refused with `ERR_SHIPMENT_EXCEEDS_ORDER`."

    PRD 3.8: "Finally credit is checked: the shipping account's `status` must be
    `ACTIVE`, and its `credit_exposure_usd` plus the reel's `deposit_usd` must not
    exceed its `credit_limit_usd`."

    Design: Corner/cross_cutting_complexity_layers/layers_compose_on_one_request
    """
    world = setup_baseline(api, order_overrides={"ordered_kft": 6.000})
    order_id = world["order"]["id"]
    customer_id = world["customer"]["id"]

    world, lot_a = setup_released_lot(api, world=world, planned_length_ft=5000)
    lot_b = create_lot(
        api, world, lot_code="LOT-B", planned_length_ft=2000, **SECOND_LINE_WINDOW
    )
    advance_lot_to_tested(api, lot_b["id"])
    lot_b = release_lot(api, lot_b["id"], 2000)

    reel_a = create_reel(api)
    get_success_data(
        api.load_reel(reel_a["id"], load_reel_payload(lot_a["id"], 5000), CLERK)
    )
    reel_b = create_reel(
        api, reel_serial="R-002", deposit_usd=300.00, capacity_ft=2000
    )
    get_success_data(
        api.load_reel(reel_b["id"], load_reel_payload(lot_b["id"], 2000), CLERK)
    )

    stale_version = current_order_version(api, order_id)
    validate_success(
        api.create_shipment(
            create_shipment_payload(
                order_id, lot_a["id"], reel_a["id"], 5000, stale_version
            ),
            CLERK,
        ),
        201,
    )
    after_first = read_order(api, order_id)
    fresh_version = after_first["version"]
    assert fresh_version == stale_version + 1, (
        "the first staging increments the order's version by one"
    )
    assert after_first["shipped_kft"] == pytest.approx(5.000, abs=0.001)
    assert after_first["fulfillment_status"] == "PARTIALLY_SHIPPED", (
        "5.000 of 6.000 kft is strictly below the ordered length"
    )

    held = lower_credit_limit(api, customer_id, 400.00)
    assert_money(held["credit_exposure_usd"], 450.00, "one outstanding deposit")
    assert_money(held["open_ar_usd"], 0.00, "a staged shipment is not yet a receivable")
    assert held["status"] == "CREDIT_HOLD", (
        "exposure of 450.00 is strictly greater than the new 400.00 limit"
    )

    all_three_armed = api.create_shipment(
        create_shipment_payload(
            order_id, lot_b["id"], reel_b["id"], 2000, stale_version
        ),
        CLERK,
    )
    validate_error(all_three_armed, "ERR_STALE_ORDER_VERSION", 412)

    assert read_reel(api, reel_b["id"])["status"] == "LOADED", (
        "the refused request did not advance the reel"
    )
    inert = read_order(api, order_id)
    assert inert["version"] == fresh_version, "a rejected write burns no version"
    assert inert["shipped_kft"] == pytest.approx(5.000, abs=0.001)
    rows, meta = validate_paginated(api.list_shipments(CLERK))
    assert len(rows) == 1 and meta["total_count"] == 1, (
        "the refused request staged no shipment"
    )

    over_quantity = api.create_shipment(
        create_shipment_payload(
            order_id, lot_b["id"], reel_b["id"], 2000, fresh_version
        ),
        CLERK,
    )
    validate_error(over_quantity, "ERR_SHIPMENT_EXCEEDS_ORDER", 422)

    over_credit = api.create_shipment(
        create_shipment_payload(
            order_id, lot_b["id"], reel_b["id"], 1000, fresh_version
        ),
        CLERK,
    )
    validate_error(over_credit, "ERR_CREDIT_LIMIT_EXCEEDED", 402)

    restored = lower_credit_limit(api, customer_id, 100000.00)
    assert restored["status"] == "ACTIVE", (
        "raising the limit re-evaluates the standing inside the adjustment response"
    )

    shipment_b = validate_success(
        api.create_shipment(
            create_shipment_payload(
                order_id, lot_b["id"], reel_b["id"], 1000, fresh_version
            ),
            CLERK,
        ),
        201,
    )
    assert_money(shipment_b["deposit_charged_usd"], 300.00, "the second reel's deposit")

    final_reel = read_reel(api, reel_b["id"])
    assert final_reel["status"] == "SHIPPED"
    assert final_reel["cycle_count"] == 0, (
        "cycle_count counts completed ship-and-return cycles and is incremented "
        "only when the reel comes back"
    )
    assert read_lot(api, lot_b["id"])["process_state"] == "SHIPPED", (
        "a partial draw still closes the lot out: 2000 ft were packaged and only "
        "1000 ft shipped"
    )

    final_order = read_order(api, order_id)
    assert final_order["shipped_kft"] == pytest.approx(6.000, abs=0.001)
    assert final_order["fulfillment_status"] == "FULFILLED", (
        "the accumulated total equals the ordered length exactly"
    )
    assert final_order["version"] == fresh_version + 1

    final_customer = read_customer(api, customer_id)
    assert_money(final_customer["reel_deposit_balance_usd"], 750.00, "two deposits")
    assert_money(final_customer["credit_exposure_usd"], 750.00, "exposure")
    assert final_customer["status"] == "ACTIVE", "750.00 is under the restored limit"


def test_every_mutation_answers_with_state_an_immediate_re_read_confirms(api):
    """Walking the whole line from a listing inspection to a returned reel, pairing
    each mutation with a read of the record it moved indirectly. There is no
    settling window: the causing response and the next call always agree.

    PRD 2.7: "The service therefore models these as **multi-hop cascades** executed
    inside the single request that triggered them, with immediate consistency: by
    the time the response is written, every affected record has already been moved
    and has already had its `version` incremented and its `updated_at` refreshed."

    PRD 2.9: "Both are tracked as running ledger fields on the account rather than
    recomputed from scratch on read, and both are refreshed inside the same request
    as the event that changed them."

    PRD 3.9: "Invoicing then settles four things."

    Design: Corner/consistency_model/every_mutating_response_is_already_the_settled_state
    """
    set_clock(api)
    create_metal_quote(api)
    insulation = create_qualified_compound(api, create_insulation_compound_payload())

    certification = validate_success(
        api.create_listing_certification(
            {
                "agency": "UL",
                "file_number": "E12345",
                "product_family_code": "BLDG-WIRE",
                "initial_listing_date": "2026-06-01",
                "inspection_interval_days": 90,
            },
            CERT_OFFICER,
        ),
        201,
    )
    inspection = validate_success(
        api.create_factory_inspection(
            certification["id"],
            {
                "inspection_date": "2026-06-05",
                "inspector_code": "INS-7",
                "findings_count": 0,
                "outcome": "PASS",
            },
            CERT_OFFICER,
        ),
        201,
    )
    assert inspection["corrective_action_due_date"] is None, (
        "a passing visit opens no corrective action"
    )
    activated = read_certification(api, certification["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["next_inspection_due_date"] == "2026-09-03", (
        "the parent's derived window is already advanced on the very next call"
    )

    product = validate_success(
        api.create_catalog_product(
            create_catalog_product_payload(insulation["id"], certification["id"]),
            ENGINEER,
        ),
        201,
    )
    assert product["required_marking_text"] == "UL E12345 12AWG THHN 90C 600V", (
        "the marking is composed in the creating response, not filled in later"
    )
    get_success_data(api.release_catalog_product(product["id"], ENGINEER))

    customer = create_customer(api)
    order = validate_success(
        api.create_customer_order(
            create_customer_order_payload(customer["id"], product["id"]),
            BILLING,
        ),
        201,
    )
    assert order["quoted_unit_price_usd_per_kft"] == pytest.approx(
        106.7800, abs=0.0001
    ), "85.00 conversion plus 19.8 lbs/kft over a 1.10 pass-through"

    rod_lot = create_rod_lot(api)
    lot = validate_success(
        api.create_production_lot(
            create_production_lot_payload(
                product["id"], rod_lot["id"],
                current_rod_lot_version(api, rod_lot["id"]),
                order_id=order["id"], lot_code="LOT-A", planned_length_ft=5000,
            ),
            ENGINEER,
        ),
        201,
    )
    assert_money(lot["consumed_rod_lbs"], 99.00, "mass drawn by the allocation")
    assert lot["traceability_code"] == "H-77Q-LOT-A", (
        "the heat number and the lot code are joined in the creating response"
    )
    allocated_rod = read_rod_lot(api, rod_lot["id"])
    assert_money(allocated_rod["committed_lbs"], 99.00, "committed mass")
    assert_money(allocated_rod["remaining_lbs"], 19901.00, "uncommitted mass")

    extruded = advance_lot_to_extruded(api, lot["id"])
    assert extruded["concentricity_pct"] == pytest.approx(85.00, abs=0.01), (
        "25.5 of a 30.0 maximum wall, derived in the step response itself"
    )
    assert read_lot(api, lot["id"])["concentricity_pct"] == pytest.approx(
        85.00, abs=0.01
    ), "the immediate re-read is identical, so no client needs to re-fetch"

    get_success_data(api.create_cable_test(lot["id"], spark_test_payload(), QE_TESTER))
    hipot = get_success_data(
        api.create_cable_test(lot["id"], hipot_test_payload(), QE_TESTER)
    )
    assert hipot["result"] == "PASS"
    assert read_lot(api, lot["id"])["process_state"] == "TESTED", (
        "the promotion the test caused is visible on the parent lot at once, even "
        "though the test response cannot show it"
    )

    released = release_lot(api, lot["id"], 5000)
    assert released["quality_state"] == "CONFORMING"

    reel = create_reel(api)
    loaded = get_success_data(
        api.load_reel(reel["id"], load_reel_payload(lot["id"], 5000), CLERK)
    )
    assert loaded["status"] == "LOADED"
    assert loaded["loaded_length_ft"] == 5000
    assert read_lot(api, lot["id"])["process_state"] == "PACKAGED", (
        "the load's effect on the lot needs no settling time"
    )

    get_success_data(api.price_lock_customer_order(order["id"], BILLING))
    shipment = validate_success(
        api.create_shipment(
            create_shipment_payload(
                order["id"], lot["id"], reel["id"], 5000,
                current_order_version(api, order["id"]),
            ),
            CLERK,
        ),
        201,
    )
    assert_money(shipment["deposit_charged_usd"], 450.00, "the reel's deposit")
    after_ship = read_customer(api, customer["id"])
    assert_money(after_ship["reel_deposit_balance_usd"], 450.00, "deposit ledger")
    assert_money(after_ship["credit_exposure_usd"], 450.00, "exposure")
    assert_money(after_ship["open_ar_usd"], 0.00, "a staged shipment is not a receivable")

    invoiced = get_success_data(api.invoice_shipment(shipment["id"], BILLING))
    assert_money(invoiced["invoice_amount_usd"], 544.58, "invoice total")
    assert_money(invoiced["volatility_surcharge_usd"], 10.68, "two percent of 533.90")
    after_invoice = read_customer(api, customer["id"])
    assert_money(after_invoice["open_ar_usd"], 544.58, "receivable")
    assert_money(after_invoice["credit_exposure_usd"], 994.58, "receivable plus deposit")
    invoiced_order = read_order(api, order["id"])
    assert invoiced_order["pricing_status"] == "INVOICED"
    assert invoiced_order["fulfillment_status"] == "FULFILLED"
    assert read_reel(api, reel["id"])["status"] == "RETURN_PENDING", (
        "the invoice's parallel effects are all readable at once"
    )

    set_clock(api, "2026-08-10T00:00:00Z")
    reel_return = validate_success(
        api.create_reel_return(
            reel["id"],
            create_reel_return_payload(shipment["id"], "2026-08-10", "GOOD"),
            CLERK,
        ),
        201,
    )
    assert reel_return["days_out"] == 9, (
        "whole calendar days from the 2026-08-01 shipping instant to the return"
    )
    assert reel_return["refund_variant_applied"] == "FLAT_STEP"
    assert_money(reel_return["refund_usd"], 450.00, "a wood reel back inside 90 days")

    rows, meta = validate_paginated(api.list_reel_returns(reel["id"], CLERK))
    assert meta["total_count"] == 1
    assert rows[0]["days_out"] == reel_return["days_out"], (
        "the append-only child re-reads exactly as it was written"
    )
    assert_money(rows[0]["refund_usd"], reel_return["refund_usd"], "refund on re-read")

    after_return = read_customer(api, customer["id"])
    assert_money(after_return["reel_deposit_balance_usd"], 0.00, "deposit ledger")
    assert_money(
        after_return["credit_memo_balance_usd"], reel_return["refund_usd"],
        "the credit memo equals exactly the refund the return reported",
    )
    assert_deposit_ledger_identity(after_return)

    final_reel = read_reel(api, reel["id"])
    assert final_reel["status"] == "AVAILABLE"
    assert final_reel["cycle_count"] == 1, "one completed ship-and-return cycle"
    assert final_reel["loaded_length_ft"] == 0


def test_a_cancellation_is_already_visible_through_every_filtered_page(api):
    """A cancel moves the order, closes a lot the caller never named and compensates
    the metal ledger. All three are already visible through filtered list
    endpoints on the next call, and list rows never diverge from single reads.

    PRD 3.5: "A successful cancellation sets the fulfillment dimension to
    `CANCELLED` and increments `version` by one, and deliberately leaves the
    pricing dimension exactly where it was."

    PRD 3.5: "Every production lot belonging to the cancelled order whose process
    dimension is `QUEUED`, processed in ascending `created_at` order, has its
    process dimension set to `SCRAP_CLOSED` while its quality dimension is left at
    `PENDING` — nothing was ever produced, so nothing is scrapped — and its
    `version` incremented by one."

    PRD 3.5: "For each such lot, its `consumed_rod_lbs` moves out of the rod lot's
    `committed_lbs` and back into that rod lot's `remaining_lbs`, never into
    `scrapped_lbs`, because a queued lot has not been drawn; the rod lot's
    `version` is incremented by one for each movement."

    Design: Corner/consistency_model/list_projections_reflect_a_cascade_at_the_same_instant
    """
    world = setup_baseline(api)
    order_id = world["order"]["id"]
    lot = create_lot(api, world, lot_code="LOT-A", planned_length_ft=5000)

    rows, meta = validate_paginated(
        api.list_production_lots(ENGINEER, params={"process_state": "QUEUED"})
    )
    assert [row["lot_code"] for row in rows] == ["LOT-A"]
    assert meta["total_count"] == 1
    rows, meta = validate_paginated(
        api.list_rod_purchase_lots(BUYER, params={"status": "RECEIVED"})
    )
    assert meta["total_count"] == 1
    assert_money(rows[0]["committed_lbs"], 99.00, "committed mass in the list row")
    assert_money(rows[0]["remaining_lbs"], 19901.00, "uncommitted mass in the list row")

    cancelled = get_success_data(
        api.cancel_customer_order(
            order_id, BILLING,
            {"reason": "customer released the job to another mill"},
        )
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["pricing_status"] == "QUOTED", (
        "the pricing dimension is deliberately left alone"
    )

    rows, meta = validate_paginated(
        api.list_customer_orders(BILLING, params={"fulfillment_status": "CANCELLED"})
    )
    assert [row["order_number"] for row in rows] == ["SO-1001"]
    assert meta["total_count"] == 1, "the order is already reclassified for readers"

    rows, meta = validate_paginated(
        api.list_production_lots(ENGINEER, params={"process_state": "SCRAP_CLOSED"})
    )
    assert [row["lot_code"] for row in rows] == ["LOT-A"], (
        "the lot the caller never named is already closed"
    )
    assert meta["total_count"] == 1
    assert rows[0]["quality_state"] == "PENDING", (
        "nothing was ever produced, so nothing is scrapped"
    )

    rows, meta = validate_paginated(
        api.list_production_lots(ENGINEER, params={"process_state": "QUEUED"})
    )
    assert rows == [], "the QUEUED page is empty in the same instant"
    assert meta["total_count"] == 0

    rows, meta = validate_paginated(
        api.list_production_lots(
            ENGINEER, params={"quality_state": "PENDING", "order_id": order_id}
        )
    )
    assert [row["lot_code"] for row in rows] == ["LOT-A"], (
        "both list filters see the split between the two dimensions correctly"
    )
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_rod_purchase_lots(BUYER, params={"status": "RECEIVED"})
    )
    assert meta["total_count"] == 1, (
        "the compensation restores mass without touching the heat's state machine"
    )
    assert_money(rows[0]["committed_lbs"], 0.00, "committed mass in the list row")
    assert_money(rows[0]["remaining_lbs"], 20000.00, "uncommitted mass in the list row")
    assert_money(rows[0]["scrapped_lbs"], 0.00, "a queued lot was never drawn")
    assert_rod_mass_conserved(rows[0])

    direct = read_lot(api, lot["id"])
    assert direct["process_state"] == "SCRAP_CLOSED", (
        "a single read never diverges from the list row"
    )
    assert direct["quality_state"] == "PENDING"

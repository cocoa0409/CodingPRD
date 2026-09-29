"""Lifecycle walks: legal transitions, birth states and refused entry points.

Each record in the plant has a declared starting state and a declared set of
admissible moves. These tests walk the legal paths and then knock on the doors
that are supposed to be closed.
"""

import pytest

from test_helpers import (
    BILLING,
    CERT_OFFICER,
    CLERK,
    ENGINEER,
    QE_DISPOSITIONER,
    QE_RELEASER,
    QE_TESTER,
    advance_lot_to_drawn,
    advance_lot_to_extruded,
    create_active_certification,
    create_customer_order_payload,
    create_factory_inspection_payload,
    create_insulation_compound_payload,
    create_lot,
    create_reel,
    create_released_product,
    get_success_data,
    read_customer,
    read_lot,
    read_order,
    read_reel,
    read_shipment,
    release_lot,
    scrap_disposition_payload,
    setup_baseline,
    setup_cancelled_order,
    setup_definitions_and_rod,
    setup_loaded_reel,
    setup_lv_catalog,
    setup_released_lot,
    setup_staged_shipment,
    spark_test_payload,
    stranding_step_payload,
    validate_error,
    validate_success,
)

SOLID_SKU_OVERRIDES = {
    "product_code": "THHN-12-CU-SOLID",
    "conductor_construction": "SOLID",
}


def test_a_formulation_walks_draft_qualified_suspended_and_back_to_qualified(api):
    """Qualification is reachable twice — the second time out of suspension — and
    each arrival at a state closes the door behind it.

    PRD 3.2: "The cycle `DRAFT` → `QUALIFIED` → `SUSPENDED` → `QUALIFIED` is
    therefore legal and expected — and it has a consequence that reaches a long
    way, because a re-qualification bumps `version`, and any SKU that pinned the
    pre-suspension version is now pinned to a formulation that no longer exists."

    Design: Corner/state_machines/compound_qualify_suspend_requalify_walks_the_declared_cycle
    """
    compound = validate_success(
        api.create_compound(create_insulation_compound_payload(), ENGINEER), 201
    )
    assert compound["status"] == "DRAFT"
    assert compound["version"] == 1

    qualified = validate_success(api.qualify_compound(compound["id"], ENGINEER), 200)
    assert qualified["status"] == "QUALIFIED"
    assert qualified["version"] == 2, "qualification is a mutation and bumps version by one"
    assert qualified["qualification_date"] == "2026-08-01", (
        "qualification stamps the current logical UTC date"
    )
    assert qualified["suspension_reason"] is None

    validate_error(
        api.qualify_compound(compound["id"], ENGINEER), "ERR_INVALID_COMPOUND_STATE", 409
    )

    suspended = validate_success(
        api.suspend_compound(
            compound["id"], ENGINEER, {"suspension_reason": "filler lot out of spec"}
        ),
        200,
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 3
    assert suspended["suspension_reason"] == "filler lot out of spec", (
        "the supplied reason is stored verbatim"
    )

    validate_error(
        api.suspend_compound(
            compound["id"], ENGINEER, {"suspension_reason": "again"}
        ),
        "ERR_INVALID_COMPOUND_STATE",
        409,
    )

    requalified = validate_success(api.qualify_compound(compound["id"], ENGINEER), 200)
    assert requalified["status"] == "QUALIFIED"
    assert requalified["version"] == 4, (
        "the re-qualification is the fourth write, and it is the version bump that "
        "strands any SKU pinned to version 2"
    )
    assert requalified["suspension_reason"] is None, (
        "re-qualification clears the suspension reason back to null"
    )


def test_every_freshly_created_record_reports_its_declared_opening_state(api):
    """Nothing in the plant is born mid-flight: each record answers with the exact
    opening state, counters and null fields the contract names.

    PRD 3.5: "A new account starts with every ledger field at 0.00 —
    `open_ar_usd`, `deposit_charged_total_usd`, `reel_deposit_balance_usd`,
    `credit_memo_balance_usd`, `forfeited_deposit_total_usd` and
    `credit_exposure_usd` — and with `status` at `ACTIVE`."

    PRD 3.8: "A registered reel begins at `AVAILABLE` with `loaded_length_ft` at
    0, `cycle_count` at 0, and `current_lot_id`, `held_by_customer_id`,
    `occupancy_start_at`, `occupancy_end_at`, `shipped_at`, `returned_at` and
    `last_return_condition` all null or zero as applicable."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    compound = validate_success(
        api.create_compound(create_insulation_compound_payload(), ENGINEER), 201
    )
    assert compound["status"] == "DRAFT"

    cert = validate_success(
        api.create_listing_certification(
            {"agency": "UL", "file_number": "E99999",
             "product_family_code": "BLDG-WIRE", "initial_listing_date": "2026-06-01"},
            CERT_OFFICER,
        ),
        201,
    )
    assert cert["status"] == "PENDING"
    assert cert["open_variation_count"] == 0
    assert cert["last_inspection_date"] is None
    assert cert["next_inspection_due_date"] is None

    world = setup_baseline(api, with_order=False)
    draft = validate_success(
        api.create_catalog_product(
            {"product_code": "THHN-14-CU", "awg_size": "14",
             "conductor_metal": "COPPER", "conductor_construction": "SOLID",
             "application_rating": "THHN", "voltage_class": "LV_600",
             "temp_rating_c": 90, "insulation_thickness_mils": 30.0,
             "conductor_lbs_per_kft": 12.4,
             "insulation_compound_id": world["insulation"]["id"],
             "listing_certification_id": world["certification"]["id"],
             "base_target_kft": 40.0},
            ENGINEER,
        ),
        201,
    )
    assert draft["status"] == "DRAFT"
    assert draft["volatility_index"] == pytest.approx(0.0, abs=0.00005)
    assert draft["target_inventory_kft"] == pytest.approx(40.0, abs=0.05)
    assert draft["pinned_insulation_compound_version"] is None
    assert draft["pinned_jacket_compound_version"] is None

    customer = read_customer(api, world["customer"]["id"])
    for ledger_field in ("open_ar_usd", "deposit_charged_total_usd",
                          "reel_deposit_balance_usd", "credit_memo_balance_usd",
                          "forfeited_deposit_total_usd", "credit_exposure_usd"):
        assert customer[ledger_field] == pytest.approx(0.00, abs=0.01), (
            f"{ledger_field} opens at 0.00, got {customer[ledger_field]}"
        )
    assert customer["status"] == "ACTIVE"

    order = validate_success(
        api.create_customer_order(
            create_customer_order_payload(
                world["customer"]["id"], world["product"]["id"], order_number="SO-INIT"
            ),
            BILLING,
        ),
        201,
    )
    assert order["pricing_status"] == "QUOTED"
    assert order["fulfillment_status"] == "OPEN"
    assert order["shipped_kft"] == pytest.approx(0.0, abs=0.0005)
    assert order["invoiced_total_usd"] == pytest.approx(0.00, abs=0.01)
    assert order["hold_reason"] is None

    world["order"] = order
    lot = create_lot(api, world, lot_code="LOT-INIT", line_code="EXT-7")
    assert lot["process_state"] == "QUEUED"
    assert lot["quality_state"] == "PENDING"

    reel = create_reel(api)
    assert reel["status"] == "AVAILABLE"
    assert reel["loaded_length_ft"] == 0
    assert reel["cycle_count"] == 0
    for null_field in ("current_lot_id", "held_by_customer_id", "occupancy_start_at",
                        "occupancy_end_at", "shipped_at", "returned_at",
                        "last_return_condition"):
        assert reel[null_field] is None, f"{null_field} opens null, got {reel[null_field]!r}"

    _, _, _, shipment = setup_staged_shipment(api, world=world, lot=None)
    assert shipment["status"] == "STAGED"
    for unpriced in ("metal_price_used_usd_per_lb", "price_variant_applied",
                      "unit_price_usd_per_kft", "extended_amount_usd", "cut_fee_usd",
                      "volatility_surcharge_usd", "invoice_amount_usd", "invoice_date"):
        assert shipment[unpriced] is None, (
            f"{unpriced} stays null until the shipment is invoiced, "
            f"got {shipment[unpriced]!r}"
        )


def test_definition_layer_transitions_refuse_inadmissible_starting_states(api):
    """The compound, listing-file and SKU state machines each answer with their own
    state code when a transition is requested from a state that does not offer it.

    PRD 3.3: "A `VARIATION` or `SUSPEND` outcome on a `PENDING` file, and any
    inspection at all recorded against a file that is already `SUSPENDED`, are
    rejected with `ERR_INVALID_CERTIFICATION_STATE`."

    PRD 3.4: "Releasing a SKU is the gate between engineering and commerce, and a
    `ProcessEngineer` performs it on a SKU that is `DRAFT` or that has been
    returned to `SUSPENDED`; a SKU that is already `RELEASED`, or that has been
    retired to `OBSOLETE`, is rejected with `ERR_INVALID_PRODUCT_STATE`."

    Design: Corner/state_machines/invalid_from_states_on_definition_entities_return_state_errors
    """
    world = setup_lv_catalog(api, with_jacket=False)

    validate_error(
        api.qualify_compound(world["insulation"]["id"], ENGINEER),
        "ERR_INVALID_COMPOUND_STATE", 409,
    )
    draft_compound = validate_success(
        api.create_compound(
            create_insulation_compound_payload(compound_code="PVC-90-B"), ENGINEER
        ),
        201,
    )
    validate_error(
        api.suspend_compound(
            draft_compound["id"], ENGINEER, {"suspension_reason": "never qualified"}
        ),
        "ERR_INVALID_COMPOUND_STATE", 409,
    )

    pending_cert = validate_success(
        api.create_listing_certification(
            {"agency": "CSA", "file_number": "C4321",
             "product_family_code": "CORD", "initial_listing_date": "2026-05-01"},
            CERT_OFFICER,
        ),
        201,
    )
    validate_error(
        api.create_factory_inspection(
            pending_cert["id"],
            create_factory_inspection_payload(
                inspection_date="2026-06-01", findings_count=2, outcome="VARIATION"
            ),
            CERT_OFFICER,
        ),
        "ERR_INVALID_CERTIFICATION_STATE", 409,
    )
    validate_error(
        api.reinstate_listing_certification(pending_cert["id"], CERT_OFFICER),
        "ERR_INVALID_CERTIFICATION_STATE", 409,
    )
    validate_error(
        api.reinstate_listing_certification(world["certification"]["id"], CERT_OFFICER),
        "ERR_INVALID_CERTIFICATION_STATE", 409,
    )

    suspended_cert = create_active_certification(
        api,
        cert_overrides={"file_number": "E55555", "initial_listing_date": "2026-01-01"},
        inspection_overrides={"inspection_date": "2026-02-01", "inspector_code": "INS-3"},
    )
    get_success_data(
        api.create_factory_inspection(
            suspended_cert["id"],
            create_factory_inspection_payload(
                inspection_date="2026-05-01", inspector_code="INS-4",
                findings_count=9, outcome="SUSPEND",
            ),
            CERT_OFFICER,
        )
    )
    validate_error(
        api.create_factory_inspection(
            suspended_cert["id"],
            create_factory_inspection_payload(
                inspection_date="2026-07-15", inspector_code="INS-5",
                findings_count=0, outcome="PASS",
            ),
            CERT_OFFICER,
        ),
        "ERR_INVALID_CERTIFICATION_STATE", 409,
    )

    validate_error(
        api.release_catalog_product(world["product"]["id"], ENGINEER),
        "ERR_INVALID_PRODUCT_STATE", 409,
    )


def test_order_and_lot_transitions_refuse_inadmissible_starting_states(api):
    """The order's pricing dimension and the lot's process dimension both refuse
    moves they do not offer from where they currently stand.

    PRD 3.5: "An order whose pricing dimension is already `LOCKED`, or that has
    reached `INVOICED`, is rejected with `ERR_INVALID_ORDER_STATE`."

    PRD 3.6: "Each report names the `step` that finished, one of `DRAWING`,
    `STRANDING` or `EXTRUSION`, and a step requested from a process or quality
    state that does not permit it is rejected with `ERR_INVALID_LOT_STATE`."

    Design: Corner/state_machines/invalid_from_states_on_order_and_lot_return_state_errors
    """
    world = setup_baseline(api)
    get_success_data(api.price_lock_customer_order(world["order"]["id"], BILLING))
    validate_error(
        api.price_lock_customer_order(world["order"]["id"], BILLING),
        "ERR_INVALID_ORDER_STATE", 409,
    )

    lot = create_lot(api, world, lot_code="LOT-STATE")
    validate_error(
        api.create_process_step(lot["id"], stranding_step_payload(), ENGINEER),
        "ERR_INVALID_LOT_STATE", 409,
    )
    validate_error(
        api.create_cable_test(lot["id"], spark_test_payload(), QE_TESTER),
        "ERR_INVALID_LOT_STATE", 409,
    )
    validate_error(
        api.disposition_production_lot(lot["id"], scrap_disposition_payload(), QE_DISPOSITIONER),
        "ERR_INVALID_LOT_STATE", 409,
    )
    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_RELEASER),
        "ERR_INVALID_LOT_STATE", 409,
    )

    advance_lot_to_extruded(api, lot["id"])
    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_RELEASER),
        "ERR_INVALID_LOT_STATE", 409,
    )
    assert read_lot(api, lot["id"])["process_state"] == "EXTRUDED", (
        "a refused release leaves the process dimension exactly where it was"
    )

    cancelled_order = get_success_data(
        api.cancel_customer_order(world["order"]["id"], BILLING)
    )
    assert cancelled_order["fulfillment_status"] == "CANCELLED"
    validate_error(
        api.cancel_customer_order(world["order"]["id"], BILLING),
        "ERR_INVALID_ORDER_STATE", 409,
    )


def test_a_reel_already_carrying_a_lot_refuses_a_second_load(api):
    """Loading is only offered on an AVAILABLE reel, so a reel that is already on
    iron with one lot cannot quietly take a second.

    PRD 3.8: "The reel must be `AVAILABLE`; loading a reel in any other status is
    rejected with `ERR_INVALID_REEL_STATE`."

    Design: Corner/state_machines/loading_a_second_lot_onto_an_occupied_reel_is_refused
    """
    world, lot_a, reel = setup_loaded_reel(api, planned_length_ft=2000)
    assert reel["status"] == "LOADED"
    assert reel["current_lot_id"] == lot_a["id"]

    world, lot_b = setup_released_lot(
        api, world=world, planned_length_ft=2000,
        lot_overrides={"lot_code": "LOT-B", "line_code": "EXT-2"},
    )
    refused = api.load_reel(
        reel["id"],
        {"lot_id": lot_b["id"], "load_length_ft": 2000,
         "occupancy_start_at": "2026-08-04T00:00:00Z"},
        CLERK,
    )
    validate_error(refused, "ERR_INVALID_REEL_STATE", 409)

    after = read_reel(api, reel["id"])
    assert after["current_lot_id"] == lot_a["id"], "the incumbent lot still owns the reel"
    assert after["loaded_length_ft"] == 2000, "no length was wound on by the refused load"
    assert after["version"] == reel["version"], "a refused load is inert"
    assert read_lot(api, lot_b["id"])["process_state"] == "TESTED", (
        "the second lot was never packaged"
    )


def test_loading_demands_a_lot_that_a_quality_engineer_has_already_released(api):
    """A reel only accepts iron a quality engineer has signed off, so a lot short of
    TESTED and CONFORMING is turned away.

    PRD 3.8: "The lot must have its process dimension at `TESTED` and its quality
    dimension at `CONFORMING` — that is, it must have been released by a quality
    engineer — and any other combination is rejected with `ERR_INVALID_LOT_STATE`."

    Design: Corner/state_machines/reel_load_requires_the_lot_to_be_released_conforming
    """
    world = setup_baseline(api)
    lot = create_lot(api, world, planned_length_ft=3000, lot_code="LOT-LOAD")
    reel = create_reel(api)

    advance_lot_to_extruded(api, lot["id"])
    validate_error(
        api.load_reel(
            reel["id"],
            {"lot_id": lot["id"], "load_length_ft": 3000,
             "occupancy_start_at": "2026-08-03T00:00:00Z"},
            CLERK,
        ),
        "ERR_INVALID_LOT_STATE", 409,
    )

    get_success_data(api.create_cable_test(lot["id"], spark_test_payload(), QE_TESTER))
    get_success_data(
        api.create_cable_test(
            lot["id"], {"test_type": "HIPOT", "test_voltage_kv": 2.5,
                        "breakdown_detected": False, "duration_sec": 300},
            QE_TESTER,
        )
    )
    staged_lot = read_lot(api, lot["id"])
    assert staged_lot["process_state"] == "TESTED"
    assert staged_lot["quality_state"] == "PENDING", (
        "the in-line pair promotes the process dimension but never the quality one"
    )
    validate_error(
        api.load_reel(
            reel["id"],
            {"lot_id": lot["id"], "load_length_ft": 3000,
             "occupancy_start_at": "2026-08-03T00:00:00Z"},
            CLERK,
        ),
        "ERR_INVALID_LOT_STATE", 409,
    )
    assert read_reel(api, reel["id"])["status"] == "AVAILABLE"

    release_lot(api, lot["id"], 3000)
    loaded = validate_success(
        api.load_reel(
            reel["id"],
            {"lot_id": lot["id"], "load_length_ft": 3000,
             "occupancy_start_at": "2026-08-03T00:00:00Z"},
            CLERK,
        ),
        200,
    )
    assert loaded["status"] == "LOADED"
    assert read_lot(api, lot["id"])["process_state"] == "PACKAGED"


def test_a_solid_conductor_skips_stranding_and_extrudes_straight_from_drawn(api):
    """The process dimension forks on construction: solid wire has no stranding
    operation at all, while a stranded construction may not skip it.

    PRD 3.6: "This is the branch point of the process dimension: a `SOLID`
    construction goes `DRAWN` → `EXTRUDED` directly and never enters `STRANDED`,
    and extrusion from `DRAWN` is admissible only for a `SOLID` construction,
    while extrusion from `STRANDED` is admissible for all the stranded and
    compressed constructions."

    Design: Corner/state_machines/solid_construction_lot_branches_from_drawn_straight_to_extruded
    """
    world = setup_definitions_and_rod(api, product_overrides=SOLID_SKU_OVERRIDES)
    solid_lot = create_lot(api, world, lot_code="LOT-SOLID", planned_length_ft=2000)
    drawn = advance_lot_to_drawn(api, solid_lot["id"])
    assert drawn["process_state"] == "DRAWN"

    validate_error(
        api.create_process_step(solid_lot["id"], stranding_step_payload(), ENGINEER),
        "ERR_INVALID_LOT_STATE", 409,
    )
    assert read_lot(api, solid_lot["id"])["process_state"] == "DRAWN"

    extruded = get_success_data(
        api.create_process_step(
            solid_lot["id"],
            {"step": "EXTRUSION", "measured_min_wall_mils": 25.5,
             "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
             "surface_marking_text": world["product"]["required_marking_text"]},
            ENGINEER,
        )
    )
    assert extruded["process_state"] == "EXTRUDED", (
        "a solid conductor reaches EXTRUDED straight from DRAWN"
    )

    stranded_product = create_released_product(
        api, world["insulation"]["id"], world["certification"]["id"],
        product_code="THHN-12-CU-S7",
    )
    stranded_world = dict(world, product=stranded_product)
    stranded_lot = create_lot(
        api, stranded_world, lot_code="LOT-S7", planned_length_ft=2000,
        line_code="EXT-9",
    )
    advance_lot_to_drawn(api, stranded_lot["id"])
    validate_error(
        api.create_process_step(
            stranded_lot["id"],
            {"step": "EXTRUSION", "measured_min_wall_mils": 25.5,
             "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
             "surface_marking_text": stranded_world["product"]["required_marking_text"]},
            ENGINEER,
        ),
        "ERR_INVALID_LOT_STATE", 409,
    )


def test_invoicing_settles_the_shipment_order_account_and_reel_in_one_request(api):
    """Invoicing is a fiscal event with four consequences, and all four are already
    settled by the time the response is written.

    PRD 3.9: "The shipment itself moves `STAGED` → `INVOICED` with `version`
    incremented by one."

    PRD 3.9: "And the reel leaves the `SHIPPED` state: a `WOOD_RETURNABLE` or
    `STEEL_RETURNABLE` reel moves `SHIPPED` → `RETURN_PENDING` and is now
    expected back, while a `NON_RETURNABLE` reel moves `SHIPPED` → `RETIRED` and
    leaves the fleet permanently."

    Design: Corner/state_machines/invoicing_a_shipment_fans_out_to_order_reel_and_customer_ledgers
    """
    world = setup_baseline(api)
    get_success_data(api.price_lock_customer_order(world["order"]["id"], BILLING))
    world, lot, reel, shipment = setup_staged_shipment(api, world=world)
    assert shipment["status"] == "STAGED"
    assert read_reel(api, reel["id"])["status"] == "SHIPPED"

    invoiced = validate_success(api.invoice_shipment(shipment["id"], BILLING), 200)
    assert invoiced["status"] == "INVOICED"
    assert invoiced["price_variant_applied"] == "ORDER_DATE_LOCK"
    assert invoiced["invoice_amount_usd"] == pytest.approx(544.58, abs=0.01), (
        "85.00 conversion plus 19.8 x (4.10 - 3.00) pass-through over 5.000 kft, "
        "with the two-percent surcharge on 533.90"
    )
    assert invoiced["invoice_date"] == "2026-08-01"

    order = read_order(api, world["order"]["id"])
    assert order["invoiced_total_usd"] == pytest.approx(544.58, abs=0.01)
    assert order["fulfillment_status"] == "FULFILLED"
    assert order["pricing_status"] == "INVOICED", (
        "the order was LOCKED, is now FULFILLED and has no uninvoiced shipment left"
    )

    customer = read_customer(api, world["customer"]["id"])
    assert customer["open_ar_usd"] == pytest.approx(544.58, abs=0.01)
    assert customer["reel_deposit_balance_usd"] == pytest.approx(450.00, abs=0.01)
    assert customer["credit_exposure_usd"] == pytest.approx(994.58, abs=0.01)
    assert customer["status"] == "ACTIVE"

    assert read_reel(api, reel["id"])["status"] == "RETURN_PENDING", (
        "a wood returnable reel is expected back once the delivery is billed"
    )
    assert read_lot(api, lot["id"])["process_state"] == "SHIPPED"


def test_a_second_invoice_on_the_same_delivery_is_refused_and_moves_no_money(api):
    """Invoicing is not idempotent-by-repetition: the second attempt is refused
    outright rather than billing the customer twice.

    PRD 3.9: "The shipment must be `STAGED`; invoicing one that has already
    reached `INVOICED` is rejected with `ERR_SHIPMENT_ALREADY_INVOICED`."

    Design: Corner/state_machines/second_invoice_on_the_same_shipment_changes_nothing
    """
    world = setup_baseline(api)
    get_success_data(api.price_lock_customer_order(world["order"]["id"], BILLING))
    world, lot, reel, shipment = setup_staged_shipment(api, world=world)
    first = validate_success(api.invoice_shipment(shipment["id"], BILLING), 200)

    order_before = read_order(api, world["order"]["id"])
    customer_before = read_customer(api, world["customer"]["id"])
    reel_before = read_reel(api, reel["id"])

    validate_error(
        api.invoice_shipment(shipment["id"], BILLING), "ERR_SHIPMENT_ALREADY_INVOICED", 409
    )

    assert read_shipment(api, shipment["id"])["version"] == first["version"], (
        "the refused second invoice does not touch the shipment"
    )
    assert read_order(api, world["order"]["id"]) == order_before, (
        "the order's invoiced total is not double counted"
    )
    assert read_customer(api, world["customer"]["id"]) == customer_before, (
        "the account's AR is not double counted"
    )
    assert read_reel(api, reel["id"]) == reel_before, (
        "the reel does not advance twice out of SHIPPED"
    )


def test_a_cancelled_order_and_its_closed_lot_refuse_every_further_operation(api):
    """Cancellation is terminal on the fulfillment dimension and closes its queued
    lots, and nothing downstream may be worked afterwards.

    PRD 3.5: "Every production lot belonging to the cancelled order whose process
    dimension is `QUEUED`, processed in ascending `created_at` order, has its
    process dimension set to `SCRAP_CLOSED` while its quality dimension is left
    at `PENDING` — nothing was ever produced, so nothing is scrapped — and its
    `version` incremented by one."

    Design: Corner/state_machines/cancelled_order_and_its_scrap_closed_lot_refuse_all_further_work
    """
    world, lot, order = setup_cancelled_order(api, planned_length_ft=4000)
    assert order["fulfillment_status"] == "CANCELLED"
    assert lot["process_state"] == "SCRAP_CLOSED"
    assert lot["quality_state"] == "PENDING"

    validate_error(
        api.create_process_step(lot["id"], {"step": "DRAWING"}, ENGINEER),
        "ERR_INVALID_LOT_STATE", 409,
    )
    validate_error(
        api.create_cable_test(lot["id"], spark_test_payload(), QE_TESTER),
        "ERR_INVALID_LOT_STATE", 409,
    )
    validate_error(
        api.disposition_production_lot(
            lot["id"], scrap_disposition_payload(), QE_DISPOSITIONER
        ),
        "ERR_INVALID_LOT_STATE", 409,
    )
    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 4000}, QE_RELEASER),
        "ERR_INVALID_LOT_STATE", 409,
    )
    validate_error(
        api.cancel_customer_order(world["order"]["id"], BILLING),
        "ERR_INVALID_ORDER_STATE", 409,
    )
    validate_error(
        api.price_lock_customer_order(world["order"]["id"], BILLING),
        "ERR_INVALID_ORDER_STATE", 409,
    )

    final_lot = read_lot(api, lot["id"])
    assert final_lot["version"] == lot["version"], (
        "every refused operation leaves the closed lot byte-for-byte where it was"
    )

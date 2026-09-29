"""Writes that fail because of the state of some other record entirely.

A quality engineer's release is refused because an agency file two hops away is
no longer `ACTIVE`, even though nothing on the lot has changed. A SKU release is
refused first because its formulation is not qualified and then, once it is,
because that same formulation's voltage ceiling does not cover the print. And a
shipment is refused twice over by an account whose standing is derived from its
own ledger rather than set by any workflow.
"""

from test_helpers import (
    BILLING,
    CERT_OFFICER,
    CLERK,
    ENGINEER,
    QE_RELEASER,
    QE_RELEASER_USER_ID,
    advance_lot_to_tested,
    assert_credit_exposure_identity,
    assert_money,
    assert_order_dimensions,
    create_active_certification,
    create_draft_product,
    create_factory_inspection_payload,
    create_insulation_compound_payload,
    create_jacket_compound_payload,
    create_lot,
    create_qualified_compound,
    create_reel,
    create_shipment_payload,
    current_order_version,
    get_success_data,
    load_reel_payload,
    lower_credit_limit,
    read_certification,
    read_compound,
    read_customer,
    read_lot,
    read_order,
    read_product,
    read_reel,
    read_shipment,
    release_lot,
    set_clock,
    setup_baseline,
    validate_error,
    validate_success,
)

VARIATION_VISIT = {
    "inspection_date": "2026-08-10",
    "inspector_code": "INS-9",
    "findings_count": 2,
    "outcome": "VARIATION",
}
SECOND_LINE_WINDOW = {
    "line_code": "EXT-2",
    "scheduled_start_at": "2026-08-02T08:00:00Z",
    "scheduled_end_at": "2026-08-02T12:00:00Z",
}
MV_SKU_ON_A_600V_COMPOUND = {
    "product_code": "MV105-2-BADCMP",
    "awg_size": "2",
    "conductor_construction": "COMPRESSED_37",
    "application_rating": "MV_105",
    "voltage_class": "MV_15KV",
    "temp_rating_c": 90,
    "insulation_thickness_mils": 175.0,
    "conductor_lbs_per_kft": 205.0,
    "base_target_kft": 20.0,
}


def _lot_awaiting_release(api):
    world = setup_baseline(
        api, order_overrides={"order_number": "SO-CERT", "ordered_kft": 5.000}
    )
    lot = create_lot(api, world, lot_code="LOT-CERT", planned_length_ft=5000)
    advance_lot_to_tested(api, lot["id"])
    return world, read_lot(api, lot["id"])


def _draft_sku_pair(api):
    """A DRAFT LV SKU and a DRAFT MV SKU sharing one unqualified 600 V insulation."""
    set_clock(api)
    insulation = get_success_data(
        api.create_compound(create_insulation_compound_payload(), ENGINEER)
    )
    jacket = create_qualified_compound(api, create_jacket_compound_payload())
    certification = create_active_certification(api)
    lv_sku = create_draft_product(
        api, insulation["id"], certification["id"], jacket_compound_id=jacket["id"]
    )
    mv_sku = create_draft_product(
        api, insulation["id"], certification["id"], jacket_compound_id=jacket["id"],
        **MV_SKU_ON_A_600V_COMPOUND,
    )
    return insulation, jacket, lv_sku, mv_sku


def _credit_world(api):
    """One invoiced shipment on the account plus a second reel loaded and ready."""
    world = setup_baseline(
        api,
        order_overrides={"order_number": "SO-CRD", "ordered_kft": 10.000},
        rod_overrides={"purchase_weight_lbs": 20000.00},
    )
    order = world["order"]
    get_success_data(api.price_lock_customer_order(order["id"], BILLING))

    staged = []
    for lot_code, serial, overrides in (
        ("LOT-CRD-A", "R-CRD-A", {}), ("LOT-CRD-B", "R-CRD-B", SECOND_LINE_WINDOW),
    ):
        lot = create_lot(
            api, world, lot_code=lot_code, planned_length_ft=5000, **overrides
        )
        advance_lot_to_tested(api, lot["id"])
        release_lot(api, lot["id"], 5000)
        reel = create_reel(api, reel_serial=serial)
        get_success_data(
            api.load_reel(
                reel["id"],
                load_reel_payload(lot["id"], 5000,
                                  occupancy_start_at="2026-08-03T00:00:00Z"),
                CLERK,
            )
        )
        staged.append((lot, reel))

    first_lot, first_reel = staged[0]
    shipment = validate_success(
        api.create_shipment(
            create_shipment_payload(
                order["id"], first_lot["id"], first_reel["id"], 5000,
                current_order_version(api, order["id"]), ship_date="2026-08-05",
            ),
            CLERK,
        ),
        201,
    )
    get_success_data(api.invoice_shipment(shipment["id"], BILLING))
    return world, order, staged[1]


def _stage_second(api, order, lot, reel, order_version):
    return api.create_shipment(
        create_shipment_payload(
            order["id"], lot["id"], reel["id"], 5000, order_version,
            ship_date="2026-08-06",
        ),
        CLERK,
    )


def test_a_variation_notice_two_hops_away_refuses_an_untouched_lot(api):
    """The agency file moves to `VARIATION_NOTICE` and fires no cascade at all, so the
    SKU stays `RELEASED` and the lot is byte-for-byte what it was — and its release
    is refused anyway, purely on the state of the file.

    PRD 3.7: "The **listing** gate finally requires the SKU's listing file to be
    `ACTIVE`, refusing with `ERR_CERTIFICATION_NOT_ACTIVE` when the file is
    `PENDING`, at `VARIATION_NOTICE`, or `SUSPENDED`."

    PRD 3.3: "A `VARIATION` recorded on an `ACTIVE` file moves it `ACTIVE` →
    `VARIATION_NOTICE`; products stay `RELEASED` under a variation notice, because
    only a suspension freezes the downstream chain."

    PRD 2.11: "Checks are evaluated in the following order, and the first failure ends
    the request with no persisted effect whatsoever:"

    Design: Difficulty/cross_entity_state_dependency/lot_release_depends_on_listing_certification_status
    """
    world, lot = _lot_awaiting_release(api)

    get_success_data(
        api.create_factory_inspection(
            world["certification"]["id"],
            create_factory_inspection_payload(**VARIATION_VISIT),
            CERT_OFFICER,
        )
    )

    certification = read_certification(api, world["certification"]["id"])
    assert certification["status"] == "VARIATION_NOTICE"
    assert certification["open_variation_count"] == 1
    assert read_product(api, world["product"]["id"])["status"] == "RELEASED", (
        "a variation notice freezes nothing downstream"
    )
    unchanged = read_lot(api, lot["id"])
    assert unchanged["version"] == lot["version"], (
        "the gated lot was not touched by the inspection at all"
    )
    assert unchanged["process_state"] == "TESTED"
    assert unchanged["quality_state"] == "PENDING"

    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_RELEASER),
        "ERR_CERTIFICATION_NOT_ACTIVE", 422,
    )

    refused = read_lot(api, lot["id"])
    assert refused["released_by_user_id"] is None, "the refused release signed nothing"
    assert refused["packaged_length_ft"] == 0, "and certified no length"
    assert refused["version"] == lot["version"], "and left no other trace"


def test_reinstating_the_file_lets_the_identical_release_succeed(api):
    """Nothing about the lot or the request changes: returning the other entity to
    `ACTIVE` is the whole difference between a refusal and a release.

    PRD 3.3: "When the condition holds, every `OPEN` row on the file, processed in
    ascending `created_at` order, moves `OPEN` → `CLOSED` with its own `version`
    incremented by one; `open_variation_count` is reset to 0; and the file's `status`
    becomes `ACTIVE` with `version` incremented by one."

    PRD 3.7: "A lot that clears all six has `released_by_user_id` set from
    `X-User-ID` and `packaged_length_ft` set from the payload, and its quality
    dimension moves `PENDING` → `CONFORMING` while its process dimension deliberately
    stays at `TESTED` — packaging has been authorised, not performed."

    Design: Difficulty/cross_entity_state_dependency/lot_release_depends_on_listing_certification_status
    """
    world, lot = _lot_awaiting_release(api)
    get_success_data(
        api.create_factory_inspection(
            world["certification"]["id"],
            create_factory_inspection_payload(**VARIATION_VISIT),
            CERT_OFFICER,
        )
    )
    validate_error(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_RELEASER),
        "ERR_CERTIFICATION_NOT_ACTIVE", 422,
    )

    reinstated = get_success_data(
        api.reinstate_listing_certification(world["certification"]["id"], CERT_OFFICER)
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["open_variation_count"] == 0

    released = validate_success(
        api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, QE_RELEASER),
        200,
    )
    assert released["quality_state"] == "CONFORMING"
    assert released["process_state"] == "TESTED", "packaging is authorised, not done"
    assert released["released_by_user_id"] == QE_RELEASER_USER_ID
    assert released["packaged_length_ft"] == 5000


def test_a_sku_cannot_be_released_against_an_unqualified_formulation(api):
    """The SKU is perfect and the formulation is merely still a draft, so the release
    is refused with `ERR_COMPOUND_NOT_QUALIFIED`; qualifying the other entity makes
    the same request succeed, and the SKU then records the revision it was cleared
    against.

    PRD 3.4: "First, both formulations must be qualified: the insulation formulation
    must be `QUALIFIED`, and when a jacket formulation is named it must be
    `QUALIFIED` too, otherwise release is refused with
    `ERR_COMPOUND_NOT_QUALIFIED`."

    PRD 3.4: "A successful release pins the formulation versions the SKU was approved
    against: `pinned_insulation_compound_version` takes the current `version` of the
    insulation formulation, and `pinned_jacket_compound_version` takes the current
    `version` of the jacket formulation when one is named and otherwise stays null."

    PRD 3.2: "Qualification is what makes a formulation usable."

    Design: Difficulty/cross_entity_state_dependency/product_release_depends_on_compound_status_and_rating
    """
    insulation, jacket, lv_sku, _ = _draft_sku_pair(api)
    assert insulation["status"] == "DRAFT"
    assert jacket["status"] == "QUALIFIED"

    validate_error(
        api.release_catalog_product(lv_sku["id"], ENGINEER),
        "ERR_COMPOUND_NOT_QUALIFIED", 422,
    )
    refused = read_product(api, lv_sku["id"])
    assert refused["status"] == "DRAFT", "the refused release left the SKU alone"
    assert refused["pinned_insulation_compound_version"] is None

    qualified = get_success_data(api.qualify_compound(insulation["id"], ENGINEER))
    assert qualified["status"] == "QUALIFIED"
    assert qualified["qualification_date"] == "2026-08-01", (
        "qualification stamps the current logical date"
    )

    released = validate_success(api.release_catalog_product(lv_sku["id"], ENGINEER), 200)
    assert released["status"] == "RELEASED"
    assert released["pinned_insulation_compound_version"] == qualified["version"], (
        "the SKU remembers exactly which revision it was cleared against"
    )
    assert released["pinned_jacket_compound_version"] == (
        read_compound(api, jacket["id"])["version"]
    )


def test_a_qualified_formulation_that_does_not_cover_the_print_still_refuses(api):
    """The same formulation, now qualified, releases the 600 volt SKU and still refuses
    the 15 kV one — a separate error id for a separate clause of the same
    dependency.

    PRD 3.4: "Second, the insulation formulation must actually cover the claims on the
    print: its `temp_rating_c` must be at least the SKU's `temp_rating_c`, its
    `max_voltage_v` must be at least the SKU's `voltage_rating_v`, and when the SKU's
    `application_rating` is either `THHN` or `THWN_2` the formulation's `flame_test`
    must be exactly `VW_1`. Any of those three failing refuses the release with
    `ERR_COMPOUND_RATING_INSUFFICIENT`."

    PRD 3.4: "`voltage_rating_v` is taken from the voltage class: 600 volts for
    `LV_600`, 5000 volts for `MV_5KV`, 15000 volts for `MV_15KV` and 35000 volts for
    `MV_35KV`."

    Design: Difficulty/cross_entity_state_dependency/product_release_depends_on_compound_status_and_rating
    """
    insulation, _, lv_sku, mv_sku = _draft_sku_pair(api)
    get_success_data(api.qualify_compound(insulation["id"], ENGINEER))
    validate_success(api.release_catalog_product(lv_sku["id"], ENGINEER), 200)

    assert read_product(api, mv_sku["id"])["voltage_rating_v"] == 15000
    assert read_compound(api, insulation["id"])["max_voltage_v"] == 600

    validate_error(
        api.release_catalog_product(mv_sku["id"], ENGINEER),
        "ERR_COMPOUND_RATING_INSUFFICIENT", 422,
    )
    refused = read_product(api, mv_sku["id"])
    assert refused["status"] == "DRAFT", (
        "the rating clause is evaluated independently of the qualification clause"
    )
    assert refused["pinned_insulation_compound_version"] is None
    assert read_product(api, lv_sku["id"])["status"] == "RELEASED", (
        "one formulation row gates two SKUs and only one of them clears it"
    )


def test_an_account_pushed_onto_credit_hold_refuses_a_perfect_shipment(api):
    """Lowering the limit under an untouched ledger is enough to flip the account's
    standing, and the shipment is refused at 402 while the lot and the reel it names
    stay exactly where they were.

    PRD 3.8: "Finally credit is checked: the shipping account's `status` must be
    `ACTIVE`, and its `credit_exposure_usd` plus the reel's `deposit_usd` must not
    exceed its `credit_limit_usd`. An account already on `CREDIT_HOLD`, or one that
    the new deposit would push past its limit, is refused with
    `ERR_CREDIT_LIMIT_EXCEEDED` at HTTP 402."

    PRD 2.9: "Both are tracked as running ledger fields on the account rather than
    recomputed from scratch on read, and both are refreshed inside the same request as
    the event that changed them."

    Design: Difficulty/cross_entity_state_dependency/shipment_creation_depends_on_customer_credit_standing
    """
    world, order, (lot, reel) = _credit_world(api)

    baseline = read_customer(api, world["customer"]["id"])
    assert_money(baseline["open_ar_usd"], 544.58, "one invoiced shipment")
    assert_money(baseline["reel_deposit_balance_usd"], 450.00, "one reel out")
    assert_money(baseline["credit_memo_balance_usd"], 0.00, "nothing refunded yet")
    assert_money(baseline["credit_exposure_usd"], 994.58, "544.58 plus 450.00")
    assert baseline["status"] == "ACTIVE"
    assert_credit_exposure_identity(baseline)

    on_hold = lower_credit_limit(api, world["customer"]["id"], 900.00)
    assert on_hold["status"] == "CREDIT_HOLD", "994.58 is more than a 900.00 limit"
    assert_money(on_hold["credit_exposure_usd"], 994.58, "the ledger did not move")

    order_version = current_order_version(api, order["id"])
    validate_error(
        _stage_second(api, order, lot, reel, order_version),
        "ERR_CREDIT_LIMIT_EXCEEDED", 402,
    )

    assert read_lot(api, lot["id"])["process_state"] == "PACKAGED", (
        "the gated lot was never the problem"
    )
    assert read_reel(api, reel["id"])["status"] == "LOADED"
    assert current_order_version(api, order["id"]) == order_version, (
        "the refused staging applied no side effects, so the order did not move"
    )


def test_an_active_account_with_too_little_headroom_still_refuses(api):
    """Restoring the account to `ACTIVE` is not enough: the amount clause fails on its
    own because the exposure plus the new deposit would clear the limit. Raising the
    limit properly lets the byte-identical request through.

    PRD 3.8: "Finally credit is checked: the shipping account's `status` must be
    `ACTIVE`, and its `credit_exposure_usd` plus the reel's `deposit_usd` must not
    exceed its `credit_limit_usd`."

    PRD 3.8: "The holding account's `deposit_charged_total_usd` and
    `reel_deposit_balance_usd` are each increased by the reel's `deposit_usd`, after
    which `credit_exposure_usd` is recomputed and the account's standing
    re-evaluated."

    PRD 3.8: "`shipped_kft` is increased by `shipped_length_ft` divided by 1000, and
    the fulfillment dimension advances `OPEN` → `PARTIALLY_SHIPPED` when the resulting
    total is strictly below `ordered_kft`, `OPEN` → `FULFILLED` when the resulting
    total equals `ordered_kft` exactly, and `PARTIALLY_SHIPPED` → `FULFILLED` when the
    resulting total equals `ordered_kft` exactly."

    Design: Difficulty/cross_entity_state_dependency/shipment_creation_depends_on_customer_credit_standing
    """
    world, order, (lot, reel) = _credit_world(api)
    lower_credit_limit(api, world["customer"]["id"], 900.00)
    order_version = current_order_version(api, order["id"])
    validate_error(
        _stage_second(api, order, lot, reel, order_version),
        "ERR_CREDIT_LIMIT_EXCEEDED", 402,
    )

    restored = lower_credit_limit(api, world["customer"]["id"], 1400.00)
    assert restored["status"] == "ACTIVE", "994.58 is within a 1400.00 limit"
    validate_error(
        _stage_second(api, order, lot, reel, order_version),
        "ERR_CREDIT_LIMIT_EXCEEDED", 402,
    )

    lower_credit_limit(api, world["customer"]["id"], 100000.00)
    shipment = validate_success(
        _stage_second(api, order, lot, reel, order_version), 201
    )

    assert read_shipment(api, shipment["id"])["status"] == "STAGED"
    assert read_reel(api, reel["id"])["status"] == "SHIPPED"
    settled = read_customer(api, world["customer"]["id"])
    assert_money(settled["reel_deposit_balance_usd"], 900.00, "two reels out")
    assert_money(settled["deposit_charged_total_usd"], 900.00, "two deposits charged")
    assert_money(settled["credit_exposure_usd"], 1444.58, "994.58 plus 450.00")
    assert settled["status"] == "ACTIVE"
    assert_order_dimensions(read_order(api, order["id"]), "LOCKED", "FULFILLED")

"""Failure surfaces: distinct conflict identities, one shared error envelope, and
the role model's four separate boundaries.

The seven staff roles are peers rather than a ladder, the eighth role is scoped to
its own account, and the duty split inside the quality role is keyed on the acting
individual rather than on the role — so authorisation is four rules, not one.
"""

import pytest

from test_helpers import (
    ADMIN,
    BILLING,
    BUYER,
    CERT_OFFICER,
    CLERK,
    ENGINEER,
    NO_AUTH_HEADERS,
    QE_TESTER,
    SENTINEL_UUID,
    THHN_12_CU_MARKING,
    advance_lot_to_extruded,
    assert_error_envelope_only_carries_error_fields,
    create_catalog_product_payload,
    create_customer,
    create_insulation_compound_payload,
    create_listing_certification_payload,
    create_lot,
    create_metal_price_quote_payload,
    create_order,
    create_reel_payload,
    get_success_data,
    make_customer_headers,
    make_plant_admin_headers,
    make_quality_engineer_headers,
    read_lot,
    set_clock,
    setup_certification_with_lapsed_variation,
    setup_definitions_and_rod,
    setup_lv_catalog,
    setup_staged_shipment,
    validate_error,
    validate_paginated,
    validate_success,
)

ALUMINUM_TWIN = {
    "product_code": "XHHW-8-AL",
    "awg_size": "8",
    "conductor_metal": "ALUMINUM",
    "application_rating": "XHHW_2",
    "insulation_thickness_mils": 45.0,
    "conductor_lbs_per_kft": 30.0,
    "base_target_kft": 50.0,
}


def test_two_uniqueness_keys_on_one_rung_answer_with_two_different_ids(api):
    """One rejection rung carries a composite key and a single-column key, and each
    must name its own conflict; the refusal never overwrites the incumbent.

    PRD 3.1: "The combination of `metal` and `effective_date` may appear only
    once; a second attempt at the same pair is rejected with
    `ERR_DUPLICATE_METAL_QUOTE`."

    PRD 3.4: "The definition carries a `product_code` that must be unique across
    the catalog — a repeat is rejected with `ERR_DUPLICATE_PRODUCT_CODE`"

    Design: Corner/errors/duplicate_keys_return_rule_specific_conflict_ids
    """
    world = setup_lv_catalog(api)

    validate_error(
        api.create_metal_price_quote(
            create_metal_price_quote_payload(
                metal="COPPER", effective_date="2026-07-30",
                settlement_price_usd_per_lb=4.25,
            ),
            BUYER,
        ),
        "ERR_DUPLICATE_METAL_QUOTE", 409,
    )
    rows, meta = validate_paginated(
        api.list_metal_price_quotes(BUYER, params={"metal": "COPPER"})
    )
    assert meta["total_count"] == 1
    assert rows[0]["settlement_price_usd_per_lb"] == pytest.approx(4.10, abs=0.005), (
        "a settlement price is immutable, so a conflicting post is a conflict, "
        "not an update"
    )

    validate_success(
        api.create_metal_price_quote(
            create_metal_price_quote_payload(
                metal="ALUMINUM", effective_date="2026-07-30",
                settlement_price_usd_per_lb=1.20, source="LME",
            ),
            BUYER,
        ),
        201,
    )

    validate_error(
        api.create_catalog_product(
            create_catalog_product_payload(
                world["insulation"]["id"], world["certification"]["id"],
                **dict(ALUMINUM_TWIN, product_code="THHN-12-CU"),
            ),
            ENGINEER,
        ),
        "ERR_DUPLICATE_PRODUCT_CODE", 409,
    )
    validate_success(
        api.create_catalog_product(
            create_catalog_product_payload(
                world["insulation"]["id"], world["certification"]["id"], **ALUMINUM_TWIN
            ),
            ENGINEER,
        ),
        201,
    )
    rows, meta = validate_paginated(api.list_catalog_products(ENGINEER))
    assert meta["total_count"] == 2, "exactly one SKU survived the two attempts"


def test_reinstatement_reads_the_logical_clock_and_not_the_inspection_row(api):
    """The corrective deadline is compared against the logical date, so the same file
    and the same inspection row flip from refused to accepted when the clock moves.

    PRD 3.3: "The agency's condition for reinstatement is that no corrective action
    has gone past its deadline: if any `OPEN` inspection row on the file carries a
    `corrective_action_due_date` earlier than the current logical date, the 30-day
    corrective action window has lapsed and the agency requires a fresh inspection
    rather than a reinstatement, so the request is rejected with
    `ERR_OPEN_VARIATION_UNRESOLVED`."

    PRD 3.3: "Reinstatement returns a file to service and is available from either
    `VARIATION_NOTICE` or `SUSPENDED`; attempting it on a file that is already
    `ACTIVE` or that is still `PENDING` is rejected with
    `ERR_INVALID_CERTIFICATION_STATE`."

    Design: Corner/errors/reinstatement_is_refused_while_a_lapsed_corrective_action_stands
    """
    cert, inspections = setup_certification_with_lapsed_variation(api)
    assert cert["status"] == "VARIATION_NOTICE"
    assert inspections["variation"]["corrective_action_due_date"] == "2026-07-01", (
        "a variation row's deadline is its inspection date advanced by 30 days"
    )
    assert inspections["variation"]["status"] == "OPEN"
    assert inspections["passing"]["status"] == "CLOSED", "a pass is born closed"

    validate_error(
        api.reinstate_listing_certification(cert["id"], CERT_OFFICER),
        "ERR_OPEN_VARIATION_UNRESOLVED", 409,
    )
    refused = get_success_data(api.get_listing_certification(cert["id"], ENGINEER))
    assert refused["status"] == "VARIATION_NOTICE"
    assert refused["open_variation_count"] == 1
    assert refused["version"] == cert["version"], "the refusal burned no version"

    set_clock(api, "2026-06-15T00:00:00Z")
    reinstated = validate_success(
        api.reinstate_listing_certification(cert["id"], CERT_OFFICER), 200
    )
    assert reinstated["status"] == "ACTIVE", (
        "nothing about the inspection row changed, only the logical date"
    )
    assert reinstated["open_variation_count"] == 0

    rows, meta = validate_paginated(
        api.list_factory_inspections(cert["id"], CERT_OFFICER)
    )
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows] == ["CLOSED", "CLOSED"], (
        "reinstatement closed every open row on the file"
    )

    validate_error(
        api.reinstate_listing_certification(cert["id"], CERT_OFFICER),
        "ERR_INVALID_CERTIFICATION_STATE", 409,
    )


def test_five_failure_classes_share_one_envelope_and_persist_nothing(api):
    """401, 403, 400, 404 and 409 all come back in the same shape, none of them leaks
    a partially built record, and none of them leaves a trace.

    PRD 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/errors/every_error_class_shares_one_envelope_and_writes_nothing
    """
    set_clock(api)
    get_success_data(
        api.create_metal_price_quote(create_metal_price_quote_payload(), BUYER)
    )
    customer = create_customer(api)

    failures = [
        (api.get_customer(customer["id"], NO_AUTH_HEADERS),
         "ERR_UNAUTHENTICATED", 401),
        (api.create_metal_price_quote(
            create_metal_price_quote_payload(
                effective_date="2026-07-31", settlement_price_usd_per_lb=4.20
            ),
            BILLING,
        ), "ERR_UNAUTHORIZED", 403),
        (api.list_metal_price_quotes(BILLING, params={"metal": "COPPER", "limit": 500}),
         "ERR_INVALID_REQUEST", 400),
        (api.get_customer(SENTINEL_UUID, BILLING), "ERR_CUSTOMER_NOT_FOUND", 404),
        (api.create_metal_price_quote(
            create_metal_price_quote_payload(settlement_price_usd_per_lb=4.30), BUYER
        ), "ERR_DUPLICATE_METAL_QUOTE", 409),
    ]
    for response, expected_id, expected_status in failures:
        error = validate_error(response, expected_id, expected_status)
        assert_error_envelope_only_carries_error_fields(response.json())
        assert "id" not in error and "version" not in error, (
            f"{expected_id} must not leak a partially built entity"
        )

    rows, meta = validate_paginated(api.list_metal_price_quotes(BUYER))
    assert meta["total_count"] == 1, "neither the 403 nor the 409 attempt was persisted"
    assert rows[0]["settlement_price_usd_per_lb"] == pytest.approx(4.10, abs=0.005)


def test_each_staff_roles_exclusive_operations_are_closed_to_its_peers(api):
    """Twelve operations attempted by the wrong peer role, eight of them naming an
    identifier that does not exist, and every single answer is the same 403.

    PRD 2.1: "A request whose `X-User-Role` is not among the roles listed for the
    endpoint being called is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 2.11: "Role authorization, including a `Customer`'s ownership scope —
    `ERR_UNAUTHORIZED`."

    PRD 2.1: "A **`PlantAdmin`** is the plant systems administrator; the role
    holds every operation in the service for setup and recovery purposes, and is
    the only role permitted to move the logical clock."

    Design: Corner/rbac/peer_roles_cannot_reach_each_others_exclusive_operations
    """
    set_clock(api)
    denials = [
        api.create_metal_price_quote(create_metal_price_quote_payload(), BILLING),
        api.create_compound(create_insulation_compound_payload(), BUYER),
        api.create_listing_certification(create_listing_certification_payload(), ENGINEER),
        api.release_catalog_product(SENTINEL_UUID, QE_TESTER),
        api.create_cable_test(
            SENTINEL_UUID,
            {"test_type": "SPARK", "duration_sec": 60, "faults_detected": 0},
            ENGINEER,
        ),
        api.create_process_step(SENTINEL_UUID, {"step": "DRAWING"}, QE_TESTER),
        api.create_reel(create_reel_payload(), CERT_OFFICER),
        api.load_reel(
            SENTINEL_UUID,
            {"lot_id": SENTINEL_UUID, "load_length_ft": 5000,
             "occupancy_start_at": "2026-08-01T00:00:00Z"},
            BILLING,
        ),
        api.invoice_shipment(SENTINEL_UUID, CLERK),
        api.patch_customer(SENTINEL_UUID, {"credit_limit_usd": 1.00}, CLERK),
        api.cancel_customer_order(SENTINEL_UUID, ENGINEER, {"reason": "not my job"}),
        api.set_current_utc("2026-09-01T00:00:00Z", ENGINEER),
    ]
    for response in denials:
        validate_error(response, "ERR_UNAUTHORIZED", 403)

    stamped = get_success_data(
        api.create_metal_price_quote(create_metal_price_quote_payload(), BUYER)
    )
    assert stamped["created_at"].startswith("2026-08-01"), (
        "the refused clock move never happened, so records are still stamped at the "
        "epoch the plant started from"
    )

    rows, meta = validate_paginated(api.list_catalog_products(CLERK))
    assert meta["total_count"] == 0, (
        "a shared read still answers for the same peer that was just refused a write"
    )


def test_every_engineer_who_tested_the_lot_is_barred_from_releasing_it(api):
    """The duty split scans every test operator on the lot rather than the latest one,
    and the plant admin role does not exempt the acting individual.

    PRD 3.7: "The **segregation-of-duties** gate requires the releasing
    `X-User-ID` to differ from every `operator_user_id` recorded on the lot's test
    rows; a quality engineer who ran any of the tests may not sign off the lot, and
    the attempt is refused with `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."

    PRD 2.1: "Segregation of duties is enforced within the `QualityEngineer` role
    rather than between roles."

    Design: Corner/rbac/segregation_of_duties_blocks_every_tester_of_the_lot_from_releasing_it
    """
    world = setup_definitions_and_rod(api)
    lot = create_lot(api, world, lot_code="LOT-A", planned_length_ft=5000)
    advance_lot_to_extruded(api, lot["id"])
    spark_operator = make_quality_engineer_headers("qe-001")
    hipot_operator = make_quality_engineer_headers("qe-002")
    get_success_data(
        api.create_cable_test(
            lot["id"], {"test_type": "SPARK", "faults_detected": 0, "duration_sec": 60},
            spark_operator,
        )
    )
    get_success_data(
        api.create_cable_test(
            lot["id"], {"test_type": "HIPOT", "test_voltage_kv": 2.5,
                        "breakdown_detected": False, "duration_sec": 300},
            hipot_operator,
        )
    )
    assert read_lot(api, lot["id"])["process_state"] == "TESTED"

    for barred in (spark_operator, hipot_operator, make_plant_admin_headers("qe-001")):
        validate_error(
            api.release_production_lot(lot["id"], {"packaged_length_ft": 5000}, barred),
            "ERR_SEGREGATION_OF_DUTIES", 403,
        )
    inert = read_lot(api, lot["id"])
    assert inert["quality_state"] == "PENDING", "all three refusals were inert"
    assert inert["packaged_length_ft"] == 0

    released = validate_success(
        api.release_production_lot(
            lot["id"], {"packaged_length_ft": 5000},
            make_quality_engineer_headers("qe-003"),
        ),
        200,
    )
    assert released["quality_state"] == "CONFORMING"
    assert released["packaged_length_ft"] == 5000
    assert released["process_state"] == "TESTED", (
        "release authorises packaging, it does not perform it"
    )


def test_a_customer_sees_its_own_account_orders_and_shipments_and_nothing_else(api):
    """The one entity-backed role: the same list endpoint answers differently for two
    callers, and a cross-account read is refused rather than reported missing.

    PRD 2.1: "Concretely, a `Customer` may read only the account whose `id` equals
    `X-User-ID`, only orders whose `customer_id` equals `X-User-ID`, and only
    shipments whose order belongs to that account."

    PRD 2.1: "Reaching an account, order, shipment or reel that belongs to a
    different account is rejected with `ERR_UNAUTHORIZED`, and this ownership check
    is applied with the same 403 status as the plain role check."

    Design: Corner/rbac/customer_role_is_scoped_to_its_own_account_orders_and_shipments
    """
    world, lot, reel, shipment = setup_staged_shipment(
        api, order_overrides={"order_number": "SO-A"}
    )
    acme = world["customer"]
    beta = create_customer(api, account_code="BETA", name="Beta Contractors")
    order_b = create_order(api, beta["id"], world["product"]["id"], order_number="SO-B")
    as_acme = make_customer_headers(acme["id"])
    as_beta = make_customer_headers(beta["id"])

    own = validate_success(api.get_customer(acme["id"], as_acme), 200)
    assert own["account_code"] == "ACME"
    validate_error(
        api.get_customer(beta["id"], as_acme), "ERR_UNAUTHORIZED", 403
    )

    rows, meta = validate_paginated(api.list_customer_orders(as_acme))
    assert [row["order_number"] for row in rows] == ["SO-A"]
    assert meta["total_count"] == 1, (
        "the collection is scoped to the caller even though two orders exist"
    )
    validate_error(
        api.get_customer_order(order_b["id"], as_acme), "ERR_UNAUTHORIZED", 403
    )

    rows, meta = validate_paginated(api.list_shipments(as_beta))
    assert meta["total_count"] == 0, "the only shipment belongs to the other account"
    validate_error(
        api.get_shipment(shipment["id"], as_beta), "ERR_UNAUTHORIZED", 403
    )
    mine = validate_success(api.get_shipment(shipment["id"], as_acme), 200)
    assert mine["shipped_length_ft"] == 5000, (
        "a shipment carries no account reference, so the scope resolves through "
        "its order"
    )

    validate_error(
        api.create_customer_order(
            {"customer_id": acme["id"], "product_id": world["product"]["id"],
             "order_number": "SO-SELF", "ordered_kft": 1.0,
             "price_basis": "ORDER_DATE_LOCK", "conversion_price_usd_per_kft": 85.0,
             "order_date": "2026-07-30"},
            as_acme,
        ),
        "ERR_UNAUTHORIZED", 403,
    )
    validate_error(
        api.get_production_lot(lot["id"], as_acme), "ERR_UNAUTHORIZED", 403
    )


def test_the_plant_admin_drives_the_whole_chain_yet_cannot_sign_off_its_own_tests(api):
    """One role runs order to invoice single-handed, which proves the blanket
    authorisation is real — and is then refused a release on a lot it tested itself.

    PRD 2.1: "A **`PlantAdmin`** is the plant systems administrator; the role
    holds every operation in the service for setup and recovery purposes, and is
    the only role permitted to move the logical clock."

    PRD 3.7: "The **segregation-of-duties** gate requires the releasing
    `X-User-ID` to differ from every `operator_user_id` recorded on the lot's test
    rows; a quality engineer who ran any of the tests may not sign off the lot, and
    the attempt is refused with `ERR_SEGREGATION_OF_DUTIES` at HTTP 403."

    Design: Corner/rbac/plant_admin_stands_in_for_every_role_but_not_for_the_duty_split
    """
    tester = make_plant_admin_headers("admin-qc")
    releaser = make_plant_admin_headers("admin-rel")
    api.set_current_utc("2026-08-01T00:00:00Z", ADMIN)
    get_success_data(
        api.create_metal_price_quote(create_metal_price_quote_payload(), ADMIN)
    )
    compound = get_success_data(
        api.create_compound(create_insulation_compound_payload(), ADMIN)
    )
    get_success_data(api.qualify_compound(compound["id"], ADMIN))
    cert = get_success_data(
        api.create_listing_certification(create_listing_certification_payload(), ADMIN)
    )
    get_success_data(
        api.create_factory_inspection(
            cert["id"],
            {"inspection_date": "2026-06-05", "inspector_code": "INS-7",
             "findings_count": 0, "outcome": "PASS"},
            ADMIN,
        )
    )
    product = get_success_data(
        api.create_catalog_product(
            create_catalog_product_payload(compound["id"], cert["id"]), ADMIN
        )
    )
    get_success_data(api.release_catalog_product(product["id"], ADMIN))
    customer = get_success_data(
        api.create_customer(
            {"account_code": "ACME", "name": "Acme Electric Supply",
             "market_region": "NORTHEAST", "credit_limit_usd": 100000.00,
             "pass_through_enabled": True, "reel_program": "RETURNABLE"},
            ADMIN,
        )
    )
    order = get_success_data(
        api.create_customer_order(
            {"customer_id": customer["id"], "product_id": product["id"],
             "order_number": "SO-ADM", "ordered_kft": 6.0,
             "price_basis": "ORDER_DATE_LOCK", "conversion_price_usd_per_kft": 85.0,
             "order_date": "2026-07-30"},
            ADMIN,
        )
    )
    rod = get_success_data(
        api.create_rod_purchase_lot(
            {"metal": "COPPER", "supplier_code": "SUP-1", "rod_diameter_mm": 8.0,
             "heat_number": "H-77Q", "purchase_weight_lbs": 20000.00,
             "purchase_price_usd_per_lb": 4.05, "pricing_basis": "SPOT",
             "received_date": "2026-07-25"},
            ADMIN,
        )
    )

    def schedule(lot_code, length, line, start, end, rod_version):
        return get_success_data(
            api.create_production_lot(
                {"product_id": product["id"], "rod_lot_id": rod["id"],
                 "order_id": order["id"], "lot_code": lot_code,
                 "planned_length_ft": length, "line_code": line,
                 "scheduled_start_at": start, "scheduled_end_at": end,
                 "expected_rod_lot_version": rod_version},
                ADMIN,
            )
        )

    lot_a = schedule("LOT-A", 5000, "EXT-1", "2026-08-02T08:00:00Z",
                      "2026-08-02T12:00:00Z", rod["version"])
    rod_v2 = get_success_data(api.get_rod_purchase_lot(rod["id"], ADMIN))["version"]
    lot_b = schedule("LOT-B", 1000, "EXT-2", "2026-08-02T08:00:00Z",
                      "2026-08-02T10:00:00Z", rod_v2)

    def run_and_test(lot_id):
        for step in ({"step": "DRAWING"}, {"step": "STRANDING"}):
            get_success_data(api.create_process_step(lot_id, step, ADMIN))
        get_success_data(
            api.create_process_step(
                lot_id,
                {"step": "EXTRUSION", "measured_min_wall_mils": 25.5,
                 "measured_max_wall_mils": 30.0, "measured_avg_od_mm": 4.1,
                 "surface_marking_text": THHN_12_CU_MARKING},
                ADMIN,
            )
        )
        get_success_data(
            api.create_cable_test(
                lot_id,
                {"test_type": "SPARK", "faults_detected": 0, "duration_sec": 60},
                tester,
            )
        )
        get_success_data(
            api.create_cable_test(
                lot_id,
                {"test_type": "HIPOT", "test_voltage_kv": 2.5,
                 "breakdown_detected": False, "duration_sec": 300},
                tester,
            )
        )

    run_and_test(lot_a["id"])
    released_a = validate_success(
        api.release_production_lot(lot_a["id"], {"packaged_length_ft": 5000}, releaser),
        200,
    )
    assert released_a["quality_state"] == "CONFORMING"

    reel = get_success_data(api.create_reel(create_reel_payload(), ADMIN))
    get_success_data(
        api.load_reel(
            reel["id"],
            {"lot_id": lot_a["id"], "load_length_ft": 5000,
             "occupancy_start_at": "2026-08-01T00:00:00Z"},
            ADMIN,
        )
    )
    order_version = get_success_data(
        api.get_customer_order(order["id"], ADMIN)
    )["version"]
    shipment = get_success_data(
        api.create_shipment(
            {"order_id": order["id"], "lot_id": lot_a["id"], "reel_id": reel["id"],
             "shipped_length_ft": 5000, "ship_date": "2026-08-01", "cuts_count": 0,
             "expected_order_version": order_version},
            ADMIN,
        )
    )
    invoiced = validate_success(api.invoice_shipment(shipment["id"], ADMIN), 200)
    assert invoiced["invoice_amount_usd"] == pytest.approx(544.58, abs=0.01), (
        "the chain a single administrator drove produced a staffed plant's number"
    )

    run_and_test(lot_b["id"])
    validate_error(
        api.release_production_lot(lot_b["id"], {"packaged_length_ft": 1000}, tester),
        "ERR_SEGREGATION_OF_DUTIES", 403,
    )
    assert read_lot(api, lot_b["id"])["quality_state"] == "PENDING", (
        "blanket authorisation does not suspend the duty split"
    )
    released_b = validate_success(
        api.release_production_lot(lot_b["id"], {"packaged_length_ft": 1000}, releaser),
        200,
    )
    assert released_b["quality_state"] == "CONFORMING", (
        "the same role and a different acting individual satisfies the rule"
    )

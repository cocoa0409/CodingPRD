"""Registration and record-keeping claims: shop defaults, customer/motor
registration rules, self-referential motor lineage, and the append-only
nature of test records and coil data records (PRD §2.5, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_coil_data_record,
    assert_motor,
    assert_shop,
    assert_test_record,
    create_motor_payload,
    create_shop_payload,
    create_shop,
    create_customer,
    create_motor,
    record_incoming_test,
    setup_balancing_work_order,
    setup_shop_customer_motor,
    setup_work_order_intake,
    diagnose_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["service_manager_headers"]
TECH = TEST_USERS["technician_headers"]


def test_shop_creation_applies_defaults_and_computed_fields(api):
    """PRD §3.1: "The shop's `currency` accepts only `USD` and defaults to it
    when omitted. A newly created shop starts at `version` 1."
    PRD §2.4: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z."

    Design: Corner/entities/shop_creation_applies_defaults_and_computed_fields
    """
    shop = validate_success(
        api.create_shop(create_shop_payload(), TEST_USERS["shop_admin_headers"]), 201
    )
    assert_shop(shop)
    assert shop["currency"] == "USD"
    assert shop["version"] == 1
    assert shop["created_at"] == "2026-08-01T00:00:00.000Z"

    fetched = validate_success(api.get_shop(shop["id"], TEST_USERS["shop_admin_headers"]), 200)
    assert fetched["currency"] == "USD"
    assert fetched["version"] == 1
    assert fetched["created_at"] == "2026-08-01T00:00:00.000Z"


def test_customer_missing_company_name_returns_invalid_input(api):
    """PRD §3.1: "Registering a customer requires only a `company_name`"
    PRD §2.11: "field-level input shape — non-positive hours, negative amounts,
    unrecognized enumeration values, rejected with `ERR_INVALID_INPUT`
    (HTTP 400)".

    Design: Corner/entities/customer_missing_company_name_returns_invalid_input
    """
    shop = create_shop()
    res = api.create_customer(shop["id"], {}, MANAGER)
    validate_error(res, "ERR_INVALID_INPUT", expected_status=400)


def test_motor_duplicate_serial_per_shop_rejected(api):
    """PRD §3.1: "the manufacturer `serial_number` (unique within the shop — a
    duplicate is rejected with `ERR_DUPLICATE_ACTIVE`)".

    Design: Corner/entities/motor_duplicate_serial_per_shop_rejected
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    first = validate_success(
        api.create_motor(
            shop["id"],
            create_motor_payload(customer["id"], "DUP-1", rated_kw=10, frame_mm=132, manufacture_year=2021),
            MANAGER,
        ),
        201,
    )
    assert_motor(first)

    res = api.create_motor(
        shop["id"],
        create_motor_payload(customer["id"], "DUP-1", rated_kw=15, frame_mm=160, manufacture_year=2022),
        MANAGER,
    )
    validate_error(res, "ERR_DUPLICATE_ACTIVE", expected_status=409)

    # The same serial under a different shop is a different uniqueness scope.
    other_shop = create_shop()
    other_customer = create_customer(other_shop["id"])
    res_other = api.create_motor(
        other_shop["id"],
        create_motor_payload(other_customer["id"], "DUP-1", rated_kw=10, frame_mm=132, manufacture_year=2021),
        MANAGER,
    )
    validate_success(res_other, 201)


def test_pool_spare_motor_defaults_custody_in_pool(api):
    """PRD §3.1: "`is_pool_spare`, defaulting to false, marks the unit as a
    shop-maintained pool spare, in which case `owner_customer_id` is left null
    — it is nullable only for pool spares — and the motor's custody starts at
    `IN_POOL` rather than `WITH_CUSTOMER`".

    Design: Corner/entities/pool_spare_motor_defaults_custody_in_pool
    """
    bundle = setup_shop_customer_motor()
    shop_id, cust_id = bundle["shop"]["id"], bundle["customer"]["id"]

    spare = validate_success(
        api.create_motor(
            shop_id,
            create_motor_payload(cust_id, "PS-1", rated_kw=75, manufacture_year=2019, is_pool_spare=True),
            MANAGER,
        ),
        201,
    )
    unit = validate_success(
        api.create_motor(shop_id, create_motor_payload(cust_id, "CU-1", rated_kw=75, manufacture_year=2019), MANAGER),
        201,
    )
    assert spare["custody"] == "IN_POOL"
    assert unit["custody"] == "WITH_CUSTOMER"


def test_test_record_immutable_no_update_endpoint(api):
    """PRD §2.5: "A TestRecord and a CoilDataRecord are immutable once written:
    each carries only `id` and `created_at` from the common set — both
    `updated_at` and `version` are absent from these two resources."

    Design: Corner/entities/test_record_immutable_no_update_endpoint
    """
    bundle = setup_work_order_intake()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    record = record_incoming_test(shop_id, wo_id)
    assert_test_record(record)
    assert record["insulation_megohms"] == 500

    # Mutate the parent work order, then re-read the record: unchanged.
    diagnose_work_order(shop_id, wo_id, rewind_hours=5, materials_cents=10000)
    data, meta = validate_paginated(api.list_tests(shop_id, wo_id, TECH))
    assert len(data) == 1
    reloaded = data[0]
    assert reloaded["id"] == record["id"]
    assert reloaded["insulation_megohms"] == 500
    assert "version" not in reloaded
    assert "updated_at" not in reloaded


def test_coil_data_record_immutable_and_lists_per_work_order(api):
    """PRD §3.4: "The record is immutable once written, and because the rework
    loop can cycle, a work order accumulates zero-to-many coil data records
    over its life, listed oldest first."
    PRD §3.4: "the server pins the shop's current EASA form revision (for
    example, `EASA-AR100-2024`) into the record's `easa_form_version` at
    creation and stamps `recorded_by` with the caller's `X-User-ID`".

    Design: Corner/entities/coil_data_record_immutable_and_lists_per_work_order
    """
    bundle = setup_balancing_work_order()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]

    data, meta = validate_paginated(api.list_coil_data(shop_id, wo_id, MANAGER))
    assert len(data) == 1
    record = data[0]
    assert_coil_data_record(record)
    assert record["recorded_by"] == "op-w"
    assert record["work_order_id"] == wo_id
    assert isinstance(record["easa_form_version"], str) and record["easa_form_version"]
    assert "version" not in record
    assert "updated_at" not in record


def test_motor_supersedes_self_reference_resolves(api):
    """PRD §3.1: "and `supersedes_motor_id` links a replacement motor record
    back to the scrapped unit it supersedes, a self-referential chain that
    preserves the service history across generations."
    PRD §2.11: "then resolution of foreign keys carried in the request body,
    such as the `motor_id` and `customer_id` on work-order intake or the
    `work_order_id` and `spare_motor_id` on pool checkout, rejected with
    `ERR_REFERENCE_NOT_FOUND` (HTTP 422)".

    Design: Corner/entities/motor_supersedes_self_reference_resolves
    """
    bundle = setup_shop_customer_motor()
    shop_id, cust_id = bundle["shop"]["id"], bundle["customer"]["id"]
    old = create_motor(shop_id, cust_id, serial_number="M-OLD", manufacture_year=2001)

    new = validate_success(
        api.create_motor(
            shop_id,
            create_motor_payload(cust_id, "M-NEW", manufacture_year=2026, supersedes_motor_id=old["id"]),
            MANAGER,
        ),
        201,
    )
    assert new["supersedes_motor_id"] == old["id"]

    res = api.create_motor(
        shop_id,
        create_motor_payload(cust_id, "M-BAD", manufacture_year=2026, supersedes_motor_id=NON_EXISTENT_UUID),
        MANAGER,
    )
    validate_error(res, "ERR_REFERENCE_NOT_FOUND", expected_status=422)

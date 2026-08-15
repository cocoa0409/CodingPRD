"""Catalog, inventory, community/lot and buyer registration claims (PRD §2.2–§2.5, §3.1–§3.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_ID,
    TEST_USERS,
    assert_customer,
    assert_home_model,
    assert_home_unit,
    assert_instant_equals,
    assert_lot,
    create_community,
    create_customer,
    create_lot,
    create_model,
    create_unit,
    get_success_data,
    is_valid_uuid,
    reserve_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CONSULTANT = TEST_USERS["consultant_headers"]


def test_create_home_model_missing_model_code_rejected(api):
    """PRD §2.8: "(all endpoints): required fields present, enums in range,
    numeric ranges honored, and a delay notice carrying exactly one of its two
    subject references, else `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_home_model_missing_required_returns_invalid_request
    """
    payload = {
        "name": "No Code",
        "floor_plan_type": "SINGLE_WIDE",
        "section_count": 1,
        "width_ft": 13.9,
        "length_ft": 66,
        "base_price_cents": 4_200_000,
        "factory_lead_time_days": 14,
    }
    resp = api.create_home_model(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_home_model_created_active(api):
    """PRD §3.1: "A model is `ACTIVE` on creation; a `DISCONTINUED` model cannot
    be referenced when registering new home units, and `model_code` uniqueness is
    scoped to non-`DISCONTINUED` models so a retired code does not block reuse
    checks against live inventory."

    Design: Corner/entities/home_model_default_status_applied
    """
    model = create_model()
    assert_home_model(model)
    assert model["status"] == "ACTIVE", f"Model must be ACTIVE on creation, got {model['status']}"


def test_get_missing_sales_order_not_found(api, consultant_headers):
    """PRD §2.8: "(all endpoints with path ids): path template ids resolve,
    validated left-to-right; the first missing resource yields that entity's
    not-found error (HTTP 404) — `ERR_HOME_MODEL_NOT_FOUND`,
    `ERR_COMMUNITY_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_HOME_UNIT_NOT_FOUND`, `ERR_SALES_ORDER_NOT_FOUND`,
    `ERR_ORDER_OPTION_NOT_FOUND`, `ERR_SITE_EVALUATION_NOT_FOUND`,
    `ERR_FINANCING_APPLICATION_NOT_FOUND`, `ERR_TRANSPORT_CREW_NOT_FOUND`,
    `ERR_TRANSPORT_JOB_NOT_FOUND`, `ERR_TITLE_RECORD_NOT_FOUND`,
    `ERR_WARRANTY_CLAIM_NOT_FOUND`, or `ERR_TRADE_IN_APPRAISAL_NOT_FOUND`."

    Design: Corner/entities/get_missing_sales_order_returns_not_found
    """
    resp = api.get_sales_order(NON_EXISTENT_ID, consultant_headers)
    validate_error(resp, ApiErrorId.ERR_SALES_ORDER_NOT_FOUND)


def test_home_models_list_pagination(api, consultant_headers):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters:
    `limit`, defaulting to 10, with a minimum of 1 and a maximum of 100; and
    `offset`, defaulting to 0. List responses are always sorted by `created_at`
    ascending, and the `meta` envelope of a list response carries `limit`,
    `offset`, `total_count`, and `has_more` alongside the request identifiers."

    Design: Corner/entities/home_models_list_pagination
    """
    ids = {create_model()["id"] for _ in range(3)}

    page1, meta1 = validate_paginated(api.list_home_models(consultant_headers, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2, f"Page 1 must carry 2 rows, got {len(page1)}"
    assert meta1["total_count"] == 3 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_home_models(consultant_headers, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1, f"Page 2 must carry the remaining 1 row, got {len(page2)}"
    assert meta2["total_count"] == 3 and meta2["has_more"] is False

    assert {row["id"] for row in page1 + page2} == ids, "Pages must partition the three models"


def test_customer_system_fields_server_minted(api, consultant_headers):
    """PRD §2.5: "Every persisted resource carries an `id` minted by the server as
    a bare UUID with no type prefix, a `created_at` timestamp, an `updated_at`
    timestamp, and a `version` integer."
    PRD §2.5: "The `version` starts at 1 on creation and increments by exactly 1
    on every mutation of that resource; any mutation also refreshes `updated_at`."
    PRD §2.4: "Before any explicit set call, the clock's startup default is
    exactly `2026-08-01T00:00:00Z`; it must not fall back to wall-clock time under
    any circumstance."

    Design: Corner/entities/customer_system_fields_input_ignored
    """
    forged_id = "00000000-0000-0000-0000-000000000000"
    payload = {
        "full_name": "Alicia Buyer",
        "email": "alicia@x.com",
        "phone": "555-0100",
        "credit_tier": "TIER_A",
        "id": forged_id,
        "created_at": "1999-01-01T00:00:00Z",
    }
    customer = validate_success(api.create_customer(payload, consultant_headers), expected_status=201)
    assert_customer(customer)
    assert customer["id"] != forged_id and is_valid_uuid(customer["id"]), "id must be server-minted"
    assert_instant_equals(customer["created_at"], "2026-08-01T00:00:00Z")
    assert customer["version"] == 1, f"version starts at 1, got {customer['version']}"


def test_create_home_unit_invalid_unit_kind(api, admin_headers):
    """PRD §2.8: "(all endpoints): required fields present, enums in range,
    numeric ranges honored, and a delay notice carrying exactly one of its two
    subject references, else `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_home_unit_invalid_enum_rejected
    """
    model = create_model()
    payload = {
        "model_id": model["id"],
        "serial_number": "SN-C7-1",
        "unit_kind": "BROKEN",
        "condition_grade": "NEW",
    }
    resp = api.create_home_unit(payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_duplicate_serial_number_rejected(api, admin_headers):
    """PRD §3.2: "Physical units are registered by a `DealershipAdmin` against a
    model with a factory `serial_number` (the HUD label, unique across all
    units), a `unit_kind`, and a `condition_grade`."
    PRD §2.8: "`serial_number` on unit registration, `email` on customer
    registration, `model_code` among non-`DISCONTINUED` models, and `lot_number`
    within its community; violations yield `ERR_DUPLICATE_RESOURCE` (HTTP 409) on
    `POST /api/home-units`, `POST /api/customers`, `POST /api/home-models`, and
    `POST /api/communities/{id}/lots`."

    Design: Corner/entities/duplicate_serial_number_rejected
    """
    model = create_model()
    create_unit(model["id"], serial_number="SN-DUP-1")
    resp = api.create_home_unit(
        {
            "model_id": model["id"],
            "serial_number": "SN-DUP-1",
            "unit_kind": "STOCK",
            "condition_grade": "NEW",
        },
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_lots_listed_under_owning_community(api, consultant_headers):
    """PRD §2.3: "Sub-resource list endpoints (an order's options, evaluations,
    applications, transport jobs, delay notices, appraisals; a unit's title
    records, warranty claims, and producing appraisals; a transport job's delay
    notices) accept only `limit` and `offset` and exist so every foreign key
    named in §3 is reverse-reachable."

    Design: Corner/entities/lot_fk_reverse_list
    """
    com_a = create_community(name="Pinewood MHC")
    com_b = create_community(name="Oakhurst")
    lot_a1 = create_lot(com_a["id"], lot_number="A-01")
    lot_a2 = create_lot(com_a["id"], lot_number="A-02", max_sections=1, utilities_ready=False)
    lot_b1 = create_lot(com_b["id"], lot_number="B-01", max_sections=1, max_length_ft=60)

    rows, meta = validate_paginated(api.list_lots(com_a["id"], consultant_headers))
    returned = {row["id"] for row in rows}
    assert returned == {lot_a1["id"], lot_a2["id"]}, f"Expected exactly A-01 and A-02, got {returned}"
    assert lot_b1["id"] not in returned
    assert meta["total_count"] == 2
    for row in rows:
        assert_lot(row)


def test_initial_states_on_create(api, consultant_headers):
    """PRD §3.1: "A lot's life is `AVAILABLE` → `RESERVED` → `LEASED`."
    PRD §3.2: "The `unit_kind` determines where the unit's life begins: `STOCK`
    units start `AT_DEALER`; `FACTORY_ORDER` units start `AT_FACTORY` and may not
    be sold until the factory finishes them".
    PRD §3.3: "On success the order is born `DRAFT` with `payment_status`
    `UNPAID`, and the unit flips to `RESERVED` with its `sales_order_id` pointing
    at the new order."

    Design: Corner/state_machines/initial_states_on_create
    """
    model = create_model()
    community = create_community()
    lot = create_lot(community["id"])
    assert lot["status"] == "AVAILABLE", f"Lot starts AVAILABLE, got {lot['status']}"
    customer = create_customer()

    stock_unit = create_unit(model["id"], unit_kind="STOCK")
    assert stock_unit["status"] == "AT_DEALER", f"STOCK unit starts AT_DEALER, got {stock_unit['status']}"
    factory_unit = create_unit(model["id"], unit_kind="FACTORY_ORDER")
    assert factory_unit["status"] == "AT_FACTORY", f"FACTORY_ORDER unit starts AT_FACTORY, got {factory_unit['status']}"

    reserve_lot(lot["id"])
    payload = {
        "customer_id": customer["id"],
        "home_unit_id": stock_unit["id"],
        "placement_type": "COMMUNITY_LOT",
        "lot_id": lot["id"],
        "financing_type": "CHATTEL",
        "agreed_home_price_cents": 4_200_000,
    }
    order = validate_success(api.create_sales_order(payload, consultant_headers), expected_status=201)
    assert order["deal_status"] == "DRAFT" and order["payment_status"] == "UNPAID"


def test_factory_order_mark_ready_temporal_gate(api, admin_headers):
    """PRD §3.2: "Factory completion is an explicit act: a `DealershipAdmin` marks
    a `FACTORY_ORDER` unit ready, moving it `AT_FACTORY` → `AT_DEALER`, only once
    the logical clock has reached the unit's `created_at` plus its model's
    `factory_lead_time_days`; an early attempt is rejected with
    `ERR_PRODUCTION_INCOMPLETE`."

    Design: Corner/validations/factory_order_mark_ready_temporal_gate
    """
    model = create_model(factory_lead_time_days=14)
    unit = create_unit(model["id"], unit_kind="FACTORY_ORDER")
    assert unit["status"] == "AT_FACTORY"
    assert_instant_equals(unit["created_at"], "2026-08-01T00:00:00Z")

    get_success_data(api.set_clock({"to_iso8601": "2026-08-14T00:00:00Z"}, admin_headers))
    resp = api.mark_ready_home_unit(unit["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_PRODUCTION_INCOMPLETE)

    get_success_data(api.set_clock({"to_iso8601": "2026-08-15T00:00:00Z"}, admin_headers))
    ready = validate_success(api.mark_ready_home_unit(unit["id"], admin_headers))
    assert_home_unit(ready)
    assert ready["status"] == "AT_DEALER", "mark-ready at exactly created_at + 14 days must succeed"


def test_home_units_filtered_by_model(api, consultant_headers):
    """PRD §3.2: "Units are listable by `model_id`, `lot_id`, `sales_order_id`,
    `unit_kind`, or `status`."

    Design: Corner/endpoints/home_units_filtered_by_model
    """
    model_a = create_model()
    model_b = create_model(double_wide=True)
    u1 = create_unit(model_a["id"])
    u2 = create_unit(model_a["id"])
    create_unit(model_b["id"])

    rows, meta = validate_paginated(
        api.list_home_units(consultant_headers, params={"model_id": model_a["id"]})
    )
    assert {row["id"] for row in rows} == {u1["id"], u2["id"]}
    assert meta["total_count"] == 2
    for row in rows:
        assert_home_unit(row)
        assert row["model_id"] == model_a["id"]

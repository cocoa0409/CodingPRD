"""Customer accounts, work-order intake defaults, rush window rules, credit
standing, listing/pagination, and read-after-write consistency (PRD §2.2,
§2.3, §2.5, §2.8, §3.1, §3.4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    DEFAULT_CLOCK_ISO,
    TEST_USERS,
    assert_customer_account,
    assert_instant_equals,
    assert_work_order,
    create_approved_recipe,
    create_customer,
    create_customer_payload,
    create_work_order,
    get_customer,
    get_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

CSR = TEST_USERS["customer_service_rep"]
QE = TEST_USERS["quality_engineer"]


# ---------------------------------------------------------------------------
# Corner: entities / customer_account_creation_defaults
# ---------------------------------------------------------------------------

def test_customer_creation_applies_defaults(api):
    """PRD §3.1: "`liability_tier` selects the coverage variant used if
    material is ever scrapped: `STANDARD` (the default when omitted) caps
    compensation at a multiple of the processing charge, while `EXTENDED`
    values material by weight — the mechanics are defined in §3.8."
    PRD §3.1: "`credit_hold` defaults to `false`; while it is `true`,
    work-order intake for the account is rejected with
    `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402)."
    PRD §3.1: "Each account also carries `outstanding_liability_exposure_cents`,
    a computed figure that starts at 0: the sum of `payout_cents` over that
    customer's claims in `PENDING` or `ACCEPTED` status, recomputed whenever
    a claim is created, paid, or rejected."

    Design: Corner/entities/customer_account_creation_defaults
    """
    res = api.create_customer_account({"name": "Defaults Co"}, CSR)
    customer = validate_success(res, 201)
    assert_customer_account(customer)
    assert customer["liability_tier"] == "STANDARD", (
        f"omitted liability_tier must default to STANDARD, got "
        f"{customer['liability_tier']}"
    )
    assert customer["credit_hold"] is False, (
        f"omitted credit_hold must default to false, got {customer['credit_hold']}"
    )
    assert customer["outstanding_liability_exposure_cents"] == 0, (
        f"exposure starts at 0, got "
        f"{customer['outstanding_liability_exposure_cents']}"
    )
    assert isinstance(customer["version"], int)


# ---------------------------------------------------------------------------
# Corner: entities / computed_field_input_ignored
# ---------------------------------------------------------------------------

def test_computed_exposure_input_ignored(api):
    """PRD §3.1: "Each account also carries
    `outstanding_liability_exposure_cents`, a computed figure that starts at
    0: the sum of `payout_cents` over that customer's claims in `PENDING` or
    `ACCEPTED` status, recomputed whenever a claim is created, paid, or
    rejected."

    Design: Corner/entities/computed_field_input_ignored
    """
    payload = create_customer_payload(
        name="Sneaky Co", liability_tier="STANDARD",
        outstanding_liability_exposure_cents=999999,
    )
    customer = validate_success(api.create_customer_account(payload, CSR), 201)
    assert customer["outstanding_liability_exposure_cents"] == 0, (
        "client-supplied value for the computed exposure must be ignored; "
        f"got {customer['outstanding_liability_exposure_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner: entities / work_order_intake_stamps_logical_clock_and_defaults
# ---------------------------------------------------------------------------

def test_work_order_intake_stamps_logical_clock_and_defaults(api):
    """PRD §2.5: "At server startup the logical clock reads exactly
    2026-08-01T00:00:00Z, and it holds that value until an operator moves it."
    PRD §3.4: "Creation stamps the order with the logical clock as
    `received_at`, sets `processing_status` to `RECEIVED` and
    `quality_status` to `PENDING_TEST`, and initializes `retreat_count` to 0."
    PRD §3.4: "For `RUSH` lots, `promised_due_at` is `received_at` plus the
    guaranteed hours; for `STANDARD` lots it stays null."
    PRD §3.4: "`STANDARD`-lane orders quote 0."

    Design: Corner/entities/work_order_intake_stamps_logical_clock_and_defaults
    """
    customer = create_customer(name="Clock Co")
    recipe = create_approved_recipe()

    rush = create_work_order(
        customer["id"], recipe["id"], service_lane="RUSH",
        guaranteed_turnaround_hours=48,
    )
    assert_work_order(rush)
    assert_instant_equals(rush["received_at"], DEFAULT_CLOCK_ISO, "received_at")
    assert_instant_equals(
        rush["promised_due_at"], "2026-08-03T00:00:00Z", "promised_due_at"
    )
    assert rush["processing_status"] == "RECEIVED"
    assert rush["quality_status"] == "PENDING_TEST"
    assert rush["retreat_count"] == 0

    std = create_work_order(customer["id"], recipe["id"])
    assert std["service_lane"] == "STANDARD"
    assert std["promised_due_at"] is None, (
        f"STANDARD promised_due_at stays null, got {std['promised_due_at']}"
    )
    assert std["rush_surcharge_quoted_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: entities / missing_required_field_returns_invalid_request
# ---------------------------------------------------------------------------

def test_work_order_missing_customer_id_rejected(api):
    """PRD §3.4: "Receiving a lot requires the `customer_id` of the material
    owner and the `recipe_id` of the selected cycle, the `part_quantity`
    piece count, the lot's `received_weight_lb` in pounds, the customer's
    `declared_value_cents` (which later caps any liability payout), and the
    quoted `processing_charge_cents`."
    PRD §3.3: "omitting a required input is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/missing_required_field_returns_invalid_request
    """
    recipe = create_approved_recipe()
    payload = {
        "recipe_id": recipe["id"],
        "part_quantity": 5,
        "received_weight_lb": 100,
        "declared_value_cents": 500000,
        "processing_charge_cents": 100000,
    }
    res = api.create_work_order(payload, CSR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner: validations / rush_guarantee_window_floor_and_presence
# ---------------------------------------------------------------------------

def test_rush_guarantee_window_floor_and_presence(api):
    """PRD §3.4: "A `RUSH` order submitted without
    `guaranteed_turnaround_hours` is rejected with `ERR_INVALID_REQUEST`; a
    value below 4 hours is rejected with `ERR_INVALID_GUARANTEE_WINDOW`
    (HTTP 422)."

    Design: Corner/validations/rush_guarantee_window_floor_and_presence
    """
    customer = create_customer(name="Floor Co")
    recipe = create_approved_recipe()
    base = {
        "customer_id": customer["id"],
        "recipe_id": recipe["id"],
        "part_quantity": 5,
        "received_weight_lb": 100,
        "declared_value_cents": 500000,
        "processing_charge_cents": 100000,
        "service_lane": "RUSH",
    }
    low = api.create_work_order({**base, "guaranteed_turnaround_hours": 2}, CSR)
    validate_error(low, ApiErrorId.ERR_INVALID_GUARANTEE_WINDOW.value)
    missing = api.create_work_order(dict(base), CSR)
    validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner: validations / credit_hold_rejects_and_existence_beats_fiscal
# ---------------------------------------------------------------------------

def test_credit_hold_rejects_and_existence_beats_fiscal(api):
    """PRD §3.1: "`credit_hold` defaults to `false`; while it is `true`,
    work-order intake for the account is rejected with
    `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402)."
    PRD §2.8: "The order is: (1) user-context headers present and non-empty
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role permitted for the
    endpoint (`ERR_INSUFFICIENT_PERMISSIONS`); (3) customer-ownership scoping
    (`ERR_OWNERSHIP_MISMATCH`); (4) resource existence — path identifiers
    validated left to right, then request-body foreign keys (the
    `ERR_*_NOT_FOUND` family); (5) state-machine preconditions and
    optimistic-concurrency checks (the state errors such as
    `ERR_LOAD_NOT_BUILDING`, plus `ERR_STALE_VERSION`); (6) business safety
    gates — furnace qualification, furnace-class rank, quench-media
    compatibility, segregation of duties; (7) recipe referential consistency —
    approval state, recipe match between order and load, alloy/spec
    uniqueness; (8) temporal rules — rush guarantee window, pyrometry validity
    containment, schedule overlap and purge gap; (9) constraint checks — load
    weight capacity, non-empty load, re-treat ceiling, required fields and
    enum validity; (10) fiscal standing (`ERR_CUSTOMER_CREDIT_HOLD`)."

    Design: Corner/validations/credit_hold_rejects_and_existence_beats_fiscal
    """
    held = create_customer(name="Held Co", credit_hold=True)
    recipe = create_approved_recipe()
    base = {
        "customer_id": held["id"],
        "part_quantity": 5,
        "received_weight_lb": 100,
        "declared_value_cents": 500000,
        "processing_charge_cents": 100000,
    }
    hold = api.create_work_order({**base, "recipe_id": recipe["id"]}, CSR)
    validate_error(hold, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value)
    ghost = api.create_work_order({**base, "recipe_id": NON_EXISTENT_UUID}, CSR)
    validate_error(ghost, ApiErrorId.ERR_RECIPE_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict /
# existence_beats_temporal_on_work_order_create
# ---------------------------------------------------------------------------

def test_existence_beats_temporal_on_work_order_create(api):
    """PRD §2.8: "When several checks could reject the same request, the
    server evaluates them in a fixed pipeline and surfaces the first failure
    rather than an arbitrary one."
    PRD §2.8: "The order is: (1) user-context headers present and non-empty
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role permitted for the
    endpoint (`ERR_INSUFFICIENT_PERMISSIONS`); (3) customer-ownership scoping
    (`ERR_OWNERSHIP_MISMATCH`); (4) resource existence — path identifiers
    validated left to right, then request-body foreign keys (the
    `ERR_*_NOT_FOUND` family); (5) state-machine preconditions and
    optimistic-concurrency checks (the state errors such as
    `ERR_LOAD_NOT_BUILDING`, plus `ERR_STALE_VERSION`); (6) business safety
    gates — furnace qualification, furnace-class rank, quench-media
    compatibility, segregation of duties; (7) recipe referential consistency —
    approval state, recipe match between order and load, alloy/spec
    uniqueness; (8) temporal rules — rush guarantee window, pyrometry validity
    containment, schedule overlap and purge gap; (9) constraint checks — load
    weight capacity, non-empty load, re-treat ceiling, required fields and
    enum validity; (10) fiscal standing (`ERR_CUSTOMER_CREDIT_HOLD`)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_on_work_order_create
    """
    customer = create_customer(name="Ghost Co")
    res = api.create_work_order(
        {
            "customer_id": customer["id"],
            "recipe_id": NON_EXISTENT_UUID,
            "part_quantity": 5,
            "received_weight_lb": 100,
            "declared_value_cents": 500000,
            "processing_charge_cents": 100000,
            "service_lane": "RUSH",
            "guaranteed_turnaround_hours": 2,
        },
        CSR,
    )
    validate_error(res, ApiErrorId.ERR_RECIPE_NOT_FOUND.value)


def test_existence_beats_constraint_on_work_order_create(api):
    """PRD §2.8: "When several checks could reject the same request, the
    server evaluates them in a fixed pipeline and surfaces the first failure
    rather than an arbitrary one."
    PRD §2.8: "The order is: (1) user-context headers present and non-empty
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); (2) role permitted for the
    endpoint (`ERR_INSUFFICIENT_PERMISSIONS`); (3) customer-ownership scoping
    (`ERR_OWNERSHIP_MISMATCH`); (4) resource existence — path identifiers
    validated left to right, then request-body foreign keys (the
    `ERR_*_NOT_FOUND` family); (5) state-machine preconditions and
    optimistic-concurrency checks (the state errors such as
    `ERR_LOAD_NOT_BUILDING`, plus `ERR_STALE_VERSION`); (6) business safety
    gates — furnace qualification, furnace-class rank, quench-media
    compatibility, segregation of duties; (7) recipe referential consistency —
    approval state, recipe match between order and load, alloy/spec
    uniqueness; (8) temporal rules — rush guarantee window, pyrometry validity
    containment, schedule overlap and purge gap; (9) constraint checks — load
    weight capacity, non-empty load, re-treat ceiling, required fields and
    enum validity; (10) fiscal standing (`ERR_CUSTOMER_CREDIT_HOLD`)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_on_work_order_create
    """
    # Ghost customer plus a RUSH order missing its required guarantee hours:
    # body-FK existence (priority 4) fires before required-field checks (9).
    res = api.create_work_order(
        {
            "customer_id": NON_EXISTENT_UUID,
            "recipe_id": NON_EXISTENT_UUID,
            "part_quantity": 5,
            "received_weight_lb": 100,
            "declared_value_cents": 500000,
            "processing_charge_cents": 100000,
            "service_lane": "RUSH",
        },
        CSR,
    )
    validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: entities / work_order_list_filtered_by_customer
# ---------------------------------------------------------------------------

def test_work_order_list_filtered_by_customer(api):
    """PRD §2.3: "Most list endpoints accept optional equality filters
    matching fields of the listed resource: work orders filter by
    `customer_id`, `recipe_id`, `processing_status`, or `service_lane`;
    pyrometry records by `furnace_id` or `record_type`; inspection tests by
    `work_order_id` or `result`; disposition cases by `work_order_id`,
    `inspection_test_id`, or `status`; liability claims by `customer_id`,
    `work_order_id`, or `status`; load batches by `furnace_id`, `recipe_id`,
    or `status`; load assignments by `load_batch_id`, `work_order_id`, or
    `status`; thermocouple readings by `load_batch_id`; audit packages by
    `furnace_id` or `status`."

    Design: Corner/entities/work_order_list_filtered_by_customer
    """
    cust_a = create_customer(name="A Co")
    cust_b = create_customer(name="B Co")
    recipe = create_approved_recipe()
    create_work_order(cust_a["id"], recipe["id"])
    create_work_order(cust_a["id"], recipe["id"])
    create_work_order(cust_b["id"], recipe["id"])

    data, meta = validate_paginated(
        api.list_work_orders(CSR, params={"customer_id": cust_a["id"]})
    )
    assert meta["total_count"] == 2, f"expected 2 orders for A, got {meta}"
    assert len(data) == 2
    assert all(item["customer_id"] == cust_a["id"] for item in data), (
        "filtered list must contain only customer A's orders"
    )


# ---------------------------------------------------------------------------
# Corner: endpoints / list_pagination_and_filter_envelope
# ---------------------------------------------------------------------------

def test_list_pagination_and_filter_envelope(api):
    """PRD §2.3: "`limit` caps the number of items returned; it defaults to
    10, with a minimum of 1 and a maximum of 100. `offset` specifies how many
    items to skip and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."

    Design: Corner/endpoints/list_pagination_and_filter_envelope
    """
    customer = create_customer(name="Page Co")
    recipe = create_approved_recipe()
    create_work_order(customer["id"], recipe["id"], service_lane="STANDARD")
    create_work_order(customer["id"], recipe["id"], service_lane="STANDARD")
    create_work_order(
        customer["id"], recipe["id"], service_lane="RUSH",
        guaranteed_turnaround_hours=48,
    )

    res1 = api.list_work_orders(
        CSR, params={"customer_id": customer["id"], "limit": 2}
    )
    page1, meta1 = validate_paginated(res1)
    body1 = res1.json()
    assert body1["response_type"] == "array"
    assert isinstance(body1["meta"].get("api_request_id"), str)
    assert body1["meta"]["api_request_id"].startswith("req_")
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_work_orders(
            CSR, params={"customer_id": customer["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    rush_items, rush_meta = validate_paginated(
        api.list_work_orders(
            CSR, params={"customer_id": customer["id"], "service_lane": "RUSH"}
        )
    )
    assert rush_meta["total_count"] == 1
    assert len(rush_items) == 1
    assert rush_items[0]["service_lane"] == "RUSH"


# ---------------------------------------------------------------------------
# Corner: consistency_model / immediate_read_after_write_consistency
# ---------------------------------------------------------------------------

def test_immediate_read_after_write_consistency(api):
    """PRD §3.1: "Each account also carries
    `outstanding_liability_exposure_cents`, a computed figure that starts at
    0: the sum of `payout_cents` over that customer's claims in `PENDING` or
    `ACCEPTED` status, recomputed whenever a claim is created, paid, or
    rejected."
    PRD §3.4: "The quote starts from a base of 15,000 cents plus 20 percent of
    the lot's `processing_charge_cents`, the percentage portion rounded
    half-up to whole cents before being added to the base. When the promised
    turnaround is 24 hours or less, this combined base is then multiplied by
    1.5 and again rounded half-up to whole cents. The quoted surcharge is that
    figure clamped to a floor of 25,000 cents and a ceiling of 200,000 cents."
    PRD §3.4: "For `RUSH` lots, `promised_due_at` is `received_at` plus the
    guaranteed hours; for `STANDARD` lots it stays null."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    customer = create_customer(name="Now Co")
    recipe = create_approved_recipe()
    order = create_work_order(
        customer["id"], recipe["id"], service_lane="RUSH",
        guaranteed_turnaround_hours=48,
    )

    read_customer = get_customer(customer["id"])
    assert read_customer["name"] == "Now Co"
    assert read_customer["liability_tier"] == "STANDARD"
    assert read_customer["outstanding_liability_exposure_cents"] == 0
    assert isinstance(read_customer["version"], int)

    read_order = get_work_order(order["id"])
    assert_instant_equals(
        read_order["promised_due_at"], "2026-08-03T00:00:00Z", "promised_due_at"
    )
    assert read_order["rush_surcharge_quoted_cents"] == 35000, (
        "15000 + round_half_up(0.20 x 100000) = 35000 must be settled in the "
        f"read, got {read_order['rush_surcharge_quoted_cents']}"
    )

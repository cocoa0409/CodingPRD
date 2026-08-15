"""Order intake and catalog creation: system-stamped fields, defaults, and
the validation rules that guard order placement (slump band, pour window,
uniqueness, required fields, not-found reads, list pagination)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_customer,
    create_customer_payload,
    create_draft_mix,
    create_mix_design_payload,
    create_plant,
    create_plant_payload,
    get_customer,
    get_order,
    make_customer_headers,
    place_order,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_plant_created_active_with_version_one(api):
    """PRD §2.5: "A plant is created with a `name`, a `batch_cycle_minutes`
    value, and a `daily_capacity_yd3` value, and starts in `ACTIVE` status
    (plants also support a `DOWN` status)."
    PRD §2.4: "Before any operator touches it, this clock reads exactly
    2026-08-01T00:00:00Z."

    Design: Corner/entities/plant_creation_fields_and_defaults
    """
    res = api.create_plant(create_plant_payload(), PM)
    plant = validate_success(res, 201)
    assert plant["status"] == "ACTIVE"
    assert plant["version"] == 1
    assert plant["batch_cycle_minutes"] == 30
    assert plant["created_at"].startswith("2026-08-01T00:00:00"), (
        f"creation timestamp must read the default logical clock, got "
        f"{plant['created_at']}"
    )

    fetched = validate_success(api.get_plant(plant["id"], PM), 200)
    assert fetched["id"] == plant["id"]
    assert fetched["status"] == "ACTIVE"


def test_customer_created_with_short_load_default_and_good_credit(api):
    """PRD §2.9: "A customer also declares `short_load_allowed` (defaulting to
    true), which governs whether loads below the price list's minimum may be
    scheduled for them."
    PRD §2.9: "Every customer carries a `credit_limit_cents`, a derived
    `credit_exposure_cents` (starting at 0), and a derived `credit_status` of
    `GOOD` or `HOLD`."

    Design: Corner/entities/customer_creation_defaults
    """
    res = api.create_customer(
        create_customer_payload(name="Cust A", credit_limit_cents=500000), PM
    )
    customer = validate_success(res, 201)
    assert customer["short_load_allowed"] is True
    assert customer["credit_status"] == "GOOD"
    assert customer["credit_exposure_cents"] == 0

    fetched = validate_success(api.get_customer(customer["id"], PM), 200)
    assert fetched["short_load_allowed"] is True
    assert fetched["credit_status"] == "GOOD"


def test_order_stamps_customer_id_from_header_and_starts_placed_unpriced(api):
    """PRD §3.3: "The `customer_id` is stamped from the placing customer's
    `X-User-ID`, not from the payload."
    PRD §3.3: "A new order is born with `delivery_status` `PLACED` and
    `billing_status` `UNPRICED`; these two dimensions are parallel and evolve
    independently — delivery runs `PLACED | CONFIRMED | SCHEDULED | IN_PROGRESS
    | DELIVERED | CANCELLED` while billing runs `UNPRICED | PRICED | INVOICED |
    DISPUTED | PAID | VOID`, with `PRICED`, `INVOICED`, `DISPUTED`, and `PAID`
    reached as billing milestones in §3.9."
    PRD §3.3: "The resulting escalated base is stored as `escalated_base_cents`
    and the quote total as `provisional_total_cents`; both remain null until
    the order is confirmed."

    Design: Corner/entities/order_creation_sets_customer_from_header_and_initial_states
    """
    plant, _ = create_plant()
    mix = create_draft_mix(plant["id"], admixtures=[])
    customer = create_customer()

    res = api.create_order(
        {
            "plant_id": plant["id"],
            "mix_design_id": mix["id"],
            "qty_yd3": 8.0,
            "pour_date": "2026-08-15",
            "pour_window_start": "07:00",
            "pour_window_end": "10:00",
            "slump_in": 4.5,
        },
        make_customer_headers(customer["id"]),
    )
    order = validate_success(res, 201)
    assert order["customer_id"] == customer["id"], (
        "customer_id must be stamped from X-User-ID, not the request body"
    )
    assert order["delivery_status"] == "PLACED"
    assert order["billing_status"] == "UNPRICED"
    assert order["delivered_qty_yd3"] == 0
    assert order["provisional_total_cents"] is None


def test_order_create_without_qty_rejected(api):
    """PRD §3.3: "A `Customer` places an order with a payload containing the
    `plant_id`, the `mix_design_id`, the ordered `qty_yd3`, the `pour_date` in
    YYYY-MM-DD form, the window endpoints `pour_window_start` and
    `pour_window_end` in 24-hour HH:MM form, and the ordered `slump_in`."
    PRD §2.8: "Referenced-resource existence (`ERR_NOT_FOUND`) and basic
    request shape — missing required fields, wrong types, out-of-range enum
    values, uniqueness violations (`ERR_VALIDATION`) — come next."

    Design: Corner/entities/order_create_missing_required_field_returns_invalid_request
    """
    plant, _ = create_plant()
    mix = create_draft_mix(plant["id"], admixtures=[])
    customer = create_customer()

    payload = {
        "plant_id": plant["id"],
        "mix_design_id": mix["id"],
        "pour_date": "2026-08-15",
        "pour_window_start": "07:00",
        "pour_window_end": "10:00",
        "slump_in": 4.5,
    }
    res = api.create_order(payload, make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_mix_design_duplicate_code_per_plant_rejected(api):
    """PRD §3.1: "A mix design is created in `DRAFT` status with the owning
    `plant_id`, a `code` that must be unique within that plant (a duplicate
    code is rejected with `ERR_VALIDATION`), a human-readable `name`, the
    specified 28-day compressive strength `design_strength_psi`, the design
    `slump_in` in inches, the `cement_content_lb_per_yd3`, the
    `design_wc_ratio` batched at the plant, the absolute legal ceiling
    `max_wc_ratio` that includes all on-site water, and an `admixtures` array
    whose entries each pair an `admixture_code` with a `dose_oz_per_cwt`."

    Design: Corner/entities/mix_design_duplicate_code_per_plant_returns_invalid_request
    """
    plant, _ = create_plant()
    first = api.create_mix_design(
        create_mix_design_payload(plant["id"], admixtures=[]), PM
    )
    validate_success(first, 201)

    res = api.create_mix_design(
        create_mix_design_payload(plant["id"], name="duplicate", admixtures=[]), PM
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_get_nonexistent_order_returns_not_found(api):
    """PRD §2.8: "Referenced-resource existence (`ERR_NOT_FOUND`) and basic
    request shape — missing required fields, wrong types, out-of-range enum
    values, uniqueness violations (`ERR_VALIDATION`) — come next."

    Design: Corner/entities/get_nonexistent_order_returns_not_found
    """
    res = api.get_order(NON_EXISTENT_UUID, DISP)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_order_list_pagination_envelope(api):
    """PRD §2.3: "All list endpoints accept the query parameters `limit` and
    `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100;
    `offset` defaults to 0. Results are sorted by `created_at` ascending. List
    responses carry `limit`, `offset`, `total_count`, and `has_more` in the
    `meta` object."

    Design: Corner/entities/order_list_pagination_envelope
    """
    plant, _ = create_plant()
    mix = create_draft_mix(plant["id"], admixtures=[])
    customer = create_customer()
    first = place_order(plant["id"], mix["id"], customer["id"])
    second = place_order(
        plant["id"], mix["id"], customer["id"],
        qty_yd3=5.0, pour_date="2026-08-16", pour_window_start="08:00",
        pour_window_end="11:00", slump_in=4.0,
    )

    data, meta = validate_paginated(
        api.list_orders(DISP, params={"customer_id": customer["id"], "limit": 1, "offset": 0})
    )
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    first_page_id = data[0]["id"]

    data2, meta2 = validate_paginated(
        api.list_orders(DISP, params={"customer_id": customer["id"], "limit": 1, "offset": 1})
    )
    assert len(data2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert data2[0]["id"] != first_page_id
    assert {first_page_id, data2[0]["id"]} == {first["id"], second["id"]}


def test_slump_beyond_one_inch_band_rejected_but_boundary_accepted(api):
    """PRD §3.1: "When a customer places an order, the ordered `slump_in` must
    lie within plus or minus 1.0 inch of the mix design's `slump_in`,
    inclusive; an order outside that band is rejected with
    `ERR_SLUMP_OUT_OF_TOLERANCE` (HTTP 422)."

    Design: Corner/validations/slump_out_of_tolerance_rejected
    """
    plant, _ = create_plant()
    mix = create_draft_mix(plant["id"], admixtures=[])  # design slump 4.0
    customer = create_customer()

    res = api.create_order(
        {
            "plant_id": plant["id"],
            "mix_design_id": mix["id"],
            "qty_yd3": 8.0,
            "pour_date": "2026-08-15",
            "pour_window_start": "07:00",
            "pour_window_end": "10:00",
            "slump_in": 6.0,
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SLUMP_OUT_OF_TOLERANCE.value)

    ok = api.create_order(
        {
            "plant_id": plant["id"],
            "mix_design_id": mix["id"],
            "qty_yd3": 8.0,
            "pour_date": "2026-08-15",
            "pour_window_start": "07:00",
            "pour_window_end": "10:00",
            "slump_in": 5.0,
        },
        make_customer_headers(customer["id"]),
    )
    order = validate_success(ok, 201)
    assert order["delivery_status"] == "PLACED"


def test_pour_window_not_strictly_after_rejected(api):
    """PRD §3.3: "The pour window must be well-formed: `pour_window_end`
    strictly after `pour_window_start`, otherwise `ERR_ORDER_WINDOW_INVALID`
    (HTTP 422)."

    Design: Corner/validations/pour_window_inverted_rejected
    """
    plant, _ = create_plant()
    mix = create_draft_mix(plant["id"], admixtures=[])
    customer = create_customer()

    res = api.create_order(
        {
            "plant_id": plant["id"],
            "mix_design_id": mix["id"],
            "qty_yd3": 8.0,
            "pour_date": "2026-08-15",
            "pour_window_start": "10:00",
            "pour_window_end": "10:00",
            "slump_in": 4.5,
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ORDER_WINDOW_INVALID.value)


def test_confirm_after_pour_date_passed_rejected(api):
    """PRD §3.3: "Confirmation is a `Dispatcher` action and is where pricing
    locks in. Only a `PLACED` order can be confirmed, and confirming enforces
    four further preconditions, evaluated within the priority framework of
    §2.8: the customer's `credit_status` must not be `HOLD` (otherwise
    `ERR_CREDIT_HOLD`, HTTP 402); the order's mix design must be `ACTIVE`
    (`ERR_MIX_NOT_ACTIVE`); exactly one price list in `ACTIVE` must exist for
    the order's (plant, mix design) pair (`ERR_PRICE_LIST_MISSING`, HTTP 409);
    and the `pour_date` must still be on or after the current logical date
    (`ERR_POUR_DATE_PAST`)."

    Design: Corner/validations/pour_date_past_rejected_at_confirm
    """
    # Build catalog + order, but do NOT confirm before moving the clock forward.
    from test_helpers import setup_standard_catalog, set_clock

    catalog = setup_standard_catalog()
    order = place_order(
        catalog["plant"]["id"], catalog["mix"]["id"], catalog["customer"]["id"]
    )
    set_clock("2026-08-20T09:00:00Z")
    res = api.confirm_order(order["id"], DISP)
    validate_error(res, ApiErrorId.ERR_POUR_DATE_PAST.value)
    after = get_order(order["id"])
    assert after["delivery_status"] == "PLACED"


def test_confirm_with_draft_mix_rejected(api):
    """PRD §3.1: "Only an `ACTIVE` design may be confirmed onto an order or
    batched into a load — either attempt against a non-active design is
    rejected with `ERR_MIX_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/validations/confirm_with_draft_mix_rejected
    """
    from test_helpers import create_active_price_list

    plant, plant_version = create_plant()
    mix = create_draft_mix(plant["id"], admixtures=[])  # never activated
    create_active_price_list(plant["id"], mix["id"], plant_version)
    customer = create_customer()
    order = place_order(plant["id"], mix["id"], customer["id"])

    res = api.confirm_order(order["id"], DISP)
    validate_error(res, ApiErrorId.ERR_MIX_NOT_ACTIVE.value)
    after = get_order(order["id"])
    assert after["billing_status"] == "UNPRICED"


def test_confirm_without_active_price_list_rejected(api):
    """PRD §3.3: "exactly one price list in `ACTIVE` must exist for the
    order's (plant, mix design) pair (`ERR_PRICE_LIST_MISSING`, HTTP 409)".

    Design: Corner/validations/confirm_without_price_list_rejected
    """
    plant, _ = create_plant()
    mix = create_draft_mix(plant["id"], admixtures=[])
    # Activate the mix but publish NO price list for the pair.
    validate_success(api.activate_mix_design(mix["id"], PM), 200)
    customer = create_customer()
    order = place_order(plant["id"], mix["id"], customer["id"])

    res = api.confirm_order(order["id"], DISP)
    validate_error(res, ApiErrorId.ERR_PRICE_LIST_MISSING.value)


def test_duplicate_cement_index_month_rejected(api):
    """PRD §3.2: "Publishing a second index for the same (`plant_id`,
    `effective_month`) is rejected with `ERR_INDEX_MONTH_DUPLICATE`
    (HTTP 409)."

    Design: Corner/validations/index_month_duplicate_rejected
    """
    from test_helpers import create_cement_price_index_payload, publish_index

    plant, _ = create_plant()
    publish_index(plant["id"], "2026-08", 115.0)

    dup = api.create_cement_price_index(
        create_cement_price_index_payload(plant["id"], "2026-08", 120.0), PM
    )
    validate_error(dup, ApiErrorId.ERR_INDEX_MONTH_DUPLICATE.value)

    ok = api.create_cement_price_index(
        create_cement_price_index_payload(plant["id"], "2026-09", 120.0), PM
    )
    validate_success(ok, 201)

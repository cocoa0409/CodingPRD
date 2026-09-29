"""Resource shapes, envelopes, defaults and write-time input validation."""

import pytest

from test_helpers import (
    CLOCK_START,
    CREDIT_MANAGER,
    FABRICATED_ID,
    LIST_PRICE_CENTS,
    PLATFORM_ADMIN,
    PRO_DESK_ASSOCIATE,
    SKU_SHINGLE_BUNDLE,
    STORE_OPERATIONS,
    TAX_COMPLIANCE_OFFICER,
    ApiErrorId,
    assert_pagination_meta,
    assert_pro_account,
    assert_pro_order,
    assert_store,
    assert_store_stock,
    create_delivery_appointment_payload,
    create_delivery_truck,
    create_job_quote_payload,
    create_order_line_payload,
    create_pro_account,
    create_pro_order_payload,
    create_store,
    create_store_payload,
    create_store_stock_payload,
    is_valid_uuid,
    make_contractor_admin_headers,
    setup_store_with_stock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant_equals(actual: str, expected: str) -> bool:
    """True when two ISO 8601 UTC strings denote the same instant."""

    def normalise(value: str) -> str:
        assert isinstance(value, str) and value.endswith(
            "Z"
        ), f"expected a UTC ISO 8601 instant, got {value!r}"
        core = value[:-1]
        if "." in core:
            core = core.split(".")[0]
        return core

    return normalise(actual) == normalise(expected)


def _rate_equals(actual, expected: float) -> bool:
    """Rates are decimal fractions; compare them without floating-point noise."""
    return isinstance(actual, (int, float)) and abs(float(actual) - expected) < 1e-9


# --------------------------------------------------------------------------- #
# Store creation                                                              #
# --------------------------------------------------------------------------- #


def test_create_store_echoes_declared_fields_in_the_success_envelope(api):
    """PRD §4: "Endpoints that create a new resource respond with `201 Created`; every other successful call responds with `200 OK`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §3.1: "Sourcing order is driven by `distance_rank`, a non-negative integer where a lower value means a nearer store; `will_call_bay_slots`, at least 1, is the number of staging bays that can be occupied at the same instant; `lift_gate_available` records whether the store dispatches lift-gate-capable equipment at all; `tax_rate_pct` is the sales tax rate applied to that store's taxable orders, expressed as a decimal fraction between 0 and 0.20 inclusive — a store charging eight and a quarter percent is registered as `0.0825`; and `max_stage_hours`, at least 1 and defaulting to 72 when omitted, caps how long a single will-call occupancy may run at that store."
    PRD §2.5: "**`version`** (integer): a monotonically increasing counter that starts at 1 when the record is created and increases by one on every mutation."
    PRD §2.5: "**`created_at`** (string): an ISO 8601 timestamp in UTC with three fractional digits, for example `2026-08-01T00:00:00.000Z`, recording when the record was first written."
    PRD §2.4: "Before any client sets the clock, it reads exactly `2026-08-01T00:00:00Z`; that startup default is fixed and the server must never fall back to real time."

    Design: Corner/entities/create_store_returns_declared_fields_and_success_envelope
    """
    payload = create_store_payload(
        store_code="HD-101",
        region_code="MIDWEST",
        state_code="IL",
        distance_rank=1,
        will_call_bay_slots=2,
        lift_gate_available=True,
        tax_rate_pct=0.0825,
        max_stage_hours=48,
    )

    response = api.create_store(payload, PLATFORM_ADMIN)
    store = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")

    assert_store(store)
    assert store["store_code"] == "HD-101"
    assert store["region_code"] == "MIDWEST"
    assert store["state_code"] == "IL"
    assert store["distance_rank"] == 1
    assert store["will_call_bay_slots"] == 2
    assert store["lift_gate_available"] is True
    assert _rate_equals(store["tax_rate_pct"], 0.0825)
    assert store["max_stage_hours"] == 48
    assert store["version"] == 1
    assert _instant_equals(store["created_at"], CLOCK_START)


# --------------------------------------------------------------------------- #
# Pro account read                                                            #
# --------------------------------------------------------------------------- #


def test_get_pro_account_reports_stored_inputs_and_reviewed_tier(api):
    """PRD §2.9: "**`PLATINUM`** opens once trailing volume reaches two hundred thousand dollars. It grants an 8 percent discount, accrues rebate at 2.0 percent, and permits quote terms of at most 60 days."
    PRD §2.9: "Each opening figure is an **inclusive** lower bound: an account sitting exactly on a rung's opening volume qualifies for that rung."
    PRD §3.2: "Opening the account immediately performs a **tier review**, so a newly created account already reports a `trailing_volume_cents`, a `tier_code`, a `tier_discount_pct` and a `tier_reviewed_at` stamp rather than nulls."
    PRD §3.2: "Each of them recomputes all three tier figures and re-stamps `tier_reviewed_at` with the current logical clock instant."
    PRD §3.2: "An account's `status` begins at `ACTIVE` and takes only one other value, `HOLD`."
    PRD §3.4: "That derived array holds exactly those `state_code` values for which the account has a certificate whose `status` is `VERIFIED` and whose `expires_on` is strictly after the current clock date — the same strict comparison, applied continuously, so a verified certificate silently drops out of the array on the day it expires without any transition being recorded against it."

    Design: Corner/entities/get_pro_account_returns_stored_and_computed_fields
    """
    store = create_store()
    account = create_pro_account(
        store["id"],
        business_name="Platinum Builders",
        po_required=True,
        job_name_required=True,
        tier_review_mode="PINNED_AT_REVIEW",
        baseline_volume_cents=20_000_000,
    )

    account = validate_success(
        api.get_pro_account(account["id"], PRO_DESK_ASSOCIATE), expected_status=200
    )

    assert_pro_account(account)
    assert account["business_name"] == "Platinum Builders"
    assert account["home_store_id"] == store["id"]
    assert account["po_required"] is True
    assert account["job_name_required"] is True
    assert account["trailing_volume_cents"] == 20_000_000
    assert account["tier_code"] == "PLATINUM"
    assert _rate_equals(account["tier_discount_pct"], 0.08)
    assert account["tax_exempt_state_codes"] == []
    assert account["status"] == "ACTIVE"
    assert _instant_equals(account["tier_reviewed_at"], CLOCK_START)


# --------------------------------------------------------------------------- #
# Listing and pagination                                                      #
# --------------------------------------------------------------------------- #


def test_list_stores_window_reports_total_count_and_has_more(api):
    """PRD §2.3: "`limit` caps the number of records returned; it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum accepted value is 100."
    PRD §2.3: "`offset` is the number of records to skip before the page begins; it defaults to 0."
    PRD §2.3: "List responses carry four pagination fields inside the envelope's `meta` object: `limit`, `offset`, `total_count` (the number of records matching the filter before the page window is applied) and `has_more` (true when records remain beyond the current window)."

    Design: Corner/entities/list_stores_pagination_envelope_and_limit_bounds
    """
    create_store(store_code="HD-101", distance_rank=1)
    create_store(store_code="HD-102", distance_rank=2)
    create_store(store_code="HD-103", distance_rank=3, lift_gate_available=False, max_stage_hours=24)

    windowed = api.list_stores(PLATFORM_ADMIN, params={"limit": 2, "offset": 0})
    rows, meta = validate_paginated(windowed)
    assert windowed.json()["response_type"] == "array"
    assert len(rows) == 2
    assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)

    defaulted = api.list_stores(PLATFORM_ADMIN)
    all_rows, default_meta = validate_paginated(defaulted)
    assert len(all_rows) == 3
    assert_pagination_meta(default_meta, limit=10, offset=0, total_count=3, has_more=False)


def test_list_stores_rejects_a_limit_above_the_accepted_maximum(api):
    """PRD §2.3: "A `limit` outside the range of 1 through 100 inclusive is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/list_stores_pagination_envelope_and_limit_bounds
    """
    create_store(store_code="HD-101", distance_rank=1)
    create_store(store_code="HD-102", distance_rank=2)
    create_store(store_code="HD-103", distance_rank=3)

    response = api.list_stores(PLATFORM_ADMIN, params={"limit": 101, "offset": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


# --------------------------------------------------------------------------- #
# Per-entity not-found sweep                                                  #
# --------------------------------------------------------------------------- #


NOT_FOUND_PROBES = [
    ("get_store", PLATFORM_ADMIN, ApiErrorId.ERR_STORE_NOT_FOUND),
    ("get_store_stock", PLATFORM_ADMIN, ApiErrorId.ERR_STORE_STOCK_NOT_FOUND),
    ("get_delivery_truck", STORE_OPERATIONS, ApiErrorId.ERR_DELIVERY_TRUCK_NOT_FOUND),
    ("get_pro_account", PLATFORM_ADMIN, ApiErrorId.ERR_PRO_ACCOUNT_NOT_FOUND),
    ("get_credit_line", CREDIT_MANAGER, ApiErrorId.ERR_CREDIT_LINE_NOT_FOUND),
    (
        "get_tax_exempt_certificate",
        TAX_COMPLIANCE_OFFICER,
        ApiErrorId.ERR_TAX_EXEMPT_CERTIFICATE_NOT_FOUND,
    ),
    ("get_job_quote", PRO_DESK_ASSOCIATE, ApiErrorId.ERR_JOB_QUOTE_NOT_FOUND),
    ("get_quote_line", PRO_DESK_ASSOCIATE, ApiErrorId.ERR_QUOTE_LINE_NOT_FOUND),
    ("get_pro_order", PRO_DESK_ASSOCIATE, ApiErrorId.ERR_PRO_ORDER_NOT_FOUND),
    ("get_order_line", PRO_DESK_ASSOCIATE, ApiErrorId.ERR_ORDER_LINE_NOT_FOUND),
    ("get_reservation", STORE_OPERATIONS, ApiErrorId.ERR_RESERVATION_NOT_FOUND),
    (
        "get_will_call_staging",
        STORE_OPERATIONS,
        ApiErrorId.ERR_WILL_CALL_STAGING_NOT_FOUND,
    ),
    (
        "get_delivery_appointment",
        STORE_OPERATIONS,
        ApiErrorId.ERR_DELIVERY_APPOINTMENT_NOT_FOUND,
    ),
    ("get_rebate_accrual", CREDIT_MANAGER, ApiErrorId.ERR_REBATE_ACCRUAL_NOT_FOUND),
    ("get_return_request", CREDIT_MANAGER, ApiErrorId.ERR_RETURN_REQUEST_NOT_FOUND),
]


@pytest.mark.parametrize(
    "read_method,headers,expected_error",
    NOT_FOUND_PROBES,
    ids=[probe[0] for probe in NOT_FOUND_PROBES],
)
def test_unknown_identifier_returns_that_entitys_own_not_found(
    api, read_method, headers, expected_error
):
    """PRD §2.8: "Each resource type has its own not-found identifier and all of them return HTTP 404: `ERR_STORE_NOT_FOUND`, `ERR_STORE_STOCK_NOT_FOUND`, `ERR_DELIVERY_TRUCK_NOT_FOUND`, `ERR_PRO_ACCOUNT_NOT_FOUND`, `ERR_CREDIT_LINE_NOT_FOUND`, `ERR_TAX_EXEMPT_CERTIFICATE_NOT_FOUND`, `ERR_JOB_QUOTE_NOT_FOUND`, `ERR_QUOTE_LINE_NOT_FOUND`, `ERR_PRO_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_WILL_CALL_STAGING_NOT_FOUND`, `ERR_DELIVERY_APPOINTMENT_NOT_FOUND`, `ERR_REBATE_ACCRUAL_NOT_FOUND` and `ERR_RETURN_REQUEST_NOT_FOUND`."
    PRD §2.11: "**Path resolution** — every identifier in the path resolves, left to right, otherwise that resource type's not-found error."

    Design: Corner/entities/unknown_ids_return_entity_specific_not_found
    """
    response = getattr(api, read_method)(FABRICATED_ID, headers)
    validate_error(response, expected_error.value, expected_status=404)
    assert response.json()["response_type"] == "error"


# --------------------------------------------------------------------------- #
# Required fields                                                             #
# --------------------------------------------------------------------------- #


def test_create_pro_order_without_payment_method_is_rejected_and_persists_nothing(api):
    """PRD §3.6: "The order declares its `payment_method`, either `CREDIT_LINE` or `CARD`, and its `delivery_mode`, either `WILL_CALL` or `DELIVERY`."
    PRD §2.11: "**Request shape** — required fields are present, enum-valued fields hold declared values, integers meet their declared minimums, ISO 8601 instants and ISO dates parse, and `lines` and `line_prices` arrays are non-empty; otherwise `ERR_INVALID_REQUEST`."
    PRD §3.6: "A new order sits at `fulfillment_status` `DRAFT` and `credit_status` `UNBILLED`, with every money field null until it is priced."

    Design: Corner/entities/create_pro_order_missing_required_fields_returns_invalid_request
    """
    store = create_store()
    account = create_pro_account(store["id"])
    headers = make_contractor_admin_headers(account["id"])

    missing = api.create_pro_order(
        {
            "pro_account_id": account["id"],
            "fulfillment_store_id": store["id"],
            "delivery_mode": "WILL_CALL",
        },
        headers,
    )
    validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    complete = api.create_pro_order(
        create_pro_order_payload(
            account["id"], store["id"], payment_method="CARD", delivery_mode="WILL_CALL"
        ),
        headers,
    )
    order = validate_success(complete, expected_status=201)
    assert_pro_order(order)
    assert order["payment_method"] == "CARD"
    assert order["fulfillment_status"] == "DRAFT"

    rows, _ = validate_paginated(
        api.list_pro_orders(headers, params={"pro_account_id": account["id"]})
    )
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# Declared defaults                                                           #
# --------------------------------------------------------------------------- #


def test_create_pro_account_without_optional_inputs_applies_declared_defaults(api):
    """PRD §3.2: "Two coding switches are pinned at this moment: `po_required`, which when true forces every order submission for this account to carry a non-empty `po_number`, and `job_name_required`, which when true forces every order submission to carry a non-empty `job_name`. Both default to false."
    PRD §3.2: "`baseline_volume_cents`, a non-negative integer defaulting to 0, is trailing volume carried over from the legacy system and is always counted in the trailing window regardless of dates."
    PRD §3.2: "`tier_review_mode` selects which of two tier-determination variants prices this account's orders; it takes the values `PINNED_AT_REVIEW` and `ROLLING_365_INCLUSIVE` and defaults to `PINNED_AT_REVIEW`."
    PRD §3.2: "An account's `status` begins at `ACTIVE` and takes only one other value, `HOLD`."
    PRD §2.9: "**`MEMBER`** opens at zero trailing volume. It grants no discount, accrues no rebate, and permits quote terms of at most 15 days."

    Design: Corner/entities/create_pro_account_omitting_optional_inputs_applies_declared_defaults
    """
    store = create_store()

    response = api.create_pro_account(
        {"business_name": "Bare Minimum LLC", "home_store_id": store["id"]},
        PLATFORM_ADMIN,
    )
    account = validate_success(response, expected_status=201)

    assert_pro_account(account)
    assert account["po_required"] is False
    assert account["job_name_required"] is False
    assert account["tier_review_mode"] == "PINNED_AT_REVIEW"
    assert account["baseline_volume_cents"] == 0
    assert account["trailing_volume_cents"] == 0
    assert account["tier_code"] == "MEMBER"
    assert _rate_equals(account["tier_discount_pct"], 0.00)
    assert account["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Server-computed fields                                                      #
# --------------------------------------------------------------------------- #


def test_new_store_stock_starts_with_no_units_reserved(api):
    """PRD §3.1: "A freshly opened position starts with `reserved_units` at 0 and `available_units` equal to `on_hand_units`."
    PRD §3.1: "Those two fields are never written by a client."
    PRD §3.1: "It is opened with the owning `store_id`, the `sku` code, the `on_hand_units` physically present (which may legitimately be zero) and the `list_unit_price_cents` at which that store lists the item — at least 1 cent, undiscounted."
    PRD §2.5: "**`version`** (integer): a monotonically increasing counter that starts at 1 when the record is created and increases by one on every mutation."

    Design: Corner/entities/store_stock_computed_units_start_at_zero_reserved
    """
    store = create_store()

    response = api.create_store_stock(
        create_store_stock_payload(
            store["id"],
            SKU_SHINGLE_BUNDLE,
            on_hand_units=600,
            list_unit_price_cents=LIST_PRICE_CENTS[SKU_SHINGLE_BUNDLE],
        ),
        PLATFORM_ADMIN,
    )
    stock = validate_success(response, expected_status=201)

    assert_store_stock(stock)
    assert stock["on_hand_units"] == 600
    assert stock["reserved_units"] == 0
    assert stock["available_units"] == 600
    assert stock["list_unit_price_cents"] == 1_999
    assert stock["version"] == 1


# --------------------------------------------------------------------------- #
# Server-generated system fields                                              #
# --------------------------------------------------------------------------- #


def test_pro_order_system_fields_ignore_client_supplied_values(api):
    """PRD §2.5: "**`id`** (string): a server-minted UUID. It carries no type prefix and no domain-specific encoding; a caller must never construct one."
    PRD §2.5: "**`version`** (integer): a monotonically increasing counter that starts at 1 when the record is created and increases by one on every mutation."
    PRD §3.6: "A new order sits at `fulfillment_status` `DRAFT` and `credit_status` `UNBILLED`, with every money field null until it is priced."
    PRD §3.6: "On success the server writes `tier_code_applied`, every order-line price field and every order money field, stamps `priced_at` with the current clock instant, recomputes the credit line's `exposure_cents` and `available_cents`, and increments the order's `version`."

    Design: Corner/entities/pro_order_system_fields_are_server_generated_and_input_ignored
    """
    store = create_store()
    account = create_pro_account(store["id"])
    headers = make_contractor_admin_headers(account["id"])

    smuggled_id = "11111111-1111-4111-8111-111111111111"
    response = api.create_pro_order(
        {
            "pro_account_id": account["id"],
            "fulfillment_store_id": store["id"],
            "payment_method": "CARD",
            "delivery_mode": "WILL_CALL",
            "fulfillment_status": "RESERVED",
            "credit_status": "PAID",
            "id": smuggled_id,
            "version": 99,
            "total_cents": 1,
        },
        headers,
    )
    order = validate_success(response, expected_status=201)

    assert order["id"] != smuggled_id
    assert is_valid_uuid(order["id"])
    assert order["fulfillment_status"] == "DRAFT"
    assert order["credit_status"] == "UNBILLED"
    assert order["version"] == 1
    assert order["total_cents"] is None
    assert order["subtotal_cents"] is None
    assert order["priced_at"] is None


# --------------------------------------------------------------------------- #
# Enum and minimum-value constraints                                          #
# --------------------------------------------------------------------------- #


def test_enum_and_minimum_value_violations_are_rejected_on_write(api):
    """PRD §2.11: "**Request shape** — required fields are present, enum-valued fields hold declared values, integers meet their declared minimums, ISO 8601 instants and ISO dates parse, and `lines` and `line_prices` arrays are non-empty; otherwise `ERR_INVALID_REQUEST`."
    PRD §3.6: "The order declares its `payment_method`, either `CREDIT_LINE` or `CARD`, and its `delivery_mode`, either `WILL_CALL` or `DELIVERY`."
    PRD §3.6: "**Order lines** are added while the order is in `DRAFT`, each naming a `sku` and a `qty_units` of at least 1, with one line per SKU per order."
    PRD §3.3: "A `CreditManager` extends terms by opening a **credit line** for an account, naming the `pro_account_id`, the `limit_cents` ceiling (at least 1 cent) and the `terms_days` net payment terms (at least 1 day)."
    PRD §3.8: "It is created naming the `pro_order_id` being scheduled, the `delivery_truck_id` that will run it, the `window_start` and `window_end` bounding the promised window — both inclusive — and the `jobsite_access_type`, one of `CURBSIDE`, `DRIVEWAY`, `NARROW_ALLEY` or `CRANE_REQUIRED`."

    Design: Corner/entities/enum_and_positive_integer_constraints_rejected_on_write
    """
    store, _ = setup_store_with_stock([(SKU_SHINGLE_BUNDLE, 600)])
    account = create_pro_account(store["id"])
    headers = make_contractor_admin_headers(account["id"])
    truck = create_delivery_truck(
        store["id"], truck_code="T-1", access_types_supported=["CURBSIDE"]
    )
    order = validate_success(
        api.create_pro_order(
            create_pro_order_payload(
                account["id"], store["id"], payment_method="CARD", delivery_mode="WILL_CALL"
            ),
            headers,
        ),
        expected_status=201,
    )

    undeclared_mode = api.create_pro_order(
        create_pro_order_payload(
            account["id"], store["id"], payment_method="CARD", delivery_mode="AIRDROP"
        ),
        headers,
    )
    validate_error(
        undeclared_mode, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
    )

    zero_qty = api.create_order_line(
        order["id"], create_order_line_payload(SKU_SHINGLE_BUNDLE, 0), headers
    )
    validate_error(zero_qty, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    zero_limit = api.create_credit_line(
        {"pro_account_id": account["id"], "limit_cents": 0, "terms_days": 30},
        CREDIT_MANAGER,
    )
    validate_error(zero_limit, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    undeclared_access = api.create_delivery_appointment(
        create_delivery_appointment_payload(
            order["id"], truck["id"], jobsite_access_type="HELICOPTER"
        ),
        STORE_OPERATIONS,
    )
    validate_error(
        undeclared_access, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
    )

    lines, _ = validate_paginated(api.list_order_lines_of_order(order["id"], headers))
    assert lines == []

    credit_lines, _ = validate_paginated(
        api.list_credit_lines(CREDIT_MANAGER, params={"pro_account_id": account["id"]})
    )
    assert credit_lines == []


# --------------------------------------------------------------------------- #
# Body-reference resolution                                                   #
# --------------------------------------------------------------------------- #


def test_body_references_that_do_not_resolve_report_the_referenced_types_error(api):
    """PRD §2.8: "The same treatment applies to references carried in a request body, and the error is the one belonging to the referenced resource type, not to the resource being created."
    PRD §2.8: "A `pro_account_id` that does not resolve yields `ERR_PRO_ACCOUNT_NOT_FOUND`; a `home_store_id`, `originating_store_id` or `fulfillment_store_id` that does not resolve yields `ERR_STORE_NOT_FOUND`; a `job_quote_id` yields `ERR_JOB_QUOTE_NOT_FOUND`; a `delivery_truck_id` yields `ERR_DELIVERY_TRUCK_NOT_FOUND`; a `quote_line_id` named inside a counter-offer's `line_prices` that is not a line of the target quote yields `ERR_QUOTE_LINE_NOT_FOUND`; an `order_line_id` named inside a return's `lines` that is not a line of the target order yields `ERR_ORDER_LINE_NOT_FOUND`."
    PRD §2.11: "**Body reference resolution** — every foreign key in the body resolves (`pro_account_id`, `home_store_id`, `fulfillment_store_id`, `job_quote_id`, `delivery_truck_id`, and each `order_line_id` inside a return's `lines`), otherwise that resource type's not-found error."

    Design: Corner/entities/create_credit_line_for_unknown_account_returns_pro_account_not_found
    """
    store = create_store()

    unknown_account = api.create_credit_line(
        {"pro_account_id": FABRICATED_ID, "limit_cents": 500_000, "terms_days": 30},
        CREDIT_MANAGER,
    )
    validate_error(
        unknown_account, ApiErrorId.ERR_PRO_ACCOUNT_NOT_FOUND.value, expected_status=404
    )

    unknown_store = api.create_store_stock(
        create_store_stock_payload(
            FABRICATED_ID, SKU_SHINGLE_BUNDLE, on_hand_units=10, list_unit_price_cents=1_999
        ),
        PLATFORM_ADMIN,
    )
    validate_error(
        unknown_store, ApiErrorId.ERR_STORE_NOT_FOUND.value, expected_status=404
    )

    credit_lines, _ = validate_paginated(api.list_credit_lines(CREDIT_MANAGER))
    assert credit_lines == []

    stocks, _ = validate_paginated(
        api.list_store_stocks(PLATFORM_ADMIN, params={"store_id": store["id"]})
    )
    assert stocks == []


def test_order_bound_to_another_accounts_quote_is_refused_at_creation(api):
    """PRD §3.6: "It may optionally name a `job_quote_id` to bind negotiated prices — a quote belonging to a different account is refused at creation with `ERR_QUOTE_ACCOUNT_MISMATCH` — and may optionally carry a `po_number` and a `job_name` for coding."
    PRD §2.11: "**Quote belongs to the account** — the order's `job_quote_id` names a quote of the same `pro_account_id` as the order, otherwise `ERR_QUOTE_ACCOUNT_MISMATCH`."

    Design: Corner/entities/order_bound_to_another_accounts_quote_is_rejected
    """
    store, _ = setup_store_with_stock([(SKU_SHINGLE_BUNDLE, 600)])
    account_a = create_pro_account(store["id"], business_name="Account A Roofing")
    account_b = create_pro_account(store["id"], business_name="Account B Framing")

    quote_a = validate_success(
        api.create_job_quote(
            create_job_quote_payload(
                account_a["id"], store["id"], job_name="A-JOB", requested_term_days=30
            ),
            make_contractor_admin_headers(account_a["id"]),
        ),
        expected_status=201,
    )

    headers_b = make_contractor_admin_headers(account_b["id"])
    response = api.create_pro_order(
        create_pro_order_payload(
            account_b["id"],
            store["id"],
            job_quote_id=quote_a["id"],
            payment_method="CARD",
            delivery_mode="WILL_CALL",
        ),
        headers_b,
    )
    validate_error(
        response, ApiErrorId.ERR_QUOTE_ACCOUNT_MISMATCH.value, expected_status=422
    )

    orders, _ = validate_paginated(
        api.list_pro_orders(headers_b, params={"pro_account_id": account_b["id"]})
    )
    assert orders == []

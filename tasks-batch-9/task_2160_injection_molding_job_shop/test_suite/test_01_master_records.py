"""Master records: registering customers, presses and tools, and reading them back."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    api_client,
    assert_customer,
    assert_mold,
    assert_press,
    create_customer,
    create_mold,
    create_mold_payload,
    create_press,
    create_production_job_payload,
    create_quote,
    create_quote_payload,
    is_valid_uuid,
    price_quote,
    set_clock,
    setup_approved_tool,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["plant_admin_headers"]
SE = TEST_USERS["sales_engineer_headers"]
PE = TEST_USERS["process_engineer_headers"]

UNKNOWN_MOLD_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_JOB_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_CUSTOMER_ID = "00000000-0000-4000-8000-0000000000ff"


def test_customer_registration_returns_201_with_minted_identity_and_default_hold(api):
    """PRD §4: "A request that creates a new resource answers with HTTP 201; every
    other successful request — reads, state transitions, decisions, settlements and
    the clock control — answers with HTTP 200."
    PRD §3.1: "A **customer** is registered with a legal `name` and a short `code`
    that must be between 2 and 16 characters and unique across all customers; an
    optional `credit_hold` flag may be supplied at registration and defaults to
    false when it is omitted."
    PRD §2.4: "The `version` of a resource starts at 1 when the resource is created
    and is incremented by exactly 1 on every mutation of that resource, and
    `updated_at` is refreshed to the current logical time on the same mutation."

    Design: Corner/entities/customer_creation_returns_201_with_system_fields_and_defaults
    """
    set_clock()

    response = api.create_customer({"name": "Acme Controls", "code": "ACME"}, PA)
    data = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert_customer(data)
    assert data["credit_hold"] is False, "credit_hold defaults to false when omitted"
    assert data["version"] == 1, "version starts at 1 when the resource is created"
    assert is_valid_uuid(data["id"]), "id is a UUID with no type prefix"
    assert not data["id"].startswith("cust"), "the id carries no type prefix"


def test_press_read_echoes_its_inputs_and_its_initial_ledger(api):
    """PRD §3.1: "A newly registered press begins with `status` `AVAILABLE` and
    `committed_minutes_scheduled` at 0."
    PRD §3.1: "A **press** is registered with a `press_code` unique across all
    machines, a clamp `tonnage` of at least 1, a `shot_size_grams_max` of at least
    1 giving the largest shot mass the barrel can deliver in grams, and an
    `hourly_rate_cents` of at least 1 that is the machine burden rate every cost
    roll in the system reads."

    Design: Corner/entities/press_retrieval_returns_stored_and_computed_fields
    """
    set_clock()
    press = create_press()

    data = validate_success(api.get_press(press["id"], PE))

    assert_press(data)
    assert data["tonnage"] == 150
    assert data["hourly_rate_cents"] == 7200
    assert data["shot_size_grams_max"] == 400
    assert data["press_code"] == "P-150"
    assert data["status"] == "AVAILABLE"
    assert data["committed_minutes_scheduled"] == 0


def test_mold_listing_reports_total_count_before_pagination(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of records
    matching the filters before pagination is applied and `has_more` is true when
    records remain beyond the current page."

    Design: Corner/entities/mold_listing_paginates_with_total_count_and_has_more
    """
    set_clock()
    customer = create_customer()
    for code in ("M-A", "M-B", "M-C"):
        create_mold(
            customer["id"],
            mold_code=code,
            cavity_count=2,
            shot_weight_grams=90,
            required_min_tonnage=60,
            required_max_tonnage=120,
            pm_interval_shots=5000,
            tooling_cost_cents=100000,
        )

    response = api.list_molds(PA, params={"limit": 2, "offset": 1})
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert meta["total_count"] == 3, "total_count counts the population before pagination"
    assert meta["has_more"] is False, "no records remain beyond offset 1 with limit 2"
    assert len(rows) == 2, f"Expected 2 rows on the page, got {len(rows)}"


def test_mold_read_with_unknown_id_returns_the_molds_own_not_found_code(api):
    """PRD §2.4: "Where an endpoint does carry path parameters, they are resolved
    strictly left to right, and the first segment that names a resource which does
    not exist determines the error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRESS_NOT_FOUND`,
    `ERR_MOLD_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
    `ERR_PPAP_SUBMISSION_NOT_FOUND`, `ERR_RESIN_LOT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_MAINTENANCE_ORDER_NOT_FOUND`,
    `ERR_TOOL_TRANSFER_NOT_FOUND` or `ERR_CAPACITY_COMMIT_NOT_FOUND`, each with
    HTTP 404."

    Design: Corner/entities/mold_get_with_unknown_id_returns_mold_not_found
    """
    set_clock()

    response = api.get_mold(UNKNOWN_MOLD_ID, PA)

    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_MOLD_NOT_FOUND.value)


def test_job_read_with_unknown_id_returns_the_jobs_own_not_found_code(api):
    """PRD §2.4: "Where an endpoint does carry path parameters, they are resolved
    strictly left to right, and the first segment that names a resource which does
    not exist determines the error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRESS_NOT_FOUND`,
    `ERR_MOLD_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
    `ERR_PPAP_SUBMISSION_NOT_FOUND`, `ERR_RESIN_LOT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_MAINTENANCE_ORDER_NOT_FOUND`,
    `ERR_TOOL_TRANSFER_NOT_FOUND` or `ERR_CAPACITY_COMMIT_NOT_FOUND`, each with
    HTTP 404."

    Design: Corner/entities/production_job_get_with_unknown_id_returns_job_not_found
    """
    set_clock()

    response = api.get_production_job(UNKNOWN_JOB_ID, PE)

    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_JOB_NOT_FOUND.value)


def test_mold_registration_without_cavity_count_is_rejected(api):
    """PRD §2.7: "Every required body field is present, every type is correct, every
    enum member is recognized, every integer sits inside its declared range, and
    pagination parameters are in range — otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "A **mold** — the tool itself — is registered with a `mold_code`
    unique across all tools, the `customer_id` of the customer whose part program it
    runs, a `cavity_count` of at least 1 giving the parts produced per shot, a
    `shot_weight_grams` of at least 1 covering the total shot mass including the
    runner, a tonnage band expressed as `required_min_tonnage` and
    `required_max_tonnage` where the maximum must be at least the minimum and both
    are at least 1, a `pm_interval_shots` of at least 1 giving the shots between
    preventive maintenance events, and a `tooling_cost_cents` of at least 0 that is
    the capitalised tool cost."

    Design: Corner/entities/mold_create_without_cavity_count_returns_invalid_request
    """
    set_clock()
    customer = create_customer()
    payload = create_mold_payload(customer["id"])
    payload.pop("cavity_count")

    response = api.create_mold(payload, PA)

    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(
        api.list_molds(PA, params={"customer_id": customer["id"]})
    )
    assert meta["total_count"] == 0, "the rejected request must not have created a tool"


def test_new_tool_and_customer_land_on_their_declared_defaults(api):
    """PRD §3.1: "An `ownership` value of `SHOP_OWNED` or `CUSTOMER_OWNED` may be
    supplied and defaults to `SHOP_OWNED`. A new tool starts with `status` `NEW`,
    `service_state` `SERVICEABLE`, `total_shot_count` and `shots_since_pm` both at
    0, and `approved_max_regrind_bp`, `interim_expiry_shots` and
    `active_transfer_id` all unset."
    PRD §3.1: "an optional `credit_hold` flag may be supplied at registration and
    defaults to false when it is omitted."

    Design: Corner/entities/mold_and_customer_creation_apply_declared_defaults
    """
    set_clock()
    customer = create_customer()
    payload = create_mold_payload(customer["id"])
    payload.pop("ownership", None)

    mold = validate_success(api.create_mold(payload, PA), 201)

    assert_mold(mold)
    assert mold["ownership"] == "SHOP_OWNED"
    assert mold["status"] == "NEW"
    assert mold["service_state"] == "SERVICEABLE"
    assert mold["total_shot_count"] == 0
    assert mold["shots_since_pm"] == 0
    assert mold.get("approved_max_regrind_bp") is None
    assert mold.get("interim_expiry_shots") is None
    assert mold.get("active_transfer_id") is None
    assert customer["credit_hold"] is False


def test_quote_price_fields_stay_unset_until_the_quote_is_priced(api):
    """PRD §3.3: "A new quote's `status` is `DRAFT` and no price exists yet."
    PRD §3.3: "Whichever way the machine is determined, its id is recorded on the
    quote as `rate_press_id`, and the quote moves `DRAFT → PRICED`."
    PRD §3.3: "Pricing a quote writes the lot figure to `quoted_lot_price_cents` and
    the per-piece figure to `quoted_piece_price_cents`."

    Design: Corner/entities/quote_price_fields_are_computed_and_null_before_pricing
    """
    set_clock()
    customer = create_customer()
    press = create_press()
    mold = create_mold(customer["id"])
    quote = create_quote(customer["id"], mold["id"])

    before = validate_success(api.get_quote(quote["id"], SE))
    assert before["status"] == "DRAFT"
    assert before.get("quoted_piece_price_cents") is None
    assert before.get("quoted_lot_price_cents") is None
    assert before.get("margin_bp") is None
    assert before.get("rate_press_id") is None

    after = validate_success(api.price_quote(quote["id"], {"press_id": press["id"]}, SE))
    assert after["status"] == "PRICED"
    assert after["quoted_piece_price_cents"] == 95
    assert after["rate_press_id"] == press["id"]


def test_mold_registration_with_an_unrecognised_ownership_value_is_rejected(api):
    """PRD §2.7: "Every required body field is present, every type is correct, every
    enum member is recognized, every integer sits inside its declared range, and
    pagination parameters are in range — otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "An `ownership` value of `SHOP_OWNED` or `CUSTOMER_OWNED` may be
    supplied and defaults to `SHOP_OWNED`."

    Design: Corner/entities/mold_create_with_unknown_ownership_enum_returns_invalid_request
    """
    set_clock()
    customer = create_customer()

    response = api.create_mold(
        create_mold_payload(customer["id"], ownership="LEASED"), PA
    )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_job_opened_with_a_start_after_its_end_is_rejected_as_an_invalid_window(api):
    """PRD §2.4: "A window whose start is not strictly before its end, or whose
    endpoints are not whole-minute UTC instants, is rejected with
    `ERR_INVALID_WINDOW` (HTTP 400)."
    PRD §3.6: "The request names the `quote_id`, a `planned_qty` of at least 1
    giving the good parts the job is expected to deliver, and the press occupancy
    window as `scheduled_start` and `scheduled_end`, whose end must be strictly
    after its start."

    Design: Corner/entities/production_job_create_with_start_after_end_is_rejected
    """
    shop = setup_approved_tool(with_lot=False)

    response = api.create_production_job(
        create_production_job_payload(
            shop["quote"]["id"],
            planned_qty=1000,
            scheduled_start="2026-09-10T16:00:00Z",
            scheduled_end="2026-09-10T08:00:00Z",
            press_id=shop["press"]["id"],
        ),
        PE,
    )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_INVALID_WINDOW.value)

    _, meta = validate_paginated(
        api.list_production_jobs(PE, params={"quote_id": shop["quote"]["id"]})
    )
    assert meta["total_count"] == 0, "the rejected window must not have opened a job"


def test_mold_registration_against_an_unknown_customer_is_rejected(api):
    """PRD §2.4: "The same catalogue answers a foreign key carried in a request body
    that does not resolve, and body-carried foreign keys are checked in the order in
    which the endpoint's input fields are listed."
    PRD §2.7: "Every `*_id` carried in the body resolves, in the order the endpoint
    lists its inputs, or the matching not-found error (404)."

    Design: Corner/entities/mold_create_with_unknown_customer_returns_customer_not_found
    """
    set_clock()

    response = api.create_mold(create_mold_payload(UNKNOWN_CUSTOMER_ID), PA)

    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_mold_list_composes_filters_before_it_paginates(api):
    """PRD §2.3: "Molds may be filtered by `customer_id`, `status`, `service_state`
    and `ownership`."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of records
    matching the filters before pagination is applied and `has_more` is true when
    records remain beyond the current page."
    PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/cross_cutting_layers/mold_list_combines_status_filter_ownership_filter_and_pagination
    """
    set_clock()
    acme = create_customer()
    beta = create_customer(name="Beta Devices", code="BETA")
    for code in ("M-S1", "M-S2"):
        create_mold(acme["id"], mold_code=code, ownership="SHOP_OWNED")
    for code in ("M-C1", "M-C2"):
        create_mold(acme["id"], mold_code=code, ownership="CUSTOMER_OWNED")
    create_mold(beta["id"], mold_code="M-B1", ownership="SHOP_OWNED")

    rows, meta = validate_paginated(
        api.list_molds(
            PA,
            params={
                "customer_id": acme["id"],
                "ownership": "CUSTOMER_OWNED",
                "limit": 1,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 2, "the filtered population, not the whole table"
    assert meta["has_more"] is True
    assert len(rows) == 1
    for row in rows:
        assert row["ownership"] == "CUSTOMER_OWNED"
        assert row["customer_id"] == acme["id"]

    _, status_meta = validate_paginated(
        api.list_molds(
            PA,
            params={"customer_id": acme["id"], "status": "NEW", "limit": 100, "offset": 0},
        )
    )
    assert status_meta["total_count"] == 4
    assert status_meta["has_more"] is False

    over_limit = api.list_molds(PA, params={"limit": 101, "offset": 0})
    assert over_limit.status_code == 400, f"Expected 400, got {over_limit.status_code}"
    validate_error(over_limit, ApiErrorId.ERR_INVALID_REQUEST.value)

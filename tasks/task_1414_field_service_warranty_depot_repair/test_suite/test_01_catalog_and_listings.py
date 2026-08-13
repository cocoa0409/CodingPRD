"""Catalog registration, payload validation, RBAC entry gates, and listings."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_customer,
    assert_unit,
    create_customer,
    create_customer_payload,
    create_model,
    create_part,
    create_part_payload,
    create_unit,
    create_unit_payload,
    get_customer,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers.fixtures import create_draft_rma


def test_customer_creation_applies_defaults(api):
    """PRD §3.1: "An `IntakeAgent` registers each customer with a `name` and an
    `email` address — the notification recipient, unique across customers — and
    optionally a `credit_limit_cents` (defaulting to 100000 cents, the maximum
    outstanding loaner deposit exposure the customer may carry) and a
    `loyalty_tier` of `STANDARD` or `PREFERRED` (defaulting to `STANDARD`)."
    PRD §3.1: "A fresh customer's `deposit_exposure_cents` starts at 0"

    Design: Corner/entities/customer_creation_applies_defaults
    """
    res = api.create_customer(create_customer_payload(name="Cust A"),
                              TEST_USERS["intake_agent_headers"])
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["credit_limit_cents"] == 100000, (
        f"default credit_limit_cents must be 100000, got {customer['credit_limit_cents']}")
    assert customer["loyalty_tier"] == "STANDARD", (
        f"default loyalty_tier must be STANDARD, got {customer['loyalty_tier']}")
    assert customer["deposit_exposure_cents"] == 0, (
        f"fresh customer exposure must start at 0, got {customer['deposit_exposure_cents']}")
    assert isinstance(customer["version"], int)

    reread = validate_success(
        api.get_customer(customer["id"], TEST_USERS["intake_agent_headers"]), 200)
    assert reread["credit_limit_cents"] == 100000
    assert reread["deposit_exposure_cents"] == 0


def test_unit_creation_duplicate_serial_rejected(api):
    """PRD §3.1: "An `IntakeAgent` registers each serialized unit with its
    `serial_number` (globally unique across all units — a duplicate is rejected
    with `ERR_DUPLICATE_SERIAL`)"

    Design: Corner/entities/unit_creation_duplicate_serial_rejected
    """
    model = create_model()
    customer = create_customer()
    first = validate_success(api.create_unit(
        create_unit_payload(model["id"], customer["id"], serial_number="SN-DUP-1"),
        TEST_USERS["intake_agent_headers"]), 201)
    assert_unit(first)

    dup = api.create_unit(
        create_unit_payload(model["id"], customer["id"], serial_number="SN-DUP-1"),
        TEST_USERS["intake_agent_headers"])
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_SERIAL)
    assert dup.status_code == 409

    other = api.create_unit(
        create_unit_payload(model["id"], customer["id"], serial_number="SN-DUP-2"),
        TEST_USERS["intake_agent_headers"])
    validate_success(other, 201)


def test_unit_creation_invalid_channel_enum_rejected(api):
    """PRD §2.8: "Generic payload-shape validation — required fields present,
    enum values valid, integers in range such as a `quantity` of at least 1,
    ISO-formatted dates — is the final backstop, evaluated only after every rule
    above, and yields `ERR_VALIDATION` (HTTP 400)."
    PRD §3.1: "the sales `channel` (`RETAIL` or `ENTERPRISE`, which selects the
    warranty basis date)"

    Design: Corner/entities/unit_creation_invalid_channel_enum_rejected
    """
    model = create_model()
    customer = create_customer()
    res = api.create_unit(
        create_unit_payload(model["id"], customer["id"], channel="WHOLESALE"),
        TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_VALIDATION)
    assert res.status_code == 400


def test_unit_creation_missing_required_field_rejected(api):
    """PRD §2.8: "Generic payload-shape validation — required fields present,
    enum values valid, integers in range such as a `quantity` of at least 1,
    ISO-formatted dates — is the final backstop, evaluated only after every rule
    above, and yields `ERR_VALIDATION` (HTTP 400)."
    PRD §3.1: "the `purchase_date` (the `RETAIL` warranty basis), the
    `ship_date` (the `ENTERPRISE` warranty basis — the date the OEM shipped to
    the enterprise), and optionally a `registration_date`."

    Design: Corner/entities/unit_creation_missing_required_field_rejected
    """
    model = create_model()
    customer = create_customer()
    payload = create_unit_payload(model["id"], customer["id"])
    del payload["purchase_date"]
    res = api.create_unit(payload, TEST_USERS["intake_agent_headers"])
    validate_error(res, ApiErrorId.ERR_VALIDATION)
    assert res.status_code == 400


def test_rma_list_pagination_envelope(api):
    """PRD §2.3: "Endpoints that return lists of resources are paginated through
    query parameters. The `limit` parameter caps the number of items returned;
    when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum
    of 100. The `offset` parameter states how many items to skip and defaults to
    0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/rma_list_pagination_and_status_filter
    """
    model = create_model()
    customer = create_customer()
    for _ in range(3):
        unit = create_unit(model["id"], customer["id"])
        create_draft_rma(customer["id"], unit["id"])

    resp = api.list_rmas(TEST_USERS["intake_agent_headers"], params={"limit": 2})
    page1, meta1 = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert len(page1) == 2, f"page 1 must hold 2 items, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    assert meta1["api_request_id"].startswith("req_")

    resp2 = api.list_rmas(TEST_USERS["intake_agent_headers"],
                          params={"limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 1, f"page 2 must hold the last item, got {len(page2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2


def test_units_filtered_list_by_serial_and_customer(api):
    """PRD §3.1: "Units can be listed with filters on `customer_id`,
    `model_id`, or `serial_number`."

    Design: Corner/endpoints/units_filtered_list_by_serial_and_customer
    """
    model = create_model()
    cust_a = create_customer()
    cust_b = create_customer()
    create_unit(model["id"], cust_a["id"], serial_number="SN-F-1")
    create_unit(model["id"], cust_a["id"], serial_number="SN-F-2")
    create_unit(model["id"], cust_b["id"], serial_number="SN-F-9")

    data, meta = validate_paginated(api.list_units(
        TEST_USERS["intake_agent_headers"], params={"serial_number": "SN-F-1"}))
    assert len(data) == 1, f"serial filter must return exactly one unit, got {len(data)}"
    assert data[0]["serial_number"] == "SN-F-1"

    data2, _ = validate_paginated(api.list_units(
        TEST_USERS["intake_agent_headers"], params={"customer_id": cust_a["id"]}))
    assert len(data2) == 2, f"customer filter must return 2 units, got {len(data2)}"
    assert all(u["customer_id"] == cust_a["id"] for u in data2)


def test_technician_cannot_create_part(api):
    """PRD §2.1: "A request whose role is recognized but not listed among the
    roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4: POST /depot/parts is authorized for DepotManager only.

    Design: Corner/rbac/technician_cannot_create_part
    """
    create_customer()  # non-empty DB
    res = api.create_part(create_part_payload(),
                          TEST_USERS["depot_technician_headers"])
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert res.status_code == 403


def test_missing_auth_header_unauthenticated(api):
    """PRD §2.1: "A request with missing headers, or whose `X-User-Role` does
    not name one of these six roles, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    customer = create_customer()
    res = api.get_customer(customer["id"], headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
    assert res.status_code == 401

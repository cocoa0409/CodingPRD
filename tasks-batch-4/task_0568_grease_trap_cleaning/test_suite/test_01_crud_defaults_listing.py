"""CRUD, defaults, computed fields, and nested/filtered listing.

Every test translates exactly one non-stub instance from the corner-design index (queue B).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_customer, assert_equipment, assert_hood_certificate,
    create_customer_payload, create_site_payload, create_equipment_payload,
    create_work_order_payload,
    TEST_USERS, make_technician_headers, NON_EXISTENT_UUID,
    get_success_data,
)
from test_helpers.fixtures import (
    new_customer, new_site, new_equipment, new_technician, new_work_order,
    dispatch_work_order, start_work_order,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_create_customer_returns_201_with_system_defaults(api):
    """PRD §3.1: "A new customer begins in `account_status` `ACTIVE` with
    `outstanding_balance_cents` of 0 and `version` 1."

    Design: Corner/entities/create_customer_returns_201_with_all_fields
    """
    res = api.create_customer(
        create_customer_payload(business_name="New Account", billing_email="n@x.com",
                                credit_limit_cents=250000),
        ADMIN)
    cust = validate_success(res, 201)
    assert_customer(cust)
    assert cust["account_status"] == "ACTIVE", "new customer must start ACTIVE"
    assert cust["version"] == 1, "new customer version must start at 1"
    assert cust["outstanding_balance_cents"] == 0, "new customer balance must start at 0"


def test_create_site_missing_municipality_code_returns_validation(api):
    """PRD §2.11: "Request shape — required fields present, enum values in range, and
    window/period ordering valid; otherwise `ERR_VALIDATION` (400) for general shape problems".

    Design: Corner/entities/create_site_missing_required_field_returns_400
    """
    cust = new_customer(business_name="Req Fields", billing_email="rf@x.com")
    payload = create_site_payload(cust["id"], address="1 Missing St", permit_number="P-Z")
    del payload["municipality_code"]
    res = api.create_site(payload, ADMIN)
    validate_error(res, "ERR_VALIDATION")


def test_get_unknown_customer_returns_not_found(api):
    """PRD §2.10: "the first identifier that does not resolve produces `ERR_NOT_FOUND`
    (HTTP 404) before any later identifier or body reference is examined."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    res = api.get_customer(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_work_order_priority_defaults_to_routine(api):
    """PRD §3.3: "an optional `priority` of `ROUTINE` or `URGENT` defaults to `ROUTINE`."

    Design: Corner/entities/work_order_priority_defaults_to_routine
    """
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"])
    res = api.create_work_order(create_work_order_payload(site["id"], eq["id"]), DISPATCHER)
    wo = validate_success(res, 201)
    assert wo["priority"] == "ROUTINE", "priority must default to ROUTINE"


def test_new_equipment_service_state_is_overdue(api):
    """PRD §3.2: "Because a freshly created piece of equipment has never been serviced,
    it lands with a `service_state` of `OVERDUE`, and adding it re-grades the owning
    site's compliance."

    Design: Corner/entities/new_equipment_service_state_is_overdue
    """
    cust = new_customer()
    site = new_site(cust["id"])
    res = api.create_equipment(create_equipment_payload(site["id"]), ADMIN)
    eq = validate_success(res, 201)
    assert_equipment(eq)
    assert eq["service_state"] == "OVERDUE", "never-serviced equipment must be OVERDUE"


def test_list_site_equipment_returns_array_envelope(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/endpoints/list_site_equipment_returns_array_envelope
    """
    cust = new_customer()
    site = new_site(cust["id"])
    new_equipment(site["id"], equipment_type="GREASE_TRAP")
    new_equipment(site["id"], equipment_type="HOOD", capacity_gallons=0, nominal_frequency_days=90)
    res = api.list_site_equipment(site["id"], ADMIN)
    assert res.json()["response_type"] == "array", "list endpoint must report response_type=array"
    data, meta = validate_paginated(res)
    assert len(data) == 2, "site must list its two equipment records"


def test_filter_work_orders_by_equipment_id(api):
    """PRD §2.10: "The work-order list supports filtering by `site_id`, `equipment_id`,
    `technician_id`, `contract_id`, and `status`".

    Design: Corner/endpoints/filter_work_orders_by_equipment_fk_reverse
    """
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"])
    new_work_order(site["id"], eq["id"])
    res = api.list_work_orders(DISPATCHER, params={"equipment_id": eq["id"]})
    assert res.json()["response_type"] == "array"
    data, meta = validate_paginated(res)
    assert len(data) == 1, "filter must return only the one work order for that equipment"
    assert data[0]["equipment_id"] == eq["id"]


def test_list_work_orders_over_limit_returns_pagination_invalid(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is
    rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/validations/list_work_orders_over_limit_returns_400
    """
    res = api.list_work_orders(DISPATCHER, params={"limit": 200})
    validate_error(res, "ERR_PAGINATION_INVALID")


def test_hood_certificate_happy_path_mints_sticker(api):
    """PRD §3.5: "On issuance the server mints a `sticker_number`, stamps `issued_at`
    with the logical-clock now, and sets `valid_until` to `issued_at` plus the equipment's
    `nominal_frequency_days`."

    Design: Corner/endpoints/hood_certificate_happy_path_issues_sticker
    """
    cust = new_customer()
    site = new_site(cust["id"])
    eq = new_equipment(site["id"], equipment_type="HOOD", capacity_gallons=0, nominal_frequency_days=90)
    tech = new_technician("NFPA96_CERTIFIED")
    wo = new_work_order(site["id"], eq["id"], planned_end="2026-05-10T12:00:00Z")
    dispatch_work_order(wo["id"], tech["id"])
    start_work_order(wo["id"], tech["id"])
    res = api.create_hood_certificate(
        {"work_order_id": wo["id"], "cleanliness_grade": "BARE_METAL_CLEAN"},
        make_technician_headers(tech["id"]))
    cert = validate_success(res, 201)
    assert_hood_certificate(cert)
    assert cert.get("sticker_number"), "hood certificate must carry a minted sticker_number"

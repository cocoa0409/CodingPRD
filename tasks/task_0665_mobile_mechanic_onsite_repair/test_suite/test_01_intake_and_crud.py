"""Service-request intake, retrieval, listing, and field-level CRUD claims.

Translates queue B (Corner) instances in the `entities` and `consistency_model`
sections that exercise creation snapshots, retrieval, pagination, required/typed
fields, defaults, immutability, and system-snapshot fields.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    assert_service_request, assert_catalog_part, assert_part_line,
    make_customer_headers,
    create_service_request_payload, create_catalog_part_payload,
    set_clock, create_customer, create_catalog_part,
    setup_in_progress_request, source_part_line,
    setup_approved_request, approve_quote,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_create_service_request_returns_201_with_snapshots(api):
    """PRD §3.2: "At creation the request enters `INTAKE` status, its `zone_code` is
    copied from the customer's `home_zone_code`, and its `fleet_account_id` is
    snapshotted from the customer's `fleet_account_id` (null for a retail customer)."

    Design: Corner/entities/create_service_request_returns_201_with_snapshots
    """
    customer = create_customer(home_zone_code="Z3", email="c1@x.com", full_name="C One")
    res = api.create_service_request(
        create_service_request_payload(customer["id"], vehicle_vin="1HGCM82633A100001",
                                       symptom_text="won't start", severity="URGENT"),
        make_customer_headers(customer["id"]))
    sr = validate_success(res, 201)
    assert_service_request(sr)
    assert sr["status"] == "INTAKE"
    assert sr["zone_code"] == "Z3"
    assert sr["fleet_account_id"] is None
    assert sr["severity"] == "URGENT"


def test_get_service_request_returns_stored(api):
    """PRD §2.4: "`version` — an integer that begins at its initial value and increments
    by one with every mutation of the resource."
    PRD §3.2: "both `estimate_total_cents` and `final_total_cents` are null until they
    are computed."

    Design: Corner/entities/get_service_request_returns_stored
    """
    customer = create_customer(home_zone_code="Z1", email="c2@x.com", full_name="C Two")
    created = get_success_data(api.create_service_request(
        create_service_request_payload(customer["id"], vehicle_vin="1HGCM82633A100002",
                                       symptom_text="x"),
        make_customer_headers(customer["id"])))
    res = api.get_service_request(created["id"], make_customer_headers(customer["id"]))
    sr = validate_success(res, 200)
    assert sr["id"] == created["id"]
    assert sr["version"] == 1
    assert sr["estimate_total_cents"] is None


def test_list_customer_service_requests_paginated(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/list_customer_service_requests_paginated
    """
    customer = create_customer(home_zone_code="Z1", email="c3@x.com", full_name="C Three")
    headers = make_customer_headers(customer["id"])
    api.create_service_request(
        create_service_request_payload(customer["id"], vehicle_vin="1HGCM82633A100003",
                                       symptom_text="a"), headers)
    api.create_service_request(
        create_service_request_payload(customer["id"], vehicle_vin="1HGCM82633A100004",
                                       symptom_text="b"), headers)
    data, meta = validate_paginated(
        api.list_customer_service_requests(customer["id"], headers,
                                           params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_get_service_request_not_found(api):
    """PRD §2.5: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first
    identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_service_request_not_found
    """
    res = api.get_service_request("00000000-0000-4000-8000-000000000000", DISPATCHER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_service_request_missing_required_field(api):
    """PRD §3.2: "A customer opens the engagement by filing a service request, supplying
    their own `customer_id`, the vehicle's `vehicle_vin` which must be exactly 17
    characters long, a free-text `symptom_text`, and an optional `severity`."

    Design: Corner/entities/create_service_request_missing_required_field
    """
    customer = create_customer(home_zone_code="Z1", email="c4@x.com", full_name="C Four")
    payload = {"customer_id": customer["id"], "symptom_text": "no vin"}
    res = api.create_service_request(payload, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_service_request_invalid_vin_length(api):
    """PRD §3.2: "the vehicle's `vehicle_vin` which must be exactly 17 characters long".

    Design: Corner/entities/create_service_request_invalid_vin_length
    """
    customer = create_customer(home_zone_code="Z1", email="c5@x.com", full_name="C Five")
    res = api.create_service_request(
        create_service_request_payload(customer["id"], vehicle_vin="SHORTVIN",
                                       symptom_text="bad vin"),
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_service_request_default_severity_routine(api):
    """PRD §3.2: "Severity is one of `ROUTINE`, `URGENT`, or `EMERGENCY` and defaults to
    `ROUTINE`".

    Design: Corner/entities/create_service_request_default_severity_routine
    """
    customer = create_customer(home_zone_code="Z1", email="c6@x.com", full_name="C Six")
    res = api.create_service_request(
        create_service_request_payload(customer["id"], vehicle_vin="1HGCM82633A100006",
                                       symptom_text="x"),
        make_customer_headers(customer["id"]))
    sr = validate_success(res, 201)
    assert sr["severity"] == "ROUTINE"


def test_catalog_part_no_version_field_immutable(api):
    """PRD §2.4: "The `CatalogPart` resource is the sole exception: it is immutable after
    creation and therefore carries only `id` and `created_at`. It has neither an
    `updated_at` field nor a `version` field."

    Design: Corner/entities/catalog_part_no_version_field_immutable
    """
    part = get_success_data(api.create_catalog_part(
        create_catalog_part_payload(sku="IMM1", name="Filter",
                                    wholesale_cost_cents=1500), ADMIN))
    res = api.get_catalog_part(part["id"], ADMIN)
    data = validate_success(res, 200)
    assert "version" not in data
    assert "updated_at" not in data
    assert data["sku"] == "IMM1"
    assert data["wholesale_cost_cents"] == 1500
    assert_catalog_part(data)


def test_part_line_unit_cost_snapshot_is_system(api):
    """PRD §3.6: "Sourcing creates a `PartLine` in `SOURCED` status whose
    `service_request_id` ties it to the request, snapshots the catalog part's wholesale
    cost into the line's `unit_cost_cents`, and computes the line's `unit_price_cents`
    and `line_total_cents` through the parts markup of §3.9."

    Design: Corner/entities/part_line_unit_cost_snapshot_is_system
    """
    part = create_catalog_part(wholesale_cost_cents=4000, sku="SNP1", name="Pad")
    ctx = setup_in_progress_request(mechanic_rate=9000, email="c7@x.com")
    pl = source_part_line(ctx["service_request"]["id"], ctx["mechanic"]["id"],
                          part["id"], quantity=1)
    assert pl["unit_cost_cents"] == 4000
    assert pl["unit_price_cents"] == 5800
    assert_part_line(pl)


def test_create_service_request_unknown_customer_fk_not_found(api):
    """PRD §2.5: "if a body field names a `customer_id`, `mechanic_id`, `catalog_part_id`,
    `job_visit_id`, `recommended_part_id`, `service_request_id`, or `fleet_account_id`
    that does not resolve, the request is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/create_service_request_unknown_customer_fk_not_found
    """
    ghost = "00000000-0000-4000-8000-000000000abc"
    res = api.create_service_request(
        create_service_request_payload(ghost, vehicle_vin="1HGCM82633A100008",
                                       symptom_text="x"),
        make_customer_headers(ghost))
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_immediate_visibility_of_estimate_after_approve(api):
    """PRD §2.8: "the platform applies every such cascade immediately and atomically."
    PRD §3.2: "the request copies the quote's `quoted_total_cents` into its own
    `estimate_total_cents`, the request advances `QUOTED → APPROVED`".

    Design: Corner/consistency_model/immediate_visibility_of_estimate_after_approve
    """
    ctx = setup_approved_request(estimated_labor_hours=2.0, estimated_parts_cents=8000,
                                 labor_rate_cents_per_hour=9000, email="c29@x.com")
    res = api.get_service_request(ctx["service_request"]["id"],
                                  make_customer_headers(ctx["customer"]["id"]))
    sr = validate_success(res, 200)
    assert sr["status"] == "APPROVED"
    assert sr["estimate_total_cents"] == 26000

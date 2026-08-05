"""Entity creation, computed fields, defaults, existence, and read-after-write.

Queue B (Corner): entities, consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    is_valid_uuid, ApiErrorId,
    ANONYMOUS_HEADERS, TEST_USERS, make_host_headers, make_tenant_headers,
    create_host_payload, create_tenant_payload, create_unit_payload, create_booking_payload,
    register_host, register_tenant, create_unit,
    assert_unit, assert_booking,
)

REVIEWER = TEST_USERS["compliance_reviewer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_create_unit_returns_201_with_server_fields(api):
    """PRD §3.2: "A host describes an available property by creating a `Unit`,
    which begins in `DRAFT`."
    PRD §2.4: "`version` — an integer that begins at 1 on creation and increments
    by one on every mutation."
    PRD §2.4: "`id` — a server-minted UUID with no type prefix. Clients never
    supply it."

    Design: Corner/entities/create_unit_returns_201_with_fields
    """
    host = register_host(api, verify_payout=False)
    resp = api.create_unit(
        create_unit_payload(host["id"], title="Cozy", address="1 A St", monthly_rate_cents=250000),
        make_host_headers(host["id"]),
    )
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"]), "unit id must be a non-prefixed UUID"
    assert data["status"] == "DRAFT", f"new unit must be DRAFT, got {data['status']}"
    assert data["version"] == 1, f"new unit version must be 1, got {data['version']}"
    assert_unit(data)


def test_unit_defaults_applied_when_omitted(api):
    """PRD §3.2: "`min_term_days` (defaulting to 30), `max_term_days` (defaulting
    to 90), and `turnover_buffer_days` (the cleaning gap appended after each stay,
    defaulting to 2)."

    Design: Corner/entities/unit_defaults_applied_when_omitted
    """
    host = register_host(api, verify_payout=False)
    data = get_success_data(api.create_unit(
        create_unit_payload(host["id"], title="Dflt", address="2 A St", monthly_rate_cents=250000),
        make_host_headers(host["id"]),
    ))
    assert data["min_term_days"] == 30, f"default min_term_days must be 30, got {data['min_term_days']}"
    assert data["max_term_days"] == 90, f"default max_term_days must be 90, got {data['max_term_days']}"
    assert data["turnover_buffer_days"] == 2, f"default turnover_buffer_days must be 2, got {data['turnover_buffer_days']}"


def test_booking_term_days_computed_from_dates(api):
    """PRD §3.3: "The `term_days` is the whole number of calendar days in the
    half-open window from `start_date` up to but not including `end_date`."
    PRD §2.5: "a stay from 2026-06-01 to 2026-07-01 spans exactly 30 days."

    Design: Corner/entities/booking_term_days_computed_from_dates
    """
    host = register_host(api, verify_payout=False)
    tenant = register_tenant(api, verified=False)
    unit = create_unit(api, host["id"], listed=False, cleaning_included=True)
    data = get_success_data(api.create_booking(
        create_booking_payload(unit["id"], tenant["id"], "2026-06-01", "2026-07-01"),
        make_tenant_headers(tenant["id"]),
    ))
    assert data["term_days"] == 30, f"term_days must be 30 for a 30-day half-open window, got {data['term_days']}"
    assert data["status"] == "REQUESTED", f"new booking must be REQUESTED, got {data['status']}"
    assert_booking(data)


def test_get_booking_nonexistent_returns_not_found(api):
    """PRD §2.8: "Path identifiers and foreign-key identifiers carried in a
    request body are resolved left to right, in the order they appear, and the
    first one that does not correspond to an existing resource causes the request
    to be rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_booking_nonexistent_returns_not_found
    """
    resp = api.get_booking("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_unit_missing_required_field_rejected(api):
    """PRD §2.9: "Body well-formedness — required fields present, enum values
    legal, dates parseable, and a booking's `end_date` strictly later than its
    `start_date`, else `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_unit_missing_required_field_rejected
    """
    host = register_host(api, verify_payout=False)
    # monthly_rate_cents omitted entirely.
    resp = api.create_unit(
        {"host_id": host["id"], "title": "NoRate", "address": "4 A St"},
        make_host_headers(host["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_register_tenant_invalid_enum_rejected(api):
    """PRD §3.1: "a `tenant_type` — one of `TRAVEL_NURSE`, `RELOCATION`, or
    `OTHER`."
    PRD §2.9: "Body well-formedness — required fields present, enum values legal,
    dates parseable, and a booking's `end_date` strictly later than its
    `start_date`, else `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/register_tenant_invalid_enum_rejected
    """
    resp = api.create_tenant(
        create_tenant_payload(full_name="Bad", email="bad@x.com", tenant_type="ASTRONAUT"),
        ANONYMOUS_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_immediate_read_after_write_visible(api):
    """PRD §2.7: "The platform maintains immediate consistency: whenever an
    operation changes a value that another resource is derived from, every
    dependent resource is recomputed within the same request, and each mutated
    resource has its `updated_at` refreshed and its `version` incremented."
    PRD §2.4: "`created_at` — an ISO 8601 UTC timestamp with three fractional
    digits, fixed at the moment of creation."

    Design: Corner/consistency_model/immediate_read_after_write_visible
    """
    host = register_host(api, verify_payout=False)
    unit = get_success_data(api.create_unit(
        create_unit_payload(host["id"], title="CZ", address="24 A St", monthly_rate_cents=275000),
        make_host_headers(host["id"]),
    ))
    data = get_success_data(api.get_unit(unit["id"], ADMIN))
    assert data["monthly_rate_cents"] == 275000, "read-back rate must match the create value"
    assert data["status"] == "DRAFT", "read-back status must match the create value (DRAFT)"

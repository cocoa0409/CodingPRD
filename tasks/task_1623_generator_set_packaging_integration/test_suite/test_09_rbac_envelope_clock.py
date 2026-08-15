"""RBAC denials, error envelope, auth, logical clock, paralleling schemes (PRD §2, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    get_success_data,
    setup_accepted_test,
    setup_booked_shipment,
    setup_customer,
    setup_order,
    setup_scheme_with_positions,
    setup_testing_order,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_customer_payload,
    create_order_payload,
    create_paralleling_scheme_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
APP_ENG = TEST_USERS["application_engineer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
FSM = TEST_USERS["field_service_manager_headers"]


# ---------------------------------------------------------------------------
# Corner/validations/missing_auth_headers_unauthenticated
# ---------------------------------------------------------------------------

def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the capacity in which they
    act. A request missing either header, or carrying a role string the system
    does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    resp = api_client.create_customer(
        create_customer_payload(name="NoAuth", credit_limit_cents=1000),
        {"Content-Type": "application/json"},  # no X-User-ID / X-User-Role
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# ---------------------------------------------------------------------------
# Corner/errors/error_envelope_shape_on_failure
# ---------------------------------------------------------------------------

def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format: ... The `meta` object for error responses contains
    only `api_request_id` and `api_request_timestamp`. The `error_id` is a
    unique, machine-readable string that identifies the specific error. The
    `message` provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape_on_failure
    """
    resp = api_client.get_customer(NON_EXISTENT_UUID, ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


# ---------------------------------------------------------------------------
# Corner/rbac/compliance_officer_cannot_issue_own_certificate
# ---------------------------------------------------------------------------

def test_compliance_officer_cannot_issue_own_certificate(api):
    """PRD §2.10: "And the regulatory filings are split so that the
    `ComplianceOfficer` who prepares and submits a permit or certificate is
    never the authority that approves, corrects, rejects, issues, or expires it
    — those authority actions belong to `PlatformAdmin`, which simulates the
    external AHJ and emissions authority."

    Design: Corner/rbac/compliance_officer_cannot_issue_own_certificate
    """
    from test_helpers import create_certificate, setup_locked_configuration
    ctx = setup_locked_configuration()
    cert = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    cert = get_success_data(api_client.submit_emissions_certificate(cert["id"], {}, COMPLIANCE))
    assert cert["status"] == "SUBMITTED"

    resp = api_client.issue_emissions_certificate(cert["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    current = get_success_data(api_client.get_emissions_certificate(cert["id"], COMPLIANCE))
    assert current["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Corner/rbac/logistics_cannot_create_orders
# ---------------------------------------------------------------------------

def test_logistics_cannot_create_orders(api):
    """PRD §2.1: "When the named role is not permitted to invoke the requested
    operation — or when a role-specific ownership rule fails — the request is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`SalesEngineer` — owns the commercial lifecycle: creates and
    authorizes orders..."; order creation is not among the
    `LogisticsCoordinator`'s operations ("owns freight and lift planning:
    books, dispatches, delivers, and releases shipments").

    Design: Corner/rbac/logistics_cannot_create_orders
    """
    customer = setup_customer()
    payload = create_order_payload(customer_id=customer["id"])
    resp = api_client.create_order(payload, LOGISTICS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ---------------------------------------------------------------------------
# Corner/rbac/field_service_cannot_drive_shipments
# ---------------------------------------------------------------------------

def test_field_service_cannot_drive_shipments(api):
    """PRD §2.1: "`LogisticsCoordinator` — owns freight and lift planning:
    books, dispatches, delivers, and releases shipments." Dispatch is not among
    the `FieldServiceManager`'s operations ("owns startup commissioning:
    requests commissioning events, assigns field engineers, and starts and
    completes startup work"), so the call is rejected per PRD §2.1:
    "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/field_service_cannot_drive_shipments
    """
    ctx = setup_booked_shipment(slot_overrides={"service_date": "2026-08-01"})
    assert ctx["shipment"]["status"] == "BOOKED"
    resp = api_client.dispatch_shipment(ctx["shipment"]["id"], FSM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    current = get_success_data(api_client.get_shipment(ctx["shipment"]["id"], LOGISTICS))
    assert current["status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Corner/endpoints/clock_set_endpoint_default_and_set
# ---------------------------------------------------------------------------

def test_clock_default_drives_permit_dates(api):
    """PRD §2.4: "At server startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`."
    PRD §3.4: "A first submission stamps `submitted_on` with the current
    logical-clock date, sets `expires_on` to `submitted_on` plus the
    jurisdiction's expiry window — 60 days for `US_CA`, 90 days for `DE`, 45
    days otherwise — and adds the `base_fee_cents` into
    `total_fees_paid_cents`."

    A US_TX permit submitted without any clock-set gets submitted_on
    2026-08-01 and expires_on 2026-09-15 (45 days).

    Design: Corner/endpoints/clock_set_endpoint_default_and_set
    """
    from test_helpers import setup_submitted_permit
    ctx = setup_submitted_permit()
    permit = ctx["permit"]
    assert permit["submitted_on"] == "2026-08-01"
    assert permit["expires_on"] == "2026-09-15"


# ---------------------------------------------------------------------------
# Corner/endpoints/paralleling_scheme_positions_capacity_boundary
# ---------------------------------------------------------------------------

def test_paralleling_scheme_positions_capacity_boundary(api):
    """PRD §3.6: "While in `DESIGN`, the engineer appends unit positions one at
    a time by supplying each position's `kw_rating`; the system assigns
    `position_no` values sequentially starting from 1, and each entry sits in
    `positions` as a `position_no`/`kw_rating` pair. The append is rejected with
    `ERR_PARALLEL_CAPACITY_EXCEEDED` when it would push the position count
    beyond `max_units`."

    With max_units 4 the 4th add succeeds; the 5th is rejected.

    Design: Corner/endpoints/paralleling_scheme_positions_capacity_boundary
    """
    customer = setup_customer()
    order = setup_order(customer["id"])
    scheme = get_success_data(api_client.create_paralleling_scheme(
        create_paralleling_scheme_payload(order_id=order["id"], sync_mode="MULTI_UNIT", max_units=4),
        APP_ENG,
    ))
    for _ in range(3):
        scheme = get_success_data(api_client.add_scheme_position(
            scheme["id"], {"kw_rating": 500}, APP_ENG
        ))
    fourth = validate_success(api_client.add_scheme_position(
        scheme["id"], {"kw_rating": 500}, APP_ENG
    ), expected_status=201)
    assert len(fourth["positions"]) == 4
    assert [p["position_no"] for p in fourth["positions"]] == [1, 2, 3, 4]

    resp = api_client.add_scheme_position(fourth["id"], {"kw_rating": 500}, APP_ENG)
    validate_error(resp, ApiErrorId.ERR_PARALLEL_CAPACITY_EXCEEDED)
    current = get_success_data(api_client.get_paralleling_scheme(fourth["id"], APP_ENG))
    assert len(current["positions"]) == 4


# ---------------------------------------------------------------------------
# Corner/endpoints/paralleling_scheme_program_requires_nonempty_positions
# ---------------------------------------------------------------------------

def test_scheme_program_requires_nonempty_positions(api):
    """PRD §3.6: "Programming the controls — the `DESIGN` → `PROGRAMMED`
    transition, performed by the `ApplicationEngineer` with a `program_version`
    input — requires the scheme to hold at least one position and no more than
    `max_units`: an empty `positions` array is rejected with
    `ERR_INVALID_REQUEST`, while a count above `max_units` is rejected with
    `ERR_PARALLEL_CAPACITY_EXCEEDED`. On success the supplied `program_version`
    is stored as `control_program_version` and the scheme's `version`
    increments."

    Design: Corner/endpoints/paralleling_scheme_program_requires_nonempty_positions
    """
    customer = setup_customer()
    order = setup_order(customer["id"])
    scheme = get_success_data(api_client.create_paralleling_scheme(
        create_paralleling_scheme_payload(order_id=order["id"], sync_mode="ISOLATED", max_units=2),
        APP_ENG,
    ))
    resp = api_client.program_scheme(scheme["id"], {"program_version": "ctrl-v1"}, APP_ENG)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    scheme = get_success_data(api_client.add_scheme_position(
        scheme["id"], {"kw_rating": 500}, APP_ENG
    ))
    programmed = validate_success(api_client.program_scheme(
        scheme["id"], {"program_version": "ctrl-v1"}, APP_ENG
    ))
    assert programmed["status"] == "PROGRAMMED"
    assert programmed["control_program_version"] == "ctrl-v1"


# ---------------------------------------------------------------------------
# Corner/endpoints/scheme_verify_gated_on_build_testing
# ---------------------------------------------------------------------------

def test_scheme_verify_gated_on_build_testing(api):
    """PRD §3.6: "Finally, verification moves a `PROGRAMMED` scheme to the
    terminal `VERIFIED` state, but only once the order's `build_status` has
    reached `TESTING`, `READY_TO_SHIP`, `DELIVERED`, or `COMMISSIONED` — any
    earlier build is rejected with `ERR_INVALID_BUILD_STATE`."

    At build CONFIGURING the verify is rejected; after the order reaches
    TESTING the same scheme verifies.

    Design: Corner/endpoints/scheme_verify_gated_on_build_testing
    """
    # Build order to CONFIGURING with a programmed scheme.
    from test_helpers import setup_locked_configuration
    ctx = setup_locked_configuration()
    scheme = setup_scheme_with_positions(ctx["order"]["id"], max_units=2, num_positions=1)
    scheme = get_success_data(api_client.program_scheme(
        scheme["id"], {"program_version": "ctrl-v1"}, APP_ENG
    ))
    assert scheme["status"] == "PROGRAMMED"
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "CONFIGURING"

    resp = api_client.verify_scheme(scheme["id"], APP_ENG)
    validate_error(resp, ApiErrorId.ERR_INVALID_BUILD_STATE)

    # Advance the same order to TESTING via permit approval + cert issue.
    from test_helpers import create_certificate
    from test_helpers.factories import create_permit_case_payload
    permit = get_success_data(api_client.create_permit_case(
        create_permit_case_payload(
            order_id=ctx["order"]["id"], configuration_id=ctx["configuration"]["id"]
        ),
        COMPLIANCE,
    ))
    get_success_data(api_client.submit_permit_case(permit["id"], COMPLIANCE))
    get_success_data(api_client.approve_permit_ahj(permit["id"], ADMIN))
    cert = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    get_success_data(api_client.submit_emissions_certificate(cert["id"], {}, COMPLIANCE))
    get_success_data(api_client.issue_emissions_certificate(cert["id"], ADMIN))
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "TESTING"

    verified = validate_success(api_client.verify_scheme(scheme["id"], APP_ENG))
    assert verified["status"] == "VERIFIED"


# ---------------------------------------------------------------------------
# Corner/validations/constraint_before_referential_on_test_create
# ---------------------------------------------------------------------------

def test_constraint_before_referential_on_test_create(api):
    """PRD §2.8: "...then business rules in the order: emissions and locale
    safety, segregation of duties, capacity and overlap constraints,
    clock-relative temporal windows, cross-entity referential requirements, and
    finally fiscal gates such as the credit check."

    A factory-test create whose bay window overlaps an existing test (capacity/
    overlap) AND whose order lacks an ISSUED certificate (cross-entity
    referential) returns ERR_TEST_BAY_OVERLAP — capacity/overlap is evaluated
    before the referential gate.

    Design: Corner/validations/constraint_before_referential_on_test_create
    """
    from test_helpers import (
        create_certificate,
        create_factory_test,
        make_test_engineer_headers,
        setup_approved_permit,
        setup_testing_order,
    )
    # Order 1 fully advanced, occupying bay window [8,12) on 2026-08-05.
    ctx1 = setup_testing_order()
    first = create_factory_test(
        ctx1["order"]["id"], ctx1["configuration"]["id"], ctx1["bay"]["id"],
        service_date="2026-08-05", start_hour=8, end_hour=12,
    )
    assert first["status"] == "SCHEDULED"

    # Order 2 has an approved permit but its certificate is only APP_DRAFT —
    # the referential ISSUED-cert gate would fail if reached.
    ctx2 = setup_approved_permit()
    resp = api_client.create_factory_test(
        {
            "order_id": ctx2["order"]["id"],
            "configuration_id": ctx2["configuration"]["id"],
            "bay_id": ctx1["bay"]["id"],
            "service_date": "2026-08-05",
            "start_hour": 10,
            "end_hour": 14,
        },
        make_test_engineer_headers("eng-sched-9"),
    )
    validate_error(resp, ApiErrorId.ERR_TEST_BAY_OVERLAP)

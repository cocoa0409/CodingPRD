"""Authority bootstrap/lifecycle, authentication, and role-based access."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_authority,
    bootstrap_authority,
    build_user_headers,
    create_account_spec,
    create_authority_payload,
    create_billing_extract_payload,
    create_compliance_filing_payload,
    create_ingest_payload,
    create_product_payload,
    create_rate_schedule_payload,
    create_supply_contract_payload,
    get_authority,
    set_clock,
    setup_active_authority,
    setup_enrolled_accounts,
    validate_error,
    validate_success,
)

BD = TEST_USERS["board_director_headers"]
RA = TEST_USERS["rate_analyst_headers"]


def test_authority_bootstrap_creation_and_singleton_uniqueness(api):
    """PRD §3.1: "Exactly one instance exists per deployment, created once by a `BoardDirector` through the bootstrap operation; a second bootstrap attempt collides with the singleton and is rejected with `ERR_UNIQUENESS_CONFLICT`."
    PRD §3.1: "At creation the authority's `status` is `FORMING` and its `climate_reserve_balance_cents` starts at 0."

    Design: Corner/entities/authority_bootstrap_creation_and_singleton_uniqueness
    """
    first = validate_success(api.create_authority(create_authority_payload(), BD), 201)
    assert_authority(first)
    assert first["status"] == "FORMING"
    assert first["climate_reserve_balance_cents"] == 0
    assert first["version"] == 1

    dup = api.create_authority(
        create_authority_payload(display_name="Duplicate Authority"), BD
    )
    validate_error(dup, ApiErrorId.ERR_UNIQUENESS_CONFLICT)


def test_activate_without_default_product_rejected(api):
    """PRD §3.1: "Activation requires that at least one adopted product with `election_key` equal to `DEFAULT` exists, and that at least one adopted rate schedule for that default product covers the current logical-clock date; without them the activation is rejected with `ERR_NO_DEFAULT_PRODUCT`."

    Design: Corner/errors/error_no_default_product_on_activate
    """
    bootstrap_authority()
    # A product exists but is only DRAFT — nothing is adopted.
    validate_success(api.create_product(create_product_payload(), RA), 201)

    res = api.activate_authority({}, BD)
    validate_error(res, ApiErrorId.ERR_NO_DEFAULT_PRODUCT)

    authority = get_authority()
    assert authority["status"] == "FORMING", "Authority must remain FORMING"


def test_dissolution_blocked_with_enrolled_account(api):
    """PRD §3.1: "A `BoardDirector` may dissolve an `ACTIVE` authority only when three conditions all hold: no service account exists in `ENROLLED` state; every compliance filing for the trailing four compliance years sits in `ACCEPTED_BY_CPUC` or `WITHDRAWN`; and every bad-debt pool has reached `TRUED_UP`. Failure of any leg is rejected with `ERR_DISSOLUTION_BLOCKED`."

    Design: Corner/errors/error_dissolution_blocked
    """
    setup_active_authority()
    setup_enrolled_accounts(specs=[create_account_spec(utility_account_number="U-D01")])

    res = api.dissolve_authority({}, BD)
    validate_error(res, ApiErrorId.ERR_DISSOLUTION_BLOCKED)

    authority = get_authority()
    assert authority["status"] == "ACTIVE", "Authority must remain ACTIVE"


def test_shared_read_operations_across_roles(api):
    """PRD §4: the row "GET | `/cca/authority` | Read the singleton authority (array of length 1)" lists all nine roles, and §4 states "The Authority read returns an array of length 1."
    PRD §2.5: "`version` (integer):** A system-managed counter, starting at 1, that increments with every modification to the resource and serves as the basis for optimistic concurrency control."

    Design: Corner/rbac/shared_read_operations_across_roles
    """
    created = bootstrap_authority()
    assert created["version"] == 1

    for role_headers in (
        TEST_USERS["compliance_officer_headers"],
        TEST_USERS["utility_liaison_headers"],
    ):
        res = api.get_authority(role_headers)
        data = validate_success(res, 200)
        assert isinstance(data, list) and len(data) == 1
        assert data[0]["version"] == 1, "reads must never mutate version"


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` value outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_request_rejected
    """
    bootstrap_authority()

    unknown_role = api.list_service_accounts(build_user_headers("intruder-1", "UnknownRole"))
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED)

    missing_headers = api.list_service_accounts({})
    validate_error(missing_headers, ApiErrorId.ERR_UNAUTHENTICATED)


def test_role_forbidden_exclusive_operation(api):
    """PRD §2.1: "An authenticated request whose role is not in the target endpoint's authorized role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the rate-schedule adopt row "POST | `/cca/rate-schedules/{id}/adopt`" authorizes only BoardDirector.

    Design: Corner/validations/role_forbidden_exclusive_operation
    """
    bootstrap_authority()
    product = validate_success(api.create_product(create_product_payload(), RA), 201)
    schedule = validate_success(
        api.create_rate_schedule(
            create_rate_schedule_payload(product_id=product["id"]), RA
        ),
        201,
    )
    validate_success(api.propose_rate_schedule(schedule["id"], {}, RA), 200)

    res = api.adopt_rate_schedule(
        schedule["id"], {}, TEST_USERS["customer_service_headers"]
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    after = validate_success(api.get_rate_schedule(schedule["id"], RA), 200)
    assert after["status"] == "PROPOSED", "Forbidden adopt must not move the schedule"


def test_rbac_role_exclusive_denials_matrix(api):
    """PRD §2.1: "An authenticated request whose role is not in the target endpoint's authorized role list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.9: "2. **Authorization** — an authenticated role outside the endpoint's role list yields `ERR_FORBIDDEN`."
    PRD §4: line posting authorizes only BillingCoordinator; contract execute only PortfolioManager; account ingest only ProgramOperator; filing create only ComplianceOfficer.

    Design: Corner/rbac/rbac_role_exclusive_denials_matrix
    """
    set_clock("2026-01-01T00:00:00Z")
    bootstrap_authority()
    extract = validate_success(
        api.create_billing_extract(
            create_billing_extract_payload(), TEST_USERS["billing_coordinator_headers"]
        ),
        201,
    )
    contract = validate_success(
        api.create_supply_contract(
            create_supply_contract_payload(
                counterparty="HydroWest Inc",
                contract_type="ENERGY_BLOCK",
                delivery_start="2027-01-01T00:00:00Z",
                delivery_end="2028-01-01T00:00:00Z",
                capacity_mw=5.0,
                total_mwh=100,
                price_dollars_per_mwh=55.0,
                rps_eligible_pct=0.0,
            ),
            TEST_USERS["portfolio_manager_headers"],
        ),
        201,
    )

    # PortfolioManager cannot post billing lines (role check fires at priority 2,
    # before the bogus body FK below is ever evaluated).
    e1 = api.post_billing_line(
        extract["id"],
        {"service_account_id": NON_EXISTENT_UUID, "usage_kwh": 100},
        TEST_USERS["portfolio_manager_headers"],
    )
    validate_error(e1, ApiErrorId.ERR_FORBIDDEN)

    # BillingCoordinator cannot execute contracts.
    e2 = api.execute_supply_contract(
        contract["id"], {}, TEST_USERS["billing_coordinator_headers"]
    )
    validate_error(e2, ApiErrorId.ERR_FORBIDDEN)

    # ComplianceOfficer cannot ingest accounts.
    e3 = api.ingest_service_accounts(
        create_ingest_payload([create_account_spec(utility_account_number="U-X01")]),
        TEST_USERS["compliance_officer_headers"],
    )
    validate_error(e3, ApiErrorId.ERR_FORBIDDEN)

    # UtilityLiaison cannot create filings.
    e4 = api.create_compliance_filing(
        create_compliance_filing_payload(filing_type="PSD"),
        TEST_USERS["utility_liaison_headers"],
    )
    validate_error(e4, ApiErrorId.ERR_FORBIDDEN)

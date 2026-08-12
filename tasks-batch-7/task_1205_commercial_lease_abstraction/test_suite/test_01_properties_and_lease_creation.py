"""Property and Lease creation: required fields, system fields, FK integrity."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_lease,
    assert_property,
    create_lease_payload,
    create_property_payload,
    set_clock,
    validate_error,
    validate_success,
)


class TestPropertyCreation:
    def test_property_create_required_fields(self, api, platform_admin_headers):
        """PRD §3.1: "A `PlatformAdmin` creates a Property by supplying a display
        `name`, a street `address`, the `total_rentable_sf` (an integer of at
        least 1), and the `fiscal_year_end_month`. A new Property's `posture`
        starts at `OPERATING`."
        PRD §4: "Operations that create a new resource — a Property, Lease,
        schedule line, escalation step, recovery pool, billing, reconciliation,
        critical date, compliance document, amendment, challenge, or audit
        right — return a `201 Created` status code."

        Design: Corner/entities/property_create_required_fields
        """
        set_clock()
        resp = api.create_property(
            create_property_payload(
                name="P1", address="1 Main",
                total_rentable_sf=10000, fiscal_year_end_month=12,
            ),
            platform_admin_headers,
        )
        data = validate_success(resp, 201)
        assert_property(data)
        assert data["posture"] == "OPERATING", (
            f"new Property posture must be OPERATING, got {data['posture']}"
        )
        assert data["name"] == "P1"
        assert data["total_rentable_sf"] == 10000
        assert data["fiscal_year_end_month"] == 12

    def test_property_create_missing_required_returns_invalid_request(
        self, api, platform_admin_headers
    ):
        """PRD §2.11: "Fourth, request shape: required request-body fields must
        be present and well-typed — dates in ISO `YYYY-MM-DD` form, enum values
        within their declared sets, integers within their declared ranges —
        else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/property_create_missing_required_returns_invalid_request
        """
        resp = api.create_property(
            {"name": "P1", "address": "1 Main", "fiscal_year_end_month": 12},
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_property_get_not_found(self, api, platform_admin_headers):
        """PRD §2.5: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) corresponding to the first identifier in the path that does
        not resolve to an existing resource."

        Design: Corner/entities/property_get_not_found
        """
        resp = api.get_property(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_property_invalid_total_sf(self, api, platform_admin_headers):
        """PRD §3.1: "A `PlatformAdmin` creates a Property by supplying a display
        `name`, a street `address`, the `total_rentable_sf` (an integer of at
        least 1), and the `fiscal_year_end_month`."
        PRD §2.11: "Fourth, request shape: required request-body fields must be
        present and well-typed — dates in ISO `YYYY-MM-DD` form, enum values
        within their declared sets, integers within their declared ranges —
        else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/property_invalid_total_sf
        """
        resp = api.create_property(
            create_property_payload(total_rentable_sf=0),
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestLeaseCreation:
    def test_lease_computed_fields_cached_on_create(
        self, api, platform_admin_headers, portfolio_manager_headers
    ):
        """PRD §3.1: "A new Lease begins with `status` of `DRAFT`,
        `abstraction_status` of `PENDING`, and `billing_posture` of `CURRENT`."
        PRD §3.1: "Two derived figures ride along on every Lease:
        `cached_annual_rent_cents`, the current-fiscal-year scheduled base rent
        derived from its rent schedule and refreshed on any schedule mutation,
        and `cached_recovery_ytd_cents`, the year-to-date total of recovery
        billings in `ISSUED` or `PAID` status for the current fiscal year."
        (With no schedule lines and no billings, both sums are over empty sets.)

        Design: Corner/entities/lease_computed_fields_cached_on_create
        """
        set_clock()
        prop = validate_success(
            api.create_property(create_property_payload(), platform_admin_headers), 201,
        )
        resp = api.create_lease(
            prop["id"],
            create_lease_payload(
                tenant_legal_name="T1", suite="100", leased_sf=4000,
                commencement_date="2027-01-01", expiration_date="2027-12-31",
                base_rent_annual_cents=1200000, escalation_type="NONE",
                recovery_structure="NNN", pro_rata_share_bps=4000,
                security_deposit_cents=0,
            ),
            portfolio_manager_headers,
        )
        data = validate_success(resp, 201)
        assert_lease(data)
        assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
        assert data["abstraction_status"] == "PENDING", (
            f"expected PENDING, got {data['abstraction_status']}"
        )
        assert data["billing_posture"] == "CURRENT", (
            f"expected CURRENT, got {data['billing_posture']}"
        )
        assert data["cached_annual_rent_cents"] == 0, (
            f"no schedule lines yet, expected 0, got {data['cached_annual_rent_cents']}"
        )
        assert data["cached_recovery_ytd_cents"] == 0, (
            f"no billings yet, expected 0, got {data['cached_recovery_ytd_cents']}"
        )

    def test_lease_fk_to_property_enforced(self, api, portfolio_manager_headers):
        """PRD §2.5: "When an endpoint path contains multiple resource
        identifiers, the system validates the existence of each identifier in a
        sequential, left-to-right order: `property_id` before `lease_id` before
        the child identifier (such as `line_id`, `step_id`, `pool_id`,
        `billing_id`, `recon_id`, `cd_id`, `doc_id`, `amendment_id`,
        `challenge_id`, or `audit_id`). The request is rejected immediately
        with `ERR_NOT_FOUND` (HTTP 404) corresponding to the first identifier
        in the path that does not resolve to an existing resource."

        Design: Corner/entities/lease_fk_to_property_enforced
        """
        resp = api.create_lease(
            NON_EXISTENT_UUID,
            create_lease_payload(),
            portfolio_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_date_range_commencement_before_expiration(
        self, api, platform_admin_headers, portfolio_manager_headers
    ):
        """PRD §2.11: "Fifth, temporal well-formedness on entity-creation
        endpoints and amendment application: a `period_start` must precede its
        `period_end`, a `commencement_date` must precede the `expiration_date`,
        a new CriticalDate's `due_date` must not be in the past, and an
        amendment's `effective_date` must not precede the lease's
        `commencement_date`, else `ERR_INVALID_DATE_RANGE` (HTTP 422)."

        Design: Corner/validations/date_range_commencement_before_expiration
        """
        set_clock()
        prop = validate_success(
            api.create_property(create_property_payload(), platform_admin_headers), 201,
        )
        resp = api.create_lease(
            prop["id"],
            create_lease_payload(
                commencement_date="2027-12-31", expiration_date="2027-01-01",
            ),
            portfolio_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)

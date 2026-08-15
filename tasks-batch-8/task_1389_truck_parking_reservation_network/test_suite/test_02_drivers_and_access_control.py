"""Driver registration, authentication/authorization guards, and ownership
scoping across roles."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_driver,
    assert_incident,
    create_driver_payload,
    create_reserved_booking,
    create_site_with_stalls,
    make_driver_headers,
    make_fleet_manager_headers,
    make_site_operator_headers,
    register_driver,
    set_clock,
    setup_invoiced_fleet_booking,
    validate_error,
    validate_success,
)


class TestDriverRegistration:

    def test_driver_register_duplicate_cdl_rejected(self, anonymous_headers):
        """PRD section 3.3: "Anyone may register a driver — it is the one
        operation open to `Anonymous` — by supplying a globally unique
        `cdl_number` (a duplicate fails with `ERR_VALIDATION`) and a
        `full_name`."

        Design: Corner/entities/driver_register_duplicate_cdl_rejected
        """
        resp = api_client.register_driver(
            create_driver_payload("CDL-DUP-1", "First"), anonymous_headers)
        first = validate_success(resp, expected_status=201)
        assert_driver(first)
        assert first["standing"] == "GOOD"
        assert first["loyalty_tier"] == "STANDARD"

        resp = api_client.register_driver(
            create_driver_payload("CDL-DUP-1", "Second"), anonymous_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestAuthenticationGuards:

    def test_missing_role_header_returns_unauthenticated(self):
        """PRD section 2.1: "A request whose `X-User-Role` header is missing
        or not one of the declared roles, or whose `X-User-ID` is missing for
        an entity-backed role (`Driver`, `FleetManager`), is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_role_header_returns_unauthenticated
        """
        resp = api_client.list_sites(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_driver_cannot_create_site(self):
        """PRD section 2.1: "A request whose role is not permitted on the
        endpoint, or that fails an ownership comparison, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD section 4: the site-creation endpoint is listed with authorized
        role NetworkAdmin only.

        Design: Corner/rbac/driver_cannot_create_site
        """
        driver = register_driver("CDL-RB-1", "R B One")
        resp = api_client.create_site(
            {"name": "X", "base_nightly_rate_cents": 5000},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_site_operator_cannot_dismiss_incident(self):
        """PRD section 3.8: "each step taken by a `SiteOperator` through a
        transition request whose `to` field names the target state
        (`ACKNOWLEDGED`, `INVESTIGATING`, `RESOLVED`, or `REOPENED` for
        operators; `DISMISSED` is reserved to `NetworkAdmin`)."
        PRD section 3.8: "From `OPEN`, `ACKNOWLEDGED`, or `INVESTIGATING`, a
        `NetworkAdmin` may instead dismiss the report outright as `DISMISSED`."

        Design: Corner/rbac/site_operator_cannot_dismiss_incident
        """
        ctx_site = create_site_with_stalls(num_reservable=0)
        site = ctx_site["site"]
        set_clock("2026-08-10T00:00:00Z")
        resp = api_client.create_incident(
            site["id"],
            {"category": "FACILITY", "severity": "LOW",
             "description": "faded paint"},
            make_site_operator_headers("op-alice"),
        )
        incident = validate_success(resp, expected_status=201)
        assert_incident(incident)

        resp = api_client.transition_incident(
            incident["id"], {"to": "DISMISSED"},
            make_site_operator_headers("op-alice"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        resp = api_client.transition_incident(
            incident["id"], {"to": "DISMISSED"}, ADMIN)
        dismissed = validate_success(resp, expected_status=200)
        assert dismissed["status"] == "DISMISSED"


class TestOwnershipScoping:

    def test_driver_cannot_cancel_other_drivers_booking(self):
        """PRD section 2.7: "Authorization and ownership: the role must be
        permitted on the endpoint, and ownership must hold — a `Driver` acts
        only where the resource's `driver_id` equals `X-User-ID`, a
        `FleetManager` only on their own fleet's authorizations, invoices, and
        account (where `fleet_account_id` equals `X-User-ID`) — otherwise
        `ERR_FORBIDDEN` (403)."
        PRD section 2.1: "ownership checks on any resource that references a
        Driver — bookings, waitlist entries, amenity lines, authorization
        requests, driver-authored incident reports — compare the resource's
        driver foreign-key field (such as `driver_id`, or
        `reporter_driver_id` on incident reports) to `X-User-ID`."

        Design: Corner/rbac/driver_cannot_cancel_other_drivers_booking
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site = ctx["site"]
        owner = register_driver("CDL-RB-3", "R B Three")
        intruder = register_driver("CDL-RB-4", "R B Four")
        set_clock("2026-08-01T00:00:00Z")
        booking = create_reserved_booking(owner["id"], site["id"],
                                          "2026-08-10", 1)

        resp = api_client.cancel_booking(
            booking["id"], make_driver_headers(intruder["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        resp = api_client.get_booking(booking["id"], ADMIN)
        after = validate_success(resp)
        assert after["status"] == "BOOKED", \
            "a foreign driver's cancel attempt must not move the booking"

    def test_fleet_manager_cannot_pay_other_fleets_invoice(self):
        """PRD section 2.1: "When `X-User-Role` is `FleetManager`, `X-User-ID`
        is the `id` of the acting FleetAccount; ownership checks on
        fleet-scoped resources (driver authorizations, invoices, the fleet
        account read itself, and fleet-billed bookings) compare the resource's
        `fleet_account_id` to `X-User-ID`."
        PRD section 2.1: "A request whose role is not permitted on the
        endpoint, or that fails an ownership comparison, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/fleet_manager_cannot_pay_other_fleets_invoice
        """
        ctx = setup_invoiced_fleet_booking(cdl_number="CDL-RB-2")
        invoice, fleet_a = ctx["invoice"], ctx["fleet"]
        other_fleet = validate_success(
            api_client.create_fleet_account(
                {"company_name": "B", "credit_limit_cents": 10_000_000,
                 "payment_terms_days": 30},
                ADMIN),
            expected_status=201,
        )

        resp = api_client.pay_invoice(
            invoice["id"], {"amount_cents": 4500},
            make_fleet_manager_headers(other_fleet["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        resp = api_client.get_invoice(invoice["id"], ADMIN)
        after = validate_success(resp)
        assert after["status"] == "ISSUED"
        assert after["paid_cents"] == 0, \
            "a foreign fleet manager's payment must not post"

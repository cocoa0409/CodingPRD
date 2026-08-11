"""Authentication and authorization: missing headers, role exclusivity, and
entity-backed Customer ownership (PRD §2.1, §2.9, §4).
"""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId, TEST_USERS,
    fixtures as fx,
)
from test_helpers.test_users import make_customer_headers


# =====================================================================
# Corner/validations/missing_auth_header_returns_unauthenticated
# =====================================================================
def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying
    the caller, and `X-User-Role`, naming the caller's role. A request missing
    either header, or carrying a role outside the declared set, is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    # Auth headers stripped entirely.
    resp = api.list_animals(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# =====================================================================
# Corner/rbac/customer_cannot_create_animals
# =====================================================================
def test_customer_cannot_create_animals(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint — or
    that violates entity-backed ownership — is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "Operators manage the animal roster, the handler roster,
    retirements, and the logical clock."

    Design: Corner/rbac/customer_cannot_create_animals
    """
    customer = fx.create_customer()
    resp = api.create_animal(
        {"name": "Gogo", "species": "GOAT", "weight_class": "SMALL",
         "temperament_tier": 3, "base_event_fee_cents": 8000},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


# =====================================================================
# Corner/rbac/coordinator_cannot_verify_certificate
# =====================================================================
def test_coordinator_cannot_verify_certificate(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint — or
    that violates entity-backed ownership — is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "A compliance officer decides permits and verifies insurance
    certificates — and, by segregation of duties, may not decide a permit
    submitted under the same operator id."

    Design: Corner/rbac/coordinator_cannot_verify_certificate
    """
    customer = fx.create_customer()
    cert = get_success_data(api.create_insurance_certificate(
        customer["id"],
        {"provider": "Acme Mutual", "policy_number": "POL-R2",
         "coverage_amount_cents": 500000, "expires_at": "2027-01-01T00:00:00Z"},
        make_customer_headers(customer["id"])))
    assert cert["status"] == "SUBMITTED"

    resp = api.verify_insurance_certificate(cert["id"], "VERIFIED", fx.COORD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    certs = get_success_data(api.list_insurance_certificates(
        customer["id"], make_customer_headers(customer["id"])))
    assert certs[0]["status"] == "SUBMITTED", certs[0]["status"]


# =====================================================================
# Corner/rbac/customer_cannot_read_other_customers_booking
# =====================================================================
def test_customer_cannot_read_other_customers_booking(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting `Customer` entity; ownership checks on any resource that
    references a `Customer` (venues, bookings, insurance certificates, and
    their children) compare the resource's foreign-key field to `X-User-ID`,
    and a mismatch is `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_read_other_customers_booking
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer_a = fx.create_customer()
    customer_b = fx.create_customer()
    venue_a = fx.create_venue(customer_a["id"], name="Venue A")
    booking = fx.create_booking(customer_a["id"], venue_a["id"], guest_count=10)

    # Customer B's X-User-ID does not match the booking's customer_id.
    resp = api.get_booking(booking["id"], make_customer_headers(customer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

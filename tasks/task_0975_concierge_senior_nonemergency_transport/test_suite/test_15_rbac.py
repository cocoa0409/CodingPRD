"""RBAC: role-exclusive denials, family tier enforcement, ownership checks,
shared operations, and segregation of duties."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_rate_card,
    create_booked_ride,
    create_client,
    create_client_with_billing_payer,
    create_completed_ride,
    create_compliant_driver,
    create_driver,
    create_family_member,
    create_invoice_payload,
    create_payment_payload,
    dispatch_and_accept,
    get_success_data,
    make_billing_admin_headers,
    make_client_headers,
    make_coordinator_headers,
    make_driver_headers,
    make_family_member_headers,
    set_clock,
    setup_standard_dispatch_env,
    validate_error,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def test_driver_cannot_generate_invoice_returns_unauthorized(api):
    """PRD §2.6: "The caller's role must appear in the endpoint's allowed role
    list; otherwise `ERR_UNAUTHORIZED_ROLE`."
    PRD §4: POST /invoices/generate is authorized for BillingAdmin only.

    Design: Corner/rbac/driver_cannot_generate_invoice_returns_unauthorized
    """
    client = create_client()
    driver = create_driver()
    resp = api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-06-01",
                               period_end="2026-06-08"),
        make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_client_cannot_dispatch_returns_unauthorized(api):
    """PRD §2.6: "The caller's role must appear in the endpoint's allowed role
    list; otherwise `ERR_UNAUTHORIZED_ROLE`."
    PRD §4: POST /rides/{id}/dispatch is authorized for Coordinator only.

    Design: Corner/rbac/client_cannot_dispatch_returns_unauthorized
    """
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-05-20T09:00:00Z")
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-01T10:00:00Z")
    resp = api_client.dispatch_ride(ride["id"], make_client_headers(client["id"]))
    # The role gate precedes ownership: even the ride's own client gets 403.
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["status"] == "SCHEDULED"


def test_view_only_family_cannot_book_returns_access_insufficient(api):
    """PRD §2.6: "Booking requires the member's `access_level` to be
    `BOOK_FOR_CLIENT` or `BILLING_PAYER`; taking a payment requires
    `BILLING_PAYER`; and the membership must be `ACTIVE` — this tier check
    guards ride booking, standing-series booking, payment capture, ride
    cancellation, and dispute raising, and failures are rejected with
    `ERR_FAMILY_ACCESS_INSUFFICIENT`."

    Design: Corner/rbac/view_only_family_cannot_book_returns_access_insufficient
    """
    client = create_client()
    member = create_family_member(client["id"], full_name="Vic V", relation="son",
                                  access_level="VIEW_ONLY")
    resp = api_client.create_ride(
        {"client_id": client["id"], "kind": "GROCERY",
         "scheduled_pickup_at": "2026-06-01T10:00:00Z",
         "estimated_duration_minutes": 60, "estimated_distance_miles": 10,
         "origin_zone": "north", "booked_by_family_member_id": member["id"]},
        make_family_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FAMILY_ACCESS_INSUFFICIENT)


def test_view_only_family_cannot_pay_returns_access_insufficient(api):
    """PRD §2.6: "Booking requires the member's `access_level` to be
    `BOOK_FOR_CLIENT` or `BILLING_PAYER`; taking a payment requires
    `BILLING_PAYER`; and the membership must be `ACTIVE` — this tier check
    guards ride booking, standing-series booking, payment capture, ride
    cancellation, and dispute raising, and failures are rejected with
    `ERR_FAMILY_ACCESS_INSUFFICIENT`."

    Design: Corner/rbac/view_only_family_cannot_pay_returns_access_insufficient
    """
    client = create_client()
    member = create_family_member(client["id"], full_name="Vic V", relation="son",
                                  access_level="VIEW_ONLY")
    resp = api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=500),
        make_family_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FAMILY_ACCESS_INSUFFICIENT)


def test_billing_payer_payment_shared_operation_allowed(api):
    """PRD §3.9: "Billing admins take payments directly, and family members
    holding `BILLING_PAYER` pay on their client's behalf."
    PRD §3.9: "Any remainder beyond all open invoices is credited to the
    client's `credit_balance_cents`. A new payment starts `SETTLED`."

    Design: Corner/rbac/billing_payer_payment_shared_operation_allowed
    """
    client, member = create_client_with_billing_payer()
    payment = get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=1000),
        make_family_member_headers(member["id"])))
    assert payment["status"] == "SETTLED"
    assert payment["applications"] == [], "no open invoices to fill"
    after = validate_success(api_client.get_client(client["id"], BILLING))
    assert after["credit_balance_cents"] == 1000, "full remainder parked as credit"


def test_client_b_cannot_read_client_a_ride_returns_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Client`, `X-User-ID` is the `id` of
    the acting `Client`; ownership checks on any resource that references a
    `Client` compare the resource's `client_id` field to `X-User-ID`."
    PRD §2.6: "A `Client` acts only on their own resources, a `Driver` only on
    their own assignments and rides, and a `FamilyMember` only on their
    client's resources; violations surface as `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/client_b_cannot_read_client_a_ride_returns_forbidden
    """
    client_a, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-05-20T09:00:00Z")
    client_b = create_client(full_name="Bob B", address="2 Elm St")
    ride = create_booked_ride(client_a["id"], scheduled_pickup_at="2026-06-01T10:00:00Z")
    resp = api_client.get_ride(ride["id"], make_client_headers(client_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_driver_cannot_respond_to_other_drivers_assignment_returns_forbidden(api):
    """PRD §3.5: "the caller must be the offered driver or the response fails
    with `ERR_FORBIDDEN_OWNERSHIP`."
    PRD §2.1: "When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the
    acting `Driver`; ownership checks on assignments and assigned rides compare
    against that driver id, and a driver who touches a resource owned by
    another driver is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/driver_cannot_respond_to_other_drivers_assignment_returns_forbidden
    """
    client, d1 = setup_standard_dispatch_env()
    # D2 needs no compliance posture: ownership fails before eligibility.
    d2 = create_driver(full_name="Eli E", home_zone="south",
                       assist_certification="DOOR_TO_DOOR")
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    offer = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    assert offer["driver_id"] == d1["id"]
    resp = api_client.respond_assignment(
        offer["id"], {"decision": "ACCEPT"}, make_driver_headers(d2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    after = validate_success(api_client.get_assignment(offer["id"], COORD))
    assert after["status"] == "OFFERED"
    assert after["driver_id"] == d1["id"]


def test_family_booking_with_wrong_client_returns_family_client_mismatch(api):
    """PRD §3.4: "a `booked_by_family_member_id` naming a member attached to a
    different client is `ERR_FAMILY_CLIENT_MISMATCH`."

    Design: Corner/rbac/family_booking_with_wrong_client_returns_family_client_mismatch
    """
    create_active_rate_card()
    client_a = create_client(full_name="Ada A")
    client_b = create_client(full_name="Bob B", address="2 Elm St")
    member_b = create_family_member(client_b["id"], full_name="Vic V", relation="son",
                                    access_level="BOOK_FOR_CLIENT")
    set_clock("2026-05-20T09:00:00Z")
    resp = api_client.create_ride(
        {"client_id": client_a["id"], "kind": "GROCERY",
         "scheduled_pickup_at": "2026-06-01T10:00:00Z",
         "estimated_duration_minutes": 60, "estimated_distance_miles": 10,
         "origin_zone": "north", "booked_by_family_member_id": member_b["id"]},
        COORD)
    validate_error(resp, ApiErrorId.ERR_FAMILY_CLIENT_MISMATCH)


def _setup_sod_dispute():
    """Completed ride dispatched by coord-7, billed on an issued invoice with a
    DISPUTED dispute raised by the BILLING_PAYER member.
    Returns (client, member, invoice)."""
    client, member = create_client_with_billing_payer()
    create_active_rate_card()
    driver, _ = create_compliant_driver()
    set_clock("2026-05-20T09:00:00Z")
    create_completed_ride(
        client["id"], driver["id"], "2026-06-01T10:00:00Z",
        estimated_duration_minutes=60, estimated_distance_miles=10,
        actual_distance_miles=10, service_minutes=60,
        coordinator_user_id="coord-7")
    invoice = get_success_data(api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-06-01", period_end="2026-06-08"),
        BILLING))
    get_success_data(api_client.issue_invoice(invoice["id"], BILLING))
    get_success_data(api_client.invoice_dispute_event(
        invoice["id"], {"action": "RAISE"}, make_family_member_headers(member["id"])))
    return client, member, invoice


def test_sod_resolver_who_dispatched_returns_sod_conflict(api):
    """PRD §2.10: "the operator resolving a dispute on an invoice must not be
    the operator whose `X-User-ID` was recorded as `matched_by_user_id` on any
    assignment whose ride is billed on that invoice. This check is evaluated
    only after the invoice's existence and dispute state are established (it
    sits at the end of the validation pipeline in §2.6), and a conflict is
    rejected with `ERR_SOD_CONFLICT`."

    Design: Corner/rbac/sod_resolver_who_dispatched_returns_sod_conflict
    """
    _, _, invoice = _setup_sod_dispute()
    resp = api_client.invoice_dispute_event(
        invoice["id"], {"action": "RESOLVE_ACCEPT", "credit_cents": 500},
        make_billing_admin_headers("coord-7"))
    validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT)
    after = validate_success(api_client.get_invoice(invoice["id"], BILLING))
    assert after["dispute_status"] == "DISPUTED", "conflicted resolve changes nothing"


def test_uninvolved_billing_admin_resolves_dispute(api):
    """PRD §3.9: "Resolution belongs to a `BillingAdmin`: `RESOLVE_ACCEPT`
    takes a `credit_cents` goodwill amount that may not exceed the invoice's
    `total_due_cents` (an excess is rejected with `ERR_INVALID_REQUEST`), posts
    that amount into the client's `credit_balance_cents`, and records
    `resolution_credit_cents` (zero until then) and the resolver's
    `resolved_by_user_id`"

    Design: Corner/rbac/sod_resolver_who_dispatched_returns_sod_conflict
    """
    client, _, invoice = _setup_sod_dispute()
    # First prove the conflicted resolver is rejected.
    validate_error(
        api_client.invoice_dispute_event(
            invoice["id"], {"action": "RESOLVE_ACCEPT", "credit_cents": 500},
            make_billing_admin_headers("coord-7")),
        ApiErrorId.ERR_SOD_CONFLICT)
    resolved = get_success_data(api_client.invoice_dispute_event(
        invoice["id"], {"action": "RESOLVE_ACCEPT", "credit_cents": 500},
        make_billing_admin_headers("bill-9")))
    assert resolved["dispute_status"] == "RESOLVED_ACCEPTED"
    assert resolved["resolution_credit_cents"] == 500
    assert resolved["resolved_by_user_id"] == "bill-9"
    after = validate_success(api_client.get_client(client["id"], BILLING))
    assert after["credit_balance_cents"] == 500, "goodwill credit posted to the pool"

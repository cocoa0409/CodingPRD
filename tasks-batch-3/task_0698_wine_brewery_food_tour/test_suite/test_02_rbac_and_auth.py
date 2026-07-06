"""Authentication, role authorization, and resource-ownership checks.

Queue B (Corner) translations from section: rbac.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    make_operator_headers, make_partner_venue_headers, make_guest_headers,
    ANONYMOUS_HEADERS,
    create_tour_product_payload, create_vehicle_payload,
    create_pickup_point_payload, create_guest_payload,
    create_departure_payload, create_stop_payload,
    create_partner_venue_payload, create_venue_confirmation_payload,
    create_booking_payload,
    get_success_data,
    setup_requested_venue_confirmation,
)
from test_helpers import api_client

OP = make_operator_headers()


def test_guest_cannot_create_tour_product_forbidden(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/guest_cannot_create_tour_product_forbidden
    """
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    resp = api.create_tour_product(
        create_tour_product_payload(name="P", theme="WINE",
                                    base_price_per_person_cents=9000),
        make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_partner_venue_cannot_confirm_other_venues_confirmation(api):
    """PRD §3.4: "the host venue has three moves, each permitted only to the
    `PartnerVenue` whose `id` matches the confirmation's `partner_venue_id`; an
    attempt by any other principal is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/partner_venue_cannot_confirm_other_venues_confirmation
    """
    product = get_success_data(api.create_tour_product(create_tour_product_payload(), OP))
    vehicle = get_success_data(api.create_vehicle(create_vehicle_payload(), OP))
    venue_a = get_success_data(api.create_partner_venue(
        create_partner_venue_payload(name="Oak A", commission_pct=0.10,
                                     tasting_cost_per_guest_cents=1200), OP))
    venue_b = get_success_data(api.create_partner_venue(
        create_partner_venue_payload(name="Oak B", commission_pct=0.12,
                                     tasting_cost_per_guest_cents=1100), OP))
    departure = get_success_data(api.create_departure(
        create_departure_payload(product["id"], vehicle["id"]), OP))
    stop = get_success_data(api.create_stop(
        create_stop_payload(departure["id"], venue_a["id"]), OP))
    vc = get_success_data(api.create_venue_confirmation(
        create_venue_confirmation_payload(stop["id"], requested_headcount=6), OP))
    # venue B (not the owner) tries to confirm venue A's confirmation.
    resp = api.confirm_venue_confirmation(vc["id"], make_partner_venue_headers(venue_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403)


def test_unauthenticated_reserve_rejected(api):
    """PRD §2.1: "When either header is missing on a protected endpoint, the
    request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_reserve_rejected
    """
    product = get_success_data(api.create_tour_product(create_tour_product_payload(), OP))
    get_success_data(api.publish_tour_product(product["id"], OP))
    vehicle = get_success_data(api.create_vehicle(create_vehicle_payload(), OP))
    pickup = get_success_data(api.create_pickup_point(create_pickup_point_payload(), OP))
    departure = get_success_data(api.create_departure(
        create_departure_payload(product["id"], vehicle["id"]), OP))
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(departure["id"], guest["id"], pickup["id"], 4),
        make_guest_headers(guest["id"])))
    # Reserve with NO auth headers at all.
    resp = api.reserve_booking(booking["id"], departure["version"], ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)

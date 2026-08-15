"""Role authorization and entity-backed ownership checks (PRD §2.1, §2.9)."""
from test_helpers import (
    ApiErrorId,
    book_reservation,
    create_customer,
    create_pilot,
    get_reservation,
    make_customer_headers,
    make_pilot_headers,
    set_clock,
    setup_publish_ready,
    setup_scheduled_flight,
    setup_weather_review_flight,
    create_draft_flight,
    validate_error,
)


class TestRoleSegregation:
    def test_customer_cannot_publish_flight(self, api, customer_headers):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list — including a request whose `event_type` belongs to a different
        role's slice of a shared events endpoint — is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4 authorizes the flight events endpoint to OperationsManager and
        Pilot, with `PUBLISH` in the OperationsManager slice.

        Design: Corner/rbac/customer_cannot_publish_flight
        """
        ctx = setup_publish_ready()
        flight = create_draft_flight(ctx)
        customer = create_customer()
        resp = api.flight_event(
            flight["id"], {"event_type": "PUBLISH"}, make_customer_headers(customer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_ops_cannot_record_weather_briefing(self, api, ops_headers):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list — including a request whose `event_type` belongs to a different
        role's slice of a shared events endpoint — is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4 authorizes POST /v1/flights/{flight_id}/weather-briefings to
        Pilot only.

        Design: Corner/rbac/ops_cannot_record_weather_briefing
        """
        ctx = setup_weather_review_flight()
        resp = api.create_weather_briefing(
            ctx["flight"]["id"],
            {
                "surface_wind_kts": 4,
                "aloft_wind_kts": 10,
                "visibility_mi": 10.0,
                "precipitation": False,
            },
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestEntityBackedOwnership:
    def test_customer_cannot_touch_others_reservation(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id`
        of the acting `Customer`; ownership checks on any resource that
        references a customer — a reservation's `customer_id` — compare that
        field to `X-User-ID`, and a mismatch is rejected with
        `ERR_RESERVATION_NOT_OWNED` (HTTP 403)."

        Design: Corner/rbac/customer_cannot_touch_others_reservation
        """
        ctx = setup_scheduled_flight()
        owner, reservation = book_reservation(ctx["flight"], party_size=1,
                                              declared_weight_lbs=180)
        intruder = create_customer()
        resp = api.reservation_event(
            reservation["id"],
            {"event_type": "CONFIRM", "paid_cents": reservation["quoted_fare_cents"]},
            make_customer_headers(intruder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESERVATION_NOT_OWNED)
        after = get_reservation(reservation["id"])
        assert after["booking_status"] == "PENDING"
        assert after["payment_status"] == "UNPAID"

    def test_unassigned_pilot_cannot_launch_flight(self, api):
        """PRD §2.1: "When `X-User-Role` is `Pilot`, `X-User-ID` is the `id` of
        the acting `Pilot`; ownership checks on any resource that references a
        pilot — chiefly a flight's `pilot_id` — compare that foreign-key field
        to `X-User-ID`, and a mismatch is rejected with `ERR_FLIGHT_NOT_ASSIGNED`
        (HTTP 403)."
        PRD §3.5: "Every pilot-scoped flight event first verifies that the
        acting pilot's `X-User-ID` equals the flight's `pilot_id`, rejecting
        impostors with `ERR_FLIGHT_NOT_ASSIGNED`".

        Design: Corner/rbac/unassigned_pilot_cannot_launch_flight
        """
        ctx = setup_scheduled_flight()
        other_pilot = create_pilot(external_pic_hours_180d=15.0,
                                   external_takeoffs_landings_90d=4)
        set_clock("2026-08-10T06:00:00Z")
        resp = api.flight_event(
            ctx["flight"]["id"],
            {"event_type": "ENTER_WEATHER_REVIEW"},
            make_pilot_headers(other_pilot["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_ASSIGNED)

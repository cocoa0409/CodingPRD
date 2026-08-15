"""Body-shape validation: required fields, the ninety-minute dawn window, and
enum membership (PRD §2.9 item 4, §3.2, §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_customer,
    create_flight_payload,
    make_customer_headers,
    setup_publish_ready,
    setup_scheduled_flight,
    validate_error,
)


class TestRequiredFields:
    def test_missing_required_field_returns_invalid_request(self, api, ops_headers):
        """PRD §2.9: "Body shape: the body is valid JSON, all required fields
        are present with the right types, enum fields take only their declared
        values, and — where a dawn window is supplied — the window is exactly
        ninety minutes long with its start's date portion equal to the flight's
        `scheduled_date` (`ERR_INVALID_REQUEST`, HTTP 400)."
        PRD §3.2: "An `OperationsManager` composes it by choosing a
        `scheduled_date`, a dawn launch window (`dawn_window_start` and
        `dawn_window_end` as ISO 8601 UTC instants), the `launch_site_id`, the
        `balloon_id`, the `pilot_id`, and the flight's `kind` — `SHARED` for
        per-seat shared-basket sales or `CHARTER` for a whole-basket booking."

        Design: Corner/entities/missing_required_field_returns_invalid_request
        """
        ctx = setup_publish_ready()
        payload = create_flight_payload(
            ctx["site"]["id"], ctx["balloon"]["id"], ctx["pilot"]["id"]
        )
        del payload["kind"]
        resp = api.create_flight(payload, ops_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDawnWindowShape:
    def test_flight_dawn_window_must_be_ninety_minutes(self, api, ops_headers):
        """PRD §3.2: "The dawn window must be exactly ninety minutes long, and
        the date portion of `dawn_window_start` must equal `scheduled_date`; a
        window that violates either rule is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/flight_dawn_window_must_be_ninety_minutes
        """
        ctx = setup_publish_ready()
        resp = api.create_flight(
            create_flight_payload(
                ctx["site"]["id"],
                ctx["balloon"]["id"],
                ctx["pilot"]["id"],
                dawn_window_start="2026-08-10T05:30:00Z",
                dawn_window_end="2026-08-10T07:30:00Z",  # 120 minutes, not 90
            ),
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        # A window whose start date differs from scheduled_date is rejected too.
        resp2 = api.create_flight(
            create_flight_payload(
                ctx["site"]["id"],
                ctx["balloon"]["id"],
                ctx["pilot"]["id"],
                scheduled_date="2026-08-11",
                dawn_window_start="2026-08-10T05:30:00Z",
                dawn_window_end="2026-08-10T07:00:00Z",
            ),
            ops_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)


class TestEnumMembership:
    def test_reservation_invalid_enum_rejected(self, api, customer_headers):
        """PRD §2.9: "Body shape: the body is valid JSON, all required fields
        are present with the right types, enum fields take only their declared
        values, and — where a dawn window is supplied — the window is exactly
        ninety minutes long with its start's date portion equal to the flight's
        `scheduled_date` (`ERR_INVALID_REQUEST`, HTTP 400)."
        PRD §3.4: "The booking payload carries the `customer_id` — which must
        equal the acting customer's `X-User-ID`, with a mismatch rejected as
        `ERR_RESERVATION_NOT_OWNED` — plus the `party_size`, the party's total
        `declared_weight_lbs`, and an optional `photo_package_tier` of `NONE`,
        `STANDARD`, or `DELUXE` (defaulting to `NONE`)."

        Design: Corner/entities/reservation_invalid_enum_rejected
        """
        ctx = setup_scheduled_flight()
        flight = ctx["flight"]
        customer = create_customer()
        resp = api.create_reservation(
            flight["id"],
            {
                "customer_id": customer["id"],
                "party_size": 1,
                "declared_weight_lbs": 180,
                "photo_package_tier": "PREMIUM",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

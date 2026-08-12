"""Corner queue B — entities section instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock, walk_assignment_to_handed_off,
    make_agent_headers, api_client, TEST_USERS,
    NON_EXISTENT_UUID,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestCreateAirport:
    def test_create_airport_with_required_fields_returns_201(self, api):
        """PRD §3.1: "The new airport is initialized with `posture` set to
        `NORMAL` and `ops_epoch` set to zero."
        PRD §4: "Endpoints that create a new resource return HTTP 201."

        Design: Corner/entities/create_airport_with_required_fields_returns_201
        """
        resp = api_client.create_airport(
            {"iata_code": "JFK", "tz_offset_minutes": -240, "meet_buffer_minutes": 30},
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert data["posture"] == "NORMAL"
        assert data["ops_epoch"] == 0

    def test_create_airport_missing_required_field_returns_400(self, api):
        """PRD §2.9: "14. **Format and value well-formedness** — enums valid,
        integers in range, `dob` parses as an ISO date, `iata_code` matches the
        three-uppercase-letter pattern (`ERR_BAD_REQUEST`)."

        Design: Corner/entities/create_airport_missing_required_field_returns_400
        """
        resp = api_client.create_airport(
            {"tz_offset_minutes": 0, "meet_buffer_minutes": 15},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST)


class TestPassengerClassComputed:
    def test_passenger_class_computed_from_dob(self, api):
        """PRD §3.2: "At creation the server derives `passenger_class` from the
        passenger's `dob` and the logical clock, yielding one of `ADULT`, `SENIOR`,
        or `UMNR` (unaccompanied minor)."

        Design: Corner/entities/passenger_class_computed_from_dob
        """
        set_clock("2026-06-15T10:00:00Z")
        kid = create_passenger(
            full_name="Kid", dob="2018-06-01", mobility_code="WCHR",
        )
        elder = create_passenger(
            full_name="Elder", dob="1956-06-01", mobility_code="WCHR",
        )
        mid = create_passenger(
            full_name="Mid", dob="1986-06-01", mobility_code="WCHR",
        )
        assert kid["passenger_class"] == "UMNR"
        assert elder["passenger_class"] == "SENIOR"
        assert mid["passenger_class"] == "ADULT"


class TestServiceLegRequiresFlags:
    def test_service_leg_requires_flags_computed(self, api):
        """PRD §3.2: "`requires_wheelchair` is true exactly when the passenger's
        `mobility_code` is `WCHS` or `WCHC`. `requires_wchc_chair` is true exactly
        when `mobility_code` is `WCHC`. `requires_ummr_agent` is true exactly when
        the passenger's derived class is `UMNR`. `requires_senior_agent` is true
        exactly when the class is `SENIOR`. `requires_tsa_escort` is true when the
        terminal's `requires_secure_escort` flag is set, or when the segment is
        international and the leg kind is not `MEET_ARRIVAL`."

        Design: Corner/entities/service_leg_requires_flags_computed
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="TPA", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="E", requires_secure_escort=True)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="BA1",
            direction="DEPARTURE", scheduled_utc="2026-06-20T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="UM P", dob="2018-01-01", mobility_code="WCHC",
            airline_pnr="TP1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="DEPARTURE_ESCORT", pickup_zone="Z")
        assert leg["requires_wheelchair"] is True
        assert leg["requires_wchc_chair"] is True
        assert leg["requires_ummr_agent"] is True
        assert leg["requires_tsa_escort"] is True
        assert leg["requires_senior_agent"] is False


class TestGetNonexistentAirport:
    def test_get_nonexistent_airport_returns_404(self, api):
        """PRD §2.6: "If any path identifier fails to resolve to a live resource,
        the request is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_airport_returns_404
        """
        resp = api_client.get_airport(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestTrackingEventImmutable:
    def test_immutable_tracking_event_has_no_version(self, api):
        """PRD §2.4: "The single exception is `TrackingEvent`, which is append-only:
        it carries `id` and `created_at` only — both `updated_at` and `version` are
        absent, because a tracking event is never modified after publication."

        Design: Corner/entities/immutable_tracking_event_has_no_version
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="FLL", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="1", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="NK1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P FLL", dob="1980-01-01", mobility_code="WCHR",
            airline_pnr="FLL1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        set_clock("2026-06-16T09:00:00Z")
        request = submit_request(request["id"])
        agent = create_agent(
            airport["id"], display_name="FLL Ag",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-FLL-1")
        assignment = dispatch_leg(leg["id"], request["id"], DISP)
        # PRD §3.9 rejects events whose occurred_at_utc lies in the future of
        # the logical clock — advance the clock past the event instant first.
        set_clock("2026-06-16T09:30:00Z")
        # Publish a tracking event
        resp = api_client.post_tracking_event(
            {"tracking_token": assignment["tracking_token"],
             "event_kind": "LOCATION_PING",
             "lat": 26.1, "lon": -80.1,
             "occurred_at_utc": "2026-06-16T09:30:00Z"},
            make_agent_headers(agent["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert "version" not in data, "TrackingEvent must NOT carry a version field"
        assert "updated_at" not in data, "TrackingEvent must NOT carry an updated_at field"

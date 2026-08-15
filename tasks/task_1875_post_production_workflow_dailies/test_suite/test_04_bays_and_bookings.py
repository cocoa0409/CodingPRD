"""Edit bay bookings: OCC, half-open overlap, check-in ceremony, utilization."""

from test_helpers import (
    ApiErrorId, assert_bay_utilization, assert_booking, create_bay,
    create_booking, current_bay_version, set_clock, setup_active_project,
    validate_error, validate_success,
)
from test_helpers.test_users import (
    make_artist_headers, make_post_supervisor_headers,
)

PS = make_post_supervisor_headers()


def _project_with_bay(clock="2026-08-01T00:00:00Z", **project_overrides):
    project, _wm, bay = setup_active_project(project_overrides=project_overrides,
                                             clock=clock)
    return project, bay


class TestBookingOcc:
    def test_occ_stale_bay_version_on_booking_create(self, api):
        """PRD §2.7: "Creating a booking requires `expected_bay_version`,
        carrying the client's last-observed `version` of the target edit bay.
        If the bay's current `version` has advanced beyond what the client
        observed — for example because another writer has since booked against
        the bay, or the bay has been placed into maintenance — the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from
        acting on a stale view of bay availability."
        PRD §3.4: "the bay's `version` increments by one".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_bay_version_on_booking_create
        """
        project, bay = _project_with_bay(client_code="CL800")
        bay_v0 = bay["version"]
        create_booking(project["id"], bay["id"], bay_v0,
                       artist_email="a@x.com", session_date="2026-08-05",
                       start_hour=9, end_hour=10, version_tag="v1")
        # Bay version advanced to v0+1; replaying with v0 must be rejected.
        resp = api.create_booking(project["id"], {
            "bay_id": bay["id"], "artist_email": "b@x.com",
            "session_date": "2026-08-05", "start_hour": 10, "end_hour": 11,
            "version_tag": "v2", "expected_bay_version": bay_v0}, PS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_booking_stale_version_beats_overlap(self, api):
        """PRD §2.9 item 5: "Stale-version guard. On the three OCC-guarded writes
        of §2.7, the supplied expected-version field must equal the parent
        entity's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.9 item 8: "Booking overlap. ... otherwise `ERR_BOOKING_OVERLAP`
        (HTTP 409). Applies to booking creation, and is evaluated only after the
        temporal-window check."

        Design: Difficulty/priority_pair_validation_conflict/booking_stale_version_beats_overlap
        """
        project, bay = _project_with_bay(client_code="CL009")
        bay_v0 = bay["version"]
        create_booking(project["id"], bay["id"], bay_v0,
                       artist_email="a@x.com", session_date="2026-08-05",
                       start_hour=10, end_hour=12, version_tag="v001")
        # Stale version AND overlapping hours: priority 5 wins over priority 8.
        resp = api.create_booking(project["id"], {
            "bay_id": bay["id"], "artist_email": "b@x.com",
            "session_date": "2026-08-05", "start_hour": 11, "end_hour": 13,
            "version_tag": "v002", "expected_bay_version": bay_v0}, PS)
        data = validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert data["error_id"] != "ERR_BOOKING_OVERLAP"

    def test_booking_overlap_fires_when_version_current(self, api):
        """PRD §2.9 item 8: "Booking overlap. The requested half-open hour
        interval must not overlap an existing non-terminal booking for the same
        bay on the same date; otherwise `ERR_BOOKING_OVERLAP` (HTTP 409)."
        PRD §3.4: "any true overlap is rejected with `ERR_BOOKING_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/booking_stale_version_beats_overlap
        """
        project, bay = _project_with_bay(client_code="CL009")
        create_booking(project["id"], bay["id"], bay["version"],
                       artist_email="a@x.com", session_date="2026-08-05",
                       start_hour=10, end_hour=12, version_tag="v001")
        # Current bay version, but overlapping hours: overlap check fires alone.
        v1 = current_bay_version(project["id"], bay["id"])
        resp = api.create_booking(project["id"], {
            "bay_id": bay["id"], "artist_email": "b@x.com",
            "session_date": "2026-08-05", "start_hour": 11, "end_hour": 13,
            "version_tag": "v002", "expected_bay_version": v1}, PS)
        validate_error(resp, ApiErrorId.ERR_BOOKING_OVERLAP)


class TestBookingHalfOpenOverlap:
    def test_booking_half_open_adjacency_accepts_touching(self, api):
        """PRD §3.4: "The requested hour interval is then checked against every
        existing non-terminal booking of the same bay on the same date under
        half-open semantics: intervals that merely touch, where one's `end_hour`
        equals the other's `start_hour`, do not conflict, while any true overlap
        is rejected with `ERR_BOOKING_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/booking_half_open_adjacency
        """
        project, bay = _project_with_bay(client_code="CL015")
        create_booking(project["id"], bay["id"], bay["version"],
                       artist_email="a@x.com", session_date="2026-08-05",
                       start_hour=10, end_hour=12, version_tag="v001")
        v1 = current_bay_version(project["id"], bay["id"])
        # Adjacent: start_hour == prior end_hour (12) — must be accepted.
        resp = api.create_booking(project["id"], {
            "bay_id": bay["id"], "artist_email": "b@x.com",
            "session_date": "2026-08-05", "start_hour": 12, "end_hour": 14,
            "version_tag": "v002", "expected_bay_version": v1}, PS)
        booking2 = validate_success(resp, expected_status=201)
        assert_booking(booking2)
        assert booking2["status"] == "RESERVED"

    def test_booking_half_open_adjacency_rejects_overlap(self, api):
        """PRD §3.4: "intervals that merely touch, where one's `end_hour` equals
        the other's `start_hour`, do not conflict, while any true overlap is
        rejected with `ERR_BOOKING_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/booking_half_open_adjacency
        """
        project, bay = _project_with_bay(client_code="CL015")
        create_booking(project["id"], bay["id"], bay["version"],
                       artist_email="a@x.com", session_date="2026-08-05",
                       start_hour=10, end_hour=12, version_tag="v001")
        v1 = current_bay_version(project["id"], bay["id"])
        create_booking(project["id"], bay["id"], v1,
                       artist_email="b@x.com", session_date="2026-08-05",
                       start_hour=12, end_hour=14, version_tag="v002")
        v2 = current_bay_version(project["id"], bay["id"])
        # 13-15 overlaps 12-14 because 13 < 14 (true overlap, not touching).
        resp = api.create_booking(project["id"], {
            "bay_id": bay["id"], "artist_email": "c@x.com",
            "session_date": "2026-08-05", "start_hour": 13, "end_hour": 15,
            "version_tag": "v003", "expected_bay_version": v2}, PS)
        validate_error(resp, ApiErrorId.ERR_BOOKING_OVERLAP)


class TestBookingCheckIn:
    def test_booking_idempotent_second_checkin_returns_invalid_state(self, api):
        """PRD §3.4: "the booking moves from `RESERVED` to `CHECKED_IN` only when
        `session_date` equals the current logical date and the current logical
        hour is at least `start_hour` and before `end_hour`."
        PRD §2.9 item 6: "The target resource must currently be in the from-state
        required by the requested transition; otherwise `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/booking_idempotent_second_checkin_returns_invalid_state
        """
        project, bay = _project_with_bay(clock="2026-08-05T10:30:00Z",
                                         client_code="CL204")
        booking = create_booking(project["id"], bay["id"], bay["version"],
                                 artist_email="art@x.com",
                                 session_date="2026-08-05", start_hour=10,
                                 end_hour=12, version_tag="v001")
        artist = make_artist_headers("art@x.com")
        first = validate_success(
            api.check_in_booking(project["id"], booking["id"], artist))
        assert first["status"] == "CHECKED_IN"
        resp = api.check_in_booking(project["id"], booking["id"], artist)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_booking(project["id"], booking["id"], PS))
        assert after["status"] == "CHECKED_IN"

    def test_error_artist_mismatch_trigger(self, api):
        """PRD §3.4: "only when the caller's `X-User-ID` matches the booking's
        `artist_email` under case-insensitive comparison, failing which the
        request is rejected with `ERR_ARTIST_MISMATCH`."
        PRD §2.9 item 18: "Check-in, completion, and artist-initiated
        cancellation require the caller's `X-User-ID` to match the booking's
        `artist_email` compared case-insensitively; otherwise
        `ERR_ARTIST_MISMATCH` (HTTP 403)."

        Design: Corner/errors/error_artist_mismatch_trigger
        """
        project, bay = _project_with_bay(clock="2026-08-05T10:30:00Z",
                                         client_code="CL600")
        booking = create_booking(project["id"], bay["id"], bay["version"],
                                 artist_email="art@x.com",
                                 session_date="2026-08-05", start_hour=10,
                                 end_hour=12, version_tag="v001")
        resp = api.check_in_booking(project["id"], booking["id"],
                                    make_artist_headers("someoneelse@x.com"))
        validate_error(resp, ApiErrorId.ERR_ARTIST_MISMATCH)


class TestBayOccupancy:
    def test_error_bay_occupied_trigger(self, api):
        """PRD §3.4: "A `PostSupervisor` may move it to `MAINTENANCE` only when
        the bay has no booking in `RESERVED` or `CHECKED_IN` on or after the
        current logical date; a violating request is rejected with
        `ERR_BAY_OCCUPIED`."

        Design: Corner/errors/error_bay_occupied_trigger
        """
        project, bay = _project_with_bay(client_code="CL601")
        create_booking(project["id"], bay["id"], bay["version"],
                       artist_email="a@x.com", session_date="2026-08-20",
                       start_hour=10, end_hour=12, version_tag="v001")
        resp = api.bay_maintenance(project["id"], bay["id"], PS)
        validate_error(resp, ApiErrorId.ERR_BAY_OCCUPIED)


class TestBayUtilization:
    def test_bay_utilization_computed_read_empty(self, api):
        """PRD §3.4: "For a given bay and `session_date`, the booked hours are
        the sum of `booked_hours` over that bay's bookings on that date whose
        status is `RESERVED`, `CHECKED_IN`, or `COMPLETED`, and the utilization
        percentage is the whole-number floor of one hundred times the booked
        hours divided by the bay's `capacity_hours_per_day`."
        PRD §3.4: "The read returns `session_date`, `booked_hours`,
        `capacity_hours_per_day`, and `utilization_pct`."

        Design: Corner/endpoints/bay_utilization_computed_read
        """
        project, _wm, bay = setup_active_project(
            project_overrides={"client_code": "CL500", "storage_quota_gb": 10},
            bay_overrides={"capacity_hours_per_day": 12})
        resp = api.get_bay_utilization(project["id"], bay["id"], PS,
                                       params={"session_date": "2026-08-20"})
        data = validate_success(resp)
        assert_bay_utilization(data)
        assert data["booked_hours"] == 0
        assert data["utilization_pct"] == 0

    def test_bay_utilization_hours_chronological_rollup(self, api):
        """PRD §3.4: "For a given bay and `session_date`, the booked hours are
        the sum of `booked_hours` over that bay's bookings on that date whose
        status is `RESERVED`, `CHECKED_IN`, or `COMPLETED`, and the utilization
        percentage is the whole-number floor of one hundred times the booked
        hours divided by the bay's `capacity_hours_per_day`."
        PRD §3.4: "Every booking lifecycle event — creation, check-in,
        completion, cancellation, and the no-show sweep — recomputes this figure
        for the affected bay and date."

        Design: Corner/calculations/bay_utilization_hours_chronological_rollup
        """
        project, bay = _project_with_bay(client_code="CL302")
        # 2h + 3h + 1h = 6 booked hours on 2026-08-10 (capacity 8).
        specs = [("a@x.com", 9, 11, "v1"), ("b@x.com", 11, 14, "v2"),
                 ("c@x.com", 14, 15, "v3"), ("d@x.com", 15, 17, "v4")]
        booking_ids = []
        for email, sh, eh, tag in specs:
            v = current_bay_version(project["id"], bay["id"])
            b = create_booking(project["id"], bay["id"], v,
                               artist_email=email, session_date="2026-08-10",
                               start_hour=sh, end_hour=eh, version_tag=tag)
            booking_ids.append(b["id"])
        # Cancel the 2h 15-17 booking; cancelled bookings are excluded.
        api.cancel_booking(project["id"], booking_ids[3], PS)
        resp = api.get_bay_utilization(project["id"], bay["id"], PS,
                                       params={"session_date": "2026-08-10"})
        data = validate_success(resp)
        assert data["booked_hours"] == 6, (
            f"Expected 6 booked hours (2+3+1), got {data['booked_hours']}")
        assert data["utilization_pct"] == 75, (
            f"floor(100*6/8) should be 75, got {data['utilization_pct']}")

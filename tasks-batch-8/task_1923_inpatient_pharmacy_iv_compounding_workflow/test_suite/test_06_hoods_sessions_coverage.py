"""Hood session overlap, windows, and coverage capacity (PRD §3.1)."""
from test_helpers import (
    create_hood,
    create_hood_session_payload,
    create_coverage_shift,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestHoodSessionHalfOpenAdjacency:
    def _setup_first_session(self, api):
        technician, technician_headers = fixtures.make_technician()
        hood = create_hood(name="HOOD-O")
        session1 = validate_success(
            api.create_hood_session(
                create_hood_session_payload(
                    hood["id"],
                    start_at="2026-08-01T08:00:00Z",
                    end_at="2026-08-01T10:00:00Z",
                ),
                technician_headers,
            ),
            201,
        )
        return hood, technician_headers, session1

    def test_adjacent_session_at_boundary_allowed(self, api, pharmacist_headers):
        """PRD §3.1: "Windows are half-open intervals — `start_at` inclusive, `end_at` exclusive — and `end_at` must be strictly after `start_at`, otherwise the request fails with `ERR_INVALID_QUANTITY`. No two sessions on the same hood whose status is `SCHEDULED` or `IN_USE` may overlap; adjacency, where one session's `start_at` equals another's `end_at`, is allowed."

        Design: Difficulty/resource_temporal_overlap/hood_session_half_open_adjacency
        """
        hood, technician_headers, _ = self._setup_first_session(api)
        resp = api.create_hood_session(
            create_hood_session_payload(
                hood["id"],
                start_at="2026-08-01T10:00:00Z",
                end_at="2026-08-01T11:00:00Z",
            ),
            technician_headers,
        )
        validate_success(resp, 201)
        rows, meta = validate_paginated(
            api.list_hood_sessions(pharmacist_headers, params={"hood_id": hood["id"]})
        )
        assert meta["total_count"] == 2

    def test_one_second_overlap_rejected(self, api):
        """PRD §3.1: "No two sessions on the same hood whose status is `SCHEDULED` or `IN_USE` may overlap; adjacency, where one session's `start_at` equals another's `end_at`, is allowed. An overlapping reservation is rejected with `ERR_HOOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/hood_session_half_open_adjacency
        """
        hood, technician_headers, _ = self._setup_first_session(api)
        resp = api.create_hood_session(
            create_hood_session_payload(
                hood["id"],
                start_at="2026-08-01T09:59:59Z",
                end_at="2026-08-01T10:30:00Z",
            ),
            technician_headers,
        )
        validate_error(resp, "ERR_HOOD_OVERLAP", 409)


class TestHoodOverlapIgnoresCancelled:
    def test_cancelled_session_does_not_block_new_window(self, api, pharmacist_headers):
        """PRD §3.1: "No two sessions on the same hood whose status is `SCHEDULED` or `IN_USE` may overlap; adjacency, where one session's `start_at` equals another's `end_at`, is allowed."
        PRD §3.1: "From `IN_USE` the technician completes the session, moving it to `COMPLETED`; from either `SCHEDULED` or `IN_USE` the technician may cancel it, moving it to `CANCELLED`."

        Design: Corner/cross_cutting_layers/hood_overlap_ignores_cancelled_sessions
        """
        technician, technician_headers = fixtures.make_technician()
        hood = create_hood(name="HOOD-CX")
        session1 = validate_success(
            api.create_hood_session(
                create_hood_session_payload(
                    hood["id"],
                    start_at="2026-08-01T08:00:00Z",
                    end_at="2026-08-01T10:00:00Z",
                ),
                technician_headers,
            ),
            201,
        )
        validate_success(
            api.cancel_hood_session(session1["id"], technician_headers), 200
        )
        resp = api.create_hood_session(
            create_hood_session_payload(
                hood["id"],
                start_at="2026-08-01T08:30:00Z",
                end_at="2026-08-01T09:30:00Z",
            ),
            technician_headers,
        )
        validate_success(resp, 201)
        rows, meta = validate_paginated(
            api.list_hood_sessions(pharmacist_headers, params={"hood_id": hood["id"]})
        )
        assert meta["total_count"] == 2
        statuses = sorted(r["status"] for r in rows)
        assert statuses == ["CANCELLED", "SCHEDULED"]


class TestHoodSessionStart:
    def test_second_start_rejected_invalid_state(self, api):
        """PRD §3.1: "A session begins `SCHEDULED`; starting it (a `PharmacyTechnician` action) requires the logical clock to fall inside the window — at or after `start_at` and strictly before `end_at` — failing which the start is rejected with `ERR_HOOD_SESSION_OUTSIDE_WINDOW`, and a successful start moves the session to `IN_USE` and increments its `version`."

        Design: Corner/state_machines/hood_session_start_twice_rejected
        """
        sess_ns = fixtures.setup_session(start=True)
        session = sess_ns.session
        assert session["status"] == "IN_USE"
        resp = api.start_hood_session(session["id"], sess_ns.technician_headers)
        validate_error(resp, "ERR_INVALID_STATE", 409)

    def test_start_outside_window_rejected(self, api):
        """PRD §3.1: "A session begins `SCHEDULED`; starting it (a `PharmacyTechnician` action) requires the logical clock to fall inside the window — at or after `start_at` and strictly before `end_at` — failing which the start is rejected with `ERR_HOOD_SESSION_OUTSIDE_WINDOW`, and a successful start moves the session to `IN_USE` and increments its `version`."

        Design: Corner/errors/error_hood_session_outside_window
        """
        sess_ns = fixtures.setup_session(
            start=False,
            start_at="2026-08-05T00:00:00Z",
            end_at="2026-08-06T00:00:00Z",
        )
        resp = api.start_hood_session(
            sess_ns.session["id"], sess_ns.technician_headers
        )
        validate_error(resp, "ERR_HOOD_SESSION_OUTSIDE_WINDOW", 422)
        fetched = validate_success(
            api.get_hood_session(sess_ns.session["id"], sess_ns.technician_headers), 200
        )
        assert fetched["status"] == "SCHEDULED"


class TestCoverageShiftCapacity:
    def _setup_two_overlapping_shifts(self):
        pharm_a, _ = fixtures.make_pharmacist()
        pharm_b, _ = fixtures.make_pharmacist()
        pharm_c, _ = fixtures.make_pharmacist()
        create_coverage_shift(pharm_a, "CENTRAL",
                              "2026-08-01T08:00:00Z", "2026-08-01T16:00:00Z")
        create_coverage_shift(pharm_b, "CENTRAL",
                              "2026-08-01T12:00:00Z", "2026-08-01T20:00:00Z")
        return pharm_c

    def test_third_overlapping_shift_rejected(self, api, admin_headers):
        """PRD §3.1: "At most two coverage shifts per zone may overlap at any instant; a new shift that would create a three-way overlap is rejected with `ERR_COVERAGE_CAP_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/coverage_shift_aggregate_capacity_cap
        """
        pharm_c = self._setup_two_overlapping_shifts()
        resp = api.create_coverage_shift(
            {
                "staff_id": pharm_c["id"],
                "zone": "CENTRAL",
                "start_at": "2026-08-01T14:00:00Z",
                "end_at": "2026-08-01T18:00:00Z",
            },
            admin_headers,
        )
        validate_error(resp, "ERR_COVERAGE_CAP_EXCEEDED", 409)

    def test_third_shift_abutting_half_open_boundary_allowed(self, api, admin_headers):
        """PRD §3.1: "Pharmacist zone coverage is scheduled by a `PharmacyAdmin` as coverage shifts, each naming a `staff_id`, a `zone` label such as `CENTRAL` or `SATELLITE_ER`, and a half-open `start_at`/`end_at` window with the same strict ordering requirement. At most two coverage shifts per zone may overlap at any instant; a new shift that would create a three-way overlap is rejected with `ERR_COVERAGE_CAP_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/coverage_shift_aggregate_capacity_cap
        """
        pharm_c = self._setup_two_overlapping_shifts()
        resp = api.create_coverage_shift(
            {
                "staff_id": pharm_c["id"],
                "zone": "CENTRAL",
                "start_at": "2026-08-01T20:00:00Z",
                "end_at": "2026-08-01T23:00:00Z",
            },
            admin_headers,
        )
        validate_success(resp, 201)
        rows, meta = validate_paginated(
            api.list_coverage_shifts(admin_headers, params={"zone": "CENTRAL"})
        )
        assert meta["total_count"] == 3

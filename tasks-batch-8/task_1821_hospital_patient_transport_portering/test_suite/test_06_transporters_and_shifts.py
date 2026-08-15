"""Transporter status machine, shift coverage, and shift overlap rules."""
from test_helpers import (
    SUP,
    ApiErrorId,
    add_covering_shift,
    add_on_shift_transporter,
    add_transporter,
    cancel_shift,
    create_dispatch_offer,
    create_location,
    create_shift_payload,
    create_transport_request,
    make_transporter_headers,
    set_clock,
    setup_assigned_trip,
    setup_transport_site,
    validate_error,
    validate_success,
)


class TestClockInCoverage:
    def test_clockin_requires_shift_coverage(self, api):
        """PRD §3.2: "Clocking in moves a transporter from `OFF_SHIFT` to
        `ON_SHIFT` and is gated on shift coverage: a `PLANNED` staffing shift
        must cover the current logical instant, meaning `shift_start` is at or
        before now and now is strictly before `shift_end` — otherwise
        `ERR_NO_SHIFT_COVERAGE`."

        Design: Difficulty/cross_entity_state_dependency/clockin_requires_shift_coverage
        """
        set_clock("2026-08-01T09:00:00Z")
        hub = create_location("HUB", "Hub", "OTHER", "Z1")
        t3 = add_transporter("T Three", hub["id"])

        refused = api.set_transporter_status(t3["id"], {"status": "ON_SHIFT"},
                                             make_transporter_headers(t3["id"]))
        validate_error(refused, ApiErrorId.ERR_NO_SHIFT_COVERAGE)

        add_covering_shift(t3["id"], "2026-08-01T08:00:00Z",
                           "2026-08-01T16:00:00Z")
        accepted = api.set_transporter_status(
            t3["id"], {"status": "ON_SHIFT"}, make_transporter_headers(t3["id"]))
        data = validate_success(accepted, 200)
        assert data["status"] == "ON_SHIFT"

    def test_clockin_half_open_coverage_boundary(self, api):
        """PRD §3.2: "a `PLANNED` staffing shift must cover the current logical
        instant, meaning `shift_start` is at or before now and now is strictly
        before `shift_end` — otherwise `ERR_NO_SHIFT_COVERAGE`."

        Design: Difficulty/cross_entity_state_dependency/clockin_requires_shift_coverage
        """
        hub = create_location("HUB", "Hub", "OTHER", "Z1")
        t3 = add_transporter("T Three", hub["id"])
        add_covering_shift(t3["id"], "2026-08-01T08:00:00Z",
                           "2026-08-01T16:00:00Z")

        # now == shift_end: the half-open interval no longer covers.
        set_clock("2026-08-01T16:00:00Z")
        refused = api.set_transporter_status(t3["id"], {"status": "ON_SHIFT"},
                                             make_transporter_headers(t3["id"]))
        validate_error(refused, ApiErrorId.ERR_NO_SHIFT_COVERAGE)

        # A shift whose start equals now covers (start is inclusive);
        # back-to-back adjacency is allowed by the overlap rule.
        add_covering_shift(t3["id"], "2026-08-01T16:00:00Z",
                           "2026-08-01T20:00:00Z")
        accepted = api.set_transporter_status(
            t3["id"], {"status": "ON_SHIFT"}, make_transporter_headers(t3["id"]))
        assert validate_success(accepted, 200)["status"] == "ON_SHIFT"


class TestSuspendAndClockoutGuards:
    def test_suspend_with_active_assignment_returns_409(self, api):
        """PRD §3.2: "Clocking out, and suspension, are only permitted when the
        transporter holds no active assignment — no request assigned to them in
        `ASSIGNED`, `AT_PICKUP`, or `IN_TRANSIT` — and has no `PENDING` offer
        addressed to them; violations answer `ERR_INVALID_TRANSPORTER_STATE`."

        Design: Corner/state_machines/suspend_with_active_assignment_returns_409
        """
        world = setup_assigned_trip(equipment="PORTER_ONLY", patient_ref="P1")
        t1 = world["transporter"]

        resp = api.set_transporter_status(t1["id"], {"status": "SUSPENDED"}, SUP)
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSPORTER_STATE)

    def test_clockout_with_pending_offer_returns_409(self, api):
        """PRD §3.2: "Clocking out, and suspension, are only permitted when the
        transporter holds no active assignment — no request assigned to them in
        `ASSIGNED`, `AT_PICKUP`, or `IN_TRANSIT` — and has no `PENDING` offer
        addressed to them; violations answer `ERR_INVALID_TRANSPORTER_STATE`."

        Design: Corner/state_machines/clockout_with_pending_offer_returns_409
        """
        site = setup_transport_site()
        t1 = add_on_shift_transporter("T One", site["hub"]["id"])
        r1 = create_transport_request("P1", site["ward"]["id"],
                                      site["img"]["id"], priority="ROUTINE",
                                      required_equipment="PORTER_ONLY")
        create_dispatch_offer(r1, transporter_id=t1["id"])

        resp = api.set_transporter_status(t1["id"], {"status": "OFF_SHIFT"},
                                          make_transporter_headers(t1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSPORTER_STATE)


class TestShiftLifecycle:
    def test_shift_cancel_twice_returns_409(self, api):
        """PRD §3.2: "Cancellation moves a shift from `PLANNED` to `CANCELLED`
        and is permitted only while the shift is `PLANNED`, otherwise
        `ERR_INVALID_SHIFT_STATE`; cancelled shifts are excluded from the
        scheduled-headcount counts in §3.8."

        Design: Corner/state_machines/shift_cancel_twice_returns_409
        """
        hub = create_location("HUB", "Hub", "OTHER", "Z1")
        t1 = add_transporter("T One", hub["id"])
        s1 = add_covering_shift(t1["id"], "2026-08-02T08:00:00Z",
                                "2026-08-02T16:00:00Z")

        first = cancel_shift(s1["id"])
        assert first["status"] == "CANCELLED"
        resp = api.set_shift_status(s1["id"], {"status": "CANCELLED"}, SUP)
        validate_error(resp, ApiErrorId.ERR_INVALID_SHIFT_STATE)

    def test_shift_halfopen_overlap_boundary(self, api):
        """PRD §3.2: "A new shift may not overlap another `PLANNED` shift of
        the same transporter — half-open semantics mean back-to-back shifts
        that merely touch are allowed — and a genuine overlap is rejected with
        `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/shift_halfopen_overlap_boundary
        """
        hub = create_location("HUB", "Hub", "OTHER", "Z1")
        t1 = add_transporter("T One", hub["id"])
        add_covering_shift(t1["id"], "2026-08-01T08:00:00Z",
                           "2026-08-01T16:00:00Z")

        # Adjacent: the new shift starts exactly at the existing shift's end.
        adjacent = api.create_staffing_shift(
            create_shift_payload(t1["id"], "2026-08-01T16:00:00Z",
                                 "2026-08-01T20:00:00Z"), SUP)
        adjacent_data = validate_success(adjacent, 201)
        assert adjacent_data["status"] == "PLANNED"
        assert adjacent_data["id"], "the adjacent shift is created"

        # Genuine overlap: starts 30 minutes before the existing shift ends.
        overlapping = api.create_staffing_shift(
            create_shift_payload(t1["id"], "2026-08-01T15:30:00Z",
                                 "2026-08-01T17:00:00Z"), SUP)
        validate_error(overlapping, ApiErrorId.ERR_SHIFT_OVERLAP)

    def test_cancelled_shift_does_not_block_new_shift(self, api):
        """PRD §3.2: "A new shift may not overlap another `PLANNED` shift of
        the same transporter"
        PRD §3.2: "Cancellation moves a shift from `PLANNED` to `CANCELLED` and
        is permitted only while the shift is `PLANNED`, otherwise
        `ERR_INVALID_SHIFT_STATE`; cancelled shifts are excluded from the
        scheduled-headcount counts in §3.8."

        Design: Difficulty/resource_temporal_overlap/shift_halfopen_overlap_boundary
        """
        hub = create_location("HUB", "Hub", "OTHER", "Z1")
        t1 = add_transporter("T One", hub["id"])
        s1 = add_covering_shift(t1["id"], "2026-08-01T08:00:00Z",
                                "2026-08-01T16:00:00Z")
        cancel_shift(s1["id"])

        # The cancelled shift is no longer PLANNED, so an overlapping window
        # is allowed.
        created = api.create_staffing_shift(
            create_shift_payload(t1["id"], "2026-08-01T12:00:00Z",
                                 "2026-08-01T20:00:00Z"), SUP)
        assert validate_success(created, 201)["status"] == "PLANNED"


class TestSuspendedTransporterShiftCreation:
    def _suspend_transporter(self, api):
        """T One with a PLANNED shift 08:00-16:00, clocked in at 09:00, then
        suspended by the supervisor. Returns (t1,)."""
        set_clock("2026-08-01T09:00:00Z")
        hub = create_location("HUB", "Hub", "OTHER", "Z1")
        t1 = add_transporter("T One", hub["id"])
        add_covering_shift(t1["id"], "2026-08-01T08:00:00Z",
                           "2026-08-01T16:00:00Z")
        clocked = api.set_transporter_status(
            t1["id"], {"status": "ON_SHIFT"}, make_transporter_headers(t1["id"]))
        validate_success(clocked, 200)
        suspended = api.set_transporter_status(t1["id"],
                                               {"status": "SUSPENDED"}, SUP)
        validate_success(suspended, 200)
        return t1

    def test_referential_beats_temporal_on_shift_create(self, api):
        """PRD §2.6: "8. **Business referential** — referenced entities are in
        a fit state (no shifts for suspended transporters, supersede targets
        that qualify, shift coverage at clock-in)."
        PRD §2.6: "9. **Business temporal** — scheduled times not in the past,
        shift non-overlap, and patient minimum separation."
        PRD §2.6: "Because the tiers are ordered, a request that would fail
        several checks always reports the earliest failure: a stale offer
        attempt surfaces `ERR_STALE_VERSION` rather than a state error, and an
        unknown path id surfaces `ERR_NOT_FOUND` before any business rule is
        consulted."
        PRD §3.2: "Planning a shift for a `SUSPENDED` transporter is rejected
        with `ERR_TRANSPORTER_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_shift_create
        """
        t1 = self._suspend_transporter(api)

        # The new 12:00-20:00 shift also overlaps the existing 08:00-16:00
        # PLANNED shift, but the referential tier outranks the temporal tier.
        resp = api.create_staffing_shift(
            create_shift_payload(t1["id"], "2026-08-01T12:00:00Z",
                                 "2026-08-01T20:00:00Z"), SUP)
        validate_error(resp, ApiErrorId.ERR_TRANSPORTER_SUSPENDED)

    def test_shift_for_suspended_transporter_rejected_without_overlap(self, api):
        """PRD §3.2: "Planning a shift for a `SUSPENDED` transporter is
        rejected with `ERR_TRANSPORTER_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_shift_create
        """
        t1 = self._suspend_transporter(api)

        # Next-day window: no overlap, so only the referential rule can fail.
        resp = api.create_staffing_shift(
            create_shift_payload(t1["id"], "2026-08-02T08:00:00Z",
                                 "2026-08-02T16:00:00Z"), SUP)
        validate_error(resp, ApiErrorId.ERR_TRANSPORTER_SUSPENDED)

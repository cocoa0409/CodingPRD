"""Dock booking: vessel fit, window validity, half-open-plus-buffer overlap,
dockage fee tiers, activation, cancellation, and booking OCC."""
from test_helpers import (
    NON_EXISTENT_UUID,
    PM,
    ApiErrorId,
    assert_timestamp_instant,
    book_reservation,
    create_dock,
    create_dock_reservation_payload,
    create_draft_project,
    create_vessel,
    get_project,
    get_success_data,
    setup_contracted_project,
    validate_error,
    validate_success,
)


class TestDockageFeeTiers:
    def test_dockage_fee_loa_tier_boundary_100(self, api):
        """PRD §3.3: "The fee charges the number of whole 24-hour nights fully
        inside the half-open window — the turnaround buffer is never chargeable
        — multiplied by the dock's `daily_rate_cents` and by a length-overall
        multiplier taken from the vessel's `length_m`: 1.00 when she is shorter
        than 100 metres, 1.25 when her length is at least 100 metres and
        shorter than 200 metres, and 1.60 when her length is 200 metres or
        more; the product is rounded half-up to a whole cent."

        Design: Corner/calculations/dockage_fee_loa_tier_boundary_100
        """
        dock = create_dock()
        vessel_at = create_vessel(
            name="MT Boundary", length_m=100.0, beam_m=20.0, draft_m=6.0
        )
        vessel_under = create_vessel(
            name="MT Just Under", length_m=99.9, beam_m=20.0, draft_m=6.0
        )
        project_a = create_draft_project(dock_id=dock["id"], vessel_id=vessel_at["id"])
        project_b = create_draft_project(dock_id=dock["id"], vessel_id=vessel_under["id"])

        reservation_a = book_reservation(
            project_a["id"],
            start_utc="2026-08-01T00:00:00Z",
            end_utc="2026-08-05T00:00:00Z",
            expected_project_version=project_a["version"],
        )
        assert reservation_a["dockage_fee_cents"] == 2000000, (
            f"100.0m selects the 1.25 multiplier: 4 nights x 400000 x 1.25 = "
            f"2000000, got {reservation_a['dockage_fee_cents']}"
        )

        reservation_b = book_reservation(
            project_b["id"],
            start_utc="2026-08-06T00:00:00Z",
            end_utc="2026-08-10T00:00:00Z",
            expected_project_version=project_b["version"],
        )
        assert reservation_b["dockage_fee_cents"] == 1600000, (
            f"99.9m stays at the 1.00 multiplier: 4 nights x 400000 = 1600000, "
            f"got {reservation_b['dockage_fee_cents']}"
        )


class TestVesselFit:
    def test_vessel_exactly_at_all_dock_limits_fits(self, api):
        """PRD §3.3: "The vessel must fit the dock: her `length_m` must not
        exceed the dock's `max_length_m`, her `beam_m` must not exceed
        `max_beam_m`, and her `draft_m` must not exceed `max_depth_m` — all
        three comparisons are inclusive, so a vessel exactly at a limit fits —
        and any excess is rejected with `ERR_VESSEL_EXCEEDS_DOCK_LIMITS`."

        Design: Difficulty/boundary_precision_check/vessel_length_exactly_equal_dock_limit_fits
        """
        dock = create_dock()
        vessel = create_vessel(
            name="MT Exact Fit", length_m=230.0, beam_m=40.0, draft_m=12.0
        )
        project = create_draft_project(dock_id=dock["id"], vessel_id=vessel["id"])
        reservation = book_reservation(
            project["id"], expected_project_version=project["version"]
        )
        assert reservation["status"] == "BOOKED", (
            "230.0 <= 230.0, 40.0 <= 40.0, 12.0 <= 12.0 — the boundary is inclusive"
        )

    def test_vessel_exactly_at_beam_limit_alone_fits(self, api):
        """PRD §3.3: "all three comparisons are inclusive, so a vessel exactly
        at a limit fits — and any excess is rejected with
        `ERR_VESSEL_EXCEEDS_DOCK_LIMITS`."

        Design: Difficulty/boundary_precision_check/vessel_length_exactly_equal_dock_limit_fits
        """
        dock = create_dock()
        vessel = create_vessel(
            name="MT Beam Exact", length_m=200.0, beam_m=40.0, draft_m=10.0
        )
        project = create_draft_project(dock_id=dock["id"], vessel_id=vessel["id"])
        reservation = book_reservation(
            project["id"], expected_project_version=project["version"]
        )
        assert reservation["status"] == "BOOKED", (
            "Each dimension is compared on its own inclusive limit; beam exactly "
            "at max_beam_m passes"
        )

    def test_oversized_vessel_rejected(self, api):
        """PRD §3.3: "all three comparisons are inclusive, so a vessel exactly
        at a limit fits — and any excess is rejected with
        `ERR_VESSEL_EXCEEDS_DOCK_LIMITS`."

        Design: Corner/validations/oversized_vessel_rejected
        """
        dock = create_dock()
        vessel = create_vessel(name="MT Too Long", length_m=231.0)
        project = create_draft_project(dock_id=dock["id"], vessel_id=vessel["id"])
        resp = api.create_dock_reservation(
            create_dock_reservation_payload(
                project["id"], project["version"],
                start_utc="2026-08-01T00:00:00Z", end_utc="2026-08-10T00:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_VESSEL_EXCEEDS_DOCK_LIMITS)


class TestReservationWindow:
    def test_reservation_end_before_start_returns_window_invalid(self, api):
        """PRD §3.3: "The window must be sensible: `end_utc` strictly after
        `start_utc`, or the booking is rejected with
        `ERR_RESERVATION_WINDOW_INVALID`."

        Design: Corner/validations/reservation_end_before_start_returns_window_invalid
        """
        project = create_draft_project()
        resp = api.create_dock_reservation(
            create_dock_reservation_payload(
                project["id"], project["version"],
                start_utc="2026-08-05T00:00:00Z", end_utc="2026-08-05T00:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_RESERVATION_WINDOW_INVALID)


class TestHalfOpenBufferOverlap:
    def test_start_inside_turnaround_buffer_conflicts(self, api):
        """PRD §3.3: "the occupied window — the booked window extended by the
        twelve-hour turnaround buffer — must not intersect the occupied window
        of any other `BOOKED` or `ACTIVE` reservation of the same dock; because
        occupied windows are half-open, a new start falling exactly twelve
        hours after a prior booking's end is allowed, while any stricter
        intersection is rejected with `ERR_DOCK_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/dock_booking_half_open_buffer_overlap
        """
        project = create_draft_project()
        book_reservation(
            project["id"],
            start_utc="2026-08-01T00:00:00Z",
            end_utc="2026-08-10T00:00:00Z",
            expected_project_version=project["version"],
        )
        version_after_first = get_project(project["id"])["version"]

        conflict = api.create_dock_reservation(
            create_dock_reservation_payload(
                project["id"], version_after_first,
                start_utc="2026-08-10T00:00:00Z", end_utc="2026-08-15T00:00:00Z",
            ),
            PM,
        )
        validate_error(conflict, ApiErrorId.ERR_DOCK_SLOT_CONFLICT)

        # The rejected booking created nothing and advanced no version, so the
        # same observed version still books cleanly at the buffer edge.
        follow_on = api.create_dock_reservation(
            create_dock_reservation_payload(
                project["id"], version_after_first,
                start_utc="2026-08-10T12:00:00Z", end_utc="2026-08-15T00:00:00Z",
            ),
            PM,
        )
        reservation = validate_success(follow_on, 201)
        assert reservation["status"] == "BOOKED"

    def test_start_one_minute_before_buffer_end_conflicts(self, api):
        """PRD §2.7: "Because the occupied window is half-open, a booking whose
        start falls exactly twelve hours after a prior booking's end touches
        without overlapping and is permitted."

        Design: Difficulty/resource_temporal_overlap/dock_booking_half_open_buffer_overlap
        """
        project = create_draft_project()
        book_reservation(
            project["id"],
            start_utc="2026-08-01T00:00:00Z",
            end_utc="2026-08-10T00:00:00Z",
            expected_project_version=project["version"],
        )
        version_after_first = get_project(project["id"])["version"]
        resp = api.create_dock_reservation(
            create_dock_reservation_payload(
                project["id"], version_after_first,
                start_utc="2026-08-10T11:59:00Z", end_utc="2026-08-15T00:00:00Z",
            ),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_DOCK_SLOT_CONFLICT)


class TestCancelRestoresAvailability:
    def test_cancel_booked_reservation_moves_to_cancelled(self, api):
        """PRD §3.3: "A `BOOKED` reservation may alternatively be cancelled,
        moving it to `CANCELLED` and freeing its window — turnaround buffer
        included — for future bookings."

        Design: Difficulty/compensating_invariant/book_then_cancel_restores_dock_availability
        """
        project = create_draft_project()
        reservation = book_reservation(
            project["id"],
            start_utc="2026-08-01T00:00:00Z",
            end_utc="2026-08-10T00:00:00Z",
            expected_project_version=project["version"],
        )
        cancelled = validate_success(api.cancel_dock_reservation(reservation["id"], PM))
        assert cancelled["status"] == "CANCELLED"

    def test_third_party_rebooks_exact_cancelled_window(self, api):
        """PRD §3.3: "A `BOOKED` reservation may alternatively be cancelled,
        moving it to `CANCELLED` and freeing its window — turnaround buffer
        included — for future bookings."

        Design: Difficulty/compensating_invariant/book_then_cancel_restores_dock_availability
        """
        project1 = create_draft_project()
        reservation = book_reservation(
            project1["id"],
            start_utc="2026-08-01T00:00:00Z",
            end_utc="2026-08-10T00:00:00Z",
            expected_project_version=project1["version"],
        )
        get_success_data(api.cancel_dock_reservation(reservation["id"], PM))

        project2 = create_draft_project(
            dock_id=project1["dock_id"], vessel_id=project1["vessel_id"]
        )
        rebooked = book_reservation(
            project2["id"],
            start_utc="2026-08-01T00:00:00Z",
            end_utc="2026-08-10T00:00:00Z",
            expected_project_version=project2["version"],
        )
        assert rebooked["status"] == "BOOKED", (
            "Cancellation fully returned the window — buffer tail included — to "
            "the dock's available capacity"
        )


class TestActivation:
    def test_activate_before_window_returns_invalid_state(self, api):
        """PRD §3.3: "activating against a project in any other state is
        rejected with `ERR_PROJECT_NOT_CONTRACTED`, and activating outside the
        window is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/activate_before_window_returns_invalid_state
        """
        ctx = setup_contracted_project()
        reservation = book_reservation(
            ctx["project"]["id"],
            start_utc="2026-08-05T00:00:00Z",
            end_utc="2026-08-20T00:00:00Z",
        )
        resp = api.activate_dock_reservation(reservation["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reservation_activate_docks_project(self, api):
        """PRD §3.3: "Activation stamps `activated_at_utc` — null until this
        moment — moves the reservation to `ACTIVE`, and in the same stroke
        moves the parent project from `CONTRACTED` to `IN_DOCK`:
        `actual_dock_in_utc` is set to the current logical time"

        Design: Corner/state_machines/reservation_activate_docks_project
        """
        ctx = setup_contracted_project()
        reservation = book_reservation(ctx["project"]["id"])
        activated = validate_success(api.activate_dock_reservation(reservation["id"], PM))
        assert activated["status"] == "ACTIVE"
        assert_timestamp_instant(activated["activated_at_utc"], "2026-08-01T00:00:00")

        project = get_project(ctx["project"]["id"])
        assert project["status"] == "IN_DOCK"
        assert_timestamp_instant(project["actual_dock_in_utc"], "2026-08-01T00:00:00")

    def test_activate_uncontracted_project_returns_not_contracted(self, api):
        """PRD §3.3: "While a reservation is `BOOKED` and the logical time
        falls inside its window — on or after `start_utc` and strictly before
        `end_utc` — the `ProjectManager` may activate it, provided the parent
        project is `CONTRACTED`; activating against a project in any other
        state is rejected with `ERR_PROJECT_NOT_CONTRACTED`"

        Design: Corner/errors/activate_uncontracted_project_returns_not_contracted
        """
        project = create_draft_project()
        reservation = book_reservation(
            project["id"], expected_project_version=project["version"]
        )
        resp = api.activate_dock_reservation(reservation["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_CONTRACTED)

    def test_existence_before_state_on_activate_unknown_reservation(self, api):
        """PRD §2.9: "Identifier resolution: path identifiers first, resolved
        left to right, then identifiers referenced in the body (`vessel_id`,
        `dock_id`, `project_id`, `work_item_id`, `subcontractor_id`, and each
        element of `depends_on_ids`) — the first miss yields `ERR_NOT_FOUND`."
        (Identifier resolution is rung 4; state preconditions are rung 5.)

        Design: Corner/validations/existence_before_state_on_activate_unknown_reservation
        """
        resp = api.activate_dock_reservation(NON_EXISTENT_UUID, PM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestReservationOcc:
    def test_occ_stale_version_on_reservation_create(self, api):
        """PRD §2.8: "If the project's current `version` differs from the
        supplied value — because another writer has since submitted the bid,
        awarded the contract, booked a window, proposed a change order, or
        otherwise mutated the project — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and nothing is created."
        PRD §2.8: "Both of these creations themselves increment the parent
        project's `version` by one, which is exactly what makes a second write
        against an unrefreshed copy fail: the client must re-read the project
        and resubmit with the current version."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_reservation_create
        """
        project = create_draft_project()
        observed = project["version"]
        first = book_reservation(
            project["id"],
            start_utc="2026-08-01T00:00:00Z",
            end_utc="2026-08-10T00:00:00Z",
            expected_project_version=observed,
        )
        assert first["status"] == "BOOKED"

        stale = api.create_dock_reservation(
            create_dock_reservation_payload(
                project["id"], observed,
                start_utc="2026-08-15T00:00:00Z", end_utc="2026-08-20T00:00:00Z",
            ),
            PM,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        refreshed = get_project(project["id"])["version"]
        assert refreshed == observed + 1, (
            f"First booking incremented the project version by exactly one "
            f"({observed} -> {refreshed})"
        )
        retried = book_reservation(
            project["id"],
            start_utc="2026-08-15T00:00:00Z",
            end_utc="2026-08-20T00:00:00Z",
            expected_project_version=refreshed,
        )
        assert retried["status"] == "BOOKED", (
            "A disjoint window booked against the refreshed version is legitimate"
        )

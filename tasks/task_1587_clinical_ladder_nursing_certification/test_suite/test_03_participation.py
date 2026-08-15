"""Participation events: enum/points validation, verification lifecycle,
24-month lookback window, and snapshot-vs-live divergence (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_verified_points,
    create_criterion,
    create_draft_application,
    create_nurse,
    create_participation_event,
    get_application,
    make_nurse_headers,
    set_clock,
    setup_submitted_application,
    validate_error,
    validate_success,
    verify_event,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestParticipationValidation:
    def test_participation_event_invalid_kind_enum_rejected(self, api):
        """PRD §2.8: "A request whose payload is missing a required field,
        carries a value of the wrong type, or names an enum value outside the
        declared set fails with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/participation_event_invalid_kind_enum_rejected
        """
        nurse = create_nurse(employee_code="RN-PE1", full_name="Pe One")
        resp = api.create_participation_event(
            {
                "nurse_id": nurse["id"],
                "event_kind": "NOT_A_KIND",
                "points": 5,
                "occurred_on": "2026-01-01T00:00:00Z",
            },
            make_nurse_headers(nurse["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_committee_seat_points_cap(self, api):
        """PRD §3.2: "Points must fall between 1 and 40 inclusive, and a
        `COMMITTEE_SEAT` event is additionally capped at 20 points; anything
        outside those bounds is rejected with
        `ERR_PARTICIPATION_POINTS_RANGE` (HTTP 422)."

        Design: Corner/validations/committee_seat_points_cap
        """
        nurse = create_nurse(employee_code="RN-PP1", full_name="Pp One")
        resp = api.create_participation_event(
            {
                "nurse_id": nurse["id"],
                "event_kind": "COMMITTEE_SEAT",
                "points": 21,
                "occurred_on": "2026-01-01T00:00:00Z",
            },
            make_nurse_headers(nurse["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARTICIPATION_POINTS_RANGE, 422)


class TestParticipationLifecycle:
    def test_participation_void_terminal_no_verify(self, api):
        """PRD §3.2: "Both terminal states are final; acting on an event that
        has already left `PENDING_VERIFICATION` fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/participation_void_terminal_no_verify
        """
        nurse = create_nurse(employee_code="RN-PE2", full_name="Pe Two")
        event = create_participation_event(nurse["id"], points=5)
        voided = validate_success(
            api.void_participation_event(event["id"], ADMIN)
        )
        assert voided["status"] == "VOIDED"
        resp = api.verify_participation_event(event["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestParticipationWindow:
    def test_window_boundaries_and_status_filtering(self, api):
        """PRD §3.2: "Only `VERIFIED` events count, an event dated exactly at the
        window start is included, and an event dated exactly at the clock
        position is excluded; the result is the plain integer sum of the
        included events' `points`, with no rounding."

        Design: Corner/calculations/participation_window_excludes_pending_and_future_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        create_criterion(target_level="CN_II", min_participation_points=5)
        nurse = create_nurse(employee_code="RN-PW", full_name="Pw Nurse",
                             hire_date="2018-01-01T00:00:00Z")
        nurse_headers = make_nurse_headers(nurse["id"])
        # Exactly at window start (2024-08-01): included.
        e1 = create_participation_event(nurse["id"], points=5,
                                        occurred_on="2024-08-01T00:00:00Z")
        verify_event(e1["id"])
        # Exactly at the clock position (2026-08-01): excluded (half-open).
        e2 = create_participation_event(nurse["id"], points=5,
                                        occurred_on="2026-08-01T00:00:00Z")
        verify_event(e2["id"])
        # Inside the window but never verified: excluded by status.
        create_participation_event(nurse["id"], points=5,
                                   occurred_on="2026-01-01T00:00:00Z")
        app = create_draft_application(nurse, "CN_II")
        submitted = validate_success(
            api.submit_application(app["id"], nurse_headers)
        )
        assert submitted["participation_snapshot_points"] == 5, (
            "only the window-start VERIFIED event counts: got "
            f"{submitted['participation_snapshot_points']}"
        )


class TestSnapshotVsLive:
    def _setup_snapshot_scenario(self, api):
        """Nurse with 10 VERIFIED points and one 5-point event that is verified
        only AFTER the application is submitted."""
        set_clock("2026-08-01T00:00:00Z")
        create_criterion(target_level="CN_II", min_participation_points=10)
        nurse = create_nurse(employee_code="RN-10", full_name="Snap Nurse",
                             hire_date="2018-06-01T00:00:00Z")
        add_verified_points(nurse["id"], 10, "2026-01-15T00:00:00Z")
        pending = create_participation_event(
            nurse["id"], event_kind="PRECEPTORSHIP", points=5,
            occurred_on="2026-02-15T00:00:00Z",
        )
        app = create_draft_application(nurse, "CN_II")
        submitted = validate_success(
            api.submit_application(app["id"], make_nurse_headers(nurse["id"]))
        )
        return nurse, pending, submitted

    def test_submit_freezes_participation_snapshot(self, api):
        """PRD §3.2: "...a snapshot variant frozen onto the application at
        submission, after which later verification of still-pending events does
        not retroactively raise the frozen figure."

        Design: Difficulty/dual_variant_calc/participation_snapshot_vs_live_on_application
        """
        nurse, pending, submitted = self._setup_snapshot_scenario(api)
        assert submitted["participation_snapshot_points"] == 10
        verify_event(pending["id"])
        reread = get_application(submitted["id"])
        assert reread["participation_snapshot_points"] == 10, (
            "frozen snapshot must not absorb events verified after submission"
        )

    def test_live_window_diverges_from_snapshot_after_late_verification(self, api):
        """PRD §3.2: "Divergence between the two is itself observable when
        events verify between submission and decision."

        Design: Difficulty/dual_variant_calc/participation_snapshot_vs_live_on_application
        """
        nurse, pending, submitted = self._setup_snapshot_scenario(api)
        verify_event(pending["id"])
        verified = validate_success(
            api.list_nurse_participation_events(
                nurse["id"], ADMIN, params={"status": "VERIFIED"}
            )
        )
        live_sum = sum(e["points"] for e in verified)
        assert live_sum == 15, f"live VERIFIED sum must be 10+5=15, got {live_sum}"
        reread = get_application(submitted["id"])
        assert reread["participation_snapshot_points"] == 10
        assert reread["participation_snapshot_points"] != live_sum


class TestReverseReachability:
    def test_filtered_list_reverse_reachability(self, api):
        """PRD §3.2: "Participation histories are reachable per nurse, and a
        cross-nurse listing accepts `nurse_id`, `event_kind`, and `status`
        filters."

        Design: Corner/endpoints/filtered_list_reverse_reachability
        """
        nurse1 = create_nurse(employee_code="RN-RR1", full_name="Rr One")
        nurse2 = create_nurse(employee_code="RN-RR2", full_name="Rr Two")
        e1 = create_participation_event(nurse1["id"], points=5,
                                        occurred_on="2026-01-01T00:00:00Z")
        e2 = create_participation_event(
            nurse1["id"], event_kind="PRECEPTORSHIP", points=5,
            occurred_on="2026-02-01T00:00:00Z",
        )
        create_participation_event(nurse2["id"], points=5,
                                   occurred_on="2026-03-01T00:00:00Z")
        flat = validate_success(
            api.list_participation_events(ADMIN, params={"nurse_id": nurse1["id"]})
        )
        nested = validate_success(
            api.list_nurse_participation_events(nurse1["id"], ADMIN)
        )
        assert len(flat) == 2 and len(nested) == 2
        assert {e["id"] for e in flat} == {e["id"] for e in nested} == {
            e1["id"], e2["id"]
        }

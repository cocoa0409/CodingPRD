"""Maintenance windows and backup fueling arrangements: overlap/buffer
discipline, aggregate capacity, continuity-of-service gating, lifecycle
guards, and the window-start outage cascade (PRD §2.7, §2.8, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_compressor,
    authorize_session_ok,
    create_active_station,
    create_backup,
    create_inspection,
    create_station,
    create_window,
    get_account,
    set_clock,
    setup_fueling_ready,
    validate_error,
    validate_success,
)


class TestWindowOverlap:
    """Difficulty instance: window_pairwise_half_open_with_turnaround_buffer
    (two tests)."""

    def _setup(self, api):
        station_payload = {"station_name": "Papa", "station_code": "ST-PAPA"}
        station = create_station(**station_payload)
        compressor = add_compressor(station["id"])
        w1 = create_window(
            station["id"],
            compressor_id=compressor["id"],
            starts_at="2026-08-20T10:00:00Z",
            ends_at="2026-08-20T12:00:00Z",
        )
        return station, compressor, w1

    def test_adjacent_and_overlapping_windows_rejected(self, api, station_manager_headers):
        """PRD §3.6: "Against each existing SCHEDULED or IN_PROGRESS window on
        the same resource, two half-open-interval tests run. If the new window
        starts before the existing window ends and the existing window starts
        before the new window ends, the two overlap and creation is rejected.
        Otherwise a turnaround buffer applies: when the new window starts at or
        after the existing window's end, the gap between that end and the new
        start must be at least two hours, and symmetrically when the existing
        window starts at or after the new window's end; a gap of exactly two
        hours is permitted. Any violation — overlap or insufficient buffer —
        is `ERR_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/window_pairwise_half_open_with_turnaround_buffer
        """
        station, compressor, _w1 = self._setup(api)
        resp_adjacent = api.create_maintenance_window(
            {
                "station_id": station["id"],
                "compressor_id": compressor["id"],
                "starts_at": "2026-08-20T12:00:00Z",
                "ends_at": "2026-08-20T14:00:00Z",
                "window_type": "PREVENTIVE",
            },
            station_manager_headers,
        )
        validate_error(resp_adjacent, ApiErrorId.ERR_WINDOW_OVERLAP, 409)
        resp_overlap = api.create_maintenance_window(
            {
                "station_id": station["id"],
                "compressor_id": compressor["id"],
                "starts_at": "2026-08-20T11:00:00Z",
                "ends_at": "2026-08-20T13:00:00Z",
                "window_type": "CORRECTIVE",
            },
            station_manager_headers,
        )
        validate_error(resp_overlap, ApiErrorId.ERR_WINDOW_OVERLAP, 409)

    def test_exactly_two_hour_gap_allowed(self, api, station_manager_headers):
        """PRD §3.6: "Otherwise a turnaround buffer applies: when the new
        window starts at or after the existing window's end, the gap between
        that end and the new start must be at least two hours, and
        symmetrically when the existing window starts at or after the new
        window's end; a gap of exactly two hours is permitted. Any violation —
        overlap or insufficient buffer — is `ERR_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/window_pairwise_half_open_with_turnaround_buffer
        """
        station, compressor, w1 = self._setup(api)
        resp = api.create_maintenance_window(
            {
                "station_id": station["id"],
                "compressor_id": compressor["id"],
                "starts_at": "2026-08-20T14:00:00Z",
                "ends_at": "2026-08-20T16:00:00Z",
                "window_type": "PREVENTIVE",
            },
            station_manager_headers,
        )
        w4 = validate_success(resp, 201)
        assert w4["status"] == "SCHEDULED", "gap of exactly 2 hours >= buffer is allowed"
        w1_after = validate_success(
            api.get_maintenance_window(w1["id"], station_manager_headers), 200
        )
        assert w1_after["status"] == "SCHEDULED", "first window remains unaffected"


class TestBackupAggregateCapacity:
    """Difficulty instance: backup_aggregate_capacity_with_equality (two tests)."""

    def _setup(self):
        station = create_station(station_name="Quebec", station_code="ST-QUEBEC")
        b1 = create_backup(
            station["id"],
            partner_station_code="ST-P1",
            available_from="2026-08-10T00:00:00Z",
            available_until="2026-08-20T00:00:00Z",
            committed_gge=3000,
        )
        return station, b1

    def test_overlapping_reservations_fit_capacity_exactly(self, api):
        """PRD §3.6: "Creation enforces aggregate-capacity semantics —
        deliberately different from the pairwise window rule: overlapping
        arrangements at the same station are allowed, but the sum of
        `committed_gge` over the station's existing RESERVED or ACTIVATED
        arrangements whose half-open availability intervals overlap the new one
        (two such intervals overlap when each starts before the other ends),
        plus the new arrangement's `committed_gge`, must not exceed the
        station's `backup_capacity_gge`; equality is permitted, and a breach is
        `ERR_BACKUP_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/backup_aggregate_capacity_with_equality
        """
        station, b1 = self._setup()
        b2 = create_backup(
            station["id"],
            partner_station_code="ST-P2",
            available_from="2026-08-15T00:00:00Z",
            available_until="2026-08-25T00:00:00Z",
            committed_gge=2000,
        )
        assert b2["status"] == "RESERVED", (
            "aggregate 3000 + 2000 == 5000 fits the cap exactly — equality allowed"
        )
        assert b1["used_gge"] == 0

    def test_one_gge_beyond_capacity_rejected(self, api, station_manager_headers):
        """PRD §3.6: "Creation enforces aggregate-capacity semantics —
        deliberately different from the pairwise window rule: overlapping
        arrangements at the same station are allowed, but the sum of
        `committed_gge` over the station's existing RESERVED or ACTIVATED
        arrangements whose half-open availability intervals overlap the new one
        (two such intervals overlap when each starts before the other ends),
        plus the new arrangement's `committed_gge`, must not exceed the
        station's `backup_capacity_gge`; equality is permitted, and a breach is
        `ERR_BACKUP_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/backup_aggregate_capacity_with_equality
        """
        station, _b1 = self._setup()
        create_backup(
            station["id"],
            partner_station_code="ST-P2",
            available_from="2026-08-15T00:00:00Z",
            available_until="2026-08-25T00:00:00Z",
            committed_gge=2000,
        )
        resp = api.create_backup_arrangement(
            {
                "station_id": station["id"],
                "partner_station_code": "ST-P3",
                "available_from": "2026-08-16T00:00:00Z",
                "available_until": "2026-08-18T00:00:00Z",
                "committed_gge": 1,
            },
            station_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BACKUP_CAPACITY_EXCEEDED, 409)


class TestWindowStartOutageCascade:
    """Difficulty instance: maintenance_window_start_outage_cascade (two tests)."""

    def _setup_and_start(self, api, station_manager_headers):
        env = setup_fueling_ready(station_name="Hotel", station_code="ST-HOTEL")
        station_id = env["station"]["id"]
        compressor_id = env["compressor"]["id"]
        backup = create_backup(
            station_id,
            partner_station_code="ST-PARTNER",
            available_from="2026-08-10T00:00:00Z",
            available_until="2026-08-20T00:00:00Z",
            committed_gge=1000,
        )
        window = create_window(
            station_id,
            compressor_id=compressor_id,
            starts_at="2026-08-10T09:00:00Z",
            ends_at="2026-08-10T17:00:00Z",
        )
        set_clock("2026-08-10T08:00:00Z")
        validate_success(
            api.activate_backup_arrangement(backup["id"], station_manager_headers), 200
        )
        set_clock("2026-08-10T09:30:00Z")
        session = authorize_session_ok(
            env["card"]["id"], env["dispenser"]["id"], "CR-M1", 20.0
        )
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 5780
        started = validate_success(
            api.start_maintenance_window(window["id"], station_manager_headers), 200
        )
        return env, compressor_id, window, session, started

    def test_window_start_drives_compressor_and_posture(self, api, station_manager_headers):
        """PRD §3.6: "On a successful start the window becomes IN_PROGRESS, its
        `version` increments, any linked compressor moves to UNDER_MAINTENANCE
        (its `version` incrementing as well), and the station posture is
        recomputed — if the station tips to OUTAGE, every AUTHORIZED session
        there is voided with STATION_OUTAGE and its hold released per §2.7."
        PRD §2.7: "Count the station's compressors whose condition is ONLINE or
        DEGRADED, and count its dispensers whose status is IN_SERVICE. If
        either count is zero, the posture is OUTAGE."

        Design: Difficulty/transitive_cascade/maintenance_window_start_outage_cascade
        """
        env, compressor_id, _window, _session, started = self._setup_and_start(
            api, station_manager_headers
        )
        assert started["status"] == "IN_PROGRESS"
        compressor = validate_success(
            api.get_compressor(compressor_id, station_manager_headers), 200
        )
        assert compressor["condition"] == "UNDER_MAINTENANCE"
        station = validate_success(
            api.get_station(env["station"]["id"], station_manager_headers), 200
        )
        assert station["uptime_posture"] == "OUTAGE", (
            "zero online compressors remain"
        )

    def test_outage_voids_authorized_sessions_and_releases_holds(
        self, api, station_manager_headers
    ):
        """PRD §2.7: "Whenever a recompute changes a station's posture to
        OUTAGE, a void cascade fires: every AUTHORIZED fueling session at that
        station is voided with `void_reason` STATION_OUTAGE, processed in
        `created_at` ascending order, and each affected private session
        releases its hold — the account's `outstanding_balance_cents` decreases
        by the session's `hold_amount_cents` and the account's `version`
        increments by one per session."

        Design: Difficulty/transitive_cascade/maintenance_window_start_outage_cascade
        """
        env, _cmp, _window, session, _started = self._setup_and_start(
            api, station_manager_headers
        )
        after = validate_success(
            api.get_fueling_session(session["id"], station_manager_headers), 200
        )
        assert after["status"] == "VOIDED"
        assert after["void_reason"] == "STATION_OUTAGE"
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 0, (
            "5780 hold fully reversed by the cascade"
        )


class TestWindowCreatePriority:
    """Difficulty instance: window_create_overdue_inspection_beats_overlap
    (two tests)."""

    def _setup(self, station_manager_headers):
        env = create_active_station(station_name="Kilo", station_code="ST-KILO")
        station_id = env["station"]["id"]
        compressor_id = env["compressors"][0]["id"]
        w1 = create_window(
            station_id,
            compressor_id=compressor_id,
            starts_at="2026-08-20T10:00:00Z",
            ends_at="2026-08-20T12:00:00Z",
        )
        inspection = create_inspection(
            station_id, scheduled_for="2026-08-02T10:00:00Z"
        )
        set_clock("2026-08-03T00:00:00Z")
        return env, compressor_id, w1, inspection

    def test_overdue_inspection_beats_window_overlap(self, api, station_manager_headers):
        """PRD §2.8: "The stages run in the order given below, and when several
        checks would fail, the caller receives the error produced by the
        earliest applicable stage — later failures are masked, never reported
        alongside."
        PRD §3.6: "While any inspection at the station is OVERDUE, creating a
        non-EMERGENCY window is refused with `ERR_OVERDUE_INSPECTION`;
        EMERGENCY windows are exempt from that gate."

        Design: Difficulty/priority_pair_validation_conflict/window_create_overdue_inspection_beats_overlap
        """
        env, compressor_id, _w1, inspection = self._setup(station_manager_headers)
        insp = validate_success(
            api.get_safety_inspection(inspection["id"], station_manager_headers), 200
        )
        assert insp["status"] == "OVERDUE", "sweep marked it"
        resp = api.create_maintenance_window(
            {
                "station_id": env["station"]["id"],
                "compressor_id": compressor_id,
                "starts_at": "2026-08-20T11:00:00Z",
                "ends_at": "2026-08-20T13:00:00Z",
                "window_type": "PREVENTIVE",
            },
            station_manager_headers,
        )
        # Safety gate (stage 7) outranks the overlap rule (stage 8).
        validate_error(resp, ApiErrorId.ERR_OVERDUE_INSPECTION, 409)

    def test_overlapping_window_alone_would_fail_with_overlap(
        self, api, station_manager_headers
    ):
        """PRD §3.6: "If the new window starts before the existing window ends
        and the existing window starts before the new window ends, the two
        overlap and creation is rejected."
        PRD §2.8: "7. **Safety gates.** Authorization is refused while a
        station's posture is OUTAGE (`ERR_STATION_OUTAGE`, HTTP 409); claim
        submission, station resume, and non-EMERGENCY window creation are
        refused while the station has an OVERDUE inspection
        (`ERR_OVERDUE_INSPECTION`, HTTP 409); an inspection approver must
        differ from its performer (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403); and
        starting a window that would remove the station's last online
        compression capacity without covering backup is refused
        (`ERR_BACKUP_REQUIRED`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/window_create_overdue_inspection_beats_overlap
        """
        env, compressor_id, w1, _insp = self._setup(station_manager_headers)
        resp = api.create_maintenance_window(
            {
                "station_id": env["station"]["id"],
                "compressor_id": compressor_id,
                "starts_at": "2026-08-20T11:00:00Z",
                "ends_at": "2026-08-20T13:00:00Z",
                "window_type": "PREVENTIVE",
            },
            station_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OVERDUE_INSPECTION, 409)
        w1_after = validate_success(
            api.get_maintenance_window(w1["id"], station_manager_headers), 200
        )
        assert w1_after["status"] == "SCHEDULED", "first window unaffected"


class TestWindowLifecycleGuards:
    def test_window_invalid_time_range_rejected(self, api, station_manager_headers):
        """PRD §3.6: "A `StationManager` schedules a window with `station_id`,
        an optional `compressor_id` — null marking a whole-station window — a
        `starts_at` that is inclusive, an `ends_at` that is exclusive and must
        be strictly later than `starts_at` (else `ERR_INVALID_TIME_RANGE`), and
        a `window_type` of PREVENTIVE, CORRECTIVE, or EMERGENCY."

        Design: Corner/validations/window_invalid_time_range_rejected
        """
        station = create_station(station_name="TR", station_code="ST-TR")
        compressor = add_compressor(station["id"])
        resp = api.create_maintenance_window(
            {
                "station_id": station["id"],
                "compressor_id": compressor["id"],
                "starts_at": "2026-08-20T10:00:00Z",
                "ends_at": "2026-08-20T10:00:00Z",
                "window_type": "PREVENTIVE",
            },
            station_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE, 422)

    def test_window_start_outside_time_range_rejected(self, api, station_manager_headers):
        """PRD §3.6: "Starting a window requires it to be SCHEDULED, else
        `ERR_WINDOW_NOT_STARTABLE` (HTTP 409), and the logical now must fall
        within the window — on or after `starts_at` and strictly before
        `ends_at` — else `ERR_WINDOW_NOT_IN_TIME_RANGE` (HTTP 409)."

        Design: Corner/validations/window_start_outside_time_range_rejected
        """
        station = create_station(station_name="Early", station_code="ST-EARLY")
        compressor = add_compressor(station["id"])
        window = create_window(
            station["id"],
            compressor_id=compressor["id"],
            starts_at="2026-08-01T10:00:00Z",
            ends_at="2026-08-01T12:00:00Z",
        )
        set_clock("2026-08-01T09:00:00Z")
        resp = api.start_maintenance_window(window["id"], station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_IN_TIME_RANGE, 409)
        after = validate_success(
            api.get_maintenance_window(window["id"], station_manager_headers), 200
        )
        assert after["status"] == "SCHEDULED"

    def test_window_start_last_compressor_requires_backup(self, api, station_manager_headers):
        """PRD §3.6: "There is also a continuity-of-service gate: starting a
        non-EMERGENCY window whose compressor is the station's only compressor
        in ONLINE or DEGRADED condition — or a whole-station window while any
        fueling capacity would be lost — requires an ACTIVATED backup
        arrangement whose `available_from` is on or before `starts_at` and
        whose `available_until` is on or after `ends_at`; without one the start
        is refused with `ERR_BACKUP_REQUIRED` (HTTP 409)."

        Design: Corner/validations/window_start_last_compressor_requires_backup
        """
        env = create_active_station(station_name="NoBk", station_code="ST-NOBK")
        window = create_window(
            env["station"]["id"],
            compressor_id=env["compressors"][0]["id"],
            starts_at="2026-08-01T00:00:00Z",
            ends_at="2026-08-01T06:00:00Z",
        )
        set_clock("2026-08-01T03:00:00Z")
        resp = api.start_maintenance_window(window["id"], station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BACKUP_REQUIRED, 409)

    def test_window_complete_before_start_rejected(self, api, station_manager_headers):
        """PRD §3.6: "Completing a window requires IN_PROGRESS, else
        `ERR_WINDOW_NOT_COMPLETABLE`; the window becomes COMPLETED and any
        linked compressor returns ONLINE, with posture recomputed."

        Design: Corner/validations/window_complete_before_start_rejected
        """
        station = create_station(station_name="WComp", station_code="ST-WCOMP")
        compressor = add_compressor(station["id"])
        window = create_window(station["id"], compressor_id=compressor["id"])
        resp = api.complete_maintenance_window(window["id"], station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_COMPLETABLE, 409)

    def test_window_cancel_after_start_rejected(self, api, station_manager_headers):
        """PRD §3.6: "Cancelling requires SCHEDULED, else
        `ERR_WINDOW_NOT_CANCELLABLE`, and lands the window in CANCELLED."

        Design: Corner/validations/window_cancel_after_start_rejected
        """
        env = create_active_station(
            station_name="WCx", station_code="ST-WCX", num_compressors=2
        )
        window = create_window(
            env["station"]["id"],
            compressor_id=env["compressors"][0]["id"],
            starts_at="2026-08-01T01:00:00Z",
            ends_at="2026-08-01T05:00:00Z",
            window_type="CORRECTIVE",
        )
        set_clock("2026-08-01T02:00:00Z")
        validate_success(
            api.start_maintenance_window(window["id"], station_manager_headers), 200
        )
        resp = api.cancel_maintenance_window(window["id"], station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_CANCELLABLE, 409)
        after = validate_success(
            api.get_maintenance_window(window["id"], station_manager_headers), 200
        )
        assert after["status"] == "IN_PROGRESS"

    def test_report_condition_while_under_maintenance_rejected(
        self, api, station_manager_headers
    ):
        """PRD §3.1: "No condition report is accepted while a compressor is
        UNDER_MAINTENANCE: the attempt fails with
        `ERR_COMPRESSOR_UNDER_MAINTENANCE` (HTTP 409)."

        Design: Corner/validations/report_condition_while_under_maintenance_rejected
        """
        env = create_active_station(
            station_name="UM", station_code="ST-UM", num_compressors=2
        )
        cmp1 = env["compressors"][0]
        window = create_window(
            env["station"]["id"],
            compressor_id=cmp1["id"],
            starts_at="2026-08-01T01:00:00Z",
            ends_at="2026-08-01T05:00:00Z",
        )
        set_clock("2026-08-01T02:00:00Z")
        validate_success(
            api.start_maintenance_window(window["id"], station_manager_headers), 200
        )
        resp = api.report_compressor_condition(
            cmp1["id"], {"condition": "OFFLINE"}, station_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_COMPRESSOR_UNDER_MAINTENANCE, 409)
        after = validate_success(api.get_compressor(cmp1["id"], station_manager_headers), 200)
        assert after["condition"] == "UNDER_MAINTENANCE"


class TestBackupLifecycleGuards:
    def test_backup_activate_outside_availability_rejected(self, api, station_manager_headers):
        """PRD §3.6: "Activation moves an arrangement from RESERVED to
        ACTIVATED and requires the logical now to lie within the availability
        window — on or after `available_from` and on or before
        `available_until`, both ends inclusive for this check alone; a RESERVED
        violation is `ERR_BACKUP_NOT_ACTIVATABLE` and an out-of-window attempt
        is `ERR_BACKUP_NOT_IN_WINDOW` (both HTTP 409)."

        Design: Corner/validations/backup_activate_outside_availability_rejected
        """
        station = create_station(station_name="EarlyBk", station_code="ST-EBK")
        backup = create_backup(
            station["id"],
            partner_station_code="ST-PE",
            available_from="2026-08-10T00:00:00Z",
            available_until="2026-08-20T00:00:00Z",
            committed_gge=500,
        )
        # Default clock 2026-08-01 is before available_from.
        resp = api.activate_backup_arrangement(backup["id"], station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BACKUP_NOT_IN_WINDOW, 409)
        after = validate_success(
            api.get_backup_arrangement(backup["id"], station_manager_headers), 200
        )
        assert after["status"] == "RESERVED"

    def test_record_draw_requires_activated_arrangement(self, api, station_manager_headers):
        """PRD §3.6: "While ACTIVATED, partner draws are recorded against the
        arrangement: each draw supplies a `gge_amount`, requires ACTIVATED
        status (else `ERR_BACKUP_NOT_ACTIVE`, HTTP 409), and is accepted only
        while the running `used_gge` plus the new `gge_amount` stays at or
        below `committed_gge` — equality allowed — else
        `ERR_BACKUP_DRAW_EXCEEDED` (HTTP 409); accepted draws accumulate into
        `used_gge` and increment the arrangement's `version`."

        Design: Corner/validations/record_draw_requires_activated_arrangement
        """
        station = create_station(station_name="NoDraw", station_code="ST-NDRAW")
        backup = create_backup(
            station["id"],
            partner_station_code="ST-PF",
            available_from="2026-07-01T00:00:00Z",
            available_until="2026-09-01T00:00:00Z",
            committed_gge=500,
        )
        resp = api.record_backup_draw(
            backup["id"], {"gge_amount": 10.0}, station_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_BACKUP_NOT_ACTIVE, 409)
        after = validate_success(
            api.get_backup_arrangement(backup["id"], station_manager_headers), 200
        )
        assert after["used_gge"] == 0

    def test_backup_release_before_activation_rejected(self, api, station_manager_headers):
        """PRD §3.6: "Releasing an arrangement requires ACTIVATED, else
        `ERR_BACKUP_NOT_RELEASABLE`, lands it in RELEASED, and freezes
        `used_gge`."

        Design: Corner/validations/backup_release_before_activation_rejected
        """
        station = create_station(station_name="BRel", station_code="ST-BREL")
        backup = create_backup(
            station["id"],
            partner_station_code="ST-PG2",
            available_from="2026-07-01T00:00:00Z",
            available_until="2026-09-01T00:00:00Z",
            committed_gge=500,
        )
        resp = api.release_backup_arrangement(backup["id"], station_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BACKUP_NOT_RELEASABLE, 409)


class TestBackupDrawBoundary:
    def test_backup_draw_exact_capacity_then_exceeded(self, api, station_manager_headers):
        """PRD §3.6: "While ACTIVATED, partner draws are recorded against the
        arrangement: each draw supplies a `gge_amount`, requires ACTIVATED
        status (else `ERR_BACKUP_NOT_ACTIVE`, HTTP 409), and is accepted only
        while the running `used_gge` plus the new `gge_amount` stays at or
        below `committed_gge` — equality allowed — else
        `ERR_BACKUP_DRAW_EXCEEDED` (HTTP 409); accepted draws accumulate into
        `used_gge` and increment the arrangement's `version`."

        Design: Corner/calculations/backup_draw_exact_capacity_then_exceeded
        """
        station = create_station(station_name="Draw", station_code="ST-DRAW")
        backup = create_backup(
            station["id"],
            partner_station_code="ST-PD",
            available_from="2026-07-01T00:00:00Z",
            available_until="2026-09-01T00:00:00Z",
            committed_gge=1000,
        )
        validate_success(
            api.activate_backup_arrangement(backup["id"], station_manager_headers), 200
        )
        r1 = validate_success(
            api.record_backup_draw(backup["id"], {"gge_amount": 600.0}, station_manager_headers),
            200,
        )
        assert r1["used_gge"] == pytest.approx(600.0, abs=1e-9)
        r2 = validate_success(
            api.record_backup_draw(backup["id"], {"gge_amount": 400.0}, station_manager_headers),
            200,
        )
        assert r2["used_gge"] == pytest.approx(1000.0, abs=1e-9), (
            "equality at committed_gge is allowed"
        )
        resp = api.record_backup_draw(
            backup["id"], {"gge_amount": 0.001}, station_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_BACKUP_DRAW_EXCEEDED, 409)

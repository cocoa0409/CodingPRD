"""Cutover window scheduling: protected shifts, buffered zone occupancy, abort."""

from test_helpers import (
    SHOP_SUPERVISOR,
    SITE_MANAGER,
    TEST_INSTANTS,
    ApiErrorId,
    abort_cutover,
    assert_cutover_window,
    assert_share_ledger_conserved,
    create_cutover_window_payload,
    make_fat_passed_lot,
    make_frozen_project,
    make_planned_lot,
    make_project,
    make_scheduled_window,
    make_site_zone,
    make_staging_bay,
    read_lot,
    read_project,
    read_window,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProtectedShiftBeforeCrossProjectCoherence:
    """A window that both collides with the shift and names a foreign lot."""

    def _two_projects(self, api):
        host = make_project(api)
        other = make_fat_passed_lot(
            api,
            bay=make_staging_bay(api, bay_code="BAY-6", concurrent_capacity=2),
            segment_codes=["IB-01"],
            lot_code="LOT-600",
            customer_name="Cascade Distribution",
            facility_code="DC-PDX-07",
            customer_rep_user_id="cust-rep-88",
            contract_base_cents=200_000_000,
            authorized_ceiling_cents=260_000_000,
            spares_budget_cents=3_000_000,
            service_tier="BASIC",
            measured_cph=1320,
            defect_count=0,
        )
        zone = make_site_zone(api, host["id"], zone_code="Z-DOCK")
        return host, other, zone

    def test_the_shift_collision_is_reported_before_the_foreign_reference(self, api):
        """Band 11 fires ahead of band 13, so the shift decides the response.

        PRD §2.12: "**Continuing-operations protection** — the requested window does
        not intersect any daily occurrence of the zone's protected shift, otherwise
        `ERR_PROTECTED_SHIFT_COLLISION` (422). Applies to cutover-window creation."

        Design: Difficulty/priority_pair_validation_conflict/protected_shift_check_precedes_cross_project_reference_check
        """
        host, other, zone = self._two_projects(api)

        response = api.create_cutover_window(
            create_cutover_window_payload(
                host["id"],
                zone["id"],
                other["lot"]["id"],
                start_utc="2026-08-12T17:00:00Z",
                end_utc="2026-08-12T21:00:00Z",
            ),
            SITE_MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_PROTECTED_SHIFT_COLLISION.value)

    def test_the_refused_window_leaves_both_projects_untouched(self, api):
        """No window is persisted, the zone stays legacy and the foreign lot is unmoved.

        PRD §2.10: "If the requested interval intersects **any** daily occurrence of
        the zone's protected shift, the request is rejected with
        `ERR_PROTECTED_SHIFT_COLLISION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/protected_shift_check_precedes_cross_project_reference_check
        """
        host, other, zone = self._two_projects(api)
        api.create_cutover_window(
            create_cutover_window_payload(
                host["id"],
                zone["id"],
                other["lot"]["id"],
                start_utc="2026-08-12T17:00:00Z",
                end_utc="2026-08-12T21:00:00Z",
            ),
            SITE_MANAGER,
        )

        _, meta = validate_paginated(
            api.list_cutover_windows(SITE_MANAGER, params={"project_id": host["id"]})
        )
        assert meta["total_count"] == 0

        zones = validate_success(api.list_site_zones(host["id"], SITE_MANAGER))
        assert [entry["ops_status"] for entry in zones] == ["LIVE_LEGACY"]
        assert read_lot(api, other["lot"]["id"])["status"] == "FAT_PASSED"


class TestZoneWindowBufferedSeparation:
    """The zone is an exclusive resource with a sixty minute quiet pad."""

    def _zone_with_one_window(self, api):
        frozen = make_frozen_project(api)
        bay = make_staging_bay(api, bay_code="BAY-10", concurrent_capacity=3)
        first_lot = make_planned_lot(
            api,
            frozen=frozen,
            bay=bay,
            segment_codes=["IB-01"],
            lot_code="LOT-1000",
            occupancy_start_utc="2026-08-03T00:00:00Z",
            occupancy_end_utc="2026-08-05T00:00:00Z",
        )["lot"]
        second_lot = make_planned_lot(
            api,
            frozen=frozen,
            bay=bay,
            segment_codes=["TR-02"],
            lot_code="LOT-1001",
            occupancy_start_utc="2026-08-06T00:00:00Z",
            occupancy_end_utc="2026-08-08T00:00:00Z",
        )["lot"]
        zone = make_site_zone(api, frozen["project"]["id"])
        window = validate_success(
            api.create_cutover_window(
                create_cutover_window_payload(
                    frozen["project"]["id"], zone["id"], first_lot["id"]
                ),
                SITE_MANAGER,
            ),
            expected_status=201,
        )
        return frozen, zone, second_lot, window

    def test_a_window_starting_inside_the_padded_tail_is_rejected(self, api):
        """23:30 falls before the first window's 23:00 end padded by sixty minutes.

        PRD §2.10: "A requested window collides with an existing window of the same
        zone when the requested start instant falls before the existing end instant
        advanced by `buffer_minutes`, **and** the existing start instant falls before
        the requested end instant advanced by `buffer_minutes`; only existing windows
        whose `status` is `SCHEDULED`, `BLOCKED_STALE_DESIGN` or `IN_PROGRESS`
        participate in this test, since completed, aborted and lot-scrapped windows hold
        no reservation."

        Design: Difficulty/resource_temporal_overlap/zone_window_buffer_padded_half_open_exclusion_boundary
        """
        frozen, zone, second_lot, window = self._zone_with_one_window(api)

        response = api.create_cutover_window(
            create_cutover_window_payload(
                frozen["project"]["id"],
                zone["id"],
                second_lot["id"],
                start_utc="2026-08-10T23:30:00Z",
                end_utc="2026-08-11T02:00:00Z",
            ),
            SITE_MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_ZONE_WINDOW_OVERLAP.value)
        assert read_window(api, window["id"])["status"] == "SCHEDULED"

    def test_a_window_starting_exactly_at_the_padded_end_is_accepted(self, api):
        """The padded comparison is strictly less-than, so 00:00 is admitted.

        PRD §3.6: "The two temporal gates of §2.10 apply here and nowhere else: the
        appointment must miss every daily occurrence of that zone's protected shift,
        otherwise `ERR_PROTECTED_SHIFT_COLLISION`, and it must clear every live window on
        the same zone once both sides are padded by the zone's `buffer_minutes`,
        otherwise `ERR_ZONE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/zone_window_buffer_padded_half_open_exclusion_boundary
        """
        frozen, zone, second_lot, window = self._zone_with_one_window(api)

        accepted = validate_success(
            api.create_cutover_window(
                create_cutover_window_payload(
                    frozen["project"]["id"],
                    zone["id"],
                    second_lot["id"],
                    start_utc="2026-08-11T00:00:00Z",
                    end_utc="2026-08-11T03:00:00Z",
                ),
                SITE_MANAGER,
            ),
            expected_status=201,
        )
        assert_cutover_window(accepted)
        assert accepted["status"] == "SCHEDULED"
        assert accepted["start_utc"] == "2026-08-11T00:00:00Z"

        _, meta = validate_paginated(
            api.list_cutover_windows(SITE_MANAGER, params={"site_zone_id": zone["id"]})
        )
        assert meta["total_count"] == 2
        assert read_window(api, window["id"])["status"] == "SCHEDULED"


class TestAbortRestoresTheShareLedger:
    """Start then abort returns the basis-point ledger to its pre-start reading."""

    def _two_zone_project_in_progress(self, api):
        state = make_fat_passed_lot(
            api,
            bay=make_staging_bay(api, bay_code="BAY-12", concurrent_capacity=2),
            segment_codes=["IB-01"],
            lot_code="LOT-1200",
            measured_cph=1320,
            defect_count=0,
        )
        project_id = state["project"]["id"]
        state["zone_in"] = make_site_zone(
            api, project_id, zone_code="Z-INBOUND", throughput_share_bps=4000
        )
        state["zone_out"] = make_site_zone(
            api, project_id, zone_code="Z-OUTBOUND", throughput_share_bps=6000
        )
        state["window"] = validate_success(
            api.create_cutover_window(
                create_cutover_window_payload(
                    project_id, state["zone_in"]["id"], state["lot"]["id"]
                ),
                SITE_MANAGER,
            ),
            expected_status=201,
        )
        set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])
        return state

    def test_starting_the_window_transfers_the_zone_share_into_transition(self, api):
        """Four thousand basis points move out of legacy and into transition.

        PRD §3.6: "A successful start advances the window `SCHEDULED → IN_PROGRESS`,
        stamps `started_at` from the logical clock and increments the window's `version`
        by 1; moves the zone `LIVE_LEGACY → CUTOVER_IN_PROGRESS`; transfers the zone's
        `throughput_share_bps` out of `legacy_share_bps` into `in_transition_share_bps`
        on the project; and, if the project's `delivery_status` was `IN_FABRICATION`,
        bubbles it up to `CUTOVER`."

        Design: Difficulty/compensating_invariant/cutover_abort_restores_facility_share_ledger_without_drift
        """
        state = self._two_zone_project_in_progress(api)
        validate_success(api.start_cutover_window(state["window"]["id"], SITE_MANAGER))

        project = read_project(api, state["project"]["id"])
        assert project["legacy_share_bps"] == 6000
        assert project["in_transition_share_bps"] == 4000
        assert project["cutover_share_bps"] == 0
        assert_share_ledger_conserved(project)
        assert project["delivery_status"] == "CUTOVER"

        zones = {
            zone["zone_code"]: zone
            for zone in validate_success(api.list_site_zones(state["project"]["id"], SITE_MANAGER))
        }
        assert zones["Z-INBOUND"]["ops_status"] == "CUTOVER_IN_PROGRESS"

    def test_aborting_restores_the_ledger_with_zero_drift(self, api):
        """The paired subtract-and-add returns the ledger to 10000, 0 and 0.

        PRD §2.9: "Aborting the window subtracts it from `in_transition_share_bps` and
        adds it back to `legacy_share_bps`, restoring the ledger to its pre-start reading
        with zero drift."

        Design: Difficulty/compensating_invariant/cutover_abort_restores_facility_share_ledger_without_drift
        """
        state = self._two_zone_project_in_progress(api)
        validate_success(api.start_cutover_window(state["window"]["id"], SITE_MANAGER))
        state = abort_cutover(api, state)

        assert state["window"]["status"] == "ABORTED"
        assert state["window"]["abort_reason"] == "Legacy sorter PLC fault during changeover"
        assert state["window"]["closed_at"] is not None

        project = read_project(api, state["project"]["id"])
        assert project["legacy_share_bps"] == 10000
        assert project["in_transition_share_bps"] == 0
        assert project["cutover_share_bps"] == 0
        assert (
            project["legacy_share_bps"]
            + project["in_transition_share_bps"]
            + project["cutover_share_bps"]
            == 10000
        )

        zones = {
            zone["zone_code"]: zone
            for zone in validate_success(api.list_site_zones(state["project"]["id"], SITE_MANAGER))
        }
        assert zones["Z-INBOUND"]["ops_status"] == "LIVE_LEGACY"
        assert zones["Z-OUTBOUND"]["ops_status"] == "LIVE_LEGACY"

    def test_an_aborted_window_never_installs_the_lot(self, api):
        """The lot stays available for another appointment.

        PRD §3.6: "The lot is not advanced by an abort — it remains `FAT_PASSED` and
        available for another window."

        Design: Difficulty/compensating_invariant/cutover_abort_restores_facility_share_ledger_without_drift
        """
        state = self._two_zone_project_in_progress(api)
        validate_success(api.start_cutover_window(state["window"]["id"], SITE_MANAGER))
        abort_cutover(api, state)

        assert read_lot(api, state["lot"]["id"], SHOP_SUPERVISOR)["status"] == "FAT_PASSED"


class TestCutoverCompletionSanity:
    """Completion is the hand-over that installs the lot."""

    def test_completing_the_window_installs_the_lot_and_moves_the_share(self, api):
        """The zone's share lands in cutover and the project reaches commissioning.

        PRD §3.6: "On success the window advances `IN_PROGRESS → COMPLETED` with
        `closed_at` stamped and its `version` incremented; the zone advances
        `CUTOVER_IN_PROGRESS → CUTOVER_COMPLETE`; the zone's share transfers out of
        `in_transition_share_bps` into `cutover_share_bps`; the installed lot advances
        `FAT_PASSED → INSTALLED` with its own `version` incremented; and if every site
        zone of the project has now reached `CUTOVER_COMPLETE`, the project bubbles up
        from `CUTOVER` to `COMMISSIONING`."

        Design: Difficulty/compensating_invariant/cutover_abort_restores_facility_share_ledger_without_drift
        """
        state = make_scheduled_window(api)
        set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])
        validate_success(api.start_cutover_window(state["window"]["id"], SITE_MANAGER))
        completed = validate_success(
            api.complete_cutover_window(state["window"]["id"], SITE_MANAGER)
        )

        assert completed["status"] == "COMPLETED"
        assert completed["closed_at"] is not None
        project = read_project(api, state["project"]["id"])
        assert project["cutover_share_bps"] == 10000
        assert project["in_transition_share_bps"] == 0
        assert project["legacy_share_bps"] == 0
        assert project["delivery_status"] == "COMMISSIONING"
        assert read_lot(api, state["lot"]["id"], SHOP_SUPERVISOR)["status"] == "INSTALLED"

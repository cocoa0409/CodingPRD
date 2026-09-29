"""The weld jig occupancy calendar of PRD 3.2 and its guards.

Covers the half-open geometry with its trailing changeover buffer, the
precedence of the optimistic-concurrency check over the window conflict, and
the cross-entity gate that keeps an uncertified model out of a jig.
"""

import test_helpers as H
from test_helpers import CERT_OFFICER, WELD_SUPERVISOR, validate_error, validate_success


class TestHalfOpenOccupancyGeometry:
    def test_duration_excludes_the_buffer_while_occupancy_end_includes_it(self, api):
        """The stored duration and the stored occupancy end disagree by the buffer.

        PRD 3.2: "An accepted reservation is created against that jig with
        `jig_id` set, `status` `RESERVED`, and two computed quantities:
        `duration_minutes`, the whole minutes between `window_start_at` and
        `window_end_at` with the changeover buffer **excluded**, and
        `occupancy_end_at` as described above."

        Design: Difficulty/resource_temporal_overlap/jig_half_open_window_with_trailing_changeover_buffer
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        unit = H.open_unit(api, model["id"], "SN-000101")

        reservation = H.reserve_jig_window(api, jig["id"], unit["id"], window=H.JIG_WINDOW_1)

        assert reservation["status"] == H.ReservationStatus.RESERVED
        assert reservation["duration_minutes"] == 120
        H.assert_instant(reservation["occupancy_end_at"], H.JIG_WINDOW_1_OCCUPANCY_END)

    def test_a_gap_one_minute_short_of_the_buffer_conflicts_and_the_exact_gap_books(self, api):
        """11:44 collides with the buffered end while 11:45 is accepted.

        PRD 3.2: "Because both comparisons are strict, a gap of exactly the
        buffer length between one window's end and the next window's start is
        accepted, while a gap one minute shorter than the buffer is rejected with
        `ERR_JIG_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/jig_half_open_window_with_trailing_changeover_buffer
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        unit1 = H.open_unit(api, model["id"], "SN-000101")
        unit2 = H.open_unit(api, model["id"], "SN-000102")
        H.reserve_jig_window(api, jig["id"], unit1["id"], window=H.JIG_WINDOW_1)
        fresh_version = H.read_jig(api, jig["id"])["version"]

        too_early = api.reserve_jig(
            jig["id"],
            H.reservation_payload(
                unit2["id"],
                fresh_version,
                window=("2026-08-03T11:44:00Z", "2026-08-03T13:00:00Z"),
            ),
            headers=WELD_SUPERVISOR,
        )
        validate_error(too_early, H.ERR_JIG_WINDOW_CONFLICT)

        accepted = api.reserve_jig(
            jig["id"],
            H.reservation_payload(
                unit2["id"],
                fresh_version,
                window=("2026-08-03T11:45:00Z", "2026-08-03T13:00:00Z"),
            ),
            headers=WELD_SUPERVISOR,
        )

        reservation = validate_success(accepted, expected_status=201)
        assert reservation["status"] == H.ReservationStatus.RESERVED
        assert reservation["duration_minutes"] == 75
        H.assert_instant(reservation["occupancy_end_at"], "2026-08-03T13:45:00Z")
        assert H.read_jig(api, jig["id"])["reserved_minutes_total"] == 195
        assert H.read_unit(api, unit2["id"])["build_status"] == H.BuildStatus.JIG_RESERVED


class TestStaleJigVersionPrecedence:
    def test_stale_version_masks_the_window_conflict_entirely(self, api):
        """A request that is both stale and overlapping reports only the staleness.

        PRD 2.7: "Jig reservation is guarded by five, and a stale jig version is
        reported before the build-state check, which is itself reported before
        the tooling mismatch, which is reported before the window conflict."

        Design: Difficulty/priority_pair_validation_conflict/stale_jig_version_beats_jig_window_conflict
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        stale_version = jig["version"]
        unit1 = H.open_unit(api, model["id"], "SN-000101")
        unit2 = H.open_unit(api, model["id"], "SN-000102")
        H.reserve_jig_window(api, jig["id"], unit1["id"], window=H.JIG_WINDOW_1)

        response = api.reserve_jig(
            jig["id"],
            H.reservation_payload(
                unit2["id"],
                stale_version,
                window=("2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z"),
            ),
            headers=WELD_SUPERVISOR,
        )

        validate_error(response, H.ERR_STALE_JIG_VERSION)

    def test_the_same_overlap_retried_with_a_fresh_version_reports_the_conflict(self, api):
        """Re-reading the jig unmasks the window conflict and nothing was booked.

        PRD 2.8: "so the request is rejected with `ERR_STALE_JIG_VERSION` (HTTP
        412) rather than being silently squeezed into a calendar the caller never
        saw."

        Design: Difficulty/priority_pair_validation_conflict/stale_jig_version_beats_jig_window_conflict
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_certified_model(api)
        jig = H.commission_jig(api)
        stale_version = jig["version"]
        unit1 = H.open_unit(api, model["id"], "SN-000101")
        unit2 = H.open_unit(api, model["id"], "SN-000102")
        H.reserve_jig_window(api, jig["id"], unit1["id"], window=H.JIG_WINDOW_1)
        overlapping = ("2026-08-03T10:00:00Z", "2026-08-03T12:00:00Z")
        api.reserve_jig(
            jig["id"],
            H.reservation_payload(unit2["id"], stale_version, window=overlapping),
            headers=WELD_SUPERVISOR,
        )
        unit2_before = H.read_unit(api, unit2["id"])
        fresh_version = H.read_jig(api, jig["id"])["version"]

        retry = api.reserve_jig(
            jig["id"],
            H.reservation_payload(unit2["id"], fresh_version, window=overlapping),
            headers=WELD_SUPERVISOR,
        )

        validate_error(retry, H.ERR_JIG_WINDOW_CONFLICT)
        reservations, _meta = H.validate_paginated(
            api.list_jig_reservations(jig["id"], headers=WELD_SUPERVISOR)
        )
        assert len(reservations) == 1
        assert H.read_jig(api, jig["id"])["reserved_minutes_total"] == 120
        unit2_after = H.read_unit(api, unit2["id"])
        assert unit2_after["build_status"] == H.BuildStatus.PLANNED
        assert unit2_after["version"] == unit2_before["version"]


class TestModelCertificationGate:
    def test_a_model_under_review_cannot_put_a_trailer_in_the_jig(self, api):
        """The reservation is refused and nothing on either row moves.

        PRD 3.2: "The trailer's model must be in `certification_status` exactly
        `CERTIFIED` — a cross-entity gate, because no trailer may enter a jig on
        an uncertified rating — and a model in any other certification state
        produces `ERR_MODEL_NOT_CERTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/jig_reservation_blocked_until_model_reaches_certified
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_model(api)
        H.submit_model(api, model["id"])
        jig = H.commission_jig(api)
        unit = H.open_unit(api, model["id"], "SN-000101")

        response = api.reserve_jig(
            jig["id"],
            H.reservation_payload(unit["id"], jig["version"], window=H.JIG_WINDOW_1),
            headers=WELD_SUPERVISOR,
        )

        validate_error(response, H.ERR_MODEL_NOT_CERTIFIED)
        assert H.read_jig(api, jig["id"])["reserved_minutes_total"] == 0
        reservations, meta = H.validate_paginated(
            api.list_jig_reservations(jig["id"], headers=WELD_SUPERVISOR)
        )
        assert reservations == []
        assert meta["total_count"] == 0
        after = H.read_unit(api, unit["id"])
        assert after["build_status"] == H.BuildStatus.PLANNED
        assert after["gvwr_lbs"] is None

    def test_once_certified_the_same_window_books_and_pins_the_revision(self, api):
        """The retry pins the model revision and seeds the weight budget.

        PRD 3.2: "`model_version_pinned` takes the model's current `version`, and
        `gvwr_lbs` takes a snapshot of the model's `certified_gvwr_lbs`."

        Design: Difficulty/cross_entity_state_dependency/jig_reservation_blocked_until_model_reaches_certified
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        model = H.create_model(api)
        H.submit_model(api, model["id"])
        jig = H.commission_jig(api)
        unit = H.open_unit(api, model["id"], "SN-000101")
        api.reserve_jig(
            jig["id"],
            H.reservation_payload(unit["id"], jig["version"], window=H.JIG_WINDOW_1),
            headers=WELD_SUPERVISOR,
        )

        H.decide_model(api, model["id"], "CERTIFIED", headers=CERT_OFFICER)
        fresh_version = H.read_jig(api, jig["id"])["version"]
        response = api.reserve_jig(
            jig["id"],
            H.reservation_payload(unit["id"], fresh_version, window=H.JIG_WINDOW_1),
            headers=WELD_SUPERVISOR,
        )

        reservation = validate_success(response, expected_status=201)
        assert reservation["status"] == H.ReservationStatus.RESERVED
        assert reservation["duration_minutes"] == 120
        after = H.read_unit(api, unit["id"])
        assert after["build_status"] == H.BuildStatus.JIG_RESERVED
        assert after["gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS
        assert after["curb_weight_lbs"] == H.TA_BASE_CURB_WEIGHT_LBS
        assert after["payload_capacity_lbs"] == H.TA_PAYLOAD_CAPACITY_LBS
        # model create, certification submission and certification decision
        assert after["model_version_pinned"] == H.TA_MODEL_VERSION_AT_CERTIFICATION

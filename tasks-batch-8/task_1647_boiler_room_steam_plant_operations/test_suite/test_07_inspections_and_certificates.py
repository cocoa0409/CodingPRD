"""Inspections, relief-valve pop tests, certificate lifecycle boundaries,
certificate posting, and buffered inspection scheduling."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_boiler,
    create_inspection_payload,
    create_online_boiler,
    create_plant,
    get_boiler,
    get_plant,
    make_operator_headers,
    record_outcome,
    record_passed_annual,
    run_ops,
    schedule_inspection,
    set_clock,
    setup_plant_with_operators,
    validate_error,
    validate_success,
)


class TestReliefPopParallelDimensions:
    def test_failed_pop_test_suspends_cert_and_trips_boiler(
        self, api, plant_manager_headers
    ):
        """PRD §3.6: "A pop test whose measured lift falls outside the
        envelope — whether the recording arrives as an explicit `FAILED` or
        the envelope check forces it — ends as a `FAILED` outcome with two
        cascades: the boiler's `cert_status` becomes `SUSPENDED`, and its
        `ops_status` is forced to `TRIPPED`. Any explicitly recorded `FAILED`
        pop test carries the same two cascades." PRD §1: "each boiler carries
        three independent status dimensions — operational, certification, and
        water chemistry" — so the water dimension is untouched.

        Design: Difficulty/non_linear_state_machine/boiler_parallel_dimensions_cert_vs_ops
        """
        plant, ops = setup_plant_with_operators(name="Para Plant", count=1)
        op = ops[0]
        boiler = create_online_boiler(plant["id"], op["id"], tag="B-PAR")
        inspection = schedule_inspection(
            plant["id"], boiler["id"], inspection_kind="RELIEF_VALVE_POP",
            scheduled_on="2026-08-06T08:00:00Z",
            relief_valve_lift_pressure_psi=175,
        )

        recorded = record_outcome(
            plant["id"], boiler["id"], inspection["id"], "FAILED"
        )
        assert recorded["outcome"] == "FAILED"

        state = get_boiler(plant["id"], boiler["id"])
        assert state["cert_status"] == "SUSPENDED"
        assert state["ops_status"] == "TRIPPED"
        assert state["water_status"] == "IN_SPEC", (
            "water dimension is independent of the cert/ops cascade"
        )

    def test_in_envelope_pop_test_changes_no_certification(
        self, api, plant_manager_headers
    ):
        """PRD §3.6: "For a `RELIEF_VALVE_POP` test, the measured lift
        pressure must sit inside a closed envelope: it must be at least the
        boiler's `relief_valve_setpoint_psi` ... and it must be no greater
        than the setpoint grown by `relief_valve_tolerance_pct` percent, with
        equality permitted". And "A pop test inside the envelope changes
        nothing in the certification dimension." Lift 168 within
        [165, 165 * 1.03 = 169.95] passes cleanly.

        Design: Difficulty/non_linear_state_machine/boiler_parallel_dimensions_cert_vs_ops
        """
        plant, ops = setup_plant_with_operators(name="Para2 Plant", count=1)
        op = ops[0]
        boiler = create_online_boiler(plant["id"], op["id"], tag="B-PR2")
        inspection = schedule_inspection(
            plant["id"], boiler["id"], inspection_kind="RELIEF_VALVE_POP",
            scheduled_on="2026-08-06T08:00:00Z",
            relief_valve_lift_pressure_psi=168,
        )

        recorded = record_outcome(
            plant["id"], boiler["id"], inspection["id"], "PASSED",
            relief_valve_lift_pressure_psi=168,
        )
        assert recorded["outcome"] == "PASSED"

        state = get_boiler(plant["id"], boiler["id"])
        assert state["cert_status"] == "VALID"
        assert state["ops_status"] == "ONLINE"


class TestReliefFailureCascadeAndRecovery:
    def test_failed_pop_test_cascade_depth2(self, api, plant_manager_headers):
        """PRD §3.6: "A pop test whose measured lift falls outside the
        envelope — whether the recording arrives as an explicit `FAILED` or
        the envelope check forces it — ends as a `FAILED` outcome with two
        cascades: the boiler's `cert_status` becomes `SUSPENDED`, and its
        `ops_status` is forced to `TRIPPED`."

        Design: Difficulty/transitive_cascade/relief_failure_cert_suspension_depth2
        """
        plant, ops = setup_plant_with_operators(name="Casc2 Plant", count=1)
        op = ops[0]
        boiler = create_online_boiler(plant["id"], op["id"], tag="B-C2")
        inspection = schedule_inspection(
            plant["id"], boiler["id"], inspection_kind="RELIEF_VALVE_POP",
            scheduled_on="2026-08-06T08:00:00Z",
            relief_valve_lift_pressure_psi=160,
        )

        recorded = record_outcome(
            plant["id"], boiler["id"], inspection["id"], "FAILED",
            relief_valve_lift_pressure_psi=160,
        )
        assert recorded["outcome"] == "FAILED"
        state = get_boiler(plant["id"], boiler["id"])
        assert state["cert_status"] == "SUSPENDED"
        assert state["ops_status"] == "TRIPPED"

    def test_post_incident_pass_restores_cert_and_reset_returns_standby(
        self, api, plant_manager_headers
    ):
        """PRD §3.6: "a boiler in `SUSPENDED` returns to `VALID` when a
        `POST_INCIDENT` inspection passes, recorded after the most recent
        suspension." PRD §3.4: "A successful reset recomputes `cert_status`
        from the latest inspection — which can carry the boiler from
        `SUSPENDED` back to `VALID` — and recomputes the plant `posture`."

        Design: Difficulty/transitive_cascade/relief_failure_cert_suspension_depth2
        """
        plant, ops = setup_plant_with_operators(name="Casc3 Plant", count=1)
        op = ops[0]
        boiler = create_online_boiler(plant["id"], op["id"], tag="B-C3")
        pop = schedule_inspection(
            plant["id"], boiler["id"], inspection_kind="RELIEF_VALVE_POP",
            scheduled_on="2026-08-06T08:00:00Z",
        )
        record_outcome(plant["id"], boiler["id"], pop["id"], "FAILED")
        assert get_boiler(plant["id"], boiler["id"])["cert_status"] == "SUSPENDED"

        followup = schedule_inspection(
            plant["id"], boiler["id"], inspection_kind="POST_INCIDENT",
            scheduled_on="2026-08-07T08:00:00Z",
        )
        record_outcome(plant["id"], boiler["id"], followup["id"], "PASSED")
        assert get_boiler(plant["id"], boiler["id"])["cert_status"] == "VALID"

        resp = api.reset_boiler(
            plant["id"], boiler["id"], make_operator_headers(op["id"])
        )
        reset = validate_success(resp, expected_status=200)
        assert reset["ops_status"] == "STANDBY"
        assert reset["cert_status"] == "VALID"


class TestCertificateExpiryBoundaries:
    def test_cert_expiring_inclusive_boundary_at_thirty_days(
        self, api, plant_manager_headers
    ):
        """PRD §3.6: "when the time remaining to expiry is thirty days or less
        — 2,592,000 seconds, with exactly thirty days remaining qualifying —
        the status becomes `EXPIRING`". A certificate expiring exactly
        30 days after the plant clock qualifies.

        Design: Difficulty/boundary_precision_check/cert_expiry_inclusive_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        plant = create_plant(name="Bnd Plant")
        boiler = create_boiler(plant["id"], tag="B-BND")
        record_passed_annual(
            plant["id"], boiler["id"],
            certificate_expires_on="2026-08-31T00:00:00Z",  # exactly 30 days
        )
        run_ops(plant["id"])
        assert get_boiler(plant["id"], boiler["id"])["cert_status"] == "EXPIRING"

    def test_cert_one_second_beyond_boundary_stays_valid(
        self, api, plant_manager_headers
    ):
        """PRD §3.6: "when the time remaining to expiry is thirty days or less
        — 2,592,000 seconds, with exactly thirty days remaining qualifying —
        the status becomes `EXPIRING`; otherwise it holds `VALID`." Thirty
        days plus one second is beyond the window.

        Design: Difficulty/boundary_precision_check/cert_expiry_inclusive_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        plant = create_plant(name="Bnd2 Plant")
        boiler = create_boiler(plant["id"], tag="B-BN2")
        record_passed_annual(
            plant["id"], boiler["id"],
            certificate_expires_on="2026-08-31T00:00:01Z",  # 30 days + 1 s
        )
        run_ops(plant["id"])
        assert get_boiler(plant["id"], boiler["id"])["cert_status"] == "VALID"

    def test_certificate_expiry_boundary_at_exactly_now_is_valid(
        self, api, plant_manager_headers
    ):
        """PRD §3.6: "otherwise an expiry strictly before the plant clock
        means `LAPSED`, while an expiry exactly equal to the clock does not".
        With expiry exactly equal to the clock, the remaining time is zero —
        inside the thirty-day window — so the status becomes `EXPIRING`.

        Design: Corner/calculations/certificate_expiry_boundary_at_exactly_now_is_valid
        """
        set_clock("2026-08-01T00:00:00Z")
        plant = create_plant(name="Eq Plant")
        boiler = create_boiler(plant["id"], tag="B-EQ")
        record_passed_annual(
            plant["id"], boiler["id"],
            certificate_expires_on="2026-08-01T00:00:00Z",  # == plant clock
        )
        run_ops(plant["id"])
        assert get_boiler(plant["id"], boiler["id"])["cert_status"] == "EXPIRING"


class TestCertificatePosting:
    def test_post_certificate_action(self, api, plant_manager_headers):
        """PRD §3.6: "Once an annual certificate passes, a `PlantManager`
        posts it, which stamps `posted_at` with the current plant clock; until
        that explicit posting, `posted_at` remains null."

        Design: Corner/endpoints/post_certificate_action
        """
        set_clock("2026-08-05T12:00:00Z")
        plant = create_plant(name="Post Plant")
        boiler = create_boiler(plant["id"], tag="B-POST")
        inspection = schedule_inspection(
            plant["id"], boiler["id"], inspection_kind="ANNUAL_EXTERNAL",
            scheduled_on="2026-08-05T08:00:00Z",
        )
        passed = record_outcome(
            plant["id"], boiler["id"], inspection["id"], "PASSED",
            certificate_number="C-P",
            certificate_expires_on="2027-08-05T00:00:00Z",
        )
        assert passed["posted_at"] is None

        resp = api.post_certificate(
            plant["id"], boiler["id"], inspection["id"], plant_manager_headers
        )
        posted = validate_success(resp, expected_status=200)
        assert posted["posted_at"] is not None
        assert posted["posted_at"].startswith("2026-08-05T12:00:00"), (
            f"posted_at must be the current plant clock, got {posted['posted_at']}"
        )


class TestInspectionSchedulingIntervals:
    def _plant_with_pending(self, api):
        plant = create_plant(name="Buf Plant")
        boiler = create_boiler(plant["id"], tag="B-BUF")
        schedule_inspection(
            plant["id"], boiler["id"], inspection_kind="ANNUAL_INTERNAL",
            scheduled_on="2026-08-10T08:00:00Z",  # occupies [06:00, 14:00]
        )
        return plant, boiler

    def test_overlapping_buffered_intervals_conflict(
        self, api, inspector_headers
    ):
        """PRD §2.11: "each inspection occupies four hours beginning at its
        `scheduled_on`, plus a two-hour buffer on each side, so its effective
        occupancy runs from two hours before `scheduled_on` to six hours after
        it. Two `PENDING` inspections on the same boiler conflict whenever
        their effective occupancy intervals intersect". [06:00, 14:00] and
        [12:00, 20:00] intersect.

        Design: Difficulty/resource_temporal_overlap/inspection_buffered_closed_interval_touching
        """
        plant, boiler = self._plant_with_pending(api)
        resp = api.create_inspection(
            plant["id"], boiler["id"],
            create_inspection_payload(
                inspection_kind="ANNUAL_EXTERNAL",
                scheduled_on="2026-08-10T14:00:00Z",
            ),
            inspector_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_SCHEDULE_CONFLICT,
                       expected_status=409)

    def test_merely_touching_buffered_endpoints_conflict(
        self, api, inspector_headers
    ):
        """PRD §2.11: "because the comparison is closed, intervals whose
        endpoints merely touch do conflict — the opposite of the dispatch
        rule." The first booking's buffered occupancy ends at 14:00; a second
        scheduled at 16:00 starts its buffer at exactly 14:00.

        Design: Difficulty/resource_temporal_overlap/inspection_buffered_closed_interval_touching
        """
        plant, boiler = self._plant_with_pending(api)
        resp = api.create_inspection(
            plant["id"], boiler["id"],
            create_inspection_payload(
                inspection_kind="ANNUAL_EXTERNAL",
                scheduled_on="2026-08-10T16:00:00Z",
            ),
            inspector_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_SCHEDULE_CONFLICT,
                       expected_status=409)

    def test_one_second_past_buffered_touch_is_allowed(
        self, api, inspector_headers
    ):
        """PRD §2.11: "Two `PENDING` inspections on the same boiler conflict
        whenever their effective occupancy intervals intersect". With the
        second buffer starting one second after the first ends, there is no
        intersection, so the booking is created.

        Design: Difficulty/resource_temporal_overlap/inspection_buffered_closed_interval_touching
        """
        plant, boiler = self._plant_with_pending(api)
        resp = api.create_inspection(
            plant["id"], boiler["id"],
            create_inspection_payload(
                inspection_kind="ANNUAL_EXTERNAL",
                scheduled_on="2026-08-10T16:00:01Z",
            ),
            inspector_headers,
        )
        inspection = validate_success(resp, expected_status=201)
        assert inspection["outcome"] == "PENDING"

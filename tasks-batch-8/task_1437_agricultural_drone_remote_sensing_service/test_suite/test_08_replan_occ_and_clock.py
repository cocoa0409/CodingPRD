"""Mission replanning cycles, optimistic concurrency, and clock-driven sweeps
(PRD sections 2.5, 2.8, and 3.3)."""
from test_helpers import (
    ADMIN,
    FC,
    ApiErrorId,
    api_client,
    abort_weather,
    authorize,
    create_authorization,
    create_grower,
    create_mission_weather_aborted,
    create_plan,
    get_grower,
    get_mission,
    launch_at,
    set_clock,
    setup_ops,
    validate_error,
    validate_success,
)


class TestReplanCycle:

    def _aborted_mission(self, ctx):
        return create_mission_weather_aborted(
            ctx["field"]["id"], ctx["pilot"]["id"],
            start="2026-06-02T08:00:00Z", end="2026-06-02T10:00:00Z",
            launch_time="2026-06-02T08:30:00Z", acres_planned=80,
            wind_kt=25)

    def test_replan_spawns_fresh_planned_revision(self):
        """PRD section 3.3: "Replanning a `WEATHER_ABORTED` or `CANCELLED`
        mission spawns a brand-new mission — a fresh resource, not a mutation
        — carrying over the original's `field_id`, `mission_type`, `pilot_id`,
        `authorization_id`, `acres_planned`, and `chemical_product_label`,
        born `PLANNED` with the newly supplied `scheduled_start` and
        `scheduled_end`."
        PRD section 3.3: "On success the original mission's `version`
        increments, marking it superseded."

        Design: Difficulty/non_linear_state_machine/flight_mission_replan_cycle
        """
        ctx = setup_ops()
        m1 = self._aborted_mission(ctx)
        assert m1["status"] == "WEATHER_ABORTED"
        observed = get_mission(m1["id"])
        resp = api_client.replan_mission(
            m1["id"],
            {"scheduled_start": "2026-06-04T08:00:00Z",
             "scheduled_end": "2026-06-04T10:00:00Z",
             "expected_mission_version": observed["version"]},
            FC)
        m2 = validate_success(resp, expected_status=201)
        assert m2["id"] != m1["id"], "replan must mint a fresh mission"
        assert m2["status"] == "PLANNED"
        assert m2["field_id"] == m1["field_id"]
        assert m2["mission_type"] == m1["mission_type"]
        assert m2["pilot_id"] == m1["pilot_id"]
        assert m2["acres_planned"] == m1["acres_planned"]
        original_after = get_mission(m1["id"])
        assert original_after["status"] == "WEATHER_ABORTED", \
            "the original mission stays in its terminal state"
        assert original_after["version"] == observed["version"] + 1, \
            "the original's version increments to mark it superseded"

    def test_replanned_mission_can_complete_a_second_cycle(self):
        """PRD section 3.3: "Replanning a `WEATHER_ABORTED` or `CANCELLED`
        mission spawns a brand-new mission — a fresh resource, not a mutation
        — carrying over the original's `field_id`, `mission_type`, `pilot_id`,
        `authorization_id`, `acres_planned`, and `chemical_product_label`,
        born `PLANNED` with the newly supplied `scheduled_start` and
        `scheduled_end`."
        PRD section 3.4: "An aborted mission lands in `WEATHER_ABORTED` with
        the observed wind recorded, `acres_flown` remaining zero, and the
        version incremented."

        Design: Difficulty/non_linear_state_machine/flight_mission_replan_cycle
        """
        ctx = setup_ops()
        m1 = self._aborted_mission(ctx)
        observed = get_mission(m1["id"])
        resp = api_client.replan_mission(
            m1["id"],
            {"scheduled_start": "2026-06-04T08:00:00Z",
             "scheduled_end": "2026-06-04T10:00:00Z",
             "expected_mission_version": observed["version"]},
            FC)
        m2 = validate_success(resp, expected_status=201)
        # The fresh revision is itself flyable through a second abort cycle.
        authorize(m2["id"])
        launched = launch_at(m2["id"], ctx["pilot"]["id"],
                             "2026-06-04T08:30:00Z")
        assert launched["status"] == "IN_FLIGHT"
        aborted = abort_weather(m2["id"], ctx["pilot"]["id"], wind_kt=30)
        assert aborted["status"] == "WEATHER_ABORTED"
        assert aborted["acres_flown"] == 0
        assert aborted["wind_kt_max_observed"] == 30
        assert get_mission(m1["id"])["status"] == "WEATHER_ABORTED"


class TestOptimisticConcurrency:

    def test_error_stale_mission_version_on_replan(self):
        """PRD section 2.8: "Replanning a disrupted mission requires the
        request to carry `expected_mission_version`, holding the `version` of
        the original `FlightMission` as the client last observed it. If that
        value does not match the mission's current `version` — because another
        writer has already replanned or otherwise advanced the mission since
        the client read it — the request is rejected with
        `ERR_STALE_MISSION_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_mission_version_on_replan
        """
        ctx = setup_ops()
        m1 = create_mission_weather_aborted(
            ctx["field"]["id"], ctx["pilot"]["id"],
            start="2026-06-02T08:00:00Z", end="2026-06-02T10:00:00Z",
            launch_time="2026-06-02T08:30:00Z", acres_planned=10, wind_kt=25)
        observed_v = get_mission(m1["id"])["version"]
        # First replan succeeds and advances the original's version.
        resp = api_client.replan_mission(
            m1["id"],
            {"scheduled_start": "2026-06-04T08:00:00Z",
             "scheduled_end": "2026-06-04T10:00:00Z",
             "expected_mission_version": observed_v},
            FC)
        validate_success(resp, expected_status=201)
        # Second replan against the stale observed version is rejected.
        resp2 = api_client.replan_mission(
            m1["id"],
            {"scheduled_start": "2026-06-05T08:00:00Z",
             "scheduled_end": "2026-06-05T10:00:00Z",
             "expected_mission_version": observed_v},
            FC)
        validate_error(resp2, ApiErrorId.ERR_STALE_MISSION_VERSION)

    def test_occ_stale_grower_version_on_patch(self):
        """PRD section 2.8: "Updating a grower's subscription plan or
        liability coverage requires the request to carry
        `expected_grower_version`, matching the grower's current `version`. A
        suspension, reinstatement, invoice run, or claim payout all advance
        the grower's version, so a client patching against a stale read —
        whose assumptions about year-to-date acreage or account standing no
        longer hold — is rejected with `ERR_STALE_GROWER_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_grower_version_on_patch
        """
        plan = create_plan()
        grower = create_grower(plan["id"], legal_name="OCC2Farms")
        v0 = grower["version"]
        # First patch at the current version succeeds and bumps the version.
        resp = api_client.patch_grower(
            grower["id"],
            {"liability_coverage_cents": 60_000_000,
             "expected_grower_version": v0},
            ADMIN)
        patched = validate_success(resp, expected_status=200)
        assert patched["version"] == v0 + 1
        assert patched["liability_coverage_cents"] == 60_000_000
        # Second patch against the stale version is rejected and changes
        # nothing.
        resp2 = api_client.patch_grower(
            grower["id"],
            {"liability_coverage_cents": 70_000_000,
             "expected_grower_version": v0},
            ADMIN)
        validate_error(resp2, ApiErrorId.ERR_STALE_GROWER_VERSION)
        after = get_grower(grower["id"])
        assert after["version"] == v0 + 1
        assert after["liability_coverage_cents"] == 60_000_000


class TestClockSweep:

    def test_clock_sweep_expires_authorization(self):
        """PRD section 2.5: "Advancing the clock triggers two automatic
        sweeps. First, any `AirspaceAuthorization` still `ACTIVE` whose
        `effective_until` has been reached — that is, the current time is at
        or past the authorization's end instant — transitions to `EXPIRED`".

        Design: Corner/cross_cutting_layers/clock_sweep_expires_authorization
        """
        ctx = setup_ops(field_overrides={"airspace_class": "B"})
        auth = create_authorization(
            ctx["field"]["id"],
            effective_from="2026-06-02T00:00:00Z",
            effective_until="2026-06-03T00:00:00Z")
        assert auth["status"] == "ACTIVE"
        set_clock("2026-06-03T00:00:01Z")
        after = validate_success(
            api_client.get_authorization(auth["id"], ADMIN))
        assert after["status"] == "EXPIRED", \
            f"authorization must expire once its end instant is reached, " \
            f"got {after['status']}"

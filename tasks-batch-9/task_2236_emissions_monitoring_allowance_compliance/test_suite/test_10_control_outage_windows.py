"""Control outage windows: the dispatch state activation demands, the per-unit
per-device interval they occupy, and the station-wide ceiling on active ones."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_control_outage_window,
    make_facility_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

CLOCK = "2026-08-01T00:00:00Z"
# Server-stamped timestamps carry three fractional digits (PRD 2.5).
CLOCK_STAMP = "2026-08-01T00:00:00.000Z"
OPERATOR_ORG = "op_alpha"
CANCELLATION_REASON = "vendor deferred the absorber liner replacement"
OPERATOR = make_facility_operator_headers(OPERATOR_ORG)


def _unit(unit_id):
    return validate_success(api_client.get_unit(unit_id, fx.REVIEWER))


def _outage(outage_id):
    return validate_success(api_client.get_control_outage(outage_id, fx.REVIEWER))


def _transition(outage_id, action, **extra):
    payload = {"action": action}
    payload.update(extra)
    return api_client.transition_control_outage(outage_id, payload, OPERATOR)


def _dispatch(unit_id, dispatch_state):
    return api_client.set_unit_dispatch(
        unit_id, {"dispatch_state": dispatch_state}, OPERATOR
    )


class TestActivationDemandsAnOffLineUnit:
    """The window depends on the unit, and activation writes back into it."""

    def _online_unit_with_planned_outage(self):
        station = fx.setup_facility_and_unit(
            clock=CLOCK,
            online=True,
            facility_overrides={"max_concurrent_control_outages": 2},
        )
        station["outage"] = fx.plan_control_outage(
            station["unit"]["id"],
            OPERATOR_ORG,
            start_utc="2026-08-02T00:00:00Z",
            end_utc="2026-08-05T00:00:00Z",
            outage_type="PLANNED_MAINTENANCE",
            control_device="FGD",
        )
        return station

    def test_activating_against_an_online_unit_is_refused_as_a_state_transition(self):
        """The refusal is the transition error, not a dispatch error.

        PRD: "A window moves from `PLANNED` to `ACTIVE` only while the unit's
        `dispatch_state` is `OFFLINE` or `RESERVE_SHUTDOWN` — attempting it on a
        unit that is online is rejected as `ERR_INVALID_STATE_TRANSITION`, not as a
        dispatch error"

        Design: Difficulty/cross_entity_state_dependency/cross_entity_outage_activation_requires_unit_off_line
        """
        station = self._online_unit_with_planned_outage()
        outage_id = station["outage"]["id"]
        unit_id = station["unit"]["id"]

        assert_control_outage_window(station["outage"])
        assert station["outage"]["status"] == "PLANNED"
        assert _unit(unit_id)["control_status"] == "AVAILABLE", (
            "a planned window leaves the control status untouched"
        )

        refused = _transition(outage_id, "ACTIVATE")
        validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        assert _outage(outage_id)["status"] == "PLANNED"
        assert _unit(unit_id)["control_status"] == "AVAILABLE"

        validate_success(_dispatch(unit_id, "OFFLINE"))
        activated = validate_success(_transition(outage_id, "ACTIVATE"))
        assert activated["status"] == "ACTIVE"
        assert activated["activated_utc"] == CLOCK_STAMP
        assert _unit(unit_id)["control_status"] == "OUT_OF_SERVICE", (
            "activation writes back into the unit"
        )

    def test_an_active_planned_maintenance_window_pins_the_unit_off_line(self):
        """Only closing the window lets the unit go back online.

        PRD: "Two conditions block a move to `ONLINE`, and both surface as
        `ERR_INVALID_STATE_TRANSITION`: `dispatch_restricted` must be false, and no
        control outage window of the unit may be `ACTIVE` with an `outage_type` of
        `PLANNED_MAINTENANCE`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_outage_activation_requires_unit_off_line
        """
        station = self._online_unit_with_planned_outage()
        outage_id = station["outage"]["id"]
        unit_id = station["unit"]["id"]

        validate_success(_dispatch(unit_id, "OFFLINE"))
        validate_success(_transition(outage_id, "ACTIVATE"))

        assert _unit(unit_id)["dispatch_restricted"] is False, (
            "no allowance shortfall exists, so the block is the active window alone"
        )
        blocked = _dispatch(unit_id, "ONLINE")
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        assert _unit(unit_id)["dispatch_state"] == "OFFLINE"

        closed = validate_success(_transition(outage_id, "CLOSE"))
        assert closed["status"] == "CLOSED"
        assert closed["closed_utc"] == CLOCK_STAMP
        assert _unit(unit_id)["control_status"] == "AVAILABLE", (
            "no other window of the unit is still ACTIVE"
        )

        released = validate_success(_dispatch(unit_id, "ONLINE"))
        assert released["dispatch_state"] == "ONLINE"


class TestIntervalIsScopedPerUnit:
    """The interval resource is keyed by unit and device, not by facility."""

    def _two_units(self):
        station = fx.setup_facility_and_unit(
            clock=CLOCK, facility_overrides={"max_concurrent_control_outages": 4}
        )
        station["unit2"] = fx.create_unit(
            station["facility"]["id"], unit_identifier="U2", control_device="FGD"
        )
        return station

    def _plan(self, unit_id, start, end, outage_type="PLANNED_MAINTENANCE"):
        return api_client.plan_control_outage(
            unit_id,
            {
                "start_utc": start,
                "end_utc": end,
                "outage_type": outage_type,
                "control_device": "FGD",
            },
            OPERATOR,
        )

    def test_the_same_interval_is_free_on_a_sibling_unit_and_abutting_is_accepted(self):
        """[08-13, 08-16) collides on U1 while [08-14, 08-16) does not.

        PRD: "Intervals are compared half-open, so an abutting window whose start
        equals an incumbent's end is accepted, while one second earlier is rejected
        with `ERR_CONTROL_OUTAGE_OVERLAP`; overlap is scoped per device, so an FGD
        outage and an SCR outage on the same unit may overlap freely, and
        `CANCELLED` or `CLOSED` windows never block."

        Design: Difficulty/resource_temporal_overlap/overlap_control_outages_are_scoped_per_unit_and_cancellation_releases_the_interval
        """
        station = self._two_units()
        u1 = station["unit"]["id"]
        u2 = station["unit2"]["id"]

        first = validate_success(
            self._plan(u1, "2026-08-10T00:00:00Z", "2026-08-14T00:00:00Z"), 201
        )
        assert first["status"] == "PLANNED"

        sibling = validate_success(
            self._plan(u2, "2026-08-10T00:00:00Z", "2026-08-14T00:00:00Z"), 201
        )
        assert sibling["unit_id"] == u2, (
            "the identical interval on a sibling unit does not collide"
        )

        colliding = self._plan(
            u1, "2026-08-13T00:00:00Z", "2026-08-16T00:00:00Z", outage_type="FORCED"
        )
        validate_error(colliding, ApiErrorId.ERR_CONTROL_OUTAGE_OVERLAP.value)

        abutting = validate_success(
            self._plan(
                u1, "2026-08-14T00:00:00Z", "2026-08-16T00:00:00Z", outage_type="FORCED"
            ),
            201,
        )
        assert abutting["start_utc"] == "2026-08-14T00:00:00Z"
        assert abutting["outage_type"] == "FORCED"

        assert _unit(u1)["control_status"] == "AVAILABLE", (
            "planning does not take the device out of service"
        )

    def test_cancelling_needs_a_reason_and_then_releases_the_interval(self):
        """A CANCELLED row stops occupying [08-10, 08-14).

        PRD: "A `PLANNED` window may instead be cancelled with a `reason`, which is
        recorded as `cancellation_reason`, moves the window to `CANCELLED`,
        increments its `version`, and releases the interval for a later window; a
        cancellation submitted without a reason is rejected with
        `ERR_REASON_REQUIRED`."

        Design: Difficulty/resource_temporal_overlap/overlap_control_outages_are_scoped_per_unit_and_cancellation_releases_the_interval
        """
        station = self._two_units()
        u1 = station["unit"]["id"]

        first = validate_success(
            self._plan(u1, "2026-08-10T00:00:00Z", "2026-08-14T00:00:00Z"), 201
        )
        validate_success(
            self._plan(
                u1, "2026-08-14T00:00:00Z", "2026-08-16T00:00:00Z", outage_type="FORCED"
            ),
            201,
        )

        reasonless = _transition(first["id"], "CANCEL")
        validate_error(reasonless, ApiErrorId.ERR_REASON_REQUIRED.value)
        assert _outage(first["id"])["status"] == "PLANNED"

        cancelled = validate_success(
            _transition(first["id"], "CANCEL", reason=CANCELLATION_REASON)
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == CANCELLATION_REASON

        reused = validate_success(
            self._plan(u1, "2026-08-11T00:00:00Z", "2026-08-13T00:00:00Z"), 201
        )
        assert reused["status"] == "PLANNED", (
            "the cancelled row no longer occupies the interval it held"
        )

        rows, meta = validate_paginated(
            api_client.list_control_outages(fx.REVIEWER, {"unit_id": u1})
        )
        assert meta["total_count"] == 3
        statuses = sorted(row["status"] for row in rows)
        assert statuses == ["CANCELLED", "PLANNED", "PLANNED"]
        assert _unit(u1)["control_status"] == "AVAILABLE"


class TestActiveCeilingIsAggregate:
    """The ceiling counts active windows across the whole facility."""

    def _three_planned_units(self):
        station = fx.setup_facility_and_unit(
            clock=CLOCK, facility_overrides={"max_concurrent_control_outages": 2}
        )
        station["units"] = [station["unit"]]
        for identifier in ("U2", "U3"):
            station["units"].append(
                fx.create_unit(
                    station["facility"]["id"],
                    unit_identifier=identifier,
                    control_device="FGD",
                )
            )
        station["outages"] = [
            fx.plan_control_outage(
                unit["id"],
                OPERATOR_ORG,
                start_utc="2026-08-10T00:00:00Z",
                end_utc="2026-08-14T00:00:00Z",
                outage_type="PLANNED_MAINTENANCE",
                control_device="FGD",
            )
            for unit in station["units"]
        ]
        return station

    def test_the_third_activation_is_refused_by_the_station_ceiling(self):
        """Three identical intervals plan cleanly; only the third activation fails.

        PRD: "and only if the count of `ACTIVE` windows across **all** units of the
        facility, counted after this one, would not exceed
        `max_concurrent_control_outages`; otherwise `ERR_CONCURRENT_OUTAGE_LIMIT`."

        Design: Difficulty/resource_temporal_overlap/overlap_facility_wide_active_outage_ceiling_is_aggregate_not_pairwise
        """
        station = self._three_planned_units()
        outages = station["outages"]
        units = station["units"]

        for outage in outages:
            assert outage["status"] == "PLANNED", (
                "the pairwise interval key includes the unit, so identical windows "
                "on three units never collide"
            )

        first = validate_success(_transition(outages[0]["id"], "ACTIVATE"))
        assert first["status"] == "ACTIVE"
        second = validate_success(_transition(outages[1]["id"], "ACTIVATE"))
        assert second["status"] == "ACTIVE"
        assert _unit(units[0]["id"])["control_status"] == "OUT_OF_SERVICE"
        assert _unit(units[1]["id"])["control_status"] == "OUT_OF_SERVICE"

        refused = _transition(outages[2]["id"], "ACTIVATE")
        validate_error(refused, ApiErrorId.ERR_CONCURRENT_OUTAGE_LIMIT.value)
        assert _outage(outages[2]["id"])["status"] == "PLANNED"
        assert _unit(units[2]["id"])["control_status"] == "AVAILABLE"

    def test_closing_one_active_window_frees_a_slot_for_the_third(self):
        """The count is of ACTIVE rows only, so a CLOSED row releases its slot.

        PRD: "Closing an `ACTIVE` window stamps `closed_utc`, increments its
        `version`, and returns the unit's `control_status` to `AVAILABLE` **only**
        when no other window of the same unit is still `ACTIVE`, leaving it
        `OUT_OF_SERVICE` otherwise; the unit's `version` increments either way."

        Design: Difficulty/resource_temporal_overlap/overlap_facility_wide_active_outage_ceiling_is_aggregate_not_pairwise
        """
        station = self._three_planned_units()
        outages = station["outages"]
        units = station["units"]

        validate_success(_transition(outages[0]["id"], "ACTIVATE"))
        validate_success(_transition(outages[1]["id"], "ACTIVATE"))
        validate_error(
            _transition(outages[2]["id"], "ACTIVATE"),
            ApiErrorId.ERR_CONCURRENT_OUTAGE_LIMIT.value,
        )

        closed = validate_success(_transition(outages[0]["id"], "CLOSE"))
        assert closed["status"] == "CLOSED"
        assert closed["closed_utc"] == CLOCK_STAMP
        assert _unit(units[0]["id"])["control_status"] == "AVAILABLE"

        third = validate_success(_transition(outages[2]["id"], "ACTIVATE"))
        assert third["status"] == "ACTIVE"
        assert _unit(units[2]["id"])["control_status"] == "OUT_OF_SERVICE"

        rows, meta = validate_paginated(
            api_client.list_control_outages(fx.REVIEWER, {"status": "ACTIVE"})
        )
        assert meta["total_count"] == 2, (
            f"the ceiling of 2 is exactly consumed again, got {meta['total_count']}"
        )
        assert sorted(row["unit_id"] for row in rows) == sorted(
            [units[1]["id"], units[2]["id"]]
        )

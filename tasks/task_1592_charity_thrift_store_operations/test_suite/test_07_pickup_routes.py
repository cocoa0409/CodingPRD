"""Pickup routes and stops: publish loop, window buffers, sequencing, cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    MGR,
    add_stop,
    complete_stop,
    create_donor,
    create_driver,
    create_route,
    create_route_with_stops,
    deactivate_donor,
    depart_stop,
    get_success_data,
    make_driver_headers,
    no_show_stop,
    publish_route,
    start_route,
    unpublish_route,
    validate_error,
    validate_success,
)


def _get_route(api, route_id):
    return validate_success(api.get_route(route_id, MGR))


def _get_stop(api, stop_id):
    return validate_success(api.get_stop(stop_id, MGR))


class TestPublishUnpublishLoop:
    def test_route_unpublish_republish_loop(self, api):
        """PRD 3.7: "Publishing requires at least one stop still `SCHEDULED` —
        publishing a route with none fails with `ERR_ROUTE_EMPTY` — and moves the
        route `DRAFT` → `PUBLISHED`. A published route can return to `DRAFT` only
        while every stop is still `SCHEDULED`"
        PRD 2.4: "The `version` is an integer starting at 1 that increments by one on
        every mutation of the resource"

        Design: Difficulty/non_linear_state_machine/route_unpublish_republish_loop
        """
        driver = create_driver()
        d1 = create_donor("D One")
        d2 = create_donor("D Two")
        route = create_route(driver["id"], "2026-08-10", 500)

        # Empty-route publish is rejected and bumps nothing.
        resp = api.publish_route(route["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_ROUTE_EMPTY)

        add_stop(route["id"], d1["id"], "2026-08-10T09:00:00Z",
                 "2026-08-10T10:00:00Z", 100)
        publish_route(route["id"])
        unpublish_route(route["id"])
        add_stop(route["id"], d2["id"], "2026-08-10T11:00:00Z",
                 "2026-08-10T12:00:00Z", 100)
        publish_route(route["id"])

        route_after = _get_route(api, route["id"])
        assert route_after["status"] == "PUBLISHED"
        assert route_after["stop_count"] == 2
        # create + stop + publish + unpublish + stop + publish = 6 mutations.
        assert route_after["version"] == 6

    def test_unpublish_after_departure_rejected(self, api):
        """PRD 3.7: "A published route can return to `DRAFT` only while every stop is
        still `SCHEDULED`; once any stop has departed, completed, or no-showed,
        unpublishing fails with `ERR_ROUTE_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/route_unpublish_republish_loop
        """
        driver, route, stops = create_route_with_stops([{}])
        publish_route(route["id"])
        start_route(route["id"])
        depart_stop(stops[0]["id"], driver["id"])

        resp = api.unpublish_route(route["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_ROUTE_INVALID_STATE)
        route_after = _get_route(api, route["id"])
        assert route_after["status"] == "IN_PROGRESS"


class TestStopWindowBuffer:
    def test_stop_windows_buffered_half_open(self, api):
        """PRD 3.7: "Spacing: against every other stop on the route still in
        `SCHEDULED` or `EN_ROUTE`, the new window must keep a 30-minute travel buffer
        on both sides — the new window must start at least thirty minutes after the
        existing window ends, or the existing window must start at least thirty
        minutes after the new window ends, with exactly thirty minutes of separation
        allowed; a tighter fit fails with `ERR_STOP_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stop_windows_buffered_half_open
        """
        driver = create_driver()
        donors = [create_donor(f"D {n}") for n in "ABCD"]
        route = create_route(driver["id"], "2026-08-10", 1000)
        add_stop(route["id"], donors[0]["id"], "2026-08-10T09:00:00Z",
                 "2026-08-10T10:00:00Z", 100)

        # 29 minutes after the existing window: too tight.
        resp = api.add_stop(route["id"], {
            "donor_id": donors[1]["id"],
            "window_start": "2026-08-10T10:29:00Z",
            "window_end": "2026-08-10T11:00:00Z",
            "estimated_volume_cuft": 100,
        }, MGR)
        validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_CONFLICT)

        # Exactly 30 minutes after: legal (the buffer is inclusive).
        add_stop(route["id"], donors[1]["id"], "2026-08-10T10:30:00Z",
                 "2026-08-10T11:00:00Z", 100)

        # Exactly 30 minutes before the first window: legal on the early side too.
        add_stop(route["id"], donors[2]["id"], "2026-08-10T07:30:00Z",
                 "2026-08-10T08:30:00Z", 100)

        # 07:31-08:31 leaves only 29 minutes before the 09:00 stop.
        resp2 = api.add_stop(route["id"], {
            "donor_id": donors[3]["id"],
            "window_start": "2026-08-10T07:31:00Z",
            "window_end": "2026-08-10T08:31:00Z",
            "estimated_volume_cuft": 100,
        }, MGR)
        validate_error(resp2, ApiErrorId.ERR_STOP_WINDOW_CONFLICT)

        route_after = _get_route(api, route["id"])
        assert route_after["stop_count"] == 3
        assert route_after["total_volume_cuft"] == pytest.approx(300)

    def test_stop_window_overlap_rejected(self, api):
        """PRD 3.7: "the new window must start at least thirty minutes after the
        existing window ends, or the existing window must start at least thirty
        minutes after the new window ends, with exactly thirty minutes of separation
        allowed; a tighter fit fails with `ERR_STOP_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stop_windows_buffered_half_open
        """
        driver = create_driver()
        d1 = create_donor("D One")
        d2 = create_donor("D Two")
        d3 = create_donor("D Three")
        route = create_route(driver["id"], "2026-08-10", 1000)
        add_stop(route["id"], d1["id"], "2026-08-10T09:00:00Z",
                 "2026-08-10T10:00:00Z", 100)

        # Partial overlap with the existing window.
        resp = api.add_stop(route["id"], {
            "donor_id": d2["id"],
            "window_start": "2026-08-10T09:30:00Z",
            "window_end": "2026-08-10T10:30:00Z",
            "estimated_volume_cuft": 100,
        }, MGR)
        validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_CONFLICT)

        # Identical window.
        resp2 = api.add_stop(route["id"], {
            "donor_id": d3["id"],
            "window_start": "2026-08-10T09:00:00Z",
            "window_end": "2026-08-10T10:00:00Z",
            "estimated_volume_cuft": 100,
        }, MGR)
        validate_error(resp2, ApiErrorId.ERR_STOP_WINDOW_CONFLICT)

        route_after = _get_route(api, route["id"])
        assert route_after["stop_count"] == 1


class TestStopSequencing:
    def test_stop_depart_requires_earlier_stops_terminal(self, api):
        """PRD 3.7: "Departing for a stop moves it `SCHEDULED` → `EN_ROUTE` and
        requires the route to be `IN_PROGRESS` (`ERR_ROUTE_INVALID_STATE`), the
        caller to be the route's own driver — the acting `X-User-ID` must equal the
        route's `driver_worker_id`, else `ERR_FORBIDDEN_OWNERSHIP` — and the day's
        sequencing to be respected: every other stop on the route with an earlier
        `window_start` must already be terminal, or the departure fails with
        `ERR_STOP_OUT_OF_SEQUENCE`."
        PRD 3.7: "the system auto-creates a donation batch for the stop's donor with
        `source` `PICKUP_STOP`, `pickup_stop_id` set to the stop, `receipt_requested`
        true, and status `OPEN`, and records the new batch's identity on the stop's
        `completed_batch_id`."

        Design: Difficulty/cross_entity_state_dependency/stop_depart_requires_earlier_stops_terminal
        """
        driver = create_driver()
        d1 = create_donor("D Early")
        d2 = create_donor("D Late")
        route = create_route(driver["id"], "2026-08-10", 500)
        s1 = add_stop(route["id"], d1["id"], "2026-08-10T09:00:00Z",
                      "2026-08-10T10:00:00Z", 100)
        s2 = add_stop(route["id"], d2["id"], "2026-08-10T11:00:00Z",
                      "2026-08-10T12:00:00Z", 100)
        publish_route(route["id"])
        start_route(route["id"])

        # The later stop cannot depart while the earlier one is non-terminal.
        resp = api.depart_stop(s2["id"], make_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_STOP_OUT_OF_SEQUENCE)

        depart_stop(s1["id"], driver["id"])
        completed = complete_stop(s1["id"], driver["id"])
        assert completed["status"] == "COMPLETED"
        batch_id = completed.get("completed_batch_id")
        assert batch_id, "completion records the auto-created batch"

        batch = validate_success(api.get_batch(batch_id, MGR))
        assert batch["source"] == "PICKUP_STOP"
        assert batch["donor_id"] == d1["id"]
        assert batch["receipt_requested"] is True
        assert batch["status"] == "OPEN"

        departed = depart_stop(s2["id"], driver["id"])
        assert departed["status"] == "EN_ROUTE", "earlier stop terminal unlocks it"

    def test_no_show_of_earlier_stop_unlocks_later(self, api):
        """PRD 3.7: "Completing the route requires every stop terminal — `COMPLETED`,
        `NO_SHOW`, or `CANCELLED`" and "every other stop on the route with an earlier
        `window_start` must already be terminal, or the departure fails with
        `ERR_STOP_OUT_OF_SEQUENCE`."

        Design: Difficulty/cross_entity_state_dependency/stop_depart_requires_earlier_stops_terminal
        """
        driver = create_driver()
        d1 = create_donor("D Early")
        d2 = create_donor("D Late")
        route = create_route(driver["id"], "2026-08-10", 500)
        s1 = add_stop(route["id"], d1["id"], "2026-08-10T09:00:00Z",
                      "2026-08-10T10:00:00Z", 100)
        s2 = add_stop(route["id"], d2["id"], "2026-08-10T11:00:00Z",
                      "2026-08-10T12:00:00Z", 100)
        publish_route(route["id"])
        start_route(route["id"])

        resp = api.depart_stop(s2["id"], make_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_STOP_OUT_OF_SEQUENCE)

        depart_stop(s1["id"], driver["id"])
        no_show_stop(s1["id"], driver["id"])
        departed = depart_stop(s2["id"], driver["id"])
        assert departed["status"] == "EN_ROUTE", "NO_SHOW is terminal for sequencing"


class TestStopGateOrdering:
    def test_stop_temporal_beats_referential(self, api):
        """PRD 2.9: "And a conflicting stop window surfaces as
        `ERR_STOP_WINDOW_CONFLICT` even when the referenced donor is also inactive,
        because the temporal tier outranks referential eligibility."

        Design: Difficulty/priority_pair_validation_conflict/stop_temporal_beats_referential
        """
        driver = create_driver()
        active = create_donor("D Active")
        inactive = create_donor("D Inactive")
        deactivate_donor(inactive["id"])
        route = create_route(driver["id"], "2026-08-10", 500)
        add_stop(route["id"], active["id"], "2026-08-10T09:00:00Z",
                 "2026-08-10T10:00:00Z", 100)

        # The new stop violates the 30-minute buffer AND references an INACTIVE
        # donor; the temporal error must win.
        resp = api.add_stop(route["id"], {
            "donor_id": inactive["id"],
            "window_start": "2026-08-10T10:15:00Z",
            "window_end": "2026-08-10T11:00:00Z",
            "estimated_volume_cuft": 50,
        }, MGR)
        validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_CONFLICT)
        route_after = _get_route(api, route["id"])
        assert route_after["stop_count"] == 1, "no stop persisted"

    def test_inactive_donor_stop_with_clean_window(self, api):
        """PRD 3.7: "Each stop names a `donor_id` — the donor must be ACTIVE, else
        `ERR_DONOR_INACTIVE`"

        Design: Difficulty/priority_pair_validation_conflict/stop_temporal_beats_referential
        """
        driver = create_driver()
        active = create_donor("D Active")
        inactive = create_donor("D Inactive")
        deactivate_donor(inactive["id"])
        route = create_route(driver["id"], "2026-08-10", 500)
        add_stop(route["id"], active["id"], "2026-08-10T09:00:00Z",
                 "2026-08-10T10:00:00Z", 100)

        # The window is exactly 30 minutes clear, so only the donor gate can fire.
        resp = api.add_stop(route["id"], {
            "donor_id": inactive["id"],
            "window_start": "2026-08-10T10:30:00Z",
            "window_end": "2026-08-10T11:30:00Z",
            "estimated_volume_cuft": 50,
        }, MGR)
        validate_error(resp, ApiErrorId.ERR_DONOR_INACTIVE)
        route_after = _get_route(api, route["id"])
        assert route_after["stop_count"] == 1


class TestRouteStateGates:
    def test_complete_route_with_open_stop_rejected(self, api):
        """PRD 3.7: "Completing the route requires every stop terminal — `COMPLETED`,
        `NO_SHOW`, or `CANCELLED` — and moves `IN_PROGRESS` → `COMPLETED`, failing
        with `ERR_ROUTE_INVALID_STATE` while any stop is still live."

        Design: Corner/state_machines/complete_route_with_open_stop_rejected
        """
        driver, route, _stops = create_route_with_stops([{}])
        publish_route(route["id"])
        start_route(route["id"])

        resp = api.complete_route(route["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_ROUTE_INVALID_STATE)
        route_after = _get_route(api, route["id"])
        assert route_after["status"] == "IN_PROGRESS"

    def test_stop_window_inverted_rejected(self, api):
        """PRD 2.9: "Request schema — ... time windows ordered (`window_end` strictly
        after `window_start`, `ends_at` strictly after `starts_at`) ... — violations
        yield `ERR_INVALID_REQUEST`."

        Design: Corner/validations/stop_window_inverted_rejected
        """
        driver = create_driver()
        donor = create_donor("D W")
        route = create_route(driver["id"], "2026-08-10", 500)
        resp = api.add_stop(route["id"], {
            "donor_id": donor["id"],
            "window_start": "2026-08-10T10:00:00Z",
            "window_end": "2026-08-10T09:00:00Z",
            "estimated_volume_cuft": 50,
        }, MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        route_after = _get_route(api, route["id"])
        assert route_after["stop_count"] == 0

    def test_depart_completed_stop_returns_invalid_state(self, api):
        """PRD 3.7: "At the curb, the driver either completes the stop or marks it a
        no-show; both demand the same driver ownership, and both demand the stop be
        `EN_ROUTE` — acting on a stop in any other state fails with
        `ERR_STOP_INVALID_STATE`."

        Design: Corner/errors/depart_completed_stop_returns_invalid_state
        """
        driver, route, stops = create_route_with_stops(
            [{"estimated_volume_cuft": 50}]
        )
        publish_route(route["id"])
        start_route(route["id"])
        depart_stop(stops[0]["id"], driver["id"])
        complete_stop(stops[0]["id"], driver["id"])

        resp = api.depart_stop(stops[0]["id"], make_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_STOP_INVALID_STATE)
        stop_after = _get_stop(api, stops[0]["id"])
        assert stop_after["status"] == "COMPLETED"


class TestRouteCapacityAndDriver:
    def test_route_capacity_boundary(self, api):
        """PRD 3.7: "Capacity: the route's `total_volume_cuft` plus the new stop's
        estimate must not exceed the truck's capacity, with a stop that fills the
        truck exactly allowed; overflow fails with `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Corner/validations/route_capacity_boundary
        """
        driver = create_driver()
        d1, d2, d3 = create_donor("D 60"), create_donor("D 40"), create_donor("D 1")
        route = create_route(driver["id"], "2026-08-10", 100)

        add_stop(route["id"], d1["id"], "2026-08-10T08:00:00Z",
                 "2026-08-10T09:00:00Z", 60)
        add_stop(route["id"], d2["id"], "2026-08-10T10:00:00Z",
                 "2026-08-10T11:00:00Z", 40)
        route_after = _get_route(api, route["id"])
        assert route_after["total_volume_cuft"] == pytest.approx(100), (
            "a stop that fills the truck exactly is allowed"
        )

        resp = api.add_stop(route["id"], {
            "donor_id": d3["id"],
            "window_start": "2026-08-10T12:00:00Z",
            "window_end": "2026-08-10T13:00:00Z",
            "estimated_volume_cuft": 1,
        }, MGR)
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)

    def test_volunteer_driver_rejected(self, api):
        """PRD 3.7: "The referenced driver must be an ACTIVE worker whose
        `employment_type` is `STAFF` — volunteers and transitional-employment
        participants never drive — or creation fails with `ERR_DRIVER_NOT_STAFF`."

        Design: Corner/validations/volunteer_driver_rejected
        """
        from test_helpers import create_worker
        volunteer = create_worker("W Vol", "VOLUNTEER")
        resp = api.create_route({
            "route_date": "2026-08-10",
            "driver_worker_id": volunteer["id"],
            "truck_capacity_cuft": 500,
        }, MGR)
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_STAFF)


class TestReschedule:
    def test_reschedule_no_show_creates_new_stop(self, api):
        """PRD 3.7: "A no-show is terminal for the stop itself, but a `StoreManager`
        may reschedule from a `NO_SHOW` stop: rescheduling creates a NEW stop in
        `SCHEDULED` on a target route — named by `target_route_id` and required to be
        `DRAFT` or `PUBLISHED` — with fresh `window_start` and `window_end`, carrying
        over the same `donor_id` and `estimated_volume_cuft`, and running the
        window-conflict and capacity checks against the target route, whose counters
        and `version` update accordingly. No transition ever moves the original stop
        out of `NO_SHOW`."

        Design: Corner/endpoints/reschedule_no_show_creates_new_stop
        """
        driver = create_driver()
        donor = create_donor("D Ns")
        route1 = create_route(driver["id"], "2026-08-10", 500)
        s1 = add_stop(route1["id"], donor["id"], "2026-08-10T09:00:00Z",
                      "2026-08-10T10:00:00Z", 120)
        publish_route(route1["id"])
        start_route(route1["id"])
        depart_stop(s1["id"], driver["id"])
        no_show_stop(s1["id"], driver["id"])

        route2 = create_route(driver["id"], "2026-08-11", 500)
        new_stop = validate_success(
            api.reschedule_stop(s1["id"], {
                "target_route_id": route2["id"],
                "window_start": "2026-08-11T09:00:00Z",
                "window_end": "2026-08-11T10:00:00Z",
            }, MGR),
            201,
        )
        assert new_stop["id"] != s1["id"], "reschedule creates a NEW stop"
        assert new_stop["status"] == "SCHEDULED"
        assert new_stop["route_id"] == route2["id"]
        assert new_stop["donor_id"] == donor["id"]
        assert new_stop["estimated_volume_cuft"] == pytest.approx(120)

        original = _get_stop(api, s1["id"])
        assert original["status"] == "NO_SHOW", "the original is terminally NO_SHOW"

        route2_after = _get_route(api, route2["id"])
        assert route2_after["stop_count"] == 1
        assert route2_after["total_volume_cuft"] == pytest.approx(120)

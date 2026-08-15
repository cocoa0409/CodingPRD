"""Cancellation cutoff, refuse/reschedule cycle, allowance conservation,
route-capacity conservation under refusal, and terminal-state guards."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cancel_payload,
    create_route_day,
    dispatch_route,
    find_assessment,
    get_ledger_row,
    get_request,
    get_request_assessments,
    get_request_items,
    get_request_notifications,
    get_route_day,
    get_success_data,
    make_resident_headers,
    schedule_request,
    set_clock,
    setup_completed_request,
    setup_refused_request,
    setup_scheduled_request,
    validate_error,
    validate_success,
)

DRIVER = TEST_USERS["driver_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestCancelCutoff:
    def _two_scheduled_households(self, api):
        set_clock("2026-08-05T00:00:00Z")
        rd_a = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")
        rd_b = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")
        hh_a, req_a, _, _ = setup_scheduled_request(
            street_address="71 Cutoff Ct", service_zone="ZONE_NORTH",
            items=((1, "TIRES", False, True),), route_day=rd_a,
        )
        hh_b, req_b, _, _ = setup_scheduled_request(
            street_address="72 Cutoff Ct", service_zone="ZONE_NORTH",
            items=((1, "TIRES", False, True),), route_day=rd_b,
        )
        return hh_a, req_a, hh_b, req_b

    def test_cancel_before_midnight_of_pickup_day_succeeds(self, api):
        """PRD §3.3: "Cancelling a `SCHEDULED` request additionally unwinds
        the commitment, but only before the cutoff: the logical clock must be
        strictly earlier than midnight at the start of `scheduled_date`; at or
        after that midnight the pickup day has begun and cancellation fails
        with `ERR_TEMPORAL_CONFLICT`."

        Design: Corner/validations/cancel_cutoff_at_midnight_of_pickup_day
        """
        hh_a, req_a, _, _ = self._two_scheduled_households(api)
        set_clock("2026-08-09T23:59:59Z")
        resp = api.cancel_pickup_request(
            req_a["id"], cancel_payload(req_a["version"]),
            make_resident_headers(hh_a["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"

    def test_cancel_at_midnight_of_pickup_day_fails(self, api):
        """PRD §3.3: "the logical clock must be strictly earlier than midnight
        at the start of `scheduled_date`; at or after that midnight the pickup
        day has begun and cancellation fails with `ERR_TEMPORAL_CONFLICT`."

        Design: Corner/validations/cancel_cutoff_at_midnight_of_pickup_day
        """
        _, _, hh_b, req_b = self._two_scheduled_households(api)
        set_clock("2026-08-10T00:00:00Z")
        resp = api.cancel_pickup_request(
            req_b["id"], cancel_payload(req_b["version"]),
            make_resident_headers(hh_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT)
        assert resp.status_code == 422


class TestCancelFromCompleted:
    def test_cancel_from_completed_returns_invalid_state(self, api):
        """PRD §3.3: "Cancellation is the resident's release valve, available
        from `SUBMITTED`, `SCHEDULED`, `MISSED`, and `REFUSED`, always
        carrying `expected_request_version` per §2.7."
        PRD §2.9: "(4) state-machine legality — the resource's current state
        lists the attempted trigger, else `ERR_INVALID_STATE`"

        Design: Corner/state_machines/cancel_from_completed_returns_invalid_state
        """
        hh, req, _, _ = setup_completed_request(
            street_address="11 Terminal Ter", service_zone="ZONE_NORTH"
        )
        done = get_request(hh["id"], req["id"])
        resp = api.cancel_pickup_request(
            req["id"], cancel_payload(done["version"]),
            make_resident_headers(hh["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        invoice = find_assessment(
            get_request_assessments(req["id"]), "FINAL_INVOICE"
        )
        assert invoice["status"] == "PENDING"


class TestAllowanceConservationUnderCancel:
    def _setup_scheduled_three_items(self, api):
        set_clock("2026-08-05T00:00:00Z")
        hh, req, items, rd = setup_scheduled_request(
            street_address="12 Redwood Rd", service_zone="ZONE_WEST",
            annual_allowance_items=4,
            items=(
                (1, "STANDARD_FURNITURE", False, True),
                (2, "STANDARD_FURNITURE", False, True),
                (3, "STANDARD_FURNITURE", False, True),
            ),
        )
        return hh, req

    def test_scheduled_cancel_exactly_reverses_consumption(self, api):
        """PRD §3.3: "A timely scheduled-cancel releases the route
        (`committed_load_units` falls by the request's `load_units`,
        `committed_stops` by 1, RouteDay `version` bumps) and releases the
        allowance: `items_consumed` falls by the number of items flagged
        `within_allowance`, `items_released` rises by the same count,
        `over_allowance_items` falls by the number of unflagged items, every
        item's `within_allowance` resets to false, the provisional quote is
        waived, and a `CANCELLATION_NOTICE` goes out."

        Design: Difficulty/compensating_invariant/allowance_conservation_under_cancel
        """
        hh, req = self._setup_scheduled_three_items(api)
        ledger_before = get_ledger_row(hh["id"], 2026)
        assert ledger_before["items_consumed"] == 3

        resp = api.cancel_pickup_request(
            req["id"], cancel_payload(req["version"]),
            make_resident_headers(hh["id"]),
        )
        validate_success(resp)

        ledger = get_ledger_row(hh["id"], 2026)
        assert ledger["items_consumed"] == 0
        assert ledger["items_released"] == 3
        assert ledger["items_consumed"] + ledger["items_released"] == 3

    def test_item_flags_reset_after_release(self, api):
        """PRD §3.3: "every item's `within_allowance` resets to false, the
        provisional quote is waived, and a `CANCELLATION_NOTICE` goes out."

        Design: Difficulty/compensating_invariant/allowance_conservation_under_cancel
        """
        hh, req = self._setup_scheduled_three_items(api)
        resp = api.cancel_pickup_request(
            req["id"], cancel_payload(req["version"]),
            make_resident_headers(hh["id"]),
        )
        validate_success(resp)
        items = get_request_items(req["id"], make_resident_headers(hh["id"]))
        assert all(i["within_allowance"] is False for i in items)


class TestRefusalRescheduleCycle:
    def _setup_refused(self, api):
        set_clock("2026-08-05T00:00:00Z")
        rd2 = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-17")
        hh, req, items, rd1 = setup_refused_request(
            street_address="9 Cedar Ct", service_zone="ZONE_NORTH",
            annual_allowance_items=4, route_date="2026-08-10",
            refusal_reason_code="IMPROPER_PREPARATION",
            items=(
                (1, "STANDARD_FURNITURE", False, True),
                (2, "STANDARD_FURNITURE", False, True),
            ),
        )
        return hh, req, rd1, rd2

    def test_refused_request_reschedules_onto_new_route(self, api):
        """PRD §3.3: "Refusal does not end the booking relationship: from
        `REFUSED` the resident may schedule again onto another (or the same)
        open route, under the full set of scheduling gates above."

        Design: Difficulty/non_linear_state_machine/pickup_request_refusal_reschedule_cycle
        """
        hh, req, rd1, rd2 = self._setup_refused(api)
        set_clock("2026-08-12T00:00:00Z")
        data = schedule_request(hh["id"], req["id"], rd2)
        assert data["status"] == "SCHEDULED"
        assert data["scheduled_date"] == "2026-08-17"

        assert get_route_day(rd1["id"])["committed_load_units"] == 0
        assert get_route_day(rd2["id"])["committed_load_units"] == 4

    def test_reschedule_is_allowance_idempotent(self, api):
        """PRD §3.3: "The ledger is idempotent across this recovery loop —
        because a refusal never released allowance (§3.4), re-scheduling
        consumes slots only for items whose `within_allowance` is false and
        which have never consumed a slot on this request; items already
        counted keep their flags and are skipped."
        PRD §3.4: "the household's allowance is **not** released — the set-out
        was made and consumed service capacity reaching the curb, so
        `items_consumed` stands."

        Design: Difficulty/non_linear_state_machine/pickup_request_refusal_reschedule_cycle
        """
        hh, req, rd1, rd2 = self._setup_refused(api)
        ledger_mid = get_ledger_row(hh["id"], 2026)
        assert ledger_mid["items_consumed"] == 2
        assert ledger_mid["items_released"] == 0

        set_clock("2026-08-12T00:00:00Z")
        data = schedule_request(hh["id"], req["id"], rd2)
        assert data["status"] == "SCHEDULED"

        ledger = get_ledger_row(hh["id"], 2026)
        assert ledger["items_consumed"] == 2
        assert ledger["items_released"] == 0

        notices = get_request_notifications(req["id"])
        refusal_notices = [n for n in notices if n["kind"] == "REFUSAL_NOTICE"]
        assert len(refusal_notices) == 1
        assert refusal_notices[0]["reason_code"] == "IMPROPER_PREPARATION"


class TestRouteCapacityConservationUnderRefusal:
    def _setup(self, api):
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10",
                              max_load_units=40, max_stops=25)
        # Other household occupies 5 load units (one refrigerant appliance).
        hh_o, req_o, _, _ = setup_scheduled_request(
            street_address="3 Magnolia Mews", service_zone="ZONE_NORTH",
            items=((1, "APPLIANCE_WITH_REFRIGERANT", False, True),),
            route_day=rd,
        )
        hh, req, _, _ = setup_scheduled_request(
            street_address="4 Magnolia Mews", service_zone="ZONE_NORTH",
            items=(
                (1, "STANDARD_FURNITURE", False, True),
                (2, "STANDARD_FURNITURE", False, True),
            ),
            route_day=rd,
        )
        set_clock("2026-08-10T07:00:00Z")
        dispatch_route(rd["id"])
        return hh, req, rd

    def test_refusal_restores_route_capacity_exactly(self, api):
        """PRD §3.4: "The route's committed load and stops are released (and
        the RouteDay's `version` bumps), but the household's allowance is
        **not** released — the set-out was made and consumed service capacity
        reaching the curb, so `items_consumed` stands."

        Design: Difficulty/compensating_invariant/route_capacity_conservation_under_refusal
        """
        hh, req, rd = self._setup(api)
        assert get_route_day(rd["id"])["committed_load_units"] == 9

        get_success_data(api.refuse_pickup_request(
            req["id"], {"refusal_reason_code": "BLOCKED_ACCESS"}, DRIVER
        ))
        route = get_route_day(rd["id"])
        assert route["committed_load_units"] == 5
        assert route["committed_stops"] == 1

    def test_refusal_does_not_release_allowance(self, api):
        """PRD §3.4: "the household's allowance is **not** released — the
        set-out was made and consumed service capacity reaching the curb, so
        `items_consumed` stands."

        Design: Difficulty/compensating_invariant/route_capacity_conservation_under_refusal
        """
        hh, req, rd = self._setup(api)
        get_success_data(api.refuse_pickup_request(
            req["id"], {"refusal_reason_code": "BLOCKED_ACCESS"}, DRIVER
        ))
        ledger = get_ledger_row(hh["id"], 2026)
        assert ledger["items_consumed"] == 2
        assert ledger["items_released"] == 0


class TestDoubleRefuse:
    def test_double_refuse_is_idempotency_error(self, api):
        """PRD §3.4: "A `Driver` working a dispatched route resolves each stop
        in one of three ways, all of which require the logical clock's date to
        equal the request's `scheduled_date` — off-date driver actions are
        `ERR_TEMPORAL_CONFLICT` — and all of which require the request to be
        `SCHEDULED`, anything else being `ERR_INVALID_STATE`."

        Design: Corner/state_machines/double_refuse_is_idempotency_error
        """
        hh, req, _, rd = setup_refused_request(
            street_address="13 Idem St", service_zone="ZONE_EAST",
            refusal_reason_code="BLOCKED_ACCESS",
        )
        resp = api.refuse_pickup_request(
            req["id"], {"refusal_reason_code": "UNSAFE_SETOUT"}, DRIVER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        after = get_request(hh["id"], req["id"])
        assert after["refusal_reason_code"] == "BLOCKED_ACCESS"
        assert get_route_day(rd["id"])["committed_load_units"] == 0

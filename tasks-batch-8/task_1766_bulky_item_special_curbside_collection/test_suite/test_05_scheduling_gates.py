"""Scheduling gates: zone, temporal, capacity boundary, duplicate date,
optimistic concurrency, household standing, and validation priority pairs."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_item,
    create_draft_request,
    create_household,
    create_route_day,
    get_request,
    get_route_day,
    make_resident_headers,
    schedule_request,
    set_clock,
    setup_scheduled_request,
    setup_submitted_request,
    submit_request,
    suspend_household_via_illegal_dumping,
    validate_error,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _schedule_call(api, household_id, request_id, route_day_id, rd_version):
    return api.schedule_pickup_request(
        request_id,
        {
            "route_day_id": route_day_id,
            "expected_route_day_version": rd_version,
        },
        make_resident_headers(household_id),
    )


class TestZoneMismatch:
    def test_zone_mismatch_on_schedule(self, api):
        """PRD §3.3: "The target route must be `OPEN` — scheduling against a
        route that is `DISPATCHED` or `CLOSED` fails with `ERR_ROUTE_LOCKED` —
        and must serve the same zone as the requesting household, failing with
        `ERR_ZONE_MISMATCH` otherwise."

        Design: Corner/validations/zone_mismatch_on_schedule
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")
        hh, req, _ = setup_submitted_request(
            street_address="61 Zone Zt", service_zone="ZONE_SOUTH",
            items=((1, "TIRES", False, True),),
        )
        resp = _schedule_call(api, hh["id"], req["id"], rd["id"], rd["version"])
        validate_error(resp, ApiErrorId.ERR_ZONE_MISMATCH)
        assert resp.status_code == 422


class TestRouteCapacityBoundary:
    def _setup(self, api):
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(
            service_zone="ZONE_WEST", route_date="2026-08-10",
            max_load_units=5, max_stops=10,
        )
        return rd

    def test_capacity_equality_boundary_admits_exact_fill(self, api):
        """PRD §3.3: "Capacity is enforced at the boundary inclusively: the
        schedule succeeds when the route's `committed_load_units` plus the
        request's `load_units` is less than or equal to `max_load_units` and
        `committed_stops` plus one is less than or equal to `max_stops`"

        Design: Difficulty/boundary_precision_check/route_capacity_equality_boundary
        """
        rd = self._setup(api)
        hh1, req1, _ = setup_submitted_request(
            street_address="1 Hickory Hts", service_zone="ZONE_WEST",
            items=((1, "APPLIANCE_WITH_REFRIGERANT", False, True),),
        )
        resp = _schedule_call(api, hh1["id"], req1["id"], rd["id"], rd["version"])
        data = validate_success(resp)
        assert data["status"] == "SCHEDULED"
        route = get_route_day(rd["id"])
        assert route["committed_load_units"] == 5
        assert route["committed_load_units"] == route["max_load_units"]

    def test_one_unit_over_capacity_rejected(self, api):
        """PRD §3.3: "exceeding either bound is rejected with
        `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/route_capacity_equality_boundary
        """
        rd = self._setup(api)
        hh1, req1, _ = setup_submitted_request(
            street_address="1 Hickory Hts", service_zone="ZONE_WEST",
            items=((1, "APPLIANCE_WITH_REFRIGERANT", False, True),),
        )
        validate_success(
            _schedule_call(api, hh1["id"], req1["id"], rd["id"], rd["version"])
        )
        hh2, req2, _ = setup_submitted_request(
            street_address="2 Hickory Hts", service_zone="ZONE_WEST",
            items=((1, "TIRES", False, True),),
        )
        rd_now = get_route_day(rd["id"])
        resp = _schedule_call(api, hh2["id"], req2["id"], rd["id"], rd_now["version"])
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)
        assert resp.status_code == 409


class TestDuplicatePickupDate:
    def _setup(self, api):
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("90 Chestnut Cir", "ZONE_NORTH",
                              annual_allowance_items=10)
        rd1 = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")
        rd2 = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")
        rd3 = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-11")

        req_a = create_draft_request(hh["id"])
        add_item(hh["id"], req_a["id"], 1, "STANDARD_FURNITURE", False, True)
        submit_request(hh["id"], req_a["id"])
        validate_success(
            _schedule_call(api, hh["id"], req_a["id"], rd1["id"], rd1["version"])
        )

        req_b = create_draft_request(hh["id"])
        add_item(hh["id"], req_b["id"], 1, "STANDARD_FURNITURE", False, True)
        submit_request(hh["id"], req_b["id"])
        return hh, req_b, rd2, rd3

    def test_second_booking_same_date_rejected(self, api):
        """PRD §3.3: "One household may hold at most one `SCHEDULED` request
        per calendar date — a point-equality test on the date, not an
        interval-overlap test — and a second booking on the same date fails
        with `ERR_DUPLICATE_PICKUP_DATE`."

        Design: Difficulty/resource_temporal_overlap/same_household_same_date_point_equality
        """
        hh, req_b, rd2, _ = self._setup(api)
        resp = _schedule_call(api, hh["id"], req_b["id"], rd2["id"], rd2["version"])
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PICKUP_DATE)
        assert resp.status_code == 409

    def test_adjacent_date_booking_allowed(self, api):
        """PRD §3.3: "One household may hold at most one `SCHEDULED` request
        per calendar date — a point-equality test on the date, not an
        interval-overlap test"

        Design: Difficulty/resource_temporal_overlap/same_household_same_date_point_equality
        """
        hh, req_b, _, rd3 = self._setup(api)
        resp = _schedule_call(api, hh["id"], req_b["id"], rd3["id"], rd3["version"])
        data = validate_success(resp)
        assert data["status"] == "SCHEDULED"
        assert data["scheduled_date"] == "2026-08-11"


class TestOptimisticConcurrency:
    def test_err_stale_route_version_on_schedule(self, api):
        """PRD §2.7: "A scheduling request must carry
        `expected_route_day_version`, equal to the `version` of the target
        RouteDay as the client last observed it. If the RouteDay's current
        `version` has advanced since that read — for example because another
        request was just scheduled onto the route or cancelled off it,
        legitimately moving `committed_load_units` or `committed_stops` — the
        schedule attempt is rejected with `ERR_STALE_ROUTE_VERSION` (HTTP
        412), because the client's capacity view is stale."

        Design: Corner/errors/err_stale_route_version_on_schedule
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")
        stale_version = rd["version"]

        hh1, req1, _ = setup_submitted_request(
            street_address="103 OCC Ave", service_zone="ZONE_NORTH",
            items=((1, "TIRES", False, True),),
        )
        validate_success(
            _schedule_call(api, hh1["id"], req1["id"], rd["id"], stale_version)
        )

        hh2, req2, _ = setup_submitted_request(
            street_address="104 OCC Ave", service_zone="ZONE_NORTH",
            items=((1, "TIRES", False, True),),
        )
        resp = _schedule_call(api, hh2["id"], req2["id"], rd["id"], stale_version)
        validate_error(resp, ApiErrorId.ERR_STALE_ROUTE_VERSION)
        assert resp.status_code == 412
        assert get_request(hh2["id"], req2["id"])["status"] == "SUBMITTED"
        assert get_route_day(rd["id"])["committed_stops"] == 1

    def test_err_stale_request_version_on_cancel(self, api):
        """PRD §2.7: "A cancellation request must carry
        `expected_request_version`, equal to the `version` of the
        PickupRequest as the client last observed it. If the request's current
        `version` has advanced — for example because it was just rescheduled
        after a refusal, which re-priced the quote and re-froze amnesty status
        — the cancel attempt is rejected with `ERR_STALE_REQUEST_VERSION`
        (HTTP 412), because the fiscal state the client intends to void is no
        longer the one on record."

        Design: Corner/errors/err_stale_request_version_on_cancel
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_WEST", route_date="2026-08-10")
        hh, req, _ = setup_submitted_request(
            street_address="105 OCC Ct", service_zone="ZONE_WEST",
            items=((1, "TIRES", False, True),),
        )
        stale_req_version = req["version"]  # version at SUBMITTED
        scheduled = schedule_request(hh["id"], req["id"], rd)
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["version"] == stale_req_version + 1

        resp = api.cancel_pickup_request(
            req["id"],
            {"expected_request_version": stale_req_version},
            make_resident_headers(hh["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_REQUEST_VERSION)
        assert resp.status_code == 412
        assert get_request(hh["id"], req["id"])["status"] == "SCHEDULED"


class TestHouseholdSuspensionGate:
    def test_schedule_gated_by_household_active(self, api):
        """PRD §3.1: "When the household is suspended — the only path to which
        is a confirmed illegal-dumping determination, described in §3.6 — the
        system records the cause in `suspension_reason` (set to
        `ILLEGAL_DUMPING` by the cascade, null while active) and the household
        loses the ability to consume municipal service: creating a new pickup
        request, submitting one, or scheduling one are all rejected with
        `ERR_HOUSEHOLD_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/schedule_gated_by_household_active
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_EAST", route_date="2026-08-10")
        hh, req, _ = setup_submitted_request(
            street_address="77 Sycamore St", service_zone="ZONE_EAST",
            items=((1, "ELECTRONICS", False, True),),
        )
        suspend_household_via_illegal_dumping(hh["id"])

        resp = _schedule_call(api, hh["id"], req["id"], rd["id"], rd["version"])
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_SUSPENDED)
        assert resp.status_code == 409
        assert get_request(hh["id"], req["id"])["status"] == "SUBMITTED"
        assert get_route_day(rd["id"])["committed_stops"] == 0

    def test_suspension_gate_evaluated_at_transition_attempt(self, api):
        """PRD §3.1: "The suspension gate is evaluated at the moment of the
        attempted transition, not eagerly at the moment of suspension."

        Design: Difficulty/cross_entity_state_dependency/schedule_gated_by_household_active
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_EAST", route_date="2026-08-10")
        hh, req, _ = setup_submitted_request(
            street_address="79 Sycamore St", service_zone="ZONE_EAST",
            items=((1, "ELECTRONICS", False, True),),
        )
        # Request sits SUBMITTED and untouched through the suspension.
        suspend_household_via_illegal_dumping(hh["id"])
        resp = _schedule_call(api, hh["id"], req["id"], rd["id"], rd["version"])
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_SUSPENDED)
        assert get_request(hh["id"], req["id"])["status"] == "SUBMITTED"


class TestPriorityPairs:
    def test_state_error_precedes_prohibited_item_on_schedule(self, api):
        """PRD §2.9: "Every guarded endpoint evaluates checks in a fixed
        priority order, so that when several problems coexist the same error
        always surfaces first. The order is: ... (4) state-machine legality —
        the resource's current state lists the attempted trigger, else
        `ERR_INVALID_STATE`; (5) optimistic-concurrency checks on the two
        guarded writes, else the stale-version error; (6) prohibited-item and
        preparation scans at submission (the prohibition scan runs first, the
        preparation-acknowledgement scan second), else `ERR_PROHIBITED_ITEM`
        or `ERR_PREPARATION_NOT_ACKED`"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_submit
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")
        hh = create_household("8 Ash Blvd", "ZONE_NORTH", annual_allowance_items=4)
        req = create_draft_request(hh["id"])
        add_item(hh["id"], req["id"], 1, "PROHIBITED", False, True)

        # Schedule from DRAFT: state check (4) fires before any submission
        # safety scan (6) would ever run.
        resp = _schedule_call(api, hh["id"], req["id"], rd["id"], rd["version"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        assert get_request(hh["id"], req["id"])["status"] == "DRAFT"

    def test_prohibited_item_error_only_surfaces_at_submit(self, api):
        """PRD §3.2: "A safety scan then runs, prohibition first: any item
        whose `category` is `PROHIBITED` causes rejection with
        `ERR_PROHIBITED_ITEM`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_submit
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("8B Ash Blvd", "ZONE_NORTH", annual_allowance_items=4)
        req = create_draft_request(hh["id"])
        add_item(hh["id"], req["id"], 1, "PROHIBITED", False, True)

        resp = api.submit_pickup_request(req["id"], make_resident_headers(hh["id"]))
        validate_error(resp, ApiErrorId.ERR_PROHIBITED_ITEM)
        assert resp.status_code == 422
        assert get_request(hh["id"], req["id"])["status"] == "DRAFT"

    def test_temporal_conflict_precedes_capacity_on_schedule(self, api):
        """PRD §2.9: "(9) temporal rules, else `ERR_TEMPORAL_CONFLICT`; (10)
        the one-scheduled-pickup-per-household-per-date rule, else
        `ERR_DUPLICATE_PICKUP_DATE`; (11) aggregate route capacity, else
        `ERR_ROUTE_CAPACITY_EXCEEDED`"
        PRD §3.3: "The route's date must not be in the past: a `route_date`
        earlier than the logical clock's date is rejected with
        `ERR_TEMPORAL_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_on_schedule
        """
        set_clock("2026-08-01T00:00:00Z")
        rd = create_route_day(
            service_zone="ZONE_EAST", route_date="2026-08-03",
            max_load_units=2, max_stops=1,
        )
        hh_other, req_other, _ = setup_submitted_request(
            street_address="30 Poplar Pl", service_zone="ZONE_EAST",
            items=((1, "STANDARD_FURNITURE", False, True),),
        )
        validate_success(
            _schedule_call(api, hh_other["id"], req_other["id"],
                           rd["id"], rd["version"])
        )

        hh, req, _ = setup_submitted_request(
            street_address="32 Poplar Pl", service_zone="ZONE_EAST",
            items=((1, "STANDARD_FURNITURE", False, True),),
        )
        # Advance clock past route_date: route now both past-dated AND full.
        set_clock("2026-08-05T00:00:00Z")
        rd_now = get_route_day(rd["id"])
        resp = _schedule_call(api, hh["id"], req["id"], rd["id"], rd_now["version"])
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT)
        assert resp.status_code == 422
        assert get_route_day(rd["id"])["committed_stops"] == 1

    def test_past_route_alone_gives_temporal_not_capacity(self, api):
        """PRD §3.3: "The route's date must not be in the past: a `route_date`
        earlier than the logical clock's date is rejected with
        `ERR_TEMPORAL_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_fiscal_on_schedule
        """
        set_clock("2026-08-01T00:00:00Z")
        rd = create_route_day(
            service_zone="ZONE_EAST", route_date="2026-08-03",
            max_load_units=40, max_stops=25,
        )
        hh, req, _ = setup_submitted_request(
            street_address="34 Poplar Pl", service_zone="ZONE_EAST",
            items=((1, "STANDARD_FURNITURE", False, True),),
        )
        set_clock("2026-08-05T00:00:00Z")
        resp = _schedule_call(api, hh["id"], req["id"], rd["id"], rd["version"])
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT)
        assert get_route_day(rd["id"])["committed_stops"] == 0

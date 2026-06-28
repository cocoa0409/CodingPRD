"""Dispatch, crew-route, weather-hold and reschedule tests.

Covers Difficulty rules priority_pair_validation_conflict, the route-capacity
boundary, the visit<->route dependency, resource_temporal_overlap, plus corner
concurrency/weather/region instances.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_account_holder_headers, make_crew_tech_headers,
    create_active_subscription, list_recurring_visits, create_crew,
    create_route, dispatch_visit, log_application, complete_visit, set_clock,
    create_service_plan, create_account_holder, create_property, add_zone,
    create_subscription, activate_subscription, create_weather_event,
    setup_visit_on_weather_hold,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _two_active_subs_same_region(region="NE01", season_end="2026-08-31"):
    plan = create_service_plan()
    holder = create_account_holder()
    prop = create_property(holder["id"], service_region_code=region)
    add_zone(prop, holder["id"], zone_type="TURF", area_sqft=4000)
    sub1 = create_subscription(prop["id"], plan["id"], holder["id"], billing_mode="PER_VISIT", season_end_date=season_end)
    sub1 = activate_subscription(sub1["id"], holder["id"])
    sub2 = create_subscription(prop["id"], plan["id"], holder["id"], billing_mode="PER_VISIT", season_end_date=season_end)
    sub2 = activate_subscription(sub2["id"], holder["id"])
    v1 = list_recurring_visits(sub1["id"])[0]
    v2 = list_recurring_visits(sub2["id"])[0]
    return holder, prop, [v1, v2]


class TestStateBeatsBusinessSafetyOnWeatherHold:
    """State check (ERR_INVALID_STATE) wins over safety check on a COMPLETED visit."""

    def _completed_visit(self):
        ctx = create_active_subscription(region="NE01")
        crew = create_crew(home_region_code="NE01")
        set_clock("2026-05-01T08:00:00Z")
        rec = list_recurring_visits(ctx["sub"]["id"])[0]
        route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
        dispatch_visit(route["id"], rec["id"], route["version"])
        log_application(rec["id"], ctx["zones"][0]["id"], crew["id"])
        complete_visit(rec["id"], crew["id"])
        return rec

    def test_completed_visit_weather_hold_returns_invalid_state(self, api):
        """
    PRD 2.9: "The order is: authentication (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource (`ERR_NOT_FOUND`), then resource ownership for entity-backed callers (`ERR_NOT_RESOURCE_OWNER`), then state validity of the requested transition (`ERR_INVALID_STATE`), then the dispatch concurrency check (`ERR_STALE_VERSION`), then request well-formedness — required fields, enum membership, and numeric ranges (`ERR_INVALID_REQUEST`) — and finally the domain-specific business rules described throughout §3."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_weather_hold
        """
        rec = self._completed_visit()
        we = create_weather_event(region_code="NE01", event_date="2026-05-01", severity="RAIN_LIGHT")
        validate_error(api.weather_hold(rec["id"], {"weather_event_id": we["id"]}, DISPATCHER), ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_check_precedes_qualifying_weather_check(self, api):
        """
    PRD 3.3: "A hold is permitted only when the visit is `SCHEDULED`, a qualifying weather event exists whose `region_code` matches the visit's property `service_region_code` and whose `event_date` equals the visit's `scheduled_date`, and that event's severity is either `RAIN_HEAVY` or `WIND_HIGH`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_weather_hold
        """
        rec = self._completed_visit()
        we = create_weather_event(region_code="NE01", event_date="2026-05-01", severity="RAIN_LIGHT")
        err = validate_error(api.weather_hold(rec["id"], {"weather_event_id": we["id"]}, DISPATCHER), ApiErrorId.ERR_INVALID_STATE.value)
        assert err["error_id"] != ApiErrorId.ERR_NO_QUALIFYING_WEATHER.value


class TestExistenceBeatsBusinessReferentialOnDispatch:
    """Non-existent visit on a region-mismatched route -> ERR_NOT_FOUND."""

    def test_nonexistent_visit_returns_not_found(self, api):
        """
    PRD 2.6: "For any request, the system validates the existence of every path identifier and every foreign-key body field in left-to-right path order, rejecting with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_referential_on_dispatch
        """
        crew = create_crew(home_region_code="SE02")
        route = create_route(crew["id"], region="SE02", route_date="2026-05-01")
        validate_error(api.dispatch_visit(route["id"],
            {"visit_id": "00000000-0000-4000-8000-000000000000", "expected_crewroute_version": route["version"]},
            DISPATCHER), ApiErrorId.ERR_NOT_FOUND.value)

    def test_existence_check_precedes_region_check(self, api):
        """
    PRD 2.6: "This existence check (priority 3) runs after authentication and role authorization but before ownership, state, and business-rule checks."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_referential_on_dispatch
        """
        crew = create_crew(home_region_code="SE02")
        route = create_route(crew["id"], region="SE02", route_date="2026-05-01")
        err = validate_error(api.dispatch_visit(route["id"],
            {"visit_id": "00000000-0000-4000-8000-000000000000", "expected_crewroute_version": route["version"]},
            DISPATCHER), ApiErrorId.ERR_NOT_FOUND.value)
        assert err["error_id"] != ApiErrorId.ERR_REGION_MISMATCH.value


class TestRouteCapacityZeroBoundary:
    """A daily_capacity=1 route accepts exactly one dispatch, then rejects."""

    def _setup(self):
        holder, prop, visits = _two_active_subs_same_region(region="NE01")
        crew = create_crew(home_region_code="NE01", daily_capacity=1)
        route = create_route(crew["id"], region="NE01", route_date="2026-05-01")
        dispatch_visit(route["id"], visits[0]["id"], route["version"])
        return route, visits

    def test_remaining_capacity_drops_to_zero_after_first_dispatch(self, api):
        """
    PRD 3.8: "the same assigned count yields `remaining_capacity` as the crew's `daily_capacity` minus that count, as an integer."

        Design: Difficulty/boundary_precision_check/route_capacity_zero_empty_slot_boundary
        """
        route, visits = self._setup()
        summary = get_success_data(api.get_crew_route_summary(route["id"], DISPATCHER))
        assert summary["remaining_capacity"] == 0, f"got {summary['remaining_capacity']}"

    def test_second_dispatch_at_capacity_rejected(self, api):
        """
    PRD 3.3: "a dispatch onto a route whose `remaining_capacity` is zero (its `assigned_visit_count` having reached the crew's `daily_capacity`) is rejected with `ERR_ROUTE_AT_CAPACITY`."

        Design: Difficulty/boundary_precision_check/route_capacity_zero_empty_slot_boundary
        """
        route, visits = self._setup()
        cur = get_success_data(api.get_crew_route(route["id"], DISPATCHER))
        validate_error(api.dispatch_visit(route["id"],
            {"visit_id": visits[1]["id"], "expected_crewroute_version": cur["version"]},
            DISPATCHER), ApiErrorId.ERR_ROUTE_AT_CAPACITY.value)


class TestDispatchRequiresRouteOpen:
    """Visit SCHEDULED->DISPATCHED depends on the route being OPEN."""

    def test_dispatch_onto_locked_route_returns_invalid_state(self, api):
        """
    PRD 3.8: "A dispatcher locks an `OPEN` route, transitioning it `OPEN → LOCKED`, after which no further visits may be dispatched onto it; the lock increments the route's `version`."

        Design: Difficulty/cross_entity_state_dependency/visit_dispatch_requires_route_open_visit_route_pair
        """
        ctx = create_active_subscription(region="NE01")
        crew = create_crew(home_region_code="NE01")
        rec = list_recurring_visits(ctx["sub"]["id"])[0]
        route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
        validate_success(api.lock_route(route["id"], DISPATCHER))
        validate_error(api.dispatch_visit(route["id"],
            {"visit_id": rec["id"], "expected_crewroute_version": route["version"]},
            DISPATCHER), ApiErrorId.ERR_INVALID_STATE.value)

    def test_visit_unchanged_after_rejected_dispatch(self, api):
        """
    PRD 3.3: "Dispatch is permitted only when the visit is `SCHEDULED`, the target route is `OPEN`, the route's `region_code` equals the visit's property `service_region_code`, the route's `route_date` equals the visit's `scheduled_date`, and the route has at least one unit of remaining capacity."

        Design: Difficulty/cross_entity_state_dependency/visit_dispatch_requires_route_open_visit_route_pair
        """
        ctx = create_active_subscription(region="NE01")
        crew = create_crew(home_region_code="NE01")
        rec = list_recurring_visits(ctx["sub"]["id"])[0]
        route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
        validate_success(api.lock_route(route["id"], DISPATCHER))
        validate_error(api.dispatch_visit(route["id"],
            {"visit_id": rec["id"], "expected_crewroute_version": route["version"]},
            DISPATCHER), ApiErrorId.ERR_INVALID_STATE.value)
        assert get_success_data(api.get_visit(rec["id"], DISPATCHER))["status"] == "SCHEDULED"


class TestRouteDateMustEqualVisitDate:
    """Point-equality: a visit dispatches only onto a route whose date equals scheduled_date."""

    def test_route_date_mismatch_returns_region_mismatch(self, api):
        """
    PRD 3.3: "A region or date mismatch between route and visit is rejected with `ERR_REGION_MISMATCH`;"

        Design: Difficulty/resource_temporal_overlap/route_date_must_equal_visit_date_point_overlap
        """
        ctx = create_active_subscription(region="NE01")
        crew = create_crew(home_region_code="NE01")
        rec = list_recurring_visits(ctx["sub"]["id"])[0]
        route = create_route(crew["id"], region="NE01", route_date="2026-05-02")
        validate_error(api.dispatch_visit(route["id"],
            {"visit_id": rec["id"], "expected_crewroute_version": route["version"]},
            DISPATCHER), ApiErrorId.ERR_REGION_MISMATCH.value)

    def test_matching_route_date_dispatches_successfully(self, api):
        """
    PRD 3.3: "Dispatch is permitted only when the visit is `SCHEDULED`, the target route is `OPEN`, the route's `region_code` equals the visit's property `service_region_code`, the route's `route_date` equals the visit's `scheduled_date`, and the route has at least one unit of remaining capacity."

        Design: Difficulty/resource_temporal_overlap/route_date_must_equal_visit_date_point_overlap
        """
        ctx = create_active_subscription(region="NE01")
        crew = create_crew(home_region_code="NE01")
        rec = list_recurring_visits(ctx["sub"]["id"])[0]
        route = create_route(crew["id"], region="NE01", route_date="2026-05-01")
        dispatched = validate_success(api.dispatch_visit(route["id"],
            {"visit_id": rec["id"], "expected_crewroute_version": route["version"]}, DISPATCHER))
        assert dispatched["status"] == "DISPATCHED"


class TestRescheduleStrictlyAfterHeldDate:
    """Strict-greater lower bound: same-day reschedule -> ERR_DATE_OUT_OF_SEASON."""

    def test_same_day_reschedule_rejected(self, api):
        """
    PRD 3.3: "The new date must be strictly later than the date the visit was held on and on or before the owning subscription's `season_end_date`, and no `RAIN_HEAVY` or `WIND_HIGH` weather event may exist for the property's region on the new date. A target date that is not strictly after the held date, or that falls after the season end, is rejected with `ERR_DATE_OUT_OF_SEASON`."

        Design: Difficulty/resource_temporal_overlap/reschedule_strictly_after_open_ended_future_window
        """
        ctx = setup_visit_on_weather_hold(severity="WIND_HIGH", region="NE01")
        validate_error(api.reschedule_visit(ctx["visit"]["id"], {"new_scheduled_date": "2026-05-01"}, DISPATCHER), ApiErrorId.ERR_DATE_OUT_OF_SEASON.value)

    def test_visit_stays_on_hold_after_rejected_reschedule(self, api):
        """
    PRD 3.3: "**Rescheduling.** A dispatcher lifts a hold by rescheduling, transitioning the visit `WEATHER_HOLD → SCHEDULED` with a `new_scheduled_date`."

        Design: Difficulty/resource_temporal_overlap/reschedule_strictly_after_open_ended_future_window
        """
        ctx = setup_visit_on_weather_hold(severity="WIND_HIGH", region="NE01")
        validate_error(api.reschedule_visit(ctx["visit"]["id"], {"new_scheduled_date": "2026-05-01"}, DISPATCHER), ApiErrorId.ERR_DATE_OUT_OF_SEASON.value)
        assert get_success_data(api.get_visit(ctx["visit"]["id"], DISPATCHER))["status"] == "WEATHER_HOLD"


def test_dispatch_stale_route_version_returns_stale_version(api):
    """
    PRD 2.7: "If that value does not match the route's current `version` at the moment of dispatch, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/dispatch_visit_stale_route_version_returns_stale_version
    """
    holder, prop, visits = _two_active_subs_same_region(region="NE01")
    crew = create_crew(home_region_code="NE01", daily_capacity=4)
    route = create_route(crew["id"], region="NE01", route_date="2026-05-01")
    stale = route["version"]
    dispatch_visit(route["id"], visits[0]["id"], stale)
    validate_error(api.dispatch_visit(route["id"],
        {"visit_id": visits[1]["id"], "expected_crewroute_version": stale}, DISPATCHER), ApiErrorId.ERR_STALE_VERSION.value)
    assert get_success_data(api.get_visit(visits[1]["id"], DISPATCHER))["status"] == "SCHEDULED"


def test_route_summary_reports_remaining_capacity_on_capacity_three(api):
    """
    PRD 3.8: "the same assigned count yields `remaining_capacity` as the crew's `daily_capacity` minus that count, as an integer."

    Design: Corner/calculations/route_load_factor_precision_four_decimals
    """
    ctx = create_active_subscription(region="NE01")
    crew = create_crew(home_region_code="NE01", daily_capacity=3)
    rec = list_recurring_visits(ctx["sub"]["id"])[0]
    route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
    dispatch_visit(route["id"], rec["id"], route["version"])
    summary = get_success_data(api.get_crew_route_summary(route["id"], DISPATCHER))
    assert summary["assigned_visit_count"] == 1
    assert summary["remaining_capacity"] == 2, f"got {summary['remaining_capacity']}"


def test_weather_hold_rain_light_returns_no_qualifying_weather(api):
    """
    PRD 3.3: "A `RAIN_LIGHT` advisory never qualifies; an attempt to hold without a qualifying event is rejected with `ERR_NO_QUALIFYING_WEATHER`."

    Design: Corner/validations/weather_hold_rain_light_returns_no_qualifying_weather
    """
    ctx = create_active_subscription(region="NE01")
    rec = list_recurring_visits(ctx["sub"]["id"])[0]
    we = create_weather_event(region_code="NE01", event_date=rec["scheduled_date"], severity="RAIN_LIGHT")
    validate_error(api.weather_hold(rec["id"], {"weather_event_id": we["id"]}, DISPATCHER), ApiErrorId.ERR_NO_QUALIFYING_WEATHER.value)


def test_fourth_weather_hold_after_three_reschedules_rejected(api):
    """
    PRD 3.3: "A hold is also blocked once the visit's `reschedule_count` has reached 3 (the precondition requires `reschedule_count` to be below 3 before a hold)."

    Design: Corner/validations/reschedule_limit_fourth_reschedule_rejected
    """
    ctx = create_active_subscription(region="NE01")
    vid = list_recurring_visits(ctx["sub"]["id"])[0]["id"]
    for hold_date, new_date in [("2026-05-01","2026-05-08"),("2026-05-08","2026-05-15"),("2026-05-15","2026-05-22")]:
        we = create_weather_event(region_code="NE01", event_date=hold_date, severity="RAIN_HEAVY")
        validate_success(api.weather_hold(vid, {"weather_event_id": we["id"]}, DISPATCHER))
        validate_success(api.reschedule_visit(vid, {"new_scheduled_date": new_date}, DISPATCHER))
    we4 = create_weather_event(region_code="NE01", event_date="2026-05-22", severity="RAIN_HEAVY")
    validate_error(api.weather_hold(vid, {"weather_event_id": we4["id"]}, DISPATCHER), ApiErrorId.ERR_RESCHEDULE_LIMIT.value)
    assert get_success_data(api.get_visit(vid, DISPATCHER))["reschedule_count"] == 3


def test_crew_route_region_mismatch_on_create_returns_region_mismatch(api):
    """
    PRD 3.8: "A route's `region_code` must equal its crew's `home_region_code`; a mismatch at creation is rejected with `ERR_REGION_MISMATCH`."

    Design: Corner/validations/crew_route_region_mismatch_on_create_returns_region_mismatch
    """
    crew = create_crew(home_region_code="NE01")
    validate_error(api.create_crew_route(
        {"crew_id": crew["id"], "region_code": "SE02", "route_date": "2026-05-01"}, DISPATCHER), ApiErrorId.ERR_REGION_MISMATCH.value)


def test_application_log_on_excluded_zone_returns_zone_not_treatable(api):
    """
    PRD 3.4: "The sprayed zone must belong to the same property as the visit's subscription and must be in `ACTIVE` status — spraying a zone that belongs to a different property, or one that has been `EXCLUDED`, is rejected with `ERR_ZONE_NOT_TREATABLE`."

    Design: Corner/validations/application_log_excluded_zone_returns_zone_not_treatable
    """
    ctx = create_active_subscription(region="NE01",
        zones=[{"label": "Turf", "zone_type": "TURF", "area_sqft": 4000},
               {"label": "Perim", "zone_type": "PERIMETER", "area_sqft": 2000}])
    ah = make_account_holder_headers(ctx["holder"]["id"])
    perim = ctx["zones"][1]
    validate_success(api.exclude_zone(perim["id"], ah))
    crew = create_crew(home_region_code="NE01")
    rec = list_recurring_visits(ctx["sub"]["id"])[0]
    route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
    dispatch_visit(route["id"], rec["id"], route["version"])
    validate_error(api.add_application_log(rec["id"],
        {"treatment_zone_id": perim["id"], "product_code": "BIFEN_IT", "gallons_applied": 2.0, "logged_by_tech_id": crew["id"]},
        make_crew_tech_headers(crew["id"])), ApiErrorId.ERR_ZONE_NOT_TREATABLE.value)

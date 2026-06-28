"""Visit and subscription state-machine tests.

Covers Difficulty rule non_linear_state_machine plus corner state-machine instances.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_account_holder_headers, make_crew_tech_headers,
    create_service_plan, create_account_holder, create_property, add_zone,
    create_subscription, activate_subscription,
    create_active_subscription, list_recurring_visits, create_crew,
    create_route, dispatch_visit, log_application, complete_visit, set_clock,
    setup_visit_on_weather_hold,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestVisitCyclicWeatherHoldReschedule:
    """Visit is cyclic: SCHEDULED -> WEATHER_HOLD -> SCHEDULED."""

    def test_reschedule_returns_visit_to_scheduled(self, api):
        """
    PRD 3.3: "**Rescheduling.** A dispatcher lifts a hold by rescheduling, transitioning the visit `WEATHER_HOLD → SCHEDULED` with a `new_scheduled_date`."

        Design: Difficulty/non_linear_state_machine/visit_cyclic_weather_hold_reschedule_loop
        """
        ctx = setup_visit_on_weather_hold(severity="RAIN_HEAVY", region="NE01")
        result = validate_success(api.reschedule_visit(ctx["visit"]["id"], {"new_scheduled_date": "2026-05-08"}, DISPATCHER))
        assert result["status"] == "SCHEDULED", f"got {result['status']}"

    def test_reschedule_increments_count_and_moves_date(self, api):
        """
    PRD 3.3: "Rescheduling sets the visit's `scheduled_date` to the new date, increments its `reschedule_count` by one, and increments its `version`."

        Design: Difficulty/non_linear_state_machine/visit_cyclic_weather_hold_reschedule_loop
        """
        ctx = setup_visit_on_weather_hold(severity="RAIN_HEAVY", region="NE01")
        assert ctx["visit"]["reschedule_count"] == 0
        result = validate_success(api.reschedule_visit(ctx["visit"]["id"], {"new_scheduled_date": "2026-05-08"}, DISPATCHER))
        assert result["reschedule_count"] == 1, f"got {result['reschedule_count']}"
        assert result["scheduled_date"] == "2026-05-08", f"got {result['scheduled_date']}"


class TestSubscriptionBranchingDraftToActiveOrCancelled:
    """DRAFT subscription forks to ACTIVE (schedule) or CANCELLED (no schedule)."""

    def _two_draft_subs(self):
        plan = create_service_plan()
        holder = create_account_holder()
        prop = create_property(holder["id"], service_region_code="NE01")
        add_zone(prop, holder["id"], zone_type="TURF", area_sqft=4000)
        sub_a = create_subscription(prop["id"], plan["id"], holder["id"], billing_mode="PER_VISIT")
        sub_b = create_subscription(prop["id"], plan["id"], holder["id"], billing_mode="PER_VISIT")
        return holder, sub_a, sub_b

    def test_activate_branch_generates_schedule(self, api):
        """
    PRD 3.2: "Activation generates the entire **seasonal recurring schedule**: starting at the `season_start_date`, the system creates one `RECURRING` visit every `visit_interval_days`, assigning each a `sequence_index` of 1, 2, 3, and so on, and continues only while the resulting `scheduled_date` is on or before the `season_end_date`."

        Design: Difficulty/non_linear_state_machine/subscription_branching_draft_to_active_or_cancelled
        """
        holder, sub_a, _ = self._two_draft_subs()
        ah = make_account_holder_headers(holder["id"])
        activated = validate_success(api.activate_subscription(sub_a["id"], ah))
        assert activated["status"] == "ACTIVE"
        _, meta = validate_paginated(api.list_subscription_visits(sub_a["id"], ah))
        assert meta["total_count"] == 6, f"expected 6 visits, got {meta['total_count']}"

    def test_cancel_from_draft_branch_has_no_schedule(self, api):
        """
    PRD 3.2: "A `DRAFT` subscription may be cancelled outright (permitted only from `DRAFT`), which simply moves it to `CANCELLED` and increments its `version`."

        Design: Difficulty/non_linear_state_machine/subscription_branching_draft_to_active_or_cancelled
        """
        holder, _, sub_b = self._two_draft_subs()
        ah = make_account_holder_headers(holder["id"])
        cancelled = validate_success(api.cancel_subscription(sub_b["id"], ah))
        assert cancelled["status"] == "CANCELLED"
        _, meta = validate_paginated(api.list_subscription_visits(sub_b["id"], ah))
        assert meta["total_count"] == 0, f"expected 0 visits, got {meta['total_count']}"


def test_new_subscription_starts_in_draft(api):
    """
    PRD 3.2: "It is created in `DRAFT` status with the `property_id` it services, the `service_plan_id` governing cadence and pricing, a `billing_mode` of either `PER_VISIT` or `SEASONAL`, an inclusive `season_start_date` and inclusive `season_end_date` (each a `YYYY-MM-DD` calendar date), and an `auto_renew` flag that defaults to true."

    Design: Corner/state_machines/subscription_new_starts_in_draft
    """
    plan = create_service_plan()
    holder = create_account_holder()
    prop = create_property(holder["id"], service_region_code="NE01")
    add_zone(prop, holder["id"], zone_type="TURF", area_sqft=4000)
    ah = make_account_holder_headers(holder["id"])
    sub = validate_success(api.create_subscription(
        {"property_id": prop["id"], "service_plan_id": plan["id"], "billing_mode": "PER_VISIT",
         "season_start_date": "2026-05-01", "season_end_date": "2026-08-31", "auto_renew": False}, ah),
        expected_status=201)
    assert sub["status"] == "DRAFT"


def test_activate_already_active_returns_invalid_state(api):
    """
    PRD 3.2: "An account holder activates a `DRAFT` subscription, which is permitted only when the subscription is still `DRAFT`, the owning property has at least one treatment zone in `ACTIVE` status, and the `season_start_date` is on or before the `season_end_date`; a violation of the state precondition surfaces as `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_subscription_returns_invalid_state
    """
    ctx = create_active_subscription(region="NE01")
    ah = make_account_holder_headers(ctx["holder"]["id"])
    validate_error(api.activate_subscription(ctx["sub"]["id"], ah), ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_terminal_cancelled_returns_invalid_state(api):
    """
    PRD 3.2: "A `DRAFT` subscription may be cancelled outright (permitted only from `DRAFT`), which simply moves it to `CANCELLED` and increments its `version`."
    PRD 3.2: "The subscription's lifecycle states are `DRAFT`, `ACTIVE`, `OFF_SEASON`, `RENEWED`, and `CANCELLED`; `CANCELLED` is terminal."

    Design: Corner/state_machines/cancel_terminal_cancelled_subscription_returns_invalid_state
    """
    plan = create_service_plan()
    holder = create_account_holder()
    prop = create_property(holder["id"], service_region_code="NE01")
    add_zone(prop, holder["id"], zone_type="TURF", area_sqft=4000)
    sub = create_subscription(prop["id"], plan["id"], holder["id"], billing_mode="PER_VISIT")
    ah = make_account_holder_headers(holder["id"])
    validate_success(api.cancel_subscription(sub["id"], ah))
    validate_error(api.cancel_subscription(sub["id"], ah), ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_recurring_visit_bumps_visits_completed_count(api):
    """
    PRD 3.4: "Completion stamps the visit's `completed_at_date` with the logical current date, recomputes the owning subscription's `visits_completed_count`, and increments the visit's `version`."

    Design: Corner/state_machines/complete_recurring_visit_bubbles_visits_completed_count
    """
    ctx = create_active_subscription(region="NE01")
    crew = create_crew(home_region_code="NE01")
    set_clock("2026-05-01T08:00:00Z")
    rec = list_recurring_visits(ctx["sub"]["id"])[0]
    route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
    dispatch_visit(route["id"], rec["id"], route["version"])
    log_application(rec["id"], ctx["zones"][0]["id"], crew["id"])
    completed = complete_visit(rec["id"], crew["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["completed_at_date"] == "2026-05-01"
    ah = make_account_holder_headers(ctx["holder"]["id"])
    sub = get_success_data(api.get_subscription(ctx["sub"]["id"], ah))
    assert sub["visits_completed_count"] == 1, f"got {sub['visits_completed_count']}"


def test_close_retreat_completes_guarantee_loop(api):
    """
    PRD 3.5: "Once the child re-treat visit reaches `COMPLETED`, a dispatcher closes the guarantee loop on the parent, transitioning it `RETREAT_SCHEDULED → COMPLETED`. This close is permitted only when the parent is `RETREAT_SCHEDULED` and the child re-treat visit (the one whose `parent_visit_id` equals this parent) is itself `COMPLETED`; it increments the parent's `version`."
    PRD 3.5: "The side effect is the creation of a new `RETREAT` visit under the same subscription: it begins in `SCHEDULED` status, with `visit_kind` of `RETREAT`, its `scheduled_date` set to the `retreat_date`, its `parent_visit_id` pointing back at the requesting visit, and a `sequence_index` of 0."

    Design: Corner/state_machines/close_retreat_completes_guarantee_loop
    """
    ctx = create_active_subscription(region="NE01")
    crew = create_crew(home_region_code="NE01")
    set_clock("2026-05-01T08:00:00Z")
    rec = list_recurring_visits(ctx["sub"]["id"])[0]
    r1 = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
    dispatch_visit(r1["id"], rec["id"], r1["version"])
    log_application(rec["id"], ctx["zones"][0]["id"], crew["id"])
    complete_visit(rec["id"], crew["id"])
    ah = make_account_holder_headers(ctx["holder"]["id"])
    validate_success(api.request_retreat(rec["id"], ah))
    validate_success(api.schedule_retreat(rec["id"], {"retreat_date": "2026-05-04"}, DISPATCHER))
    set_clock("2026-05-04T08:00:00Z")
    children, _ = validate_paginated(api.list_visits(DISPATCHER, params={"parent_visit_id": rec["id"]}))
    child = children[0]
    assert child["parent_visit_id"] == rec["id"]
    assert child["visit_kind"] == "RETREAT"
    r2 = create_route(crew["id"], region="NE01", route_date="2026-05-04")
    dispatch_visit(r2["id"], child["id"], r2["version"])
    log_application(child["id"], ctx["zones"][0]["id"], crew["id"])
    complete_visit(child["id"], crew["id"])
    parent = validate_success(api.close_retreat(rec["id"], DISPATCHER))
    assert parent["status"] == "COMPLETED", f"got {parent['status']}"


def test_cancel_recurring_visit_directly_returns_invalid_state(api):
    """
    PRD 3.4: "A special-event visit is the only kind a customer may cancel individually: an account holder may cancel a `SCHEDULED` visit, transitioning it `SCHEDULED → CANCELLED`, only when its `visit_kind` is `SPECIAL_EVENT` (recurring visits are resolved en masse through subscription cancel or off-season)."

    Design: Corner/state_machines/cancel_recurring_visit_directly_returns_invalid_state
    """
    ctx = create_active_subscription(region="NE01")
    ah = make_account_holder_headers(ctx["holder"]["id"])
    rec = list_recurring_visits(ctx["sub"]["id"])[0]
    validate_error(api.cancel_visit(rec["id"], ah), ApiErrorId.ERR_INVALID_STATE.value)
    assert get_success_data(api.get_visit(rec["id"], ah))["status"] == "SCHEDULED"


def test_close_route_with_dispatched_visit_returns_route_not_empty(api):
    """
    PRD 3.8: "A dispatcher closes a `LOCKED` route, transitioning it `LOCKED → CLOSED`, only when every visit assigned to the route is in `COMPLETED` or `SKIPPED` status. A close attempt while a route still has a `DISPATCHED` visit open is rejected with `ERR_ROUTE_NOT_EMPTY`;"

    Design: Corner/state_machines/close_route_with_dispatched_visit_returns_route_not_empty
    """
    ctx = create_active_subscription(region="NE01")
    crew = create_crew(home_region_code="NE01")
    rec = list_recurring_visits(ctx["sub"]["id"])[0]
    route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
    dispatch_visit(route["id"], rec["id"], route["version"])
    validate_success(api.lock_route(route["id"], DISPATCHER))
    validate_error(api.close_route(route["id"], DISPATCHER), ApiErrorId.ERR_ROUTE_NOT_EMPTY.value)
    assert get_success_data(api.get_crew_route(route["id"], DISPATCHER))["status"] == "LOCKED"


def test_confirm_renewal_activates_successor(api):
    """
    PRD 3.9: "An account holder confirms renewal on an `OFF_SEASON` subscription, transitioning it `OFF_SEASON → RENEWED`. This is permitted only when the subscription is `OFF_SEASON`, its `renewed_into_subscription_id` is not null, and the referenced successor subscription is still in `DRAFT` status. Confirming activates the successor — the successor moves from `DRAFT` to `ACTIVE` and generates its own recurring schedule exactly as a fresh activation would — and increments the confirming subscription's `version`."

    Design: Corner/state_machines/confirm_renewal_activates_successor
    """
    ctx = create_active_subscription(region="NE01", season_start="2026-05-01", season_end="2026-05-22", auto_renew=True)
    ah = make_account_holder_headers(ctx["holder"]["id"])
    set_clock("2026-05-23T00:00:00Z")
    sub = get_success_data(api.get_subscription(ctx["sub"]["id"], ah))
    successor_id = sub["renewed_into_subscription_id"]
    assert successor_id is not None
    confirmed = validate_success(api.confirm_renewal(ctx["sub"]["id"], ah))
    assert confirmed["status"] == "RENEWED"
    successor = get_success_data(api.get_subscription(successor_id, ah))
    assert successor["status"] == "ACTIVE", f"got {successor['status']}"


def test_complete_without_application_log_returns_no_application_logged(api):
    """
    PRD 3.4: "A completion attempt with no application logs recorded is rejected with `ERR_NO_APPLICATION_LOGGED`."

    Design: Corner/state_machines/error_no_application_logged_blocks_complete
    """
    ctx = create_active_subscription(region="NE01")
    crew = create_crew(home_region_code="NE01")
    rec = list_recurring_visits(ctx["sub"]["id"])[0]
    route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
    dispatch_visit(route["id"], rec["id"], route["version"])
    validate_error(api.complete_visit(rec["id"], make_crew_tech_headers(crew["id"])), ApiErrorId.ERR_NO_APPLICATION_LOGGED.value)

"""Re-treat guarantee window and special-event scheduling tests.

Covers the Difficulty retreat-guarantee inclusive-boundary instance plus corner
guarantee-expired and special-event validations.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_account_holder_headers,
    create_active_subscription, list_recurring_visits, create_crew,
    create_route, dispatch_visit, log_application, complete_visit, set_clock,
    create_service_plan, create_account_holder, create_property, add_zone, create_subscription,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _complete_second_recurring_at_0522(guarantee_days=7):
    ctx = create_active_subscription(region="NE01", plan_overrides={"retreat_guarantee_days": guarantee_days})
    crew = create_crew(home_region_code="NE01")
    set_clock("2026-05-22T08:00:00Z")
    v2 = list_recurring_visits(ctx["sub"]["id"])[1]
    route = create_route(crew["id"], region="NE01", route_date=v2["scheduled_date"])
    dispatch_visit(route["id"], v2["id"], route["version"])
    log_application(v2["id"], ctx["zones"][0]["id"], crew["id"])
    completed = complete_visit(v2["id"], crew["id"])
    return ctx, crew, completed


class TestRetreatGuaranteeInclusiveBoundary:
    """Guarantee window uses <= (inclusive)."""

    def test_request_retreat_on_deadline_succeeds(self, api):
        """
    PRD 3.5: "The guarantee is claimable only within a window measured in whole calendar days: it is open if and only if the logical current date is on or before the completed visit's `completed_at_date` plus the plan's `retreat_guarantee_days`. The boundary is inclusive — a request on exactly the deadline date is still open, while the day after the deadline is closed."

        Design: Difficulty/boundary_precision_check/retreat_guarantee_window_inclusive_boundary
        """
        ctx, crew, completed = _complete_second_recurring_at_0522(guarantee_days=7)
        assert completed["completed_at_date"] == "2026-05-22"
        ah = make_account_holder_headers(ctx["holder"]["id"])
        set_clock("2026-05-29T08:00:00Z")
        result = validate_success(api.request_retreat(completed["id"], ah))
        assert result["status"] == "RETREAT_REQUESTED", f"got {result['status']}"

    def test_request_retreat_one_day_past_deadline_rejected(self, api):
        """
    PRD 3.5: "A request after the window has closed is rejected with `ERR_GUARANTEE_EXPIRED`; a second request once a re-treat already exists for the visit is rejected with `ERR_RETREAT_ALREADY_EXISTS`."

        Design: Difficulty/boundary_precision_check/retreat_guarantee_window_inclusive_boundary
        """
        ctx, crew, completed = _complete_second_recurring_at_0522(guarantee_days=7)
        ah = make_account_holder_headers(ctx["holder"]["id"])
        set_clock("2026-05-30T08:00:00Z")
        validate_error(api.request_retreat(completed["id"], ah), ApiErrorId.ERR_GUARANTEE_EXPIRED.value)


def test_guarantee_expired_one_day_past_deadline(api):
    """
    PRD 3.5: "A request after the window has closed is rejected with `ERR_GUARANTEE_EXPIRED`; a second request once a re-treat already exists for the visit is rejected with `ERR_RETREAT_ALREADY_EXISTS`."

    Design: Corner/validations/guarantee_expired_one_day_past_deadline
    """
    ctx, crew, completed = _complete_second_recurring_at_0522(guarantee_days=7)
    ah = make_account_holder_headers(ctx["holder"]["id"])
    set_clock("2026-05-30T08:00:00Z")
    validate_error(api.request_retreat(completed["id"], ah), ApiErrorId.ERR_GUARANTEE_EXPIRED.value)


def test_special_event_date_after_season_end_returns_date_out_of_season(api):
    """
    PRD 3.4: "The request supplies the `scheduled_date` for the new visit, which must be strictly after the logical current date and on or before the subscription's `season_end_date`, or the request is rejected with `ERR_DATE_OUT_OF_SEASON`."

    Design: Corner/validations/special_event_date_after_season_end_returns_date_out_of_season
    """
    ctx = create_active_subscription(region="NE01", season_start="2026-05-01", season_end="2026-08-31")
    ah = make_account_holder_headers(ctx["holder"]["id"])
    validate_error(api.schedule_special_event(ctx["sub"]["id"], {"scheduled_date": "2026-09-15"}, ah), ApiErrorId.ERR_DATE_OUT_OF_SEASON.value)


def test_special_event_on_draft_subscription_returns_subscription_not_active(api):
    """
    PRD 3.4: "A one-time **special-event** treatment can be scheduled by an account holder against a subscription, but only while that subscription is `ACTIVE`; otherwise the request is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Corner/validations/special_event_on_draft_subscription_returns_subscription_not_active
    """
    plan = create_service_plan()
    holder = create_account_holder()
    prop = create_property(holder["id"], service_region_code="NE01")
    add_zone(prop, holder["id"], zone_type="TURF", area_sqft=4000)
    sub = create_subscription(prop["id"], plan["id"], holder["id"], billing_mode="PER_VISIT")
    ah = make_account_holder_headers(holder["id"])
    validate_error(api.schedule_special_event(sub["id"], {"scheduled_date": "2026-06-01"}, ah), ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value)

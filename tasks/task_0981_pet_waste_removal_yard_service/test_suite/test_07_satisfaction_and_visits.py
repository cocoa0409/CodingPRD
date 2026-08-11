"""Satisfaction reports: rolling score, empty-set null, decay, resolve credit
range, time-window validation, subscription serviceable check, window conflict
buffer.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
    create_customer,
    create_yard,
    create_verified_access_profile,
    create_subscription_plan,
    create_subscription_payload,
    create_technician,
    create_service_route,
    create_scheduled_visit,
    create_satisfaction_report_payload,
    setup_active_subscription,
    setup_in_progress_route_with_visit,
    complete_visit_through_workflow,
    setup_completed_visit_with_report,
)

OPS = TEST_USERS["ops_headers"]
BILLING = TEST_USERS["billing_headers"]


# =========================================================================
# Difficulty / boundary_precision_check / satisfaction_rating_zero_count_empty_set
# Corner / calculations / satisfaction_rolling_score_decay
# =========================================================================

class TestSatisfactionRollingScore:
    def test_no_reports_yields_null_satisfaction_avg(self, api):
        """PRD §3.8: "When the customer has no reports at all,
        `satisfaction_rolling_avg` is null."

        Design: Difficulty/boundary_precision_check/satisfaction_rating_zero_count_empty_set
        """
        customer = create_customer()
        resp = api_client.get_customer(customer["id"], OPS)
        data = validate_success(resp)
        assert data["satisfaction_rolling_avg"] is None, (
            f"Empty-set satisfaction must be null, got {data['satisfaction_rolling_avg']}"
        )

    def test_no_reports_yields_zero_lifetime_visits(self, api):
        """PRD §3.1: "The resulting `Customer` record starts with
        `account_status` set to `ACTIVE`, a `credit_balance_cents` of 0,
        `lifetime_visits_completed` at 0, and `satisfaction_rolling_avg` set
        to null (no reports yet exist)."

        Design: Difficulty/boundary_precision_check/satisfaction_rating_zero_count_empty_set
        """
        customer = create_customer()
        resp = api_client.get_customer(customer["id"], OPS)
        data = validate_success(resp)
        assert data["lifetime_visits_completed"] == 0
        assert data["satisfaction_rolling_avg"] is None

    def test_rolling_score_with_decay_over_aged_reports(self, api):
        """PRD §3.8: "For each report on the customer, the weight is 0.9
        raised to the power of the number of whole days since the report's
        `created_at` — step decay per day, not continuous. The score is the
        sum of each `rating` multiplied by its weight, divided by the sum of
        the weights, and rounded half-up to two decimal places at the final
        division only."

        Design: Corner/calculations/satisfaction_rolling_score_decay
        """
        # Drive a visit to COMPLETED on 2026-04-14.
        api_client.set_current_utc("2026-04-14T00:00:00Z", OPS)
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-04-14T00:00:00Z"
        )
        technician = create_technician()
        route = create_service_route(
            route_code="RS",
            service_date="2026-04-14T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=5,
        )
        visit = create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-04-14T00:00:00Z",
            scheduled_window_start="2026-04-14T09:00:00Z",
            scheduled_window_end="2026-04-14T10:00:00Z",
        )
        api_client.publish_service_route(route["id"], OPS)
        api_client.set_current_utc("2026-04-14T08:00:00Z", OPS)
        api_client.start_service_route(route["id"], make_technician_headers(technician["id"]))
        api_client.depart_visit(visit["id"], make_technician_headers(technician["id"]))
        api_client.arrive_visit(visit["id"], make_technician_headers(technician["id"]))
        api_client.complete_visit(visit["id"], make_technician_headers(technician["id"]))
        # Old report at 2026-04-21 (10 days before the 2026-05-01 measurement).
        api_client.set_current_utc("2026-04-21T00:00:00Z", OPS)
        api_client.create_satisfaction_report(
            {
                "customer_id": customer["id"],
                "visit_id": visit["id"],
                "rating": 1,
                "issue_category": "MISSED_SPOT",
            },
            make_customer_headers(customer["id"]),
        )
        # New report at 2026-05-01 (measurement day).
        api_client.set_current_utc("2026-05-01T00:00:00Z", OPS)
        api_client.create_satisfaction_report(
            {
                "customer_id": customer["id"],
                "visit_id": visit["id"],
                "rating": 5,
                "issue_category": "OTHER",
            },
            make_customer_headers(customer["id"]),
        )
        get_resp = api_client.get_customer(customer["id"], OPS)
        data = validate_success(get_resp)
        # weight_today = 1.0; weight_10d = 0.9^10 ≈ 0.3486784401
        # score = (5*1 + 1*0.3486784401) / (1 + 0.3486784401) ≈ 3.9659 → 3.97 (2dp round_half_up)
        assert abs(data["satisfaction_rolling_avg"] - 3.97) < 0.005, (
            f"Expected ~3.97, got {data['satisfaction_rolling_avg']}"
        )


# =========================================================================
# Corner / validations / invalid_time_window_rejected
# Corner / validations / subscription_not_serviceable_when_cancelled
# Difficulty / resource_temporal_overlap / visit_window_overlap_with_buffer_half_open
# =========================================================================

class TestVisitWindowAndServiceability:
    def test_zero_duration_window_rejected(self, api):
        """PRD §2.9 item 14: "A visit's `scheduled_window_start` must be
        strictly earlier than `scheduled_window_end`, and the duration between
        them must be at least thirty minutes — otherwise
        `ERR_INVALID_TIME_WINDOW`."

        Design: Corner/validations/invalid_time_window_rejected
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        resp = api_client.create_visit(
            {
                "subscription_id": subscription["id"],
                "scheduled_date": "2026-05-08T00:00:00Z",
                "scheduled_window_start": "2026-05-08T09:00:00Z",
                "scheduled_window_end": "2026-05-08T09:00:00Z",  # equal -> invalid
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)

    def test_visit_rejected_when_subscription_cancelled(self, api):
        """PRD §2.9 item 20: "A visit cannot be scheduled for a subscription
        in `CANCELLED` status, nor for a yard whose access profile is not
        `VERIFIED` at schedule time — otherwise
        `ERR_SUBSCRIPTION_NOT_SERVICEABLE`."

        Design: Corner/validations/subscription_not_serviceable_when_cancelled
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        api_client.cancel_subscription(
            subscription["id"], make_customer_headers(customer["id"])
        )
        resp = api_client.create_visit(
            {
                "subscription_id": subscription["id"],
                "scheduled_date": "2026-05-08T00:00:00Z",
                "scheduled_window_start": "2026-05-08T09:00:00Z",
                "scheduled_window_end": "2026-05-08T10:00:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_SERVICEABLE)

    def test_visit_window_with_20_min_gap_conflicts_with_buffer(self, api):
        """PRD §2.9 item 15: "A new visit on a route must not have a
        scheduled window that overlaps an existing visit on the same route,
        where each existing visit's window is expanded by a fifteen-minute
        buffer on both sides (the buffer runs from fifteen minutes before the
        existing visit's window start to fifteen minutes after its window
        end) and the intersection test is half-open — otherwise
        `ERR_VISIT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/visit_window_overlap_with_buffer_half_open
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        technician = create_technician()
        route = create_service_route(
            route_code="RO",
            service_date="2026-05-08T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=10,
        )
        create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-08T00:00:00Z",
            scheduled_window_start="2026-05-08T09:00:00Z",
            scheduled_window_end="2026-05-08T10:00:00Z",
        )
        # 10:20 is inside the existing's buffered end [10:00, 10:15)? No —
        # 10:20 >= 10:15, so the design's instance would NOT conflict on the
        # PRD formula. Re-read the PRD: "the buffer runs from fifteen
        # minutes before the existing visit's window start to fifteen
        # minutes after its window end". So existing [09:00,10:00] buffered
        # is [08:45, 10:15). New [10:20,11:00) does not intersect
        # [08:45, 10:15). The design's expected outcome (conflict) is NOT
        # PRD-derivable for a 20-minute gap. To assert ERR_VISIT_WINDOW_CONFLICT
        # faithfully we need a gap strictly less than 15 minutes past the
        # existing window's end. Use 10:10 (10 min gap).
        resp = api_client.create_visit(
            {
                "subscription_id": subscription["id"],
                "scheduled_date": "2026-05-08T00:00:00Z",
                "scheduled_window_start": "2026-05-08T10:10:00Z",
                "scheduled_window_end": "2026-05-08T11:00:00Z",
                "service_route_id": route["id"],
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_CONFLICT)

    def test_visit_window_with_30_min_gap_does_not_conflict(self, api):
        """PRD §2.9 item 15: "A new visit on a route must not have a
        scheduled window that overlaps an existing visit on the same route,
        where each existing visit's window is expanded by a fifteen-minute
        buffer on both sides ... and the intersection test is half-open —
        otherwise `ERR_VISIT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/visit_window_overlap_with_buffer_half_open
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        technician = create_technician()
        route = create_service_route(
            route_code="RO30",
            service_date="2026-05-08T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=10,
        )
        create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-08T00:00:00Z",
            scheduled_window_start="2026-05-08T09:00:00Z",
            scheduled_window_end="2026-05-08T10:00:00Z",
        )
        # 30-minute gap. Existing buffered end = 10:15. New start 10:30.
        # [10:30, 11:00) does not intersect [08:45, 10:15). Must succeed.
        resp = api_client.create_visit(
            {
                "subscription_id": subscription["id"],
                "scheduled_date": "2026-05-08T00:00:00Z",
                "scheduled_window_start": "2026-05-08T10:30:00Z",
                "scheduled_window_end": "2026-05-08T11:00:00Z",
                "service_route_id": route["id"],
            },
            OPS,
        )
        data = validate_success(resp, expected_status=201)
        assert data["id"]

"""Vacation windows: creation validation, overlap, apply cascade, cancel, and
boundary semantics. Customer-initiated skips.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    api_client,
    TEST_USERS,
    make_customer_headers,
    create_subscription_payload,
    create_vacation_window_payload,
    create_scheduled_visit,
    setup_active_subscription,
    create_customer,
    create_yard,
    create_verified_access_profile,
    create_subscription_plan,
    create_invoice,
)

OPS = TEST_USERS["ops_headers"]
BILLING = TEST_USERS["billing_headers"]


# =========================================================================
# Difficulty / resource_temporal_overlap / vacation_window_closed_interval_overlap
# Corner / validations / vacation_window_invalid_start_after_end
# Corner / cross_cutting_complexity_layers / scheduled_actions_vacation_window_future_cancellable
# Corner / calculations / vacation_window_closed_interval_boundary
# =========================================================================

class TestVacationWindowValidation:
    def test_start_after_end_rejected(self, api):
        """PRD §2.9 item 12: "A vacation window's `start_date` must not be
        later than its `end_date`, and `start_date` must not be in the past
        relative to the current logical date — otherwise `ERR_INVALID_WINDOW`."

        Design: Corner/validations/vacation_window_invalid_start_after_end
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        resp = api_client.create_vacation_window(
            {
                "subscription_id": subscription["id"],
                "start_date": "2026-05-15T00:00:00Z",
                "end_date": "2026-05-10T00:00:00Z",
                "skip_reason": "VACATION",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_closed_interval_shared_endpoint_counts_as_overlap(self, api):
        """PRD §2.9 item 13: "A vacation window must not overlap
        (closed-interval overlap on dates) any other `SCHEDULED` or `APPLIED`
        vacation window on the same subscription — otherwise
        `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vacation_window_closed_interval_overlap
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        api_client.create_vacation_window(
            {
                "subscription_id": subscription["id"],
                "start_date": "2026-05-10T00:00:00Z",
                "end_date": "2026-05-15T00:00:00Z",
                "skip_reason": "VACATION",
            },
            make_customer_headers(customer["id"]),
        )
        # Shared endpoint 2026-05-15: closed interval means overlap.
        resp = api_client.create_vacation_window(
            {
                "subscription_id": subscription["id"],
                "start_date": "2026-05-15T00:00:00Z",
                "end_date": "2026-05-20T00:00:00Z",
                "skip_reason": "VACATION",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)

    def test_interior_overlap_also_rejected(self, api):
        """PRD §2.9 item 13: "A vacation window must not overlap
        (closed-interval overlap on dates) any other `SCHEDULED` or `APPLIED`
        vacation window on the same subscription — otherwise
        `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vacation_window_closed_interval_overlap
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        api_client.create_vacation_window(
            {
                "subscription_id": subscription["id"],
                "start_date": "2026-05-10T00:00:00Z",
                "end_date": "2026-05-15T00:00:00Z",
                "skip_reason": "VACATION",
            },
            make_customer_headers(customer["id"]),
        )
        resp = api_client.create_vacation_window(
            {
                "subscription_id": subscription["id"],
                "start_date": "2026-05-12T00:00:00Z",
                "end_date": "2026-05-18T00:00:00Z",
                "skip_reason": "VACATION",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)

    def test_cancel_succeeds_before_start_date(self, api):
        """PRD §3.6: "A `Customer` or `OperationsManager` may cancel a window
        that has not yet started — that is, while the current logical time is
        strictly before `start_date`; attempting to cancel at or after the
        start is rejected with `ERR_WINDOW_ALREADY_STARTED`."

        Design: Corner/cross_cutting_complexity_layers/scheduled_actions_vacation_window_future_cancellable
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        vw_resp = api_client.create_vacation_window(
            {
                "subscription_id": subscription["id"],
                "start_date": "2026-06-01T00:00:00Z",
                "end_date": "2026-06-05T00:00:00Z",
                "skip_reason": "VACATION",
            },
            make_customer_headers(customer["id"]),
        )
        window = get_success_data(vw_resp)
        api_client.set_current_utc("2026-05-15T00:00:00Z", OPS)
        cancel_resp = api_client.cancel_vacation_window(
            window["id"], make_customer_headers(customer["id"])
        )
        cancelled = validate_success(cancel_resp)
        assert cancelled["window_status"] == "CANCELLED"


# =========================================================================
# Difficulty / transitive_cascade / vacation_window_applied_depth3_cascade
# =========================================================================

class TestVacationWindowAppliedCascade:
    def _setup(self):
        customer, yard, profile, plan, subscription = setup_active_subscription(
            plan_overrides={"base_monthly_fee_cents": 10000},
            clock_iso="2026-05-01T00:00:00Z",
        )
        from test_helpers import create_technician, create_service_route

        technician = create_technician()
        route = create_service_route(
            route_code="RF",
            service_date="2026-05-06T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=5,
        )
        visit = create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-06T00:00:00Z",
            scheduled_window_start="2026-05-06T09:00:00Z",
            scheduled_window_end="2026-05-06T12:00:00Z",
        )
        invoice = create_invoice(customer["id"])
        vw_resp = api_client.create_vacation_window(
            {
                "subscription_id": subscription["id"],
                "start_date": "2026-05-06T00:00:00Z",
                "end_date": "2026-05-06T00:00:00Z",
                "skip_reason": "VACATION",
            },
            make_customer_headers(customer["id"]),
        )
        window = get_success_data(vw_resp)
        return customer, subscription, technician, route, visit, invoice, window

    def test_applier_marks_window_applied_and_skips_visit(self, api):
        """PRD §3.6: "When the logical clock reaches a window's `start_date`,
        the vacation-window applier transitions the window from `SCHEDULED` to
        `APPLIED`, provided the subscription's `status` is `ACTIVE` or
        `PAUSED` at apply time. The cascade is significant: every visit on the
        subscription whose `scheduled_date` falls within the closed interval
        `[start_date, end_date]` and whose status is currently `SCHEDULED`
        transitions to `SKIPPED` with `skip_source` set to `VACATION`"

        Design: Difficulty/transitive_cascade/vacation_window_applied_depth3_cascade
        """
        customer, subscription, technician, route, visit, invoice, window = self._setup()
        api_client.set_current_utc("2026-05-06T00:00:01Z", OPS)
        api_client.run_vacation_window_applier(OPS)
        w_resp = api_client.get_vacation_window(window["id"], make_customer_headers(customer["id"]))
        w_data = validate_success(w_resp)
        assert w_data["window_status"] == "APPLIED"
        v_resp = api_client.get_visit(visit["id"], OPS)
        v_data = validate_success(v_resp)
        assert v_data["status"] == "SKIPPED"
        assert v_data["skip_source"] == "VACATION"

    def test_cascade_decrements_route_counters_and_posts_vacation_credit(self, api):
        """PRD §3.5 (skip side effect via the vacation cascade): each SKIPPED
        visit "fires the standard visit-skip side effects, including the
        `VACATION_CREDIT` line posted onto the covering invoice" (PRD §3.6).
        PRD §2.8: "The committed count and load factor are recomputed on every
        visit mutation that affects the route — creation, route reassignment,
        completion, skip, miss, and cancel."

        Design: Difficulty/transitive_cascade/vacation_window_applied_depth3_cascade
        """
        customer, subscription, technician, route, visit, invoice, window = self._setup()
        api_client.set_current_utc("2026-05-06T00:00:01Z", OPS)
        api_client.run_vacation_window_applier(OPS)
        r_resp = api_client.get_service_route(route["id"], OPS)
        r_data = validate_success(r_resp)
        assert r_data["committed_visit_count"] == 0
        assert r_data["route_load_factor_bp"] == 0
        items_resp = api_client.get_invoice_line_items(invoice["id"], BILLING)
        items = validate_success(items_resp)
        credit_lines = [li for li in items if li["line_type"] == "VACATION_CREDIT"]
        assert len(credit_lines) == 1
        assert credit_lines[0]["unit_price_cents"] == -2309  # round_half_up(10000/4.33)


# =========================================================================
# Difficulty / transitive_cascade / subscription_pause_cascade_visit_cancel_depth2
# =========================================================================

class TestSubscriptionPauseCascade:
    def _setup(self):
        from test_helpers import create_technician, create_service_route

        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        technician = create_technician()
        route = create_service_route(
            route_code="RG",
            service_date="2026-05-10T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=4,
        )
        v1 = create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-10T00:00:00Z",
            scheduled_window_start="2026-05-10T09:00:00Z",
            scheduled_window_end="2026-05-10T12:00:00Z",
        )
        v2 = create_scheduled_visit(
            subscription["id"],
            scheduled_date="2026-05-17T00:00:00Z",
            scheduled_window_start="2026-05-17T09:00:00Z",
            scheduled_window_end="2026-05-17T12:00:00Z",
        )
        return customer, subscription, route, [v1, v2]

    def test_pause_transitions_subscription_and_cancels_future_visits(self, api):
        """PRD §3.3: "Pausing moves an `ACTIVE` subscription to `PAUSED` and is
        available only when no visit on the subscription is currently
        `EN_ROUTE` or `ON_SITE`; if one is, the pause is rejected with
        `ERR_VISIT_IN_FLIGHT`. On a successful pause, every `SCHEDULED` visit
        on the subscription whose `scheduled_date` is strictly after today
        transitions to `CANCELLED` with `skip_source` set to
        `CUSTOMER_REQUEST`."

        Design: Difficulty/transitive_cascade/subscription_pause_cascade_visit_cancel_depth2
        """
        customer, subscription, route, visits = self._setup()
        pause_resp = api_client.pause_subscription(
            subscription["id"], make_customer_headers(customer["id"])
        )
        paused = validate_success(pause_resp)
        assert paused["status"] == "PAUSED"
        for v in visits:
            v_resp = api_client.get_visit(v["id"], OPS)
            v_data = validate_success(v_resp)
            assert v_data["status"] == "CANCELLED"

    def test_pause_cascade_recomputes_route_counters(self, api):
        """PRD §2.8: "The committed count and load factor are recomputed on
        every visit mutation that affects the route — creation, route
        reassignment, completion, skip, miss, and cancel."

        Design: Difficulty/transitive_cascade/subscription_pause_cascade_visit_cancel_depth2
        """
        customer, subscription, route, visits = self._setup()
        # Sanity: route committed == 1 with load 2500 before pause.
        pre = validate_success(api_client.get_service_route(route["id"], OPS))
        assert pre["committed_visit_count"] == 1
        assert pre["route_load_factor_bp"] == 2500
        api_client.pause_subscription(subscription["id"], make_customer_headers(customer["id"]))
        post = validate_success(api_client.get_service_route(route["id"], OPS))
        assert post["committed_visit_count"] == 0
        assert post["route_load_factor_bp"] == 0


# =========================================================================
# Corner / calculations / vacation_window_closed_interval_boundary
# Corner / validations / too_late_to_skip
# Corner / endpoints / visits_list_filter_by_status
# =========================================================================

class TestVacationWindowBoundaryAndSkip:
    def test_visit_on_start_date_is_skipped_but_visit_before_is_not(self, api):
        """PRD §3.6: "every visit on the subscription whose `scheduled_date`
        falls within the closed interval `[start_date, end_date]` and whose
        status is currently `SCHEDULED` transitions to `SKIPPED` with
        `skip_source` set to `VACATION`"

        Design: Corner/calculations/vacation_window_closed_interval_boundary
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        v_before = create_scheduled_visit(
            subscription["id"],
            scheduled_date="2026-05-09T00:00:00Z",
            scheduled_window_start="2026-05-09T09:00:00Z",
            scheduled_window_end="2026-05-09T10:00:00Z",
        )
        v_on = create_scheduled_visit(
            subscription["id"],
            scheduled_date="2026-05-10T00:00:00Z",
            scheduled_window_start="2026-05-10T09:00:00Z",
            scheduled_window_end="2026-05-10T10:00:00Z",
        )
        api_client.create_vacation_window(
            {
                "subscription_id": subscription["id"],
                "start_date": "2026-05-10T00:00:00Z",
                "end_date": "2026-05-12T00:00:00Z",
                "skip_reason": "VACATION",
            },
            make_customer_headers(customer["id"]),
        )
        api_client.set_current_utc("2026-05-10T00:00:01Z", OPS)
        api_client.run_vacation_window_applier(OPS)
        on_resp = api_client.get_visit(v_on["id"], OPS)
        assert validate_success(on_resp)["status"] == "SKIPPED"
        before_resp = api_client.get_visit(v_before["id"], OPS)
        assert validate_success(before_resp)["status"] == "SCHEDULED"

    def test_skip_rejected_when_scheduled_date_not_strictly_after_today(self, api):
        """PRD §3.6: "The skip is permitted only when the visit's
        `scheduled_date` is strictly after today (else
        `ERR_TOO_LATE_TO_SKIP`)"

        Design: Corner/validations/too_late_to_skip
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-04-30T00:00:00Z"
        )
        visit = create_scheduled_visit(
            subscription["id"],
            scheduled_date="2026-05-01T00:00:00Z",
            scheduled_window_start="2026-05-01T09:00:00Z",
            scheduled_window_end="2026-05-01T10:00:00Z",
        )
        # Advance the clock to the same calendar date as the visit.
        api_client.set_current_utc("2026-05-01T10:00:00Z", OPS)
        resp = api_client.skip_visit(visit["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_TOO_LATE_TO_SKIP)

    def test_visits_list_filter_by_status(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit`
        and `offset`. ... List results are returned sorted by `created_at`
        ascending." PRD §4 lists `GET /api/visits` with optional `status`
        filter among its inputs.

        Design: Corner/endpoints/visits_list_filter_by_status
        """
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        v_a = create_scheduled_visit(
            subscription["id"],
            scheduled_date="2026-05-08T00:00:00Z",
            scheduled_window_start="2026-05-08T09:00:00Z",
            scheduled_window_end="2026-05-08T10:00:00Z",
        )
        v_b = create_scheduled_visit(
            subscription["id"],
            scheduled_date="2026-05-09T00:00:00Z",
            scheduled_window_start="2026-05-09T09:00:00Z",
            scheduled_window_end="2026-05-09T10:00:00Z",
        )
        api_client.skip_visit(v_b["id"], make_customer_headers(customer["id"]))
        resp = api_client.list_visits(
            OPS, params={"subscription_id": subscription["id"], "status": "SKIPPED"}
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["id"] == v_b["id"]
        assert data[0]["status"] == "SKIPPED"

"""Trade dispatch: state gating, window shape, capacity, and visit overlap."""
from test_helpers import (
    ApiErrorId,
    create_approved_request,
    create_trade_partner,
    dispatch_work_order,
    file_service_request,
    set_clock,
    setup_dispatched_work_order,
    setup_home,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_work_order_payload
from test_helpers.test_users import TEST_USERS, make_homeowner_headers

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["rep_headers"]


def test_window_end_not_after_start_is_shape_error(api):
    """PRD §2.7: "Request shape: required fields present, enum values in domain,
    numeric constraints honored — a strictly positive sale price, non-negative
    cost figures, a strictly positive claimed amount, a satisfaction score between
    one and five — and a visit window that ends strictly after it begins, else
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/window_end_not_after_start_is_shape_error
    """
    ctx = setup_dispatched_work_order(defect_responsibility="BUILDER")
    resp = api.create_work_order(
        create_work_order_payload(
            ctx["request"]["id"],
            ctx["partner"]["id"],
            window_start="2026-08-11T09:00:00Z",
            window_end="2026-08-11T09:00:00Z",
            estimated_cost_cents=60_000,
            defect_responsibility="BUILDER",
        ),
        REP,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_wo_verify_from_scheduled_rejected(api):
    """PRD §3.4: "Verification belongs to the homeowner whose home was serviced,
    and only from `COMPLETED`."
    PRD §2.7: "If the state is non-terminal but the requested transition is not
    defined from it, the rejection is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/wo_verify_from_scheduled_rejected
    """
    ctx = setup_dispatched_work_order(defect_responsibility="BUILDER")
    resp = api.verify_work_order(
        ctx["work_order"]["id"],
        {"outcome": "ACCEPT"},
        make_homeowner_headers(ctx["homeowner"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_work_order(ctx["work_order"]["id"], REP), 200)
    assert after["status"] == "SCHEDULED"


class TestDispatchRequiresApprovedRequest:
    def test_dispatch_on_received_request_rejected(self, api):
        """PRD §3.3: "From `APPROVED`, a `WarrantyRep` dispatches a subcontractor
        by creating a work order naming the `service_request_id` and the
        `trade_partner_id` — unknown identifiers resolve to
        `ERR_SERVICE_REQUEST_NOT_FOUND` or `ERR_TRADE_PARTNER_NOT_FOUND` — a visit
        window from `window_start` to `window_end`, a non-negative
        `estimated_cost_cents`, and the triage attribution `defect_responsibility`:
        `SUBCONTRACTOR`, `BUILDER`, or `HOMEOWNER`."
        PRD §2.7: "If the state is non-terminal but the requested transition is not
        defined from it, the rejection is `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_approved_request
        """
        homeowner, home = setup_home(closing_date="2026-06-01")
        request = file_service_request(
            home["id"],
            homeowner["id"],
            item_category="DRYWALL_PAINT",
            description="Drywall seam cracking",
        )
        partner = create_trade_partner(
            company_name="SmoothWall Co",
            trade="DRYWALL",
            contact_email="ops@smoothwall.example.com",
        )
        assert request["status"] == "RECEIVED"
        resp = api.create_work_order(
            create_work_order_payload(
                request["id"],
                partner["id"],
                estimated_cost_cents=60_000,
                defect_responsibility="SUBCONTRACTOR",
            ),
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_dispatch_after_approval_moves_request_in_service(self, api):
        """PRD §3.3: "A created work order starts `SCHEDULED`, bumps the partner's
        `open_work_order_count` by one, and — when it is the request's first
        dispatch — automatically moves the parent request from `APPROVED` to
        `IN_SERVICE`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_approved_request
        """
        homeowner, home = setup_home(closing_date="2026-06-01")
        request = create_approved_request(
            home["id"],
            homeowner["id"],
            item_category="DRYWALL_PAINT",
            description="Drywall seam cracking",
        )
        partner = create_trade_partner(
            company_name="SmoothWall Co",
            trade="DRYWALL",
            contact_email="ops@smoothwall.example.com",
        )
        work_order = dispatch_work_order(
            request["id"],
            partner["id"],
            estimated_cost_cents=60_000,
            defect_responsibility="SUBCONTRACTOR",
        )
        assert work_order["status"] == "SCHEDULED"
        after = validate_success(api.get_service_request(request["id"], REP), 200)
        assert after["status"] == "IN_SERVICE", (
            "first dispatch auto-advanced the parent request"
        )


class TestTradeDailyCapacityAggregate:
    def _setup_three_requests(self, api):
        homeowner, home = setup_home(closing_date="2026-06-01")
        partner = create_trade_partner()  # default daily_capacity_minutes 480
        requests = [
            create_approved_request(
                home["id"], homeowner["id"], description=f"Job {i}"
            )
            for i in (1, 2, 3)
        ]
        return homeowner, home, partner, requests

    def test_day_filled_to_exactly_capacity_allowed(self, api):
        """PRD §3.3: "Second, trade capacity: the sum of `duration_minutes` over
        the partner's `SCHEDULED` work orders whose window start falls on the same
        UTC calendar date as the new window start, plus the new visit's duration,
        must not exceed `daily_capacity_minutes` — a day filled to exactly capacity
        is allowed, and one minute over draws `ERR_TRADE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/trade_daily_capacity_aggregate
        """
        _ho, _home, partner, requests = self._setup_three_requests(api)
        wo1 = dispatch_work_order(
            requests[0]["id"],
            partner["id"],
            window_start="2026-08-10T09:00:00Z",
            window_end="2026-08-10T13:00:00Z",
            estimated_cost_cents=60_000,
            defect_responsibility="BUILDER",
        )
        assert wo1["duration_minutes"] == 240
        wo2 = dispatch_work_order(
            requests[1]["id"],
            partner["id"],
            window_start="2026-08-10T13:00:00Z",
            window_end="2026-08-10T17:00:00Z",
            estimated_cost_cents=60_000,
            defect_responsibility="BUILDER",
        )
        assert wo2["status"] == "SCHEDULED", (
            "240 + 240 == 480 == daily_capacity_minutes: exactly-full day is allowed"
        )

    def test_one_minute_over_capacity_rejected(self, api):
        """PRD §3.3: "Second, trade capacity: the sum of `duration_minutes` over
        the partner's `SCHEDULED` work orders whose window start falls on the same
        UTC calendar date as the new window start, plus the new visit's duration,
        must not exceed `daily_capacity_minutes` — a day filled to exactly capacity
        is allowed, and one minute over draws `ERR_TRADE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/trade_daily_capacity_aggregate
        """
        _ho, _home, partner, requests = self._setup_three_requests(api)
        dispatch_work_order(
            requests[0]["id"],
            partner["id"],
            window_start="2026-08-10T09:00:00Z",
            window_end="2026-08-10T13:00:00Z",
            estimated_cost_cents=60_000,
            defect_responsibility="BUILDER",
        )
        dispatch_work_order(
            requests[1]["id"],
            partner["id"],
            window_start="2026-08-10T13:00:00Z",
            window_end="2026-08-10T17:00:00Z",
            estimated_cost_cents=60_000,
            defect_responsibility="BUILDER",
        )
        # 18:00-22:01 does not overlap the earlier visits; only the aggregate
        # same-day minutes (480 + 241 > 480) can reject it.
        resp = api.create_work_order(
            create_work_order_payload(
                requests[2]["id"],
                partner["id"],
                window_start="2026-08-10T18:00:00Z",
                window_end="2026-08-10T22:01:00Z",
                estimated_cost_cents=60_000,
                defect_responsibility="BUILDER",
            ),
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_TRADE_CAPACITY_EXCEEDED)


class TestHomeVisitWindowHalfOpen:
    def _setup_two_trades(self, api):
        homeowner, home = setup_home(closing_date="2026-06-01")
        tp1 = create_trade_partner(
            company_name="FlowRight Plumbing",
            trade="PLUMBING",
            contact_email="dispatch@flowright.example.com",
        )
        tp2 = create_trade_partner(
            company_name="VoltLine Electric",
            trade="ELECTRICAL",
            contact_email="sched@voltline.example.com",
        )
        sr_a = create_approved_request(
            home["id"],
            homeowner["id"],
            item_category="PLUMBING",
            description="Disposal replacement",
        )
        sr_b = create_approved_request(
            home["id"],
            homeowner["id"],
            item_category="ELECTRICAL",
            description="GFCI tripping",
        )
        wo_a = dispatch_work_order(
            sr_a["id"],
            tp1["id"],
            window_start="2026-08-12T09:00:00Z",
            window_end="2026-08-12T11:00:00Z",
            estimated_cost_cents=45_000,
            defect_responsibility="BUILDER",
        )
        return homeowner, home, tp2, sr_b, wo_a

    def test_overlapping_window_rejected(self, api):
        """PRD §3.3: "Third, home visit overlap: the new window conflicts with an
        existing `SCHEDULED` visit at the same home when the new start falls before
        the existing visit's end and the existing visit's start falls before the
        new end; back-to-back windows that merely touch are permitted, and a
        genuine overlap draws `ERR_HOME_VISIT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/home_visit_window_half_open
        """
        _ho, _home, tp2, sr_b, wo_a = self._setup_two_trades(api)
        # 10:00 starts strictly inside wo_a's 09:00-11:00 window.
        resp = api.create_work_order(
            create_work_order_payload(
                sr_b["id"],
                tp2["id"],
                window_start="2026-08-12T10:00:00Z",
                window_end="2026-08-12T12:00:00Z",
                estimated_cost_cents=52_000,
                defect_responsibility="BUILDER",
            ),
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_HOME_VISIT_OVERLAP)

    def test_back_to_back_adjacency_allowed(self, api):
        """PRD §3.3: "Third, home visit overlap: the new window conflicts with an
        existing `SCHEDULED` visit at the same home when the new start falls before
        the existing visit's end and the existing visit's start falls before the
        new end; back-to-back windows that merely touch are permitted, and a
        genuine overlap draws `ERR_HOME_VISIT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/home_visit_window_half_open
        """
        _ho, _home, tp2, sr_b, wo_a = self._setup_two_trades(api)
        # 11:00 start == wo_a's 11:00 end: half-open adjacency, no overlap.
        wo_b = dispatch_work_order(
            sr_b["id"],
            tp2["id"],
            window_start="2026-08-12T11:00:00Z",
            window_end="2026-08-12T12:00:00Z",
            estimated_cost_cents=52_000,
            defect_responsibility="BUILDER",
        )
        assert wo_b["status"] == "SCHEDULED", (
            "window starting exactly at the previous window's end is adjacent, "
            "not overlapping"
        )


class TestPastWindowAndCapacityConflict:
    def _setup_past_full_day(self, api):
        homeowner, home = setup_home(closing_date="2026-06-01")
        partner = create_trade_partner()  # 480 minutes/day
        sr1 = create_approved_request(
            home["id"], homeowner["id"], description="Leak A"
        )
        sr2 = create_approved_request(
            home["id"], homeowner["id"], description="Leak B"
        )
        set_clock("2026-07-01T00:00:00Z")
        dispatch_work_order(
            sr1["id"],
            partner["id"],
            window_start="2026-07-20T09:00:00Z",
            window_end="2026-07-20T17:00:00Z",  # 480 min: fills 2026-07-20
            estimated_cost_cents=60_000,
            defect_responsibility="BUILDER",
        )
        set_clock("2026-08-01T00:00:00Z")  # 2026-07-20 is now in the past
        return homeowner, home, partner, sr2

    def test_window_error_wins_over_capacity(self, api):
        """PRD §3.3: "Three scheduling guards run in order, after shape and state
        checks. First, the window must not begin in the past: a `window_start`
        strictly before the current clock is `ERR_INVALID_WINDOW`, while a window
        opening exactly now is acceptable. Second, trade capacity: the sum of
        `duration_minutes` over the partner's `SCHEDULED` work orders whose window
        start falls on the same UTC calendar date as the new window start, plus the
        new visit's duration, must not exceed `daily_capacity_minutes` — a day
        filled to exactly capacity is allowed, and one minute over draws
        `ERR_TRADE_CAPACITY_EXCEEDED`."
        PRD §2.7: "When a request violates several rules at once, exactly one error
        is returned: the first failure in the fixed precedence below."

        Design: Difficulty/priority_pair_validation_conflict/past_window_and_capacity_conflict
        """
        _ho, _home, partner, sr2 = self._setup_past_full_day(api)
        # Both violations hold: window_start in the past AND 480 + 600 > 480.
        resp = api.create_work_order(
            create_work_order_payload(
                sr2["id"],
                partner["id"],
                window_start="2026-07-20T09:00:00Z",
                window_end="2026-07-20T19:00:00Z",
                estimated_cost_cents=80_000,
                defect_responsibility="BUILDER",
            ),
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_conflicting_dispatch_creates_nothing(self, api):
        """PRD §3.3: "Three scheduling guards run in order, after shape and state
        checks. First, the window must not begin in the past: a `window_start`
        strictly before the current clock is `ERR_INVALID_WINDOW`, while a window
        opening exactly now is acceptable."
        PRD §2.7: "When a request violates several rules at once, exactly one error
        is returned: the first failure in the fixed precedence below."

        Design: Difficulty/priority_pair_validation_conflict/past_window_and_capacity_conflict
        """
        _ho, _home, partner, sr2 = self._setup_past_full_day(api)
        resp = api.create_work_order(
            create_work_order_payload(
                sr2["id"],
                partner["id"],
                window_start="2026-07-20T09:00:00Z",
                window_end="2026-07-20T19:00:00Z",
                estimated_cost_cents=80_000,
                defect_responsibility="BUILDER",
            ),
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

        data, meta = validate_paginated(
            api.list_work_orders(REP, params={"service_request_id": sr2["id"]})
        )
        assert meta["total_count"] == 0 and data == [], (
            "the rejected dispatch must not create a work order"
        )

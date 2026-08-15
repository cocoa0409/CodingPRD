"""Vacation holds: window rules, half-open overlap, state guards, priority pairs."""
from test_helpers import (
    REP,
    ApiErrorId,
    create_active_subscription,
    create_hold,
    create_plan,
    create_subscriber,
    create_subscription,
    get_hold,
    get_subscription,
    run_daily_cycle,
    set_clock,
    set_clock_and_cycle,
    validate_error,
    validate_success,
)


class TestHoldOverlap:
    def test_vacation_hold_half_open_adjacency(self, api):
        """PRD §2.8: "**Vacation holds** use a half-open interval:
        `start_date` is the first non-delivery day, `end_date` is the resume
        date and is **exclusive** — the hold's length in days is `end_date`
        minus `start_date`. Two holds on the same subscription overlap if
        their half-open intervals intersect; adjacency, where the new hold's
        start equals an existing hold's end, is allowed."

        Design: Difficulty/resource_temporal_overlap/vacation_hold_half_open_adjacency
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        subscription_id = ctx["subscription"]["id"]
        create_hold(subscription_id, "2026-08-10", "2026-08-14", resolution="CREDIT")

        overlap = api.create_vacation_hold(
            subscription_id,
            {"start_date": "2026-08-13", "end_date": "2026-08-15", "resolution": "CREDIT"},
            REP,
        )
        validate_error(overlap, ApiErrorId.ERR_HOLD_OVERLAP, 409)

        adjacent = api.create_vacation_hold(
            subscription_id,
            {"start_date": "2026-08-14", "end_date": "2026-08-17", "resolution": "CREDIT"},
            REP,
        )
        data = validate_success(adjacent, 201)
        assert data["status"] == "SCHEDULED"

    def test_vacation_hold_adjacency_before_existing_also_allowed(self, api):
        """PRD §2.8: "Two holds on the same subscription overlap if their
        half-open intervals intersect; adjacency, where the new hold's start
        equals an existing hold's end, is allowed."

        Design: Difficulty/resource_temporal_overlap/vacation_hold_half_open_adjacency
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        subscription_id = ctx["subscription"]["id"]
        create_hold(subscription_id, "2026-08-10", "2026-08-14", resolution="CREDIT")

        # New hold whose end equals the existing hold's start: also adjacent.
        before = api.create_vacation_hold(
            subscription_id,
            {"start_date": "2026-08-06", "end_date": "2026-08-10", "resolution": "CREDIT"},
            REP,
        )
        data = validate_success(before, 201)
        assert data["status"] == "SCHEDULED"

        # True containment still collides.
        contained = api.create_vacation_hold(
            subscription_id,
            {"start_date": "2026-08-11", "end_date": "2026-08-13", "resolution": "CREDIT"},
            REP,
        )
        validate_error(contained, ApiErrorId.ERR_HOLD_OVERLAP, 409)


class TestHoldStateGuards:
    def test_hold_cancel_active_rejected(self, api):
        """PRD §3.3: "Cancelling a hold that has already left `SCHEDULED` is
        rejected with `ERR_HOLD_NOT_CANCELLABLE`; resuming a hold that is not
        currently `ACTIVE` is rejected with `ERR_HOLD_NOT_ACTIVE`."

        Design: Corner/state_machines/hold_cancel_active_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        hold = create_hold(ctx["subscription"]["id"], "2026-08-03", "2026-08-07", "CREDIT")
        run_daily_cycle()  # start_date == today -> hold flips to ACTIVE
        assert get_hold(hold["id"])["status"] == "ACTIVE"

        resp = api.cancel_vacation_hold(hold["id"], REP)
        validate_error(resp, ApiErrorId.ERR_HOLD_NOT_CANCELLABLE, 409)
        assert get_hold(hold["id"])["status"] == "ACTIVE"

    def test_hold_cancel_scheduled_succeeds(self, api):
        """PRD §3.3: "A `SCHEDULED` hold can still be cancelled outright —
        by the subscriber or a staff role — which flips it to `CANCELLED`
        with no credit, no delivery change, and zero drift on the subscriber
        ledger."

        Design: Corner/state_machines/hold_cancel_active_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        hold = create_hold(ctx["subscription"]["id"], "2026-08-10", "2026-08-14", "CREDIT")
        assert hold["status"] == "SCHEDULED"

        cancelled = validate_success(api.cancel_vacation_hold(hold["id"], REP))
        assert cancelled["status"] == "CANCELLED"

        subscriber = get_subscription(ctx["subscription"]["id"])
        assert subscriber["delivery_status"] == "DELIVERING", (
            "cancelling a SCHEDULED hold must not touch delivery"
        )

    def test_resume_scheduled_hold_rejected(self, api):
        """PRD §3.3: "Cancelling a hold that has already left `SCHEDULED` is
        rejected with `ERR_HOLD_NOT_CANCELLABLE`; resuming a hold that is not
        currently `ACTIVE` is rejected with `ERR_HOLD_NOT_ACTIVE`."

        Design: Corner/errors/resume_scheduled_hold_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        hold = create_hold(ctx["subscription"]["id"], "2026-08-10", "2026-08-14", "CREDIT")
        assert hold["status"] == "SCHEDULED"

        resp = api.resume_vacation_hold(hold["id"], REP)
        validate_error(resp, ApiErrorId.ERR_HOLD_NOT_ACTIVE, 409)
        assert get_hold(hold["id"])["status"] == "SCHEDULED"

    def test_digital_only_plan_blocks_hold(self, api):
        """PRD §3.3: "Holds are only meaningful for print-capable plans;
        attempting one against a `DIGITAL` plan is rejected with
        `ERR_DIGITAL_ONLY_PLAN`."

        Design: Corner/validations/digital_only_plan_blocks_hold
        """
        ctx = create_active_subscription(
            start_date="2026-08-03",
            clock="2026-08-03T00:00:00Z",
            plan_overrides={
                "name": "DG", "plan_type": "DIGITAL", "issues_per_week": 0,
                "base_weekly_rate_cents": 400,
            },
        )
        resp = api.create_vacation_hold(
            ctx["subscription"]["id"],
            {"start_date": "2026-08-10", "end_date": "2026-08-12", "resolution": "CREDIT"},
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_DIGITAL_ONLY_PLAN, 409)


class TestHoldValidationPriority:
    def test_hold_state_error_beats_temporal_overlap(self, api):
        """PRD §3.3: "Finally, holds require the subscription's billing axis
        to be in an active set: `ACTIVE` or `GRACE`, otherwise
        `ERR_SUBSCRIPTION_NOT_ACTIVE`."
        PRD §2.10: "State preconditions come next (the specific state-axis
        errors such as `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_COMPLAINT_NOT_OPEN`,
        `ERR_OFFER_NOT_OPEN`, and their siblings), then the OCC stale-version
        check (`ERR_STALE_VERSION`). Temporal interval rules follow (hold
        windows and overlaps, assignment overlaps, rack week conflicts, audit
        period overlaps, complaint filing windows), then cross-entity
        referential fit (service-address requirements and print-capability
        requirements), then capacity and uniqueness constraints (route
        capacity, duplicate complaints, route code uniqueness)."

        Design: Difficulty/priority_pair_validation_conflict/hold_state_error_beats_temporal_overlap
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="SV", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(
            display_name="SV", email="sv@x.com", service_address="9 Main St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()
        # Existing SCHEDULED hold in October.
        create_hold(subscription["id"], "2026-10-05", "2026-10-09", "CREDIT")

        # Drive billing to SUSPENDED: oldest charge due 2026-08-17 is 22 days
        # past due on 2026-09-08.
        set_clock_and_cycle("2026-09-08T00:00:00Z")
        assert get_subscription(subscription["id"])["billing_status"] == "SUSPENDED"

        resp = api.create_vacation_hold(
            subscription["id"],
            {"start_date": "2026-10-06", "end_date": "2026-10-08", "resolution": "CREDIT"},
            REP,
        )
        error = validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE, 409)
        assert error["error_id"] != "ERR_HOLD_OVERLAP"

    def test_hold_state_error_also_beats_window_rule(self, api):
        """PRD §2.10: "State preconditions come next (the specific state-axis
        errors such as `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_COMPLAINT_NOT_OPEN`,
        `ERR_OFFER_NOT_OPEN`, and their siblings), then the OCC stale-version
        check (`ERR_STALE_VERSION`). Temporal interval rules follow (hold
        windows and overlaps, assignment overlaps, rack week conflicts, audit
        period overlaps, complaint filing windows), then cross-entity
        referential fit (service-address requirements and print-capability
        requirements), then capacity and uniqueness constraints (route
        capacity, duplicate complaints, route code uniqueness)."

        Design: Difficulty/priority_pair_validation_conflict/hold_state_error_beats_temporal_overlap
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="SV2", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(
            display_name="SV2", email="sv2@x.com", service_address="10 Main St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()
        set_clock_and_cycle("2026-09-08T00:00:00Z")  # SUSPENDED
        assert get_subscription(subscription["id"])["billing_status"] == "SUSPENDED"

        # This window is also in the past (temporal violation) — state wins.
        resp = api.create_vacation_hold(
            subscription["id"],
            {"start_date": "2026-09-01", "end_date": "2026-09-03", "resolution": "CREDIT"},
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE, 409)

    def test_hold_temporal_error_beats_fiscal_annual_cap(self, api):
        """PRD §3.3: "The window must be valid: the start cannot be in the
        past relative to today (violations surface as
        `ERR_HOLD_WINDOW_INVALID`), and the length — `end_date` minus
        `start_date` under the half-open convention — must fall between one
        and twenty-one days inclusive."
        PRD §2.10: "Money and quota checks are always evaluated last: the
        monthly goodwill cap, the per-complaint credit cap, the annual hold
        budget, the settled-ledger requirement for subscriber close, and the
        unreconciled-rack-report block on audit certification."

        Design: Difficulty/priority_pair_validation_conflict/hold_temporal_error_beats_fiscal_annual_cap
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="TF", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(
            display_name="TF", email="tf@x.com", service_address="10 Main St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()
        # Two REDELIVER holds consume exactly 30 annual hold days.
        create_hold(subscription["id"], "2026-08-03", "2026-08-18", "REDELIVER")  # 15 days
        create_hold(subscription["id"], "2026-08-19", "2026-09-03", "REDELIVER")  # 15 days

        set_clock_and_cycle("2026-09-04T00:00:00Z")  # both holds complete

        # Past-dated start (temporal) AND would exceed the annual budget
        # (fiscal): the temporal error must surface.
        resp = api.create_vacation_hold(
            subscription["id"],
            {"start_date": "2026-09-01", "end_date": "2026-09-03", "resolution": "CREDIT"},
            REP,
        )
        error = validate_error(resp, ApiErrorId.ERR_HOLD_WINDOW_INVALID, 409)
        assert error["error_id"] != "ERR_HOLD_LIMIT_EXCEEDED"

    def test_hold_annual_budget_exceeded_when_window_valid(self, api):
        """PRD §3.3: "There is also an annual budget: the total hold days
        across a subscription's `SCHEDULED`, `ACTIVE`, and `COMPLETED` holds
        within the calendar year, plus the new hold's length, may not exceed
        thirty days — excess is rejected with `ERR_HOLD_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/hold_temporal_error_beats_fiscal_annual_cap
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="TF2", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscriber = create_subscriber(
            display_name="TF2", email="tf2@x.com", service_address="11 Main St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()
        create_hold(subscription["id"], "2026-08-03", "2026-08-18", "REDELIVER")  # 15 days
        create_hold(subscription["id"], "2026-08-19", "2026-09-03", "REDELIVER")  # 15 days
        set_clock_and_cycle("2026-09-04T00:00:00Z")

        # Valid future window, but 30 + 2 > 30 annual days.
        resp = api.create_vacation_hold(
            subscription["id"],
            {"start_date": "2026-09-10", "end_date": "2026-09-12", "resolution": "CREDIT"},
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_HOLD_LIMIT_EXCEEDED, 409)

"""Tune-ticket pipeline: quoting, OCC approval, capacity gates, the rework loop,
and terminal lockdown."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_ticket,
    declare_capacity,
    make_customer,
    make_customer_headers,
    make_tune_ticket,
    quote_ticket,
    set_clock,
    setup_active_lease,
    setup_ticket_in_quality_check,
    validate_error,
    validate_success,
)

TECH = TEST_USERS["technician_headers"]
MGR = TEST_USERS["manager_headers"]


class TestReworkCycle:
    def test_rework_loop_returns_to_ready(self, api):
        """PRD The Tuning Workshop: "A QC fail loops the ticket back to `IN_PROGRESS`
        for rework" and "A QC pass moves the ticket to `READY` and fixes the money:
        `final_price_cents` is set equal to `quoted_price_cents` — rework is never
        billed."

        Design: Difficulty/non_linear_state_machine/tune_ticket_rework_cycle
        """
        ctx = setup_ticket_in_quality_check(services=("WAX",))
        ticket = ctx["ticket"]
        failed = validate_success(api.qc_fail_tune_ticket(ticket["id"], TECH))
        assert failed["status"] == "IN_PROGRESS"
        assert failed["rework_count"] == 1

        validate_success(api.complete_tune_ticket(ticket["id"], TECH))
        passed = validate_success(api.qc_pass_tune_ticket(ticket["id"], TECH))
        assert passed["status"] == "READY"
        assert passed["rework_count"] == 1
        assert passed["final_price_cents"] == 2500

    def test_rework_reconsumes_standard_capacity(self, api):
        """PRD The Tuning Workshop: "first the day's standard capacity is re-verified
        exactly as at start (rework consumes the pool a second time, adding
        `labor_minutes` to `booked_minutes` again, and a full pool yields
        `ERR_CAPACITY_FULL`)"

        Design: Difficulty/non_linear_state_machine/tune_ticket_rework_cycle
        """
        ctx = setup_ticket_in_quality_check(services=("WAX",))
        ticket = ctx["ticket"]
        validate_success(api.qc_fail_tune_ticket(ticket["id"], TECH))
        capacity = validate_success(api.get_shop_day_capacity(ctx["capacity"]["id"], TECH))
        # WAX labor is 45 minutes: start 45 + rework re-book 45.
        assert capacity["booked_minutes"] == 90


class TestTerminalLockdown:
    def test_cancel_after_picked_up_rejected(self, api):
        """PRD The Tuning Workshop: "Once `READY`, the customer collects the gear and
        the ticket reaches `PICKED_UP`, terminal alongside `CANCELLED`."
        PRD The Tuning Workshop: "Cancelling a ticket while it is still in `INTAKE` or
        `QUOTED` moves it to `CANCELLED`"

        Design: Corner/state_machines/ticket_cancel_from_picked_up_returns_invalid_state
        """
        ctx = setup_ticket_in_quality_check(services=("WAX",))
        ticket = ctx["ticket"]
        customer = ctx["customer"]
        validate_success(api.qc_pass_tune_ticket(ticket["id"], TECH))
        picked = validate_success(
            api.pickup_tune_ticket(ticket["id"], make_customer_headers(customer["id"])))
        assert picked["status"] == "PICKED_UP"

        resp = api.cancel_tune_ticket(ticket["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_tune_ticket(ticket["id"], TECH))
        assert after["status"] == "PICKED_UP"
        assert after["final_price_cents"] == 2500


class TestRushCapacityBoundary:
    def test_exact_fit_rush_intake_allowed(self, api):
        """PRD The Tuning Workshop: "the sum of already-booked rush minutes and the new
        ticket's `labor_minutes` must not exceed `rush_reserved_minutes`, or the intake
        is rejected with `ERR_RUSH_CAPACITY_EXCEEDED`. An exact fit — booked plus new
        exactly equal to the reserved pool — is allowed."

        Design: Difficulty/boundary_precision_check/rush_capacity_exact_fit_boundary
        """
        set_clock("2026-12-01T09:00:00Z")
        declare_capacity("2026-12-01", base_labor_minutes=480, rush_reserved_minutes=120)
        customer = make_customer()
        # BASE_GRIND 90 + BINDING_ADJUST 30 = 120 rush minutes: exact fit.
        ticket = make_tune_ticket(customer, services=("BASE_GRIND", "BINDING_ADJUST"),
                                  rush=True)
        assert ticket["labor_minutes"] == 120
        # Rush promises a 24h turnaround: created 2026-12-01T09:00Z + 24h.
        assert ticket["promised_at"].startswith("2026-12-02T09:00:00"), (
            f"promised_at must be creation + 24h, got {ticket['promised_at']!r}"
        )

    def test_one_minute_over_rush_pool_rejected(self, api):
        """PRD The Tuning Workshop: "the sum of already-booked rush minutes and the new
        ticket's `labor_minutes` must not exceed `rush_reserved_minutes`, or the intake
        is rejected with `ERR_RUSH_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/rush_capacity_exact_fit_boundary
        """
        set_clock("2026-12-01T09:00:00Z")
        capacity = declare_capacity("2026-12-01", base_labor_minutes=480,
                                    rush_reserved_minutes=120)
        customer = make_customer()
        make_tune_ticket(customer, services=("BASE_GRIND", "BINDING_ADJUST"), rush=True)

        # 120 + 45 (WAX) > 120: the pool overflows.
        resp = api.create_tune_ticket(
            {"customer_id": customer["id"], "own_gear_description": "pow board",
             "services": ["WAX"], "rush": True},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RUSH_CAPACITY_EXCEEDED)
        after = validate_success(api.get_shop_day_capacity(capacity["id"], TECH))
        assert after["rush_booked_minutes"] == 120


class TestQuoteCalculation:
    def test_rush_multiplier_and_promised_turnaround(self, api):
        """PRD The Tuning Workshop: "first a rush multiplier of 1.5 when the ticket is
        a rush job (1.0 otherwise)" and "the computed `promised_at` is exactly
        twenty-four hours after creation for rush tickets and forty-eight hours after
        for standard ones."

        Design: Corner/calculations/rush_multiplier_on_tune_quote
        """
        set_clock("2026-12-02T09:00:00Z")
        declare_capacity("2026-12-02", base_labor_minutes=480, rush_reserved_minutes=120)
        customer = make_customer()
        ticket = make_tune_ticket(customer, services=("WAX",), rush=True)
        assert ticket["promised_at"].startswith("2026-12-03T09:00:00")

        quoted = quote_ticket(ticket)
        # round_half_up(2500 x 1.5 x 1.0) = 3750; no lease, so no junior multiplier.
        assert quoted["quoted_price_cents"] == 3750
        assert quoted["junior_discount_applied"] is False

    def test_junior_lease_discount_applied(self, api):
        """PRD The Tuning Workshop: "then a junior multiplier of 0.8 when the ticket's
        customer holds a season lease in `ACTIVE` or `SUSPENDED` status at quote time
        (1.0 otherwise)" and "when the junior multiplier applied, the ticket's
        `junior_discount_applied` flag is set true."

        Design: Corner/calculations/junior_lease_discount_on_tune_quote
        """
        lease_ctx = setup_active_lease()
        junior = lease_ctx["junior"]
        declare_capacity("2026-12-01", base_labor_minutes=480, rush_reserved_minutes=120)
        set_clock("2026-12-01T09:00:00Z")
        ticket = make_tune_ticket(junior, services=("WAX",), rush=False,
                                  actor_headers=TEST_USERS["front_desk_headers"])
        quoted = quote_ticket(ticket)
        # round_half_up(2500 x 1.0 x 0.8) = 2000.
        assert quoted["quoted_price_cents"] == 2000
        assert quoted["junior_discount_applied"] is True


class TestCapacityGates:
    def test_intake_without_capacity_row_rejected(self, api):
        """PRD The Tuning Workshop: "First, a capacity row must exist for the calendar
        date of the ticket's creation; intaking a ticket on an undeclared day is
        rejected with `ERR_CAPACITY_MISSING`."

        Design: Corner/validations/ticket_without_capacity_row_returns_capacity_missing
        """
        set_clock("2026-12-05T09:00:00Z")
        customer = make_customer()
        resp = api.create_tune_ticket(
            {"customer_id": customer["id"], "own_gear_description": "own skis",
             "services": ["WAX"], "rush": False},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_MISSING)

    def test_start_over_base_capacity_rejected(self, api):
        """PRD The Tuning Workshop: "a technician may start an `APPROVED` ticket only
        when the capacity row for the ticket's creation date has room in its standard
        pool — booked standard minutes plus the ticket's `labor_minutes` must not
        exceed `base_labor_minutes`, or the start is rejected with
        `ERR_CAPACITY_FULL`."

        Design: Corner/validations/start_over_base_capacity_returns_409
        """
        set_clock("2026-12-03T09:00:00Z")
        capacity = declare_capacity("2026-12-03", base_labor_minutes=60,
                                    rush_reserved_minutes=0)
        customer = make_customer()
        t1 = approve_ticket(quote_ticket(make_tune_ticket(
            customer, services=("EDGE_TUNE",))), customer)
        t2 = approve_ticket(quote_ticket(make_tune_ticket(
            customer, services=("WAX",))), customer)

        validate_success(api.start_tune_ticket(t1["id"], TECH))
        # EDGE_TUNE consumed the whole 60-minute pool; WAX needs 45 more.
        resp = api.start_tune_ticket(t2["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_FULL)
        after = validate_success(api.get_shop_day_capacity(capacity["id"], TECH))
        assert after["booked_minutes"] == 60

    def test_duplicate_capacity_date_rejected(self, api):
        """PRD The Tuning Workshop: "A `Manager` creates a shop-day capacity row for a
        `service_date` — unique across all such rows, with a duplicate date rejected as
        `ERR_CAPACITY_EXISTS`"

        Design: Corner/validations/duplicate_capacity_date_returns_409
        """
        declare_capacity("2026-12-01", base_labor_minutes=480, rush_reserved_minutes=120)
        resp = api.create_shop_day_capacity(
            {"service_date": "2026-12-01", "base_labor_minutes": 600,
             "rush_reserved_minutes": 60},
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXISTS)


class TestReworkLimit:
    def test_third_qc_fail_rejected(self, api):
        """PRD The Tuning Workshop: "a ticket whose `rework_count` has already reached
        two may not fail QC again and is rejected with `ERR_REWORK_LIMIT_EXCEEDED`."

        Design: Corner/validations/third_qc_fail_rejected_rework_limit
        """
        ctx = setup_ticket_in_quality_check(services=("WAX",))
        ticket = ctx["ticket"]
        first = validate_success(api.qc_fail_tune_ticket(ticket["id"], TECH))
        assert first["rework_count"] == 1
        validate_success(api.complete_tune_ticket(ticket["id"], TECH))
        second = validate_success(api.qc_fail_tune_ticket(ticket["id"], TECH))
        assert second["rework_count"] == 2
        validate_success(api.complete_tune_ticket(ticket["id"], TECH))

        resp = api.qc_fail_tune_ticket(ticket["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_REWORK_LIMIT_EXCEEDED)
        after = validate_success(api.get_tune_ticket(ticket["id"], TECH))
        assert after["status"] == "QUALITY_CHECK"


class TestQuoteApprovalOcc:
    def test_stale_version_approve_rejected_then_current_accepted(self, api):
        """PRD Optimistic Concurrency Control: "If the ticket's current `version` has
        advanced since then — for example because a technician re-quoted the ticket,
        which itself bumps the version — the approval is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so a customer can never approve a quote they
        have not actually seen."

        Design: Corner/cross_cutting_layers/occ_ticket_approve_stale_version
        """
        set_clock("2026-12-01T09:00:00Z")
        declare_capacity("2026-12-01", base_labor_minutes=480, rush_reserved_minutes=120)
        customer = make_customer()
        headers = make_customer_headers(customer["id"])
        ticket = make_tune_ticket(customer, services=("WAX",))

        first_quote = quote_ticket(ticket, parts_surcharge_cents=0)
        assert first_quote["quoted_price_cents"] == 2500
        second_quote = quote_ticket(first_quote, parts_surcharge_cents=700)
        # Re-quote keeps the ticket QUOTED and recomputes: 2500 + 700 parts.
        assert second_quote["quoted_price_cents"] == 3200
        assert second_quote["version"] > first_quote["version"]

        stale = api.approve_tune_ticket(
            ticket["id"], {"expected_tune_ticket_version": first_quote["version"]},
            headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        approved = validate_success(api.approve_tune_ticket(
            ticket["id"], {"expected_tune_ticket_version": second_quote["version"]},
            headers))
        assert approved["status"] == "APPROVED"

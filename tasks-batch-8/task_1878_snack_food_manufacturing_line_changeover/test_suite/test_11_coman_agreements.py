"""Co-manufacturing: weekly capacity and budget checks with their fixed
ordering, Monday week anchoring, agreement-state gating, slot lifecycle
terminal states, and ownership scope."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_slot,
    create_co_manufacturer_payload,
    create_plain_product,
    create_slot_payload,
    get_success_data,
    make_coman_headers,
    setup_active_agreement,
    validate_error,
    validate_paginated,
)

PM = TEST_USERS["plant_manager_headers"]


class TestCapacityBeforeBudget:
    def _setup_full_week(self, api):
        """ACTIVE agreement (capacity 10000, rate 50, budget 600000) with
        6000 + 4000 lbs booked on ISO week 2026-09-07 (budget used 500000)."""
        product = create_plain_product()
        ctx = setup_active_agreement(weekly_capacity_lbs=10000,
                                     rate_per_lb_cents=50, budget_cents=600000)
        book_slot(ctx["agreement"]["id"], product["id"], ctx["coman"]["id"],
                  reserved_lbs=6000)
        book_slot(ctx["agreement"]["id"], product["id"], ctx["coman"]["id"],
                  reserved_lbs=4000)
        return product, ctx

    def test_dual_breach_reports_capacity_not_budget(self, api):
        """PRD §2.9: "Because fiscal rules are checked last, a slot booking
        that would breach both its weekly capacity and its budget surfaces
        `ERR_CAPACITY_EXCEEDED`, never `ERR_BUDGET_EXCEEDED`; capacity is
        checked before budget."

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_slot_booking
        """
        product, ctx = self._setup_full_week(api)
        # 10000 + 3000 > capacity 10000 AND 500000 + 150000 > budget 600000
        resp = api.create_slot(
            create_slot_payload(ctx["agreement"]["id"], product["id"],
                                week_start_date="2026-09-07", reserved_lbs=3000),
            make_coman_headers(ctx["coman"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)

    def test_capacity_breach_with_budget_satisfied(self, api):
        """PRD §3.9: "the weekly capacity check comes first — the sum of
        `reserved_lbs` across the agreement's slots in the same ISO week with
        status `BOOKED` or `CONFIRMED`, plus the new reservation, must not
        exceed `weekly_capacity_lbs`, with a total exactly equal to the weekly
        capacity allowed; a breach is `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_slot_booking
        """
        product, ctx = self._setup_full_week(api)
        # 11500 > 10000 breaches capacity; 575000 <= 600000 leaves budget
        # intact: the constraint rule fires on its own
        resp = api.create_slot(
            create_slot_payload(ctx["agreement"]["id"], product["id"],
                                week_start_date="2026-09-07", reserved_lbs=1500),
            make_coman_headers(ctx["coman"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)


class TestCapacityExactFit:
    def test_exact_fit_accepted_then_one_pound_rejected(self, api):
        """PRD §3.9: "the sum of `reserved_lbs` across the agreement's slots in
        the same ISO week with status `BOOKED` or `CONFIRMED`, plus the new
        reservation, must not exceed `weekly_capacity_lbs`, with a total
        exactly equal to the weekly capacity allowed; a breach is
        `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/coman_capacity_exact_fit_inclusive
        """
        product = create_plain_product()
        ctx = setup_active_agreement(weekly_capacity_lbs=10000, rate_per_lb_cents=50,
                                     budget_cents=1000000)
        book_slot(ctx["agreement"]["id"], product["id"], ctx["coman"]["id"],
                  reserved_lbs=6000)
        # 6000 + 4000 == 10000: exactly at the weekly capacity, inclusive
        slot2 = book_slot(ctx["agreement"]["id"], product["id"], ctx["coman"]["id"],
                          reserved_lbs=4000)
        assert slot2["status"] == "BOOKED"
        resp = api.create_slot(
            create_slot_payload(ctx["agreement"]["id"], product["id"],
                                week_start_date="2026-09-07", reserved_lbs=1),
            make_coman_headers(ctx["coman"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)

    def test_capacity_is_scoped_to_the_iso_week(self, api):
        """PRD §3.9: "the sum of `reserved_lbs` across the agreement's slots in
        the same ISO week with status `BOOKED` or `CONFIRMED`, plus the new
        reservation, must not exceed `weekly_capacity_lbs`"

        Design: Difficulty/boundary_precision_check/coman_capacity_exact_fit_inclusive
        """
        product = create_plain_product()
        ctx = setup_active_agreement(weekly_capacity_lbs=10000, rate_per_lb_cents=50,
                                     budget_cents=1000000)
        book_slot(ctx["agreement"]["id"], product["id"], ctx["coman"]["id"],
                  reserved_lbs=6000)
        book_slot(ctx["agreement"]["id"], product["id"], ctx["coman"]["id"],
                  reserved_lbs=4000)
        # a different ISO week (Monday 2026-09-14) carries its own capacity
        slot3 = book_slot(ctx["agreement"]["id"], product["id"], ctx["coman"]["id"],
                          reserved_lbs=4000, week_start_date="2026-09-14")
        assert slot3["status"] == "BOOKED"


class TestSlotBookingRules:
    def test_slot_week_start_not_monday_rejected(self, api):
        """PRD §3.9: "the `week_start_date` — the Monday, as an ISO calendar
        date, of the production week the reservation occupies; any other
        weekday is rejected with `ERR_WEEK_START_INVALID`"

        Design: Corner/validations/slot_week_start_not_monday_rejected
        """
        product = create_plain_product()
        ctx = setup_active_agreement()
        # 2026-09-08 is a Tuesday
        resp = api.create_slot(
            create_slot_payload(ctx["agreement"]["id"], product["id"],
                                week_start_date="2026-09-08", reserved_lbs=100),
            make_coman_headers(ctx["coman"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WEEK_START_INVALID, 422)
        slots, meta = validate_paginated(api.list_slots(PM))
        assert slots == [] and meta["total_count"] == 0

    def test_budget_exceeded_alone_rejected(self, api):
        """PRD §3.9: "Only then is the budget checked — the sum of each slot's
        `reserved_lbs` multiplied by the agreement's `rate_per_lb_cents` across
        all of the agreement's `BOOKED` or `CONFIRMED` slots in every week,
        plus the new reservation's poundage at that rate, must not exceed
        `budget_cents`; a breach is `ERR_BUDGET_EXCEEDED`."

        Design: Corner/validations/budget_exceeded_alone_rejected
        """
        product = create_plain_product()
        ctx = setup_active_agreement(weekly_capacity_lbs=10000,
                                     rate_per_lb_cents=50, budget_cents=600000)
        book_slot(ctx["agreement"]["id"], product["id"], ctx["coman"]["id"],
                  reserved_lbs=6000)
        book_slot(ctx["agreement"]["id"], product["id"], ctx["coman"]["id"],
                  reserved_lbs=4000)
        # week 2026-09-14 is unconsumed (capacity passes); 500000 + 150000
        # exceeds the 600000 budget across every week's BOOKED/CONFIRMED slots
        resp = api.create_slot(
            create_slot_payload(ctx["agreement"]["id"], product["id"],
                                week_start_date="2026-09-14", reserved_lbs=3000),
            make_coman_headers(ctx["coman"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED, 422)


class TestSlotConfirmAgreementGate:
    def _setup_booked_slot(self, api):
        product = create_plain_product()
        ctx = setup_active_agreement()
        slot = book_slot(ctx["agreement"]["id"], product["id"],
                         ctx["coman"]["id"], reserved_lbs=2000)
        return product, ctx, slot

    def test_confirm_blocked_during_suspension(self, api):
        """PRD §3.9: "Suspension moves `ACTIVE` to `SUSPENDED`; suspension
        does not release booked slots, but it blocks both new bookings and
        slot confirmations with `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/slot_confirm_gated_on_agreement_active
        """
        _product, ctx, slot = self._setup_booked_slot(api)
        get_success_data(api.suspend_agreement(ctx["agreement"]["id"], PM))
        resp = api.confirm_slot(slot["id"], make_coman_headers(ctx["coman"]["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)
        slot = get_success_data(api.get_slot(slot["id"], PM))
        assert slot["status"] == "BOOKED", "suspension does not cascade"

    def test_confirm_succeeds_after_resume(self, api):
        """PRD §3.9: "Resuming returns `SUSPENDED` to `ACTIVE`."
        PRD §3.9: "The partner confirms its own commitments: a `CoManufacturer`
        confirms a `BOOKED` slot, moving it to `CONFIRMED`, only when the
        agreement is `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/slot_confirm_gated_on_agreement_active
        """
        _product, ctx, slot = self._setup_booked_slot(api)
        get_success_data(api.suspend_agreement(ctx["agreement"]["id"], PM))
        validate_error(
            api.confirm_slot(slot["id"], make_coman_headers(ctx["coman"]["id"])),
            ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)
        get_success_data(api.resume_agreement(ctx["agreement"]["id"], PM))
        confirmed = get_success_data(
            api.confirm_slot(slot["id"], make_coman_headers(ctx["coman"]["id"])))
        assert confirmed["status"] == "CONFIRMED"


class TestSlotTerminalAndOwnership:
    def test_slot_release_from_consumed_returns_already_terminal(self, api):
        """PRD §2.9: "the target entity occupies a from-state of the invoked
        transition, terminal entities reject all further transitions with
        `ERR_ALREADY_TERMINAL`"
        PRD §3.9: "a `PlantManager` consumes a `CONFIRMED` slot, moving it to
        the terminal `CONSUMED` state"

        Design: Corner/state_machines/slot_release_from_consumed_returns_already_terminal
        """
        product = create_plain_product()
        ctx = setup_active_agreement()
        slot = book_slot(ctx["agreement"]["id"], product["id"],
                         ctx["coman"]["id"], reserved_lbs=2000)
        get_success_data(
            api.confirm_slot(slot["id"], make_coman_headers(ctx["coman"]["id"])))
        consumed = get_success_data(api.consume_slot(slot["id"], PM))
        assert consumed["status"] == "CONSUMED"
        resp = api.release_slot(slot["id"], PM)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        slot = get_success_data(api.get_slot(slot["id"], PM))
        assert slot["status"] == "CONSUMED"

    def test_coman_other_cannot_confirm_slot(self, api):
        """PRD §3.9: "The partner confirms its own commitments: a
        `CoManufacturer` confirms a `BOOKED` slot, moving it to `CONFIRMED`,
        only when the agreement is `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`)
        and the agreement's `co_manufacturer_id` equals the caller's
        `X-User-ID` (else `ERR_FORBIDDEN`)."

        Design: Corner/rbac/coman_other_cannot_confirm_slot
        """
        product = create_plain_product()
        ctx = setup_active_agreement(name="TollCo A")
        cm_b = get_success_data(api.create_co_manufacturer(
            create_co_manufacturer_payload(name="TollCo B"), PM))
        slot = book_slot(ctx["agreement"]["id"], product["id"],
                         ctx["coman"]["id"], reserved_lbs=2000)
        resp = api.confirm_slot(slot["id"], make_coman_headers(cm_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        slot = get_success_data(api.get_slot(slot["id"], PM))
        assert slot["status"] == "BOOKED"

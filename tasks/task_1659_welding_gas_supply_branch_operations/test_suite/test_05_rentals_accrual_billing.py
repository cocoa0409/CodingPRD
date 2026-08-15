"""Rental agreements: accrual dual variants, grace boundaries, billing runs,
turnaround buffer, waivers, and the fixed default logical clock."""
from test_helpers import (
    ApiErrorId,
    get_fresh_rental_version,
    get_machine,
    get_rental,
    make_customer,
    make_cylinder,
    make_demurrage_rental,
    make_machine,
    make_machine_rental,
    run_billing_cycle,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProvisionalCeilVsBilledFloor:
    def _demurrage_at(self, clock_after_setup):
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-RA1", name="Accrual Co",
                                 terms="CASH")
        asset = make_cylinder(serial_no="CYL-RA1", gas_grade="ARGON",
                              size="MEDIUM")
        rental = make_demurrage_rental(customer["id"], asset["id"],
                                       start_date="2026-08-01", grace_days=5)
        set_clock(clock_after_setup)
        return customer, rental

    def test_provisional_ceil_accrues_while_billed_floor_posts_nothing(
            self, api):
        """PRD §3.6: "The provisional value rounds the chargeable-days-over-
        period quotient up to a whole number of periods and multiplies by the
        rate — the customer currently owes for a period they have started. The
        billed value rounds the same quotient down to whole completed periods
        only — a started-but-unfinished period is not yet billed, so the
        billed figure is smaller than the provisional figure whenever a
        partial period is in flight." At 2026-08-20 the chargeable days are
        max(0, 19 - 5) = 14: provisional ceil(14/30) x 1200 = 1200 while the
        billing run posts floor(14/30) = 0 periods.

        Design: Difficulty/dual_variant_calc/rental_accrual_provisional_ceil_vs_billed_floor
        """
        _customer, rental = self._demurrage_at("2026-08-20T00:00:00Z")
        assert get_rental(rental["id"])["accrued_unbilled_cents"] == 1200, \
            "ceil(14/30) = 1 period x 1200 DEMURRAGE rate"
        run = run_billing_cycle()
        assert run["invoices_created"] == 0
        assert run["total_billed_cents"] == 0, \
            "floor(14/30) = 0 complete periods — nothing to bill"

    def test_billing_run_posts_completed_periods_and_rebases_accrual(
            self, api):
        """PRD §3.6: "It iterates every agreement in `ACTIVE` status, computes
        each one's billed value at the current clock date as the
        complete-period figure minus `lifetime_billed_cents` and minus
        `waived_cents` (never below zero), and for every agreement with a
        positive amount posts the charge." and "each billed agreement's
        `billed_through_date` advances to the run date and its
        `lifetime_billed_cents` grows by the billed amount." At 2026-09-15 the
        chargeable days are 45 - 5 = 40: provisional ceil(40/30) x 1200 =
        2400; the run bills floor(40/30) = 1 period = 1200.

        Design: Difficulty/dual_variant_calc/rental_accrual_provisional_ceil_vs_billed_floor
        """
        _customer, rental = self._demurrage_at("2026-09-15T00:00:00Z")
        assert get_rental(rental["id"])["accrued_unbilled_cents"] == 2400
        run = run_billing_cycle()
        assert run["invoices_created"] == 1
        assert run["total_billed_cents"] == 1200
        after = get_rental(rental["id"])
        assert after["lifetime_billed_cents"] == 1200
        assert after["accrued_unbilled_cents"] == 1200, \
            "provisional 2400 minus lifetime_billed 1200"
        assert after["billed_through_date"] == "2026-09-15"


class TestAccrualBoundaries:
    def test_demurrage_grace_day_boundary(self, api):
        """PRD §3.6: "The chargeable days at a given as-of date are the whole
        days elapsed from `start_date` to that date minus `grace_days`, never
        less than zero." and "The period rate is the rented machine's
        `daily_rate_cents`, `weekly_rate_cents`, or `monthly_rate_cents` for
        the machine plans, and a flat 1200 cents ($12.00) per 30-day period
        for `DEMURRAGE`." At exactly 5 days held the chargeable count is 0;
        one day later ceil(1/30) = 1 full period is owed.

        Design: Corner/calculations/demurrage_grace_day_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-CA3", name="Grace Co",
                                 terms="CASH")
        asset = make_cylinder(serial_no="CYL-CA3", gas_grade="ACETYLENE",
                              size="MEDIUM")
        rental = make_demurrage_rental(customer["id"], asset["id"],
                                       start_date="2026-08-01", grace_days=5)
        set_clock("2026-08-06T00:00:00Z")
        assert get_rental(rental["id"])["accrued_unbilled_cents"] == 0, \
            "5 days held - 5 grace = 0 chargeable"
        set_clock("2026-08-07T00:00:00Z")
        assert get_rental(rental["id"])["accrued_unbilled_cents"] == 1200, \
            "1 chargeable day -> ceil(1/30) = 1 period x 1200"

    def test_machine_weekly_plan_ceil_accrual(self, api):
        """PRD §3.6: "The period length depends on the rate plan: 1 day for
        `DAILY`, 7 days for `WEEKLY`, and 30 days for both `MONTHLY` and
        `DEMURRAGE`." and "The provisional value rounds the
        chargeable-days-over-period quotient up to a whole number of periods
        and multiplies by the rate". 8 days on a 20000/week plan:
        ceil(8/7) = 2 x 20000 = 40000.

        Design: Corner/calculations/machine_weekly_plan_ceil_accrual
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-CA4", name="Weekly Co",
                                 terms="CASH")
        machine = make_machine(model="Lincoln 210", serial_no="M-CA4",
                               daily_rate_cents=4000, weekly_rate_cents=20000,
                               monthly_rate_cents=55000)
        rental = make_machine_rental(customer["id"], machine["id"],
                                     rate_plan="WEEKLY",
                                     start_date="2026-08-01", grace_days=0)
        set_clock("2026-08-09T00:00:00Z")
        assert get_rental(rental["id"])["accrued_unbilled_cents"] == 40000


class TestBillingRunGroupingAndSuspension:
    def test_suspend_skips_billing_resume_recovers(self, api,
                                                   counter_rep_headers):
        """PRD §3.6: "Suspension stops billing, not accrual — billing runs
        skip agreements in `SUSPENDED` status, but the provisional value keeps
        accruing against the clock." At 2026-09-15 the agreement floors to
        floor(40/30) = 1 period = 1200 once it is ACTIVE again.

        Design: Corner/state_machines/rental_suspend_skips_billing_resume_recovers
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-SM6", name="Suspend Co",
                                 terms="CASH")
        asset = make_cylinder(serial_no="CYL-SM6", gas_grade="NITROGEN",
                              size="LARGE")
        rental = make_demurrage_rental(customer["id"], asset["id"],
                                       start_date="2026-08-01", grace_days=5)
        set_clock("2026-09-15T00:00:00Z")
        validate_success(api.suspend_rental_agreement(rental["id"],
                                                      counter_rep_headers))
        assert run_billing_cycle()["invoices_created"] == 0, \
            "SUSPENDED agreements are skipped"
        validate_success(api.resume_rental_agreement(rental["id"],
                                                     counter_rep_headers))
        resumed = run_billing_cycle()
        assert resumed["invoices_created"] == 1
        assert resumed["total_billed_cents"] == 1200, "floor(40/30) x 1200"

    def test_billing_run_aggregates_one_invoice_per_customer(
            self, api, branch_manager_headers):
        """PRD §3.6: "Charges are grouped per customer into a single invoice
        per customer with `source` `RENTAL_CYCLE`" and "The run responds with
        `invoices_created`, the list of `invoice_ids`, and the
        `total_billed_cents` across the run."

        Design: Corner/calculations/billing_run_aggregates_one_invoice_per_customer
        """
        set_clock("2026-08-01T00:00:00Z")
        cust_a = make_customer(account_no="ACC-CA5A", name="Multi Co",
                               terms="CASH")
        cust_b = make_customer(account_no="ACC-CA5B", name="Solo Co",
                               terms="CASH")
        n1 = make_cylinder(serial_no="CYL-CA5-1", gas_grade="NITROGEN",
                           size="SMALL")
        n2 = make_cylinder(serial_no="CYL-CA5-2", gas_grade="NITROGEN",
                           size="SMALL")
        n3 = make_cylinder(serial_no="CYL-CA5-3", gas_grade="NITROGEN",
                           size="SMALL")
        for asset in (n1, n2):
            make_demurrage_rental(cust_a["id"], asset["id"],
                                  start_date="2026-08-01", grace_days=5)
        make_demurrage_rental(cust_b["id"], n3["id"], start_date="2026-08-01",
                              grace_days=5)
        set_clock("2026-09-15T00:00:00Z")
        run = run_billing_cycle()
        assert run["invoices_created"] == 2, "one invoice per customer"
        assert run["total_billed_cents"] == 3600, "1200 x 3 agreements"
        invoices, meta = validate_paginated(api.list_invoices(
            branch_manager_headers, params={"customer_id": cust_a["id"]}))
        assert meta["total_count"] == 1
        assert invoices[0]["amount_cents"] == 2400, \
            "customer A's two agreements roll up into one invoice"
        assert invoices[0]["source"] == "RENTAL_CYCLE"


class TestRentalOpenGuards:
    def test_rental_item_mismatch_rejected(self, api, counter_rep_headers):
        """PRD §3.6: "The item fields are polymorphic: `cylinder_asset_id` is
        required exactly when the item type is `CYLINDER` and must be null
        otherwise, `machine_id` is required exactly when the item type is
        `MACHINE` and must be null otherwise, and the rate plan must match the
        item — `DEMURRAGE` is for cylinders only, while `DAILY`, `WEEKLY`, and
        `MONTHLY` are for machines only. Any inconsistent combination of item
        type, asset field, and rate plan is rejected with
        `ERR_RENTAL_ITEM_MISMATCH`."

        Design: Corner/validations/rental_item_mismatch_rejected
        """
        customer = make_customer(account_no="ACC-VA3", name="Mix Co",
                                 terms="CASH")
        asset = make_cylinder(serial_no="CYL-VA3", gas_grade="ARGON",
                              size="SMALL")
        resp = api.create_rental_agreement(
            {"customer_id": customer["id"], "item_type": "MACHINE",
             "cylinder_asset_id": asset["id"], "rate_plan": "DAILY",
             "start_date": "2026-08-01"}, counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_RENTAL_ITEM_MISMATCH, 400)

    def test_rental_on_rented_machine_rejected(self, api,
                                               counter_rep_headers):
        """PRD §3.6: "A cylinder being put on rent must be `FULL`, and a
        machine must be `AVAILABLE`; otherwise the open fails with
        `ERR_ASSET_NOT_AVAILABLE`".

        Design: Corner/validations/rental_on_rented_machine_rejected
        """
        customer = make_customer(account_no="ACC-VA11", name="Busy Co",
                                 terms="CASH")
        machine = make_machine(model="Miller 211", serial_no="M-VA11",
                               daily_rate_cents=3000, weekly_rate_cents=12000,
                               monthly_rate_cents=36000)
        make_machine_rental(customer["id"], machine["id"], rate_plan="DAILY",
                            start_date="2026-08-01")
        assert get_machine(machine["id"])["status"] == "RENTED"
        resp = api.create_rental_agreement(
            {"customer_id": customer["id"], "item_type": "MACHINE",
             "machine_id": machine["id"], "rate_plan": "DAILY",
             "start_date": "2026-08-02"}, counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE)

    def test_condemned_cylinder_rejected_on_rental(self, api,
                                                   counter_rep_headers,
                                                   branch_manager_headers):
        """PRD §3.6: "A cylinder being put on rent must be `FULL`, and a
        machine must be `AVAILABLE`; otherwise the open fails with
        `ERR_ASSET_NOT_AVAILABLE` — and per §2.10 a `RETIRED` cylinder is
        rejected outright with `ERR_CYLINDER_CONDEMNED`."

        Design: Corner/validations/condemned_cylinder_rejected_on_rental
        """
        customer = make_customer(account_no="ACC-VA12", name="Safe Co",
                                 terms="CASH")
        asset = make_cylinder(serial_no="CYL-VA12", gas_grade="ACETYLENE",
                              size="SMALL")
        validate_success(api.retire_cylinder_asset(asset["id"],
                                                   branch_manager_headers))
        resp = api.create_rental_agreement(
            {"customer_id": customer["id"], "item_type": "CYLINDER",
             "cylinder_asset_id": asset["id"], "rate_plan": "DEMURRAGE",
             "start_date": "2026-08-01"}, counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_CYLINDER_CONDEMNED)


class TestMachineTurnaroundBuffer:
    def _closed_machine_rental(self):
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-OV1", name="Rent Co",
                                 terms="NET30", credit_limit_cents=1000000)
        machine = make_machine(model="Miller 252", serial_no="M-OV1",
                               daily_rate_cents=5000, weekly_rate_cents=20000,
                               monthly_rate_cents=60000)
        rental = make_machine_rental(customer["id"], machine["id"],
                                     rate_plan="DAILY",
                                     start_date="2026-08-01")
        set_clock("2026-08-10T00:00:00Z")
        return customer, machine, rental

    def test_close_posts_final_ceil_charge_and_releases_machine(self, api,
                                                                counter_rep_headers):
        """PRD §3.6: "the final charge is the provisional (round-up) value at
        the close date minus `lifetime_billed_cents` and minus `waived_cents`,
        never below zero. When the final charge is positive, an invoice with
        `source` `RENTAL_CLOSE` is created for that amount and
        `lifetime_billed_cents` grows by it. The asset comes back: a rented
        cylinder moves `OUT` → `EMPTY` with its holder and rental links
        cleared, while a rented machine moves `RENTED` → `AVAILABLE`, arming
        the turnaround buffer for the next rental." 9 chargeable days on a
        5000/day DAILY plan close out at 45000.

        Design: Difficulty/resource_temporal_overlap/machine_turnaround_buffer_blocks_next_day_rental
        """
        _customer, machine, rental = self._closed_machine_rental()
        closed = validate_success(api.close_rental_agreement(rental["id"],
                                                             counter_rep_headers))
        assert closed["status"] == "CLOSED"
        assert closed["lifetime_billed_cents"] == 45000, \
            "close-out ceil: 9 days x 5000"
        assert get_machine(machine["id"])["status"] == "AVAILABLE"

    def test_next_day_start_rejected_then_buffer_cleared(self, api,
                                                         counter_rep_headers):
        """PRD §3.6: "Machines carry an additional turnaround rule: after a
        rental closes, the machine needs a one-day service buffer, so a new
        rental's `start_date` must be strictly later than one day after the
        most recent close date among that machine's `CLOSED` rentals — a prior
        close on date D blocks start dates on D itself and on the following
        day — and a violation is `ERR_RENTAL_OVERLAP`." A close on 2026-08-10
        blocks 2026-08-11; 2026-08-12 clears the buffer.

        Design: Difficulty/resource_temporal_overlap/machine_turnaround_buffer_blocks_next_day_rental
        """
        customer, machine, rental = self._closed_machine_rental()
        validate_success(api.close_rental_agreement(rental["id"],
                                                    counter_rep_headers))
        blocked = api.create_rental_agreement(
            {"customer_id": customer["id"], "item_type": "MACHINE",
             "machine_id": machine["id"], "rate_plan": "DAILY",
             "start_date": "2026-08-11"}, counter_rep_headers)
        validate_error(blocked, ApiErrorId.ERR_RENTAL_OVERLAP)
        allowed = api.create_rental_agreement(
            {"customer_id": customer["id"], "item_type": "MACHINE",
             "machine_id": machine["id"], "rate_plan": "DAILY",
             "start_date": "2026-08-12"}, counter_rep_headers)
        validate_success(allowed, 201)


class TestWaivers:
    def _rental_with_1200_accrued(self):
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-VA6", name="Waive Co",
                                 terms="CASH")
        asset = make_cylinder(serial_no="CYL-VA6", gas_grade="ARGON",
                              size="SMALL")
        rental = make_demurrage_rental(customer["id"], asset["id"],
                                       start_date="2026-08-01", grace_days=5)
        set_clock("2026-08-20T00:00:00Z")
        return rental

    def test_waive_above_accrued_rejected(self, api, branch_manager_headers):
        """PRD §3.6: "The waived amount may not exceed the agreement's current
        `accrued_unbilled_cents` — waiving exactly the accrued amount is
        allowed, one cent more is rejected with
        `ERR_WAIVER_EXCEEDS_ACCRUED`."

        Design: Corner/validations/waive_above_accrued_rejected
        """
        rental = self._rental_with_1200_accrued()
        assert get_rental(rental["id"])["accrued_unbilled_cents"] == 1200
        version = get_fresh_rental_version(rental["id"])
        resp = api.waive_rental_agreement(
            rental["id"],
            {"waive_amount_cents": 1201, "reason": "goodwill",
             "expected_rental_agreement_version": version},
            branch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXCEEDS_ACCRUED)

    def test_full_waiver_then_stale_version_rejected(self, api,
                                                     branch_manager_headers):
        """PRD §3.6: "A successful waiver adds the amount to `waived_cents`,
        recomputes the accrual, and increments the agreement's `version`." PRD
        §2.7: "If the agreement's current `version` no longer matches, the
        waiver is rejected with `ERR_STALE_VERSION` (HTTP 412), because
        accrual-affecting mutations — suspension, resumption, closure, prior
        waivers, and billing runs — rebase the accrued amount the waiver was
        judged against."

        Design: Corner/cross_cutting_layers/occ_waiver_full_accrual_then_stale_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-LA2", name="OCC Waive Co",
                                 terms="CASH")
        asset = make_cylinder(serial_no="CYL-LA2", gas_grade="OXYGEN",
                              size="MEDIUM")
        rental = make_demurrage_rental(customer["id"], asset["id"],
                                       start_date="2026-08-01", grace_days=5)
        set_clock("2026-08-20T00:00:00Z")
        version = get_fresh_rental_version(rental["id"])
        waived = validate_success(api.waive_rental_agreement(
            rental["id"],
            {"waive_amount_cents": 1200, "reason": "billing dispute",
             "expected_rental_agreement_version": version},
            branch_manager_headers))
        assert waived["waived_cents"] == 1200, \
            "waiving exactly the accrued amount is allowed"
        assert waived["accrued_unbilled_cents"] == 0, \
            "the full waiver zeroes the accrual"
        replay = api.waive_rental_agreement(
            rental["id"],
            {"waive_amount_cents": 100, "reason": "more goodwill",
             "expected_rental_agreement_version": version},
            branch_manager_headers)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_counter_rep_cannot_waive_rental(self, api, counter_rep_headers):
        """PRD §3.6: "Goodwill waivers are a `BranchManager` exclusive
        carrying three inputs: `waive_amount_cents`, a free-text `reason`,
        and the concurrency token `expected_rental_agreement_version` of
        §2.7." PRD §2.1: a recognized role "not listed for the endpoint ... is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/counter_rep_cannot_waive_rental
        """
        rental = self._rental_with_1200_accrued()
        version = get_fresh_rental_version(rental["id"])
        resp = api.waive_rental_agreement(
            rental["id"],
            {"waive_amount_cents": 1200, "reason": "loyalty",
             "expected_rental_agreement_version": version},
            counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestLogicalClockDefault:
    def test_default_clock_pins_accrual_to_zero(self, api):
        """PRD §2.4: "At server startup, before any operator intervention, the
        logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls
        back to wall-clock time." With no clock call at all, a rental whose
        `start_date` is 2026-08-01 shows zero chargeable days; a drifting
        wall-clock read on any later date would accrue at least one 1200-cent
        period.

        Design: Corner/cross_cutting_layers/logical_clock_default_is_fixed_at_start
        """
        customer = make_customer(account_no="ACC-LA3", name="Clock Co",
                                 terms="CASH")
        asset = make_cylinder(serial_no="CYL-LA3", gas_grade="NITROGEN",
                              size="MEDIUM")
        rental = make_demurrage_rental(customer["id"], asset["id"],
                                       start_date="2026-08-01", grace_days=5)
        assert get_rental(rental["id"])["accrued_unbilled_cents"] == 0, \
            "logical clock == startup default == start_date: 0 days held"

"""Daily settlement dual variants, teardown gating, the fair's terminal
lifecycle, and the begin-checklists clock gate (PRD sections 3.4 and 3.8).

Covers design instances:
  Difficulty/dual_variant_calc/settlement_projected_vs_recognized_diverge_on_breakage
  Corner/errors/teardown_blocked_until_days_reconciled
  Corner/state_machines/fair_full_lifecycle_terminal_lockdown
  Corner/validations/begin_checklists_requires_current_date
"""
from test_helpers import (
    ApiErrorId,
    make_crew_headers,
    make_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def _setup_day_with_partial_redemption(api, name):
    """Open day with one 10-credit bundle sale (subtotal 990, fee 59, total
    1049) and exactly 3 credits boarded on a completed cycle."""
    ctx = fx.setup_open_day(name)
    sup, op, clerk = ctx["sup"], ctx["op"], ctx["clerk"]
    ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
    prod = fx.create_product(sup, name="Credits", base_price_cents=100)
    sale = fx.sell(clerk, prod["id"], day_id, quantity=10)
    for _ in range(3):
        fx.queue_redemption(op, sale["id"], ride_id)
    fx.run_cycle(op, ride_id, day_id)
    ctx.update({"prod": prod, "sale": sale})
    return ctx


class TestSettlementDualVariant:
    def test_close_gates_computes_projected_variant(self, api):
        """PRD section 3.8: "The `gross_sales_cents` is the sum of
        `total_charged_cents` over every sale of the day, voided sales
        included. The `voided_cents` is the same sum restricted to `VOIDED`
        sales. The `projected_revenue_cents` is the gross minus the voided —
        it recognizes every non-voided sale at full face value regardless of
        how many credits were ever redeemed." Also: "every credit-bearing sale
        still `ACTIVE` forfeits its remaining balance — `credits_forfeited`
        rises by the full `credits_remaining`, `credits_remaining` falls to
        zero, and the sale moves to `EXPIRED`."

        Design: Difficulty/dual_variant_calc/settlement_projected_vs_recognized_diverge_on_breakage
        """
        ctx = _setup_day_with_partial_redemption(api, "B")
        sup = ctx["sup"]
        day_id = ctx["day"]["id"]
        closed = validate_success(api.close_gates(day_id, {}, make_manager_headers(sup["id"])))
        assert closed["posture"] == "CLOSED"
        assert closed["gross_sales_cents"] == 1049
        assert closed["voided_cents"] == 0
        assert closed["projected_revenue_cents"] == 1049, (
            "the projected variant recognizes the full face value at close-gates")
        sale = fx.get_sale(sup, ctx["sale"]["id"])
        assert sale["status"] == "EXPIRED"
        assert sale["credits_redeemed"] == 3
        assert sale["credits_forfeited"] == 7
        assert sale["credits_remaining"] == 0
        ride = fx.get_ride(sup, ctx["ride"]["id"])
        assert ride["daily_status"] == "CLOSED"

    def test_reconcile_computes_recognized_variant_and_breakage(self, api):
        """PRD section 3.8: "otherwise — for credit-bearing sales, including
        `EXPIRED` ones contributing with their final `credits_redeemed` — its
        full `service_fee_cents` plus its `subtotal_cents` pro-rated by the
        ratio of `credits_redeemed` to `credits_granted`, with that pro-rated
        amount rounded half-up to whole cents per sale before any summation"
        and "The `breakage_cents` is then the projected revenue minus the
        recognized revenue — the value of credits that were sold but never
        redeemed — and `reconciliation_flagged` is set true when the breakage
        strictly exceeds 1,000 cents".

        recognized = 59 + round_half_up(990 * 3/10) = 59 + 297 = 356;
        breakage = 1049 - 356 = 693 (not > 1000, so unflagged) — the same
        sales data, two defensible variants, different revenue.

        Design: Difficulty/dual_variant_calc/settlement_projected_vs_recognized_diverge_on_breakage
        """
        ctx = _setup_day_with_partial_redemption(api, "Bb")
        sup = ctx["sup"]
        day_id = ctx["day"]["id"]
        validate_success(api.close_gates(day_id, {}, make_manager_headers(sup["id"])))
        rec = validate_success(api.reconcile_day(day_id, {}, make_manager_headers(sup["id"])))
        assert rec["posture"] == "RECONCILED"
        assert rec["recognized_revenue_cents"] == 356
        assert rec["breakage_cents"] == 693
        assert rec["reconciliation_flagged"] is False


class TestTeardownGate:
    def test_teardown_blocked_until_days_reconciled(self, api):
        """PRD section 3.8: "no operating day may still be in flight: a day in
        `CHECKLIST_PHASE`, `OPEN`, `WEATHER_HOLD`, or `CLOSED` blocks the move
        with `ERR_DAYS_STILL_ACTIVE`, while `SCHEDULED` and `RECONCILED` days
        do not."

        Design: Corner/errors/teardown_blocked_until_days_reconciled
        """
        ctx = fx.setup_open_day("ER10")
        sup = ctx["sup"]
        day_id = ctx["day"]["id"]
        validate_success(api.close_gates(day_id, {}, make_manager_headers(sup["id"])))
        fx.set_clock(fx.TEARDOWN_CLOCK_ISO)
        resp = api.begin_teardown(sup["fair_id"], {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_DAYS_STILL_ACTIVE, 422)
        rec = validate_success(api.reconcile_day(day_id, {}, make_manager_headers(sup["id"])))
        assert rec["posture"] == "RECONCILED"
        assert rec["gross_sales_cents"] == 0
        assert rec["recognized_revenue_cents"] == 0
        assert rec["breakage_cents"] == 0
        assert rec["reconciliation_flagged"] is False
        fair = validate_success(api.begin_teardown(sup["fair_id"], {},
                                                   make_manager_headers(sup["id"])))
        assert fair["status"] == "TEARDOWN"


class TestFairFullLifecycle:
    def test_archive_lockdown_and_dismantle_gate(self, api):
        """PRD section 3.8: "With every ride of the fair `DISMANTLED` — any
        straggler blocks the move with `ERR_RIDES_NOT_DISMANTLED` — the
        `FairManager` archives the fair, moving it from `TEARDOWN`
        (`ERR_FAIR_INVALID_STATE` from any other status) to the terminal
        `ARCHIVED`" and "Dismantling moves `setup_status` to `DISMANTLED`,
        moves the `license_status` to `REVOKED` if it is not already there — a
        dismantled ride cannot hold a license — and advances the ride's
        `version`." PRD section 3.2: "requesting from any fair status other
        than `SETUP` is `ERR_FAIR_INVALID_STATE`."

        Design: Corner/state_machines/fair_full_lifecycle_terminal_lockdown
        """
        ctx = fx.setup_permitted_fair("SM2")
        sup, crew, ride = ctx["sup"], ctx["crew"], ctx["ride"]
        fx.set_clock(fx.TEARDOWN_CLOCK_ISO)
        fx.book_teardown_shift(sup, crew)
        fair = validate_success(api.begin_teardown(sup["fair_id"], {},
                                                   make_manager_headers(sup["id"])))
        assert fair["status"] == "TEARDOWN"
        resp = api.archive_fair(sup["fair_id"], {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_RIDES_NOT_DISMANTLED, 422)
        ride = validate_success(api.dismantle_ride(ride["id"], {},
                                                   make_crew_headers(crew["id"])))
        assert ride["setup_status"] == "DISMANTLED"
        assert ride["license_status"] == "REVOKED"
        fair = validate_success(api.archive_fair(sup["fair_id"], {},
                                                 make_manager_headers(sup["id"])))
        assert fair["status"] == "ARCHIVED"
        resp = api.request_permit(sup["fair_id"], {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_FAIR_INVALID_STATE, 409)


class TestBeginChecklistsClockGate:
    def test_begin_checklists_requires_current_date(self, api):
        """PRD section 3.4: "beginning on any date other than the day's own
        `date` — as read from the logical clock — is `ERR_DAY_NOT_TODAY`."

        The day is legally scheduled for 2026-08-04, but the logical clock
        reads 2026-08-03, so the checklist phase cannot begin yet.

        Design: Corner/validations/begin_checklists_requires_current_date
        """
        ctx = fx.setup_permitted_fair("V3", operator_functions=None)
        sup = ctx["sup"]
        day = validate_success(api.create_operating_day(
            {"fair_id": sup["fair_id"], "date": "2026-08-04", "max_attendance": 100},
            make_manager_headers(sup["id"])), 201)
        fx.set_clock(fx.OPERATING_CLOCK_ISO)
        resp = api.begin_checklists(day["id"], {}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_DAY_NOT_TODAY, 422)
        day_after = fx.get_day(sup, day["id"])
        assert day_after["posture"] == "SCHEDULED"

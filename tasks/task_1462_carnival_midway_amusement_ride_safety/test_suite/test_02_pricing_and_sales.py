"""Ticket pricing: marginal bundle tiers, the pre-fee service fee, sale
lifecycle gates, and settlement input filtering (PRD sections 3.5 and 3.8).

Covers design instances:
  Difficulty/combinatorial_formula/bundle_marginal_tiers_with_per_unit_pre_rounding
  Difficulty/combinatorial_formula/service_fee_computed_on_pre_fee_subtotal
  Difficulty/boundary_precision_check/day_attendance_cap_exact_boundary
  Corner/calculations/bundle_tier_boundary_9_vs_10_credits
  Corner/calculations/settlement_voided_sale_and_close_cascade
  Corner/errors/day_create_capacity_duplicate_and_window_errors
  Corner/errors/sale_rejected_while_day_scheduled
"""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_clerk_headers,
    make_manager_headers,
    make_operator_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


class TestBundleMarginalTiers:
    def test_thirty_credits_per_unit_pre_rounding(self, api):
        """PRD section 3.5: "the next fifteen credits — the tenth through the
        twenty-fourth — are each priced at nine-tenths of the base price, with
        that per-credit price rounded half-up to whole cents before being
        multiplied by the tier count; and every credit beyond the twenty-fourth
        is each priced at eight-tenths of the base price, likewise rounded
        half-up per credit before multiplying."

        30 credits at base 95: 9*95 + 15*round_half_up(85.5)=86 + 6*76
        = 855 + 1290 + 456 = 2601.

        Design: Difficulty/combinatorial_formula/bundle_marginal_tiers_with_per_unit_pre_rounding
        """
        ctx = fx.setup_open_day("C2")
        sup, clerk = ctx["sup"], ctx["clerk"]
        prod = fx.create_product(sup, name="Bundle95", base_price_cents=95)
        sale = fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=30)
        assert sale["subtotal_cents"] == 2601, (
            f"30 credits at base 95 must subtotal 2601, got {sale['subtotal_cents']}")
        assert sale["credits_granted"] == 30
        assert sale["credits_remaining"] == 30

    def test_thirty_credits_fee_and_total(self, api):
        """PRD section 3.5: "The service fee is then six percent of the pre-fee
        subtotal, rounded half-up to whole cents, but never less than fifty
        cents... The `total_charged_cents` is the subtotal plus the service
        fee."

        round_half_up(2601 * 0.06) = round_half_up(156.06) = 156; total 2757.

        Design: Difficulty/combinatorial_formula/bundle_marginal_tiers_with_per_unit_pre_rounding
        """
        ctx = fx.setup_open_day("C2b")
        sup, clerk = ctx["sup"], ctx["clerk"]
        prod = fx.create_product(sup, name="Bundle95", base_price_cents=95)
        sale = fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=30)
        assert sale["service_fee_cents"] == 156
        assert sale["total_charged_cents"] == 2757


class TestServiceFeePreFeeSubtotal:
    def test_ticket_sale_hits_fee_floor(self, api):
        """PRD section 3.5: "The service fee is then six percent of the pre-fee
        subtotal, rounded half-up to whole cents, but never less than fifty
        cents."

        A RIDE_TICKET at base 300 x 1: subtotal 300, 6% is 18 -> floor 50,
        total 350.

        Design: Difficulty/combinatorial_formula/service_fee_computed_on_pre_fee_subtotal
        """
        ctx = fx.setup_open_day("C3")
        sup, clerk = ctx["sup"], ctx["clerk"]
        prod_t = fx.create_product(sup, name="Ticket300", kind="RIDE_TICKET",
                                   base_price_cents=300)
        sale = fx.sell(clerk, prod_t["id"], ctx["day"]["id"], quantity=1)
        assert sale["subtotal_cents"] == 300
        assert sale["service_fee_cents"] == 50, (
            f"6% of 300 = 18 must be raised to the 50-cent floor; got "
            f"{sale['service_fee_cents']}")
        assert sale["total_charged_cents"] == 350

    def test_bundle_fee_computed_on_pre_fee_subtotal(self, api):
        """PRD section 3.5: "The evaluation order is pinned: the fee is computed
        strictly on the pre-fee subtotal, because defining it on the grand total
        would be circular."

        10 credits at base 100: subtotal 9*100 + 1*90 = 990;
        round_half_up(990 * 0.06) = 59 (a total-inclusive reading would give 62).

        Design: Difficulty/combinatorial_formula/service_fee_computed_on_pre_fee_subtotal
        """
        ctx = fx.setup_open_day("C3b")
        sup, clerk = ctx["sup"], ctx["clerk"]
        prod_b = fx.create_product(sup, name="Bundle100", base_price_cents=100)
        sale = fx.sell(clerk, prod_b["id"], ctx["day"]["id"], quantity=10)
        assert sale["subtotal_cents"] == 990
        assert sale["service_fee_cents"] == 59, (
            f"fee must be round_half_up(990 * 0.06) = 59, not a fee-on-total "
            f"value; got {sale['service_fee_cents']}")
        assert sale["total_charged_cents"] == 1049


class TestBundleTierBoundary:
    def test_nine_credits_no_discount(self, api):
        """PRD section 3.5: "the first nine credits are each priced at the full
        base price".

        9 credits at base 95: subtotal 855, fee round_half_up(855*0.06)=51,
        total 906.

        Design: Corner/calculations/bundle_tier_boundary_9_vs_10_credits
        """
        ctx = fx.setup_open_day("CA2")
        sup, clerk = ctx["sup"], ctx["clerk"]
        prod = fx.create_product(sup, name="Bundle95", base_price_cents=95)
        sale = fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=9)
        assert sale["subtotal_cents"] == 855
        assert sale["total_charged_cents"] == 906

    def test_tenth_credit_enters_tier_two_marginally(self, api):
        """PRD section 3.5: "the next fifteen credits — the tenth through the
        twenty-fourth — are each priced at nine-tenths of the base price, with
        that per-credit price rounded half-up to whole cents before being
        multiplied by the tier count".

        10 credits at base 95: 855 + round_half_up(85.5)=86 -> subtotal 941,
        fee round_half_up(941*0.06)=56, total 997.

        Design: Corner/calculations/bundle_tier_boundary_9_vs_10_credits
        """
        ctx = fx.setup_open_day("CA2b")
        sup, clerk = ctx["sup"], ctx["clerk"]
        prod = fx.create_product(sup, name="Bundle95", base_price_cents=95)
        sale = fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=10)
        assert sale["subtotal_cents"] == 941
        assert sale["total_charged_cents"] == 997


class TestDayAttendanceCap:
    def test_sale_reaching_exact_cap_succeeds(self, api):
        """PRD section 3.5: "if the day's `attendance_count` has already reached
        `max_attendance`, the sale is rejected with `ERR_DAY_AT_CAPACITY` — the
        sale that brings attendance exactly to the cap still succeeds, and the
        next one fails."

        Design: Difficulty/boundary_precision_check/day_attendance_cap_exact_boundary
        """
        ctx = fx.setup_open_day("M", day_overrides={"max_attendance": 2})
        sup, clerk = ctx["sup"], ctx["clerk"]
        prod = fx.create_product(sup, name="Ticket500", kind="RIDE_TICKET",
                                 base_price_cents=500)
        sale1 = fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=1)
        assert sale1["status"] == "ACTIVE"
        sale2 = fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=1,
                        holder_height_in=55)
        assert sale2["status"] == "ACTIVE"
        day = fx.get_day(sup, ctx["day"]["id"])
        assert day["attendance_count"] == 2

    def test_sale_beyond_cap_rejected_and_count_unchanged(self, api):
        """PRD section 3.5: "the sale that brings attendance exactly to the cap
        still succeeds, and the next one fails."

        Design: Difficulty/boundary_precision_check/day_attendance_cap_exact_boundary
        """
        ctx = fx.setup_open_day("Mb", day_overrides={"max_attendance": 2})
        sup, clerk = ctx["sup"], ctx["clerk"]
        prod = fx.create_product(sup, name="Ticket500", kind="RIDE_TICKET",
                                 base_price_cents=500)
        fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=1)
        fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=1, holder_height_in=55)
        resp = api.create_sale(
            {"product_id": prod["id"], "operating_day_id": ctx["day"]["id"],
             "quantity": 1, "holder_height_in": 50},
            make_clerk_headers(clerk["id"]))
        validate_error(resp, ApiErrorId.ERR_DAY_AT_CAPACITY, 422)
        day = fx.get_day(sup, ctx["day"]["id"])
        assert day["attendance_count"] == 2, (
            f"rejected sale must not move attendance; got {day['attendance_count']}")


class TestDayCreateValidation:
    def test_max_attendance_above_midway_capacity_rejected(self, api):
        """PRD section 3.4: "the cap must be at least one and no greater than
        the fair's `midway_capacity` (`ERR_CAPACITY_ABOVE_MIDWAY`)".

        Design: Corner/errors/day_create_capacity_duplicate_and_window_errors
        """
        ctx = fx.setup_permitted_fair("ER2", operator_functions=None)
        sup = ctx["sup"]
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        resp = api.create_operating_day(
            {"fair_id": sup["fair_id"], "date": "2026-08-03", "max_attendance": 301},
            make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_CAPACITY_ABOVE_MIDWAY, 422)

    def test_duplicate_operating_day_rejected(self, api):
        """PRD section 3.4: "the date must be unique within the fair
        (`ERR_DUPLICATE_OPERATING_DAY`)".

        Design: Corner/errors/day_create_capacity_duplicate_and_window_errors
        """
        ctx = fx.setup_permitted_fair("ER2b", operator_functions=None)
        sup = ctx["sup"]
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        payload = {"fair_id": sup["fair_id"], "date": "2026-08-03", "max_attendance": 100}
        validate_success(api.create_operating_day(payload, make_manager_headers(sup["id"])), 201)
        resp = api.create_operating_day(
            {**payload, "max_attendance": 50}, make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPERATING_DAY, 409)

    def test_date_before_opening_rejected(self, api):
        """PRD section 3.4: "must fall between `opening_date` and `closing_date`
        inclusive, and must not be in the past".

        A date before opening_date violates the request-shape date window, a
        malformed-body rejection with ERR_INVALID_REQUEST (400).

        Design: Corner/errors/day_create_capacity_duplicate_and_window_errors
        """
        ctx = fx.setup_permitted_fair("ER2c", operator_functions=None)
        sup = ctx["sup"]
        fx.set_clock(fx.INSPECTION_CLOCK_ISO)
        resp = api.create_operating_day(
            {"fair_id": sup["fair_id"], "date": "2026-08-02", "max_attendance": 50},
            make_manager_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestSalePostureGate:
    def test_sale_into_scheduled_day_rejected(self, api):
        """PRD section 3.5: "A day whose posture is not `OPEN` rejects the sale
        with `ERR_INVALID_DAY_POSTURE`."

        Design: Corner/errors/sale_rejected_while_day_scheduled
        """
        ctx = fx.setup_permitted_fair("ER3", operator_functions=None, include_clerk=True)
        sup, clerk = ctx["sup"], ctx["clerk"]
        fx.set_clock(fx.OPERATING_CLOCK_ISO)
        day = get_success_data(api.create_operating_day(
            {"fair_id": sup["fair_id"], "date": "2026-08-03", "max_attendance": 100},
            make_manager_headers(sup["id"])))
        prod = fx.create_product(sup, name="Credits")
        resp = api.create_sale(
            {"product_id": prod["id"], "operating_day_id": day["id"],
             "quantity": 5, "holder_height_in": 60},
            make_clerk_headers(clerk["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_DAY_POSTURE, 409)
        day_after = fx.get_day(sup, day["id"])
        assert day_after["attendance_count"] == 0


class TestSettlementVoidedSale:
    def _setup_two_sales(self, api, name):
        ctx = fx.setup_open_day(name)
        sup, clerk, op = ctx["sup"], ctx["clerk"], ctx["op"]
        prod_b = fx.create_product(sup, name="Bundle100", base_price_cents=100)
        prod_t = fx.create_product(sup, name="Ticket300", kind="RIDE_TICKET",
                                   base_price_cents=300)
        sale_a = fx.sell(clerk, prod_b["id"], ctx["day"]["id"], quantity=10)
        sale_b = fx.sell(clerk, prod_t["id"], ctx["day"]["id"], quantity=1)
        red_a = fx.queue_redemption(op, sale_a["id"], ctx["ride"]["id"])
        ctx.update({"prod_b": prod_b, "prod_t": prod_t, "sale_a": sale_a,
                    "sale_b": sale_b, "red_a": red_a})
        return ctx

    def test_void_drops_attendance_and_double_void_rejected(self, api):
        """PRD section 3.5: "A successful void moves the sale to `VOIDED`...
        subtracts one from the day's `attendance_count`" and "voiding a
        `VOIDED` or `EXPIRED` sale is `ERR_SALE_NOT_ACTIVE`".

        Design: Corner/calculations/settlement_voided_sale_and_close_cascade
        """
        ctx = self._setup_two_sales(api, "CA3")
        sup, clerk = ctx["sup"], ctx["clerk"]
        day_id = ctx["day"]["id"]
        day_before = fx.get_day(sup, day_id)
        assert day_before["attendance_count"] == 2
        voided = validate_success(api.void_sale(ctx["sale_b"]["id"], {},
                                                make_clerk_headers(clerk["id"])))
        assert voided["status"] == "VOIDED"
        day_after = fx.get_day(sup, day_id)
        assert day_after["attendance_count"] == 1
        resp = api.void_sale(ctx["sale_b"]["id"], {}, make_clerk_headers(clerk["id"]))
        validate_error(resp, ApiErrorId.ERR_SALE_NOT_ACTIVE, 409)

    def test_close_and_reconcile_with_voided_and_unboarded_sales(self, api):
        """PRD section 3.8: "The `gross_sales_cents` is the sum of
        `total_charged_cents` over every sale of the day, voided sales
        included. The `voided_cents` is the same sum restricted to `VOIDED`
        sales. The `projected_revenue_cents` is the gross minus the voided" and
        "each contributes: zero if `VOIDED`; ... otherwise — for credit-bearing
        sales... its full `service_fee_cents` plus its `subtotal_cents`
        pro-rated by the ratio of `credits_redeemed` to `credits_granted`".

        Sale A (10-credit bundle, total 1049, never boarded) + sale B (ride
        ticket, total 350, voided): gross 1399, voided 350, projected 1049,
        recognized 59 + round_half_up(990 * 0/10) = 59, breakage 990,
        flagged false.

        Design: Corner/calculations/settlement_voided_sale_and_close_cascade
        """
        ctx = self._setup_two_sales(api, "CA3b")
        sup, clerk = ctx["sup"], ctx["clerk"]
        day_id = ctx["day"]["id"]
        validate_success(api.void_sale(ctx["sale_b"]["id"], {}, make_clerk_headers(clerk["id"])))
        closed = validate_success(api.close_gates(day_id, {}, make_manager_headers(sup["id"])))
        assert closed["gross_sales_cents"] == 1399
        assert closed["voided_cents"] == 350
        assert closed["projected_revenue_cents"] == 1049
        red_a = fx.get_redemption(sup, ctx["red_a"]["id"])
        assert red_a["status"] == "EXPIRED", (
            f"QUEUED redemption must expire at close-gates; got {red_a['status']}")
        sale_a = fx.get_sale(sup, ctx["sale_a"]["id"])
        assert sale_a["status"] == "EXPIRED"
        assert sale_a["credits_forfeited"] == 10
        assert sale_a["credits_remaining"] == 0
        reconciled = validate_success(api.reconcile_day(day_id, {}, make_manager_headers(sup["id"])))
        assert reconciled["recognized_revenue_cents"] == 59
        assert reconciled["breakage_cents"] == 990
        assert reconciled["reconciliation_flagged"] is False
        ride = fx.get_ride(sup, ctx["ride"]["id"])
        assert ride["daily_status"] == "CLOSED"

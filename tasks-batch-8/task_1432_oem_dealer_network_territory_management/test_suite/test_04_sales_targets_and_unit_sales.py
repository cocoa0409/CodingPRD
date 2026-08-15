"""Quarterly sales targets, unit-sale adjudication, and tier discounts."""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_sale,
    assert_sales_target,
    create_advance,
    create_dealer,
    create_sales_target,
    create_sales_target_payload,
    get_advance,
    get_dealer,
    get_sales_target,
    get_unit_sale,
    make_dealer_user_headers,
    report_sale,
    set_clock,
    setup_dealer_with_open_target,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTargetCloseBoundary:
    """The close gate compares achieved_units to target_units with >= ."""

    def test_exact_attainment_closes_met(self, api, sales_ops_headers):
        """PRD section 3.3: "If `achieved_units` is at least `target_units` — equality counts as met — the target closes as `CLOSED_MET`; otherwise it closes as `CLOSED_MISSED`."

        Design: Difficulty/boundary_precision_check/target_close_exact_attainment_is_met
        """
        ctx = setup_dealer_with_open_target("DL-T1", target_units=2)
        dealer = ctx["dealer"]
        target = ctx["target"]
        accept_sale(report_sale(dealer["id"], "B-1", "2026-08-05")["id"])
        accept_sale(report_sale(dealer["id"], "B-2", "2026-08-06")["id"])
        set_clock("2026-10-01T00:00:00Z")

        closed = validate_success(api.close_sales_target(target["id"],
                                                         sales_ops_headers),
                                  200)
        assert_sales_target(closed)
        assert closed["achieved_units"] == 2
        assert closed["status"] == "CLOSED_MET", (
            "equality counts as met: achieved 2 == target 2 must close "
            f"CLOSED_MET, got {closed['status']}"
        )

    def test_ratio_at_silver_threshold_locks_silver_rate(
            self, api, sales_ops_headers):
        """PRD section 3.3: "it projects this sale as accepted by taking the target's current `achieved_units` plus one as the counted units, dividing by the target's `target_units` to get an attainment ratio, selecting the tier rate — eight percent (0.08) when the ratio is at least 1.2 (`GOLD` attainment), five percent (0.05) when the ratio is at least 1.0 (`SILVER` attainment), and two percent (0.02) otherwise (`BRONZE` attainment) — and multiplying the `list_price_cents` by that rate, rounding half-up to a whole cent."
        PRD section 3.3: "the tier rate is selected from the same 1.2 and 1.0 thresholds and the same 0.08, 0.05, and 0.02 rates, and that rate is locked into the target's `final_discount_rate`."

        Design: Difficulty/boundary_precision_check/target_close_exact_attainment_is_met
        """
        ctx = setup_dealer_with_open_target("DL-T2", target_units=2)
        dealer = ctx["dealer"]
        target = ctx["target"]
        accept_sale(report_sale(dealer["id"], "B-1", "2026-08-05")["id"])
        accept_sale(report_sale(dealer["id"], "B-2", "2026-08-06")["id"])
        set_clock("2026-10-01T00:00:00Z")

        closed = validate_success(api.close_sales_target(target["id"],
                                                         sales_ops_headers),
                                  200)
        # ratio 2/2 = 1.0: at least 1.0 (SILVER) but below 1.2 (GOLD).
        assert closed["final_discount_rate"] == pytest.approx(0.05, abs=1e-9)

    def test_target_close_below_target_is_missed(self, api, sales_ops_headers):
        """PRD section 3.3: "If `achieved_units` is at least `target_units` — equality counts as met — the target closes as `CLOSED_MET`; otherwise it closes as `CLOSED_MISSED`."
        PRD section 3.3: "the tier rate is selected from the same 1.2 and 1.0 thresholds and the same 0.08, 0.05, and 0.02 rates, and that rate is locked into the target's `final_discount_rate`."

        Design: Corner/state_machines/target_close_below_target_is_missed
        """
        ctx = setup_dealer_with_open_target("DL-SM3", target_units=2)
        dealer = ctx["dealer"]
        target = ctx["target"]
        accept_sale(report_sale(dealer["id"], "SM-3", "2026-08-05")["id"])
        set_clock("2026-10-01T00:00:00Z")

        closed = validate_success(api.close_sales_target(target["id"],
                                                         sales_ops_headers),
                                  200)
        assert closed["achieved_units"] == 1
        assert closed["status"] == "CLOSED_MISSED"
        # ratio 1/2 = 0.5: below the 1.0 SILVER threshold -> BRONZE rate.
        assert closed["final_discount_rate"] == pytest.approx(0.02, abs=1e-9)


class TestTargetClosePreconditions:

    def test_target_double_close_rejected(self, api, sales_ops_headers):
        """PRD section 3.3: "Closing requires the target to still be `OPEN` (`ERR_TARGET_NOT_OPEN`) and requires the current logical date to be on or after the first day of the quarter following the target's `(period_year, period_quarter)` — an early close is rejected with `ERR_QUARTER_NOT_ENDED`."

        Design: Corner/state_machines/target_double_close_rejected
        """
        ctx = setup_dealer_with_open_target("DL-SM2", target_units=1)
        dealer = ctx["dealer"]
        target = ctx["target"]
        accept_sale(report_sale(dealer["id"], "SM-2", "2026-08-05")["id"])
        set_clock("2026-10-01T00:00:00Z")
        closed = validate_success(api.close_sales_target(target["id"],
                                                         sales_ops_headers),
                                  200)
        assert closed["status"] == "CLOSED_MET"

        resp = api.close_sales_target(target["id"], sales_ops_headers)
        validate_error(resp, ApiErrorId.ERR_TARGET_NOT_OPEN)

        unchanged = get_sales_target(target["id"])
        assert unchanged["status"] == "CLOSED_MET"

    def test_quarter_not_ended_blocks_close(self, api, sales_ops_headers):
        """PRD section 3.3: "Closing requires the target to still be `OPEN` (`ERR_TARGET_NOT_OPEN`) and requires the current logical date to be on or after the first day of the quarter following the target's `(period_year, period_quarter)` — an early close is rejected with `ERR_QUARTER_NOT_ENDED`."

        Design: Corner/validations/quarter_not_ended_blocks_close
        """
        # Q3 2026 ends 2026-09-30; the following quarter starts 2026-10-01.
        set_clock("2026-09-15T00:00:00Z")
        ctx = setup_dealer_with_open_target("DL-QE1", target_units=2)
        target = ctx["target"]

        resp = api.close_sales_target(target["id"], sales_ops_headers)
        validate_error(resp, ApiErrorId.ERR_QUARTER_NOT_ENDED)

        unchanged = get_sales_target(target["id"])
        assert unchanged["status"] == "OPEN"

    def test_duplicate_target_rejected(self, api, sales_ops_headers):
        """PRD section 3.3: "Only one target may exist for a given dealer, year, and quarter; a duplicate is rejected with `ERR_DUPLICATE_TARGET`."

        Design: Corner/validations/duplicate_target_rejected
        """
        dealer = create_dealer("DL-DT1", name="Dealer DT1")
        validate_success(
            api.create_sales_target(
                create_sales_target_payload(
                    dealer_id=dealer["id"], period_year=2026,
                    period_quarter=3, target_units=5),
                sales_ops_headers,
            ),
            expected_status=201,
        )

        resp = api.create_sales_target(
            create_sales_target_payload(
                dealer_id=dealer["id"], period_year=2026, period_quarter=3,
                target_units=9),
            sales_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TARGET)


class TestUnitSaleDecisions:

    def test_sale_decide_on_accepted_rejected(self, api, sales_ops_headers):
        """PRD section 3.3: "Acceptance — a `decision` of `ACCEPT` — requires the sale to be `REPORTED` (`ERR_SALE_NOT_REPORTED`) and requires a sales target for the dealer and the sale's quarter to exist and still be `OPEN` (`ERR_TARGET_NOT_OPEN`)."

        Design: Corner/state_machines/sale_decide_on_accepted_rejected
        """
        ctx = setup_dealer_with_open_target("DL-SM4", target_units=5)
        dealer = ctx["dealer"]
        sale = report_sale(dealer["id"], "SM-4", "2026-08-05")
        accept_sale(sale["id"])

        resp = api.decide_unit_sale(sale["id"], {"decision": "REJECT"},
                                    sales_ops_headers)
        validate_error(resp, ApiErrorId.ERR_SALE_NOT_REPORTED)

        unchanged = get_unit_sale(sale["id"])
        assert unchanged["status"] == "ACCEPTED"

    def test_sale_void_from_reported_rejected(self, api, sales_ops_headers):
        """PRD section 3.3: "If the linked advance is sitting in `PAID_OFF` because this sale's acceptance paid it off, the void is rejected with `ERR_SALE_PAYOFF_LOCKED`; a void attempted on a sale that is not `ACCEPTED` fails with `ERR_SALE_NOT_ACCEPTED`."

        Design: Corner/validations/sale_void_from_reported_rejected
        """
        ctx = setup_dealer_with_open_target("DL-VD1", target_units=5)
        dealer = ctx["dealer"]
        sale = report_sale(dealer["id"], "VD-1", "2026-08-05")

        resp = api.void_unit_sale(sale["id"], sales_ops_headers)
        validate_error(resp, ApiErrorId.ERR_SALE_NOT_ACCEPTED)

        unchanged = get_unit_sale(sale["id"])
        assert unchanged["status"] == "REPORTED"

    def test_duplicate_unit_serial_sale_rejected(self, api,
                                                 oem_admin_headers):
        """PRD section 3.3: "The serial number is unique per dealer among sales that are not `REJECTED` and not `VOIDED`; a live duplicate is rejected with `ERR_DUPLICATE_UNIT_SERIAL`."

        Design: Corner/validations/duplicate_unit_serial_sale_rejected
        """
        ctx = setup_dealer_with_open_target("DL-DS1", target_units=9)
        dealer = ctx["dealer"]
        report_sale(dealer["id"], "DS-1", "2026-08-05")

        resp = api.create_unit_sale(
            {
                "dealer_id": dealer["id"],
                "unit_serial": "DS-1",
                "sale_date": "2026-08-06",
                "list_price_cents": 12000,
            },
            make_dealer_user_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIT_SERIAL)

        data, meta = validate_paginated(
            api.list_unit_sales(oem_admin_headers,
                                params={"dealer_id": dealer["id"]}))
        assert meta["total_count"] == 1, (
            "only the first sale may persist; got "
            f"total_count={meta['total_count']}"
        )


class TestAttainmentAcceptVoidInvariant:
    """achieved_units tracks the live count of ACCEPTED sales exactly."""

    def test_accept_then_void_returns_attainment_to_zero(
            self, api, sales_ops_headers):
        """PRD section 3.3: "On acceptance the sale moves to `ACCEPTED`, the target's `achieved_units` increases by one, and — crucially — the acceptance triggers the **retail-sale payoff cascade**: any floor-plan advance for the same dealer and `unit_serial` in `OPEN`, `CURTAILED`, or `PAST_DUE` status is paid off in full, moving to `PAID_OFF` with its `paid_curtailments_cents` set equal to its `advance_cents` and the dealer's `floorplan_utilization_cents` reduced by the remaining principal."
        PRD section 3.3: "An accepted sale can later be voided by `OemSalesOps`, moving it from `ACCEPTED` to `VOIDED` and decrementing the target's `achieved_units` by one — but only if it was not itself the cause of a floor-plan payoff."

        Design: Difficulty/compensating_invariant/target_attainment_accept_void_invariant
        """
        ctx = setup_dealer_with_open_target("DL-S1", target_units=5)
        dealer = ctx["dealer"]
        target = ctx["target"]
        assert get_sales_target(target["id"])["achieved_units"] == 0

        sale = report_sale(dealer["id"], "W-1", "2026-08-03",
                           list_price_cents=50000)
        accept_sale(sale["id"])
        assert get_sales_target(target["id"])["achieved_units"] == 1

        voided = validate_success(api.void_unit_sale(sale["id"],
                                                     sales_ops_headers), 200)
        assert voided["status"] == "VOIDED"
        assert get_sales_target(target["id"])["achieved_units"] == 0, (
            "the accept/void pair must return achieved_units to its "
            "pre-action value"
        )

    def test_void_decrements_attainment_among_multiple_sales(
            self, api, sales_ops_headers):
        """PRD section 3.3: "An accepted sale can later be voided by `OemSalesOps`, moving it from `ACCEPTED` to `VOIDED` and decrementing the target's `achieved_units` by one — but only if it was not itself the cause of a floor-plan payoff."

        Design: Difficulty/compensating_invariant/target_attainment_accept_void_invariant
        """
        ctx = setup_dealer_with_open_target("DL-S2", target_units=5)
        dealer = ctx["dealer"]
        target = ctx["target"]

        sale1 = report_sale(dealer["id"], "W-1", "2026-08-03")
        sale2 = report_sale(dealer["id"], "W-2", "2026-08-04")
        accept_sale(sale1["id"])
        accept_sale(sale2["id"])
        assert get_sales_target(target["id"])["achieved_units"] == 2

        validate_success(api.void_unit_sale(sale1["id"], sales_ops_headers),
                         200)
        assert get_sales_target(target["id"])["achieved_units"] == 1
        assert get_unit_sale(sale1["id"])["status"] == "VOIDED"
        assert get_unit_sale(sale2["id"])["status"] == "ACCEPTED"


class TestRetailSalePayoffCascade:
    """Accepting the retail sale of a financed unit pays off its advance."""

    def _setup_financed_accepted_sale(self, api, dealer_code="DL-CS1"):
        ctx = setup_dealer_with_open_target(
            dealer_code, target_units=5, credit_limit_cents=200000)
        dealer = ctx["dealer"]
        advance = create_advance(dealer["id"], "CS-1", 50000)
        sale = report_sale(dealer["id"], "CS-1", "2026-08-03",
                           list_price_cents=80000)
        return ctx, advance, sale

    def test_sale_acceptance_pays_off_floorplan_cascade(
            self, api, sales_ops_headers):
        """PRD section 3.3: "On acceptance the sale moves to `ACCEPTED`, the target's `achieved_units` increases by one, and — crucially — the acceptance triggers the **retail-sale payoff cascade**: any floor-plan advance for the same dealer and `unit_serial` in `OPEN`, `CURTAILED`, or `PAST_DUE` status is paid off in full, moving to `PAID_OFF` with its `paid_curtailments_cents` set equal to its `advance_cents` and the dealer's `floorplan_utilization_cents` reduced by the remaining principal."

        Design: Corner/cross_cutting_layers/sale_acceptance_pays_off_floorplan_cascade
        """
        ctx, advance, sale = self._setup_financed_accepted_sale(api)
        assert get_dealer(ctx["dealer"]["id"])[
            "floorplan_utilization_cents"] == 50000

        accepted = validate_success(
            api.decide_unit_sale(sale["id"], {"decision": "ACCEPT"},
                                 sales_ops_headers), 200)
        assert accepted["status"] == "ACCEPTED"

        advance_after = get_advance(advance["id"])
        assert advance_after["status"] == "PAID_OFF"
        assert advance_after["paid_curtailments_cents"] == 50000
        assert get_dealer(ctx["dealer"]["id"])[
            "floorplan_utilization_cents"] == 0
        assert get_sales_target(ctx["target"]["id"])["achieved_units"] == 1

    def test_void_rejected_when_acceptance_paid_off_advance(
            self, api, sales_ops_headers):
        """PRD section 3.3: "If the linked advance is sitting in `PAID_OFF` because this sale's acceptance paid it off, the void is rejected with `ERR_SALE_PAYOFF_LOCKED`; a void attempted on a sale that is not `ACCEPTED` fails with `ERR_SALE_NOT_ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/sale_void_blocked_by_floorplan_payoff
        """
        ctx, advance, sale = self._setup_financed_accepted_sale(
            api, dealer_code="DL-N1")
        accept_sale(sale["id"])
        assert get_advance(advance["id"])["status"] == "PAID_OFF"

        resp = api.void_unit_sale(sale["id"], sales_ops_headers)
        validate_error(resp, ApiErrorId.ERR_SALE_PAYOFF_LOCKED)

        unchanged = get_unit_sale(sale["id"])
        assert unchanged["status"] == "ACCEPTED", (
            "a rejected void must leave the sale ACCEPTED, got "
            f"{unchanged['status']}"
        )

    def test_payoff_lock_preserves_target_attainment(self, api,
                                                     sales_ops_headers):
        """PRD section 3.3: "An accepted sale can later be voided by `OemSalesOps`, moving it from `ACCEPTED` to `VOIDED` and decrementing the target's `achieved_units` by one — but only if it was not itself the cause of a floor-plan payoff. If the linked advance is sitting in `PAID_OFF` because this sale's acceptance paid it off, the void is rejected with `ERR_SALE_PAYOFF_LOCKED`; a void attempted on a sale that is not `ACCEPTED` fails with `ERR_SALE_NOT_ACCEPTED`."

        Design: Difficulty/cross_entity_state_dependency/sale_void_blocked_by_floorplan_payoff
        """
        ctx, advance, sale = self._setup_financed_accepted_sale(
            api, dealer_code="DL-N2")
        accept_sale(sale["id"])

        resp = api.void_unit_sale(sale["id"], sales_ops_headers)
        validate_error(resp, ApiErrorId.ERR_SALE_PAYOFF_LOCKED)

        assert get_advance(advance["id"])["status"] == "PAID_OFF"
        assert get_sales_target(ctx["target"]["id"])["achieved_units"] == 1, (
            "the blocked void must not decrement achieved_units"
        )


class TestProvisionalVersusFinalDiscount:
    """PROVISIONAL projects the reporting sale as accepted; FINAL uses only
    ACCEPTED sales at close and reconciles the delta onto the dealer."""

    def _setup_two_accepted_sales_then_close(self, api, sales_ops_headers):
        ctx = setup_dealer_with_open_target("DL-A1", target_units=2)
        dealer = ctx["dealer"]
        target = ctx["target"]
        # Sale A: (0 achieved + 1) / 2 = 0.5 -> BRONZE 2% of 100000 = 2000.
        sale_a = report_sale(dealer["id"], "A-100", "2026-08-10",
                             list_price_cents=100000)
        accept_sale(sale_a["id"])
        # Sale B: (1 achieved + 1) / 2 = 1.0 -> SILVER 5% of 100000 = 5000.
        sale_b = report_sale(dealer["id"], "A-101", "2026-08-15",
                             list_price_cents=100000)
        accept_sale(sale_b["id"])
        set_clock("2026-10-01T00:00:00Z")
        closed = validate_success(
            api.close_sales_target(target["id"], sales_ops_headers), 200)
        return ctx, sale_a, sale_b, closed

    def test_provisional_vs_final_discount_divergence(
            self, api, sales_ops_headers, oem_admin_headers):
        """PRD section 3.3: "it projects this sale as accepted by taking the target's current `achieved_units` plus one as the counted units, dividing by the target's `target_units` to get an attainment ratio, selecting the tier rate — eight percent (0.08) when the ratio is at least 1.2 (`GOLD` attainment), five percent (0.05) when the ratio is at least 1.0 (`SILVER` attainment), and two percent (0.02) otherwise (`BRONZE` attainment) — and multiplying the `list_price_cents` by that rate, rounding half-up to a whole cent."
        PRD section 3.3: "Every `ACCEPTED` sale in the quarter then receives its `final_discount_cents`, computed from the locked rate and the sale's `list_price_cents` with half-up rounding to whole cents, and the dealer's `discount_reconciliation_cents` accumulates the sum, across those sales, of each final discount minus its previously booked provisional discount."

        Design: Difficulty/dual_variant_calc/unit_sale_discount_provisional_vs_final
        """
        ctx, sale_a, sale_b, closed = (
            self._setup_two_accepted_sales_then_close(api, sales_ops_headers))

        sale_a_after = validate_success(api.get_unit_sale(sale_a["id"],
                                                          oem_admin_headers),
                                        200)
        sale_b_after = validate_success(api.get_unit_sale(sale_b["id"],
                                                          oem_admin_headers),
                                        200)
        # Close ratio is 2/2 = 1.0 -> SILVER 5% locked.
        assert sale_a_after["provisional_discount_cents"] == 2000, (
            "provisional was booked at creation under the projected ratio "
            f"0.5 (BRONZE 2%), got "
            f"{sale_a_after['provisional_discount_cents']}"
        )
        assert sale_a_after["final_discount_cents"] == 5000
        assert sale_b_after["final_discount_cents"] == 5000

        dealer_after = validate_success(api.get_dealer(ctx["dealer"]["id"],
                                                       oem_admin_headers),
                                        200)
        assert dealer_after["discount_reconciliation_cents"] == 3000, (
            "sum of (final - provisional) = (5000-2000) + (5000-5000) = "
            f"3000, got {dealer_after['discount_reconciliation_cents']}"
        )

    def test_close_locks_rate_and_recomputes_tier(self, api,
                                                  sales_ops_headers,
                                                  oem_admin_headers):
        """PRD section 3.3: "Either way, the close performs the **final** discount reckoning: the attainment ratio is recomputed using the final counted units (`achieved_units`, which reflects `ACCEPTED` sales only, with `VOIDED` sales excluded), the tier rate is selected from the same 1.2 and 1.0 thresholds and the same 0.08, 0.05, and 0.02 rates, and that rate is locked into the target's `final_discount_rate`."
        PRD section 3.3: "Finally, the dealer's `tier` is recomputed from the final ratio — `GOLD`, `SILVER`, or `BRONZE` by the same thresholds — and `Dealer.version` increments."

        Design: Difficulty/dual_variant_calc/unit_sale_discount_provisional_vs_final
        """
        ctx, sale_a, sale_b, closed = (
            self._setup_two_accepted_sales_then_close(api, sales_ops_headers))

        assert closed["status"] == "CLOSED_MET"
        assert closed["final_discount_rate"] == pytest.approx(0.05, abs=1e-9)

        dealer_after = validate_success(api.get_dealer(ctx["dealer"]["id"],
                                                       oem_admin_headers),
                                        200)
        assert dealer_after["tier"] == "SILVER", (
            "final ratio 1.0 is SILVER attainment, got "
            f"{dealer_after['tier']}"
        )
        assert dealer_after["version"] > ctx["dealer"]["version"], (
            "the close must increment Dealer.version"
        )


class TestDealerUserOwnershipOnSales:

    def test_dealer_user_cannot_report_sale_for_other_dealer(
            self, api, oem_admin_headers):
        """PRD section 2.1: "When `X-User-Role` is `DealerUser`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` compare the resource's foreign-key field (for example, the `dealer_id` supplied in a request body, or the `dealer_id` stored on the resource being acted upon) to `X-User-ID`. A mismatch is rejected with `ERR_DEALER_IDENTITY_MISMATCH` (HTTP 403)."

        Design: Corner/validations/dealer_user_cannot_report_sale_for_other_dealer
        """
        actor = create_dealer("DL-ID1", name="Dealer ID1")
        victim = create_dealer("DL-ID2", name="Dealer ID2", region="East")

        resp = api.create_unit_sale(
            {
                "dealer_id": victim["id"],
                "unit_serial": "ID-1",
                "sale_date": "2026-08-05",
                "list_price_cents": 10000,
            },
            make_dealer_user_headers(actor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEALER_IDENTITY_MISMATCH)

    def test_dealer_user_cannot_close_target(self, api):
        """PRD section 2.1: "Beyond header presence, each operation is restricted to specific roles; a caller whose role is not permitted for the endpoint receives `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD section 4: "| POST | `/network/sales-targets/{targetId}/close` | Close after quarter end; lock final discounts and tier | OemSalesOps |"

        Design: Corner/rbac/dealer_user_cannot_close_target
        """
        dealer = create_dealer("DL-RC1", name="Dealer RC1")
        target = create_sales_target(dealer["id"], target_units=5)

        resp = api.close_sales_target(
            target["id"], make_dealer_user_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        unchanged = get_sales_target(target["id"])
        assert unchanged["status"] == "OPEN"

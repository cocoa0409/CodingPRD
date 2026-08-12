"""Regalia pricing arithmetic, payment exactness, deadline late fees, and the
walk-privilege conduct gate on fulfillment."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, api_client,
    setup_ceremony, import_graduate, create_regalia_order, pay_regalia_order,
    setup_graduate_with_strikes, set_clock, get_graduate,
    make_graduate_headers, TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]

GOWN_10000 = [{"item_type": "GOWN", "size": "M", "quantity": 1, "unit_price_cents": 10000}]


class TestRegaliaPricingRoundingOrder:
    def _setup_graduate(self):
        ctx = setup_ceremony()
        graduate = import_graduate(ctx["ceremony"]["id"], full_name="Reg Ivy",
                                   email="reg@x.edu")
        return ctx, graduate

    def test_per_line_discount_rounding_order(self, api):
        """PRD §3.4: "`discount_cents` is the sum of the **per-line** discounts,
        each line's discount computed as its line total multiplied by the
        percentage and rounded half up to a whole cent — summing the raw
        discounts and rounding once produces different cents and is not
        acceptable."
        PRD §3.4: "the discount percentage is keyed on the **pre-discount**
        subtotal: fifteen percent when `subtotal_cents` is at least 20,000
        cents, otherwise ten percent when it is at least 10,000 cents,
        otherwise no discount."

        Design: Difficulty/combinatorial_formula/regalia_per_line_discount_rounding_order
        """
        ctx, graduate = self._setup_graduate()
        items = [
            {"item_type": "GOWN", "size": "M", "quantity": 1, "unit_price_cents": 10029},
            {"item_type": "HOOD", "size": "NA", "quantity": 1, "unit_price_cents": 10049},
            {"item_type": "CAP", "size": "M", "quantity": 1, "unit_price_cents": 10069},
        ]
        order = create_regalia_order(graduate["id"], items=items)
        assert order["subtotal_cents"] == 30147  # >= 20000 -> 15% tier (pre-discount key)
        # per-line round_half_up: 1504 + 1507 + 1510 (sum-then-round would give 4522)
        assert order["discount_cents"] == 4521
        assert order["late_fee_cents"] == 0  # clock default precedes the deadline
        assert order["total_cents"] == 25626
        assert order["status"] == "SUBMITTED"

    def test_line_total_multiplies_quantity_before_discount(self, api):
        """PRD §3.4: "First, each line's total is its `unit_price_cents`
        multiplied by its `quantity`, and `subtotal_cents` is the sum of the
        line totals."
        PRD §3.4: "Third, `discount_cents` is the sum of the **per-line**
        discounts, each line's discount computed as its line total multiplied
        by the percentage and rounded half up to a whole cent".

        Design: Difficulty/combinatorial_formula/regalia_per_line_discount_rounding_order
        """
        ctx, graduate = self._setup_graduate()
        items = [{"item_type": "GOWN", "size": "M", "quantity": 2, "unit_price_cents": 10029}]
        order = create_regalia_order(graduate["id"], items=items)
        # line total 2 * 10029 = 20058 -> 15% tier; round_half_up(3008.7) = 3009
        assert order["subtotal_cents"] == 20058
        assert order["discount_cents"] == 3009
        assert order["late_fee_cents"] == 0
        assert order["total_cents"] == 17049


class TestRegaliaPayStateVersusFiscal:
    def _setup_cancelled_order(self):
        ctx = setup_ceremony()
        graduate = import_graduate(ctx["ceremony"]["id"], full_name="Ora Pay",
                                   email="ora@x.edu")
        order = create_regalia_order(graduate["id"], items=GOWN_10000)
        # on-time: subtotal 10000, 10% tier -> discount 1000, total 9000
        assert order["total_cents"] == 9000
        cancelled = validate_success(
            api_client.cancel_regalia_order(order["id"], make_graduate_headers(graduate["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        return graduate, order

    def test_pay_cancelled_order_wrong_amount_reports_state(self, api):
        """PRD §2.11: "When several checks could reject the same call, the
        server evaluates them in one fixed global order and surfaces only the
        first failure."
        PRD §3.4: "any attempt to pay an order not in `SUBMITTED` is rejected
        with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/regalia_pay_state_beats_fiscal
        """
        graduate, order = self._setup_cancelled_order()
        res = api.pay_regalia_order(order["id"], {"amount_cents": 1},
                                    make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert res.status_code == 409  # state check precedes payment exactness

    def test_pay_cancelled_order_exact_amount_still_state_error(self, api):
        """PRD §3.4: "the order moves `SUBMITTED` to `PAID` only when the
        presented amount equals the order's `total_cents` exactly; any
        discrepancy is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402),
        and any attempt to pay an order not in `SUBMITTED` is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/regalia_pay_state_beats_fiscal
        """
        graduate, order = self._setup_cancelled_order()
        res = api.pay_regalia_order(order["id"], {"amount_cents": 9000},
                                    make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert res.status_code == 409
        reread = validate_success(api.get_regalia_order(order["id"], REGISTRAR), 200)
        assert reread["status"] == "CANCELLED"


class TestRegaliaDeadlinesAndTiers:
    def test_regalia_late_fee_applies_after_deadline(self, api):
        """PRD §3.4: "an order created strictly after the ceremony's
        `regalia_order_deadline` adds a `late_fee_cents` of ten percent of the
        already-discounted subtotal, rounded half up; an order created at the
        deadline instant itself is on time and carries a `late_fee_cents` of
        zero."

        Design: Corner/calculations/regalia_late_fee_applies_after_deadline
        """
        ctx = setup_ceremony()
        graduate = import_graduate(ctx["ceremony"]["id"], full_name="Late Larry",
                                   email="larry@x.edu")
        on_time = create_regalia_order(graduate["id"], items=GOWN_10000)
        assert on_time["subtotal_cents"] == 10000
        assert on_time["discount_cents"] == 1000  # 10% tier at exactly 10000
        assert on_time["late_fee_cents"] == 0
        assert on_time["total_cents"] == 9000

        set_clock("2026-05-11T00:00:00Z")  # strictly after the 2026-05-10 deadline
        late = create_regalia_order(graduate["id"], items=GOWN_10000)
        assert late["subtotal_cents"] == 10000
        assert late["discount_cents"] == 1000
        assert late["late_fee_cents"] == 900  # round_half_up(9000 * 0.10)
        assert late["total_cents"] == 9900

    def test_regalia_discount_tier_boundary_at_10000(self, api):
        """PRD §3.4: "the discount percentage is keyed on the **pre-discount**
        subtotal: fifteen percent when `subtotal_cents` is at least 20,000
        cents, otherwise ten percent when it is at least 10,000 cents,
        otherwise no discount."

        Design: Corner/calculations/regalia_discount_tier_boundary_at_10000
        """
        ctx = setup_ceremony()
        graduate = import_graduate(ctx["ceremony"]["id"], full_name="Tier Tess",
                                   email="tess@x.edu")
        below = create_regalia_order(
            graduate["id"],
            items=[{"item_type": "TASSEL", "size": "NA", "quantity": 1,
                    "unit_price_cents": 9999}])
        assert below["discount_cents"] == 0
        assert below["total_cents"] == 9999

        at = create_regalia_order(
            graduate["id"],
            items=[{"item_type": "STOLE", "size": "NA", "quantity": 1,
                    "unit_price_cents": 10000}])
        assert at["discount_cents"] == 1000  # >= 10000 earns the 10% tier
        assert at["total_cents"] == 9000

    def test_payment_amount_mismatch_returns_error(self, api):
        """PRD §3.4: "the order moves `SUBMITTED` to `PAID` only when the
        presented amount equals the order's `total_cents` exactly; any
        discrepancy is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402)".

        Design: Corner/validations/payment_amount_mismatch_returns_error
        """
        ctx = setup_ceremony()
        graduate = import_graduate(ctx["ceremony"]["id"], full_name="Pay Pam",
                                   email="pam@x.edu")
        order = create_regalia_order(graduate["id"], items=GOWN_10000)
        assert order["total_cents"] == 9000

        res = api.pay_regalia_order(order["id"], {"amount_cents": 8999},
                                    make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
        assert res.status_code == 402
        reread = validate_success(api.get_regalia_order(order["id"], REGISTRAR), 200)
        assert reread["status"] == "SUBMITTED"


class TestWalkPrivilegeGate:
    def test_walk_privilege_revoked_blocks_regalia_fulfill(self, api):
        """PRD §3.4: "fulfillment moves a `PAID` order — or an
        `EXCHANGE_REQUESTED` one, in the exchange loop below — to `FULFILLED`,
        but only while the graduate's `walk_privilege_revoked` is false; a
        graduate who has accumulated two or more unexcused rehearsal strikes
        (§3.6) is refused with `ERR_WALK_PRIVILEGE_REVOKED`."

        Design: Corner/validations/walk_privilege_revoked_blocks_regalia_fulfill
        """
        ctx = setup_graduate_with_strikes(strikes=2)
        graduate = ctx["graduate"]
        assert get_graduate(graduate["id"])["walk_privilege_revoked"] is True

        order = create_regalia_order(graduate["id"], items=GOWN_10000)
        paid = pay_regalia_order(order)  # exact on-time total 9000
        assert paid["status"] == "PAID"

        res = api.fulfill_regalia_order(order["id"], CHAIR)
        validate_error(res, ApiErrorId.ERR_WALK_PRIVILEGE_REVOKED)
        assert res.status_code == 409
        reread = validate_success(api.get_regalia_order(order["id"], REGISTRAR), 200)
        assert reread["status"] == "PAID"

"""Preorder placement and payment: deposit math, exact tendering, state gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_program,
    create_approved_design,
    create_campaign,
    create_variant,
    get_preorder,
    lock_campaign,
    make_customer_headers,
    place_preorder,
    setup_campaign_in_production,
    setup_open_campaign_shop,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestDepositCalculation:
    def test_deposit_floor_applies_below_percentage(self, api):
        """PRD §3.4: "The raw deposit is the campaign's `unit_price_cents`
        times `qty` times `deposit_pct`, rounded half-up to whole cents;
        `deposit_due_cents` is the larger of the program's
        `deposit_floor_cents` and that raw figure. `balance_due_cents` is the
        remainder: `unit_price_cents` times `qty` minus `deposit_due_cents`."

        Design: Corner/calculations/deposit_floor_applies_below_percentage
        """
        shop = setup_open_campaign_shop(
            goal_units=1, unit_price_cents=1000, deposit_pct=0.4
        )
        preorder = place_preorder(
            shop["program"]["id"],
            shop["campaign"]["id"],
            shop["variant"]["id"],
            "cust-01",
            1,
        )
        assert preorder["deposit_due_cents"] == 500, (
            "raw 1000*1*0.4 = 400 is below the 500 floor; the max() constant "
            "governs"
        )
        assert preorder["balance_due_cents"] == 500, "1000 - 500"


class TestExactTendering:
    def test_deposit_shortfall_and_overpay_rejected(self, api):
        """PRD §3.4: "While the preorder is `PLACED`, a `DEPOSIT` payment of
        exactly `deposit_due_cents` moves it to `PAID`; less is
        `ERR_DEPOSIT_SHORTFALL`, more is `ERR_PAYMENT_AMOUNT_MISMATCH`, the
        campaign must be `OPEN` (else `ERR_CAMPAIGN_NOT_OPEN`), and a preorder
        in any other state is not payable (`ERR_PREORDER_NOT_PAYABLE`)."

        Design: Corner/errors/deposit_shortfall_and_overpay_rejected
        """
        shop = setup_open_campaign_shop(goal_units=5)
        preorder = place_preorder(
            shop["program"]["id"],
            shop["campaign"]["id"],
            shop["variant"]["id"],
            "cust-86",
            1,
        )
        assert preorder["deposit_due_cents"] == 1000, (
            "max(floor 500, round_half_up(2500*1*0.4) = 1000)"
        )

        low = api.pay_preorder(
            preorder["id"],
            {"phase": "DEPOSIT", "amount_cents": 999},
            make_customer_headers("cust-86"),
        )
        validate_error(low, ApiErrorId.ERR_DEPOSIT_SHORTFALL, 402)
        high = api.pay_preorder(
            preorder["id"],
            {"phase": "DEPOSIT", "amount_cents": 1001},
            make_customer_headers("cust-86"),
        )
        validate_error(high, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH, 422)
        assert get_preorder_status(api, preorder["id"]) == "PLACED", (
            "failed pays move nothing"
        )


def get_preorder_status(api, preorder_id):
    return validate_success(api.get_preorder(preorder_id, TREASURER), 200)["status"]


class TestStateBeatsFiscalOnPay:
    def _cancelled_preorder(self, api):
        shop = setup_open_campaign_shop(goal_units=10)
        preorder = place_preorder(
            shop["program"]["id"],
            shop["campaign"]["id"],
            shop["variant"]["id"],
            "cust-01",
            1,
        )
        cancelled = validate_success(
            api.cancel_preorder(
                preorder["id"], make_customer_headers("cust-01")
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        return preorder

    def test_pay_cancelled_preorder_with_short_amount_returns_state_error(self, api):
        """PRD §2.8: "The ordering is normative: when a request would fail two
        checks, the earlier check's error is the one returned."
        PRD §3.4: "a preorder in any other state is not payable
        (`ERR_PREORDER_NOT_PAYABLE`)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_preorder_pay
        """
        preorder = self._cancelled_preorder(api)
        assert preorder["deposit_due_cents"] == 1000, (
            "the fiscal shortfall (1 < 1000) is real, so both checks fail"
        )
        res = api.pay_preorder(
            preorder["id"],
            {"phase": "DEPOSIT", "amount_cents": 1},
            make_customer_headers("cust-01"),
        )
        validate_error(res, ApiErrorId.ERR_PREORDER_NOT_PAYABLE, 409)

    def test_pay_cancelled_preorder_with_exact_amount_returns_state_error(self, api):
        """PRD §2.8: "The ordering is normative: when a request would fail two
        checks, the earlier check's error is the one returned."
        PRD §3.4: "a preorder in any other state is not payable
        (`ERR_PREORDER_NOT_PAYABLE`)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_preorder_pay
        """
        preorder = self._cancelled_preorder(api)
        res = api.pay_preorder(
            preorder["id"],
            {"phase": "DEPOSIT", "amount_cents": 1000},
            make_customer_headers("cust-01"),
        )
        validate_error(res, ApiErrorId.ERR_PREORDER_NOT_PAYABLE, 409)


class TestPreorderPlacementGates:
    def test_preorder_on_draft_campaign_rejected(self, api):
        """PRD §3.4: "The variant's design must be the campaign's design — a
        mismatch is `ERR_VARIANT_DESIGN_MISMATCH` — and the campaign must
        still be `OPEN`, else `ERR_CAMPAIGN_NOT_OPEN`."

        Design: Corner/errors/preorder_on_draft_campaign_rejected
        """
        shop = setup_open_campaign_shop(goal_units=5)
        program_id = shop["program"]["id"]
        draft = create_campaign(program_id, shop["design"]["id"], goal_units=5)
        res = api.create_preorder(
            {
                "program_id": program_id,
                "campaign_id": draft["id"],
                "variant_id": shop["variant"]["id"],
                "customer_user_id": "cust-82",
                "qty": 1,
            },
            make_customer_headers("cust-82"),
        )
        validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN, 409)

    def test_preorder_cancel_after_lock_rejected(self, api):
        """PRD §3.4: "Once the campaign has locked — it is no longer `OPEN` —
        or the preorder is already terminal, the cancel is rejected with
        `ERR_PREORDER_NOT_CANCELLABLE`."

        Design: Corner/errors/preorder_cancel_after_lock_rejected
        """
        shop = setup_campaign_in_production(
            goal_units=1, preorder_qty=1, vendor_min_order_qty=1,
            customer_user_id="cust-80",
        )
        preorder = shop["preorders"][0]
        assert preorder["status"] == "PAID"
        res = api.cancel_preorder(
            preorder["id"], make_customer_headers("cust-80")
        )
        validate_error(res, ApiErrorId.ERR_PREORDER_NOT_CANCELLABLE, 409)

    def test_preorder_variant_design_mismatch_rejected(self, api):
        """PRD §3.4: "The variant's design must be the campaign's design — a
        mismatch is `ERR_VARIANT_DESIGN_MISMATCH` — and the campaign must
        still be `OPEN`, else `ERR_CAMPAIGN_NOT_OPEN`."

        Design: Corner/errors/preorder_variant_design_mismatch_rejected
        """
        program = create_active_program()
        design_a = create_approved_design(program["id"], name="A")
        design_b = create_approved_design(program["id"], name="B")
        variant_b = create_variant(program["id"], design_b["id"], size="M")
        campaign = create_campaign(program["id"], design_a["id"])
        validate_success(api.open_preorder_campaign(campaign["id"], MANAGER), 200)

        res = api.create_preorder(
            {
                "program_id": program["id"],
                "campaign_id": campaign["id"],
                "variant_id": variant_b["id"],
                "customer_user_id": "cust-85",
                "qty": 1,
            },
            make_customer_headers("cust-85"),
        )
        validate_error(res, ApiErrorId.ERR_VARIANT_DESIGN_MISMATCH, 422)

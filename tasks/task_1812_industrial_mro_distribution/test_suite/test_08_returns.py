"""Returns: windows, per-line rounding, restocking fees, and spend reconciliation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_return,
    get_customer,
    get_order_lines,
    mark_fulfilled,
    mark_ready,
    set_clock,
    setup_completed_order,
    setup_confirmed_order,
    setup_fulfilled_order,
    validate_error,
    validate_success,
    walk_return_to_received,
)

ADMIN = TEST_USERS["admin_headers"]


def _two_special_order_scenario(api, account_number, sku_prefix, branch_code):
    """Two SPECIAL_ORDER items list 103 each (1 on hand each); WILL_CALL order
    with one line per item, confirmed, readied, fulfilled."""
    scenario = setup_fulfilled_order(
        [
            {"qty": 1, "sku": f"{sku_prefix}A", "item_class": "SPECIAL_ORDER",
             "list_price_cents": 103},
            {"qty": 1, "sku": f"{sku_prefix}B", "item_class": "SPECIAL_ORDER",
             "list_price_cents": 103},
        ],
        customer_overrides={"account_number": account_number,
                            "credit_limit_cents": 10000000},
        branch_overrides={"location_code": branch_code},
        restock_qtys=[1, 1],
    )
    return scenario


def _full_return_lines(lines, condition_a="RESALEABLE", condition_b="RESALEABLE"):
    return [
        {"order_line_id": lines[0]["id"], "qty": 1, "condition": condition_a},
        {"order_line_id": lines[1]["id"], "qty": 1, "condition": condition_b},
    ]


class TestReturnCreditPerLineRounding:
    def test_credit_rounds_per_line_before_summing(self, api, admin_headers):
        """PRD §3.8: "The rounding order is pinned per line first, then summed:
        each line's gross is its returned `qty` multiplied by the order line's
        snapshot `unit_price_cents`; each line's credit is that gross reduced by
        the class restocking percentage — zero for `STOCKED`, twenty percent for
        `SPECIAL_ORDER` — rounded half up individually; `credit_cents` is the sum
        of those per-line credits"
        PRD §3.8: "two `SPECIAL_ORDER` lines grossing 103 cents each yield credits
        of 82 plus 82 for a 164-cent total, not the 165 that a single rounding of
        206 would produce."

        Design: Difficulty/combinatorial_formula/return_credit_per_line_rounding
        """
        scenario = _two_special_order_scenario(api, "RET-1", "SP-103", "BR-4")
        ret = create_return(
            scenario["order"]["id"],
            _full_return_lines(scenario["lines"], "RESALEABLE", "DAMAGED"),
        )
        walk_return_to_received(ret["id"])
        credited = validate_success(api.credit_return(ret["id"], admin_headers))
        assert credited["status"] == "CREDITED"
        assert credited["credit_cents"] == 164

    def test_restocking_fee_is_gross_sum_minus_credit(self, api, admin_headers):
        """PRD §3.8: "`restocking_fee_cents` is the sum of the grosses minus
        `credit_cents`. The alternative of summing grosses first and rounding once
        is explicitly rejected: two `SPECIAL_ORDER` lines grossing 103 cents each
        yield credits of 82 plus 82 for a 164-cent total, not the 165 that a
        single rounding of 206 would produce."

        Design: Difficulty/combinatorial_formula/return_credit_per_line_rounding
        """
        scenario = _two_special_order_scenario(api, "RET-1", "SP-103", "BR-4")
        ret = create_return(
            scenario["order"]["id"],
            _full_return_lines(scenario["lines"], "RESALEABLE", "DAMAGED"),
        )
        walk_return_to_received(ret["id"])
        credited = validate_success(api.credit_return(ret["id"], admin_headers))
        assert credited["restocking_fee_cents"] == 206 - 164


class TestSpendCompleteCreditReconciliation:
    def test_completion_moves_gross_spend_onto_customer(self, api, admin_headers):
        """PRD §3.7: "Completion moves the order to `COMPLETED`, stamps
        `completed_at`, credits the account's `net_spend_cents` with the order's
        `total_cents`, releases the same amount from `open_credit_exposure_cents`"
        PRD §3.1: "`net_spend_cents`, the read-only lifetime figure equal to the
        sum of `total_cents` over the account's `COMPLETED` orders minus the sum
        of `credit_cents` over its `CREDITED` returns"

        Design: Difficulty/compensating_invariant/spend_complete_credit_reconciliation
        """
        scenario = setup_completed_order(
            [
                {"qty": 1, "sku": "RC-103A", "item_class": "SPECIAL_ORDER",
                 "list_price_cents": 103},
                {"qty": 1, "sku": "RC-103B", "item_class": "SPECIAL_ORDER",
                 "list_price_cents": 103},
            ],
            customer_overrides={"account_number": "RC-1",
                                "credit_limit_cents": 10000000},
            branch_overrides={"location_code": "BR-16"},
            restock_qtys=[1, 1],
        )
        assert scenario["order"]["total_cents"] == 206
        account = get_customer(scenario["customer"]["id"])
        assert account["net_spend_cents"] == 206
        assert account["open_credit_exposure_cents"] == 0

    def test_credit_decrements_net_spend_and_conserves_gross(self, api,
                                                             admin_headers):
        """PRD §3.8: "The credit then unwinds the fiscal record — the account's
        `net_spend_cents` falls by `credit_cents`"
        PRD §3.1: "`net_spend_cents`, the read-only lifetime figure equal to the
        sum of `total_cents` over the account's `COMPLETED` orders minus the sum
        of `credit_cents` over its `CREDITED` returns"

        Design: Difficulty/compensating_invariant/spend_complete_credit_reconciliation
        """
        scenario = setup_completed_order(
            [
                {"qty": 1, "sku": "RC-103A", "item_class": "SPECIAL_ORDER",
                 "list_price_cents": 103},
                {"qty": 1, "sku": "RC-103B", "item_class": "SPECIAL_ORDER",
                 "list_price_cents": 103},
            ],
            customer_overrides={"account_number": "RC-1",
                                "credit_limit_cents": 10000000},
            branch_overrides={"location_code": "BR-16"},
            restock_qtys=[1, 1],
        )
        gross = scenario["order"]["total_cents"]
        ret = create_return(
            scenario["order"]["id"], _full_return_lines(scenario["lines"])
        )
        walk_return_to_received(ret["id"])
        credited = validate_success(api.credit_return(ret["id"], admin_headers))
        assert credited["credit_cents"] == 164
        assert credited["restocking_fee_cents"] == 42

        account = get_customer(scenario["customer"]["id"])
        assert account["net_spend_cents"] == 42
        # Conserved: completed gross = net spend + credited returns.
        assert account["net_spend_cents"] + credited["credit_cents"] == gross


class TestReturnGateRequiresFulfilled:
    def _setup(self, api):
        scenario = setup_confirmed_order(
            [{"qty": 1, "sku": "XR-1", "list_price_cents": 1000}],
            customer_overrides={"account_number": "XR-1",
                                "credit_limit_cents": 10000000},
            branch_overrides={"location_code": "BR-14"},
            restock_qtys=[1],
        )
        return scenario

    def test_return_against_unfulfilled_order_rejected(self, api, admin_headers):
        """PRD §3.8: "The order must be returnable — `COMPLETED`, or `CONFIRMED`
        with fulfillment already `FULFILLED` — and any other state is rejected
        with `ERR_ORDER_NOT_RETURNABLE`."

        Design: Difficulty/cross_entity_state_dependency/return_requires_order_fulfilled
        """
        scenario = self._setup(api)
        line_id = scenario["lines"][0]["id"]
        res = api.create_return(
            {"order_id": scenario["order"]["id"],
             "lines": [{"order_line_id": line_id, "qty": 1,
                        "condition": "RESALEABLE"}]},
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_RETURNABLE)

    def test_return_accepted_once_order_fulfilled(self, api, admin_headers):
        """PRD §3.8: "The order must be returnable — `COMPLETED`, or `CONFIRMED`
        with fulfillment already `FULFILLED`"
        PRD §3.8: "A valid return is born `REQUESTED` with `credit_cents` and
        `restocking_fee_cents` unset."

        Design: Difficulty/cross_entity_state_dependency/return_requires_order_fulfilled
        """
        scenario = self._setup(api)
        line_id = scenario["lines"][0]["id"]
        res = api.create_return(
            {"order_id": scenario["order"]["id"],
             "lines": [{"order_line_id": line_id, "qty": 1,
                        "condition": "RESALEABLE"}]},
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_RETURNABLE)

        mark_ready(scenario["order"]["id"])
        mark_fulfilled(scenario["order"]["id"])
        created = validate_success(
            api.create_return(
                {"order_id": scenario["order"]["id"],
                 "lines": [{"order_line_id": line_id, "qty": 1,
                            "condition": "RESALEABLE"}]},
                admin_headers,
            ),
            201,
        )
        assert created["status"] == "REQUESTED"


class TestReturnPolicyViolations:
    def test_return_window_expired_for_special_order(self, api, admin_headers):
        """PRD §3.8: "the calendar window — sixty days for `STOCKED`, thirty for
        `SPECIAL_ORDER` — is enforced against the logical clock: a return created
        on a date later than the order's `fulfilled_at` date plus the class window
        is rejected with `ERR_RETURN_WINDOW_EXPIRED`, while a return dated exactly
        on the window's last day is admitted."

        Design: Corner/validations/return_window_expired_for_special_order
        """
        scenario = setup_fulfilled_order(
            [{"qty": 1, "sku": "RW-1", "item_class": "SPECIAL_ORDER",
              "list_price_cents": 1000}],
            customer_overrides={"account_number": "RW-1",
                                "credit_limit_cents": 100000},
            branch_overrides={"location_code": "BR-RW"},
            restock_qtys=[1],
        )
        line_id = get_order_lines(scenario["order"]["id"])[0]["id"]
        set_clock("2026-09-15T00:00:00Z")
        res = api.create_return(
            {"order_id": scenario["order"]["id"],
             "lines": [{"order_line_id": line_id, "qty": 1,
                        "condition": "RESALEABLE"}]},
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED)

    def test_return_qty_exceeding_remaining_rejected(self, api, admin_headers):
        """PRD §3.8: "the cumulative returned quantity across all of the order's
        non-rejected returns must never exceed the order line's purchased `qty`;
        violations are rejected with `ERR_RETURN_LINE_INVALID`."

        Design: Corner/validations/return_qty_exceeding_remaining_rejected
        """
        scenario = setup_fulfilled_order(
            [{"qty": 2, "sku": "RQ-1", "list_price_cents": 100}],
            customer_overrides={"account_number": "RQ-1",
                                "credit_limit_cents": 100000},
            branch_overrides={"location_code": "BR-RQ"},
            restock_qtys=[2],
        )
        line_id = get_order_lines(scenario["order"]["id"])[0]["id"]
        first = create_return(
            scenario["order"]["id"],
            [{"order_line_id": line_id, "qty": 2, "condition": "RESALEABLE"}],
        )
        assert first["status"] == "REQUESTED"

        res = api.create_return(
            {"order_id": scenario["order"]["id"],
             "lines": [{"order_line_id": line_id, "qty": 1,
                        "condition": "RESALEABLE"}]},
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_RETURN_LINE_INVALID)

    def test_non_returnable_item_rejected_from_returns(self, api, admin_headers):
        """PRD §3.8: "Item class gates the request further: a line whose item is
        `NON_RETURNABLE` is refused with `ERR_ITEM_NOT_RETURNABLE`"

        Design: Corner/errors/non_returnable_item_rejected_from_returns
        """
        scenario = setup_fulfilled_order(
            [{"qty": 1, "sku": "NR-1", "item_class": "NON_RETURNABLE",
              "list_price_cents": 100}],
            customer_overrides={"account_number": "NR-1",
                                "credit_limit_cents": 100000},
            branch_overrides={"location_code": "BR-NR"},
            restock_qtys=[1],
        )
        line_id = get_order_lines(scenario["order"]["id"])[0]["id"]
        res = api.create_return(
            {"order_id": scenario["order"]["id"],
             "lines": [{"order_line_id": line_id, "qty": 1,
                        "condition": "RESALEABLE"}]},
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_ITEM_NOT_RETURNABLE)

    def test_return_decision_after_rejected_returns_invalid_state(
        self, api, admin_headers
    ):
        """PRD §3.8: "The decision belongs to a `DistributionAdmin` and is a
        strict fork — a requested return is approved or rejected, never both, and
        either decision against a non-`REQUESTED` return is
        `ERR_INVALID_STATE_TRANSITION`. Rejection stores the supplied `reason` on
        `rejection_reason` and is terminal."

        Design: Corner/state_machines/return_decision_after_rejected_returns_invalid_state
        """
        scenario = setup_fulfilled_order(
            [{"qty": 1, "sku": "RJ-1", "list_price_cents": 100}],
            customer_overrides={"account_number": "RJ-1",
                                "credit_limit_cents": 100000},
            branch_overrides={"location_code": "BR-RJ"},
            restock_qtys=[1],
        )
        line_id = get_order_lines(scenario["order"]["id"])[0]["id"]
        ret = create_return(
            scenario["order"]["id"],
            [{"order_line_id": line_id, "qty": 1, "condition": "DAMAGED"}],
        )
        rejected = validate_success(
            api.reject_return(ret["id"], {"reason": "not our product"},
                              admin_headers)
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "not our product"

        res = api.approve_return(ret["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

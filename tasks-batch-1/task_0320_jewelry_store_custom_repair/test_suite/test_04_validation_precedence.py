"""Validation-precedence depth tests: when two checks could both fire, the earlier
check in the §2.8 fixed priority pipeline determines the error.

Translates queue-A difficulty instances under rule_id priority_pair_validation_conflict.
Both orderings are stated verbatim by the §2.8 pipeline, so the winning error is
uniquely derivable from PRD alone.
"""
import pytest
from test_helpers import (
    validate_error,
    create_quoted_custom_order,
    create_in_production_custom_order,
    ApiErrorId,
    TEST_USERS,
)

SA = TEST_USERS["sales_associate_headers"]
GS = TEST_USERS["goldsmith_headers"]
SM = TEST_USERS["store_manager_headers"]


class TestStateVsFiscalPrecedence:
    def test_complete_quoted_order_reports_state_error_not_balance(self, api):
        """PRD §2.8: "then state legality of the requested transition (`ERR_INVALID_STATE`,
        HTTP 409), then the cross-entity state guards ... and finally ... balance clearance".
        PRD §3.3: "Completion is legal only from `READY` and additionally requires that the
        balance be cleared".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_complete_nonready_outstanding_balance
        """
        # QUOTED order (not READY) with provisional balance outstanding (no deposit paid).
        order, _ = create_quoted_custom_order(
            estimated_materials_cents=200000, design_fee_cents=50000
        )
        res = api.complete_custom_order(order["id"], {"expected_version": order["version"]}, SA)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_complete_quoted_order_state_error_blocks_completion(self, api):
        """PRD §2.8: "an earlier failing check determines the error and later checks are not
        reached."
        PRD §3.3: "Completion is legal only from `READY`".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_complete_nonready_outstanding_balance
        """
        order, _ = create_quoted_custom_order(
            estimated_materials_cents=200000, design_fee_cents=50000
        )
        res = api.complete_custom_order(order["id"], {"expected_version": order["version"]}, SA)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


class TestRoleVsStatePrecedence:
    def test_goldsmith_cancel_in_production_reports_role_error_not_state(self, api):
        """PRD §2.8: "authentication headers first (`ERR_MISSING_AUTH`), then role
        authorization (`ERR_FORBIDDEN_ROLE`), then existence of any path-referenced resource
        (`ERR_NOT_FOUND`) ... then state legality of the requested transition
        (`ERR_INVALID_STATE`, HTTP 409)".
        PRD §3.3: "cancellation is forbidden — and yields `ERR_INVALID_STATE` — once the
        order has reached `IN_PRODUCTION`".

        Design: Difficulty/priority_pair_validation_conflict/role_vs_state_goldsmith_cancels_terminal_order
        """
        # Cancel is StoreManager-only; the order is in IN_PRODUCTION (non-cancellable).
        order, _ = create_in_production_custom_order(
            [{"qty": 1, "unit_price_cents": 100000, "markup_pct": 0.1}],
            deposit_cents=90000,
            estimated_materials_cents=200000,
            design_fee_cents=50000,
        )
        res = api.cancel_custom_order(order["id"], {"expected_version": order["version"]}, GS)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)

    def test_goldsmith_cancel_role_check_precedes_state_check(self, api):
        """PRD §2.8: "Authorization (the role check) is evaluated before resource existence,
        and resource existence is evaluated before any request-body or business validation."
        PRD §4: the /custom-orders/{id}/cancel operation authorizes only StoreManager.

        Design: Difficulty/priority_pair_validation_conflict/role_vs_state_goldsmith_cancels_terminal_order
        """
        order, _ = create_in_production_custom_order(
            [{"qty": 1, "unit_price_cents": 100000, "markup_pct": 0.1}],
            deposit_cents=90000,
            estimated_materials_cents=200000,
            design_fee_cents=50000,
        )
        res = api.cancel_custom_order(order["id"], {"expected_version": order["version"]}, GS)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)

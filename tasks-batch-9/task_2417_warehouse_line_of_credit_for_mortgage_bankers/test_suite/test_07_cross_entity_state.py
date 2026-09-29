"""Gates that turn on a different aggregate's state.

In both families the addressed row is in a perfectly legal state for the trigger
and the request still fails, because a child row it never names is not.
"""

import pytest

from test_helpers import (
    COLLATERAL_ANALYST,
    CREDIT_OFFICER,
    ApiErrorId,
    api_client,
    make_custodian_headers,
    validate_error,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as make
from test_helpers import fixtures as fx


# ─── Reinstatement gated on a child margin call ───────────────────────────────

class TestReinstateBlockedByOpenMarginCall:
    def test_a_valid_suspended_facility_cannot_reinstate_while_a_call_is_open(self):
        """The facility row is fine; its child margin call is what refuses.

        PRD 2.8: "This gate is notable because it turns on a *different*
        aggregate's state: the facility row itself is a perfectly valid
        `SUSPENDED` row, yet the request fails because a child margin call or a
        breached covenant test is still live."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_facility_reinstate_blocked_by_open_margin_call
        """
        scenario = fx.setup_suspended_facility_with_open_call()

        assert scenario.facility["status"] == "SUSPENDED"
        call = fx.read_margin_call(scenario.margin_call["id"])
        asserts.assert_margin_call(call)
        assert call["status"] == "ISSUED"
        # 1,960,000,000 outstanding against floor(1,900,000,000 * 0.98).
        assert call["call_amount_cents"] == 98_000_000

        validate_error(
            api_client.reinstate_facility(scenario.facility["id"], CREDIT_OFFICER),
            ApiErrorId.ERR_OPEN_MARGIN_CALL,
        )

        assert fx.read_facility(scenario.facility["id"])["status"] == "SUSPENDED"

    def test_waiving_the_child_call_flips_the_identical_request_to_success(self):
        """Nothing about the facility row changed, yet the request now works.

        PRD 2.8: "Curing or waiving every one of them flips the identical
        request to success with no change at all to the facility row."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_facility_reinstate_blocked_by_open_margin_call
        """
        scenario = fx.setup_suspended_facility_with_open_call()
        validate_error(
            api_client.reinstate_facility(scenario.facility["id"], CREDIT_OFFICER),
            ApiErrorId.ERR_OPEN_MARGIN_CALL,
        )

        waived = fx.waive_margin_call(
            scenario.margin_call["id"],
            reason="Borrower pledged substitute collateral",
            officer_user_id="co_1",
        )
        assert waived["status"] == "WAIVED"

        reinstated = validate_success(
            api_client.reinstate_facility(scenario.facility["id"], CREDIT_OFFICER)
        )
        asserts.assert_facility(reinstated)
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["open_margin_call_count"] == 0
        # The waiver is audit-only, so the drawn balance is untouched.
        assert reinstated["outstanding_principal_cents"] == 1_960_000_000


# ─── Dry funding gated on the custodian's receipt chain ───────────────────────

class TestDryFundingBlockedByReceiptState:
    def test_a_dry_advance_with_no_receipt_at_all_cannot_fund(self):
        """Full headroom and a verified wire are not enough without the file.

        PRD 2.8: "For an advance whose `funding_type` is `DRY`, `custody_status`
        is `RECEIVED_CLEAR` or `EXCEPTION_CURED`, failing with
        `ERR_CUSTODY_RECEIPT_REQUIRED` (409)."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_dry_funding_blocked_by_custodian_receipt_state
        """
        scenario = fx.setup_advance_ready_to_fund(file_clear_receipt=False)

        assert scenario.advance["custody_status"] == "PENDING_RECEIPT"
        assert scenario.wire["status"] == "VERIFIED"
        assert fx.read_facility(scenario.facility["id"])["availability_cents"] == (
            20_000_000_000
        )

        validate_error(
            api_client.fund_advance(scenario.advance["id"], COLLATERAL_ANALYST),
            ApiErrorId.ERR_CUSTODY_RECEIPT_REQUIRED,
        )

        assert fx.read_advance(scenario.advance["id"])["funding_status"] == "REQUESTED"

    def test_an_exception_receipt_fails_exactly_as_a_missing_one_does(self):
        """Existence is not the gate; the receipt's own state is.

        PRD 3.5: "A receipt with defects moves the advance `PENDING_RECEIPT →
        RECEIVED_EXCEPTION` instead."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_dry_funding_blocked_by_custodian_receipt_state
        """
        scenario = fx.setup_advance_ready_to_fund(file_clear_receipt=False)
        validate_error(
            api_client.fund_advance(scenario.advance["id"], COLLATERAL_ANALYST),
            ApiErrorId.ERR_CUSTODY_RECEIPT_REQUIRED,
        )

        receipt = validate_success(
            api_client.create_receipt(
                scenario.advance["id"],
                make.receipt_payload(
                    scenario.custodian["id"],
                    document_types=["NOTE", "MORTGAGE", "TITLE_POLICY"],
                    exception_codes=["UNSIGNED_ASSIGNMENT"],
                ),
                make_custodian_headers(scenario.custodian["id"]),
            ),
            expected_status=201,
        )
        asserts.assert_receipt(receipt)
        assert receipt["status"] == "EXCEPTION"
        assert fx.read_advance(scenario.advance["id"])["custody_status"] == (
            "RECEIVED_EXCEPTION"
        )

        validate_error(
            api_client.fund_advance(scenario.advance["id"], COLLATERAL_ANALYST),
            ApiErrorId.ERR_CUSTODY_RECEIPT_REQUIRED,
        )

        # Two refusals, and neither one moved any money.
        assert fx.read_advance(scenario.advance["id"])["funding_status"] == "REQUESTED"
        assert fx.read_facility(scenario.facility["id"])[
            "outstanding_principal_cents"
        ] == 0

    def test_curing_the_exception_opens_the_gate_at_the_full_rate(self):
        """`EXCEPTION_CURED` funds, and the exception haircut is gone with it.

        PRD 3.5: "On a complete cure the receipt moves `EXCEPTION → CURED`, the
        stored `cured_exception_codes` is updated, the advance moves
        `RECEIVED_EXCEPTION → EXCEPTION_CURED`, the document-exception haircut is
        removed and the valuation re-runs; when that re-run drives
        `required_paydown_cents` down to zero, every margin call of this advance
        with `trigger_reason` of `CUSTODY_EXCEPTION` still in `ISSUED` or
        `PARTIALLY_CURED` moves to `CURED`, and a `RESTRICTED` facility returns to
        `ACTIVE` once no other open call, no unwaived breach and no escalated
        demand remain."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_dry_funding_blocked_by_custodian_receipt_state
        """
        scenario = fx.setup_advance_ready_to_fund(file_clear_receipt=False)
        receipt = fx.file_receipt(
            scenario.advance["id"],
            scenario.custodian["id"],
            document_types=["NOTE", "MORTGAGE", "TITLE_POLICY"],
            exception_codes=["UNSIGNED_ASSIGNMENT"],
        )

        cured = fx.cure_receipt(
            receipt["id"], scenario.custodian["id"], ["UNSIGNED_ASSIGNMENT"]
        )
        assert cured["status"] == "CURED"
        assert fx.read_advance(scenario.advance["id"])["custody_status"] == (
            "EXCEPTION_CURED"
        )

        funded = validate_success(
            api_client.fund_advance(scenario.advance["id"], COLLATERAL_ANALYST)
        )
        asserts.assert_advance(funded)
        assert funded["funding_status"] == "FUNDED"
        assert funded["advance_amount_cents"] == 1_960_000_000
        assert funded["effective_advance_rate"] == pytest.approx(0.98, abs=1e-6)

        assert fx.wire_for_advance(scenario.advance["id"])["status"] == "RELEASED"

"""SBA loan decision branches, conditional finalize, and the escrow financing gate."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_broker_headers,
    create_escrow_payload,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Design: Difficulty/non_linear_state_machine/loan_conditional_branch_then_finalize
# ---------------------------------------------------------------------------
class TestLoanConditionalBranch:
    def test_conditional_approval_sets_amount_and_status(self, api):
        """PRD §3.7: "A `CONDITIONALLY_APPROVED` decision requires an `approved_amount_cents`
        supplied in the body — its absence is rejected with `ERR_INVALID_REQUEST` — sets
        `approved_amount_cents` to that supplied value, and moves the application to
        `CONDITIONALLY_APPROVED`, a status that does **not** unlock escrow."

        Design: Difficulty/non_linear_state_machine/loan_conditional_branch_then_finalize
        """
        s = fx.setup_deal_in_financing(api)
        data = validate_success(
            api.decide_loan(
                s["loan"]["id"],
                {"outcome": "CONDITIONALLY_APPROVED", "approved_amount_cents": 90_000_000,
                 "decision_reason": "Pending updated tax returns"},
                TEST_USERS["lender_headers"],
            )
        )
        assert data["status"] == "CONDITIONALLY_APPROVED"
        assert data["approved_amount_cents"] == 90_000_000

    def test_finalize_conditions_to_approved(self, api):
        """PRD §3.7: "From `CONDITIONALLY_APPROVED`, a `Lender` **finalizes the conditions** with an
        `outcome` of either `APPROVED` — which moves the application to `APPROVED` and unlocks
        escrow — or `DECLINED`, which moves it to the terminal `DECLINED`."

        Design: Difficulty/non_linear_state_machine/loan_conditional_branch_then_finalize
        """
        s = fx.setup_deal_in_financing(api)
        validate_success(
            api.decide_loan(
                s["loan"]["id"],
                {"outcome": "CONDITIONALLY_APPROVED", "approved_amount_cents": 90_000_000},
                TEST_USERS["lender_headers"],
            )
        )
        data = validate_success(
            api.finalize_loan_conditions(s["loan"]["id"], {"outcome": "APPROVED"}, TEST_USERS["lender_headers"])
        )
        assert data["status"] == "APPROVED"
        assert data["approved_amount_cents"] == 90_000_000


# ---------------------------------------------------------------------------
# Design: Difficulty/cross_entity_state_dependency/escrow_open_requires_approved_loan
# ---------------------------------------------------------------------------
class TestEscrowOpenRequiresApprovedLoan:
    def test_open_escrow_with_submitted_loan_rejected(self, api):
        """PRD §3.8: "Opening requires that the deal have an `SBALoanApplication` in `APPROVED`;
        without one, the open is rejected with `ERR_FINANCING_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/escrow_open_requires_approved_loan
        """
        s = fx.setup_deal_in_financing(api)  # loan is SUBMITTED, not decided
        resp = api.open_escrow(
            s["deal"]["id"], create_escrow_payload(110_000_000, 5_000_000), TEST_USERS["escrow_agent_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_FINANCING_NOT_APPROVED.value)
        deal = validate_success(api.get_deal(s["deal"]["id"], make_broker_headers(s["broker"]["id"])))
        assert deal["status"] == "FINANCING"

    def test_open_escrow_succeeds_after_loan_approved(self, api):
        """PRD §3.8: "On success the **EscrowAccount** is created in `OPENED`, the deal advances
        from `FINANCING` to `IN_ESCROW`, and the listing cascades from `UNDER_LOI` to `IN_ESCROW`."

        Design: Difficulty/cross_entity_state_dependency/escrow_open_requires_approved_loan
        """
        s = fx.setup_deal_in_financing(api)
        fx.approve_loan(api, s["loan"]["id"])
        escrow = validate_success(
            api.open_escrow(
                s["deal"]["id"], create_escrow_payload(110_000_000, 5_000_000), TEST_USERS["escrow_agent_headers"]
            ),
            expected_status=201,
        )
        assert escrow["status"] == "OPENED"
        deal = validate_success(api.get_deal(s["deal"]["id"], make_broker_headers(s["broker"]["id"])))
        assert deal["status"] == "IN_ESCROW"
        listing = validate_success(api.get_listing(s["listing"]["id"], make_broker_headers(s["broker"]["id"])))
        assert listing["status"] == "IN_ESCROW"


def test_finalize_conditions_on_submitted_loan_rejected(api):
    """PRD §3.7: "Finalizing an application that is not in `CONDITIONALLY_APPROVED` is rejected
    with `ERR_LOAN_INVALID_STATE`."

    Design: Corner/state_machines/loan_finalize_from_submitted_returns_invalid_state
    """
    s = fx.setup_deal_in_financing(api)  # loan is SUBMITTED
    resp = api.finalize_loan_conditions(s["loan"]["id"], {"outcome": "APPROVED"}, TEST_USERS["lender_headers"])
    validate_error(resp, ApiErrorId.ERR_LOAN_INVALID_STATE.value)


def test_conditional_approval_without_amount_rejected(api):
    """PRD §3.7: "A `CONDITIONALLY_APPROVED` decision requires an `approved_amount_cents` supplied
    in the body — its absence is rejected with `ERR_INVALID_REQUEST`"

    Design: Corner/state_machines/loan_conditional_approval_without_amount_returns_invalid_request
    """
    s = fx.setup_deal_in_financing(api)
    resp = api.decide_loan(s["loan"]["id"], {"outcome": "CONDITIONALLY_APPROVED"}, TEST_USERS["lender_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

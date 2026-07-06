"""Consignment payout variants and grading-submission dispute cycle."""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_customer,
    create_listed_consignment,
    create_sold_consignment,
    grading_submission_returned,
    grading_submission_at_dispute_limit,
    create_consignment_payload,
    create_grading_submission_payload,
    TEST_USERS,
    make_customer_headers,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc: provisional vs final payout diverge
# ---------------------------------------------------------------------------
def test_provisional_payout_from_asking_price(api, clerk_headers):
    """PRD §3.7: "Listing computes a `provisional_payout_cents`: the `asking_price_cents` multiplied by one minus the `commission_pct`, rounded half-up to whole cents — an estimate of what the consignor would receive before a buyer is found."

    Design: Difficulty/dual_variant_calc/consignment_provisional_vs_final_payout_diverge
    """
    _cust, consignment = create_listed_consignment(asking_price_cents=10000,
                                                    commission_pct=0.30)
    # 10000 * (1 - 0.30) = 7000
    assert consignment["provisional_payout_cents"] == 7000


def test_final_payout_from_sale_price_diverges_from_provisional(api, clerk_headers):
    """PRD §3.7: "computes `final_payout_cents` as the `sale_price_cents` multiplied by one minus the `commission_pct`, rounded half-up to whole cents; because the sale price may differ from the asking price, this final figure can diverge from the provisional estimate."

    Design: Difficulty/dual_variant_calc/consignment_provisional_vs_final_payout_diverge
    """
    _cust, consignment = create_sold_consignment(asking_price_cents=10000,
                                                  sale_price_cents=20000,
                                                  commission_pct=0.30)
    # final = 20000 * 0.7 = 14000; provisional was 10000 * 0.7 = 7000
    assert consignment["provisional_payout_cents"] == 7000
    assert consignment["final_payout_cents"] == 14000
    assert consignment["provisional_payout_cents"] != consignment["final_payout_cents"]


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine: consignment LISTED forks to RETURNED
# ---------------------------------------------------------------------------
def test_listed_returns_to_consignor_no_payout(api, clerk_headers):
    """PRD §3.7: "Alternatively the item is returned to its owner, advancing to `RETURNED_TO_CONSIGNOR`; this branch produces no payout, writes no credit transaction, and makes no change to store credit."

    Design: Difficulty/non_linear_state_machine/consignment_listed_forks_to_returned_no_payout
    """
    cust, consignment = create_listed_consignment(asking_price_cents=10000)
    returned = validate_success(
        api.transition_consignment(consignment["id"],
                                   {"to_status": "RETURNED_TO_CONSIGNOR"}, clerk_headers),
        200,
    )
    assert returned["status"] == "RETURNED_TO_CONSIGNOR"
    assert returned["final_payout_cents"] is None


def test_listed_returns_to_consignor_leaves_store_credit_zero(api, clerk_headers):
    """PRD §3.7: "this branch produces no payout, writes no credit transaction, and
    makes no change to store credit."

    Design: Difficulty/non_linear_state_machine/consignment_listed_forks_to_returned_no_payout
    """
    cust, consignment = create_listed_consignment(asking_price_cents=10000)
    validate_success(
        api.transition_consignment(consignment["id"],
                                   {"to_status": "RETURNED_TO_CONSIGNOR"}, clerk_headers),
        200,
    )
    after = validate_success(api.get_customer(cust["id"], clerk_headers), 200)
    assert after["store_credit_cents"] == 0


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine: grading dispute cycle RETURNED->AT_GRADER
# ---------------------------------------------------------------------------
def test_grading_dispute_returns_to_at_grader(api):
    """PRD §3.5: "Once returned, the owner may dispute the grade, which sends the
    book back to `AT_GRADER` for regrading and increments `dispute_count` by one"

    Design: Difficulty/non_linear_state_machine/grading_dispute_cycle_returned_to_at_grader
    """
    cust, gs = grading_submission_returned(grade_result=9.0)
    owner = make_customer_headers(cust["id"])
    disputed = validate_success(
        api.transition_grading_submission(gs["id"], {"to_status": "AT_GRADER"}, owner), 200
    )
    assert disputed["status"] == "AT_GRADER"
    assert disputed["dispute_count"] == 1


def test_grading_dispute_increments_dispute_count(api):
    """PRD §3.5: "which sends the book back to `AT_GRADER` for regrading and
    increments `dispute_count` by one"

    Design: Difficulty/non_linear_state_machine/grading_dispute_cycle_returned_to_at_grader
    """
    cust, gs = grading_submission_returned(grade_result=8.5)
    assert gs["dispute_count"] == 0
    owner = make_customer_headers(cust["id"])
    disputed = validate_success(
        api.transition_grading_submission(gs["id"], {"to_status": "AT_GRADER"}, owner), 200
    )
    assert disputed["dispute_count"] == 1


# ---------------------------------------------------------------------------
# Queue B — validations / state machines / errors / rbac / cascade
# ---------------------------------------------------------------------------
def test_consignment_sell_without_sale_price_rejected(api, clerk_headers):
    """PRD §3.7: "If it sells, it advances to `SOLD`, which requires a `sale_price_cents` to be supplied (else `ERR_SALE_PRICE_REQUIRED`)"

    Design: Corner/validations/consignment_sell_without_sale_price_rejected
    """
    _cust, consignment = create_listed_consignment(asking_price_cents=5000)
    res = api.transition_consignment(consignment["id"], {"to_status": "SOLD"}, clerk_headers)
    validate_error(res, ApiErrorId.ERR_SALE_PRICE_REQUIRED, expected_status=422)


def test_consignment_provisional_rounds_half_up(api, clerk_headers):
    """PRD §3.7: "the `asking_price_cents` multiplied by one minus the `commission_pct`, rounded half-up to whole cents"

    Design: Corner/calculations/consignment_provisional_rounds_half_up
    """
    _cust, consignment = create_listed_consignment(asking_price_cents=999,
                                                    commission_pct=0.30)
    # 999 * 0.7 = 699.3 -> round_half_up -> 699
    assert consignment["provisional_payout_cents"] == 699


def test_grading_dispute_limit_reached_rejected(api):
    """PRD §3.5: "this resubmit loop is bounded, and a dispute attempted when `dispute_count` has already reached the limit of 3 is rejected with `ERR_DISPUTE_LIMIT_REACHED`."

    Design: Corner/validations/grading_dispute_limit_reached_rejected
    """
    cust, gs = grading_submission_at_dispute_limit()
    assert gs["dispute_count"] == 3
    owner = make_customer_headers(cust["id"])
    res = api.transition_grading_submission(gs["id"], {"to_status": "AT_GRADER"}, owner)
    validate_error(res, ApiErrorId.ERR_DISPUTE_LIMIT_REACHED, expected_status=409)


def test_grading_terminal_pickedup_no_further_transition(api, clerk_headers):
    """PRD §3.5: "staff move a returned submission to `READY_FOR_PICKUP` and finally to `PICKED_UP`, the terminal state."
    PRD §2.8: "State — the target resource is in a state from which the requested
    transition or operation is defined, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/grading_terminal_pickedup_no_further_transition
    """
    cust = create_customer()
    gs = validate_success(
        api.create_grading_submission(
            create_grading_submission_payload(cust["id"], description="book",
                                              declared_value_cents=1000),
            clerk_headers,
        ),
        201,
    )
    api.transition_grading_submission(gs["id"], {"to_status": "SUBMITTED"}, clerk_headers)
    api.transition_grading_submission(gs["id"], {"to_status": "AT_GRADER"}, clerk_headers)
    api.transition_grading_submission(gs["id"], {"to_status": "RETURNED", "grade_result": 8.5},
                                      clerk_headers)
    api.transition_grading_submission(gs["id"], {"to_status": "READY_FOR_PICKUP"}, clerk_headers)
    api.transition_grading_submission(gs["id"], {"to_status": "PICKED_UP"}, clerk_headers)
    res = api.transition_grading_submission(gs["id"], {"to_status": "AT_GRADER"}, clerk_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_grading_submit_banned_customer_rejected(api, clerk_headers, manager_headers):
    """PRD §3.5: "Staff advance it from `INTAKE` to `SUBMITTED`, but only when the owning customer is `ACTIVE` — a banned customer's submission cannot be advanced and is rejected with `ERR_CUSTOMER_BANNED`."

    Design: Corner/errors/grading_submit_banned_customer_rejected
    """
    cust = create_customer()
    gs = validate_success(
        api.create_grading_submission(
            create_grading_submission_payload(cust["id"], description="book",
                                              declared_value_cents=1000),
            clerk_headers,
        ),
        201,
    )
    validate_success(api.ban_customer(cust["id"], manager_headers), 200)
    res = api.transition_grading_submission(gs["id"], {"to_status": "SUBMITTED"}, clerk_headers)
    validate_error(res, ApiErrorId.ERR_CUSTOMER_BANNED, expected_status=409)


def test_clerk_cannot_pay_out_consignment(api, clerk_headers):
    """PRD §3.7: "Paying out a sold consignment is a manager-only action that advances it from `SOLD` to `PAID_OUT`."

    Design: Corner/rbac/clerk_cannot_pay_out_consignment
    """
    _cust, consignment = create_sold_consignment(asking_price_cents=10000,
                                                  sale_price_cents=10000)
    res = api.transition_consignment(consignment["id"], {"to_status": "PAID_OUT"}, clerk_headers)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_consignment_paid_out_cascades_store_credit_and_txn(api, manager_headers):
    """PRD §3.7: "first it writes a credit transaction with reason `CONSIGNMENT_PAYOUT` and an `amount_cents` equal to the consignment's `final_payout_cents`, and raises the consignor's `store_credit_cents` by that `final_payout_cents"

    Design: Corner/cross_cutting_complexity_layers/consignment_paid_out_cascades_store_credit_and_txn
    """
    cust, consignment = create_sold_consignment(asking_price_cents=9000,
                                                 sale_price_cents=10000,
                                                 commission_pct=0.30)
    # final_payout = 10000 * 0.7 = 7000
    assert consignment["final_payout_cents"] == 7000
    validate_success(
        api.transition_consignment(consignment["id"], {"to_status": "PAID_OUT"}, manager_headers),
        200,
    )
    after = validate_success(api.get_customer(cust["id"], manager_headers), 200)
    assert after["store_credit_cents"] == 7000

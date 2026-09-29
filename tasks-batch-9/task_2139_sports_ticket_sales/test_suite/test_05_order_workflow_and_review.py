"""Submission forks, the discount revision cycle and cancellation compensation."""
from test_helpers import (
    ApiErrorId,
    api_client,
    cancel_order,
    create_confirmed_order,
    create_order,
    create_plan_order_payload,
    create_rep,
    pay_order,
    read_account,
    read_order,
    read_season,
    read_seat,
    review_order,
    setup_four_seat_zone_c_world,
    setup_selling_world,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    OPS_HEADERS,
    RM_HEADERS,
    TEST_USERS,
)


def test_zero_discount_submission_forks_straight_to_approved():
    """PRD 3.5: "**When the order's `discount_pct` is exactly 0**, submission advances `order_status` straight from `DRAFT` to `APPROVED`. The submitting rep's identifier is stamped into `submitted_by_user_id`, `reviewed_by_user_id` is deliberately left null because no review is required on this branch, and the order's `version` increments by 1. A zero-discount order therefore never visits `PENDING_APPROVAL` at all."

    Design: Corner/state_machines/sm_zero_discount_submit_forks_straight_to_approved
    """
    world = setup_selling_world()
    order = create_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]],
        world["rep_headers"], discount_pct=0,
    )

    submitted = submit_order(order["id"], world["rep_headers"])

    assert submitted["order_status"] == "APPROVED"
    assert submitted["submitted_by_user_id"] == world["rep_id"]
    assert submitted["reviewed_by_user_id"] is None
    assert submitted["payment_status"] == "NOT_STARTED"


def test_discounted_order_walks_the_revision_cycle_and_is_reapproved():
    """PRD 3.5: "**When the order's `discount_pct` is greater than 0**, submission advances `order_status` from `DRAFT` to `PENDING_APPROVAL`."
    PRD 3.5: "A `decision` of `REVISE` sends `order_status` from `PENDING_APPROVAL` back to `DRAFT`, stamps `reviewed_by_user_id` with the reviewer's identifier, clears `submitted_by_user_id` back to null so that the next submission re-stamps it fresh, and increments the order's `version` by 1."
    PRD 3.5: "A `decision` of `APPROVE` advances `order_status` from `PENDING_APPROVAL` to `APPROVED`, stamps `reviewed_by_user_id` with the reviewer's identifier, and increments the order's `version` by 1."

    Design: Corner/state_machines/sm_discounted_order_revision_cycle_returns_to_draft_then_reapproves
    """
    world = setup_selling_world()
    order = create_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]],
        world["rep_headers"], discount_pct=0.10,
    )
    assert order["quoted_total_cents"] == 8915

    pending = submit_order(order["id"], world["rep_headers"])
    assert pending["order_status"] == "PENDING_APPROVAL"

    revised = review_order(
        order["id"], "REVISE", RM_HEADERS, decision_note="trim the discount"
    )
    assert revised["order_status"] == "DRAFT"
    assert revised["submitted_by_user_id"] is None

    resubmitted = submit_order(order["id"], world["rep_headers"])
    assert resubmitted["order_status"] == "PENDING_APPROVAL"

    approved = review_order(order["id"], "APPROVE", RM_HEADERS)
    assert approved["order_status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == "rm-001"


def test_reviewer_who_submitted_the_order_is_refused():
    """PRD 2.1: "Segregation of duties is enforced on discount review: the reviewing `RevenueManager`'s `X-User-ID` must differ from the value recorded in the order's `submitted_by_user_id`. When they are equal, the review is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), so the person who pushed a discount through can never be the person who clears it."
    PRD 3.5: "A `decision` of `APPROVE` advances `order_status` from `PENDING_APPROVAL` to `APPROVED`, stamps `reviewed_by_user_id` with the reviewer's identifier, and increments the order's `version` by 1."

    Design: Corner/validations/val_reviewer_who_submitted_the_order_is_rejected
    """
    from test_helpers import build_user_headers

    world = setup_selling_world()
    order = create_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]],
        world["rep_headers"], discount_pct=0.10,
    )
    submit_order(order["id"], world["rep_headers"])

    self_review = api_client.review_plan_order(
        order["id"],
        {"decision": "APPROVE"},
        build_user_headers(world["rep_id"], "RevenueManager"),
    )

    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert read_order(order["id"])["order_status"] == "PENDING_APPROVAL"

    approved = review_order(order["id"], "APPROVE", RM_HEADERS)
    assert approved["order_status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == "rm-001"


def test_sales_rep_cannot_write_against_an_account_they_do_not_own():
    """PRD 2.1: "Concretely, every account-scoped write by a `SalesRep` requires `X-User-ID` to equal the target account's `assigned_rep_id`; a mismatch is `ERR_NOT_ACCOUNT_REP` (HTTP 403)."
    PRD 2.9: "**Rep ownership.** A `SalesRep` caller's `X-User-ID` equals the target account's `assigned_rep_id` — otherwise `ERR_NOT_ACCOUNT_REP` (403). This guards six operations: hold creation, order creation, order submission, relocation, touchpoint logging and hospitality booking."

    Design: Corner/validations/val_sales_rep_acting_on_an_account_they_do_not_own_rejected
    """
    from test_helpers import build_user_headers

    world = setup_selling_world()
    other_rep = create_rep(rep_name="Rep South", territory_code="SOUTH", book_capacity=5)

    response = api_client.create_plan_order(
        create_plan_order_payload(
            world["account_id"], world["plan_id"], [world["seat_ids"][0]]
        ),
        build_user_headers(other_rep["id"], "SalesRep"),
    )

    validate_error(response, ApiErrorId.ERR_NOT_ACCOUNT_REP.value, 403)
    assert read_account(world["account_id"])["assigned_rep_id"] == world["rep_id"]
    _, meta = validate_paginated(
        api_client.list_plan_orders(
            OPS_HEADERS, params={"account_id": world["account_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_cancelling_an_already_cancelled_order_is_rejected():
    """PRD 3.8: "Cancellation is available to a `SalesRep` or a `TicketOpsAdmin` from any order status other than `CANCELLED`, and carries an optional `cancel_reason` that is recorded in the order's `cancelled_reason` when supplied."
    PRD 3.8: "From `DRAFT`, from `PENDING_APPROVAL` and from `APPROVED` the effects are identical and modest: every hold whose `origin_order_id` is this order and whose `hold_status` is `ACTIVE` becomes `RELEASED` with `released_reason` recorded as `ORDER_CANCELLED`, the seat census is recomputed, `order_status` becomes `CANCELLED`, and the order's `version` increments by 1."

    Design: Corner/state_machines/sm_cancelled_order_cannot_be_cancelled_again
    """
    world = setup_selling_world()
    order = create_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]], world["rep_headers"]
    )
    cancel_order(order["id"], world["rep_headers"], cancel_reason="first cancel")

    response = api_client.cancel_plan_order(
        order["id"], {"cancel_reason": "second cancel"}, world["rep_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ORDER_STATE_INVALID.value, 409)
    unchanged = read_order(order["id"])
    assert unchanged["order_status"] == "CANCELLED"
    assert unchanged["cancelled_reason"] == "first cancel"
    assert read_seat(world["seat_ids"][0])["seat_status"] == "AVAILABLE"
    _, meta = validate_paginated(
        api_client.list_seat_holds(
            OPS_HEADERS,
            params={"origin_order_id": order["id"], "hold_status": "RELEASED"},
        )
    )
    assert meta["total_count"] == 1


def test_cancelling_a_confirmed_order_returns_the_revenue_ledger_to_zero():
    """PRD 2.10: "The ledger obeys a standing invariant: at all times it equals the sum of `final_total_cents` over every plan order whose `order_status` is `CONFIRMED`, plus the sum of `total_due_cents` over every hospitality package whose `package_status` is either `CONFIRMED` or `SETTLED`."
    PRD 3.8: "The season's `contracted_revenue_cents` decreases by the order's `final_total_cents`, restoring the ledger invariant. Every seat in `seat_ids` has its `assigned_account_id` cleared and its `seat_status` recomputed to `AVAILABLE`, and the season seat counters are recomputed."

    Design: Difficulty/compensating_invariant/order_cancel_restores_the_contracted_revenue_ledger
    """
    world = setup_four_seat_zone_c_world()
    order = create_confirmed_order(
        world["account_id"], world["plan_id"], world["seat_ids"],
        world["rep_headers"], installment_count=3,
    )
    pay_order(order["id"], world["rep_headers"], 5000)
    before = read_season(world["season_id"])
    assert before["contracted_revenue_cents"] == 38430
    assert before["assigned_seat_count"] == 4

    cancel_order(order["id"], world["rep_headers"], cancel_reason="buyer withdrew")

    after = read_season(world["season_id"])
    assert after["contracted_revenue_cents"] == 0
    assert after["assigned_seat_count"] == 0
    assert after["available_seat_count"] == 4


def test_cancelling_a_confirmed_order_refunds_paid_money_into_loyalty_credit():
    """PRD 3.8: "The billing dimension moves to `REFUNDED` — from `SCHEDULED`, from `PARTIALLY_PAID`, from `PAID_IN_FULL` or from `DELINQUENT`, all four reach the same terminal `REFUNDED` — and in every one of those four cases the account's `loyalty_credit_cents` increases by the order's `amount_paid_cents`."
    PRD 3.8: "Every hold whose `origin_order_id` is this order and whose `hold_status` is `ACTIVE` or `CONVERTED` becomes `RELEASED` with `released_reason` recorded as `ORDER_CANCELLED`."
    PRD 3.6: "`lifetime_value_cents` is the sum of `final_total_cents` over the account's `CONFIRMED` orders plus the sum of `total_due_cents` over the account's `CONFIRMED` or `SETTLED` hospitality packages."

    Design: Difficulty/compensating_invariant/order_cancel_restores_the_contracted_revenue_ledger
    """
    world = setup_four_seat_zone_c_world()
    order = create_confirmed_order(
        world["account_id"], world["plan_id"], world["seat_ids"],
        world["rep_headers"], installment_count=3,
    )
    pay_order(order["id"], world["rep_headers"], 5000)

    cancelled = cancel_order(
        order["id"], world["rep_headers"], cancel_reason="buyer withdrew"
    )

    assert cancelled["order_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["amount_paid_cents"] == 5000
    account = read_account(world["account_id"])
    assert account["loyalty_credit_cents"] == 5000
    assert account["lifetime_value_cents"] == 0
    _, meta = validate_paginated(
        api_client.list_seat_holds(
            OPS_HEADERS,
            params={"origin_order_id": order["id"], "hold_status": "RELEASED"},
        )
    )
    assert meta["total_count"] == 4

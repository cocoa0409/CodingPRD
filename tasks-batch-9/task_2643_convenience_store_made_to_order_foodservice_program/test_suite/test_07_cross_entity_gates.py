"""Gates that live on a different row than the one being written.

A kitchen ticket is refused because of a money field on its order, and an
order is refused because of a labor plan it never references by id. Each test
proves the gate by satisfying it on the *other* entity and replaying the same
request unchanged.
"""

import test_helpers as H
from test_helpers import fixtures as X

CLOCK_LUNCH = "2026-08-01T11:00:00Z"


def _placed_but_unpaid_sandwich_order(api):
    """A placed touchscreen order with one queued SANDWICH ticket, unpaid."""
    store = X.setup_store_open_for_lunch(api, CLOCK_LUNCH)
    hoagie = X.create_hoagie(api)
    order = X.create_draft_order(api, store["id"])
    X.add_order_line(api, order["id"], hoagie["id"], 1)
    placed = X.place_order(api, order["id"])
    ticket = X.find_ticket(api, placed["id"], "SANDWICH")
    return store, placed, ticket


def _lunch_store_with_an_unpublished_plan(api):
    """A store trading in LUNCH whose only LUNCH plan is still a draft."""
    X.set_clock(api, CLOCK_LUNCH)
    store = X.create_store(api)
    X.transition_daypart(api, store["id"], "LUNCH")
    plan = X.create_staffing_plan(api, store["id"], daypart="LUNCH")
    coffee = X.create_coffee(api)
    order = X.create_draft_order(api, store["id"])
    X.add_order_line(api, order["id"], coffee["id"], 1)
    return X.read_store(api, store["id"]), plan, coffee, order


def test_claiming_a_queued_ticket_fails_while_the_order_is_unpaid(api):
    """The ticket is legal on its own axis and still refused.

    "The ticket's `status` must be `QUEUED`" is satisfied, yet "The owning
    order's `settlement_status` must be `AUTHORIZED`; kitchen work is
    deliberately blocked until tender has been authorized, and an attempt
    before then reports `ERR_ORDER_NOT_AUTHORIZED` (HTTP 409)." The refusal
    must not consume the ticket: nothing in that precondition list writes, so
    the row stays claimable.

    Design: Difficulty/cross_entity_state_dependency/ticket_start_is_gated_on_the_owning_orders_settlement_axis
    """
    store, placed, ticket = _placed_but_unpaid_sandwich_order(api)
    assert placed["settlement_status"] == "UNPAID"
    assert ticket["status"] == "QUEUED"

    response = api.start_kitchen_ticket(ticket["id"], {}, H.KITCHEN_ASSOCIATE_HEADERS)

    H.validate_error(response, H.ApiErrorId.ERR_ORDER_NOT_AUTHORIZED.value, 409)
    assert X.read_order(api, placed["id"])["production_status"] == "PLACED"
    unchanged = H.get_success_data(
        api.get_kitchen_ticket(ticket["id"], H.KITCHEN_ASSOCIATE_HEADERS)
    )
    assert unchanged["status"] == "QUEUED"
    assert unchanged["started_by_user_id"] is None


def test_authorizing_tender_unblocks_the_identical_claim_and_moves_the_order(api):
    """Money on the order, not a change to the ticket, opens the gate.

    "Authorization records the `tender_type`, increments the order's `version`
    by one, moves no points, and unblocks ticket claiming for every ticket of
    the order." The replayed claim then does two things at once: "The claim
    records `started_by_user_id` as the acting `X-User-ID` and increments the
    ticket's `version` by one; where the order was still `PLACED`, it also
    advances the order `PLACED → IN_PRODUCTION`".

    Design: Difficulty/cross_entity_state_dependency/ticket_start_is_gated_on_the_owning_orders_settlement_axis
    """
    store, placed, ticket = _placed_but_unpaid_sandwich_order(api)
    refused = api.start_kitchen_ticket(ticket["id"], {}, H.KITCHEN_ASSOCIATE_HEADERS)
    H.validate_error(refused, H.ApiErrorId.ERR_ORDER_NOT_AUTHORIZED.value, 409)

    authorized = X.authorize_order(api, placed["id"], "CARD")
    assert authorized["settlement_status"] == "AUTHORIZED"

    started = X.start_ticket(api, ticket["id"], H.KITCHEN_ASSOCIATE_HEADERS)

    assert started["status"] == "IN_PROGRESS"
    assert started["started_by_user_id"] == H.ASSOCIATE_1_USER_ID
    assert X.read_order(api, placed["id"])["production_status"] == "IN_PRODUCTION"


def test_a_draft_labor_plan_is_invisible_to_order_placement(api):
    """An unpublished plan does not authorize trade, so the commit is refused.

    "Exactly one staffing plan must exist for the order's store whose
    `daypart` equals the store's `current_daypart`, whose `service_date`
    equals the calendar date of the current logical clock in UTC, and whose
    `status` is either `PUBLISHED` or `LOCKED`; absent such a plan the commit
    is refused with `ERR_DAYPART_PLAN_NOT_PUBLISHED` (HTTP 409)." The order is
    otherwise complete, and the failed commit leaves its snapshot field where a
    new order starts it, with "`daypart_at_placement` ... null until the
    workflow stages that populate them".

    Design: Difficulty/cross_entity_state_dependency/placement_is_gated_on_the_staffing_plans_publication_state
    """
    store, plan, coffee, order = _lunch_store_with_an_unpublished_plan(api)
    assert store["current_daypart"] == "LUNCH"
    assert plan["status"] == "DRAFT"

    response = api.place_order(order["id"], {}, H.STORE_TERMINAL_HEADERS)

    H.validate_error(response, H.ApiErrorId.ERR_DAYPART_PLAN_NOT_PUBLISHED.value, 409)
    still_draft = X.read_order(api, order["id"])
    assert still_draft["production_status"] == "DRAFT"
    assert still_draft["daypart_at_placement"] is None


def test_publishing_the_plan_authorizes_the_identical_commit(api):
    """Publishing the plan is the only change, and the same commit succeeds.

    "Publishing is what authorizes trade. A `StoreManager` publishes a plan,
    moving it `DRAFT → PUBLISHED`, after which orders may be placed at that
    store in that daypart on that service date." The commit then snapshots the
    trading daypart, since "`daypart_at_placement` snapshots the store's
    `current_daypart`", and prices the single line with no promotion in play,
    where "the order's `applied_promotion_id` stays null and its
    `promo_discount_cents` stays 0".

    Design: Difficulty/cross_entity_state_dependency/placement_is_gated_on_the_staffing_plans_publication_state
    """
    store, plan, coffee, order = _lunch_store_with_an_unpublished_plan(api)
    refused = api.place_order(order["id"], {}, H.STORE_TERMINAL_HEADERS)
    H.validate_error(refused, H.ApiErrorId.ERR_DAYPART_PLAN_NOT_PUBLISHED.value, 409)

    published = X.publish_staffing_plan(api, plan["id"])
    assert published["status"] == "PUBLISHED"

    placed = X.place_order(api, order["id"])

    assert placed["production_status"] == "PLACED"
    assert placed["daypart_at_placement"] == "LUNCH"
    assert placed["subtotal_gross_cents"] == 249
    assert placed["promo_discount_cents"] == 0
    assert placed["total_cents"] == 249

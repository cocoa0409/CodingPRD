"""Lifecycle transitions: invalid transitions, initial state, terminal lockdown,
and branch valid transitions (team reject, price-match reject).

Corner queue: state_machines section.
"""
import pytest
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    create_store,
    create_sku,
    create_customer,
    stock_sku,
    create_draft_order,
    add_order_line,
    place_order,
    setup_placed_order,
    setup_fulfilled_order,
    setup_started_service_ticket,
    setup_submitted_team_order,
    submit_price_match_claim,
    make_customer_headers,
    get_order,
    TEST_USERS,
)

ASSOCIATE = TEST_USERS["store_associate_headers"]
TECH = TEST_USERS["service_tech_headers"]
PRICE_ADMIN = TEST_USERS["price_admin_headers"]


def test_fulfill_from_reserved_is_invalid_state(api):
    """PRD §3.3: "Fulfillment, the version-guarded step of §2.6, advances
    `READY → FULFILLED`: it is permitted only when `fulfillment_status` is `READY`".
    PRD §2.10: "for transition endpoints, that the target resource is in a state
    from which the requested transition is defined (`ERR_INVALID_STATE`)."

    Fulfilling a RESERVED (not READY) order is an undefined transition.

    Design: Corner/state_machines/order_fulfill_from_reserved_invalid_state
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Mitt", base_price_cents=3000, size_label="M")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    placed, _ = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    current = get_order(placed["id"])
    res = api.fulfill_order(
        placed["id"], {"expected_order_version": current["version"]}, ASSOCIATE
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_new_order_starts_draft_unpaid(api):
    """PRD §3.3: "A new order starts with `fulfillment_status` of `DRAFT`,
    `payment_status` of `UNPAID`, `provisional_total_cents` of 0, and
    `final_total_cents` of null."

    Design: Corner/state_machines/order_initial_state_draft_unpaid
    """
    store = create_store(state_code="CA")
    customer = create_customer(home_state_code="CA")
    order = create_draft_order(customer["id"], store["id"], "SFS")
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["version"] == 1


def test_resume_from_inprogress_is_invalid_state(api):
    """PRD §3.8: "Resuming advances `NEEDS_PARTS → IN_PROGRESS`, cycling back into
    work with no inventory change."
    PRD §3.8: "A transition requested from a state where it is not defined is
    rejected with `ERR_INVALID_STATE`."

    Resuming an IN_PROGRESS (not NEEDS_PARTS) ticket is undefined.

    Design: Corner/state_machines/service_ticket_resume_from_inprogress_invalid_state
    """
    store = create_store(state_code="CA")
    customer = create_customer(home_state_code="CA")
    ticket = setup_started_service_ticket(customer["id"], store["id"], "SKATE_SHARPEN")
    assert ticket["status"] == "IN_PROGRESS"

    res = api.resume_service_ticket(ticket["id"], TECH)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_fulfilled_order_is_invalid_state(api):
    """PRD §3.3: "A cancel requested from any other fulfillment state is an
    undefined transition and is rejected with `ERR_INVALID_STATE`."
    PRD §3.3: "Cancellation can occur from `DRAFT`, `RESERVED`, or `READY`, and
    always lands in `CANCELLED`."

    A FULFILLED order is terminal, so cancel is rejected.

    Design: Corner/state_machines/order_terminal_fulfilled_lockdown_cancel_rejected
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Cap", base_price_cents=2500, size_label="M")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    fulfilled, _ = setup_fulfilled_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    assert fulfilled["fulfillment_status"] == "FULFILLED"

    res = api.cancel_order(fulfilled["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_team_order_reject_leaves_no_spawned_order(api):
    """PRD §3.10: "Rejection advances `SUBMITTED → REJECTED`, spawns no order and
    reserves no inventory, and increments the team order's `version` by one."

    Design: Corner/state_machines/team_order_reject_terminal_no_spawn
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="TEAMWEAR", name="Shorts", base_price_cents=2000,
                     size_label="L", embroiderable=True)
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 10)

    submitted, _ = setup_submitted_team_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 5}],
        team_name="Tigers",
    )
    rejected = get_success_data(api.reject_team_order(submitted["id"], ASSOCIATE))
    assert rejected["status"] == "REJECTED"
    assert rejected["spawned_order_id"] is None


def test_price_match_reject_keeps_approved_price_null(api):
    """PRD §3.7: "Rejecting a claim leaves `approved_unit_price_cents` null and the
    line price unchanged at fulfillment; rejection is permitted only from
    `SUBMITTED`."

    Design: Corner/state_machines/pricematch_reject_keeps_line_price
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Bat2", base_price_cents=7000, size_label="32in")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    placed, lines = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    claim = submit_price_match_claim(placed["id"], lines[0]["id"], customer["id"], 5000)

    rejected = get_success_data(api.reject_price_match_claim(claim["id"], PRICE_ADMIN))
    assert rejected["status"] == "REJECTED"
    assert rejected["approved_unit_price_cents"] is None

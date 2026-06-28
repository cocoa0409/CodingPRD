"""State machine shapes: the cyclic service-ticket lifecycle and the order's two
parallel status axes.

Difficulty queue: non_linear_state_machine.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    create_store,
    create_sku,
    create_customer,
    stock_sku,
    setup_started_service_ticket,
    setup_placed_order,
    create_draft_order,
    add_order_line,
    place_order,
    get_service_ticket,
)


# ===========================================================================
# non_linear_state_machine / service_ticket_needs_parts_inprogress_cycle
# ===========================================================================
def test_service_ticket_flag_parts_then_resume_cycle(api):
    """PRD §3.8: "Flagging for parts advances `IN_PROGRESS → NEEDS_PARTS` with no
    inventory change (the part, if any, was already reserved at start). Resuming
    advances `NEEDS_PARTS → IN_PROGRESS`, cycling back into work with no inventory
    change."

    A started RACKET_STRING ticket goes IN_PROGRESS -> NEEDS_PARTS (flag-parts)
    -> IN_PROGRESS (resume), exercising the cycle.

    Design: Difficulty/non_linear_state_machine/service_ticket_needs_parts_inprogress_cycle
    """
    store = create_store(state_code="CA")
    part_sku = create_sku(sport="APPAREL", name="String Pack", base_price_cents=1500, size_label="NA")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], part_sku["id"], 5)

    ticket = setup_started_service_ticket(
        customer["id"], store["id"], "RACKET_STRING", part_sku_id=part_sku["id"]
    )
    assert ticket["status"] == "IN_PROGRESS"

    flagged = get_success_data(api.flag_parts_service_ticket(ticket["id"], TEST_USERS["service_tech_headers"]))
    assert flagged["status"] == "NEEDS_PARTS"

    resumed = get_success_data(api.resume_service_ticket(ticket["id"], TEST_USERS["service_tech_headers"]))
    assert resumed["status"] == "IN_PROGRESS"


def test_service_ticket_cycle_can_repeat(api):
    """PRD §3.8: "The ticket lifecycle is `RECEIVED`, `IN_PROGRESS`, `NEEDS_PARTS`,
    `COMPLETED`, and `CANCELLED`, with a cycle between `IN_PROGRESS` and
    `NEEDS_PARTS`."

    The IN_PROGRESS<->NEEDS_PARTS cycle can be traversed more than once
    (flag-parts, resume, flag-parts again).

    Design: Difficulty/non_linear_state_machine/service_ticket_needs_parts_inprogress_cycle
    """
    headers = TEST_USERS["service_tech_headers"]
    store = create_store(state_code="CA")
    part_sku = create_sku(sport="APPAREL", name="String Pack", base_price_cents=1500, size_label="NA")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], part_sku["id"], 5)

    ticket = setup_started_service_ticket(
        customer["id"], store["id"], "RACKET_STRING", part_sku_id=part_sku["id"]
    )

    flagged1 = get_success_data(api.flag_parts_service_ticket(ticket["id"], headers))
    assert flagged1["status"] == "NEEDS_PARTS"
    resumed1 = get_success_data(api.resume_service_ticket(ticket["id"], headers))
    assert resumed1["status"] == "IN_PROGRESS"
    flagged2 = get_success_data(api.flag_parts_service_ticket(ticket["id"], headers))
    assert flagged2["status"] == "NEEDS_PARTS"


# ===========================================================================
# non_linear_state_machine / order_parallel_payment_fulfillment_axes
# ===========================================================================
def test_place_advances_both_fulfillment_and_payment_axes(api):
    """PRD §3.3: "advances the payment axis `UNPAID → AUTHORIZED`, placing an
    authorization hold for the provisional total".
    PRD §3.3: "Placing an order advances the fulfillment axis `DRAFT → RESERVED`."

    Placing moves fulfillment_status DRAFT->RESERVED and, independently,
    payment_status UNPAID->AUTHORIZED in one operation.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_axes
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Glove", base_price_cents=4000, size_label="M")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    placed, _ = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}],
        fulfillment_type="SFS",
    )
    assert placed["fulfillment_status"] == "RESERVED"
    assert placed["payment_status"] == "AUTHORIZED"


def test_order_axes_independent_in_draft(api):
    """PRD §3.3: "A new order starts with `fulfillment_status` of `DRAFT`,
    `payment_status` of `UNPAID`, `provisional_total_cents` of 0, and
    `final_total_cents` of null. The two status axes are independent".

    Before placement the two axes sit at their independent initial values
    (DRAFT / UNPAID), confirming they are tracked separately on one row.

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_axes
    """
    store = create_store(state_code="CA")
    customer = create_customer(home_state_code="CA")
    order = create_draft_order(customer["id"], store["id"], "SFS")
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"

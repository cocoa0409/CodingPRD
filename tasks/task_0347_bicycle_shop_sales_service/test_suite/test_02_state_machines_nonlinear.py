"""Non-linear state-machine and cross-entity state-dependency depth tests
(PRD §3.2, §3.3, §3.10).

Queue A — difficulty rules non_linear_state_machine and
cross_entity_state_dependency.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_customer, create_sku, create_tier, create_quoted_ticket,
    create_in_progress_ticket, add_labor_line, create_under_review_claim,
    create_approved_repair_claim,
    approve_warranty_payload,
    TEST_USERS, make_customer_headers,
)

MGR = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
ADV = TEST_USERS["service_advisor_headers"]


# ════════════════════════════════════════════════════════════════════════════
# Rule 3 — non_linear_state_machine / service_ticket_revision_cycle
# ════════════════════════════════════════════════════════════════════════════
def test_revision_cycle_counts_two_loops():
    """PRD §3.2: "Adding a labor line to a ticket that is `IN_PROGRESS` marks
    that line as added after approval and cycles the ticket back to
    `AWAITING_APPROVAL` for re-approval; this is the `IN_PROGRESS →
    AWAITING_APPROVAL` transition, and it may repeat any number of times, with
    each loop tracked by `revision_count`."

    Two add-line/approve loops drive revision_count to 2 and leave the ticket
    back in IN_PROGRESS — a state a linear machine could not re-enter.

    Design: Difficulty/non_linear_state_machine/service_ticket_revision_cycle
    """
    cust = create_customer()
    tier = create_tier(code="STANDARD", base_labor_cents=6000, turnaround_hours=4)
    cust_headers = make_customer_headers(cust["id"])
    # quote -> approve -> IN_PROGRESS
    ticket = create_in_progress_ticket(cust["id"], tier["id"])
    # loop 1: add line (back to AWAITING_APPROVAL) -> approve (IN_PROGRESS)
    add_labor_line(ticket["id"], labor_cents=2000, menu_code="WHEEL_TRUE")
    validate_success(api_client.approve_service_ticket(ticket["id"], cust_headers), 200)
    # loop 2
    add_labor_line(ticket["id"], labor_cents=1500, menu_code="CABLE_REPLACE")
    final = validate_success(api_client.approve_service_ticket(ticket["id"], cust_headers), 200)
    assert final["revision_count"] == 2
    assert final["status"] == "IN_PROGRESS"
    assert final["labor_subtotal_cents"] == 9500


def test_revision_loop_marks_lines_added_after_approval():
    """PRD §3.3: "A line added while the ticket is still in `INTAKE` or
    `AWAITING_APPROVAL` leaves that flag false; a line added while the ticket is
    `IN_PROGRESS` sets it true, bumps the ticket's `revision_count`, and triggers
    the re-approval cycle".

    A labor line added while IN_PROGRESS carries added_after_approval=true.

    Design: Difficulty/non_linear_state_machine/service_ticket_revision_cycle
    """
    cust = create_customer()
    tier = create_tier(code="STANDARD", base_labor_cents=6000, turnaround_hours=4)
    ticket = create_in_progress_ticket(cust["id"], tier["id"])
    line = add_labor_line(ticket["id"], labor_cents=2000, menu_code="WHEEL_TRUE")
    assert line["added_after_approval"] is True
    reread = validate_success(api_client.get_service_ticket(ticket["id"], ADV), 200)
    assert reread["status"] == "AWAITING_APPROVAL"
    assert reread["revision_count"] == 1


# ════════════════════════════════════════════════════════════════════════════
# Rule 3 — non_linear_state_machine / warranty_claim_branch_replace
# ════════════════════════════════════════════════════════════════════════════
def test_replace_branch_reaches_approved_replace():
    """PRD §3.10: "The second branch approves a replacement, supplying a
    `resolution` of `REPLACE` and a `resolution_sku_id`, and moving the claim to
    `APPROVED_REPLACE`."

    The REPLACE fork from UNDER_REVIEW reaches APPROVED_REPLACE.

    Design: Difficulty/non_linear_state_machine/warranty_claim_branch_replace
    """
    cust = create_customer()
    sku = create_sku(name="Carbon Frame", category="BIKE", list_price_cents=120000,
                     on_hand=2, warranty_class="FRAME_AND_COMPONENT", is_serialized=True)
    repl = create_sku(name="Carbon Frame Replacement", category="BIKE",
                      list_price_cents=120000, on_hand=1,
                      warranty_class="FRAME_AND_COMPONENT", is_serialized=True)
    cust2, claim, line = create_under_review_claim(sku["id"], "FRAME", customer_id=cust["id"])
    approved = validate_success(api_client.approve_warranty_claim(
        claim["id"], approve_warranty_payload("REPLACE", resolution_sku_id=repl["id"]), ADV), 200)
    assert approved["status"] == "APPROVED_REPLACE"


def test_replace_branch_reserves_replacement_unit():
    """PRD §3.10: "On success it pulls the replacement from stock by creating one
    `ACTIVE` reservation of quantity 1 against the resolution `Sku`, ... raising
    that `Sku`'s `reserved` and incrementing its `version`."

    Approving REPLACE raises the replacement Sku's reserved to 1 — a side effect
    the REPAIR and DENY branches do not produce.

    Design: Difficulty/non_linear_state_machine/warranty_claim_branch_replace
    """
    cust = create_customer()
    sku = create_sku(name="Carbon Frame B", category="BIKE", list_price_cents=120000,
                     on_hand=2, warranty_class="FRAME_AND_COMPONENT", is_serialized=True)
    repl = create_sku(name="Carbon Frame Replacement B", category="BIKE",
                      list_price_cents=120000, on_hand=1,
                      warranty_class="FRAME_AND_COMPONENT", is_serialized=True)
    cust2, claim, line = create_under_review_claim(sku["id"], "FRAME", customer_id=cust["id"])
    validate_success(api_client.approve_warranty_claim(
        claim["id"], approve_warranty_payload("REPLACE", resolution_sku_id=repl["id"]), ADV), 200)
    repl_after = validate_success(api_client.get_sku(repl["id"], MGR), 200)
    assert repl_after["reserved"] == 1


# ════════════════════════════════════════════════════════════════════════════
# Rule 7 — cross_entity_state_dependency / ticket_close_resolves_linked_warranty_claim
# ════════════════════════════════════════════════════════════════════════════
def test_ticket_close_drives_ticket_to_closed():
    """PRD §3.2: "At pickup, the advisor closes the ticket, moving it from
    `READY_FOR_PICKUP` to `CLOSED`".
    PRD §3.2: "On a successful close of such a ticket, the linked warranty claim
    is transitioned from `APPROVED_REPAIR` to `RESOLVED` in the same operation".

    A warranty-linked ticket walked to READY_FOR_PICKUP closes to CLOSED.

    Design: Difficulty/cross_entity_state_dependency/ticket_close_resolves_linked_warranty_claim
    """
    cust = create_customer()
    tier = create_tier(code="PREMIUM", base_labor_cents=10000, turnaround_hours=8)
    sku = create_sku(name="Derailleur", category="PART", list_price_cents=7000,
                     on_hand=4, warranty_class="COMPONENT")
    cust2, claim, line = create_approved_repair_claim(sku["id"], "COMPONENT",
                                                      customer_id=cust["id"])
    ticket = create_in_progress_ticket(cust["id"], tier["id"],
                                       warranty_claim_id=claim["id"])
    validate_success(api_client.complete_service_ticket(ticket["id"], ADV), 200)
    closed = validate_success(api_client.close_service_ticket(ticket["id"], ADV), 200)
    assert closed["status"] == "CLOSED"


def test_ticket_close_cascades_claim_to_resolved():
    """PRD §3.2: "If the ticket being closed has a `warranty_claim_id` set, that
    linked claim must be in `APPROVED_REPAIR` status at close time ... On a
    successful close of such a ticket, the linked warranty claim is transitioned
    from `APPROVED_REPAIR` to `RESOLVED` in the same operation".

    Closing the linked ticket cascades the claim APPROVED_REPAIR -> RESOLVED.

    Design: Difficulty/cross_entity_state_dependency/ticket_close_resolves_linked_warranty_claim
    """
    cust = create_customer()
    tier = create_tier(code="PREMIUM", base_labor_cents=10000, turnaround_hours=8)
    sku = create_sku(name="Derailleur B", category="PART", list_price_cents=7000,
                     on_hand=4, warranty_class="COMPONENT")
    cust2, claim, line = create_approved_repair_claim(sku["id"], "COMPONENT",
                                                      customer_id=cust["id"])
    ticket = create_in_progress_ticket(cust["id"], tier["id"],
                                       warranty_claim_id=claim["id"])
    validate_success(api_client.complete_service_ticket(ticket["id"], ADV), 200)
    validate_success(api_client.close_service_ticket(ticket["id"], ADV), 200)
    claim_after = validate_success(api_client.get_warranty_claim(claim["id"], ADV), 200)
    assert claim_after["status"] == "RESOLVED"


# ════════════════════════════════════════════════════════════════════════════
# Rule 7 — cross_entity_state_dependency / warranty_approve_requires_delivered_order
# ════════════════════════════════════════════════════════════════════════════
def test_approve_succeeds_only_after_delivery():
    """PRD §3.10: "the `source_order_line_id` must belong to a sales order whose
    fulfillment is `DELIVERED` and whose `customer_id` equals the claim's
    `customer_id`".

    The positive cross-entity case: once the source order is DELIVERED and the
    Sku is covered, approve REPAIR succeeds (UNDER_REVIEW -> APPROVED_REPAIR).

    Design: Difficulty/cross_entity_state_dependency/warranty_approve_requires_delivered_order
    """
    cust = create_customer()
    sku = create_sku(name="Shifter B", category="PART", list_price_cents=6000,
                     on_hand=4, warranty_class="COMPONENT")
    cust2, claim, line = create_under_review_claim(sku["id"], "COMPONENT",
                                                   customer_id=cust["id"])
    approved = validate_success(api_client.approve_warranty_claim(
        claim["id"], approve_warranty_payload("REPAIR"), ADV), 200)
    assert approved["status"] == "APPROVED_REPAIR"

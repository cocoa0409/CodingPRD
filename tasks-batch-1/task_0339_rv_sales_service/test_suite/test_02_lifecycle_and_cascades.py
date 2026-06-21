"""Deal and service-order lifecycles, parallel finance/sale axes, cyclic service
loop, and multi-link cascades (warranty exhaust, hold release, parts conservation).

Covers the non_linear_state_machine and transitive_cascade difficulty rules plus
the state_machine corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    setup_held_deal,
    setup_quoted_deal,
    setup_dealership_customer_unit,
    create_deal_on_unit,
    setup_started_service_order,
    setup_warranty_so_in_progress,
    create_customer,
    create_unit,
    create_recall_campaign,
    create_pdi_inspection_payload,
)

SALES = TEST_USERS["sales_agent_headers"]
MGR = TEST_USERS["dealer_manager_headers"]
SVC = TEST_USERS["service_advisor_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine / deal_parallel_finance_and_sale_dimensions
# ===========================================================================
def test_finance_axis_cycles_through_decline_to_approve(api):
    """PRD §3.4: "A resubmission after a decline moves `finance_status` from
    `DECLINED` back to `REQUESTED` and clears any previously set `apr_bps`".
    PRD §3.4: "When the guard passes, the approval selects the APR for the
    customer's credit tier ... and moves `finance_status` to `APPROVED`."

    REQUESTED -> DECLINED -> REQUESTED -> APPROVED; PRIME P=6000000 n=60 -> mp 115969.

    Design: Difficulty/non_linear_state_machine/deal_parallel_finance_and_sale_dimensions
    """
    dealer, customer, unit, deal = setup_held_deal(
        dealer_overrides={"doc_fee_cents": 29900, "sales_tax_rate_bps": 725},
        customer_overrides={"credit_tier": "PRIME"},
        unit_overrides={"list_price_cents": 6500000},
        sale_price_cents=6000000,
        down_payment_cents=464900,
        term_months=60,
    )
    get_success_data(api_client.quote_deal(deal["id"], SALES))
    get_success_data(api_client.request_finance(deal["id"], SALES))
    get_success_data(api_client.finance_decision(deal["id"], {"decision": "DECLINE"}, MGR))
    get_success_data(api_client.request_finance(deal["id"], SALES, {"term_months": 60}))
    approved = validate_success(api.finance_decision(deal["id"], {"decision": "APPROVE"}, MGR))
    assert approved["finance_status"] == "APPROVED", approved["finance_status"]
    assert approved["monthly_payment_cents"] == 115969, approved["monthly_payment_cents"]


def test_sale_axis_unchanged_by_finance_cycle(api):
    """PRD §3.4: "This decline-to-request-to-approve loop is a true cycle on the
    financing axis and does not disturb where the sale pipeline stands."

    The deal stays in QUOTED on the sale axis while finance cycles to APPROVED.

    Design: Difficulty/non_linear_state_machine/deal_parallel_finance_and_sale_dimensions
    """
    dealer, customer, unit, deal = setup_held_deal(
        customer_overrides={"credit_tier": "PRIME"},
        unit_overrides={"list_price_cents": 6500000},
        sale_price_cents=6000000,
        down_payment_cents=464900,
        term_months=60,
    )
    get_success_data(api_client.quote_deal(deal["id"], SALES))
    get_success_data(api_client.request_finance(deal["id"], SALES))
    get_success_data(api_client.finance_decision(deal["id"], {"decision": "DECLINE"}, MGR))
    get_success_data(api_client.request_finance(deal["id"], SALES, {"term_months": 60}))
    approved = validate_success(api.finance_decision(deal["id"], {"decision": "APPROVE"}, MGR))
    assert approved["sale_status"] == "QUOTED", approved["sale_status"]


# ===========================================================================
# Difficulty: non_linear_state_machine / service_order_cyclic_awaiting_parts_loop
# ===========================================================================
def test_service_order_resumes_after_second_await(api):
    """PRD §3.7: "Awaiting parts moves it from `IN_PROGRESS` to `AWAITING_PARTS`,
    and resuming moves it from `AWAITING_PARTS` back to `IN_PROGRESS`; a single
    order may bounce between `IN_PROGRESS` and `AWAITING_PARTS` many times as parts
    arrive."

    start, await, resume, await, resume leaves the order IN_PROGRESS (re-enterable loop).

    Design: Difficulty/non_linear_state_machine/service_order_cyclic_awaiting_parts_loop
    """
    dealer, customer, unit, so = setup_started_service_order()
    get_success_data(api_client.await_parts(so["id"], SVC))
    get_success_data(api_client.resume_service_order(so["id"], SVC))
    get_success_data(api_client.await_parts(so["id"], SVC))
    resumed = validate_success(api.resume_service_order(so["id"], SVC))
    assert resumed["status"] == "IN_PROGRESS", resumed["status"]


def test_service_order_version_tracks_each_transition(api):
    """PRD §2.4: "The `version` field is an integer that begins at its initial
    value on creation and increments by one on every mutation of the resource".

    create (v1) + 5 transitions (start, await, resume, await, resume) -> version 6.

    Design: Difficulty/non_linear_state_machine/service_order_cyclic_awaiting_parts_loop
    """
    dealer, customer, unit, so = setup_started_service_order()
    get_success_data(api_client.await_parts(so["id"], SVC))
    get_success_data(api_client.resume_service_order(so["id"], SVC))
    get_success_data(api_client.await_parts(so["id"], SVC))
    resumed = validate_success(api.resume_service_order(so["id"], SVC))
    assert resumed["version"] == 6, resumed["version"]


# ===========================================================================
# Difficulty: transitive_cascade / so_complete_warranty_exhaust_chain_depth3
# ===========================================================================
def test_complete_fulfills_reservation_and_decrements_stock(api):
    """PRD §3.7: "every `RESERVED` reservation for the order becomes `FULFILLED`
    and each backing part has its `qty_on_hand` and `qty_reserved` both reduced by
    the fulfilled quantity".

    qty_on_hand 5 -> 4, qty_reserved -> 0 after completing with one part fulfilled.

    Design: Difficulty/transitive_cascade/so_complete_warranty_exhaust_chain_depth3
    """
    dealer, customer, unit, plan, part, so = setup_warranty_so_in_progress(
        plan_cap_cents=300000, deductible_cents=0,
        labor_hours=2.5, labor_rate_cents=12000,
        part_price_cents=270000, part_qty_on_hand=5, reserve_qty=1,
    )
    get_success_data(api_client.complete_service_order(so["id"], SVC))
    part_after = validate_success(api.get_part_item(part["id"], SVC))
    assert part_after["qty_on_hand"] == 4, part_after["qty_on_hand"]
    assert part_after["qty_reserved"] == 0, part_after["qty_reserved"]


def test_complete_consumes_plan_and_auto_exhausts(api):
    """PRD §3.7: "for a warranty order the plan's `consumed_cents` rises by the
    `covered_cents`, and if that brings the consumed total to or above the cap the
    plan automatically moves to `EXHAUSTED`".

    covered 300000 == cap 300000 -> consumed_cents 300000, plan EXHAUSTED.

    Design: Difficulty/transitive_cascade/so_complete_warranty_exhaust_chain_depth3
    """
    dealer, customer, unit, plan, part, so = setup_warranty_so_in_progress(
        plan_cap_cents=300000, deductible_cents=0,
        labor_hours=2.5, labor_rate_cents=12000,
        part_price_cents=270000, part_qty_on_hand=5, reserve_qty=1,
    )
    get_success_data(api_client.complete_service_order(so["id"], SVC))
    plan_after = validate_success(api.get_warranty_plan(plan["id"], SVC))
    assert plan_after["consumed_cents"] == 300000, plan_after["consumed_cents"]
    assert plan_after["status"] == "EXHAUSTED", plan_after["status"]


# ===========================================================================
# Difficulty: transitive_cascade / deal_cancel_releases_unit_hold_depth2
# ===========================================================================
def test_cancel_sets_deal_cancelled(api):
    """PRD §3.5: "Cancellation moves `sale_status` to the terminal `CANCELLED` and
    releases the unit hold as a cascade: the unit goes from `HELD` back to
    `AVAILABLE`, its `active_hold_deal_id` is cleared, and its `version`
    increments."

    Design: Difficulty/transitive_cascade/deal_cancel_releases_unit_hold_depth2
    """
    dealer, customer, unit, deal = setup_held_deal(
        dealer_overrides={"doc_fee_cents": 29900, "sales_tax_rate_bps": 725},
        unit_overrides={"list_price_cents": 7000000},
        sale_price_cents=7000000,
    )
    cancelled = validate_success(api.cancel_deal(deal["id"], SALES))
    assert cancelled["sale_status"] == "CANCELLED", cancelled["sale_status"]


def test_cancel_releases_unit_hold_to_available(api):
    """PRD §3.5: "Cancellation moves `sale_status` to the terminal `CANCELLED` and
    releases the unit hold as a cascade: the unit goes from `HELD` back to
    `AVAILABLE`, its `active_hold_deal_id` is cleared, and its `version`
    increments."

    Design: Difficulty/transitive_cascade/deal_cancel_releases_unit_hold_depth2
    """
    dealer, customer, unit, deal = setup_held_deal(
        unit_overrides={"list_price_cents": 7000000},
        sale_price_cents=7000000,
    )
    get_success_data(api_client.cancel_deal(deal["id"], SALES))
    unit_after = validate_success(api.get_unit(unit["id"], SALES))
    assert unit_after["status"] == "AVAILABLE", unit_after["status"]
    assert unit_after["active_hold_deal_id"] in (None, ""), unit_after["active_hold_deal_id"]


# ===========================================================================
# Corner: state_machines / cancel_already_cancelled_deal_returns_terminal
# ===========================================================================
def test_cancel_already_cancelled_deal_rejected(api):
    """PRD §3.5: "Cancelling a deal ... is rejected with `ERR_DEAL_TERMINAL` once
    the deal is already `DELIVERED` or `CANCELLED`."

    Design: Corner/state_machines/cancel_already_cancelled_deal_returns_terminal
    """
    dealer, customer, unit, deal = setup_held_deal(
        unit_overrides={"list_price_cents": 7000000}, sale_price_cents=7000000
    )
    get_success_data(api_client.cancel_deal(deal["id"], SALES))
    resp = api.cancel_deal(deal["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_DEAL_TERMINAL.value)


# ===========================================================================
# Corner: state_machines / start_service_order_not_open_returns_bad_state
# ===========================================================================
def test_start_already_in_progress_order_rejected(api):
    """PRD §3.7: "Starting work advances it from `OPEN` to `IN_PROGRESS`. ... Each
    of these transitions requires the order to be in the appropriate originating
    state and is otherwise rejected with `ERR_SO_BAD_STATE`."

    Design: Corner/state_machines/start_service_order_not_open_returns_bad_state
    """
    dealer, customer, unit, so = setup_started_service_order()
    resp = api.start_service_order(so["id"], SVC)
    validate_error(resp, ApiErrorId.ERR_SO_BAD_STATE.value)


# ===========================================================================
# Corner: state_machines / complete_from_awaiting_parts_returns_bad_state
# ===========================================================================
def test_complete_from_awaiting_parts_rejected(api):
    """PRD §3.7: "Completing an order is the settlement event for both parts and
    money, and it advances the order from `IN_PROGRESS` to the terminal
    `COMPLETED`; completion from any other state is rejected with
    `ERR_SO_BAD_STATE`."

    Design: Corner/state_machines/complete_from_awaiting_parts_returns_bad_state
    """
    dealer, customer, unit, so = setup_started_service_order()
    get_success_data(api_client.await_parts(so["id"], SVC))
    resp = api.complete_service_order(so["id"], SVC)
    validate_error(resp, ApiErrorId.ERR_SO_BAD_STATE.value)


# ===========================================================================
# Corner: state_machines / new_deal_initial_states_draft_none
# ===========================================================================
def test_new_deal_opens_draft_none_and_holds_unit(api):
    """PRD §3.3: "A freshly created deal opens with `sale_status` of `DRAFT` and
    `finance_status` of `NONE`, captures the creating agent's identifier into
    `sales_agent_user_id`, and — as a side effect — places the unit hold described
    in §3.2."

    Design: Corner/state_machines/new_deal_initial_states_draft_none
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"list_price_cents": 7000000}
    )
    deal = validate_success(
        api.create_deal(
            {
                "dealership_id": dealer["id"], "unit_id": unit["id"],
                "customer_id": customer["id"], "sale_price_cents": 7000000,
                "expected_unit_version": unit["version"],
            },
            SALES,
        ),
        expected_status=201,
    )
    assert deal["sale_status"] == "DRAFT", deal["sale_status"]
    assert deal["finance_status"] == "NONE", deal["finance_status"]
    unit_after = validate_success(api.get_unit(unit["id"], SALES))
    assert unit_after["status"] == "HELD", unit_after["status"]


# ===========================================================================
# Corner: state_machines / deliver_before_walkthrough_returns_bad_sale_state
# ===========================================================================
def test_deliver_before_walkthrough_rejected(api):
    """PRD §3.5: "Delivery requires `sale_status` to be `WALKTHROUGH` (otherwise
    `ERR_DEAL_BAD_SALE_STATE`)".

    A quoted (not WALKTHROUGH) deal cannot be delivered.

    Design: Corner/state_machines/deliver_before_walkthrough_returns_bad_sale_state
    """
    dealer, customer, unit, quoted = setup_quoted_deal(
        unit_overrides={"list_price_cents": 7000000}, sale_price_cents=7000000
    )
    resp = api.deliver_deal(quoted["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_DEAL_BAD_SALE_STATE.value)


# ===========================================================================
# Corner: state_machines / close_recall_with_outstanding_remedies_blocked
# ===========================================================================
def test_close_campaign_with_outstanding_remedy_rejected(api):
    """PRD §3.11: "A campaign may be closed only while it is `OPEN` ... and only
    when every remedy belonging to it is already `CLEARED`; outstanding
    non-cleared remedies block the close with `ERR_REMEDIES_OUTSTANDING`."

    An open campaign on an in-scope unit auto-creates a PENDING remedy that blocks close.

    Design: Corner/state_machines/close_recall_with_outstanding_remedies_blocked
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"class_type": "CLASS_A", "list_price_cents": 9000000}
    )
    rc = create_recall_campaign(
        dealer["id"], target_class_type="CLASS_A", target_model_year=2024, severity="ADVISORY"
    )
    resp = api.close_recall_campaign(rc["id"], MGR)
    validate_error(resp, ApiErrorId.ERR_REMEDIES_OUTSTANDING.value)


# ===========================================================================
# Corner: state_machines / return_consignment_on_stock_unit_rejected
# ===========================================================================
def test_return_consignment_on_stock_unit_rejected(api):
    """PRD §3.1: "The action is permitted only when the unit's `acquisition` is
    `CONSIGNMENT` — a non-consignment unit is rejected with `ERR_NOT_CONSIGNMENT`".

    Design: Corner/state_machines/return_consignment_on_stock_unit_rejected
    """
    dealer, customer, unit = setup_dealership_customer_unit(
        unit_overrides={"list_price_cents": 5000000}
    )
    resp = api.return_consignment(unit["id"], SVC)
    validate_error(resp, ApiErrorId.ERR_NOT_CONSIGNMENT.value)


# ===========================================================================
# Corner: state_machines / pdi_fail_keeps_deal_in_pdi_pending
# ===========================================================================
def test_pdi_fail_keeps_deal_in_pdi_pending(api):
    """PRD §3.5: "The inspection's `result` is computed: it is `PASS` only when
    `defects_found` equals zero and the deal's unit has an `open_recall_count` of
    zero at the moment of inspection, and `FAIL` otherwise. A `FAIL` leaves the
    deal in `PDI_PENDING` for re-inspection."

    Design: Corner/state_machines/pdi_fail_keeps_deal_in_pdi_pending
    """
    dealer, customer, unit, quoted = setup_quoted_deal(
        unit_overrides={"list_price_cents": 7000000}, sale_price_cents=7000000
    )
    get_success_data(api_client.start_pdi(quoted["id"], SALES))
    inspection = validate_success(
        api.create_pdi_inspection(
            create_pdi_inspection_payload(dealer["id"], quoted["id"], 2), SVC
        ),
        expected_status=201,
    )
    assert inspection["result"] == "FAIL", inspection["result"]
    deal_after = validate_success(api.get_deal(quoted["id"], SALES))
    assert deal_after["sale_status"] == "PDI_PENDING", deal_after["sale_status"]
    assert deal_after["pdi_passed"] is False, deal_after["pdi_passed"]

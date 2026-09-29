"""Blockers that live on a related row rather than on the target (PRD §3.3, §3.8)."""

from test_helpers import (
    FLOUR_HRW_INDEXED,
    RICE_FLOUR,
    YEAST_INSTANT,
    ApiErrorId,
    add_contract_line,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    create_customer,
    create_product,
    create_route,
    create_zone,
    dispatch_route,
    draft_contract,
    offer_contract,
    open_order,
    publish_index_quote,
    raise_substitution_request,
    read_contract,
    read_contract_line,
    read_customer,
    read_lot,
    read_order,
    read_order_line,
    read_substitution_request,
    receive_lot,
    seal_route,
    set_clock,
    submit_order,
    validate_error,
)
from test_helpers.fixtures import QM, buyer_headers


def _offered_contract_and_an_order_that_nominates_it():
    """A contract stalled at `OFFERED`, with an order already pointing at it."""
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
    flour = create_product(FLOUR_HRW_INDEXED)
    publish_index_quote(
        index_code=FLOUR_HRW_INDEXED["index_code"],
        effective_on="2026-08-01T00:00:00Z",
        price_cents_per_lb=38,
    )
    zone = create_zone(allergen_class="GLUTEN")
    lot = receive_lot(flour["id"], zone["id"], quantity_received_lb=50000)
    contract = draft_contract(
        customer,
        term_start_on="2026-09-01T00:00:00Z",
        term_end_on="2026-12-31T00:00:00Z",
        pricing_mode="ORDER_DATE_INDEX",
    )
    contract_line = add_contract_line(
        contract["id"], flour["id"], volume_committed_lb=20000, basis_cents_per_lb=6
    )
    offered = offer_contract(contract["id"])
    order = open_order(
        customer,
        contract_id=contract["id"],
        requested_delivery_on="2026-09-15T00:00:00Z",
    )
    line = add_order_line(customer, order["id"], flour["id"], 20000)
    return {
        "customer": customer,
        "flour": flour,
        "lot": lot,
        "contract": offered,
        "contract_line": contract_line,
        "order": order,
        "order_line": line,
    }


class TestContractStateGatesSubmission:
    """The order is legal, the buyer owns it, the quote exists — the contract is not ACTIVE."""

    def test_submitting_against_a_merely_offered_contract_is_refused(self):
        """PRD §3.3: "When the order nominates a contract, that contract's
        `status` must be `ACTIVE`, and the order's `requested_delivery_on` must
        fall on or after `term_start_on` and on or before `term_end_on`, both
        endpoints inclusive; a delivery date outside the term is rejected with
        `ERR_CONTRACT_TERM_NOT_COVERING` (HTTP 422)."

        The delivery date of 2026-09-15 sits inside the term, so the term check
        passes and the only unmet condition is the contract's own status. §2.7
        files that under "the state of related entities", whose error is
        `ERR_RELATED_ENTITY_STATE_INVALID` at HTTP 409.

        Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_by_contract_still_offered_not_active
        """
        scenario = _offered_contract_and_an_order_that_nominates_it()
        assert scenario["contract"]["status"] == "OFFERED", (
            f"Expected the contract to stall at OFFERED, got {scenario['contract']['status']}"
        )
        assert scenario["contract"]["approved_by_user_id"] is None, (
            "An un-activated contract records no approver"
        )

        response = api_client.submit_order(
            scenario["order"]["id"], {}, buyer_headers(scenario["customer"])
        )

        validate_error(response, ApiErrorId.ERR_RELATED_ENTITY_STATE_INVALID)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        assert read_contract(scenario["contract"]["id"])["status"] == "OFFERED", (
            "The refused submission must not activate the contract as a side effect"
        )

    def test_the_refused_submission_draws_no_volume_and_books_no_exposure(self):
        """PRD §3.3: "Submission is the buyer's commitment, and it is the most
        heavily guarded transition in the service, moving `pricing_status` from
        `UNPRICED` to `PROVISIONAL`."

        Because the guard rejected the call, nothing downstream of it may have
        run: no line binds to the commitment, no pounds are drawn, and no money
        is booked.

        Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_by_contract_still_offered_not_active
        """
        scenario = _offered_contract_and_an_order_that_nominates_it()

        api_client.submit_order(
            scenario["order"]["id"], {}, buyer_headers(scenario["customer"])
        )

        order = read_order(scenario["order"]["id"])
        assert order["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {order['pricing_status']}"
        )
        assert order["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {order['fulfillment_status']}"
        )
        assert order["subtotal_cents"] == 0, (
            f"Expected subtotal 0, got {order['subtotal_cents']}"
        )
        assert order["fuel_surcharge_cents"] == 0
        assert order["volume_rebate_cents"] == 0
        assert order["total_cents"] == 0, (
            f"Expected total 0, got {order['total_cents']}"
        )
        line = read_order_line(scenario["order_line"]["id"])
        assert line["contract_line_id"] is None, (
            f"Expected no commitment binding, got {line['contract_line_id']}"
        )
        contract_line = read_contract_line(scenario["contract_line"]["id"])
        assert contract_line["volume_drawn_lb"] == 0, (
            f"Expected volume_drawn_lb 0, got {contract_line['volume_drawn_lb']}"
        )
        assert contract_line["volume_committed_lb"] == 20000
        customer = read_customer(scenario["customer"]["id"])
        assert customer["open_exposure_cents"] == 0, (
            f"Expected exposure 0, got {customer['open_exposure_cents']}"
        )
        assert customer["status"] == "ACTIVE"


def _requested_swap_on_a_dispatched_load():
    """A yeast order that is already on the road, with a swap still on the table.

    Raising the proposal is legal at any point — §2.6 says nothing in the
    substitution state machine forbids the write — so the request reaches
    `REQUESTED` even though the load has left.
    """
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
    yeast = create_product(YEAST_INSTANT)
    rice = create_product(RICE_FLOUR)
    zone = create_zone(allergen_class="NONE")
    lot = receive_lot(
        yeast["id"],
        zone["id"],
        manufactured_on="2026-07-01T00:00:00Z",
        quantity_received_lb=20000,
    )
    order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
    line = add_order_line(customer, order["id"], yeast["id"], 5000)
    submitted = submit_order(customer, order["id"])
    allocate_order(order["id"])
    route = create_route(
        service_on="2026-09-15T00:00:00Z",
        vehicle_capacity_lb=24000,
        service_buffer_minutes=30,
    )
    append_stop(route["id"], order["id"], "2026-09-15T08:00:00Z", "2026-09-15T10:00:00Z")
    seal_route(route["id"])
    set_clock("2026-09-15T00:00:00Z")
    dispatched = dispatch_route(route["id"])
    request = raise_substitution_request(
        line["id"],
        rice["id"],
        read_order(order["id"])["version"],
        specialist_user_id="ts-1",
        rationale="late swap request from the plant floor",
    )
    return {
        "customer": customer,
        "yeast": yeast,
        "rice": rice,
        "lot": lot,
        "order": order,
        "order_line": line,
        "submitted": submitted,
        "route": dispatched,
        "request": request,
    }


class TestParentOrderStateGatesAdjudication:
    """The request is `REQUESTED` and the manager is not the author — the load has shipped."""

    def test_claiming_a_swap_on_a_loaded_order_is_refused(self):
        """PRD §3.8: "That last condition is the reason a dispatched load is
        beyond substitution: once an order reaches `LOADED` it is immutable to
        substitution approval, and any claim or approval against it is rejected
        with `ERR_RELATED_ENTITY_STATE_INVALID`."

        Design: Difficulty/cross_entity_state_dependency/substitution_claim_blocked_by_parent_order_already_loaded
        """
        scenario = _requested_swap_on_a_dispatched_load()
        assert scenario["submitted"]["total_cents"] == 1526750, (
            f"Expected total 1526750, got {scenario['submitted']['total_cents']}"
        )
        assert scenario["route"]["status"] == "DISPATCHED", (
            f"Expected DISPATCHED, got {scenario['route']['status']}"
        )
        assert read_order(scenario["order"]["id"])["fulfillment_status"] == "LOADED", (
            "Dispatch is what carries the order to LOADED"
        )
        assert scenario["request"]["status"] == "REQUESTED", (
            f"Expected the proposal to reach REQUESTED, got {scenario['request']['status']}"
        )

        response = api_client.claim_substitution_request(
            scenario["request"]["id"], {}, QM
        )

        validate_error(response, ApiErrorId.ERR_RELATED_ENTITY_STATE_INVALID)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )

    def test_the_refused_claim_leaves_the_request_and_the_line_untouched(self):
        """PRD §3.8: "Claiming a request moves it `REQUESTED → UNDER_REVIEW` and
        records the claiming manager in `decided_by_user_id`; it requires that
        the request is in `REQUESTED`, that the claimant's `X-User-ID` differs
        from `requested_by_user_id`, and that the parent order's
        `fulfillment_status` is still `NEW` or `ALLOCATED`."

        Design: Difficulty/cross_entity_state_dependency/substitution_claim_blocked_by_parent_order_already_loaded
        """
        scenario = _requested_swap_on_a_dispatched_load()

        api_client.claim_substitution_request(scenario["request"]["id"], {}, QM)

        request = read_substitution_request(scenario["request"]["id"])
        assert request["status"] == "REQUESTED", (
            f"Expected the request to stay REQUESTED, got {request['status']}"
        )
        assert request["decided_by_user_id"] is None, (
            f"Expected no adjudicator recorded, got {request['decided_by_user_id']}"
        )
        assert request["revision_round"] == 0, (
            f"Expected revision_round 0, got {request['revision_round']}"
        )
        assert request["requested_by_user_id"] == "ts-1"
        line = read_order_line(scenario["order_line"]["id"])
        assert line["product_id"] == scenario["yeast"]["id"], (
            f"Expected the yeast SKU still on the line, got {line['product_id']}"
        )
        assert line["lot_id"] == scenario["lot"]["id"], (
            f"Expected the line still bound to its picked lot, got {line['lot_id']}"
        )
        assert read_order(scenario["order"]["id"])["fulfillment_status"] == "LOADED"
        assert read_lot(scenario["lot"]["id"])["quantity_reserved_lb"] == 5000, (
            "A dispatched load still holds its pounds in reserve until the drop is confirmed"
        )

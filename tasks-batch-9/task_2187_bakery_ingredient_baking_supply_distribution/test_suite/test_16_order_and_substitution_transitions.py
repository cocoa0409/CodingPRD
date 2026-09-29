"""Route initialisation, the two order dimensions and the substitution fork (PRD §3.3, §3.5, §3.8, §3.9)."""

from test_helpers import (
    FLOUR_HRW_LIST_ONLY,
    ApiErrorId,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    assert_lot_inventory_conservation,
    claim_substitution_request,
    create_customer,
    create_product,
    create_route_payload,
    create_zone,
    dispatch_route,
    open_order,
    raise_substitution_request,
    read_customer,
    read_lot,
    read_order,
    read_order_line,
    read_substitution_request,
    receive_lot,
    reject_substitution_payload,
    seal_route,
    set_clock,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import LP, QM, buyer_headers

BREAD_FLOUR = dict(
    FLOUR_HRW_LIST_ONLY,
    sku="FLR-BREAD-50",
    list_price_cents_per_lb=30,
    min_rotation_days=0,
)
CAKE_FLOUR = dict(
    FLOUR_HRW_LIST_ONLY,
    sku="FLR-CAKE-50",
    list_price_cents_per_lb=40,
    min_rotation_days=0,
)


def _submitted_thousand_pound_order(with_stock=True):
    """1000 lb of 30-cent bread flour: subtotal 30000, surcharge 750, total 30750."""
    set_clock("2026-08-01T00:00:00Z")
    customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
    flour = create_product(BREAD_FLOUR)
    zone = lot = None
    if with_stock:
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        lot = receive_lot(
            flour["id"],
            zone["id"],
            lot_code="LOT-GLU-A",
            manufactured_on="2026-07-01T00:00:00Z",
            quantity_received_lb=40000,
        )
    order = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on="2026-09-10T00:00:00Z",
    )
    line = add_order_line(customer, order["id"], flour["id"], 1000)
    submitted = submit_order(customer, order["id"])
    return {
        "customer": customer,
        "flour": flour,
        "zone": zone,
        "lot": lot,
        "order": submitted,
        "order_line": line,
    }


class TestRouteInitialState:
    """A trailer opens empty, unlocked and at zero utilisation."""

    def test_a_new_route_opens_in_planning_with_no_allergen_lock(self):
        """PRD §3.9: "A new route has `status` at `PLANNING`, `allergen_class_lock`
        at `NONE`, and `planned_load_lb`, `utilization_pct` and `stop_count` all at
        0."

        Design: Corner/state_machines/corner_new_route_initial_state_is_planning
        """
        set_clock("2026-08-01T00:00:00Z")

        route = validate_success(
            api_client.create_route(
                create_route_payload(
                    route_code="R-INIT",
                    service_on="2026-09-10T00:00:00Z",
                    vehicle_capacity_lb=24000,
                    service_buffer_minutes=30,
                ),
                LP,
            ),
            201,
        )

        assert route["status"] == "PLANNING", (
            f"Expected PLANNING, got {route['status']}"
        )
        assert route["allergen_class_lock"] == "NONE", (
            f"Expected an unlocked trailer, got {route['allergen_class_lock']}"
        )
        assert route["planned_load_lb"] == 0, (
            f"Expected planned_load_lb 0, got {route['planned_load_lb']}"
        )
        assert float(route["utilization_pct"]) == 0, (
            f"Expected utilization_pct 0, got {route['utilization_pct']}"
        )
        assert route["stop_count"] == 0, (
            f"Expected stop_count 0, got {route['stop_count']}"
        )
        assert route["service_buffer_minutes"] == 30, (
            f"Expected the supplied buffer of 30, got {route['service_buffer_minutes']}"
        )


class TestSubmissionIsNotRepeatable:
    """A second submit finds the order out of `UNPRICED` and books nothing twice."""

    def test_resubmitting_a_provisional_order_neither_transitions_nor_double_counts(self):
        """PRD §3.3: "It requires that the order is still `UNPRICED`, that its
        `fulfillment_status` is still `NEW`, that the acting buyer's `X-User-ID`
        equals the order's `customer_id`, that the order carries at least one line,
        and that the bakery's own `status` is `ACTIVE`".

        PRD §3.4: "Open exposure is a separate aggregation, recomputed in full from
        scratch — never incrementally — after submission, after each provisional
        reprice, after final settlement, after invoicing, and after voiding."

        Design: Corner/state_machines/corner_second_submit_on_provisional_order_rejected
        """
        scenario = _submitted_thousand_pound_order(with_stock=False)
        assert scenario["order"]["total_cents"] == 30750, (
            f"Expected total 30750, got {scenario['order']['total_cents']}"
        )

        response = api_client.submit_order(
            scenario["order"]["id"], {}, buyer_headers(scenario["customer"])
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        order = read_order(scenario["order"]["id"])
        assert order["pricing_status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {order['pricing_status']}"
        )
        assert order["total_cents"] == 30750, (
            f"Expected total 30750, got {order['total_cents']}"
        )
        assert read_customer(scenario["customer"]["id"])["open_exposure_cents"] == 30750, (
            "A rebuilt-from-scratch aggregation cannot double-count one order"
        )


class TestDimensionsAreIndependent:
    """Allocation moves the physical dimension and nothing else."""

    def test_allocating_moves_fulfillment_only_and_leaves_the_money_alone(self):
        """PRD §3.3: "An order carries two independent status dimensions.
        `fulfillment_status` tracks the physical life of the load through `NEW`,
        `ALLOCATED`, `ROUTED`, `LOADED`, and then one of the three terminal
        dispositions `DELIVERED`, `SHORT_SHIPPED`, or `CANCELLED`."

        PRD §3.5: "Each line's `lot_id` is set to the lot the selector chose and
        its `allocation_status` becomes `RESERVED`. On each picked lot,
        `quantity_reserved_lb` increases by the line's `quantity_lb` and
        `quantity_on_hand_lb` decreases by the same amount, so the conservation
        invariant of §2.9 holds unchanged."

        Design: Corner/state_machines/corner_allocate_leaves_pricing_dimension_untouched
        """
        scenario = _submitted_thousand_pound_order()

        allocated = allocate_order(scenario["order"]["id"])

        assert allocated["fulfillment_status"] == "ALLOCATED", (
            f"Expected ALLOCATED, got {allocated['fulfillment_status']}"
        )
        assert allocated["pricing_status"] == "PROVISIONAL", (
            f"Expected the commercial dimension untouched, got {allocated['pricing_status']}"
        )
        assert allocated["subtotal_cents"] == 30000, (
            f"Expected subtotal 30000, got {allocated['subtotal_cents']}"
        )
        assert allocated["total_cents"] == 30750, (
            f"Expected total 30750, got {allocated['total_cents']}"
        )
        line = read_order_line(scenario["order_line"]["id"])
        assert line["allocation_status"] == "RESERVED", (
            f"Expected RESERVED, got {line['allocation_status']}"
        )
        assert line["lot_id"] == scenario["lot"]["id"], (
            f"Expected the only eligible lot, got {line['lot_id']}"
        )
        assert line["silo_id"] is None, (
            f"A bagged line has no destination silo, got {line['silo_id']}"
        )
        lot = read_lot(scenario["lot"]["id"])
        assert lot["quantity_on_hand_lb"] == 39000, (
            f"Expected 39000 lb on hand, got {lot['quantity_on_hand_lb']}"
        )
        assert lot["quantity_reserved_lb"] == 1000, (
            f"Expected 1000 lb reserved, got {lot['quantity_reserved_lb']}"
        )
        assert lot["quantity_consumed_lb"] == 0, (
            f"Expected nothing consumed by a reservation, got {lot['quantity_consumed_lb']}"
        )
        assert_lot_inventory_conservation(lot)
        customer = read_customer(scenario["customer"]["id"])
        assert float(customer["allergen_risk_score"]) == 55.00, (
            f"Expected the gluten-only score 55.00, got {customer['allergen_risk_score']}"
        )
        assert customer["risk_tier"] == "AMBER", (
            f"Expected AMBER, got {customer['risk_tier']}"
        )


def _claimed_swap_to_cake_flour(allocate=False):
    """An UNDER_REVIEW proposal to move a 1000 lb line from bread to cake flour."""
    set_clock("2026-08-01T00:00:00Z")
    customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
    bread = create_product(BREAD_FLOUR)
    cake = create_product(CAKE_FLOUR)
    zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
    lot_a = receive_lot(
        bread["id"],
        zone["id"],
        lot_code="LOT-A-0001",
        manufactured_on="2026-07-01T00:00:00Z",
        quantity_received_lb=40000,
    )
    lot_b = receive_lot(
        cake["id"],
        zone["id"],
        lot_code="LOT-B-0001",
        manufactured_on="2026-07-01T00:00:00Z",
        quantity_received_lb=40000,
    )
    order = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on="2026-09-10T00:00:00Z",
    )
    line = add_order_line(customer, order["id"], bread["id"], 1000)
    submitted = submit_order(customer, order["id"])
    if allocate:
        allocate_order(order["id"])
    request = raise_substitution_request(
        line["id"],
        cake["id"],
        read_order(order["id"])["version"],
        rationale="Switch to cake flour after a bench trial",
    )
    claim_substitution_request(request["id"])
    return {
        "customer": customer,
        "bread": bread,
        "cake": cake,
        "lot_a": lot_a,
        "lot_b": lot_b,
        "order": submitted,
        "order_line": line,
        "request": request,
    }


class TestSubstitutionFork:
    """Both arcs out of `UNDER_REVIEW`, distinguished by what they cascade."""

    def test_rejection_leaves_the_line_and_the_totals_exactly_as_they_were(self):
        """PRD §3.8: "Rejection is the sibling branch out of `UNDER_REVIEW`, and its
        specification is deliberately narrow. It requires that the request is in
        `UNDER_REVIEW` and that the rejecting manager's `X-User-ID` differs from
        `requested_by_user_id`; it optionally carries a `decision_note`; and it
        moves the request to `REJECTED`."

        PRD §3.8: "**Hop one:** the order line's current `product_id` is copied into
        `substituted_from_product_id`, and `product_id` becomes the request's
        `proposed_product_id`."

        Hop one is what rejection does not do: the line keeps the 30-cent bread
        flour, so the order stays at 30750 rather than moving to the 41000 the cake
        flour would have cost.

        Design: Corner/state_machines/corner_reject_substitution_leaves_order_line_and_totals_untouched
        """
        scenario = _claimed_swap_to_cake_flour()

        rejected = validate_success(
            api_client.reject_substitution_request(
                scenario["request"]["id"],
                reject_substitution_payload(
                    decision_note="Protein spec incompatible with the customer's rye blend"
                ),
                QM,
            )
        )

        assert rejected["status"] == "REJECTED", (
            f"Expected REJECTED, got {rejected['status']}"
        )
        assert rejected["decided_by_user_id"] == "qm-1", (
            f"Expected the deciding manager recorded, got {rejected['decided_by_user_id']}"
        )
        line = read_order_line(scenario["order_line"]["id"])
        assert line["product_id"] == scenario["bread"]["id"], (
            f"Expected the original SKU on the line, got {line['product_id']}"
        )
        assert line["substituted_from_product_id"] is None, (
            f"Expected substituted_from_product_id still null, got "
            f"{line['substituted_from_product_id']}"
        )
        order = read_order(scenario["order"]["id"])
        assert order["subtotal_cents"] == 30000, (
            f"Expected subtotal 30000, got {order['subtotal_cents']}"
        )
        assert order["total_cents"] == 30750, (
            f"Expected total 30750 rather than the cake flour's 41000, got "
            f"{order['total_cents']}"
        )
        assert read_customer(scenario["customer"]["id"])["open_exposure_cents"] == 30750

    def test_approval_releases_the_old_lot_and_reserves_one_of_the_new_sku(self):
        """PRD §3.8: "**Hop two:** because the line's product changed, any existing
        `RESERVED` allocation is released — the line's `allocation_status` becomes
        `RELEASED` and the old lot returns the line's pounds from
        `quantity_reserved_lb` to `quantity_on_hand_lb` — and the rotation selector
        of §3.5 re-picks a lot of the new product and re-reserves it; if no eligible
        lot of the new product exists, the approval is rejected with
        `ERR_NO_ELIGIBLE_LOT`."

        PRD §3.8: "**Hop three:** because the line's product and unit price
        changed, the order is repriced through the `PROVISIONAL` self-loop, changing
        `subtotal_cents`, `volume_rebate_cents` and `total_cents`."

        Design: Corner/state_machines/corner_substitution_approval_repicks_lot_only_for_reserved_line
        """
        scenario = _claimed_swap_to_cake_flour(allocate=True)
        assert read_order_line(scenario["order_line"]["id"])["lot_id"] == scenario["lot_a"]["id"]

        approved = validate_success(
            api_client.approve_substitution_request(
                scenario["request"]["id"], {}, QM
            )
        )

        assert approved["status"] == "APPROVED", (
            f"Expected APPROVED, got {approved['status']}"
        )
        assert read_order_line(scenario["order_line"]["id"])["lot_id"] == scenario["lot_b"]["id"], (
            "The re-pick must bind the line to a lot of the new SKU"
        )
        lot_a = read_lot(scenario["lot_a"]["id"])
        assert lot_a["quantity_on_hand_lb"] == 40000, (
            f"Expected the released lot whole again, got {lot_a['quantity_on_hand_lb']}"
        )
        assert lot_a["quantity_reserved_lb"] == 0, (
            f"Expected nothing left reserved on the old lot, got {lot_a['quantity_reserved_lb']}"
        )
        assert lot_a["quantity_consumed_lb"] == 0
        assert_lot_inventory_conservation(lot_a)
        lot_b = read_lot(scenario["lot_b"]["id"])
        assert lot_b["quantity_on_hand_lb"] == 39000, (
            f"Expected 39000 lb on hand, got {lot_b['quantity_on_hand_lb']}"
        )
        assert lot_b["quantity_reserved_lb"] == 1000, (
            f"Expected 1000 lb reserved on the new lot, got {lot_b['quantity_reserved_lb']}"
        )
        assert_lot_inventory_conservation(lot_b)
        order = read_order(scenario["order"]["id"])
        assert order["subtotal_cents"] == 40000, (
            f"Expected subtotal 40000, got {order['subtotal_cents']}"
        )
        assert order["fuel_surcharge_cents"] == 1000, (
            f"Expected surcharge 1000, got {order['fuel_surcharge_cents']}"
        )
        assert order["total_cents"] == 41000, (
            f"Expected total 41000, got {order['total_cents']}"
        )
        customer = read_customer(scenario["customer"]["id"])
        assert customer["open_exposure_cents"] == 41000, (
            f"Expected exposure 41000, got {customer['open_exposure_cents']}"
        )
        assert customer["status"] == "ACTIVE", (
            f"Expected the account still ACTIVE, got {customer['status']}"
        )


class TestClaimGuardReadsTheParentOrder:
    """`REQUESTED → UNDER_REVIEW` is guarded by a different entity's state."""

    def test_claiming_a_proposal_on_a_dispatched_load_is_refused(self):
        """PRD §3.8: "Claiming a request moves it `REQUESTED → UNDER_REVIEW` and
        records the claiming manager in `decided_by_user_id`; it requires that the
        request is in `REQUESTED`, that the claimant's `X-User-ID` differs from
        `requested_by_user_id`, and that the parent order's `fulfillment_status` is
        still `NEW` or `ALLOCATED`."

        PRD §3.8: "That last condition is the reason a dispatched load is beyond
        substitution: once an order reaches `LOADED` it is immutable to substitution
        approval, and any claim or approval against it is rejected with
        `ERR_RELATED_ENTITY_STATE_INVALID`."

        Design: Corner/state_machines/corner_claim_substitution_on_loaded_order_rejected
        """
        scenario = _submitted_thousand_pound_order()
        cake = create_product(CAKE_FLOUR)
        allocate_order(scenario["order"]["id"])
        route = validate_success(
            api_client.create_route(
                create_route_payload(
                    route_code="R-LOAD",
                    service_on="2026-09-10T00:00:00Z",
                    vehicle_capacity_lb=24000,
                    service_buffer_minutes=30,
                ),
                LP,
            ),
            201,
        )
        append_stop(
            route["id"],
            scenario["order"]["id"],
            "2026-09-10T08:00:00Z",
            "2026-09-10T10:00:00Z",
        )
        seal_route(route["id"])
        set_clock("2026-09-10T00:00:00Z")
        dispatch_route(route["id"])
        assert read_order(scenario["order"]["id"])["fulfillment_status"] == "LOADED", (
            "Dispatch is what carries the order to LOADED"
        )
        request = raise_substitution_request(
            scenario["order_line"]["id"],
            cake["id"],
            read_order(scenario["order"]["id"])["version"],
            rationale="Late request to swap the sponge flour on the trailer",
        )

        response = api_client.claim_substitution_request(request["id"], {}, QM)

        validate_error(response, ApiErrorId.ERR_RELATED_ENTITY_STATE_INVALID)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        after = read_substitution_request(request["id"])
        assert after["status"] == "REQUESTED", (
            f"Expected the request to stay REQUESTED, got {after['status']}"
        )
        assert after["decided_by_user_id"] is None, (
            f"Expected no adjudicator recorded, got {after['decided_by_user_id']}"
        )

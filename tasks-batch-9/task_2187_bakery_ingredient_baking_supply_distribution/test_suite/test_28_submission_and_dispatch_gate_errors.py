"""One-cent and one-day misses on the submission, dispatch and drop gates (PRD §2.3, §2.7, §3.3, §3.5, §3.10)."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_contract_line,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    activate_contract,
    create_customer,
    create_product,
    create_route,
    create_route_stop_payload,
    create_zone,
    draft_contract,
    offer_contract,
    open_order,
    publish_index_quote,
    quarantine_lot,
    read_contract_line,
    read_customer,
    read_lot,
    read_order,
    read_order_line,
    read_route,
    read_route_stop,
    receive_lot,
    seal_route,
    set_clock,
    short_drop_payload,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AM, LP, WO, buyer_headers

EPOCH = "2026-08-01T00:00:00Z"
SERVICE_ON = "2026-09-10T00:00:00Z"

FLOUR_30 = {
    "sku": "FLR-GATE-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 365,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


class TestTheContractTermIsInclusiveAtItsFarEnd:
    """The last day of the term is covered; the next day is not."""

    def test_a_delivery_one_day_past_the_term_end_is_refused(self):
        """PRD §3.3: "When the order nominates a contract, that contract's `status` must
        be `ACTIVE`, and the order's `requested_delivery_on` must fall on or after
        `term_start_on` and on or before `term_end_on`, both endpoints inclusive; a
        delivery date outside the term is rejected with
        `ERR_CONTRACT_TERM_NOT_COVERING` (HTTP 422)."

        PRD §3.4: "From the prevailing quote the engine takes `price_cents_per_lb`, adds
        the commitment line's `basis_cents_per_lb`, and then applies cap and floor in
        exactly that order"

        Design: Corner/errors/corner_err_delivery_one_day_past_inclusive_term_end_not_covered
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(
            dict(FLOUR_30, sku="FLR-TRM-30", index_code="HRW_WHEAT")
        )
        publish_index_quote(
            index_code="HRW_WHEAT",
            effective_on="2026-08-01T00:00:00Z",
            price_cents_per_lb=100,
        )
        contract = draft_contract(
            customer,
            term_start_on="2026-09-01T00:00:00Z",
            term_end_on="2026-09-30T00:00:00Z",
            pricing_mode="ORDER_DATE_INDEX",
        )
        contract_line = add_contract_line(
            contract["id"], flour["id"],
            volume_committed_lb=50000,
            basis_cents_per_lb=5,
            cap_cents_per_lb=200,
        )
        offer_contract(contract["id"])
        activate_contract(contract["id"])
        late = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-10-01T00:00:00Z",
            contract_id=contract["id"],
        )
        late_line = add_order_line(customer, late["id"], flour["id"], 1000)

        response = api_client.submit_order(late["id"], {}, buyer_headers(customer))

        validate_error(response, ApiErrorId.ERR_CONTRACT_TERM_NOT_COVERING)
        assert response.status_code == 422, (
            f"Expected HTTP 422, got {response.status_code}"
        )
        refused = read_order(late["id"])
        assert refused["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {refused['fulfillment_status']}"
        )
        assert refused["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {refused['pricing_status']}"
        )
        unpriced_line = read_order_line(late_line["id"])
        assert unpriced_line["unit_price_cents"] == 0, (
            f"Expected no price written, got {unpriced_line['unit_price_cents']}"
        )
        assert unpriced_line["contract_line_id"] is None, (
            f"Expected no commitment binding, got {unpriced_line['contract_line_id']}"
        )
        assert read_contract_line(contract_line["id"])["volume_drawn_lb"] == 0, (
            "A refused submission draws no volume"
        )

        on_the_last_day = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-30T00:00:00Z",
            contract_id=contract["id"],
        )
        covered_line = add_order_line(
            customer, on_the_last_day["id"], flour["id"], 1000
        )
        submitted = submit_order(customer, on_the_last_day["id"])

        assert submitted["pricing_status"] == "PROVISIONAL", (
            f"The inclusive endpoint must submit, got {submitted['pricing_status']}"
        )
        assert read_order_line(covered_line["id"])["unit_price_cents"] == 105, (
            "Expected the 100 c print plus the 5 c basis"
        )
        assert submitted["total_cents"] == 107625, (
            f"Expected 105000 plus 2625 of fuel, got {submitted['total_cents']}"
        )


class TestDispatchComparesDatesNotOrdering:
    """The evening before is as wrong as the day after."""

    def test_dispatching_on_the_ninth_is_refused_and_the_tenth_succeeds(self):
        """PRD §3.10: "A `LogisticsPlanner` moves a route `SEALED → DISPATCHED` only
        when the logical clock date equals the route's `service_on`; any other date is
        rejected with `ERR_ROUTE_DATE_MISMATCH`." ... "Dispatch advances each stop's
        order `ROUTED → LOADED` and increments the route's `version` by 1."

        PRD §3.9: "Sealing assigns each stop's `sequence_no` as a one-based position
        ordered by `window_start_at` ascending then `created_at` ascending"

        Design: Corner/errors/corner_err_dispatch_one_day_before_service_date_rejected
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-DTE-30"))
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        receive_lot(
            flour["id"], zone["id"], lot_code="LOT-DTE-0001",
            manufactured_on="2026-08-01T00:00:00Z", quantity_received_lb=20000,
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        add_order_line(customer, order["id"], flour["id"], 1000)
        submit_order(customer, order["id"])
        allocate_order(order["id"])
        route = create_route(
            route_code="R-DATE",
            service_on=SERVICE_ON,
            vehicle_capacity_lb=48000,
            service_buffer_minutes=30,
        )
        stop = append_stop(
            route["id"], order["id"],
            "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z",
        )
        seal_route(route["id"])
        set_clock("2026-09-09T23:00:00Z")

        response = api_client.dispatch_route(route["id"], {}, LP)

        validate_error(response, ApiErrorId.ERR_ROUTE_DATE_MISMATCH)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        held = read_route(route["id"])
        assert held["status"] == "SEALED", (
            f"Expected the route still SEALED, got {held['status']}"
        )
        waiting = read_route_stop(stop["id"])
        assert waiting["sequence_no"] == 1, (
            f"The seal's sequence survives, got {waiting['sequence_no']}"
        )
        assert waiting["status"] == "PLANNED", (
            f"Expected PLANNED, got {waiting['status']}"
        )
        assert read_order(order["id"])["fulfillment_status"] == "ROUTED", (
            "The order stays ROUTED until a legal dispatch"
        )

        set_clock("2026-09-10T05:00:00Z")
        dispatched = validate_success(
            api_client.dispatch_route(route["id"], {}, LP), 200
        )

        assert dispatched["status"] == "DISPATCHED", (
            f"The service date itself dispatches, got {dispatched['status']}"
        )
        assert read_order(order["id"])["fulfillment_status"] == "LOADED", (
            "Dispatch loads the routed order"
        )


class TestTheMinimumDropIsComparedAgainstTheSettledTotal:
    """30000 of goods plus 750 of fuel is 30750, and 30751 refuses it."""

    def test_a_total_one_cent_under_the_floor_is_refused_and_equality_passes(self):
        """PRD §3.3: "The order's computed `total_cents` must reach the bakery's
        `min_drop_cents`; a total exactly equal to the floor passes, and a total strictly
        below it is rejected with `ERR_MIN_DROP_NOT_MET` (HTTP 422)."

        PRD §3.3: "A successful submission stamps `order_placed_on` with the logical
        clock date, runs the three pricing calculations of §3.4 in their pinned order,
        recomputes the bakery's `open_exposure_cents`, and increments the order's
        `version` by 1."

        Design: Corner/errors/corner_err_total_one_cent_under_min_drop_rejected
        """
        set_clock(EPOCH)
        strict = create_customer(credit_limit_cents=10000000, min_drop_cents=30751)
        flour = create_product(dict(FLOUR_30, sku="FLR-MIN-30"))
        order = open_order(
            strict,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        line = add_order_line(strict, order["id"], flour["id"], 1000)

        response = api_client.submit_order(order["id"], {}, buyer_headers(strict))

        validate_error(response, ApiErrorId.ERR_MIN_DROP_NOT_MET)
        assert response.status_code == 422, (
            f"Expected HTTP 422, got {response.status_code}"
        )
        refused = read_order(order["id"])
        assert refused["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {refused['fulfillment_status']}"
        )
        assert refused["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {refused['pricing_status']}"
        )
        assert refused["total_cents"] == 0, (
            f"Expected nothing settled, got {refused['total_cents']}"
        )
        assert refused["order_placed_on"] is None, (
            f"Only a successful submission stamps the date, got "
            f"{refused['order_placed_on']}"
        )
        assert read_order_line(line["id"])["extended_cents"] == 0, (
            "A refused submission extends no line"
        )
        assert read_customer(strict["id"])["open_exposure_cents"] == 0, (
            "A refused submission books no exposure"
        )

        equal = create_customer(credit_limit_cents=10000000, min_drop_cents=30750)
        matching = open_order(
            equal,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        add_order_line(equal, matching["id"], flour["id"], 1000)
        submitted = submit_order(equal, matching["id"])

        assert submitted["total_cents"] == 30750, (
            f"Expected 30000 plus 750 of fuel, got {submitted['total_cents']}"
        )
        assert submitted["pricing_status"] == "PROVISIONAL", (
            f"A total exactly equal to the floor passes, got "
            f"{submitted['pricing_status']}"
        )


class TestTheCreditGateRejectsOnlyStrictExcess:
    """61500 against 61499 is one cent too many, and the account keeps its standing."""

    def test_the_second_order_is_refused_with_payment_required(self):
        """PRD §3.3: "Then the bakery's existing `open_exposure_cents` plus this order's
        computed `total_cents` must be no greater than its `credit_limit_cents`; a sum
        that strictly exceeds the limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 402)."

        PRD §3.4: "Immediately afterwards the account standing is re-derived: an
        `ACTIVE` bakery whose recomputed exposure strictly exceeds its
        `credit_limit_cents` moves to `CREDIT_HOLD`"

        Design: Corner/errors/corner_err_second_order_exceeds_credit_limit_by_one_cent
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=61499, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-CRD-30"))
        first = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        add_order_line(customer, first["id"], flour["id"], 1000)
        submit_order(customer, first["id"])
        second = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-11T00:00:00Z",
        )
        second_line = add_order_line(customer, second["id"], flour["id"], 1000)

        response = api_client.submit_order(second["id"], {}, buyer_headers(customer))

        validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert response.status_code == 402, (
            f"Expected HTTP 402, got {response.status_code}"
        )
        refused = read_order(second["id"])
        assert refused["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {refused['fulfillment_status']}"
        )
        assert refused["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {refused['pricing_status']}"
        )
        assert read_order_line(second_line["id"])["unit_price_cents"] == 0, (
            "A refused submission prices no line"
        )
        standing = read_customer(customer["id"])
        assert standing["open_exposure_cents"] == 30750, (
            f"Only the first order is booked, got {standing['open_exposure_cents']}"
        )
        assert standing["status"] == "ACTIVE", (
            f"A failed submit raises no credit hold, got {standing['status']}"
        )


class TestTheShortQuantityBandIsOpenAtBothEnds:
    """A full drop through the short form is refused, and so is a zero drop."""

    def test_delivering_the_whole_order_on_the_short_endpoint_is_refused(self):
        """PRD §3.10: "The operator supplies a `delivered_lb_total` and a
        `short_reason`; the delivered total must be strictly greater than zero and
        strictly less than the total of `quantity_lb` across the order's lines, since a
        zero drop is an abort and a complete drop is a full delivery. A
        `delivered_lb_total` outside that open range is rejected with
        `ERR_SHORT_QUANTITY_INVALID` (HTTP 422)."

        PRD §3.5: "On each picked lot, `quantity_reserved_lb` increases by the line's
        `quantity_lb` and `quantity_on_hand_lb` decreases by the same amount"

        Design: Corner/errors/corner_err_short_drop_of_the_full_requested_quantity_invalid
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-SHE-30"))
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        lot = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-SHE-0001",
            manufactured_on="2026-08-01T00:00:00Z", quantity_received_lb=20000,
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        line = add_order_line(customer, order["id"], flour["id"], 4000)
        submit_order(customer, order["id"])
        allocate_order(order["id"])
        route = create_route(
            route_code="R-SHORTEDGE",
            service_on=SERVICE_ON,
            vehicle_capacity_lb=48000,
            service_buffer_minutes=30,
        )
        stop = append_stop(
            route["id"], order["id"],
            "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z",
        )
        seal_route(route["id"])
        set_clock("2026-09-10T06:00:00Z")
        api_client.dispatch_route(route["id"], {}, LP)

        response = api_client.short_route_stop(
            stop["id"],
            short_drop_payload(
                4000, short_reason="Driver reported a full drop on the short form"
            ),
            WO,
        )

        validate_error(response, ApiErrorId.ERR_SHORT_QUANTITY_INVALID)
        assert response.status_code == 422, (
            f"Expected HTTP 422, got {response.status_code}"
        )
        assert read_route_stop(stop["id"])["status"] == "PLANNED", (
            "The stop is untouched by the refused drop"
        )
        loaded = read_order(order["id"])
        assert loaded["fulfillment_status"] == "LOADED", (
            f"Expected LOADED, got {loaded['fulfillment_status']}"
        )
        assert loaded["short_ship_lb"] == 0, (
            f"Expected no shorted pounds recorded, got {loaded['short_ship_lb']}"
        )
        assert read_order_line(line["id"])["allocation_status"] == "RESERVED", (
            "No pounds have shipped"
        )
        untouched = read_lot(lot["id"])
        assert untouched["quantity_reserved_lb"] == 4000, (
            f"Expected 4000 lb still reserved, got {untouched['quantity_reserved_lb']}"
        )
        assert untouched["quantity_consumed_lb"] == 0, (
            f"Expected nothing consumed, got {untouched['quantity_consumed_lb']}"
        )
        assert untouched["quantity_on_hand_lb"] == 16000, (
            f"Expected 16000 lb on hand, got {untouched['quantity_on_hand_lb']}"
        )

        zero_drop = api_client.short_route_stop(
            stop["id"],
            short_drop_payload(0, short_reason="Driver never opened the trailer"),
            WO,
        )

        validate_error(zero_drop, ApiErrorId.ERR_SHORT_QUANTITY_INVALID)
        assert read_route_stop(stop["id"])["status"] == "PLANNED", (
            "The band is open at the low end too"
        )


class TestTheCandidateSetEmptiesForTwoReasonsAtOnce:
    """The only fresh lot is held and the only free lot is too old."""

    def test_allocation_refuses_rather_than_picking_stale_or_held_stock(self):
        """PRD §3.5: "For a given order line, a lot is a candidate when all six of the
        following hold: the lot's `product_id` equals the line's `product_id`; the lot's
        `status` is `AVAILABLE`; the lot's `quantity_on_hand_lb` is at least the line's
        `quantity_lb`; the number of whole UTC days from the logical clock date to the
        lot's `expires_on` is at least the product's `min_rotation_days`" ... "If the
        candidate set is empty for any line, the operation is rejected with
        `ERR_NO_ELIGIBLE_LOT` (HTTP 409)."

        PRD §3.5: "Lots that are `QUARANTINED`, `EXPIRED`, `DISPOSED` or `DEPLETED` are
        never candidates."

        The stale lot expires on 2026-10-28, which is 88 days from the clock against a
        120-day floor, while the fresh lot is held.

        Design: Corner/errors/corner_err_no_eligible_lot_when_fresh_stock_is_quarantined
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(
            dict(FLOUR_30, sku="FLR-ROT-30", shelf_life_days=180, min_rotation_days=120)
        )
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        stale = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-ROT-STALE",
            manufactured_on="2026-05-01T00:00:00Z", quantity_received_lb=20000,
        )
        fresh = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-ROT-FRESH",
            manufactured_on="2026-07-20T00:00:00Z", quantity_received_lb=20000,
        )
        quarantine_lot(fresh["id"], quarantine_reason="Held pending mycotoxin retest")
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        line = add_order_line(customer, order["id"], flour["id"], 1000)
        submit_order(customer, order["id"])

        response = api_client.allocate_order(order["id"], {}, WO)

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_LOT)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        assert read_order(order["id"])["fulfillment_status"] == "NEW", (
            "A refused allocation leaves the order at NEW"
        )
        unallocated = read_order_line(line["id"])
        assert unallocated["allocation_status"] == "UNALLOCATED", (
            f"Expected UNALLOCATED, got {unallocated['allocation_status']}"
        )
        assert unallocated["lot_id"] is None, (
            f"Expected no lot picked, got {unallocated['lot_id']}"
        )
        assert read_lot(stale["id"])["quantity_reserved_lb"] == 0, (
            "The stale lot fails the rotation floor and reserves nothing"
        )
        held = read_lot(fresh["id"])
        assert held["quantity_reserved_lb"] == 0, (
            f"Expected nothing reserved on the held lot, got "
            f"{held['quantity_reserved_lb']}"
        )
        assert held["status"] == "QUARANTINED", (
            f"Allocation never releases held stock, got {held['status']}"
        )


class TestThePaginationBandOnAListEndpoint:
    """100 is inside the band; 101 and 0 are not."""

    def test_a_limit_of_one_hundred_and_one_fails_schema_validation(self):
        """PRD §2.3: "Every collection endpoint accepts two optional query parameters,
        `limit` and `offset`. When `limit` is omitted it defaults to 10; the smallest
        accepted value is 1 and the largest accepted value is 100. A `limit` below 1 or
        above 100 is a schema violation and is rejected with `ERR_VALIDATION`
        (HTTP 400)."

        Design: Corner/errors/corner_err_pagination_limit_101_invalid_on_list_endpoint
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)

        response = api_client.list_orders(
            AM, params={"customer_id": customer["id"], "limit": 101, "offset": 0}
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION)
        assert response.status_code == 400, (
            f"Expected HTTP 400, got {response.status_code}"
        )
        rows, _meta = validate_paginated(
            api_client.list_orders(
                AM, params={"customer_id": customer["id"], "limit": 100, "offset": 0}
            )
        )
        assert rows == [], (
            f"The upper endpoint is accepted and the bakery has no orders, got {len(rows)}"
        )
        below = api_client.list_orders(
            AM, params={"customer_id": customer["id"], "limit": 0, "offset": 0}
        )
        validate_error(below, ApiErrorId.ERR_VALIDATION)
        assert below.status_code == 400, (
            f"The band is closed at 1 as well, got {below.status_code}"
        )


class TestExistenceIsCheckedLeftToRight:
    """An unknown path id is reported before an unknown body id."""

    def test_the_unknown_route_in_the_path_outranks_the_unknown_order_in_the_body(self):
        """PRD §2.7: "Nested resources are addressed hierarchically, and existence is
        verified strictly left to right: the route before the stop, the contract before
        the contract line, the order before the order line. The first path segment whose
        referenced row does not exist produces `ERR_RESOURCE_NOT_FOUND` (HTTP 404), and
        no deeper segment is examined. Foreign keys arriving in a request body are a
        separate concern" ... "a key that does not resolve yields
        `ERR_REFERENCED_ENTITY_NOT_FOUND`, also HTTP 404."

        PRD §2.7: "Only after all of that do state and business checks run, in this
        order: the target resource's own state-transition legality"

        Both identifiers are unknown and the version token is genuine, so any answer
        other than the path 404 would betray the wrong resolution order.

        Design: Corner/errors/corner_err_unknown_route_in_path_beats_unknown_order_in_body_not_found
        """
        set_clock(EPOCH)
        real_route = create_route(
            route_code="R-404",
            service_on=SERVICE_ON,
            vehicle_capacity_lb=48000,
            service_buffer_minutes=30,
        )

        response = api_client.create_route_stop(
            NON_EXISTENT_UUID,
            create_route_stop_payload(
                "00000000-0000-0000-0000-0000000000ee",
                real_route["version"],
                window_start_at="2026-09-10T08:00:00Z",
                window_end_at="2026-09-10T09:00:00Z",
            ),
            LP,
        )

        validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
        assert response.status_code == 404, (
            f"Expected the path 404 rather than a body or version error, got "
            f"{response.status_code}"
        )
        stops, _meta = validate_paginated(api_client.list_route_stops(LP))
        assert stops == [], (
            f"No stop may be created by the refused call, got {len(stops)}"
        )
        assert read_route(real_route["id"])["stop_count"] == 0, (
            "The real route is untouched"
        )

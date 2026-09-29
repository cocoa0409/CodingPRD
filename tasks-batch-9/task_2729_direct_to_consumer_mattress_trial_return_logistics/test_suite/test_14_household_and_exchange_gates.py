"""Aggregate gates: the household trial limit, one live return per order and the
two comfort-exchange guards.

What these four rules share is that no single request in the setup is illegal —
the refusal comes from an aggregate over rows the caller cannot see in one place.
"""

from test_helpers import (
    AGENT,
    LOGISTICS,
    ApiErrorId,
    api_client,
    add_order_for_customer,
    approve_comfort_exchange,
    comfort_exchange_payload,
    create_customer_row,
    create_model,
    get_success_data,
    read_customer,
    read_order,
    request_comfort_exchange,
    return_case_payload,
    set_clock,
    setup_delivered_order,
    setup_return_lifecycle,
    trial_order_payload,
    validate_error,
    validate_paginated,
)


class TestHouseholdTrialLimitCountsDeliveredOrders:
    """Two mattresses have already been in the house, so the third is refused."""

    def test_a_third_household_order_is_refused_even_though_both_earlier_ones_closed(self):
        """PRD §3.3: "And the household as a whole, counting every customer that shares the hash, may have at most one trial order that has ever reached `DELIVERED`; a second such order is the limit, so the count of already-delivered household orders must be strictly fewer than two."

        Three customers share HH-V6. The first two orders were delivered and then
        kept, so nothing is live any more — but the aggregate count of orders that
        have ever reached DELIVERED is two, and the third customer is refused.

        Design: Corner/validations/third_household_trial_returns_household_trial_limit
        """
        set_clock("2026-08-01T00:00:00Z")
        model = create_model(
            sku="MDL-Q-V6", name="Comfort Q", list_price_cents=120000
        )
        customers = [
            create_customer_row(
                email=f"v6{tag}@example.com",
                full_name=f"Val Six {tag.upper()}",
                household_hash="HH-V6",
            )
            for tag in ("a", "b", "c")
        ]

        for customer in customers[:2]:
            order = add_order_for_customer(
                customer, model, delivered_at="2026-08-01T00:00:00Z"
            )
            kept = get_success_data(
                api_client.keep_trial_order(order["id"], {}, AGENT)
            )
            assert kept["fulfillment_status"] == "CLOSED"

        response = api_client.create_trial_order(
            trial_order_payload(
                customers[2]["id"], model["id"], gross_price_cents=120000
            ),
            AGENT,
        )
        validate_error(response, ApiErrorId.ERR_HOUSEHOLD_TRIAL_LIMIT)

        _rows, meta = validate_paginated(
            api_client.list_trial_orders(
                AGENT, params={"customer_id": customers[2]["id"]}
            )
        )
        assert meta["total_count"] == 0, "the refused order must not be written"

        third = read_customer(customers[2]["id"])
        assert third["status"] == "ACTIVE", (
            "hitting the household limit is not an abuse signal, got "
            f"{third['status']}"
        )
        assert third["abuse_score_rolling"] == 0

        second = read_customer(customers[1]["id"])
        assert second["abuse_score_rolling"] == 30, (
            "the second member's delivery did raise a HOUSEHOLD_MATCH signal, got "
            f"{second['abuse_score_rolling']}"
        )


class TestOneLiveReturnPerOrder:
    """A merely REQUESTED case is already live enough to block a second."""

    def test_a_second_return_on_the_same_order_is_refused(self):
        """PRD §3.6: "If any return case on the order is currently in `REQUESTED`, `PICKUP_SCHEDULED`, `PICKED_UP`, `INSPECTED` or `DISPOSITIONED`, a second request is refused with `ERR_DUPLICATE_ACTIVE_RETURN`."

        Nothing has been scheduled yet — the first case is still REQUESTED — and
        the second request carries a different reason code, but the order may only
        carry one live return, so the original case and its COMFORT reason survive
        untouched.

        Design: Corner/validations/second_open_return_on_one_order_returns_duplicate_active_return
        """
        scenario = setup_return_lifecycle(
            stage="REQUESTED",
            model_overrides={
                "sku": "MDL-Q-V7",
                "name": "Comfort Q",
                "list_price_cents": 120000,
            },
            customer_overrides={
                "email": "v7@example.com",
                "full_name": "Vin Seven",
                "household_hash": "HH-V7",
            },
        )
        order = scenario["order"]
        first_case = scenario["return_case"]

        response = api_client.create_return_case(
            return_case_payload(order["id"], "OTHER"), scenario["customer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_RETURN)

        rows, meta = validate_paginated(
            api_client.list_return_cases(AGENT, params={"order_id": order["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first_case["id"]]
        assert rows[0]["logistics_status"] == "REQUESTED"
        assert rows[0]["reason_code"] == "COMFORT", (
            f"the refused OTHER reason must not overwrite the first case's "
            f"reason, got {rows[0]['reason_code']}"
        )
        assert read_order(order["id"])["trial_status"] == "RETURN_REQUESTED"


class TestExchangeMustKeepTheBedSize:
    """A comfort exchange trades firmness only."""

    def test_a_king_target_against_a_queen_order_is_refused(self):
        """PRD §3.5: "The target model must be a genuinely different model of the same bed size: a target whose `size` differs from the original order's model, or a target that is the original's own model, is refused with `ERR_MODEL_SIZE_MISMATCH`."

        The clock sits on exactly break_in_ends_at, so the trial gates are
        satisfied and the chain is empty — the only defect is that the target is a
        KING, and the request leaves the order at TRIAL_ACTIVE with an empty chain.

        Design: Corner/validations/exchanging_a_king_target_from_a_queen_order_returns_model_size_mismatch
        """
        set_clock("2026-08-01T00:00:00Z")
        king = create_model(
            sku="MDL-K-V8",
            name="Comfort King",
            firmness="FIRM",
            size="KING",
            list_price_cents=180000,
        )
        scenario = setup_delivered_order(
            model_overrides={
                "sku": "MDL-Q-V8",
                "name": "Comfort Q",
                "firmness": "MEDIUM",
                "size": "QUEEN",
                "list_price_cents": 120000,
            },
            customer_overrides={
                "email": "v8@example.com",
                "full_name": "Vera Eight",
                "household_hash": "HH-V8",
            },
        )
        order = scenario["order"]

        set_clock("2026-08-22T00:00:00Z")
        response = api_client.create_comfort_exchange(
            comfort_exchange_payload(order["id"], king["id"]),
            scenario["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_MODEL_SIZE_MISMATCH)

        _rows, meta = validate_paginated(
            api_client.list_comfort_exchanges(
                AGENT, params={"original_order_id": order["id"]}
            )
        )
        assert meta["total_count"] == 0

        reloaded = read_order(order["id"])
        assert reloaded["trial_status"] == "TRIAL_ACTIVE", (
            "at exactly break_in_ends_at the order has already moved, got "
            f"{reloaded['trial_status']}"
        )
        assert reloaded["exchange_chain_depth"] == 0


class TestExchangeChainIsBoundedAtTwo:
    """Depth accumulates along the replacement chain, and the third link is refused."""

    def _deliver(self, order_id: str, at: str) -> dict:
        set_clock(at)
        get_success_data(api_client.dispatch_trial_order(order_id, {}, LOGISTICS))
        return get_success_data(api_client.deliver_trial_order(order_id, {}, LOGISTICS))

    def test_a_third_exchange_request_in_one_chain_is_refused(self):
        """PRD §3.5: "The exchange chain is bounded at two exchanges: `sequence_number`, defined as the original order's `exchange_chain_depth` plus one, may not exceed two, and a third attempt is refused with `ERR_EXCHANGE_LIMIT_REACHED`."

        Three equally priced QUEEN models keep the settlement arithmetic out of the
        way. The MEDIUM order is exchanged for FIRM and then for SOFT, each
        replacement being delivered and given its own 21-night break-in, so the
        third request computes sequence_number 3 and is refused even though every
        other gate passes.

        Design: Corner/validations/third_exchange_in_one_chain_returns_exchange_limit_reached
        """
        set_clock("2026-08-01T00:00:00Z")
        medium = create_model(
            sku="MDL-Q-V11-M", name="Comfort Q Medium", firmness="MEDIUM",
            size="QUEEN", list_price_cents=120000,
        )
        firm = create_model(
            sku="MDL-Q-V11-F", name="Comfort Q Firm", firmness="FIRM",
            size="QUEEN", list_price_cents=120000,
        )
        soft = create_model(
            sku="MDL-Q-V11-S", name="Comfort Q Soft", firmness="SOFT",
            size="QUEEN", list_price_cents=120000,
        )
        scenario = setup_delivered_order(
            model=medium,
            customer_overrides={
                "email": "v11@example.com",
                "full_name": "Vic Eleven",
                "household_hash": "HH-V11",
            },
        )
        customer_headers = scenario["customer_headers"]
        order_one = scenario["order"]

        set_clock("2026-08-22T00:00:00Z")
        exchange_one = request_comfort_exchange(
            order_one["id"], firm["id"], headers=customer_headers
        )
        approved_one = approve_comfort_exchange(exchange_one["id"], order_one["id"])
        order_two_id = approved_one["replacement_order_id"]
        order_two = self._deliver(order_two_id, "2026-08-22T00:00:00Z")
        assert order_two["exchange_chain_depth"] == 1

        set_clock("2026-09-12T00:00:00Z")
        exchange_two = request_comfort_exchange(
            order_two_id, soft["id"], headers=customer_headers
        )
        approved_two = approve_comfort_exchange(exchange_two["id"], order_two_id)
        order_three_id = approved_two["replacement_order_id"]
        order_three = self._deliver(order_three_id, "2026-09-12T00:00:00Z")

        set_clock("2026-10-03T00:00:00Z")
        response = api_client.create_comfort_exchange(
            comfort_exchange_payload(order_three_id, medium["id"]), customer_headers
        )
        validate_error(response, ApiErrorId.ERR_EXCHANGE_LIMIT_REACHED)

        assert approved_one["sequence_number"] == 1
        assert approved_one["status"] == "APPROVED"
        assert approved_two["sequence_number"] == 2, (
            "the second link in the chain is sequence 2, got "
            f"{approved_two['sequence_number']}"
        )
        assert approved_two["status"] == "APPROVED"

        assert order_three["exchange_chain_depth"] == 2, (
            f"depth accumulates along the chain, got "
            f"{order_three['exchange_chain_depth']}"
        )
        assert order_three["exchanged_from_order_id"] == order_two_id

        _rows, meta = validate_paginated(
            api_client.list_comfort_exchanges(
                AGENT, params={"original_order_id": order_three_id}
            )
        )
        assert meta["total_count"] == 0, "the refused request must not be written"

"""The error catalogue: one not-found code per collection, one auth code above
them all, and the five terminal-state refusals.

Every test here checks the error id the API chose, not merely that it failed, and
then proves the refused write left its target exactly where it was.
"""

from test_helpers import (
    AGENT,
    LOGISTICS,
    ApiErrorId,
    api_client,
    confirm_intake_payload,
    complete_appointment_payload,
    create_customer_row,
    create_model,
    decline_exchange_payload,
    get_success_data,
    inspect_payload,
    make_finance_controller_headers,
    make_retail_partner_headers,
    read_appointment,
    read_assignment,
    read_attribution_claim,
    read_customer,
    read_exchange,
    read_order,
    read_return_case,
    request_comfort_exchange,
    setup_delivered_order,
    setup_partner_channel_order,
    setup_return_lifecycle,
    approve_exchange_payload,
    attribution_claim_payload,
    resolve_attribution_payload,
    set_clock,
    trial_order_payload,
    validate_error,
    validate_paginated,
)

RESOLVER_X8 = make_finance_controller_headers("fin-x8")


class TestEveryCollectionHasItsOwnNotFoundCode:
    """Nine unknown ids, nine distinct error ids, no generic fallback."""

    def test_nine_unknown_entity_reads_answer_nine_different_error_ids(self):
        """PRD §2.8: "4. Path-identifier resolution, checked left to right along the URL, answering the not-found code of whichever segment failed first."

        On an empty system every read below is well-formed and authenticated, so
        the only thing left to distinguish the nine responses is which collection
        the identifier belonged to.

        Design: Corner/errors/every_single_entity_read_answers_its_own_not_found_error_id
        """
        cases = [
            (api_client.get_customer, "c1", AGENT, ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
            (api_client.get_return_case, "c2", AGENT, ApiErrorId.ERR_RETURN_CASE_NOT_FOUND),
            (api_client.get_pickup_route, "c3", LOGISTICS, ApiErrorId.ERR_ROUTE_NOT_FOUND),
            (
                api_client.get_pickup_appointment,
                "c4",
                LOGISTICS,
                ApiErrorId.ERR_APPOINTMENT_NOT_FOUND,
            ),
            (
                api_client.get_disposition_assignment,
                "c5",
                LOGISTICS,
                ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
            ),
            (api_client.get_quality_claim, "c6", AGENT, ApiErrorId.ERR_CLAIM_NOT_FOUND),
            (api_client.get_comfort_exchange, "c7", AGENT, ApiErrorId.ERR_EXCHANGE_NOT_FOUND),
            (
                api_client.get_refund_authorization,
                "c8",
                make_finance_controller_headers("fin-x9"),
                ApiErrorId.ERR_REFUND_NOT_FOUND,
            ),
            (
                api_client.get_attribution_claim,
                "c9",
                make_finance_controller_headers("fin-x9"),
                ApiErrorId.ERR_ATTRIBUTION_CLAIM_NOT_FOUND,
            ),
        ]

        seen = []
        for read, suffix, headers, expected in cases:
            response = read(f"00000000-0000-0000-0000-0000000000{suffix}", headers)
            # validate_error also asserts the error envelope shape and the 404 the
            # PRD's status table pairs with each of these ids.
            seen.append(validate_error(response, expected)["error_id"])

        assert len(set(seen)) == 9, (
            f"each collection must answer its own not-found code, got {seen}"
        )

    def test_an_unresolvable_partner_reference_in_the_body_is_a_partner_not_found(self):
        """PRD §2.8: "5. Foreign-key resolution for identifiers supplied in the request body, checked in the order the endpoint declares its input fields, answering the corresponding not-found code."

        The customer and the model both resolve; only the retail-partner reference
        dangles, and it has its own code rather than sharing the catalogue's.

        Design: Corner/errors/an_unknown_retail_partner_id_in_the_body_returns_partner_not_found
        """
        set_clock("2026-08-01T00:00:00Z")
        model = create_model(sku="MDL-Q-F1", name="Comfort Q", list_price_cents=120000)
        customer = create_customer_row(
            email="f1@example.com", full_name="Fay One", household_hash="HH-F1"
        )

        response = api_client.create_trial_order(
            trial_order_payload(
                customer["id"],
                model["id"],
                channel="RETAIL_PARTNER",
                gross_price_cents=120000,
                retail_partner_id="00000000-0000-0000-0000-0000000000f1",
            ),
            AGENT,
        )
        validate_error(response, ApiErrorId.ERR_PARTNER_NOT_FOUND)

        _rows, meta = validate_paginated(
            api_client.list_trial_orders(AGENT, params={"customer_id": customer["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_request_without_identity_headers_is_unauthenticated(self):
        """PRD §2.8: "1. Header presence and role recognition — `ERR_UNAUTHENTICATED`."

        The path identifier does not exist either, so the only thing that decides
        between 401 and 404 is the precedence order: authentication is checked
        first and the read never gets far enough to miss.

        Design: Corner/errors/a_request_without_auth_headers_returns_unauthenticated
        """
        response = api_client.get_customer(
            "00000000-0000-0000-0000-0000000000d1", {}
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


class TestTerminalAndPrematureStatesAreRefused:
    """Five state guards, each with its own error id and no partial write."""

    def test_inspecting_a_case_before_pickup_is_refused(self):
        """PRD §3.6: "Inspecting a case before pickup, dispositioning one before inspection, cancelling one after collection, or authorizing a refund on a cancelled case are all refused with `ERR_INVALID_RETURN_STATE`."

        Grading requires the unit in hand, and this case was never even scheduled,
        so no grade, no offsets and no provisional refund are stamped.

        Design: Corner/errors/inspecting_a_return_case_before_pickup_returns_invalid_return_state
        """
        scenario = setup_return_lifecycle(
            stage="REQUESTED",
            model_overrides={
                "sku": "MDL-Q-F4", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "f4@example.com",
                "full_name": "Fay Four",
                "household_hash": "HH-F4",
            },
        )
        return_case = scenario["return_case"]

        response = api_client.inspect_return_case(
            return_case["id"], inspect_payload("A", False, False), LOGISTICS
        )
        validate_error(response, ApiErrorId.ERR_INVALID_RETURN_STATE)

        reloaded = read_return_case(return_case["id"])
        assert reloaded["logistics_status"] == "REQUESTED"
        assert reloaded["condition_grade"] is None
        assert reloaded["provisional_refund_cents"] is None
        assert reloaded["version"] == return_case["version"]

    def test_completing_an_appointment_twice_is_refused(self):
        """PRD §3.7: "Appointments can be read individually or listed with filters on `route_id`, `return_case_id` and `status`; an unknown appointment identifier answers `ERR_APPOINTMENT_NOT_FOUND`, and completing or cancelling an appointment that is not `BOOKED` answers `ERR_INVALID_APPOINTMENT_STATE`."

        COMPLETED is terminal, so the four-hop collection cascade cannot be
        replayed: the case keeps its single 45-night pricing basis and the
        customer's completed-return counter stays at one.

        Design: Corner/errors/completing_an_appointment_twice_returns_invalid_appointment_state
        """
        scenario = setup_return_lifecycle(
            stage="PICKED_UP",
            model_overrides={
                "sku": "MDL-Q-F5", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "f5@example.com",
                "full_name": "Fay Five",
                "household_hash": "HH-F5",
            },
        )
        appointment = scenario["appointment"]

        response = api_client.complete_pickup_appointment(
            appointment["id"], complete_appointment_payload("COMPLETED"), LOGISTICS
        )
        validate_error(response, ApiErrorId.ERR_INVALID_APPOINTMENT_STATE)

        reloaded = read_appointment(appointment["id"])
        assert reloaded["status"] == "COMPLETED"
        assert reloaded["version"] == appointment["version"]

        return_case = read_return_case(scenario["return_case"]["id"])
        assert return_case["logistics_status"] == "PICKED_UP"
        assert return_case["nights_used"] == 45

        customer = read_customer(scenario["customer"]["id"])
        assert customer["completed_return_count"] == 1, (
            "the cascade must not run twice, got "
            f"{customer['completed_return_count']}"
        )

    def test_confirming_intake_twice_is_refused(self):
        """PRD §3.8: "Confirming intake twice, or confirming intake on an assignment that is not `ASSIGNED`, answers `ERR_INVALID_ASSIGNMENT_STATE`."

        DELIVERED is terminal for the assignment, so the second call — which asks
        for the REJECTED branch — cannot re-open the case or give the partner's day
        bucket its units back.

        Design: Corner/errors/confirming_intake_twice_returns_invalid_assignment_state
        """
        scenario = setup_return_lifecycle(
            stage="INTAKE_CONFIRMED",
            model_overrides={
                "sku": "MDL-Q-F6",
                "name": "Comfort Q",
                "list_price_cents": 120000,
                "donation_eligible": True,
            },
            customer_overrides={
                "email": "f6@example.com",
                "full_name": "Fay Six",
                "household_hash": "HH-F6",
            },
        )
        assignment = scenario["assignment"]

        response = api_client.confirm_intake(
            assignment["id"], confirm_intake_payload("REJECTED"), LOGISTICS
        )
        validate_error(response, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE)

        reloaded = read_assignment(assignment["id"])
        assert reloaded["status"] == "DELIVERED"
        assert reloaded["version"] == assignment["version"]

        return_case = read_return_case(scenario["return_case"]["id"])
        assert return_case["logistics_status"] == "DISPOSITIONED", (
            "the rejection path never ran, got "
            f"{return_case['logistics_status']}"
        )

    def test_approving_a_declined_exchange_is_refused(self):
        """PRD §3.5: "Approval further requires that the exchange still be `REQUESTED` — approving or declining an already-decided exchange answers `ERR_INVALID_EXCHANGE_STATE` — that the original order's `fulfillment_status` be either `DELIVERED` or `DAMAGED_REPORTED`, that its `trial_status` be exactly `TRIAL_ACTIVE`, and that the owning customer's posture not be `BLOCKED`."

        The approval carries the order's genuinely current version, so the only
        possible refusal is the terminal status of the exchange itself; nothing is
        minted and the original order is untouched.

        Design: Corner/errors/approving_a_declined_exchange_returns_invalid_exchange_state
        """
        set_clock("2026-08-01T00:00:00Z")
        firm = create_model(
            sku="MDL-Q-F7-F", name="Comfort Q Firm", firmness="FIRM",
            size="QUEEN", list_price_cents=120000,
        )
        scenario = setup_delivered_order(
            model_overrides={
                "sku": "MDL-Q-F7-M",
                "name": "Comfort Q Medium",
                "firmness": "MEDIUM",
                "size": "QUEEN",
                "list_price_cents": 120000,
            },
            customer_overrides={
                "email": "f7@example.com",
                "full_name": "Fay Seven",
                "household_hash": "HH-F7",
            },
        )
        order = scenario["order"]

        set_clock("2026-08-22T00:00:00Z")
        exchange = request_comfort_exchange(
            order["id"], firm["id"], headers=scenario["customer_headers"]
        )
        declined = get_success_data(
            api_client.decline_comfort_exchange(
                exchange["id"],
                decline_exchange_payload("the requested firmness is out of stock"),
                AGENT,
            )
        )
        assert declined["status"] == "DECLINED"

        response = api_client.approve_comfort_exchange(
            exchange["id"], approve_exchange_payload(order["version"]), AGENT
        )
        validate_error(response, ApiErrorId.ERR_INVALID_EXCHANGE_STATE)

        reloaded_exchange = read_exchange(exchange["id"])
        assert reloaded_exchange["status"] == "DECLINED"
        assert reloaded_exchange["replacement_order_id"] is None

        reloaded_order = read_order(order["id"])
        assert reloaded_order["trial_status"] == "TRIAL_ACTIVE"
        assert reloaded_order["fulfillment_status"] == "DELIVERED"
        assert reloaded_order["exchange_chain_depth"] == 0
        assert reloaded_order["version"] == order["version"], (
            "declining leaves the order untouched, so its version must not move"
        )

        _rows, meta = validate_paginated(
            api_client.list_trial_orders(
                AGENT, params={"exchanged_from_order_id": order["id"]}
            )
        )
        assert meta["total_count"] == 0, "no replacement order may have been minted"

    def test_resolving_an_attribution_claim_before_review_is_refused(self):
        """PRD §3.10: "Resolving a claim that is not `UNDER_REVIEW`, or resubmitting one that is not `REVISION_REQUESTED`, is refused with `ERR_INVALID_ATTRIBUTION_STATE`; the loop `SUBMITTED → UNDER_REVIEW → REVISION_REQUESTED → SUBMITTED` is the only cycle in this workflow."

        The claim was never accepted for review, so resolution has no state to move
        from: the window and evidence rules both pass, yet nothing is priced and
        resolved_at stays null.

        Design: Corner/errors/resolving_an_attribution_claim_before_review_returns_invalid_attribution_state
        """
        scenario = setup_partner_channel_order(
            partner_overrides={
                "name": "Sleep Gallery F8",
                "region_code": "CA",
                "commission_bps": 800,
            },
            model_overrides={
                "sku": "MDL-Q-F8", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "f8@example.com",
                "full_name": "Fay Eight",
                "household_hash": "HH-F8",
            },
        )
        partner = scenario["partner"]

        set_clock("2026-08-10T00:00:00Z")
        claim = get_success_data(
            api_client.create_attribution_claim(
                attribution_claim_payload(
                    partner["id"], scenario["order"]["id"], "SALES_ATTRIBUTION", 2
                ),
                make_retail_partner_headers(partner["id"]),
            ),
            expected_status=201,
        )

        response = api_client.resolve_attribution_claim(
            claim["id"], resolve_attribution_payload("APPROVE"), RESOLVER_X8
        )
        validate_error(response, ApiErrorId.ERR_INVALID_ATTRIBUTION_STATE)

        reloaded = read_attribution_claim(claim["id"])
        assert reloaded["status"] == "SUBMITTED"
        assert reloaded["commission_cents"] == 0
        assert reloaded["resolved_at"] is None
        assert reloaded["version"] == claim["version"]

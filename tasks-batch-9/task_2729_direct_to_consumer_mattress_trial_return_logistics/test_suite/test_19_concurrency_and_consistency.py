"""Optimistic concurrency on the three parent ledgers, plus the version counter
itself, the deterministic partner selector, and synchronous read-your-writes.

Each concurrency test performs the losing write first and proves it consumed
nothing, then re-reads the parent and performs the identical write successfully —
so a implementation that ignores the expected-version field fails the first half
and one that never lets a fresh version through fails the second.
"""

from test_helpers import (
    ADMIN,
    AGENT,
    LOGISTICS,
    ApiErrorId,
    api_client,
    approve_exchange_payload,
    assert_instant,
    book_appointment,
    complete_appointment,
    confirm_assignment_intake,
    create_charity,
    create_customer_row,
    create_model,
    create_recycler,
    disposition_return,
    inspect_return,
    make_customer_headers,
    make_finance_controller_headers,
    open_return_case,
    pickup_appointment_payload,
    pickup_route_payload,
    read_appointment,
    read_assignment,
    read_exchange,
    read_order,
    read_refund_summary,
    read_return_case,
    read_route,
    refund_authorization_payload,
    request_comfort_exchange,
    set_clock,
    setup_delivered_order,
    setup_published_route,
    setup_return_lifecycle,
    trial_order_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBookingCarriesTheRoutesExpectedVersion:
    """The losing booking is legal on every axis except its view of capacity."""

    def test_a_stale_route_version_is_refused_and_the_re_read_booking_succeeds(self):
        """PRD §2.7: "Booking a second appointment for a different return case in a non-overlapping slot is perfectly legitimate product behaviour, so the write cannot be refused on state grounds; a stale version is the only signal that the client's view of `booked_units` and `available_units` predates another booking that has already consumed capacity."

        Two QUEEN pickups are 2 units each on a 6-unit route, so there is room
        for both; holding the version from publish time is the only thing wrong
        with the second booking, and after re-reading the route the identical
        slot is accepted.

        Design: Corner/cross_cutting_layers/booking_with_a_stale_route_version_is_rejected_then_succeeds_on_the_fresh_one
        """
        model = create_model(sku="MDL-Q-C1", name="Comfort Q", list_price_cents=120000)
        scenario_a = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "c1a@example.com",
                "full_name": "Cy A",
                "household_hash": "HH-C1A",
            },
        )
        scenario_b = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "c1b@example.com",
                "full_name": "Cy B",
                "household_hash": "HH-C1B",
            },
        )

        set_clock("2026-09-10T00:00:00Z")
        case_a = open_return_case(scenario_a["order"]["id"], scenario_a["customer_headers"])
        case_b = open_return_case(scenario_b["order"]["id"], scenario_b["customer_headers"])

        route = setup_published_route(capacity_units=6)
        route_v1 = route["version"]
        appointment_a = book_appointment(
            route["id"],
            case_a["id"],
            slot_start_at="2026-09-15T09:00:00Z",
            slot_end_at="2026-09-15T11:00:00Z",
            expected_version=route_v1,
        )

        stale_body = pickup_appointment_payload(
            route["id"],
            case_b["id"],
            route_v1,
            slot_start_at="2026-09-15T12:00:00Z",
            slot_end_at="2026-09-15T13:00:00Z",
        )
        refused = api_client.create_pickup_appointment(stale_body, LOGISTICS)
        validate_error(refused, ApiErrorId.ERR_STALE_ROUTE_VERSION)

        after_refusal = read_route(route["id"])
        assert after_refusal["booked_units"] == 2, (
            "the rejected booking must consume no capacity, got "
            f"{after_refusal['booked_units']} units booked"
        )
        assert after_refusal["available_units"] == 4
        _rows, meta = validate_paginated(
            api_client.list_pickup_appointments(LOGISTICS, params={"route_id": route["id"]})
        )
        assert meta["total_count"] == 1

        route_v2 = after_refusal["version"]
        assert route_v2 == route_v1 + 1, (
            "only the successful booking bumped the route, so its version moved "
            f"once; expected {route_v1 + 1}, got {route_v2}"
        )

        fresh_body = pickup_appointment_payload(
            route["id"],
            case_b["id"],
            route_v2,
            slot_start_at="2026-09-15T12:00:00Z",
            slot_end_at="2026-09-15T13:00:00Z",
        )
        appointment_b = validate_success(
            api_client.create_pickup_appointment(fresh_body, LOGISTICS), 201
        )

        final_route = read_route(route["id"])
        assert final_route["booked_units"] == 4
        assert final_route["available_units"] == 2
        assert final_route["version"] == route_v2 + 1
        assert read_appointment(appointment_a["id"])["status"] == "BOOKED"
        assert read_appointment(appointment_b["id"])["status"] == "BOOKED"


class TestRefundAuthorizationCarriesTheCasesExpectedVersion:
    """The version held from case creation predates everything the refund prices."""

    def test_a_stale_return_case_version_is_refused_and_the_re_read_authorization_succeeds(self):
        """PRD §2.7: "Because a voided authorization may legitimately be superseded by a fresh one, a second create is not blocked by state either; a stale version is the only signal that the inspection grade, bundle unwind, or damage offset the client priced against has since been re-stamped."

        Collection, inspection and disposition each bumped the case after the
        client captured its version at creation, so the create is refused with no
        ledger row written; the freshly read version authorizes 114000 cents
        against the 500-basis-point band for 45 nights.

        Design: Corner/cross_cutting_layers/authorizing_a_refund_on_a_stale_return_case_version_is_rejected
        """
        controller = make_finance_controller_headers("fin-c2-1")
        create_charity(name="Charity C2", region_code="CA")
        scenario = setup_delivered_order(
            model_overrides={
                "sku": "MDL-Q-C2",
                "name": "Comfort Q",
                "list_price_cents": 120000,
                "donation_eligible": True,
            },
            customer_overrides={
                "email": "c2@example.com",
                "full_name": "Cal Two",
                "household_hash": "HH-C2",
            },
        )
        case = open_return_case(
            scenario["order"]["id"],
            scenario["customer_headers"],
            requested_at="2026-09-10T00:00:00Z",
        )
        case_v1 = case["version"]

        route = setup_published_route(capacity_units=6)
        appointment = book_appointment(route["id"], case["id"])
        complete_appointment(appointment["id"], "COMPLETED", at="2026-09-15T00:00:00Z")
        inspect_return(case["id"], "A", False, False)
        assignment = disposition_return(case["id"], "DONATION", "2026-09-16")
        confirm_assignment_intake(assignment["id"], "DELIVERED")

        refused = api_client.create_refund_authorization(
            refund_authorization_payload(case["id"], case_v1), controller
        )
        validate_error(refused, ApiErrorId.ERR_STALE_RETURN_CASE_VERSION)

        after_refusal = read_return_case(case["id"])
        assert after_refusal["financial_status"] == "PENDING"
        assert after_refusal["final_refund_cents"] is None
        _rows, meta = validate_paginated(
            api_client.list_refund_authorizations(
                controller, params={"return_case_id": case["id"]}
            )
        )
        assert meta["total_count"] == 0

        case_v2 = after_refusal["version"]
        assert case_v2 > case_v1, (
            "pickup, inspection and disposition each bumped the case, so the "
            f"current version must exceed {case_v1}, got {case_v2}"
        )

        refund = validate_success(
            api_client.create_refund_authorization(
                refund_authorization_payload(case["id"], case_v2), controller
            ),
            201,
        )
        assert refund["net_refund_cents"] == 114000
        assert refund["proration_deduction_cents"] == 6000

        authorized = read_return_case(case["id"])
        assert authorized["financial_status"] == "AUTHORIZED"
        assert authorized["final_refund_cents"] == 114000
        assert authorized["version"] == case_v2 + 1


class TestExchangeApprovalCarriesTheOrdersExpectedVersion:
    """The OCC parent here is the order the approval will retire."""

    def test_a_stale_order_version_is_refused_and_the_re_read_approval_mints_the_replacement(self):
        """PRD §2.7: "Approving a comfort exchange — `POST /comfort-exchanges/{id}/approve` — requires `expected_trial_order_version` and it must equal the original `TrialOrder`'s current `version`."

        The version observed at order creation is two writes behind once dispatch
        and delivery have each bumped it, so the approval is refused and mints
        nothing; the current version approves the exchange and creates the
        replacement at chain depth 1.

        Design: Corner/cross_cutting_layers/approving_an_exchange_on_a_stale_order_version_is_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        medium = create_model(
            sku="MDL-Q-C3M", name="Comfort Q Medium", firmness="MEDIUM",
            size="QUEEN", list_price_cents=120000,
        )
        firm = create_model(
            sku="MDL-Q-C3F", name="Comfort Q Firm", firmness="FIRM",
            size="QUEEN", list_price_cents=120000,
        )
        customer = create_customer_row(
            email="c3@example.com", full_name="Cleo Three", household_hash="HH-C3"
        )

        order = validate_success(
            api_client.create_trial_order(
                trial_order_payload(
                    customer["id"], medium["id"], gross_price_cents=120000
                ),
                AGENT,
            ),
            201,
        )
        order_v0 = order["version"]
        validate_success(api_client.dispatch_trial_order(order["id"], {}, LOGISTICS), 200)
        validate_success(api_client.deliver_trial_order(order["id"], {}, LOGISTICS), 200)

        set_clock("2026-08-22T00:00:00Z")
        exchange = request_comfort_exchange(
            order["id"], firm["id"], headers=make_customer_headers(customer["id"])
        )

        refused = api_client.approve_comfort_exchange(
            exchange["id"], approve_exchange_payload(order_v0), AGENT
        )
        validate_error(refused, ApiErrorId.ERR_STALE_ORDER_VERSION)

        held = read_exchange(exchange["id"])
        assert held["status"] == "REQUESTED"
        assert held["replacement_order_id"] is None
        assert read_order(order["id"])["exchange_chain_depth"] == 0

        order_v1 = read_order(order["id"])["version"]
        assert order_v1 == order_v0 + 2, (
            "dispatch and deliver each bumped the order exactly once, so the "
            f"current version must be {order_v0 + 2}, got {order_v1}"
        )

        approved = validate_success(
            api_client.approve_comfort_exchange(
                exchange["id"], approve_exchange_payload(order_v1), AGENT
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        replacement_id = approved["replacement_order_id"]
        assert replacement_id is not None

        original = read_order(order["id"])
        assert original["fulfillment_status"] == "REPLACED"
        assert original["trial_status"] == "EXCHANGED"

        replacement = read_order(replacement_id)
        assert replacement["exchanged_from_order_id"] == order["id"]
        assert replacement["exchange_chain_depth"] == 1


class TestTheVersionCounterMovesOnlyOnWrites:
    """Create, publish and book on one route; three GETs in between."""

    def test_three_writes_produce_three_versions_and_the_reads_produce_none(self):
        """PRD §2.4: "Most resources additionally carry `updated_at`, using the same timestamp format, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that resource."

        The route opens at version 1, publish takes it to 2 and the booking to 3,
        while each interleaved read — including one by a different role — returns
        the counter untouched; the booking bumps the route once, not once per
        side effect, and the appointment keeps a counter of its own.

        Design: Corner/cross_cutting_layers/every_write_bumps_the_version_and_reads_never_do
        """
        scenario = setup_delivered_order(
            model_overrides={
                "sku": "MDL-Q-C4", "name": "Comfort Q", "list_price_cents": 120000
            },
            customer_overrides={
                "email": "c4@example.com",
                "full_name": "Cam Four",
                "household_hash": "HH-C4",
            },
        )
        case = open_return_case(
            scenario["order"]["id"],
            scenario["customer_headers"],
            requested_at="2026-09-10T00:00:00Z",
        )

        created = validate_success(
            api_client.create_pickup_route(
                pickup_route_payload(capacity_units=6), LOGISTICS
            ),
            201,
        )
        version_at_create = created["version"]

        assert read_route(created["id"])["version"] == version_at_create, (
            "a GET is not a mutation, so it must not move the counter"
        )

        published = validate_success(
            api_client.publish_pickup_route(created["id"], {}, LOGISTICS), 200
        )
        version_at_publish = published["version"]
        assert version_at_publish == version_at_create + 1

        assert read_route(created["id"], ADMIN)["version"] == version_at_publish, (
            "reading as a different role is still only a read"
        )

        appointment = book_appointment(
            created["id"], case["id"], expected_version=version_at_publish
        )

        after_booking = read_route(created["id"])
        assert after_booking["version"] == version_at_publish + 1, (
            "the booking bumps the route exactly once, not once per side effect; "
            f"expected {version_at_publish + 1}, got {after_booking['version']}"
        )
        assert after_booking["status"] == "PUBLISHED"
        assert after_booking["booked_units"] == 2
        assert after_booking["available_units"] == 4

        assert read_appointment(appointment["id"])["version"] == appointment["version"], (
            "the appointment carries its own counter, untouched by the route's"
        )


class TestThePartnerSelectorIsDeterministic:
    """Two recyclers identical on every ranking key force the documented tie-break."""

    def test_the_first_assignment_breaks_the_tie_on_created_at_and_the_second_on_headroom(self):
        """PRD §3.8: "When a type yields at least one eligible partner, the winner is chosen deterministically: lowest `priority_rank` first; among equal ranks, the partner with the greatest remaining intake headroom for that date — its `daily_intake_capacity_units` less its already-booked units — wins; and if that is still tied, the partner with the earliest `created_at` wins."

        Both recyclers are rank 1 with 6 free units, so the first QUEEN unit goes
        to the earlier-created one at 2 * 4000 = 8000 cents; that leaves it 4 units
        of headroom against the other's 6, so the second unit flips partners and
        books 2 * 5000 = 10000 cents.

        Design: Corner/cross_cutting_layers/the_disposition_selector_is_deterministic_across_two_identical_partners
        """
        model = create_model(sku="MDL-Q-C5", name="Comfort Q", list_price_cents=120000)
        recycler_one = create_recycler(
            name="Recycler C5-R1",
            region_code="CA",
            daily_intake_capacity_units=6,
            priority_rank=1,
            recycle_fee_cents_per_unit=4000,
        )
        recycler_two = create_recycler(
            name="Recycler C5-R2",
            region_code="CA",
            daily_intake_capacity_units=6,
            priority_rank=1,
            recycle_fee_cents_per_unit=5000,
        )

        scenario_a = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "c5a@example.com",
                "full_name": "Coe A",
                "household_hash": "HH-C5A",
            },
        )
        scenario_b = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "c5b@example.com",
                "full_name": "Coe B",
                "household_hash": "HH-C5B",
            },
        )

        set_clock("2026-09-10T00:00:00Z")
        case_a = open_return_case(scenario_a["order"]["id"], scenario_a["customer_headers"])
        case_b = open_return_case(scenario_b["order"]["id"], scenario_b["customer_headers"])

        route = setup_published_route(capacity_units=6)
        appointment_a = book_appointment(
            route["id"], case_a["id"],
            slot_start_at="2026-09-15T09:00:00Z", slot_end_at="2026-09-15T11:00:00Z",
        )
        appointment_b = book_appointment(
            route["id"], case_b["id"],
            slot_start_at="2026-09-15T12:00:00Z", slot_end_at="2026-09-15T13:00:00Z",
        )

        set_clock("2026-09-15T00:00:00Z")
        complete_appointment(appointment_a["id"], "COMPLETED")
        complete_appointment(appointment_b["id"], "COMPLETED")
        inspect_return(case_a["id"], "A", False, False)
        inspect_return(case_b["id"], "A", False, False)

        assignment_a = disposition_return(case_a["id"], "RECYCLE", "2026-09-16")
        assignment_b = disposition_return(case_b["id"], "RECYCLE", "2026-09-16")

        assert assignment_a["partner_id"] == recycler_one["id"], (
            "with priority_rank and headroom tied the earliest created_at wins, "
            "so the first assignment belongs to Recycler C5-R1"
        )
        assert assignment_a["units"] == 2
        assert assignment_a["fee_cents"] == 8000, (
            f"2 units at 4000 cents each is 8000, got {assignment_a['fee_cents']}"
        )

        assert assignment_b["partner_id"] == recycler_two["id"], (
            "6 free units beat 4, so headroom decides before created_at is "
            "consulted and the second assignment flips partners"
        )
        assert assignment_b["units"] == 2
        assert assignment_b["fee_cents"] == 10000, (
            f"2 units at 5000 cents each is 10000, got {assignment_b['fee_cents']}"
        )

        for assignment in (read_assignment(assignment_a["id"]),
                          read_assignment(assignment_b["id"])):
            assert assignment["disposition_type"] == "RECYCLE"
            assert assignment["fallback_applied"] is False
            assert assignment["intake_date"] == "2026-09-16"
            assert assignment["status"] == "ASSIGNED"


class TestAReleasedRefundIsVisibleImmediatelyEverywhere:
    """No settling delay, no retry loop: the next read is already correct."""

    def test_the_release_response_and_every_downstream_reader_agree_at_once(self):
        """PRD §3.9: "Release advances the row `AUTHORIZED → RELEASED`, records `released_by_user_id` and stamps `released_at` from the logical clock, and then rewrites the order's ledger so the four-way identity of section 2.9 still holds: `net_refund_cents` is added to `refunded_total_cents`, `outstanding_refundable_cents` is set to zero, and `retained_amount_cents` is set to `paid_amount_cents` less `refunded_total_cents`."

        The release response itself already carries the released state at the
        2026-09-15 clock, and on the very next reads the order ledger reads
        114000 / 0 / 6000, the status-filtered case index finds the case, and the
        summary reports the FINAL variant — the 106500-cent provisional figure
        and the 7500-cent delta survive because they describe the two formulas,
        not which one was stamped.

        Design: Corner/consistency_model/a_released_refund_is_visible_everywhere_within_the_same_request
        """
        authorizer = make_finance_controller_headers("fin-y1-1")
        releaser = make_finance_controller_headers("fin-y1-2")
        scenario = setup_return_lifecycle(
            stage="AUTHORIZED",
            model_overrides={
                "sku": "MDL-Q-Y1",
                "name": "Comfort Q",
                "list_price_cents": 120000,
                "donation_eligible": True,
            },
            customer_overrides={
                "email": "y1@example.com",
                "full_name": "Yan One",
                "household_hash": "HH-Y1",
            },
            authorizer_headers=authorizer,
        )
        case_id = scenario["return_case"]["id"]

        released = validate_success(
            api_client.release_refund(scenario["refund"]["id"], {}, releaser), 200
        )
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "fin-y1-2"
        assert released["net_refund_cents"] == 114000
        assert_instant(released["released_at"], "2026-09-15T00:00:00Z", "released_at")

        order = read_order(scenario["order"]["id"])
        assert order["refunded_total_cents"] == 114000
        assert order["outstanding_refundable_cents"] == 0
        assert order["retained_amount_cents"] == 6000

        rows, meta = validate_paginated(
            api_client.list_return_cases(releaser, params={"financial_status": "RELEASED"})
        )
        assert meta["total_count"] == 1, (
            "the filtered index must reflect the write synchronously, got "
            f"{meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [case_id]

        summary = read_refund_summary(case_id, releaser)
        assert summary["variant_in_effect"] == "FINAL"
        assert summary["final_refund_cents"] == 114000
        assert summary["provisional_refund_cents"] == 106500
        assert abs(summary["variant_delta_cents"]) == 7500

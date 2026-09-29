"""Writes whose admissibility depends on the state of a different entity.

In both rules the request payload is legal in isolation and the same payload
succeeds untouched once the other entity has advanced.
"""

from test_helpers import (
    ApiErrorId,
    LOGISTICS,
    api_client,
    assert_route_capacity_identity,
    confirm_assignment_intake,
    create_model,
    get_success_data,
    make_finance_controller_headers,
    open_return_case,
    pickup_appointment_payload,
    pickup_route_payload,
    read_return_case,
    read_route,
    refund_authorization_payload,
    setup_delivered_order,
    setup_return_lifecycle,
    validate_error,
)

AUTHORIZER_3 = make_finance_controller_headers("fin-authorizer-3")


class TestAppointmentBookingIsGatedOnRoutePublication:
    """A slot booked against a route that is still a draft, then against the same route published."""

    def _draft_route_scenario(self):
        model = create_model(sku="MDL-Q-MED-X1", firmness="MEDIUM", size="QUEEN")
        scenario = setup_delivered_order(
            model=model,
            customer_overrides={
                "email": "xe1@example.com",
                "full_name": "Xavier Route",
                "household_hash": "HH-XE1",
            },
        )
        scenario["return_case"] = open_return_case(
            scenario["order"]["id"],
            scenario["customer_headers"],
            requested_at="2026-09-10T00:00:00Z",
        )
        scenario["route"] = get_success_data(
            api_client.create_pickup_route(
                pickup_route_payload(capacity_units=6), LOGISTICS
            ),
            expected_status=201,
        )
        return scenario

    def test_booking_against_a_draft_route_is_refused_and_changes_nothing(self):
        """PRD §3.7: "Appointments may only be booked on a `PUBLISHED` route; booking against a route still in `DRAFT` is refused with `ERR_ROUTE_NOT_PUBLISHED`."

        The payload carries the draft route's own current version, so the
        optimistic-concurrency check would pass; the refusal comes purely from
        the route's publication state, and the route's ledger, version and the
        return case are all left alone.

        Design: Difficulty/cross_entity_state_dependency/appointment_booking_gated_on_pickup_route_publication_state
        """
        scenario = self._draft_route_scenario()
        route = scenario["route"]

        response = api_client.create_pickup_appointment(
            pickup_appointment_payload(
                route["id"],
                scenario["return_case"]["id"],
                route["version"],
                slot_start_at="2026-09-15T09:00:00Z",
                slot_end_at="2026-09-15T11:00:00Z",
            ),
            LOGISTICS,
        )
        validate_error(response, ApiErrorId.ERR_ROUTE_NOT_PUBLISHED)

        reloaded = read_route(route["id"])
        assert reloaded["status"] == "DRAFT"
        assert reloaded["booked_units"] == 0
        assert reloaded["available_units"] == 6
        assert reloaded["version"] == route["version"]
        assert (
            read_return_case(scenario["return_case"]["id"])["logistics_status"]
            == "REQUESTED"
        )

    def test_publishing_the_route_admits_the_identical_booking(self):
        """PRD §3.7: "A successful booking creates the appointment at `status` `BOOKED` with `closed_at` null, adds its `units` to the route's `booked_units` while re-deriving `available_units`, moves the return case `REQUESTED → PICKUP_SCHEDULED`, and bumps both the route's and the return case's `version`."

        Publication bumps the route's version, so the retry carries the fresh
        version with the same slot bounds and now consumes two of the six units.

        Design: Difficulty/cross_entity_state_dependency/appointment_booking_gated_on_pickup_route_publication_state
        """
        scenario = self._draft_route_scenario()
        route = scenario["route"]

        api_client.create_pickup_appointment(
            pickup_appointment_payload(
                route["id"],
                scenario["return_case"]["id"],
                route["version"],
                slot_start_at="2026-09-15T09:00:00Z",
                slot_end_at="2026-09-15T11:00:00Z",
            ),
            LOGISTICS,
        )
        published = get_success_data(
            api_client.publish_pickup_route(route["id"], {}, LOGISTICS)
        )
        appointment = get_success_data(
            api_client.create_pickup_appointment(
                pickup_appointment_payload(
                    route["id"],
                    scenario["return_case"]["id"],
                    published["version"],
                    slot_start_at="2026-09-15T09:00:00Z",
                    slot_end_at="2026-09-15T11:00:00Z",
                ),
                LOGISTICS,
            ),
            expected_status=201,
        )

        assert appointment["status"] == "BOOKED"
        assert appointment["units"] == 2
        reloaded = read_route(route["id"])
        assert reloaded["booked_units"] == 2
        assert reloaded["available_units"] == 4
        assert_route_capacity_identity(reloaded)
        assert (
            read_return_case(scenario["return_case"]["id"])["logistics_status"]
            == "PICKUP_SCHEDULED"
        )


class TestRefundAuthorizationIsGatedOnIntakeConfirmation:
    """A refund priced against a case whose charity has not yet accepted the unit."""

    def _dispositioned_case(self):
        return setup_return_lifecycle(
            stage="DISPOSITIONED",
            model_overrides={"sku": "MDL-Q-MED-X2", "donation_eligible": True},
            customer_overrides={
                "email": "xe2@example.com",
                "full_name": "Xena Intake",
                "household_hash": "HH-XE2",
            },
        )

    def test_authorizing_before_the_partner_accepts_the_unit_is_refused(self):
        """PRD §3.9: "The assignment created for that case must have reached `status` `DELIVERED`; authorizing before the charity or recycler has physically accepted the unit is refused with `ERR_DISPOSITION_NOT_CONFIRMED`."

        The case is already DISPOSITIONED and the expected version is current, so
        only the assignment's ASSIGNED status stands in the way; the money axis
        stays PENDING and the case's version does not move.

        Design: Difficulty/cross_entity_state_dependency/refund_authorization_gated_on_disposition_assignment_intake_confirmation
        """
        scenario = self._dispositioned_case()
        case = scenario["return_case"]

        response = api_client.create_refund_authorization(
            refund_authorization_payload(case["id"], case["version"]), AUTHORIZER_3
        )
        validate_error(response, ApiErrorId.ERR_DISPOSITION_NOT_CONFIRMED)

        reloaded = read_return_case(case["id"])
        assert reloaded["financial_status"] == "PENDING"
        assert reloaded["version"] == case["version"]

    def test_confirming_intake_unlocks_the_identical_authorization(self):
        """PRD §3.8: "An `outcome` of `DELIVERED` advances the assignment `ASSIGNED → DELIVERED`, and the partner's `intake_date` bucket keeps those units permanently; this is also the event that unlocks refund authorization for the return case."

        Confirming intake leaves the return case untouched, so the retry carries
        the very same expected version and now prices the 114000-cent net refund
        onto both the ledger row and the case.

        Design: Difficulty/cross_entity_state_dependency/refund_authorization_gated_on_disposition_assignment_intake_confirmation
        """
        scenario = self._dispositioned_case()
        case = scenario["return_case"]

        api_client.create_refund_authorization(
            refund_authorization_payload(case["id"], case["version"]), AUTHORIZER_3
        )
        confirm_assignment_intake(scenario["assignment"]["id"], "DELIVERED")
        refund = get_success_data(
            api_client.create_refund_authorization(
                refund_authorization_payload(case["id"], case["version"]), AUTHORIZER_3
            ),
            expected_status=201,
        )

        assert refund["status"] == "AUTHORIZED"
        assert refund["net_refund_cents"] == 114000

        reloaded = read_return_case(case["id"])
        assert reloaded["financial_status"] == "AUTHORIZED"
        assert reloaded["final_refund_cents"] == 114000
        assert reloaded["version"] == case["version"] + 1, (
            "authorization bumps the case's version exactly once, from "
            f"{case['version']} to {reloaded['version']}"
        )

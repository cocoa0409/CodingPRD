"""Draws that must agree with three other rows, the trade gate, and the two sequencing fences."""

from __future__ import annotations

from decimal import Decimal

import pytest

from test_helpers import (
    ApiErrorId,
    Portfolio,
    acknowledge_plan,
    acknowledged_plan,
    activate_phase,
    assert_field_equals,
    assert_item_state,
    assert_plan_dimensions,
    authorize_budget,
    book_crew,
    bootstrap_portfolio,
    complete_item_work,
    contractor_booking_payload,
    current_property_version,
    draw_decision_payload,
    issue_plan,
    list_rows,
    locked_budget,
    read_budget,
    read_draw,
    read_item,
    read_phase,
    read_plan,
    read_property,
    register_contractor,
    register_property,
    reserve_draw_payload,
    schedule_phase,
    scope_plan,
    set_clock,
    start_item,
    validate_error,
    validate_success,
)


@pytest.fixture
def two_properties_each_with_their_own_plan(api):
    """One owner, two properties: plan A locked and running on P1, plan B still draft-funded on P2."""
    first = bootstrap_portfolio(
        api, "Netherby Hotels LLC", "ops@netherbyh.example", name="Netherby Central"
    )
    second = Portfolio(
        franchisee=first.franchisee,
        prop=register_property(api, first.franchisee_id, name="Netherby Southbank"),
        owner_headers=first.owner_headers,
    )
    plan_a = acknowledge_plan(
        api,
        issue_plan(
            api,
            scope_plan(
                api,
                first,
                [
                    {
                        "key": "wing_a",
                        "category": "GUEST_FACING",
                        "standards_reference": "GF-20.1.1",
                        "brand_estimated_cost_cents": 1000000,
                    }
                ],
            ),
        ),
    )
    budget_a = locked_budget(api, plan_a, 1182500, financing_source="RESERVE_DRAW")
    start_item(api, plan_a, plan_a.item_id("wing_a"))
    plan_b = issue_plan(
        api,
        scope_plan(
            api,
            second,
            [
                {
                    "key": "wing_b",
                    "category": "GUEST_FACING",
                    "standards_reference": "GF-20.2.1",
                    "brand_estimated_cost_cents": 1000000,
                }
            ],
            trigger_type="RELICENSING",
        ),
    )
    budget_b = authorize_budget(api, plan_b, 1182500, financing_source="RESERVE_DRAW")
    return plan_a, budget_a, plan_b, budget_b


class TestDrawReferentialAndFiscalGuards:
    def test_the_purpose_item_must_belong_to_the_budgets_plan(
        self, api, two_properties_each_with_their_own_plan
    ):
        """"Two referential rules bind the three references together: `purpose_item_id` must belong to
        the same plan as the budget named by `capital_budget_id` (`ERR_DRAW_ITEM_PLAN_MISMATCH`, 422)".

        Design: Corner/validations/reserve_draw_cross_entity_and_fiscal_guards_all_fire
        """
        plan_a, budget_a, plan_b, _budget_b = two_properties_each_with_their_own_plan
        version = current_property_version(api, plan_a.property_id, plan_a.owner_headers)

        response = api.create_reserve_draw(
            reserve_draw_payload(
                plan_a.property_id, budget_a["id"], plan_b.item_id("wing_b"), 100000, version
            ),
            plan_a.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_DRAW_ITEM_PLAN_MISMATCH, 422)
        prop = read_property(api, plan_a.property_id)
        assert_field_equals(prop, "reserve_balance_cents", 50000000, "first property")
        assert_field_equals(prop, "version", version, "first property")

    def test_the_property_must_be_the_property_of_the_budgets_plan(
        self, api, two_properties_each_with_their_own_plan
    ):
        """"and `property_id` must be the property of the plan that budget funds
        (`ERR_DRAW_PROPERTY_MISMATCH`, 422)."

        Design: Corner/validations/reserve_draw_cross_entity_and_fiscal_guards_all_fire
        """
        plan_a, budget_a, plan_b, _budget_b = two_properties_each_with_their_own_plan
        version = current_property_version(api, plan_b.property_id, plan_b.owner_headers)

        response = api.create_reserve_draw(
            reserve_draw_payload(
                plan_b.property_id, budget_a["id"], plan_a.item_id("wing_a"), 100000, version
            ),
            plan_b.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_DRAW_PROPERTY_MISMATCH, 422)
        _rows, meta = list_rows(api, "list_reserve_draws", property_id=plan_b.property_id)
        assert meta["total_count"] == 0, f"the refused draw must leave no row, got {meta}"

    def test_a_draw_beyond_the_budget_headroom_is_refused(
        self, api, two_properties_each_with_their_own_plan
    ):
        """"Headroom is the referenced budget's `total_authorized_cents` less its `committed_cents`
        less the sum of `amount_cents` over the *other* draws against that same budget whose `status`
        is `REQUESTED` or `BRAND_CONSENTED`. The new `amount_cents` must be no greater than that
        headroom — again with the boundary inclusive — or the create is refused with
        `ERR_DRAW_EXCEEDS_BUDGET` (409)."

        Design: Corner/validations/reserve_draw_cross_entity_and_fiscal_guards_all_fire
        """
        plan_a, budget_a, _plan_b, _budget_b = two_properties_each_with_their_own_plan
        version = current_property_version(api, plan_a.property_id, plan_a.owner_headers)

        response = api.create_reserve_draw(
            reserve_draw_payload(
                plan_a.property_id, budget_a["id"], plan_a.item_id("wing_a"), 1182501, version
            ),
            plan_a.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_DRAW_EXCEEDS_BUDGET, 409)
        settled = read_budget(api, budget_a["id"])
        assert_field_equals(settled, "committed_cents", 0, "first budget")
        assert_field_equals(settled, "status", "LOCKED", "first budget")
        _rows, meta = list_rows(api, "list_reserve_draws", property_id=plan_a.property_id)
        assert meta["total_count"] == 0, f"the refused draw must leave no row, got {meta}"

    def test_the_budgets_fundability_is_only_tested_at_consent(
        self, api, brand_manager, two_properties_each_with_their_own_plan
    ):
        """"Either decision is refused unless the draw is in `REQUESTED` (`ERR_DRAW_NOT_DECIDABLE`);
        consent additionally requires the draw's budget to be in `APPROVED`, `LOCKED` or `UNDERFUNDED`
        (`ERR_BUDGET_NOT_FUNDABLE`)." "A draw is created in `REQUESTED`, with `consented_by_user_id`
        and `disbursed_at` null, and increments the property's `version` by one."

        Design: Corner/validations/reserve_draw_cross_entity_and_fiscal_guards_all_fire
        """
        _plan_a, _budget_a, plan_b, budget_b = two_properties_each_with_their_own_plan
        version = current_property_version(api, plan_b.property_id, plan_b.owner_headers)

        draw = validate_success(
            api.create_reserve_draw(
                reserve_draw_payload(
                    plan_b.property_id, budget_b["id"], plan_b.item_id("wing_b"), 100000, version
                ),
                plan_b.owner_headers,
            ),
            201,
        )
        validate_error(
            api.consent_reserve_draw(draw["id"], draw_decision_payload("CONSENT"), brand_manager),
            ApiErrorId.ERR_BUDGET_NOT_FUNDABLE,
            409,
        )

        assert_field_equals(read_draw(api, draw["id"]), "status", "REQUESTED", "draw")
        assert_field_equals(read_budget(api, budget_b["id"]), "status", "DRAFT", "second budget")
        assert_field_equals(
            read_property(api, plan_b.property_id), "version", version + 1, "second property"
        )


@pytest.fixture
def active_phase_with_two_unapproved_contractors(api):
    """An active window on a plan with no life-safety scope, plus a fire and a general crew."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "public_areas",
                "category": "GUEST_FACING",
                "standards_reference": "GF-21.1.1",
                "brand_estimated_cost_cents": 900000,
            }
        ],
        legal_name="Overdale Hotels LLC",
        contact_email="ops@overdaleh.example",
    )
    phase = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=12,
    )
    fire = register_contractor(
        api,
        name="Pyrelock Sprinkler Co",
        trade="FIRE_PROTECTION",
        brand_approved=False,
        max_concurrent_bookings=2,
    )
    general = register_contractor(
        api,
        name="Quaylight Construction",
        trade="GENERAL",
        brand_approved=False,
        max_concurrent_bookings=2,
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    phase = activate_phase(api, scenario, phase["id"])
    return scenario, phase, fire, general


class TestFireProtectionTradeNeedsVetting:
    def test_an_unvetted_fire_protection_crew_may_not_be_booked(
        self, api, active_phase_with_two_unapproved_contractors
    ):
        """"A contractor whose `trade` is `FIRE_PROTECTION` may be booked only when its
        `brand_approved` flag is true, and the same vetting requirement extends to *any* contractor
        booked onto a phase of a plan that still carries a life-safety item in `SCOPED`,
        `DEFERRED_PENDING_EXTENSION` or `IN_PROGRESS`. A booking that breaches either arm is refused
        with `ERR_CONTRACTOR_NOT_BRAND_APPROVED` (409)."

        Design: Corner/validations/fire_protection_work_requires_a_brand_approved_contractor
        """
        scenario, phase, fire, _general = active_phase_with_two_unapproved_contractors

        response = api.create_contractor_booking(
            contractor_booking_payload(
                fire["id"],
                phase["id"],
                start_datetime="2026-09-02T08:00:00Z",
                end_datetime="2026-09-03T17:00:00Z",
                crew_size=4,
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_CONTRACTOR_NOT_BRAND_APPROVED, 409)
        _rows, meta = list_rows(api, "list_contractor_bookings", contractor_id=fire["id"])
        assert meta["total_count"] == 0, f"the refused engagement must leave no row, got {meta}"

    def test_an_unvetted_general_crew_on_the_same_window_is_admitted(
        self, api, active_phase_with_two_unapproved_contractors
    ):
        """"A booking is created in `BOOKED`". The second arm of the vetting rule does not bite here,
        since it extends only to "a phase of a plan that still carries a life-safety item in `SCOPED`,
        `DEFERRED_PENDING_EXTENSION` or `IN_PROGRESS`".

        Design: Corner/validations/fire_protection_work_requires_a_brand_approved_contractor
        """
        scenario, phase, _fire, general = active_phase_with_two_unapproved_contractors

        booking = book_crew(
            api,
            scenario,
            general["id"],
            phase["id"],
            start_datetime="2026-09-02T08:00:00Z",
            end_datetime="2026-09-03T17:00:00Z",
            crew_size=4,
        )

        assert_field_equals(booking, "status", "BOOKED", "booking")
        _rows, meta = list_rows(api, "list_contractor_bookings", phase_id=phase["id"])
        assert meta["total_count"] == 1, f"exactly one engagement should stand, got {meta}"
        assert_field_equals(
            read_property(api, scenario.property_id), "rooms_out_of_service_current", 12, "property"
        )


@pytest.fixture
def room_impacting_item_and_a_planned_phase(api):
    """A twenty-key room-impacting item, its funding locked, and its window not yet activated."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "guest_floors",
                "category": "GUEST_FACING",
                "standards_reference": "GF-22.1.1",
                "brand_estimated_cost_cents": 1000000,
                "room_impacting": True,
                "rooms_affected_count": 20,
            }
        ],
        legal_name="Ravensworth Hotels LLC",
        contact_email="ops@ravensworthh.example",
    )
    budget = locked_budget(api, scenario, 1182500)
    phase = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=20,
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    return scenario, budget, phase


class TestRoomWorkIsFencedOnBothSides:
    def test_room_work_may_not_start_without_an_active_phase(
        self, api, room_impacting_item_and_a_planned_phase
    ):
        """"If the item's `room_impacting` flag is true, some renovation phase of the same plan must
        be `ACTIVE`, must cover the clock date inside its closed interval — start date at or before
        the clock date, clock date at or before end date — and must hold `rooms_out_of_service` at
        least equal to the item's `rooms_affected_count`, or the start is refused with
        `ERR_NO_ACTIVE_PHASE_FOR_ROOM_WORK`."

        Design: Corner/validations/room_work_chain_requires_an_active_phase_and_blocks_early_closeout
        """
        scenario, _budget, phase = room_impacting_item_and_a_planned_phase

        response = api.start_item(scenario.item_id("guest_floors"), scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_NO_ACTIVE_PHASE_FOR_ROOM_WORK, 409)
        assert_item_state(read_item(api, scenario.item_id("guest_floors")), status="SCOPED")
        assert_field_equals(read_phase(api, phase["id"]), "status", "PLANNED", "phase")

    def test_the_phase_may_not_close_out_while_that_work_runs(
        self, api, room_impacting_item_and_a_planned_phase
    ):
        """"Closing a phase out moves it `ACTIVE → CLOSED_OUT` and is refused unless the phase is
        `ACTIVE` (`ERR_PHASE_NOT_CLOSEABLE`), unless the acting `X-User-ID` is the property's
        `franchisee_id`, and unless no room-impacting item of the phase's plan is still `IN_PROGRESS`
        (`ERR_ROOM_WORK_STILL_IN_PROGRESS`) — keys may not return to inventory while work that needs
        them out of service is running."

        Design: Corner/validations/room_work_chain_requires_an_active_phase_and_blocks_early_closeout
        """
        scenario, _budget, phase = room_impacting_item_and_a_planned_phase
        activated = activate_phase(api, scenario, phase["id"])
        start_item(api, scenario, scenario.item_id("guest_floors"))

        response = api.close_out_renovation_phase(phase["id"], scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_ROOM_WORK_STILL_IN_PROGRESS, 409)
        assert Decimal(str(activated["ooo_pct_at_activation"])) == Decimal("0.1000"), (
            f"20 of 200 keys is 0.1000 at activation, got {activated!r}"
        )
        assert_field_equals(read_phase(api, phase["id"]), "status", "ACTIVE", "phase")
        assert_item_state(read_item(api, scenario.item_id("guest_floors")), status="IN_PROGRESS")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="IN_EXECUTION")
        assert_field_equals(
            read_property(api, scenario.property_id), "rooms_out_of_service_current", 20, "property"
        )

    def test_the_keys_come_back_once_the_work_is_reported_finished(
        self, api, room_impacting_item_and_a_planned_phase
    ):
        """"Close-out subtracts the phase's `rooms_out_of_service` from the property's
        `rooms_out_of_service_current`, increments the property's `version`, restores the
        key-inventory invariant of §2.10, and marks every booking of the phase that is still `BOOKED`
        as `COMPLETED`, freeing that contractor's capacity."

        Design: Corner/validations/room_work_chain_requires_an_active_phase_and_blocks_early_closeout
        """
        scenario, _budget, phase = room_impacting_item_and_a_planned_phase
        activate_phase(api, scenario, phase["id"])
        start_item(api, scenario, scenario.item_id("guest_floors"))
        complete_item_work(api, scenario, scenario.item_id("guest_floors"))

        closed = validate_success(
            api.close_out_renovation_phase(phase["id"], scenario.owner_headers)
        )

        assert_field_equals(closed, "status", "CLOSED_OUT", "phase")
        assert_field_equals(closed, "displacement_revenue_impact_cents", 2142000, "phase")
        assert_plan_dimensions(
            read_plan(api, scenario.plan_id), status="READY_FOR_COMPLETION_INSPECTION"
        )
        assert_field_equals(
            read_property(api, scenario.property_id), "rooms_out_of_service_current", 0, "property"
        )


@pytest.fixture
def successor_waiting_on_a_running_predecessor(api):
    """Two back-of-house items in sequence, the upstream one already under way."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "predecessor",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-23.1.1",
                "brand_estimated_cost_cents": 1000000,
            },
            {
                "key": "successor",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-23.1.2",
                "brand_estimated_cost_cents": 1000000,
                "predecessor_key": "predecessor",
            },
        ],
        legal_name="Stonebeck Hotels LLC",
        contact_email="ops@stonebeckh.example",
    )
    budget = locked_budget(api, scenario, 2277000)
    start_item(api, scenario, scenario.item_id("predecessor"))
    return scenario, budget


class TestPredecessorGatePassesOnceSatisfied:
    def test_the_successor_is_refused_while_the_predecessor_runs(
        self, api, successor_waiting_on_a_running_predecessor
    ):
        """"If the item carries a `predecessor_item_id`, that predecessor's `status` must be
        `WORK_COMPLETE`, `ACCEPTED` or `REMOVED_BY_DISPUTE`, or the start is refused with
        `ERR_PREDECESSOR_NOT_SATISFIED`; an item with a null predecessor clears this check trivially."

        Design: Corner/validations/predecessor_gate_passes_once_the_upstream_item_completes
        """
        scenario, _budget = successor_waiting_on_a_running_predecessor

        response = api.start_item(scenario.item_id("successor"), scenario.owner_headers)

        validate_error(response, ApiErrorId.ERR_PREDECESSOR_NOT_SATISFIED, 409)
        assert_item_state(read_item(api, scenario.item_id("successor")), status="SCOPED")
        assert_item_state(read_item(api, scenario.item_id("predecessor")), status="IN_PROGRESS")

    def test_the_successor_starts_the_moment_the_predecessor_completes(
        self, api, successor_waiting_on_a_running_predecessor
    ):
        """"Reporting the work finished moves the item `IN_PROGRESS → WORK_COMPLETE`". "The item moves
        `SCOPED → IN_PROGRESS` and its `version` increments."

        Design: Corner/validations/predecessor_gate_passes_once_the_upstream_item_completes
        """
        scenario, budget = successor_waiting_on_a_running_predecessor
        complete_item_work(api, scenario, scenario.item_id("predecessor"))

        started = start_item(api, scenario, scenario.item_id("successor"))

        assert_field_equals(started, "status", "IN_PROGRESS", "successor")
        assert_item_state(read_item(api, scenario.item_id("predecessor")), status="WORK_COMPLETE")
        assert_plan_dimensions(read_plan(api, scenario.plan_id), status="IN_EXECUTION")
        settled = read_budget(api, budget["id"])
        assert_field_equals(settled, "status", "LOCKED", "budget")
        assert_field_equals(settled, "committed_cents", 0, "budget")

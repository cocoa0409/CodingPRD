"""Declared transitions, refused triggers, cascades and bounded loops.

Each case fires one trigger against one standing state and checks both the
outcome and the counters the trigger was or was not allowed to move.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_AIRCRAFT_HAS_OPEN_LEGS,
    ERR_ALREADY_TERMINAL,
    ERR_BASE_UNDERSTAFFED,
    ERR_COUNTER_ROUNDS_EXHAUSTED,
    ERR_CYCLE_HAS_OPEN_LEGS,
    ERR_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_block_hours,
    assert_is_null,
    assert_money,
    assert_ordered_by_created_at,
    assert_staffing_picture,
    assert_status,
    assert_version_bumped_by,
    grounding_candidate_order,
)
from test_helpers.factories import (
    make_agreement_payload,
    make_cancel_payload,
    make_completion_payload,
    make_counter_payload,
    make_pass_through_payload,
    make_revise_offer_payload,
    make_terminate_payload,
    make_transition_payload,
)
from test_helpers.fixtures import (
    add_leg,
    advance_pilot_to,
    attrite_pilot,
    build_active_agreement,
    build_open_cycle,
    build_staffed_base,
    cancel_leg,
    complete_leg,
    create_agreement,
    create_crew_base,
    hire_pilot,
    open_extension_offer,
    read_agreement,
    read_aircraft,
    read_crew_base,
    read_cycle,
    read_leg,
    read_negotiation,
    read_pilot,
    register_aircraft,
)
from test_helpers.test_users import ADMIN_HEADERS, OPS_HEADERS, SCHEDULER_HEADERS


class TestAgreementActivation:
    """Activation is the one gate between a signed contract and any operation."""

    def test_activating_a_draft_with_a_live_base_stamps_the_instant(self, api):
        """The transition changes status and time, and no money at all.

        PRD 3.1: "The `DRAFT → ACTIVE` transition stamps `activated_at` with the logical
        clock instant and increments the agreement's `version`."

        Design: Corner/state_machines/activate_agreement_moves_draft_to_active
        """
        agreement = create_agreement(api, make_agreement_payload())
        base = create_crew_base(
            api,
            agreement["id"],
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )

        activated = validate_success(
            api.activate_agreement(agreement["id"], headers=ADMIN_HEADERS)
        )

        assert_status(activated, "ACTIVE")
        assert activated["activated_at"] is not None, (
            "activation stamps the instant from the logical clock"
        )
        assert_version_bumped_by(agreement, activated, 1)

        assert_money(activated["settled_to_date_usd"], 0.00, "settled to date")
        assert activated["extension_round_count"] == 0
        assert_status(read_crew_base(api, base["id"]), "ACTIVE", field="lifecycle_status")


class TestCycleCloseRequiresResolvedLegs:
    """One unresolved leg is enough to hold the month open."""

    def test_a_month_with_a_scheduled_leg_cannot_be_closed(self, api):
        """The refusal carries its own code and publishes no scorecard.

        PRD 3.4: "A month with unresolved legs is refused with
        `ERR_CYCLE_HAS_OPEN_LEGS` (HTTP 409)."

        Design: Corner/state_machines/close_cycle_with_scheduled_leg_rejected
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N2501RG"],
            cycle_month="2026-09",
            published_departures=10,
        )
        add_leg(
            api,
            scenario,
            flight_number="SM6301",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:00:00Z",
            planned_block_hours=1.000,
        )

        response = api.close_schedule_cycle(scenario.cycle_id, headers=SCHEDULER_HEADERS)
        validate_error(response, ERR_CYCLE_HAS_OPEN_LEGS, 409)

        standing = read_cycle(api, scenario.cycle_id)
        assert_status(standing, "OPEN")
        assert_is_null(standing, "closed_at")

        cards, meta = validate_paginated(
            api.list_scorecards(headers=SCHEDULER_HEADERS, params={"cycle_id": scenario.cycle_id})
        )
        assert cards == []
        assert meta["total_count"] == 0


class TestCancelIsNotIdempotent:
    """The second cancel is a conflict, not a no-op, and records nothing.

    A repeat cancel must neither overwrite the recorded cause nor raise a second
    claim against the same leg.
    """

    def test_cancelling_an_already_cancelled_leg_is_refused(self, api):
        """The first cause code stands and the ledger moved exactly once.

        PRD 3.4: "Cancelling a leg is the other `RegionalOpsController` report, permitted
        from `SCHEDULED` while the cycle is `OPEN`, and it names a `cause_code` from
        `CREW_UNAVAILABLE`, `MAINTENANCE`, `WEATHER`, `ATC`, `MAINLINE_REQUEST` or
        `SECURITY`."

        Design: Corner/state_machines/cancel_leg_twice_rejected
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N2601RG"],
            cycle_month="2026-09",
            published_departures=10,
        )
        leg = add_leg(
            api,
            scenario,
            flight_number="SM6401",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:00:00Z",
            planned_block_hours=1.000,
        )
        cancel_leg(api, leg["id"], cause_code="WEATHER")

        response = api.cancel_flight_leg(
            leg["id"], make_cancel_payload(cause_code="ATC"), headers=OPS_HEADERS
        )
        validate_error(response, ERR_INVALID_STATE, 409)

        standing = read_leg(api, leg["id"])
        assert_status(standing, "CANCELLED")
        assert standing["cancel_cause_code"] == "WEATHER", (
            "the refused second report does not overwrite the recorded cause"
        )

        claims, meta = validate_paginated(
            api.list_cancellation_claims(headers=OPS_HEADERS, params={"leg_id": leg["id"]})
        )
        assert meta["total_count"] == 1
        assert len(claims) == 1

        month = read_cycle(api, scenario.cycle_id)
        assert month["cancelled_controllable_count"] == 1
        assert month["metric_completed_departures"] == 9
        assert month["departure_ledger_total"] == 10


class TestCompletedLegIsLockedDown:
    """COMPLETED is the leg's only terminal state, so a re-report is terminal-guarded."""

    def test_reporting_a_completed_leg_again_is_refused_as_already_terminal(self, api):
        """The second report's figures reach neither the leg nor the month.

        PRD 3.1: "One scoping rule is worth stating here because it governs the whole of
        §3: the already-terminal guard that yields `ERR_ALREADY_TERMINAL` applies to the
        action endpoints of aircraft, pilots, flight legs, cancellation claims,
        pass-through claims, invoices and extension negotiations."

        Design: Corner/state_machines/complete_already_completed_leg_rejected
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N2701RG"],
            cycle_month="2026-09",
            published_departures=10,
        )
        leg = add_leg(
            api,
            scenario,
            flight_number="SM6501",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:00:00Z",
            planned_block_hours=1.000,
        )
        complete_leg(
            api,
            leg["id"],
            make_completion_payload(
                actual_block_hours=1.000,
                actual_arrival_utc="2026-09-02T09:00:00Z",
                enplaned_bags=40,
                mishandled_bags=0,
            ),
        )

        response = api.complete_flight_leg(
            leg["id"],
            make_completion_payload(
                actual_block_hours=2.000,
                actual_arrival_utc="2026-09-02T10:05:00Z",
                enplaned_bags=90,
                mishandled_bags=4,
            ),
            headers=OPS_HEADERS,
        )
        validate_error(response, ERR_ALREADY_TERMINAL, 409)

        standing = read_leg(api, leg["id"])
        assert_block_hours(standing["actual_block_hours"], 1.000, "actual block hours")
        assert standing["enplaned_bags"] == 40
        assert standing["mishandled_bags"] == 0
        assert_money(standing["leg_variable_payment_usd"], 1770.75, "leg variable payment")

        month = read_cycle(api, scenario.cycle_id)
        assert_block_hours(month["credited_block_hours"], 1.000, "credited block hours")
        assert month["recorded_completed_legs"] == 1
        assert month["enplaned_bags_total"] == 40
        assert month["mishandled_bags_total"] == 0


class TestReinstateIsDeclaredOnlyFromCancelled:
    """A refused trigger leaves the reinstatement counter untouched."""

    def test_reinstating_a_scheduled_leg_is_refused(self, api):
        """The leg was never cancelled, so there is nothing to compensate.

        PRD 3.4: "A `RegionalOpsController` may move a leg `CANCELLED → SCHEDULED` while
        the cycle is `OPEN`, provided the tail is still `IN_SERVICE` — the availability
        rule of `ERR_AIRCRAFT_NOT_AVAILABLE` guards reinstatement just as it guards
        scheduling and completion — and provided the leg's cancellation claim has not yet
        been finalized."

        Design: Corner/state_machines/reinstate_scheduled_leg_rejected
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N2801RG"],
            cycle_month="2026-09",
            published_departures=10,
        )
        leg = add_leg(
            api,
            scenario,
            flight_number="SM6601",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:00:00Z",
            planned_block_hours=1.000,
        )

        response = api.reinstate_flight_leg(leg["id"], headers=OPS_HEADERS)
        validate_error(response, ERR_INVALID_STATE, 409)

        standing = read_leg(api, leg["id"])
        assert_status(standing, "SCHEDULED")
        assert standing["reinstate_count"] == 0, (
            "the counter records successful reinstatements only"
        )

        month = read_cycle(api, scenario.cycle_id)
        assert month["open_leg_count"] == 1
        assert month["cancelled_controllable_count"] == 0


class TestInductionRequiresAnActiveAgreement:
    """The governing-contract check outranks the base's own staffing test."""

    def test_a_draft_agreement_refuses_the_induction_before_staffing_is_considered(self, api):
        """The base is unstaffed too, yet the earlier code is the one surfaced.

        PRD 3.3: "A `RegionalOpsController` may move a tail from `PENDING_INDUCTION` to
        `IN_SERVICE` only when the governing agreement is `ACTIVE`, the assigned base's
        `lifecycle_status` is `ACTIVE`, and two capacity tests both pass."

        PRD 2.12: "The practical consequence is that a request failing several of these
        surfaces only the earliest code in the list."

        Design: Corner/state_machines/induct_tail_before_agreement_activation_rejected
        """
        agreement = create_agreement(api, make_agreement_payload())
        base = create_crew_base(
            api,
            agreement["id"],
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        tail = register_aircraft(api, agreement["id"], base["id"], tail_number="N2901RG")

        response = api.induct_aircraft(tail["id"], headers=OPS_HEADERS)
        error_id = validate_error(response, ERR_AGREEMENT_NOT_ACTIVE, 409)["error_id"]
        assert error_id != ERR_BASE_UNDERSTAFFED, (
            "the staffing admissibility test sits later in the precedence order"
        )

        standing = read_aircraft(api, tail["id"])
        assert_status(standing, "PENDING_INDUCTION")
        assert_is_null(standing, "inducted_at")
        assert_staffing_picture(read_crew_base(api, base["id"]), assigned_aircraft=0)


class TestTerminationCascade:
    """The cascade runs two hops and only over children that are still admissible."""

    def test_termination_closes_the_base_and_withdraws_only_the_pending_tail(self, api):
        """The in-service tail and the qualified pilot are outside the cascade.

        PRD 3.1: "Second hop, caused by the first: because each of those bases is now
        `CLOSED`, every aircraft assigned to it that is still sitting in
        `PENDING_INDUCTION` moves to `WITHDRAWN`."

        Design: Corner/state_machines/agreement_termination_cascades_base_and_pending_tail
        """
        scenario = build_staffed_base(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=2,
            line_qualified_pilots=1,
            tail_numbers=["N3001RG"],
        )
        pending = register_aircraft(
            api,
            scenario.agreement_id,
            scenario.crew_base_id,
            tail_number="N3002RG",
            ownership="MAINLINE_OWNED",
        )

        terminated = validate_success(
            api.terminate_agreement(
                scenario.agreement_id,
                make_terminate_payload(termination_reason="MUTUAL_AGREEMENT"),
                headers=ADMIN_HEADERS,
            )
        )

        assert_status(terminated, "TERMINATED")
        assert_status(
            read_crew_base(api, scenario.crew_base_id), "CLOSED", field="lifecycle_status"
        )
        assert_status(read_aircraft(api, pending["id"]), "WITHDRAWN")
        assert_status(read_aircraft(api, scenario.aircraft_id), "IN_SERVICE")
        assert_status(read_pilot(api, scenario.captain_pilot_id), "LINE_QUALIFIED")


class TestFleetTransitionRequiresAnEmptySchedule:
    """Forward schedule exposure, not the tail's own state, blocks fleet renewal."""

    def test_one_scheduled_leg_blocks_the_transition_and_records_nothing(self, api):
        """The refused transition neither records the intent nor releases the allocation.

        PRD 3.3: "It is refused while the tail still has any leg in `SCHEDULED` status,
        with `ERR_AIRCRAFT_HAS_OPEN_LEGS` (HTTP 409); an aeroplane cannot be pulled out
        from under a published schedule."

        Design: Corner/state_machines/transition_tail_with_scheduled_leg_rejected
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N3101RG"],
            cycle_month="2026-09",
            published_departures=10,
        )
        add_leg(
            api,
            scenario,
            flight_number="SM6701",
            origin="MKE",
            destination="ORD",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            scheduled_arrival_utc="2026-09-02T09:00:00Z",
            planned_block_hours=1.000,
        )

        response = api.transition_aircraft(
            scenario.aircraft_id,
            make_transition_payload(
                transition_reason="FLEET_RENEWAL", target_ownership="MAINLINE_OWNED"
            ),
            headers=ADMIN_HEADERS,
        )
        validate_error(response, ERR_AIRCRAFT_HAS_OPEN_LEGS, 409)

        standing = read_aircraft(api, scenario.aircraft_id)
        assert_status(standing, "IN_SERVICE")
        assert_is_null(standing, "transition_reason", "target_ownership")
        assert_staffing_picture(read_crew_base(api, scenario.crew_base_id), assigned_aircraft=1)


class TestGroundedTailRestorationIsConditional:
    """Which pilot status the replacement reaches decides whether the tail comes back."""

    def test_training_credit_floors_to_zero_and_only_qualification_restores_the_tail(self, api):
        """Sixty-five hundredths of one trainee floors to no pilot at all.

        PRD 3.2: "The **pipeline basis** additionally credits the training pipeline net of
        expected attrition: each pilot in training counts as sixty-five hundredths of a
        line pilot — thirty-five hundredths of the pipeline is discounted for the attrition
        the base expects before qualification — and the credited contribution is floored to
        a whole pilot before being added to `line_qualified_pilot_count`."

        PRD 3.3: "When a recompute leaves the number of `IN_SERVICE` tails at the base
        below `allocatable_aircraft_count`, the server returns grounded tails to service:
        the candidate set is the tails at that base in `GROUNDED_STAFFING`, ranked by
        `created_at` ascending so the longest-grounded tails come back first, again with
        `tail_number` ascending as the tie-break."

        Design: Corner/state_machines/grounded_tail_restored_only_when_pilot_reaches_line_qualified
        """
        scenario = build_staffed_base(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=2,
            line_qualified_pilots=2,
            tail_numbers=["N3201RG", "N3202RG"],
        )
        grounded_tail, retained_tail = grounding_candidate_order(scenario.aircraft)
        attrite_pilot(api, scenario.pilot_ids[1], scenario.crew_base_id, "MAINLINE")
        assert_status(read_aircraft(api, grounded_tail["id"]), "GROUNDED_STAFFING")

        replacement = hire_pilot(
            api, scenario.crew_base_id, "EMP-3203", seat="CAPTAIN", hire_class_date="2026-08-01"
        )

        advance_pilot_to(api, replacement["id"], scenario.crew_base_id, "IN_TRAINING")
        mid = read_crew_base(api, scenario.crew_base_id)
        assert_staffing_picture(
            mid, line_qualified=1, in_training=1, allocatable_aircraft=1, assigned_aircraft=2
        )
        assert_status(read_aircraft(api, grounded_tail["id"]), "GROUNDED_STAFFING")

        advance_pilot_to(api, replacement["id"], scenario.crew_base_id, "LINE_QUALIFIED")
        after = read_crew_base(api, scenario.crew_base_id)
        assert_staffing_picture(
            after,
            line_qualified=2,
            in_training=0,
            headcount_shortfall=0,
            posture="STAFFED",
            allocatable_aircraft=2,
        )

        restored = read_aircraft(api, grounded_tail["id"])
        assert_status(restored, "IN_SERVICE")
        assert_is_null(restored, "grounded_reason")
        assert_status(read_aircraft(api, retained_tail["id"]), "IN_SERVICE")


class TestPassThroughEstimateLedger:
    """Opening a claim syncs the estimate ledger and leaves the settlement ledger alone."""

    def test_two_categories_sum_into_the_month_estimate_while_settlement_stays_empty(self, api):
        """The two ledgers move on different events, so only one of them moves here.

        PRD 3.6: "A new claim lands in `SUBMITTED` with `actual_amount_usd`,
        `supporting_doc_ref`, `allowed_amount_usd`, `variance_usd`,
        `actual_submitted_by_user_id` and `reconciled_by_user_id` all null, and the month's
        `estimated_passthrough_total_usd` takes on the filed estimate."

        Design: Corner/state_machines/passthrough_estimate_rolls_up_to_cycle_ledger
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N3301RG"],
            cycle_month="2026-09",
            published_departures=10,
        )

        fees = validate_success(
            api.create_pass_through_claim(
                make_pass_through_payload(
                    scenario.cycle_id, category="AIRPORT_FEES", estimated_amount_usd=12500.00
                ),
                headers=OPS_HEADERS,
            ),
            201,
        )
        insurance = validate_success(
            api.create_pass_through_claim(
                make_pass_through_payload(
                    scenario.cycle_id, category="INSURANCE", estimated_amount_usd=7500.00
                ),
                headers=OPS_HEADERS,
            ),
            201,
        )

        for claim in (fees, insurance):
            assert_status(claim, "SUBMITTED")
            assert_is_null(claim, "allowed_amount_usd", "variance_usd")

        month = read_cycle(api, scenario.cycle_id)
        assert_money(
            month["estimated_passthrough_total_usd"], 20000.00, "estimated pass-through total"
        )
        assert_money(month["passthrough_settlement_usd"], 0.00, "pass-through settlement")

        claims, meta = validate_paginated(
            api.list_pass_through_claims(
                headers=OPS_HEADERS, params={"cycle_id": scenario.cycle_id}
            )
        )
        assert meta["total_count"] == 2
        assert_ordered_by_created_at(claims)


class TestExtensionCounterLoopIsBounded:
    """The bargaining loop closes on a counter, not on the state alphabet."""

    def test_a_third_counter_is_refused_although_the_round_is_legally_offered(self, api):
        """Two counters exhaust the bound; the revised offer on the table stands.

        PRD 3.9: "Each counter raises `counter_round` by 1, and the loop is bounded at
        two: a round whose `counter_round` has already reached two may not be countered
        again, and the attempt is refused with `ERR_COUNTER_ROUNDS_EXHAUSTED` (HTTP 409)."

        Design: Corner/state_machines/extension_counter_rounds_exhausted_after_two_loops
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        negotiation = open_extension_offer(
            api,
            scenario.agreement_id,
            proposed_term_end_date="2031-12-31",
            proposed_block_hour_rate_usd=1500.00,
        )
        validate_success(
            api.counter_negotiation(
                negotiation["id"],
                make_counter_payload(
                    counter_term_end_date="2032-06-30", counter_block_hour_rate_usd=1575.00
                ),
                headers=OPS_HEADERS,
            )
        )
        validate_success(
            api.revise_offer(
                negotiation["id"],
                make_revise_offer_payload(
                    proposed_term_end_date="2032-03-31", proposed_block_hour_rate_usd=1525.00
                ),
                headers=SCHEDULER_HEADERS,
            )
        )
        validate_success(
            api.counter_negotiation(
                negotiation["id"],
                make_counter_payload(
                    counter_term_end_date="2032-06-30", counter_block_hour_rate_usd=1560.00
                ),
                headers=OPS_HEADERS,
            )
        )
        validate_success(
            api.revise_offer(
                negotiation["id"],
                make_revise_offer_payload(
                    proposed_term_end_date="2032-04-30", proposed_block_hour_rate_usd=1540.00
                ),
                headers=SCHEDULER_HEADERS,
            )
        )

        response = api.counter_negotiation(
            negotiation["id"],
            make_counter_payload(
                counter_term_end_date="2032-06-30", counter_block_hour_rate_usd=1550.00
            ),
            headers=OPS_HEADERS,
        )
        validate_error(response, ERR_COUNTER_ROUNDS_EXHAUSTED, 409)

        standing = read_negotiation(api, negotiation["id"])
        assert_status(standing, "OFFERED")
        assert standing["counter_round"] == 2
        assert standing["proposed_term_end_date"] == "2032-04-30"
        assert_money(
            standing["proposed_block_hour_rate_usd"], 1540.00, "the offer left on the table"
        )
        assert_is_null(standing, "counter_term_end_date", "counter_block_hour_rate_usd")

        agreement = read_agreement(api, scenario.agreement_id)
        assert_status(agreement, "EXTENSION_PENDING")
        assert agreement["term_end_date"] == "2029-12-31"

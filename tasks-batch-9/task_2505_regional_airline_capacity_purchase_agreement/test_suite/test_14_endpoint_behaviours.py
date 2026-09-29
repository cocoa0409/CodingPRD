"""Endpoint-level behaviour: the clock sweep, recomputation, links, and settlement gates.

Each test drives one endpoint whose effect is not confined to the resource it names —
the clock's expiry sweep, a recompute that re-reads the month, a leg creation that
establishes three associations at once, and the variant gate on issuance.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_INVOICE_VARIANT_NOT_FINAL,
)
from test_helpers.assertions import (
    assert_is_null,
    assert_money,
    assert_percentage,
    assert_status,
    ids_of,
)
from test_helpers.factories import (
    make_agreement_payload,
    make_completion_payload,
    make_flight_leg_payload,
    make_invoice_payload,
    make_second_agreement_payload,
)
from test_helpers.fixtures import (
    add_leg,
    build_active_agreement,
    build_open_cycle,
    cancel_leg,
    classify_claim,
    claim_for_leg,
    close_cycle,
    complete_leg,
    create_agreement,
    create_cycle,
    cycle_version,
    finalize_claim,
    hire_pilot,
    induct_aircraft,
    open_cycle,
    qualify_pilot,
    read_agreement,
    read_crew_base,
    read_cycle,
    read_invoice,
    register_aircraft,
    scorecard_for_cycle,
)
from test_helpers.test_users import ADMIN_HEADERS, SCHEDULER_HEADERS


class TestClockSweepExpiresOnlyLiveAgreements:
    """The sweep is conditional on the status and on the date, and both conditions bite."""

    def test_the_term_end_date_must_be_strictly_passed_and_the_draft_is_left_alone(self, api):
        """A move to the last day of the term changes nothing; the next day expires it.

        PRD 2.5: "Setting the clock also performs one sweep. Immediately after the new
        instant is installed, every agreement whose `status` is `ACTIVE` and whose
        `term_end_date` falls strictly before the calendar date of the new logical instant is
        moved to `EXPIRED`, each such agreement's `version` incrementing by 1."

        PRD 2.5: "Expiry deliberately leaves the agreement's schedule cycles alone: a cycle
        sitting in `PLANNED` is not touched, but it can never be opened again, because
        opening requires a governing agreement in `ACTIVE`."

        Design: Corner/endpoints/clock_advance_past_term_end_expires_agreement
        """
        live = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(term_end_date="2026-09-30"),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        dormant = create_agreement(
            api, make_second_agreement_payload(term_end_date="2026-09-30")
        )
        planned = create_cycle(
            api, live.agreement_id, cycle_month="2026-10", published_departures=0
        )

        validate_success(api.set_clock("2026-09-30T23:59:00Z", headers=ADMIN_HEADERS))
        assert_status(read_agreement(api, live.agreement_id), "ACTIVE")

        validate_success(api.set_clock("2026-10-01T00:00:00Z", headers=ADMIN_HEADERS))
        expired = read_agreement(api, live.agreement_id)
        assert_status(expired, "EXPIRED")
        assert_status(read_crew_base(api, live.crew_base_id), "ACTIVE", field="lifecycle_status")
        assert_status(read_agreement(api, dormant["id"]), "DRAFT")

        assert_status(read_cycle(api, planned["id"]), "PLANNED")
        validate_error(
            api.open_schedule_cycle(planned["id"], headers=SCHEDULER_HEADERS),
            ERR_AGREEMENT_NOT_ACTIVE,
            409,
        )
        assert_status(read_cycle(api, planned["id"]), "PLANNED")


class TestScorecardRecompute:
    """Recompute reads the month's live counters rather than replaying the close."""

    def test_a_finalized_uncontrollable_cancellation_turns_a_capped_penalty_into_an_incentive(
        self, api
    ):
        """The same scorecard flips sign because the eligible base moved under it.

        PRD 3.7: "Recomputation rebuilds every metric, every point value,
        `gross_performance_usd`, `incentive_usd`, `penalty_usd` and `brand_penalty_usd` from
        the month's current counters and the current exposure set, leaves the scorecard in
        `PUBLISHED`, raises `recompute_count` by 1 and increments the scorecard's `version`."

        PRD 3.7: "**Completion factor**, published as `completion_factor_pct`, starts from
        the eligible departure base: `published_departures` less
        `cancelled_uncontrollable_count`."

        PRD 3.7: "Concretely, when `completion_factor_points` is −4, `on_time_points` becomes
        whichever is smaller, 0 or the banded on-time value, and `bag_points` likewise
        becomes whichever is smaller, 0 or the banded bag value; an operator that ran a
        superb on-time month while cancelling too much banks nothing for the punctuality."

        Design: Corner/endpoints/scorecard_recompute_refreshes_metrics_and_counter
        """
        scenario = build_open_cycle(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
            line_qualified_pilots=1,
            tail_numbers=["N4601RG"],
            cycle_month="2026-09",
            published_departures=4,
        )
        flown = []
        for index, day in enumerate(("02", "03", "04")):
            flown.append(
                add_leg(
                    api,
                    scenario,
                    flight_number=f"SM760{index + 1}",
                    origin="MKE",
                    destination="ORD",
                    scheduled_departure_utc=f"2026-09-{day}T08:00:00Z",
                    scheduled_arrival_utc=f"2026-09-{day}T09:00:00Z",
                    planned_block_hours=1.000,
                )
            )
        dropped = add_leg(
            api,
            scenario,
            flight_number="SM7604",
            origin="DEN",
            destination="MKE",
            scheduled_departure_utc="2026-09-05T08:00:00Z",
            scheduled_arrival_utc="2026-09-05T09:00:00Z",
            planned_block_hours=1.000,
        )
        for leg, day in zip(flown, ("02", "03", "04")):
            complete_leg(
                api,
                leg["id"],
                make_completion_payload(
                    actual_block_hours=1.000,
                    actual_arrival_utc=f"2026-09-{day}T09:05:00Z",
                    enplaned_bags=100,
                    mishandled_bags=0,
                ),
            )
        cancel_leg(api, dropped["id"], cause_code="WEATHER")
        close_cycle(api, scenario.cycle_id)

        published = scorecard_for_cycle(api, scenario.cycle_id)
        assert_percentage(published["completion_factor_pct"], 75.00, "completion factor at close")
        assert published["completion_factor_points"] == -4
        assert published["on_time_points"] == 0, (
            "the forfeiture branch voids the punctuality credit"
        )
        assert published["bag_points"] == 0, "the forfeiture branch voids the baggage credit"
        assert published["performance_points"] == -4
        assert_money(published["gross_performance_usd"], -48000.00, "gross performance at close")
        assert_money(published["penalty_usd"], 48000.00, "penalty at close")
        assert_money(published["incentive_usd"], 0.00, "incentive at close")

        claim = claim_for_leg(api, dropped["id"])
        classify_claim(api, claim["id"], classification="UNCONTROLLABLE")
        finalize_claim(api, claim["id"])
        assert_status(scorecard_for_cycle(api, scenario.cycle_id), "STALE")

        recomputed = validate_success(
            api.recompute_scorecard(published["id"], headers=ADMIN_HEADERS)
        )

        assert_status(recomputed, "PUBLISHED")
        assert recomputed["recompute_count"] == 1
        assert_percentage(
            recomputed["completion_factor_pct"], 100.00, "completion factor after recompute"
        )
        assert recomputed["completion_factor_points"] == 3
        assert recomputed["on_time_points"] == 2
        assert recomputed["bag_points"] == 1
        assert recomputed["performance_points"] == 6
        assert_money(recomputed["gross_performance_usd"], 72000.00, "gross performance")
        assert_money(
            recomputed["incentive_usd"], 15865.61, "incentive under the revenue-share ceiling"
        )
        assert_money(recomputed["penalty_usd"], 0.00, "penalty after recompute")

        month = read_cycle(api, scenario.cycle_id)
        assert month["cancelled_controllable_count"] == 0
        assert month["cancelled_uncontrollable_count"] == 1
        assert month["departure_ledger_total"] == 4


class TestLegEstablishesThreeAssociations:
    """One creation writes three foreign keys, each visible through its own filter."""

    def test_the_published_leg_is_found_by_month_by_tail_and_by_captain(self, api):
        """The second tail and the second captain carry no legs at all.

        PRD 3.4: "The `MainlineScheduler` schedules one by naming the `cycle_id` it is
        credited to, the `aircraft_id` operating it, the `captain_pilot_id` in command, the
        mainline-branded `flight_number`, the `origin` and `destination` station codes, the
        published `scheduled_departure_utc` and `scheduled_arrival_utc` instants, and the
        `planned_block_hours` the schedule allows."

        PRD 3.4: "Leg listings may be narrowed by `cycle_id`, `aircraft_id`,
        `captain_pilot_id`, or `status`."

        Design: Corner/endpoints/flight_leg_links_cycle_tail_and_captain
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=2,
        )
        first_captain = hire_pilot(
            api, scenario.crew_base_id, "EMP-4701", hire_class_date="2026-05-01"
        )
        second_captain = hire_pilot(
            api, scenario.crew_base_id, "EMP-4702", hire_class_date="2026-05-01"
        )
        qualify_pilot(api, first_captain["id"], scenario.crew_base_id)
        qualify_pilot(api, second_captain["id"], scenario.crew_base_id)

        first_tail = register_aircraft(
            api, scenario.agreement_id, scenario.crew_base_id, tail_number="N4701RG"
        )
        induct_aircraft(api, first_tail["id"])
        second_tail = register_aircraft(
            api,
            scenario.agreement_id,
            scenario.crew_base_id,
            tail_number="N4702RG",
            ownership="MAINLINE_OWNED",
        )
        induct_aircraft(api, second_tail["id"])

        cycle = create_cycle(
            api, scenario.agreement_id, cycle_month="2026-09", published_departures=5
        )
        cycle = open_cycle(api, cycle["id"])

        leg = validate_success(
            api.create_flight_leg(
                make_flight_leg_payload(
                    cycle["id"],
                    first_tail["id"],
                    first_captain["id"],
                    flight_number="SM7701",
                    origin="MKE",
                    destination="ORD",
                    scheduled_departure_utc="2026-09-02T08:00:00Z",
                    scheduled_arrival_utc="2026-09-02T09:00:00Z",
                    planned_block_hours=1.000,
                ),
                headers=SCHEDULER_HEADERS,
            ),
            201,
        )

        assert leg["cycle_id"] == cycle["id"]
        assert leg["aircraft_id"] == first_tail["id"]
        assert leg["captain_pilot_id"] == first_captain["id"]

        for query in (
            {"cycle_id": cycle["id"]},
            {"aircraft_id": first_tail["id"]},
            {"captain_pilot_id": first_captain["id"]},
        ):
            found, meta = validate_paginated(
                api.list_flight_legs(headers=SCHEDULER_HEADERS, params=query)
            )
            assert meta["total_count"] == 1, f"the leg should be found by {query}"
            assert ids_of(found) == [leg["id"]]

        for query in (
            {"aircraft_id": second_tail["id"]},
            {"captain_pilot_id": second_captain["id"]},
        ):
            found, meta = validate_paginated(
                api.list_flight_legs(headers=SCHEDULER_HEADERS, params=query)
            )
            assert found == [], f"nothing should be found by {query}"
            assert meta["total_count"] == 0

        base = read_crew_base(api, scenario.crew_base_id)
        assert base["assigned_aircraft_count"] == 2, (
            "publishing a leg does not change the fleet allocation"
        )


class TestIssuanceIsGatedOnVariant:
    """A provisional bill can never settle, however clean the month is."""

    def test_issuing_a_provisional_invoice_is_refused_and_moves_no_money(self, api):
        """The month is closed and unencumbered, and the refusal is the variant alone.

        PRD 3.8: "Four further conditions apply, and each has its own rejection: the
        `variant` must be `FINAL`, and issuing a provisional bill is refused with
        `ERR_INVOICE_VARIANT_NOT_FINAL` (HTTP 422); the month must be `CLOSED`; every
        pass-through claim of the month must be terminal, failing which
        `ERR_PASSTHROUGH_UNRECONCILED`; and the month's scorecard must be `PUBLISHED`, a
        scorecard sitting in `STALE` blocking settlement with `ERR_SCORECARD_STALE` (HTTP
        409) until it has been recomputed."

        Design: Corner/endpoints/issue_final_on_provisional_invoice_rejected
        """
        scenario = build_active_agreement(
            api,
            agreement_payload=make_agreement_payload(),
            station_code="MKE",
            pilots_required_per_aircraft=1,
            aircraft_allocation_cap=1,
        )
        cycle = create_cycle(
            api, scenario.agreement_id, cycle_month="2026-09", published_departures=0
        )
        cycle = open_cycle(api, cycle["id"])
        invoice = validate_success(
            api.create_invoice(
                cycle["id"],
                make_invoice_payload("PROVISIONAL", cycle_version(api, cycle["id"])),
                headers=ADMIN_HEADERS,
            ),
            201,
        )
        closed = close_cycle(api, cycle["id"])
        assert_status(closed, "CLOSED")
        assert_status(scorecard_for_cycle(api, cycle["id"]), "PUBLISHED")

        validate_error(
            api.issue_final_invoice(invoice["id"], headers=ADMIN_HEADERS),
            ERR_INVOICE_VARIANT_NOT_FINAL,
            422,
        )

        standing = read_invoice(api, invoice["id"])
        assert_status(standing, "DRAFT")
        assert_is_null(standing, "issued_final_at")

        agreement = read_agreement(api, scenario.agreement_id)
        assert_money(agreement["settled_to_date_usd"], 0.00, "settled to date")
        assert agreement["open_invoice_count"] == 1
        assert_status(read_cycle(api, cycle["id"]), "CLOSED")

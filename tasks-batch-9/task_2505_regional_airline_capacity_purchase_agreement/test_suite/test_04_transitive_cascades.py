"""Cascades that reach several entities deep from a single request.

Finalizing one cancellation unwinds an issued bill five hops away, and one pilot
departure grounds a tail three hops away.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_money,
    assert_percentage,
    assert_staffing_picture,
    assert_status,
    grounding_candidate_order,
)
from test_helpers.constants import GROUNDED_REASON_STAFFING_SHORTFALL
from test_helpers.factories import (
    make_agreement_payload,
    make_attrite_payload,
    make_completion_payload,
)
from test_helpers.fixtures import (
    add_leg,
    build_open_cycle,
    build_staffed_base,
    cancel_leg,
    claim_for_leg,
    classify_claim,
    close_cycle,
    complete_leg,
    finalize_claim,
    issue_invoice,
    raise_invoice,
    read_agreement,
    read_aircraft,
    read_crew_base,
    read_cycle,
    read_invoice,
    read_pilot,
    read_scorecard,
    scorecard_for_cycle,
)
from test_helpers.test_users import make_base_chief_pilot_headers

SETTLED_INVOICE_TOTAL_USD = 334362.99


def _build_settled_month_with_open_verdict(api):
    """A settled September month whose one cancellation is classified but not final."""
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="ORD",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=4,
        line_qualified_pilots=1,
        tail_numbers=["N701RG"],
        cycle_month="2026-09",
        published_departures=100,
    )
    flown = (
        ("SM4501", "DSM", "2026-09-02T08:00:00Z", "2026-09-02T09:12:00Z", 1.200, 1.155, "2026-09-02T09:26:00Z", 120),
        ("SM4502", "MSP", "2026-09-04T08:00:00Z", "2026-09-04T10:00:00Z", 2.000, 2.007, "2026-09-04T10:14:00Z", 100),
        ("SM4503", "SBN", "2026-09-06T08:00:00Z", "2026-09-06T08:42:00Z", 0.700, 0.616, "2026-09-06T08:40:00Z", 80),
    )
    for number, destination, departure, arrival, planned, actual, actual_arrival, bags in flown:
        leg = add_leg(
            api,
            scenario,
            flight_number=number,
            origin="ORD",
            destination=destination,
            scheduled_departure_utc=departure,
            scheduled_arrival_utc=arrival,
            planned_block_hours=planned,
        )
        complete_leg(
            api,
            leg["id"],
            make_completion_payload(
                actual_block_hours=actual,
                actual_arrival_utc=actual_arrival,
                enplaned_bags=bags,
                mishandled_bags=0,
            ),
        )

    dropped = add_leg(
        api,
        scenario,
        flight_number="SM4504",
        origin="ORD",
        destination="GRR",
        scheduled_departure_utc="2026-09-08T08:00:00Z",
        scheduled_arrival_utc="2026-09-08T09:30:00Z",
        planned_block_hours=1.500,
    )
    cancel_leg(api, dropped["id"], cause_code="WEATHER")
    claim = claim_for_leg(api, dropped["id"])
    classify_claim(api, claim["id"], "UNCONTROLLABLE")

    close_cycle(api, scenario.cycle_id)
    invoice = raise_invoice(api, scenario.cycle_id, "FINAL")
    issue_invoice(api, invoice["id"])
    scorecard = scorecard_for_cycle(api, scenario.cycle_id)
    return scenario, claim, invoice, scorecard


class TestClaimFinalizationCascade:
    """One finalization walks claim, month, scorecard, invoice and agreement."""

    def test_finalizing_an_uncontrollable_verdict_moves_the_month_cancellation_counters(self, api):
        """The agreed verdict lands and the departure moves between the two positions.

        PRD 3.5: "Hop two follows from hop one and only bites when the agreed verdict is
        `UNCONTROLLABLE`: the claim leaves the controllable filter set and joins the
        uncontrollable one, so `cancelled_controllable_count` falls by 1 and
        `cancelled_uncontrollable_count` rises by 1, after which
        `metric_completed_departures` and `departure_ledger_total` are recomputed."

        Design: Difficulty/transitive_cascade/claim_finalize_five_hop_cascade_unwinds_issued_invoice
        """
        scenario, claim, _invoice, _scorecard = _build_settled_month_with_open_verdict(api)

        finalized = finalize_claim(api, claim["id"])

        assert_status(finalized, "FINALIZED")
        assert finalized["effective_classification"] == "UNCONTROLLABLE"

        cycle = read_cycle(api, scenario.cycle_id)
        assert cycle["cancelled_uncontrollable_count"] == 1
        assert cycle["cancelled_controllable_count"] == 0

    def test_the_stale_scorecard_voids_the_issued_bill_and_unwinds_the_settled_money(self, api):
        """Hops three through five reach the scorecard, the invoice and the agreement.

        PRD 3.5: "Hop five follows from hop four: for a voided invoice that had been
        `ISSUED`, the agreement's `settled_to_date_usd` is reduced by that invoice's
        `total_usd` and the month itself reverts from `SETTLED` back to `CLOSED`; for
        each voided `DRAFT` invoice, `open_invoice_count` falls by 1."

        Design: Difficulty/transitive_cascade/claim_finalize_five_hop_cascade_unwinds_issued_invoice
        """
        scenario, claim, invoice, scorecard = _build_settled_month_with_open_verdict(api)

        assert_money(
            read_agreement(api, scenario.agreement_id)["settled_to_date_usd"],
            SETTLED_INVOICE_TOTAL_USD,
            "settled to date before the cascade",
        )

        finalize_claim(api, claim["id"])

        stale = read_scorecard(api, scorecard["id"])
        assert_status(stale, "STALE")
        assert_percentage(
            stale["completion_factor_pct"],
            99.00,
            "the stale scorecard's published completion factor",
        )

        voided = read_invoice(api, invoice["id"])
        assert_status(voided, "VOIDED")
        assert voided["void_reason"] == "AUTO_SCORECARD_STALE"
        assert_money(voided["total_usd"], SETTLED_INVOICE_TOTAL_USD, "the voided invoice total")

        agreement = read_agreement(api, scenario.agreement_id)
        assert_money(agreement["settled_to_date_usd"], 0.00, "settled to date after the cascade")
        assert agreement["open_invoice_count"] == 0
        assert_status(read_cycle(api, scenario.cycle_id), "CLOSED")


def _build_two_tail_base(api):
    """Two line-qualified pilots holding two inducted tails at a one-for-one base."""
    return build_staffed_base(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="MSP",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=2,
        line_qualified_pilots=2,
        tail_numbers=["N701RG", "N702RG"],
    )


class TestPilotAttritionCascade:
    """Losing a line pilot recomputes the base and grounds the newest tail."""

    def test_losing_a_line_pilot_recomputes_both_shortfall_bases(self, api):
        """Hops one and two: the pilot leaves and the base's whole picture moves.

        PRD 3.2: "Hop two, caused by hop one, recomputes `headcount_shortfall`,
        `staffing_posture`, `pipeline_shortfall` and `allocatable_aircraft_count` — a
        base that was `STAFFED` can land in `SHORT` or `CRITICAL` in a single
        departure."

        Design: Difficulty/transitive_cascade/pilot_attrition_three_hop_grounds_newest_tail
        """
        scenario = _build_two_tail_base(api)
        leaving = scenario.pilots[1]

        response = api.attrite_pilot(
            leaving["id"],
            make_attrite_payload("MAINLINE"),
            headers=make_base_chief_pilot_headers(scenario.crew_base_id),
        )
        departed = validate_success(response)

        assert_status(departed, "ATTRITED_TO_MAINLINE")
        assert departed["attrition_destination"] == "MAINLINE"

        base = read_crew_base(api, scenario.crew_base_id)
        assert_staffing_picture(
            base,
            line_qualified=1,
            required_pilots=2,
            headcount_shortfall=1,
            pipeline_shortfall=1,
            posture="SHORT",
            allocatable_aircraft=1,
        )
        assert_status(read_pilot(api, scenario.pilots[0]["id"]), "LINE_QUALIFIED")

    def test_the_first_ranked_tail_is_the_one_grounded_and_stays_allocated(self, api):
        """Hop three grounds exactly the difference, taking the first-ranked candidate.

        PRD 3.3: "the candidate set is the tails at that base whose status is
        `IN_SERVICE`, ranked by `created_at` descending so that the most recently
        inducted tails are grounded first, with `tail_number` in ascending lexicographic
        order as the tie-break when two tails share a creation timestamp."

        PRD 3.3: "Each grounded tail moves `IN_SERVICE → GROUNDED_STAFFING`, has
        `grounded_reason` written as `STAFFING_SHORTFALL`, and has its `version`
        incremented."

        Design: Difficulty/transitive_cascade/pilot_attrition_three_hop_grounds_newest_tail
        """
        scenario = _build_two_tail_base(api)
        first_ranked, retained = grounding_candidate_order(scenario.aircraft)

        validate_success(
            api.attrite_pilot(
                scenario.pilots[1]["id"],
                make_attrite_payload("MAINLINE"),
                headers=make_base_chief_pilot_headers(scenario.crew_base_id),
            )
        )

        grounded = read_aircraft(api, first_ranked["id"])
        assert_status(grounded, "GROUNDED_STAFFING")
        assert grounded["grounded_reason"] == GROUNDED_REASON_STAFFING_SHORTFALL

        assert_status(read_aircraft(api, retained["id"]), "IN_SERVICE")
        assert_staffing_picture(read_crew_base(api, scenario.crew_base_id), assigned_aircraft=2)

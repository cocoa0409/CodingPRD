"""Compensating actions that restore conserved quantities exactly.

Voiding an issued bill returns settled money to its pre-issue figure, and
reinstating a cancelled leg rebalances the departure ledger without changing its
total.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_block_hours,
    assert_departure_ledger_identity,
    assert_is_null,
    assert_money,
    assert_settled_money,
    assert_status,
)
from test_helpers.factories import make_agreement_payload, make_completion_payload
from test_helpers.fixtures import (
    add_leg,
    build_open_cycle,
    cancel_leg,
    claim_for_leg,
    classify_claim,
    close_cycle,
    complete_leg,
    issue_invoice,
    raise_invoice,
    read_agreement,
    read_cycle,
    read_invoice,
    read_leg,
    reinstate_leg,
    scorecard_for_cycle,
)
from test_helpers.test_users import ADMIN_HEADERS, OPS_HEADERS

FINAL_INVOICE_TOTAL_USD = 334362.99
PUBLISHED_DEPARTURES = 10


def _build_settled_month(api):
    """A September month whose final bill has been issued and the money booked."""
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="ORD",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=4,
        line_qualified_pilots=1,
        tail_numbers=["N1501RG"],
        cycle_month="2026-09",
        published_departures=100,
    )
    plan = (
        ("SM5201", "DSM", "2026-09-02T08:00:00Z", "2026-09-02T09:12:00Z", 1.200, 1.155, "2026-09-02T09:26:00Z", 120),
        ("SM5202", "MSP", "2026-09-04T08:00:00Z", "2026-09-04T10:00:00Z", 2.000, 2.007, "2026-09-04T10:14:00Z", 100),
        ("SM5203", "SBN", "2026-09-06T08:00:00Z", "2026-09-06T08:42:00Z", 0.700, 0.616, "2026-09-06T08:40:00Z", 80),
    )
    for number, destination, departure, arrival, planned, actual, actual_arrival, bags in plan:
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
        flight_number="SM5204",
        origin="ORD",
        destination="GRR",
        scheduled_departure_utc="2026-09-08T08:00:00Z",
        scheduled_arrival_utc="2026-09-08T09:30:00Z",
        planned_block_hours=1.500,
    )
    cancel_leg(api, dropped["id"], cause_code="WEATHER")
    classify_claim(api, claim_for_leg(api, dropped["id"])["id"], "UNCONTROLLABLE")

    close_cycle(api, scenario.cycle_id)
    invoice = raise_invoice(api, scenario.cycle_id, "FINAL")
    invoice = issue_invoice(api, invoice["id"])
    return scenario, invoice


class TestSettledMoneyRestoredByVoid:
    """Settled money is the quantity the settle/unsettle loop conserves."""

    def test_voiding_the_issued_bill_returns_the_money_to_its_pre_issue_figure(self, api):
        """The subtraction is exact and the month reverts one step.

        PRD 3.8: "Voiding an `ISSUED` invoice unwinds the settlement precisely:
        `settled_to_date_usd` is reduced by that invoice's `total_usd`, returning the
        conserved figure to exactly the value it held before the issue rather than to a
        recomputed approximation of it, and the month reverts `SETTLED → CLOSED`."

        Design: Difficulty/compensating_invariant/settled_money_restored_by_invoice_void
        """
        scenario, invoice = _build_settled_month(api)

        assert_settled_money(
            read_agreement(api, scenario.agreement_id), FINAL_INVOICE_TOTAL_USD, 0
        )

        voided = validate_success(api.void_invoice(invoice["id"], headers=ADMIN_HEADERS))

        assert_status(voided, "VOIDED")
        assert voided["void_reason"] == "MANUAL", (
            "an explicit administrator void records MANUAL rather than either automatic cause"
        )
        assert_settled_money(read_agreement(api, scenario.agreement_id), 0.00, 0)
        assert_status(read_cycle(api, scenario.cycle_id), "CLOSED")

    def test_the_compensation_preserves_the_frozen_components_and_the_scorecard(self, api):
        """The void records history rather than erasing it.

        PRD 2.8: "Issuing a final invoice adds that invoice's `total_usd` to the figure;
        voiding an issued invoice subtracts exactly the same amount, returning the figure
        to its pre-issue value rather than to an approximation of it."

        Design: Difficulty/compensating_invariant/settled_money_restored_by_invoice_void
        """
        scenario, invoice = _build_settled_month(api)

        validate_success(api.void_invoice(invoice["id"], headers=ADMIN_HEADERS))

        after = read_invoice(api, invoice["id"])
        assert_money(after["total_usd"], FINAL_INVOICE_TOTAL_USD, "invoice total")
        assert_money(after["fixed_component_usd"], 312000.00, "fixed component")
        assert_money(after["variable_component_usd"], 6440.94, "variable component")
        assert_money(after["incentive_component_usd"], 15922.05, "incentive component")
        assert after["issued_final_at"] is not None, (
            "the issue instant survives the void as the audit trail of what happened"
        )

        assert_status(scorecard_for_cycle(api, scenario.cycle_id), "PUBLISHED")


def _build_month_with_one_flown_and_one_scheduled_leg(api):
    """An open month of ten bought departures, one flown and one still to fly."""
    scenario = build_open_cycle(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="SBN",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=1,
        line_qualified_pilots=1,
        tail_numbers=["N1601RG"],
        cycle_month="2026-09",
        published_departures=PUBLISHED_DEPARTURES,
    )
    flown = add_leg(
        api,
        scenario,
        flight_number="SM5301",
        origin="SBN",
        destination="ORD",
        scheduled_departure_utc="2026-09-03T08:00:00Z",
        scheduled_arrival_utc="2026-09-03T09:00:00Z",
        planned_block_hours=1.000,
    )
    pending = add_leg(
        api,
        scenario,
        flight_number="SM5302",
        origin="SBN",
        destination="DTW",
        scheduled_departure_utc="2026-09-05T08:00:00Z",
        scheduled_arrival_utc="2026-09-05T09:00:00Z",
        planned_block_hours=1.000,
    )
    complete_leg(
        api,
        flown["id"],
        make_completion_payload(
            actual_block_hours=1.000,
            actual_arrival_utc="2026-09-03T09:05:00Z",
            enplaned_bags=50,
            mishandled_bags=0,
        ),
    )
    return scenario, flown, pending


class TestDepartureLedgerRestoredByReinstate:
    """The ledger total never moves; the cancellation only shifts a departure between buckets."""

    def test_the_ledger_total_holds_while_the_departure_changes_buckets(self, api):
        """Cancelling and reinstating rebalance the same ten bought departures.

        PRD 2.8: "A cancellation therefore moves one departure from the completed
        position into a cancellation position without changing the total, and a
        reinstatement moves it back to the exact value it held before the cancellation."

        Design: Difficulty/compensating_invariant/departure_ledger_restored_by_leg_reinstate
        """
        scenario, _flown, pending = _build_month_with_one_flown_and_one_scheduled_leg(api)

        before = read_cycle(api, scenario.cycle_id)
        assert_departure_ledger_identity(before)
        assert before["departure_ledger_total"] == PUBLISHED_DEPARTURES

        cancel_leg(api, pending["id"], cause_code="CREW_UNAVAILABLE")
        between = read_cycle(api, scenario.cycle_id)
        assert between["cancelled_controllable_count"] == 1
        assert between["metric_completed_departures"] == 9
        assert between["departure_ledger_total"] == PUBLISHED_DEPARTURES
        assert between["open_leg_count"] == 0
        assert_departure_ledger_identity(between)

        reinstated = reinstate_leg(api, pending["id"])
        assert_status(reinstated, "SCHEDULED")
        assert reinstated["reinstate_count"] == 1
        assert_is_null(reinstated, "cancel_cause_code")

        after = read_cycle(api, scenario.cycle_id)
        assert after["cancelled_controllable_count"] == 0
        assert after["metric_completed_departures"] == PUBLISHED_DEPARTURES
        assert after["departure_ledger_total"] == PUBLISHED_DEPARTURES
        assert after["open_leg_count"] == 1
        assert_departure_ledger_identity(after)

    def test_the_voided_claim_drops_out_of_the_counter_and_the_flown_leg_is_untouched(self, api):
        """The compensation reaches the claim and nothing else.

        PRD 3.4: "On success `reinstate_count` rises by 1, `cancel_cause_code` is cleared
        to null, the claim is voided, `open_leg_count` rises by 1, and
        `cancelled_controllable_count` falls by 1 so that
        `metric_completed_departures` and `departure_ledger_total` return to their exact
        pre-cancellation values."

        Design: Difficulty/compensating_invariant/departure_ledger_restored_by_leg_reinstate
        """
        scenario, flown, pending = _build_month_with_one_flown_and_one_scheduled_leg(api)

        cancel_leg(api, pending["id"], cause_code="CREW_UNAVAILABLE")
        claim = claim_for_leg(api, pending["id"])
        assert_status(claim, "OPEN")

        reinstate_leg(api, pending["id"])

        assert_status(
            validate_success(api.get_cancellation_claim(claim["id"], headers=OPS_HEADERS)),
            "VOIDED",
        )
        assert_status(read_leg(api, flown["id"]), "COMPLETED")
        assert_block_hours(
            read_cycle(api, scenario.cycle_id)["credited_block_hours"],
            1.000,
            "credited block hours",
        )

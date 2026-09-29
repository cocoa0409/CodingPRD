"""Requests that break two rules at once, where only the earlier one may surface.

A final bill against a month that is both open and unreconciled reports the state
failure; a leg on a tail that is both grounded and foreign reports the safety
failure.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_AIRCRAFT_NOT_AVAILABLE,
    ERR_CROSS_AGREEMENT_REFERENCE,
    ERR_INVALID_STATE,
    ERR_PASSTHROUGH_UNRECONCILED,
)
from test_helpers.assertions import assert_status, assert_version
from test_helpers.factories import (
    make_agreement_payload,
    make_attrite_payload,
    make_flight_leg_payload,
    make_invoice_payload,
)
from test_helpers.fixtures import (
    advance_pilot_to,
    build_active_agreement,
    build_staffed_base,
    create_cycle,
    file_pass_through_actual,
    hire_pilot,
    open_cycle,
    open_pass_through,
    read_aircraft,
    read_cycle,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    SCHEDULER_HEADERS,
    make_base_chief_pilot_headers,
)


def _build_open_month_with_unreconciled_fuel(api):
    """An open month carrying one fuel claim whose actual has been filed but not judged."""
    scenario = build_active_agreement(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="OMA",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=1,
    )
    cycle = create_cycle(api, scenario.agreement_id, cycle_month="2026-09", published_departures=5)
    cycle = open_cycle(api, cycle["id"])

    claim = open_pass_through(api, cycle["id"], category="FUEL", estimated_amount_usd=4000.00)
    file_pass_through_actual(api, claim["id"], 4300.00, supporting_doc_ref="FUEL-OMA-01")
    return cycle, claim


class TestFinalInvoiceStateBeatsFiscal:
    """The month's state is checked before the pass-through ledger's readiness."""

    def test_the_open_month_is_reported_rather_than_the_unreconciled_pass_through(self, api):
        """Both rules are broken and only the state rejection surfaces.

        PRD 3.8: "A `PROVISIONAL` invoice is the cash-flow bill raised while the month
        is still `OPEN`; a `FINAL` invoice is the settlement bill and requires the month
        to be `CLOSED`, a request for one against a month that is still `OPEN` being
        refused with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/final_invoice_on_open_cycle_state_beats_fiscal
        """
        cycle, _claim = _build_open_month_with_unreconciled_fuel(api)
        standing_version = read_cycle(api, cycle["id"])["version"]

        response = api.create_invoice(
            cycle["id"],
            make_invoice_payload("FINAL", standing_version),
            headers=ADMIN_HEADERS,
        )
        error_id = validate_error(response, ERR_INVALID_STATE, 409)["error_id"]
        assert error_id != ERR_PASSTHROUGH_UNRECONCILED, (
            "the lower-priority fiscal rule is also broken but must not surface"
        )

    def test_the_refused_request_creates_no_invoice_and_moves_no_version(self, api):
        """The month, its version and the filed claim are all left where they were.

        PRD 3.8: "A `FINAL` invoice additionally requires every pass-through claim of the
        month to have reached a terminal status, either `RECONCILED` or `REJECTED`; while
        any claim is still `SUBMITTED` or `ACTUAL_SUBMITTED` the request is refused with
        `ERR_PASSTHROUGH_UNRECONCILED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/final_invoice_on_open_cycle_state_beats_fiscal
        """
        cycle, claim = _build_open_month_with_unreconciled_fuel(api)
        standing_version = read_cycle(api, cycle["id"])["version"]

        validate_error(
            api.create_invoice(
                cycle["id"],
                make_invoice_payload("FINAL", standing_version),
                headers=ADMIN_HEADERS,
            ),
            ERR_INVALID_STATE,
            409,
        )

        invoices, _meta = validate_paginated(
            api.list_invoices(headers=ADMIN_HEADERS, params={"cycle_id": cycle["id"]})
        )
        assert invoices == [], "a refused invoice request should create no invoice row"

        after = read_cycle(api, cycle["id"])
        assert_status(after, "OPEN")
        assert_version(after, standing_version)
        assert_status(
            validate_success(api.get_pass_through_claim(claim["id"], headers=ADMIN_HEADERS)),
            "ACTUAL_SUBMITTED",
        )


def _build_grounded_foreign_tail(api):
    """A grounded tail belonging to one contract and an open month under another."""
    other = build_staffed_base(
        api,
        agreement_payload=make_agreement_payload(
            regional_carrier_name="Other Regional",
            fixed_monthly_fee_usd=200000.00,
            block_hour_rate_usd=1400.00,
            departure_rate_usd=300.00,
            aircraft_ownership_fee_usd=55000.00,
            incentive_pool_cap_usd=80000.00,
            penalty_cap_usd=100000.00,
            term_end_date="2029-06-30",
        ),
        station_code="PIT",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=1,
        line_qualified_pilots=1,
        tail_numbers=["N801RG"],
    )
    validate_success(
        api.attrite_pilot(
            other.pilots[0]["id"],
            make_attrite_payload("MAINLINE"),
            headers=make_base_chief_pilot_headers(other.crew_base_id),
        )
    )
    foreign_tail = read_aircraft(api, other.aircraft[0]["id"])

    mine = build_active_agreement(
        api,
        agreement_payload=make_agreement_payload(),
        station_code="ORD",
        pilots_required_per_aircraft=1,
        aircraft_allocation_cap=2,
    )
    captain = hire_pilot(api, mine.crew_base_id, "EMP-9001", hire_class_date="2026-05-01")
    advance_pilot_to(api, captain["id"], mine.crew_base_id, "IN_TRAINING")
    captain = advance_pilot_to(api, captain["id"], mine.crew_base_id, "LINE_QUALIFIED")

    cycle = create_cycle(api, mine.agreement_id, cycle_month="2026-09", published_departures=5)
    cycle = open_cycle(api, cycle["id"])
    return other, foreign_tail, mine, captain, cycle


class TestGroundedTailSafetyBeatsReferential:
    """Tail availability is checked before the tail's contract membership."""

    def test_the_grounded_tail_is_reported_rather_than_the_cross_contract_reference(self, api):
        """Both rules are broken and only the availability rejection surfaces.

        PRD 3.4: "The tail must be `IN_SERVICE`: a tail in `PENDING_INDUCTION`,
        `GROUNDED_STAFFING`, `TRANSITION_PENDING`, `TRANSITIONED` or `WITHDRAWN` may not
        be scheduled, and the refusal is `ERR_AIRCRAFT_NOT_AVAILABLE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/grounded_cross_agreement_tail_safety_beats_referential
        """
        _other, foreign_tail, _mine, captain, cycle = _build_grounded_foreign_tail(api)

        response = api.create_flight_leg(
            make_flight_leg_payload(
                cycle["id"],
                foreign_tail["id"],
                captain["id"],
                flight_number="SM4601",
                origin="ORD",
                destination="PIT",
                scheduled_departure_utc="2026-09-10T08:00:00Z",
                scheduled_arrival_utc="2026-09-10T09:30:00Z",
                planned_block_hours=1.500,
            ),
            headers=SCHEDULER_HEADERS,
        )
        error_id = validate_error(response, ERR_AIRCRAFT_NOT_AVAILABLE, 409)["error_id"]
        assert error_id != ERR_CROSS_AGREEMENT_REFERENCE, (
            "the tail is also foreign to this contract, but the safety rule wins"
        )

    def test_the_refused_leg_leaves_the_tail_grounded_and_the_month_empty(self, api):
        """No leg is published and the foreign tail keeps its contract and its status.

        PRD 3.4: "Both the tail and the captain must belong to the same agreement as the
        cycle — the tail's `agreement_id` and the crew base of the captain must both
        resolve to the cycle's `agreement_id` — and a mismatch is
        `ERR_CROSS_AGREEMENT_REFERENCE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/grounded_cross_agreement_tail_safety_beats_referential
        """
        other, foreign_tail, _mine, captain, cycle = _build_grounded_foreign_tail(api)

        validate_error(
            api.create_flight_leg(
                make_flight_leg_payload(
                    cycle["id"],
                    foreign_tail["id"],
                    captain["id"],
                    flight_number="SM4601",
                    origin="ORD",
                    destination="PIT",
                    scheduled_departure_utc="2026-09-10T08:00:00Z",
                    scheduled_arrival_utc="2026-09-10T09:30:00Z",
                    planned_block_hours=1.500,
                ),
                headers=SCHEDULER_HEADERS,
            ),
            ERR_AIRCRAFT_NOT_AVAILABLE,
            409,
        )

        standing_tail = read_aircraft(api, foreign_tail["id"])
        assert_status(standing_tail, "GROUNDED_STAFFING")
        assert standing_tail["agreement_id"] == other.agreement_id
        assert read_cycle(api, cycle["id"])["open_leg_count"] == 0

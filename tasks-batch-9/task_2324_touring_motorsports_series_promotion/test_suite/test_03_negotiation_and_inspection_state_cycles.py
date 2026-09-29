"""The two bounded cycles in the domain.

A booking alternates between ``TERMS_PROPOSED`` and ``COUNTERED`` while the round
budget lasts, and a vehicle entry sits on a self-loop at ``TECH_HELD`` while the
attempt budget lasts. Both cycles are exercised here from the same state until
their bound bites.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BookingState,
    InspectionResult,
    ReadinessPosture,
    ReadinessVariant,
    TechStatus,
    TermsSource,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as F
from test_helpers import fixtures as helpers


def _read_booking(
    api: ApiClient, booking_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    """The booking row as the server currently holds it."""
    return get_success_data(api.get_venue_booking(booking_id, headers=headers))


class TestBookingNegotiationCycle:
    """Countering and revising alternate the booking until the round cap bites."""

    def test_counter_and_revision_alternate_the_two_negotiation_states(
        self,
        api: ApiClient,
        promoter_headers: Dict[str, str],
        venue_manager_headers: Callable[[str], Dict[str, str]],
    ) -> None:
        """PRD §3.1: "Countering sets `terms_source` to `VENUE`, records the caller
        in `last_counter_by_user_id`, increments `negotiation_round` by one and
        increments the booking's `version` by one." "The promoter answers a counter
        with a revision, moving the booking from `COUNTERED` back to
        `TERMS_PROPOSED`." "It overwrites the terms fields, sets `terms_source` back
        to `PROMOTER` and increments the booking's `version`."

        Design: Difficulty/non_linear_state_machine/booking_negotiation_cycles_until_the_round_cap_bites
        """
        state = helpers.proposed_booking(api)
        booking_id = state["booking_id"]
        venue_id = state["venue_id"]
        manager = venue_manager_headers(venue_id)
        opening = state["booking"]

        countered = validate_success(
            api.counter_venue_booking(
                booking_id,
                F.make_counter_terms_payload(
                    rental_base_cents=3400000,
                    revenue_share_pct=0.14,
                    per_ticket_facility_fee_cents=400,
                    note="Building counters the opening terms.",
                ),
                headers=manager,
            ),
            expected_status=200,
        )
        assert countered["state"] == BookingState.COUNTERED
        assert countered["terms_source"] == TermsSource.VENUE
        assert countered["last_counter_by_user_id"] == venue_id
        assert countered["negotiation_round"] == opening["negotiation_round"] + 1
        assert countered["version"] == opening["version"] + 1
        assert countered["rental_base_cents"] == 3400000
        assert countered["per_ticket_facility_fee_cents"] == 400
        assert countered["revenue_share_pct"] == pytest.approx(0.14, abs=0.01)

        revised = validate_success(
            api.revise_venue_booking(
                booking_id,
                F.make_revise_terms_payload(
                    rental_base_cents=3100000,
                    revenue_share_pct=0.13,
                    per_ticket_facility_fee_cents=375,
                    note="Promoter answers the counter.",
                ),
                headers=promoter_headers,
            ),
            expected_status=200,
        )
        assert revised["state"] == BookingState.TERMS_PROPOSED
        assert revised["terms_source"] == TermsSource.PROMOTER
        assert revised["negotiation_round"] == countered["negotiation_round"]
        assert revised["version"] == countered["version"] + 1
        assert revised["rental_base_cents"] == 3100000
        assert revised["per_ticket_facility_fee_cents"] == 375
        assert revised["revenue_share_pct"] == pytest.approx(0.13, abs=0.01)

        # The same state accepts the same act a second time: the cycle re-enters
        # COUNTERED and only the counter advances the round.
        recountered = validate_success(
            api.counter_venue_booking(
                booking_id,
                F.make_counter_terms_payload(
                    rental_base_cents=3200000,
                    revenue_share_pct=0.135,
                    per_ticket_facility_fee_cents=390,
                    note="Building counters the revision.",
                ),
                headers=manager,
            ),
            expected_status=200,
        )
        assert recountered["state"] == BookingState.COUNTERED
        assert recountered["terms_source"] == TermsSource.VENUE
        assert recountered["negotiation_round"] == revised["negotiation_round"] + 1
        assert recountered["negotiation_round"] == 3
        assert recountered["version"] == revised["version"] + 1
        assert recountered["rental_base_cents"] == 3200000

    def test_countering_a_saturated_round_budget_is_rejected_without_a_trace(
        self,
        api: ApiClient,
        promoter_headers: Dict[str, str],
        venue_manager_headers: Callable[[str], Dict[str, str]],
    ) -> None:
        """PRD §3.1: "A counter is admissible only while `negotiation_round` is still
        below 3; the fourth attempt to counter is rejected with
        `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/booking_negotiation_cycles_until_the_round_cap_bites
        """
        state = helpers.proposed_booking(api)
        booking_id = state["booking_id"]
        manager = venue_manager_headers(state["venue_id"])

        validate_success(
            api.counter_venue_booking(
                booking_id,
                F.make_counter_terms_payload(
                    rental_base_cents=3400000,
                    revenue_share_pct=0.14,
                    per_ticket_facility_fee_cents=400,
                    note="Building counters the opening terms.",
                ),
                headers=manager,
            ),
            expected_status=200,
        )
        validate_success(
            api.revise_venue_booking(
                booking_id,
                F.make_revise_terms_payload(
                    rental_base_cents=3100000,
                    revenue_share_pct=0.13,
                    per_ticket_facility_fee_cents=375,
                    note="Promoter answers the counter.",
                ),
                headers=promoter_headers,
            ),
            expected_status=200,
        )
        saturated = validate_success(
            api.counter_venue_booking(
                booking_id,
                F.make_counter_terms_payload(
                    rental_base_cents=3200000,
                    revenue_share_pct=0.135,
                    per_ticket_facility_fee_cents=390,
                    note="Building counters the revision.",
                ),
                headers=manager,
            ),
            expected_status=200,
        )
        assert saturated["negotiation_round"] == 3

        rejected = api.counter_venue_booking(
            booking_id,
            F.make_counter_terms_payload(
                rental_base_cents=3250000,
                revenue_share_pct=0.132,
                per_ticket_facility_fee_cents=385,
                note="One counter too many.",
            ),
            headers=manager,
        )
        validate_error(rejected, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED)

        untouched = _read_booking(api, booking_id, promoter_headers)
        assert untouched["state"] == BookingState.COUNTERED
        assert untouched["negotiation_round"] == 3
        assert untouched["terms_source"] == TermsSource.VENUE
        assert untouched["rental_base_cents"] == 3200000
        assert untouched["per_ticket_facility_fee_cents"] == 390
        assert untouched["version"] == saturated["version"]


class TestTechInspectionHoldCycle:
    """A failure holds the entry, holds again, and finally exhausts the budget."""

    def test_every_failed_attempt_holds_the_entry_and_restricts_the_stop(
        self,
        api: ApiClient,
        safety_inspector_headers: Dict[str, str],
    ) -> None:
        """PRD §3.3: "A `FAILED` result moves the entry to `TECH_HELD`, increments
        both `tech_attempt_count` and `failed_attempt_count`, re-scores readiness
        with the 25-point-per-failure penalty, and — uniquely among the three
        branches — reaches across to the stop: the stop's posture is recomputed and
        becomes `RESTRICTED` while any live entry of the stop sits at `TECH_HELD`,
        which in turn drives a stop that was `ON_SALE` to `SALES_HALTED`." "A further
        attempt with `FAILED` while already `TECH_HELD` leaves the entry at
        `TECH_HELD`, appends the attempt, increments `failed_attempt_count` and
        re-scores readiness — and since the third failure exhausts the attempt
        budget, no fourth attempt of any kind is admissible." "`attempt_no` is a
        1-based index computed at insert time as the entry's `tech_attempt_count`
        plus one."

        Design: Difficulty/non_linear_state_machine/tech_inspection_self_loops_on_failure_then_falls_out_to_tech_held
        """
        state = helpers.stop_ready_for_sale(api)
        stop_id = state["stop_id"]
        entry_id = helpers.staged_entry(api, stop_id)["entry_id"]

        first = validate_success(
            api.create_tech_inspection(
                entry_id,
                F.make_tech_inspection_payload(
                    result="FAILED",
                    defect_severity="MAJOR",
                    notes="Fuel cell strap fails the first attempt.",
                ),
                headers=safety_inspector_headers,
            ),
            expected_status=201,
        )
        assert first["attempt_no"] == 1
        assert first["result"] == InspectionResult.FAILED
        assert first["inspected_by_user_id"] == safety_inspector_headers["X-User-ID"]

        held = helpers.fetch_entry(api, entry_id)
        assert held["tech_status"] == TechStatus.TECH_HELD
        assert held["tech_attempt_count"] == 1
        assert held["failed_attempt_count"] == 1

        # The failure branch is the only one that reaches across to the stop.
        assert (
            helpers.fetch_stop(api, stop_id)["readiness_posture"]
            == ReadinessPosture.RESTRICTED
        )

        # The self-loop: two further failures leave the entry exactly where it is.
        for attempt_no in (2, 3):
            appended = validate_success(
                api.create_tech_inspection(
                    entry_id,
                    F.make_tech_inspection_payload(
                        result="FAILED",
                        defect_severity="MAJOR",
                        notes=f"Still failing on attempt {attempt_no}.",
                    ),
                    headers=safety_inspector_headers,
                ),
                expected_status=201,
            )
            assert appended["attempt_no"] == attempt_no
            looped = helpers.fetch_entry(api, entry_id)
            assert looped["tech_status"] == TechStatus.TECH_HELD
            assert looped["tech_attempt_count"] == attempt_no
            assert looped["failed_attempt_count"] == attempt_no

    @pytest.mark.parametrize("result", ["PASSED", "CONDITIONAL", "FAILED"])
    def test_a_fourth_attempt_of_any_kind_is_rejected_on_an_exhausted_entry(
        self,
        api: ApiClient,
        safety_inspector_headers: Dict[str, str],
        result: str,
    ) -> None:
        """PRD §3.3: "An attempt is admissible only while `tech_attempt_count` is
        still below 3; once three attempts exist, any further filing is rejected
        with `ERR_TECH_ATTEMPTS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/tech_inspection_self_loops_on_failure_then_falls_out_to_tech_held
        """
        state = helpers.stop_ready_for_sale(api)
        entry_id = helpers.staged_entry(api, state["stop_id"])["entry_id"]
        for attempt_no in (1, 2, 3):
            helpers.file_tech_inspection(
                api,
                entry_id,
                result="FAILED",
                defect_severity="MAJOR",
                notes=f"Attempt {attempt_no} fails.",
            )
        exhausted = helpers.fetch_entry(api, entry_id)
        assert exhausted["tech_attempt_count"] == 3

        rejected = api.create_tech_inspection(
            entry_id,
            F.make_tech_inspection_payload(
                result=result,
                defect_severity="NONE" if result == "PASSED" else "MINOR",
                notes="A fourth filing after the budget is spent.",
            ),
            headers=safety_inspector_headers,
        )
        validate_error(rejected, ApiErrorId.ERR_TECH_ATTEMPTS_EXHAUSTED)

        rows, meta = validate_paginated(
            api.list_tech_inspections(entry_id, headers=safety_inspector_headers)
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3
        assert sorted(row["attempt_no"] for row in rows) == [1, 2, 3]

        untouched = helpers.fetch_entry(api, entry_id)
        assert untouched["tech_status"] == TechStatus.TECH_HELD
        assert untouched["tech_attempt_count"] == 3
        assert untouched["failed_attempt_count"] == 3
        assert untouched["version"] == exhausted["version"]

    @pytest.mark.parametrize(
        "result,expected_tech_status",
        [
            ("PASSED", TechStatus.TECH_CLEARED),
            ("CONDITIONAL", TechStatus.TECH_CONDITIONAL),
        ],
    )
    def test_an_attempt_after_the_hold_leaves_the_loop_and_lifts_the_restriction(
        self,
        api: ApiClient,
        safety_inspector_headers: Dict[str, str],
        result: str,
        expected_tech_status: str,
    ) -> None:
        """PRD §3.3: "From `TECH_HELD`, a further attempt with `PASSED` moves it to
        `TECH_CLEARED` and a further attempt with `CONDITIONAL` moves it to
        `TECH_CONDITIONAL`; in both cases the re-inspection is appended as another
        attempt, readiness is re-scored under `POST_STAGING` with the earlier failure
        still counted in `failed_attempt_count`, and the stop's posture is
        recomputed, which may return it to `OPEN` once no live entry of the stop is
        held."

        Design: Difficulty/non_linear_state_machine/tech_inspection_self_loops_on_failure_then_falls_out_to_tech_held
        """
        state = helpers.stop_ready_for_sale(api)
        stop_id = state["stop_id"]
        entry_id = helpers.staged_entry(api, stop_id)["entry_id"]
        helpers.file_tech_inspection(
            api,
            entry_id,
            result="FAILED",
            defect_severity="MAJOR",
            notes="First attempt fails and holds the entry.",
        )

        reinspection = validate_success(
            api.create_tech_inspection(
                entry_id,
                F.make_tech_inspection_payload(
                    result=result,
                    defect_severity="NONE" if result == "PASSED" else "MINOR",
                    notes="Re-inspection after the hold.",
                ),
                headers=safety_inspector_headers,
            ),
            expected_status=201,
        )
        assert reinspection["attempt_no"] == 2

        cleared = helpers.fetch_entry(api, entry_id)
        assert cleared["tech_status"] == expected_tech_status
        assert cleared["tech_attempt_count"] == 2
        assert cleared["failed_attempt_count"] == 1
        assert cleared["readiness_variant"] == ReadinessVariant.POST_STAGING

        assert (
            helpers.fetch_stop(api, stop_id)["readiness_posture"]
            == ReadinessPosture.OPEN
        )

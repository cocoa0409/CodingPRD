"""Threshold boundaries: the admitted side and the refused side of each pinned figure.

Every group below exercises one contractual comparison exactly at its boundary and once
one unit past it, so an inclusive test cannot pass as an exclusive one.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    complete_leg,
    complete_leg_payload,
    create_aircraft,
    create_flight_leg_payload,
    create_substitution_payload,
    dispatch_leg,
    fly_leg,
    schedule_leg,
    setup_active_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["lessor_ops_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
TECH = TEST_USERS["maintenance_controller_headers"]

# A term starting 2026-09-11 covers 20 of September's 30 days: 5 x 20 / 30 = 3.3333 hours.
PRORATED_MGH_HOURS = 3.3333
PRORATED_BASE_CHARGE_CENTS = 1_599_984

# 795 scheduled block minutes plus the 105-minute allowance is 900 duty minutes.
LONG_LEGS = [
    ("2026-09-10T00:00:00Z", "2026-09-10T13:15:00Z", "KJFK"),
    ("2026-09-11T00:00:00Z", "2026-09-11T13:15:00Z", "KORD"),
    ("2026-09-12T00:00:00Z", "2026-09-12T13:15:00Z", "KIAD"),
]


def _setup_two_dispatched_revenue_legs(api):
    """One revenue leg airborne on a 60-minute plan and one on a 59-minute plan."""
    scenario = setup_active_lease(api)
    at_floor = schedule_leg(
        api,
        scenario,
        "2026-09-08T06:00:00Z",
        "2026-09-08T07:00:00Z",
        dest_icao="EIDW",
    )
    dispatch_leg(api, at_floor["id"], "2026-09-08T06:00:00Z")
    under_floor = schedule_leg(
        api,
        scenario,
        "2026-09-09T06:00:00Z",
        "2026-09-09T06:59:00Z",
        dest_icao="EGPH",
    )
    dispatch_leg(api, under_floor["id"], "2026-09-09T06:00:00Z")
    return scenario, at_floor, under_floor


def _setup_three_long_legs(api):
    """Three scheduled legs of 795 block minutes each, all on the same crew pair."""
    scenario = setup_active_lease(api)
    for scheduled_out, scheduled_in, dest in LONG_LEGS:
        leg = schedule_leg(api, scenario, scheduled_out, scheduled_in, dest_icao=dest)
        assert leg["scheduled_block_minutes"] == 795, (
            "each accumulating leg must carry 795 scheduled block minutes, got "
            f"{leg['scheduled_block_minutes']}"
        )
    return scenario


def _candidate_long_leg(api, scenario, scheduled_in: str):
    """Offer a candidate leg in the 2026-09-13 slot ending at ``scheduled_in``."""
    return api.create_flight_leg(
        create_flight_leg_payload(
            scenario["lease"]["id"],
            scenario["aircraft"]["id"],
            scenario["captain"]["id"],
            scenario["first_officer"]["id"],
            scheduled_out="2026-09-13T00:00:00Z",
            scheduled_in=scheduled_in,
            dest_icao="KBOS",
        ),
        OPS,
    )


def _register_spare(api, tail_number: str, hours_since_last_check: float, **overrides):
    return create_aircraft(
        api,
        tail_number=tail_number,
        hours_since_last_check=hours_since_last_check,
        **overrides,
    )


def _request_server_selected_substitution(api, scenario, lease_version: int):
    return api.create_substitution(
        create_substitution_payload(
            scenario["lease"]["id"],
            scenario["aircraft"]["id"],
            lease_version,
            reason="SCHEDULED_MAINTENANCE",
            effective_from="2026-09-15T00:00:00Z",
        ),
        OPS,
    )


class TestProratedGuaranteeBoundary:
    def test_credited_hours_exactly_on_the_prorated_guarantee_yields_neither_side(self, api):
        """PRD §3.8: `mgh_effective_hours` is the lease's `min_guaranteed_block_hours_per_month` multiplied by the number of covered days and divided by the number of calendar days in `period_month`, rounded half up to four decimal places.
        PRD §3.8: A day of `period_month` is covered when it falls on or after `term_start_date` and on or before `term_end_date`, both bounds inclusive.
        PRD §3.8: Each included leg's minute contribution is divided by 60 and rounded half up to four decimal places *first*; `credited_hours` is the sum of those rounded per-leg figures.
        PRD §3.8: Otherwise `shortfall_hours` is 0 and `overrun_hours` is `credited_hours` less `mgh_effective_hours`, rounded half up to four decimal places — so a month landing exactly on the guarantee produces neither.
        PRD §3.8: `base_charge_cents` is `mgh_effective_hours` multiplied by the lease's `block_hour_rate_usd_cents`, rounded half up to whole cents.
        PRD §3.8: `gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.
        PRD §3.8: If no accepted report exists for the month, `reliability_penalty_cents` is 0 and no penalty applies.

        Design: Difficulty/boundary_precision_check/prorated_guarantee_equals_credited_hours_exactly_at_four_decimals
        """
        scenario = setup_active_lease(
            api, lease_overrides={"term_start_date": "2026-09-11"}
        )
        leg = fly_leg(
            api,
            scenario,
            "2026-09-15T06:00:00Z",
            "2026-09-15T09:20:00Z",
            technical_delay_minutes=0,
        )
        assert leg["block_minutes"] == 200, (
            f"expected a 200-minute block time, got {leg['block_minutes']}"
        )

        period = validate_success(
            api.close_utilization_period(scenario["period"]["id"], BILLING)
        )

        assert period["period_month"] == "2026-09", (
            f"expected the closed month to be 2026-09, got {period['period_month']}"
        )
        assert period["mgh_effective_hours"] == pytest.approx(
            PRORATED_MGH_HOURS, abs=0.0001
        ), f"expected mgh_effective_hours 3.3333, got {period['mgh_effective_hours']}"
        assert period["credited_block_minutes"] == 200, (
            f"expected credited_block_minutes 200, got {period['credited_block_minutes']}"
        )
        assert period["credited_hours"] == pytest.approx(
            PRORATED_MGH_HOURS, abs=0.0001
        ), f"expected credited_hours 3.3333, got {period['credited_hours']}"
        assert period["shortfall_hours"] == pytest.approx(0.0, abs=0.0001), (
            "credited hours equal to the guarantee must produce no shortfall, got "
            f"{period['shortfall_hours']}"
        )
        assert period["lessor_attributable_shortfall_hours"] == pytest.approx(
            0.0, abs=0.0001
        ), (
            "expected lessor_attributable_shortfall_hours 0.0000, got "
            f"{period['lessor_attributable_shortfall_hours']}"
        )
        assert period["overrun_hours"] == pytest.approx(0.0, abs=0.0001), (
            "credited hours equal to the guarantee must produce no overrun, got "
            f"{period['overrun_hours']}"
        )
        assert period["base_charge_cents"] == PRORATED_BASE_CHARGE_CENTS, (
            f"expected base_charge_cents {PRORATED_BASE_CHARGE_CENTS}, got "
            f"{period['base_charge_cents']}"
        )
        assert period["shortfall_credit_cents"] == 0, (
            f"expected shortfall_credit_cents 0, got {period['shortfall_credit_cents']}"
        )
        assert period["overrun_charge_cents"] == 0, (
            f"expected overrun_charge_cents 0, got {period['overrun_charge_cents']}"
        )
        assert period["gross_charge_cents"] == PRORATED_BASE_CHARGE_CENTS, (
            f"expected gross_charge_cents {PRORATED_BASE_CHARGE_CENTS}, got "
            f"{period['gross_charge_cents']}"
        )
        assert period["final_charge_cents"] == PRORATED_BASE_CHARGE_CENTS, (
            f"expected final_charge_cents {PRORATED_BASE_CHARGE_CENTS}, got "
            f"{period['final_charge_cents']}"
        )

    def test_credited_hours_one_minute_below_the_prorated_guarantee_takes_the_shortfall_branch(
        self, api
    ):
        """PRD §3.8: When `credited_hours` is strictly less than `mgh_effective_hours`, `shortfall_hours` is their difference rounded half up to four decimal places and `overrun_hours` is 0.
        PRD §3.8: Separately, the lessor-cancelled hours of the month are the sum of `scheduled_block_minutes` over every leg of the month whose `status` is `CANCELLED_LESSOR`, divided by 60 and rounded half up to four decimal places; `lessor_attributable_shortfall_hours` is the lesser of `shortfall_hours` and that figure.
        PRD §3.8: `shortfall_credit_cents` is `lessor_attributable_shortfall_hours` multiplied by that same rate and by the lease's `shortfall_credit_pct`, rounded half up to whole cents.
        PRD §3.8: `credited_block_minutes` is separately the plain sum of the same per-leg minute contributions, in whole minutes.

        Design: Difficulty/boundary_precision_check/prorated_guarantee_equals_credited_hours_exactly_at_four_decimals
        """
        scenario = setup_active_lease(
            api, lease_overrides={"term_start_date": "2026-09-11"}
        )
        leg = fly_leg(
            api,
            scenario,
            "2026-09-15T06:00:00Z",
            "2026-09-15T09:19:00Z",
            technical_delay_minutes=0,
        )
        assert leg["block_minutes"] == 199, (
            f"expected a 199-minute block time, got {leg['block_minutes']}"
        )

        period = validate_success(
            api.close_utilization_period(scenario["period"]["id"], BILLING)
        )

        assert period["mgh_effective_hours"] == pytest.approx(
            PRORATED_MGH_HOURS, abs=0.0001
        ), f"expected mgh_effective_hours 3.3333, got {period['mgh_effective_hours']}"
        assert period["credited_block_minutes"] == 199, (
            f"expected credited_block_minutes 199, got {period['credited_block_minutes']}"
        )
        assert period["credited_hours"] == pytest.approx(3.3167, abs=0.0001), (
            f"expected credited_hours 3.3167, got {period['credited_hours']}"
        )
        assert period["shortfall_hours"] == pytest.approx(0.0166, abs=0.0001), (
            "credited hours one minute below the guarantee must raise a 0.0166-hour "
            f"shortfall, got {period['shortfall_hours']}"
        )
        assert period["overrun_hours"] == pytest.approx(0.0, abs=0.0001), (
            f"expected overrun_hours 0.0000 on the shortfall side, got {period['overrun_hours']}"
        )
        assert period["lessor_attributable_shortfall_hours"] == pytest.approx(
            0.0, abs=0.0001
        ), (
            "with no lessor-cancelled leg the attributable shortfall is 0.0000, got "
            f"{period['lessor_attributable_shortfall_hours']}"
        )
        assert period["shortfall_credit_cents"] == 0, (
            f"expected shortfall_credit_cents 0, got {period['shortfall_credit_cents']}"
        )
        assert period["base_charge_cents"] == PRORATED_BASE_CHARGE_CENTS, (
            f"expected base_charge_cents {PRORATED_BASE_CHARGE_CENTS}, got "
            f"{period['base_charge_cents']}"
        )
        assert period["gross_charge_cents"] == PRORATED_BASE_CHARGE_CENTS, (
            f"expected gross_charge_cents {PRORATED_BASE_CHARGE_CENTS}, got "
            f"{period['gross_charge_cents']}"
        )


class TestMinimumBillableBlockBoundary:
    def test_revenue_leg_at_exactly_sixty_block_minutes_bills_sixty(self, api):
        """PRD §3.6: A `REVENUE` leg is subject to a minimum billable block of one hour: if `block_minutes` is at least 60 the billable figure is `block_minutes` itself, and otherwise it is 60.
        PRD §3.6: Because the comparison is inclusive, a 60-minute revenue leg bills 60 minutes and a 59-minute revenue leg also bills 60.
        PRD §3.6: It advances `status` from `DISPATCHED` to `COMPLETED`, stores `actual_in` and the optionally supplied `technical_delay_minutes` (a non-negative count of departure-delay minutes attributable to a technical defect, defaulting to 0), and writes `block_minutes` as the whole number of minutes between `actual_out` and `actual_in` with the remaining seconds discarded.

        Design: Difficulty/boundary_precision_check/revenue_leg_block_minutes_exactly_at_minimum_billable_floor
        """
        _scenario, at_floor, _under_floor = _setup_two_dispatched_revenue_legs(api)

        leg = validate_success(
            api.complete_flight_leg(
                at_floor["id"],
                complete_leg_payload("2026-09-08T07:00:00Z", technical_delay_minutes=0),
                OPS,
            )
        )

        assert leg["block_minutes"] == 60, (
            f"a leg flown in exactly 60 minutes keeps block_minutes 60, got {leg['block_minutes']}"
        )
        assert leg["billable_block_minutes"] == 60, (
            "the one-hour floor must leave an at-boundary revenue leg billing 60 minutes, "
            f"got {leg['billable_block_minutes']}"
        )
        assert leg["status"] == "COMPLETED", (
            f"expected the leg to land COMPLETED, got {leg['status']}"
        )

    def test_revenue_leg_one_minute_under_the_floor_still_bills_sixty(self, api):
        """PRD §3.6: A `REVENUE` leg is subject to a minimum billable block of one hour: if `block_minutes` is at least 60 the billable figure is `block_minutes` itself, and otherwise it is 60.
        PRD §3.6: Because the comparison is inclusive, a 60-minute revenue leg bills 60 minutes and a 59-minute revenue leg also bills 60.
        PRD §3.6: Completion also advances the airframe's counters: `block_minutes` divided by 60 is added to both `airframe_hours_total` and `hours_since_last_check`, each rounded to two decimal places, and `cycles_since_last_check` is increased by 1.

        Design: Difficulty/boundary_precision_check/revenue_leg_block_minutes_exactly_at_minimum_billable_floor
        """
        scenario, at_floor, under_floor = _setup_two_dispatched_revenue_legs(api)
        complete_leg(api, at_floor["id"], "2026-09-08T07:00:00Z", technical_delay_minutes=0)

        leg = validate_success(
            api.complete_flight_leg(
                under_floor["id"],
                complete_leg_payload("2026-09-09T06:59:00Z", technical_delay_minutes=0),
                OPS,
            )
        )

        assert leg["block_minutes"] == 59, (
            "a leg flown in 59 minutes keeps its own block_minutes 59, got "
            f"{leg['block_minutes']}"
        )
        assert leg["billable_block_minutes"] == 60, (
            "a revenue leg under the one-hour floor bills 60 minutes, got "
            f"{leg['billable_block_minutes']}"
        )
        assert leg["status"] == "COMPLETED", (
            f"expected the leg to land COMPLETED, got {leg['status']}"
        )
        aircraft = validate_success(
            api.get_aircraft(scenario["aircraft"]["id"], TECH)
        )
        assert aircraft["cycles_since_last_check"] == 42, (
            "two completions on top of the opening 40 cycles leave 42, got "
            f"{aircraft['cycles_since_last_check']}"
        )


class TestCrewDutyProjectionBoundary:
    def test_projected_duty_of_3601_minutes_is_refused(self, api):
        """PRD §3.4: The limits are 3,600 minutes of projected seven-day duty — sixty hours — and 5,400 minutes of projected twenty-eight-day block time — ninety hours.
        PRD §3.4: The boundary is inclusive on the admissible side: a projection landing exactly on 3,600 or exactly on 5,400 minutes is admitted, and only a strictly greater projection is refused.
        PRD §3.4: Exceeding the duty limit yields `ERR_CREW_DUTY_LIMIT_EXCEEDED` (HTTP 409); exceeding the block limit yields `ERR_CREW_BLOCK_LIMIT_EXCEEDED` (HTTP 409).
        PRD §3.4: For the crew member under test, the projected seven-day duty is that crew member's candidate leg duty — its scheduled block minutes plus the 105-minute allowance — plus the same duty figure summed over that crew member's other legs in `SCHEDULED`, `DISPATCHED` or `COMPLETED` whose `scheduled_out` falls at or after the instant 168 hours before the candidate's off-blocks instant and strictly before that instant.

        Design: Difficulty/boundary_precision_check/crew_duty_projection_at_3600_admitted_then_3601_rejected
        """
        scenario = _setup_three_long_legs(api)

        # 2700 accumulated duty minutes plus 796 + 105 projects 3601.
        response = _candidate_long_leg(api, scenario, "2026-09-13T13:16:00Z")

        validate_error(response, ApiErrorId.ERR_CREW_DUTY_LIMIT_EXCEEDED)
        legs, _ = validate_paginated(
            api.list_flight_legs(OPS, params={"lease_id": scenario["lease"]["id"]})
        )
        assert len(legs) == 3, (
            f"expected the refused candidate to create no leg, found {len(legs)} legs"
        )

    def test_projected_duty_of_exactly_3600_minutes_is_admitted(self, api):
        """PRD §3.4: The boundary is inclusive on the admissible side: a projection landing exactly on 3,600 or exactly on 5,400 minutes is admitted, and only a strictly greater projection is refused.
        PRD §3.4: `rolling_block_minutes_28d` is the sum of the scheduled block minutes alone, over the same status filter, for legs whose `scheduled_out` falls within the last twenty-eight days — at or after the instant 672 hours before the clock and strictly before it.
        PRD §3.6: `scheduled_block_minutes` is computed once at creation and never changes: it is the whole number of minutes between `scheduled_out` and `scheduled_in`, with any remaining seconds discarded.
        PRD §3.6: The leg is created with `status` `SCHEDULED` and `billing_state` `UNBILLED`; `actual_out`, `actual_in`, `cancelling_party` and `cancel_reason` are all null, `technical_delay_minutes` is 0, `block_minutes` and `billable_block_minutes` are 0, and `crew_requalification_required` is false.

        Design: Difficulty/boundary_precision_check/crew_duty_projection_at_3600_admitted_then_3601_rejected
        """
        scenario = _setup_three_long_legs(api)
        refused = _candidate_long_leg(api, scenario, "2026-09-13T13:16:00Z")
        validate_error(refused, ApiErrorId.ERR_CREW_DUTY_LIMIT_EXCEEDED)

        # The identical slot at 795 block minutes projects 2700 + 795 + 105 == 3600, and
        # 3 x 795 + 795 == 3180 block minutes against the 5,400-minute ceiling.
        response = _candidate_long_leg(api, scenario, "2026-09-13T13:15:00Z")

        leg = validate_success(response, 201)
        assert leg["scheduled_block_minutes"] == 795, (
            f"expected scheduled_block_minutes 795, got {leg['scheduled_block_minutes']}"
        )
        assert leg["status"] == "SCHEDULED", (
            f"expected the admitted leg to be SCHEDULED, got {leg['status']}"
        )
        legs, _ = validate_paginated(
            api.list_flight_legs(OPS, params={"lease_id": scenario["lease"]["id"]})
        )
        assert len(legs) == 4, (
            "expected exactly four legs on the lease after the refused and the admitted "
            f"candidate, found {len(legs)}"
        )


class TestSubstituteHoursSinceCheckCeiling:
    def test_only_spare_just_past_the_hours_ceiling_leaves_the_pool_empty(self, api):
        """PRD §3.7: The eligible pool is every airframe other than the original whose `status` is `AVAILABLE`, whose `assigned_lease_id` is null, whose `type_family` equals the original's `type_family`, whose `maintenance_program_ref` equals the lease's `required_maintenance_program_ref`, whose `seat_count` is at least the original's `seat_count` less five, and whose `hours_since_last_check` is not more than 400.00 hours — the boundary being inclusive, so an airframe at exactly 400.00 hours remains eligible.
        PRD §3.7: If the pool is empty the request is refused with `ERR_NO_SUBSTITUTE_AIRCRAFT_AVAILABLE` (HTTP 409).
        PRD §2.5: Airframe hour counters are held to two decimal places, and the substitution eligibility comparison on hours since last heavy check is likewise made at two decimal places.
        PRD §3.7: Either way the request records `seat_delta` as the substitute's `seat_count` less the original's `seat_count` — a figure the lessee needs for its consent decision — and `repointed_leg_count` as 0 at creation, and the lease's `version` increments by 1.

        Design: Difficulty/boundary_precision_check/substitute_selection_at_hours_since_check_ceiling_boundary
        """
        scenario = setup_active_lease(api)
        over_ceiling = _register_spare(
            api,
            "G-OVER",
            400.01,
            airframe_hours_total=31000.00,
            cycles_since_last_check=150,
        )
        lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS))

        response = _request_server_selected_substitution(api, scenario, lease["version"])

        validate_error(response, ApiErrorId.ERR_NO_SUBSTITUTE_AIRCRAFT_AVAILABLE)
        substitutions, _ = validate_paginated(
            api.list_substitutions(OPS, params={"lease_id": scenario["lease"]["id"]})
        )
        assert substitutions == [], (
            "a refused request records no substitution, found "
            f"{len(substitutions)}"
        )
        lease_after = validate_success(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease_after["version"] == lease["version"], (
            "no substitution was recorded, so the lease version must stay at "
            f"{lease['version']}, got {lease_after['version']}"
        )
        spare = validate_success(api.get_aircraft(over_ceiling["id"], TECH))
        assert float(spare["hours_since_last_check"]) == pytest.approx(400.01, abs=0.001), (
            "the excluded spare must sit just past the ceiling, got "
            f"{spare['hours_since_last_check']}"
        )

    def test_spare_at_exactly_the_hours_ceiling_is_selected(self, api):
        """PRD §3.7: The eligible pool is every airframe other than the original whose `status` is `AVAILABLE`, whose `assigned_lease_id` is null, whose `type_family` equals the original's `type_family`, whose `maintenance_program_ref` equals the lease's `required_maintenance_program_ref`, whose `seat_count` is at least the original's `seat_count` less five, and whose `hours_since_last_check` is not more than 400.00 hours — the boundary being inclusive, so an airframe at exactly 400.00 hours remains eligible.
        PRD §3.7: When `substitute_aircraft_id` is omitted, the server picks one and records `selection_basis` as `SERVER_SELECTED`.
        PRD §3.7: Either way the request records `seat_delta` as the substitute's `seat_count` less the original's `seat_count` — a figure the lessee needs for its consent decision — and `repointed_leg_count` as 0 at creation, and the lease's `version` increments by 1.
        PRD §3.7: On a lease whose rights are `LESSOR_UNILATERAL` the request lands directly in `APPROVED`, `seat_delta` is written, no airframe is touched yet, and — this is the branch's extra effect — every other substitution on the same lease whose `status` is `REQUESTED`, `LESSEE_CONSENT_PENDING` or `APPROVED` is moved to the terminal `WITHDRAWN`, without touching any airframe.

        Design: Difficulty/boundary_precision_check/substitute_selection_at_hours_since_check_ceiling_boundary
        """
        scenario = setup_active_lease(api)
        over_ceiling = _register_spare(
            api,
            "G-OVER",
            400.01,
            airframe_hours_total=31000.00,
            cycles_since_last_check=150,
        )
        lease = validate_success(api.get_lease(scenario["lease"]["id"], OPS))
        refused = _request_server_selected_substitution(api, scenario, lease["version"])
        validate_error(refused, ApiErrorId.ERR_NO_SUBSTITUTE_AIRCRAFT_AVAILABLE)

        at_ceiling = _register_spare(
            api,
            "G-EDGE",
            400.00,
            airframe_hours_total=15000.00,
            cycles_since_last_check=149,
        )

        response = _request_server_selected_substitution(api, scenario, lease["version"])

        substitution = validate_success(response, 201)
        assert substitution["substitute_aircraft_id"] == at_ceiling["id"], (
            "the airframe at exactly 400.00 hours since check is eligible and must be "
            f"selected, got {substitution['substitute_aircraft_id']}"
        )
        assert substitution["substitute_aircraft_id"] != over_ceiling["id"], (
            "the airframe at 400.01 hours since check must stay out of the pool"
        )
        assert substitution["selection_basis"] == "SERVER_SELECTED", (
            f"expected selection_basis SERVER_SELECTED, got {substitution['selection_basis']}"
        )
        assert substitution["seat_delta"] == 0, (
            f"expected seat_delta 0 between two 189-seat airframes, got {substitution['seat_delta']}"
        )
        assert substitution["status"] == "APPROVED", (
            "a unilateral-rights lease lands the request directly in APPROVED, got "
            f"{substitution['status']}"
        )
        assert substitution["repointed_leg_count"] == 0, (
            f"expected repointed_leg_count 0 at creation, got {substitution['repointed_leg_count']}"
        )

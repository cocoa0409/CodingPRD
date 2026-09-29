"""Consistency model: an acceptance's whole cascade is visible to the reads that
immediately follow it, with no sweep or checkpoint interposed.
"""

from test_helpers import (
    PAYROLL_ANALYST,
    STAFFING_OFFICER,
    fixtures as fx,
    validate_success,
)


def _member_holding_a_live_voluntary_offer(api):
    """A single-seat company whose only vacancy is out for offer at 144000 cents."""
    station = fx.create_station(
        api,
        name="Station 134",
        battalion_code="G6",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=900_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-134",
        apparatus_type="ENGINE",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="Z Zorn",
        rank="FIREFIGHTER",
        platoon="D",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
    shift = fx.published_shift(api, station["id"], shift_date="2026-08-11", platoon="C")
    vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
    offer = fx.dispatch_offer(api, vacancy["id"], "VOLUNTARY", 24)
    assert offer["firefighter_id"] == member["id"]
    assert offer["projected_cost_cents"] == 144_000
    return {
        "station": station,
        "member": member,
        "shift": shift,
        "vacancy": vacancy,
        "offer": offer,
        "work_period": fx.work_period_of(api, member["id"]),
    }


class TestImmediateConsistencyOnOfferAcceptance:
    def test_the_acceptance_response_already_carries_the_final_staffing_state(
        self, api
    ):
        """PRD 2.4: "Cascades propagate immediately and completely, in the hop
        order stated wherever a workflow in 3 describes one ... Whenever any
        mutation leaves a shift in `HIRING` with `open_vacancy_count` at zero,
        the shift moves to `STAFFED` and its `version` increments ... Neither
        transition requires a client request naming the shift."  PRD 3.7 fixes
        what acceptance writes: the offer to `ACCEPTED` and "the vacancy
        `OFFERING -> FILLED`", a seat "created in `SCHEDULED` status with
        `assignment_type` `OVERTIME` ... `source_offer_id` pointing at the
        offer", and "the vacancy's `filled_by_assignment_id` is set to that
        seat".  No staffing-run is called anywhere below.

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_request_that_causes_it
        """
        world = _member_holding_a_live_voluntary_offer(api)

        accepted = validate_success(
            api.respond_to_offer(
                world["offer"]["id"],
                {"response": "ACCEPT"},
                fx.make_firefighter_headers(world["member"]["id"]),
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED"

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["status"] == "STAFFED"
        assert shift["assigned_headcount"] == 1
        assert shift["open_vacancy_count"] == 0
        assert shift["staffing_gap"] == 0
        assert shift["staffing_posture"] == "FULLY_STAFFED"

        vacancy = fx.read_vacancy(api, world["vacancy"]["id"])
        assert vacancy["status"] == "FILLED"
        assert vacancy["filled_by_assignment_id"] is not None

        seat = fx.read_assignment(api, vacancy["filled_by_assignment_id"])
        assert seat["source_offer_id"] == world["offer"]["id"]
        assert seat["assignment_type"] == "OVERTIME"
        assert seat["status"] == "SCHEDULED"
        assert seat["scheduled_hours"] == 24
        assert seat["projected_premium_cents"] == 144_000

    def test_the_ledger_and_the_work_period_are_current_on_the_very_next_read(
        self, api
    ):
        """PRD 3.7: "The station's `ot_committed_cents` is **not** re-added,
        because the encumbrance has merely moved from the offer to the
        assignment ... but `budget_posture` is recomputed all the same", and hops
        two and three are part of the same acceptance: "the covering work
        period's scheduled hours increase by the payable hours and its projected
        overtime hours are recomputed" then "the work period's premium is
        re-priced on the scheduled basis".  PRD 3.9 defines `scheduled_hours` as
        the assignment sum "plus the period's `adjusted_scheduled_hours`", which
        no adjustment has touched, and 24 hours are far below the 204-hour
        threshold, so the premium is zero.  144000 of a 900000 budget is 1600
        basis points, and PRD 2.10 bands anything at or below 9000 as `WITHIN`.

        Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_request_that_causes_it
        """
        world = _member_holding_a_live_voluntary_offer(api)
        fx.answer_offer(api, world["offer"]["id"], world["member"]["id"], "ACCEPT")

        station = validate_success(
            api.get_station(world["station"]["id"], STAFFING_OFFICER), 200
        )
        assert station["ot_committed_cents"] == 144_000
        assert station["ot_actual_cents"] == 0
        assert station["budget_posture"] == "WITHIN"

        period = validate_success(
            api.get_work_period(world["work_period"]["id"], PAYROLL_ANALYST), 200
        )
        assert period["scheduled_hours"] == 24
        assert period["adjusted_scheduled_hours"] == 0
        assert period["projected_flsa_overtime_hours"] == 0
        assert period["flsa_premium_cents"] == 0

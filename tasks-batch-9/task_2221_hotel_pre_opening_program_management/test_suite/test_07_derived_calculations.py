"""Derived arithmetic on the pre-opening program.

Every expectation in this file is recomputed from the formula, the rounding rule
and the evaluation order the PRD states, never from an implementation.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.api_errors import ERR_INVALID_SYSTEM_STATE
from test_helpers.assertions import (
    assert_cents,
    assert_committed_is_authority,
    assert_posture,
    assert_program_dimensions,
    assert_ratio,
)
from test_helpers.constants import ROLE_SYSTEMS_INTEGRATOR
from test_helpers.factories import reservation_block_payload
from test_helpers.fixtures import (
    add_test_run,
    baselined_program,
    booking_open_program,
    make_hire,
    make_hiring_plan,
    make_milestone,
    make_program,
    make_system,
    program_with_milestones,
    read_program,
    read_readiness,
    respond_to_offer,
    set_clock,
)
from test_helpers.test_users import (
    BASELINING_DIRECTOR,
    CERTIFYING_INTEGRATOR,
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    PROGRAM_DIRECTOR,
    SYSTEMS_INTEGRATOR,
    TALENT_MANAGER,
    TEST_RUNNER_INTEGRATOR,
    headers_for,
)

CLOCK_START = "2026-09-01T00:00:00Z"

# A single thirty-day construction milestone starting on the chain-root date.
THIRTY_DAY_NETWORK = [
    {
        "code": "CONSTRUCTION_COMPLETE",
        "name": "Construction complete",
        "duration_days": 30,
        "planned_start_date": "2026-09-01",
    }
]


def _payroll_scenario(api):
    """A baselined program plus one ROOMS plan holding three identical-shift hires.

    The single thirty-day milestone starts on 2026-09-01, so the committed
    project finish is 2026-10-01 and the committed projected opening date is
    2026-10-15 once the fourteen-day licensing buffer is added.
    """
    built = baselined_program(api, milestones=THIRTY_DAY_NETWORK)
    program_id = built["program"]["id"]
    plan = make_hiring_plan(
        api,
        program_id,
        department="ROOMS",
        headcount_target=5,
        wave_start_date="2026-09-10",
    )
    accepted = make_hire(
        api,
        plan["id"],
        full_name="A. Keeper",
        hourly_rate_cents=2500,
        scheduled_hours_per_day=8,
        start_date="2026-09-15",
    )
    offered = make_hire(
        api,
        plan["id"],
        full_name="B. Pending",
        hourly_rate_cents=3000,
        scheduled_hours_per_day=8,
        start_date="2026-09-15",
    )
    withdrawn = make_hire(
        api,
        plan["id"],
        full_name="C. Gone",
        hourly_rate_cents=4000,
        scheduled_hours_per_day=8,
        start_date="2026-09-15",
    )
    respond_to_offer(api, accepted["id"], "ACCEPT")
    respond_to_offer(api, withdrawn["id"], "ACCEPT")
    respond_to_offer(api, withdrawn["id"], "WITHDRAW")
    return {
        "program": built["program"],
        "plan": plan,
        "accepted": accepted,
        "offered": offered,
        "withdrawn": withdrawn,
    }


class TestPayrollAccrualSet:
    """The payroll projection is built only over the accepted and onboarded hires."""

    def test_program_payroll_accrual_counts_only_the_accepted_hire(self, api):
        """Three hires share the same shift and the same first payroll day, but one
        is still offered and one has withdrawn after accepting. Only the accepted
        hire's thirty pre-opening days reach the program's payroll projection.

        The program's `payroll_accrual_cents` is then the sum of `accrual_cents` over the hires reached through the program's hiring plans whose state is `ACCEPTED` or `ONBOARDED`; hires in `OFFERED`, `DECLINED` or `WITHDRAWN` contribute nothing.

        Design: Corner/calculations/payroll_accrual_excludes_offered_and_withdrawn_hires
        """
        set_clock(api, CLOCK_START)
        scenario = _payroll_scenario(api)
        program_id = scenario["program"]["id"]

        # The committed projection is the accrual horizon: 2026-09-01 + 30 days
        # of duration + 14 licensing buffer days.
        assert scenario["program"]["projected_opening_date_committed"] == "2026-10-15"

        response = api.get_readiness(program_id, PROGRAM_DIRECTOR)
        readiness = validate_success(response, expected_status=200)

        # 2026-09-15 up to but excluding 2026-10-15 is thirty whole days, so the
        # accepted hire accrues round_half_up(2500 * 8 * 30) = 600000 cents. The
        # offered hire's 720000 and the withdrawn hire's 960000 are excluded.
        assert_cents(readiness["payroll_accrual_cents"], 600000)

    def test_offered_and_withdrawn_hires_hold_a_zero_accrual(self, api):
        """The per-hire projection is published on the hire itself. A hire outside
        the accrual set carries zero cents no matter what its rate and shift would
        otherwise have produced.

        That day count is multiplied by the hire's `hourly_rate_cents` and by its `scheduled_hours_per_day`, and the product is rounded half up to whole cents to give the hire's `accrual_cents`; a hire whose state is anything other than `ACCEPTED` or `ONBOARDED` holds `accrual_cents` of 0.

        Design: Corner/calculations/payroll_accrual_excludes_offered_and_withdrawn_hires
        """
        set_clock(api, CLOCK_START)
        scenario = _payroll_scenario(api)

        accepted = validate_success(
                api.get_hire(scenario["accepted"]["id"], TALENT_MANAGER),
                expected_status=200,
            )
        assert accepted["state"] == "ACCEPTED"
        assert_cents(accepted["accrual_cents"], 600000)

        offered = validate_success(
                api.get_hire(scenario["offered"]["id"], TALENT_MANAGER),
                expected_status=200,
            )
        assert offered["state"] == "OFFERED"
        assert_cents(offered["accrual_cents"], 0)

        withdrawn = validate_success(
                api.get_hire(scenario["withdrawn"]["id"], TALENT_MANAGER),
                expected_status=200,
            )
        assert withdrawn["state"] == "WITHDRAWN"
        assert_cents(withdrawn["accrual_cents"], 0)


class TestTestRunPassRateFloor:
    """The 0.50 demotion floor and the 0.95 certification floor read the same run."""

    def test_run_below_the_fifty_percent_floor_drives_the_system_to_failed(self, api):
        """A property-systems run that passes four of ten cases sits below the
        demotion floor, so the system lands in FAILED rather than TESTING and
        cannot be signed off from there.

        Against all of that sits one demotion rule: if the new run's `latest_pass_rate` is below 0.50 the system lands in `FAILED` instead of `TESTING`.

        Design: Corner/calculations/test_run_below_fifty_percent_floor_drives_system_to_failed
        """
        set_clock(api, CLOCK_START)
        program = make_program(api)
        system = make_system(api, program["id"], system_type="PMS", is_required=True)

        response = api.create_test_run(
            system["id"],
            {
                "executed_at": "2026-09-01T09:00:00Z",
                "cases_total": 10,
                "cases_passed": 4,
                "blocker_count": 0,
            },
            TEST_RUNNER_INTEGRATOR,
        )
        run = validate_success(response, expected_status=201)
        assert_ratio(run["pass_rate"], 0.4)
        assert run["result"] == "FAILED"

        after = validate_success(
                api.get_system_implementation(system["id"], SYSTEMS_INTEGRATOR),
                expected_status=200,
            )
        assert after["state"] == "FAILED"
        assert_ratio(after["latest_pass_rate"], 0.4)

        # A FAILED system is not an admissible certification source at all.
        validate_error(
            api.certify_system(system["id"], CERTIFYING_INTEGRATOR),
            ERR_INVALID_SYSTEM_STATE,
            expected_status=409,
        )

    def test_run_at_exactly_fifty_percent_recovers_the_system_to_testing(self, api):
        """Five of ten cases lands exactly on the recovery floor, which is inclusive,
        so the failed system returns to testing while the pooled figure keeps both
        runs in view.

        A system in `FAILED` may only be moved back into `TESTING` by a run whose pass rate is at least 0.50.

        Design: Corner/calculations/test_run_below_fifty_percent_floor_drives_system_to_failed
        """
        set_clock(api, CLOCK_START)
        program = make_program(api)
        system = make_system(api, program["id"], system_type="PMS", is_required=True)

        add_test_run(api, system["id"], "2026-09-01T09:00:00Z", 10, 4)

        response = api.create_test_run(
            system["id"],
            {
                "executed_at": "2026-09-01T11:00:00Z",
                "cases_total": 10,
                "cases_passed": 5,
                "blocker_count": 0,
            },
            TEST_RUNNER_INTEGRATOR,
        )
        recovery = validate_success(response, expected_status=201)
        assert_ratio(recovery["pass_rate"], 0.5)

        after = validate_success(
                api.get_system_implementation(system["id"], SYSTEMS_INTEGRATOR),
                expected_status=200,
            )
        assert after["state"] == "TESTING"
        assert_ratio(after["latest_pass_rate"], 0.5)
        # Nine cases passed of twenty executed, pooled over both runs.
        assert_ratio(after["cumulative_pass_rate"], 0.45)


class TestLatestRunSelection:
    """The most recent run is chosen on the executed instant, not on arrival order."""

    def _two_runs_out_of_order(self, api):
        program = make_program(api)
        system = make_system(api, program["id"], system_type="POS", is_required=True)
        # Inserted first, but carries the later executed instant.
        add_test_run(api, system["id"], "2026-09-03T09:00:00Z", 40, 40)
        # Inserted second, and carries the earlier executed instant.
        add_test_run(
            api,
            system["id"],
            "2026-09-01T09:00:00Z",
            40,
            30,
            headers=headers_for(ROLE_SYSTEMS_INTEGRATOR, "si-runner-2"),
        )
        return {"program": program, "system": system}

    def test_latest_pass_rate_reads_the_greatest_executed_at(self, api):
        """Two runs are appended out of chronological order. The aggregate rate must
        come from the run executed on 2026-09-03 even though it was written first,
        while the pooled rate keeps counting both runs.

        The most recent run is the one with the greatest `executed_at`; ties on that instant are broken by the greater `created_at`, and the run's `id` is never consulted.

        Design: Corner/calculations/latest_run_selected_by_executed_at_not_insertion_order
        """
        set_clock(api, CLOCK_START)
        built = self._two_runs_out_of_order(api)

        system = validate_success(
                api.get_system_implementation(built["system"]["id"], SYSTEMS_INTEGRATOR),
                expected_status=200,
            )
        assert_ratio(system["latest_pass_rate"], 1.0)
        # Seventy cases passed of eighty executed, pooling both runs.
        assert_ratio(system["cumulative_pass_rate"], 0.875)
        assert system["open_blocker_count"] == 0
        assert system["state"] == "TESTING"
        assert system["test_run_count"] == 2

    def test_certification_reads_the_latest_rate_not_the_last_inserted_run(self, api):
        """Certification is guarded on the latest run's pass rate. Here the
        last-inserted run scored 0.75, but the chronologically latest run scored
        1.0, so the sign-off is admitted.

        The system's `latest_pass_rate` must be at least 0.95, else `ERR_SYSTEM_PASS_RATE_BELOW_THRESHOLD` — and this reads the **latest** rate, never the pooled one, so a system whose `cumulative_pass_rate` sits comfortably above the floor but whose most recent run fell below it must still be refused.

        Design: Corner/calculations/latest_run_selected_by_executed_at_not_insertion_order
        """
        set_clock(api, CLOCK_START)
        built = self._two_runs_out_of_order(api)

        certifier = headers_for(ROLE_SYSTEMS_INTEGRATOR, "si-certifier-3")
        certified = validate_success(
                api.certify_system(built["system"]["id"], certifier),
                expected_status=200,
            )
        assert certified["state"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == "si-certifier-3"


class TestReadinessScorePrecision:
    """The weighted readiness score is published at four decimal places."""

    def test_readiness_score_is_rounded_half_up_to_four_decimals(self, api):
        """A programme whose contractual first-guest date is a week before the
        committed projection carries a seven-day slip. Only the schedule term
        contributes, and its weighted value is not representable at four places
        without rounding.

        `readiness_score` is the systems ratio weighted at 0.30, plus the staffing ratio weighted at 0.25, plus the permit ratio weighted at 0.25, plus the schedule term weighted at 0.20, rounded half up to four decimal places.

        Design: Corner/calculations/readiness_score_rounded_half_up_to_four_decimals
        """
        set_clock(api, CLOCK_START)
        program = make_program(api, target_opening_date="2026-10-08")
        make_milestone(
            api,
            program["id"],
            code="CONSTRUCTION_COMPLETE",
            name="Construction complete",
            duration_days=30,
            planned_start_date="2026-09-01",
        )

        baselined = validate_success(
                api.baseline_schedule(program["id"], BASELINING_DIRECTOR),
                expected_status=200,
            )

        assert baselined["projected_opening_date_committed"] == "2026-10-15"
        assert_committed_is_authority(baselined)
        # 2026-10-15 exceeds the 2026-10-08 target by seven whole days.
        assert baselined["schedule_slip_days"] == 7

        # 0.30*0.0 + 0.25*0.0 + 0.25*0.0 + 0.20*(1 - 7/30) = 0.153333...,
        # which rounds half up at four places to 0.1533.
        assert_ratio(baselined["readiness_score"], 0.1533)
        # Seven days of slip stays inside the ten-day tolerance and the score is
        # far below the 0.85 floor, so the posture stays at its opening value.
        assert_posture(baselined, "MOBILIZING")

        readiness = read_readiness(api, program["id"])
        assert_ratio(readiness["readiness_score"], 0.1533)
        assert readiness["schedule_slip_days"] == 7


class TestCriticalPathTopology:
    """A join node with two predecessors of unequal length distributes the float."""

    def test_join_node_earliest_start_is_driven_by_the_longer_branch(self, api):
        """Structure and mechanical rough-in both feed the interior fit-out. The
        twenty-day branch drives the join node's earliest start, which leaves the
        fifteen-day branch with five days of float and two milestones critical.

        The milestone's earliest start is the **latest** of its candidates.

        Design: Corner/calculations/dependency_graph_topological_order_with_two_predecessors
        """
        set_clock(api, CLOCK_START)
        built = program_with_milestones(
            api,
            milestones=[
                {
                    "code": "STRUCTURE_TOPPED_OUT",
                    "name": "Structure topped out",
                    "duration_days": 20,
                    "planned_start_date": "2026-09-01",
                },
                {
                    "code": "MEP_ROUGH_IN",
                    "name": "MEP rough-in",
                    "duration_days": 15,
                    "planned_start_date": "2026-09-02",
                },
                {
                    "code": "INTERIOR_FIT_OUT",
                    "name": "Interior fit-out",
                    "duration_days": 10,
                    "planned_start_date": "2026-09-25",
                },
            ],
            edges=[
                {
                    "predecessor": "STRUCTURE_TOPPED_OUT",
                    "successor": "INTERIOR_FIT_OUT",
                    "dependency_type": "FINISH_START",
                    "lag_days": 0,
                },
                {
                    "predecessor": "MEP_ROUGH_IN",
                    "successor": "INTERIOR_FIT_OUT",
                    "dependency_type": "FINISH_START",
                    "lag_days": 0,
                },
            ],
        )
        program_id = built["program"]["id"]

        baselined = validate_success(
                api.baseline_schedule(program_id, BASELINING_DIRECTOR),
                expected_status=200,
            )
        # Project finish 2026-10-01 plus the fourteen-day licensing buffer.
        assert baselined["projected_opening_date_committed"] == "2026-10-15"
        assert baselined["critical_path_milestone_count"] == 2

        structure = validate_success(
                api.get_milestone(
                    built["milestones"]["STRUCTURE_TOPPED_OUT"]["id"],
                    CONSTRUCTION_MANAGER,
                ),
                expected_status=200,
            )
        assert structure["earliest_start_date"] == "2026-09-01"
        assert structure["earliest_finish_date"] == "2026-09-21"
        assert structure["latest_finish_date"] == "2026-09-21"
        assert structure["total_float_days"] == 0
        assert structure["is_critical"] is True

        mep = validate_success(
                api.get_milestone(
                    built["milestones"]["MEP_ROUGH_IN"]["id"], CONSTRUCTION_MANAGER
                ),
                expected_status=200,
            )
        assert mep["earliest_start_date"] == "2026-09-01"
        assert mep["earliest_finish_date"] == "2026-09-16"
        assert mep["latest_finish_date"] == "2026-09-21"
        assert mep["total_float_days"] == 5
        assert mep["is_critical"] is False

        fit_out = validate_success(
                api.get_milestone(
                    built["milestones"]["INTERIOR_FIT_OUT"]["id"], CONSTRUCTION_MANAGER
                ),
                expected_status=200,
            )
        # The twenty-day branch finishes on 2026-09-21 and the fifteen-day branch
        # on 2026-09-16, so the later of the two candidates decides.
        assert fit_out["earliest_start_date"] == "2026-09-21"
        assert fit_out["earliest_finish_date"] == "2026-10-01"
        assert fit_out["total_float_days"] == 0
        assert fit_out["is_critical"] is True


class TestContingencyEvaluationOrder:
    """The administrative fee tier is chosen on the pre-fee relocation base."""

    def test_accepted_pre_opening_block_contingency_follows_the_pinned_order(self, api):
        """A five-room, two-night group arrives ten days before the committed
        projected opening, so the block is pre-opening and carries contingency. The
        base relocation sits in the lowest fee tier and no guarantee penalty is due.

        Third, a fee tier is chosen **on that base relocation amount** — not on the subtotal and not on the final contingency: five percent when the base is below five thousand dollars (500,000 cents), eight percent when the base is at least five thousand dollars and below twenty thousand dollars (2,000,000 cents), and twelve percent when the base is at or above twenty thousand dollars.

        Design: Corner/calculations/contingency_for_a_single_accepted_pre_opening_block_follows_the_pinned_order
        """
        set_clock(api, CLOCK_START)
        built = booking_open_program(
            api, finish_iso="2026-10-01T00:00:00Z", duration_days=30
        )
        program = built["program"]
        program_id = program["id"]

        assert_program_dimensions(
            program,
            schedule_state="CONSTRUCTION_COMPLETE",
            commercial_state="BOOKING_OPEN",
        )
        assert program["projected_opening_date_committed"] == "2026-10-15"

        response = api.create_reservation_block(
            reservation_block_payload(
                program_id,
                program["version"],
                account_name="Harborline Crew",
                arrival_date="2026-10-05",
                night_count=2,
                room_count=5,
                rate_cents=20000,
            ),
            COMMERCIAL_DIRECTOR,
        )
        block = validate_success(response, expected_status=201)

        assert block["room_nights"] == 10
        assert_cents(block["revenue_cents"], 200000)
        # 2026-10-05 falls strictly before the committed projected opening.
        assert block["is_pre_opening"] is True
        assert block["state"] == "ACCEPTED"
        # Base 10 * 25000 = 250000, below the 500000 breakpoint, so the tier is
        # five percent: fee 12500, subtotal 262500, no guarantee penalty.
        assert_cents(block["contingency_cents"], 262500)

        refreshed = read_program(api, program_id)
        assert refreshed["committed_room_nights"] == 10
        assert_cents(refreshed["contingency_liability_cents"], 262500)

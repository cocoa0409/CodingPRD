"""Reversals that must land exactly on the state they started from."""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.assertions import (
    assert_clock_default,
    assert_flow,
    assert_money,
    assert_posture,
    assert_sheet_counters,
)
from test_helpers.fixtures import (
    HC1_TOTAL_DEMAND_GPM,
    PROJECT_TOTAL_DEMAND_GPM,
    STANDPIPE_DEMAND_GPM,
    close_comment,
    complete_review,
    create_auxiliary_system,
    raise_comment,
    read_auxiliary_system,
    read_calculation,
    read_project,
    read_shop_drawing,
    read_submittal,
    read_trade_clearance,
    build_converged_stage,
    build_under_review_stage,
)
from test_helpers.test_users import make_contractor_headers, make_design_engineer_headers

MAJOR_COMMENT = dict(
    code_section="NFPA 13 14.2.9",
    severity="MAJOR",
    description="Most demanding area is not the remote area; rerun with the corner bay",
)
WITHDRAW_NOTE = "Comment raised against the wrong sheet revision; retracted"


def _cascaded_then_withdrawn(client):
    """Fire cascade A, then retract the comment that caused it."""
    ctx = build_under_review_stage(client)
    ctx["comment"] = raise_comment(
        client,
        ctx["submittal_id"],
        ctx["reviewer_id"],
        assigned_engineer_id=ctx["lead_id"],
        **MAJOR_COMMENT,
    )
    complete_review(client, ctx["submittal_id"], ctx["reviewer_id"])
    ctx["comment"] = close_comment(
        client,
        ctx["comment"]["id"],
        ctx["reviewer_id"],
        disposition="WITHDRAWN",
        close_note=WITHDRAW_NOTE,
    )
    return ctx


class TestWithdrawnCommentReversesTheCascade:
    def test_01_the_calculation_is_resealed_to_its_original_sealer(self, client):
        """Every calculation whose `reopened_by_submittal_id` is this package moves
        `REOPENED → SEALED`, with its previous `sealed_by_engineer_id` and `sealed_at`
        restored, `stale_reason` cleared to null and `reopened_by_submittal_id` cleared to
        null.

        Design: Difficulty/compensating_invariant/withdrawing_the_major_comment_reverses_cascade_a_with_no_counter_drift
        """
        ctx = _cascaded_then_withdrawn(client)
        assert ctx["comment"]["state"] == "WITHDRAWN"
        assert ctx["comment"]["disposition"] == "WITHDRAWN"

        calculation = read_calculation(client, ctx["calculation_id"])
        assert calculation["state"] == "SEALED"
        assert calculation["stale_reason"] is None
        assert calculation["reopened_by_submittal_id"] is None
        assert calculation["sealed_by_engineer_id"] == ctx["lead_id"]
        assert calculation["sealed_by_engineer_id"] != ctx["reviewer_id"]
        assert_clock_default(calculation["sealed_at"])

    def test_02_the_sheet_and_its_three_items_come_back_with_no_counter_drift(self, client):
        """Every `STALE` shop drawing over those calculations returns to `COORDINATED`, every
        `STALE` item of those sheets returns to `CLEARED`, and each sheet's
        `cleared_trade_count` is restored to its `required_trade_count`.

        Design: Difficulty/compensating_invariant/withdrawing_the_major_comment_reverses_cascade_a_with_no_counter_drift
        """
        ctx = _cascaded_then_withdrawn(client)
        assert_sheet_counters(read_shop_drawing(client, ctx["sheet_id"]), "COORDINATED", 3)
        for cleared in ctx["clearances"]:
            item = read_trade_clearance(client, ctx["sheet_id"], cleared["id"])
            assert item["state"] == "CLEARED", f"{item['trade']} item stayed stale"
        assert read_project(client, ctx["project_id"])["sealed_calculation_count"] == 1

    def test_03_the_package_the_posture_and_the_ledger_all_return_to_where_they_were(
        self, client
    ):
        """A withdrawal that clears the last outstanding comment of a package compensates the
        four-link invalidation in full, with no drift left behind. The package returns
        `COMMENTS_ISSUED → UNDER_REVIEW`.

        Design: Difficulty/compensating_invariant/withdrawing_the_major_comment_reverses_cascade_a_with_no_counter_drift
        """
        ctx = _cascaded_then_withdrawn(client)
        submittal = read_submittal(client, ctx["submittal_id"])
        assert submittal["state"] == "UNDER_REVIEW"
        assert submittal["open_comment_count"] == 0
        assert submittal["major_comment_count"] == 0
        assert submittal["cycle_number"] == 1
        assert_money(submittal["review_fee_usd"], 0.00)

        project = read_project(client, ctx["project_id"])
        assert project["open_major_comment_count"] == 0
        assert_posture(project, "OPEN")
        assert project["status"] == "PERMIT_REVIEW"
        assert project["submittal_cycle_count"] == 1
        assert_money(project["review_fee_balance_usd"], 0.00)
        assert project["governing_hydraulic_calculation_id"] == ctx["calculation_id"]
        assert_flow(project["total_system_demand_gpm"], PROJECT_TOTAL_DEMAND_GPM)

        _, meta = validate_paginated(
            client.list_submittals(
                make_design_engineer_headers(ctx["lead_id"]),
                params={"project_id": ctx["project_id"]},
            )
        )
        assert meta["total_count"] == 1


FOAM_DELUGE = dict(
    system_type="FOAM_DELUGE",
    label="Flammable liquids dock",
    protected_area_sqft=3000.0,
    agent_type="AFFF",
)
FOAM_DEMAND_GPM = 480.0
LEDGER_WITH_FOAM_GPM = 2610.0


def _withdraw(client, ctx, system_id):
    return client.withdraw_auxiliary_system(
        system_id, make_design_engineer_headers(ctx["lead_id"])
    )


class TestAuxiliaryWithdrawalRestoresTheLedger:
    def test_04_adding_the_foam_deluge_lifts_the_ledger_by_exactly_its_own_demand(
        self, client
    ):
        """A foam deluge system takes a density of 0.16 gallons per minute per square foot
        over `protected_area_sqft`, rounded to 1 decimal place, and is raised to a floor of
        250.0 if it falls below it.

        Design: Difficulty/compensating_invariant/auxiliary_withdrawal_returns_the_demand_ledger_to_its_exact_prior_total
        """
        ctx = build_converged_stage(client)
        baseline = read_project(client, ctx["project_id"])
        assert_flow(baseline["auxiliary_demand_gpm"], STANDPIPE_DEMAND_GPM)
        assert_flow(baseline["total_system_demand_gpm"], PROJECT_TOTAL_DEMAND_GPM)

        foam = create_auxiliary_system(
            client, ctx["project_id"], ctx["lead_id"], **FOAM_DELUGE
        )
        assert_flow(foam["demand_gpm"], FOAM_DEMAND_GPM)
        assert foam["interlock_required"] is False
        assert foam["status"] == "PROPOSED"

        loaded = read_project(client, ctx["project_id"])
        assert_flow(
            loaded["auxiliary_demand_gpm"], STANDPIPE_DEMAND_GPM + FOAM_DEMAND_GPM
        )
        assert_flow(loaded["total_system_demand_gpm"], LEDGER_WITH_FOAM_GPM)

    def test_05_withdrawing_it_lands_back_on_the_exact_prior_total(self, client):
        """Withdrawal is the compensating half of the demand round trip: adding a system and
        then withdrawing it must leave the project's ledger figures exactly where they
        started.

        Design: Difficulty/compensating_invariant/auxiliary_withdrawal_returns_the_demand_ledger_to_its_exact_prior_total
        """
        ctx = build_converged_stage(client)
        foam = create_auxiliary_system(
            client, ctx["project_id"], ctx["lead_id"], **FOAM_DELUGE
        )
        withdrawn = validate_success(_withdraw(client, ctx, foam["id"]))
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["outage_start_at"] is None
        assert withdrawn["outage_end_at"] is None
        # The withdrawn row keeps its own figure while dropping out of the input set.
        assert_flow(withdrawn["demand_gpm"], FOAM_DEMAND_GPM)

        project = read_project(client, ctx["project_id"])
        assert_flow(project["auxiliary_demand_gpm"], STANDPIPE_DEMAND_GPM)
        assert_flow(project["governing_demand_gpm"], HC1_TOTAL_DEMAND_GPM)
        assert project["governing_hydraulic_calculation_id"] == ctx["calculation_id"]
        assert_flow(project["total_system_demand_gpm"], PROJECT_TOTAL_DEMAND_GPM)

    def test_06_the_compensation_cannot_be_applied_twice(self, client):
        """The target row is not already in a terminal state of the dimension the request
        advances — `ERR_TERMINAL_STATE_LOCKED` (409).

        Design: Difficulty/compensating_invariant/auxiliary_withdrawal_returns_the_demand_ledger_to_its_exact_prior_total
        """
        ctx = build_converged_stage(client)
        foam = create_auxiliary_system(
            client, ctx["project_id"], ctx["lead_id"], **FOAM_DELUGE
        )
        validate_success(_withdraw(client, ctx, foam["id"]))
        validate_error(
            _withdraw(client, ctx, foam["id"]),
            "ERR_TERMINAL_STATE_LOCKED",
            expected_status=409,
        )

        assert read_auxiliary_system(client, foam["id"])["status"] == "WITHDRAWN"
        assert_flow(
            read_project(client, ctx["project_id"])["total_system_demand_gpm"],
            PROJECT_TOTAL_DEMAND_GPM,
        )
        rows, meta = validate_paginated(
            client.list_auxiliary_systems(
                make_contractor_headers(),
                params={"project_id": ctx["project_id"], "status": "WITHDRAWN"},
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [foam["id"]]

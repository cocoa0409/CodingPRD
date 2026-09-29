"""The two deep invalidation cascades: the major comment and the failed witness."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.assertions import (
    assert_flow,
    assert_posture,
    assert_pressure,
    assert_reopened,
    assert_sheet_counters,
)
from test_helpers.factories import (
    build_commission_payload,
    build_hazard_area_payload,
    build_record_witness_payload,
)
from test_helpers.fixtures import (
    HC1_REQUIRED_PSI,
    HC1_TOTAL_DEMAND_GPM,
    STANDPIPE_DEMAND_GPM,
    complete_review,
    create_auxiliary_system,
    open_acceptance_test,
    raise_comment,
    read_auxiliary_system,
    read_calculation,
    read_project,
    read_shop_drawing,
    read_trade_clearance,
    schedule_witness,
    build_under_review_stage,
    build_permitted_stage,
)
from test_helpers.test_users import (
    make_ahj_reviewer_headers,
    make_contractor_headers,
    make_design_engineer_headers,
)

MAJOR_COMMENT = dict(
    code_section="NFPA 13 14.2.9",
    severity="MAJOR",
    description="Most demanding area is not the remote area; rerun with the corner bay",
)


def _cascade_a(client):
    """Raise the MAJOR comment and close the pass, which fires the four-link cascade."""
    ctx = build_under_review_stage(client)
    ctx["comment"] = raise_comment(
        client,
        ctx["submittal_id"],
        ctx["reviewer_id"],
        assigned_engineer_id=ctx["lead_id"],
        **MAJOR_COMMENT,
    )
    ctx["submittal"] = complete_review(client, ctx["submittal_id"], ctx["reviewer_id"])
    return ctx


class TestMajorCommentCascade:
    def test_01_the_sealed_calculation_reopens_and_names_the_package_that_did_it(
        self, client
    ):
        """Every calculation named in `included_calculation_ids` whose state is `SEALED`
        moves `SEALED → REOPENED`, with `stale_reason` set to `MAJOR_COMMENT` and
        `reopened_by_submittal_id` set to this package.

        Design: Difficulty/transitive_cascade/major_comment_cascade_a_depth_four_invalidates_seal_sheet_and_clearances
        """
        ctx = _cascade_a(client)
        submittal = ctx["submittal"]
        assert submittal["state"] == "COMMENTS_ISSUED"
        assert submittal["major_comment_count"] == 1
        assert submittal["open_comment_count"] == 1

        calculation = read_calculation(client, ctx["calculation_id"])
        assert_reopened(calculation, "MAJOR_COMMENT")
        assert calculation["reopened_by_submittal_id"] == ctx["submittal_id"]
        assert read_project(client, ctx["project_id"])["sealed_calculation_count"] == 0

    def test_02_the_sheet_and_every_cleared_trade_item_below_it_go_stale(self, client):
        """Every `COORDINATED` shop drawing over those calculations becomes `STALE`, and
        every `CLEARED` trade item of those sheets becomes `STALE` with the sheet's
        `cleared_trade_count` reset to 0.

        Design: Difficulty/transitive_cascade/major_comment_cascade_a_depth_four_invalidates_seal_sheet_and_clearances
        """
        ctx = _cascade_a(client)
        assert_sheet_counters(read_shop_drawing(client, ctx["sheet_id"]), "STALE", 0)
        for cleared in ctx["clearances"]:
            item = read_trade_clearance(client, ctx["sheet_id"], cleared["id"])
            assert item["state"] == "STALE", f"{item['trade']} item was left behind"

    def test_03_the_project_gates_and_drops_the_reopened_calculation_from_the_ledger(
        self, client
    ):
        """The project's `open_major_comment_count` is recounted, driving the posture to
        `GATED`, the demand ledger is recomputed — a `REOPENED` calculation is not
        eligible, so the governing selection may change or empty.

        Design: Difficulty/transitive_cascade/major_comment_cascade_a_depth_four_invalidates_seal_sheet_and_clearances
        """
        ctx = _cascade_a(client)
        project = read_project(client, ctx["project_id"])
        assert project["open_major_comment_count"] == 1
        assert_posture(project, "GATED")
        assert project["status"] == "PERMIT_REVIEW"

        # The standpipe is untouched, so only the governing half of the ledger empties.
        assert project["governing_hydraulic_calculation_id"] is None
        assert_flow(project["governing_demand_gpm"], 0.0)
        assert_flow(project["auxiliary_demand_gpm"], STANDPIPE_DEMAND_GPM)
        assert_flow(project["total_system_demand_gpm"], STANDPIPE_DEMAND_GPM)


OUTAGE_START = "2026-09-05T08:00:00.000Z"
OUTAGE_END = "2026-09-05T16:00:00.000Z"
WITNESS_START = "2026-09-10T09:00:00.000Z"
WITNESS_END = "2026-09-10T11:00:00.000Z"
CLASS_II_DEMAND_GPM = 100.0
PROJECT_DEMAND_WITH_BOTH_STANDPIPES = 2230.0
REQUIRED_FLOW_GPM = 2118.5


def _booked_witness(client):
    """A permitted project with one commissioned and one proposed standpipe, and an
    acceptance test whose thresholds froze against the full ledger."""
    ctx = build_permitted_stage(client)
    ctx["commissioned"] = ctx["standpipe"]
    ctx["proposed"] = create_auxiliary_system(
        client,
        ctx["project_id"],
        ctx["lead_id"],
        system_type="STANDPIPE_CLASS_II",
        label="Office hose station",
        riser_count=1,
    )
    validate_success(
        client.commission_auxiliary_system(
            ctx["commissioned"]["id"],
            build_commission_payload(
                outage_start_at=OUTAGE_START, outage_end_at=OUTAGE_END
            ),
            make_contractor_headers(),
        )
    )
    ctx["acceptance_test"] = open_acceptance_test(client, ctx["project_id"])
    ctx["acceptance_test"] = schedule_witness(
        client,
        ctx["acceptance_test"]["id"],
        ctx["reviewer_id"],
        WITNESS_START,
        WITNESS_END,
    )
    return ctx


def _record_shortfall(client, ctx):
    return validate_success(
        client.record_witness(
            ctx["acceptance_test"]["id"],
            build_record_witness_payload(
                measured_flow_gpm=2000.0, measured_residual_psi=61.00
            ),
            make_ahj_reviewer_headers(ctx["reviewer_id"]),
        )
    )


class TestWitnessFailureCascade:
    def test_04_a_flow_shortfall_alone_fails_the_test_against_its_frozen_thresholds(
        self, client
    ):
        """The test passes only when both readings meet or exceed their threshold:
        `measured_flow_gpm` at least `required_flow_gpm` **and** `measured_residual_psi`
        at least `required_residual_psi`.

        Design: Difficulty/transitive_cascade/witness_failure_cascade_b_freezes_project_and_decommissions_only_commissioned_systems
        """
        ctx = _booked_witness(client)
        booked = ctx["acceptance_test"]
        assert_flow(booked["required_flow_gpm"], REQUIRED_FLOW_GPM)
        assert_pressure(booked["required_residual_psi"], HC1_REQUIRED_PSI)
        assert booked["witness_status"] == "SCHEDULED"

        recorded = _record_shortfall(client, ctx)
        assert recorded["witness_status"] == "WITNESSED_FAIL"
        assert_flow(recorded["measured_flow_gpm"], 2000.0)
        assert_pressure(recorded["measured_residual_psi"], 61.00)
        assert recorded["measured_residual_psi"] >= booked["required_residual_psi"]
        assert recorded["measured_flow_gpm"] < booked["required_flow_gpm"]

        # The documentation dimension is untouched by the witness visit.
        assert recorded["documentation_status"] == "PENDING"
        assert recorded["retest_count"] == 0

    def test_05_only_the_commissioned_sibling_is_decommissioned(self, client):
        """every auxiliary system of the project whose `status` is `COMMISSIONED` moves to
        `DECOMMISSIONED_PENDING_RETEST` with both `outage_start_at` and `outage_end_at`
        cleared to null.

        Design: Difficulty/transitive_cascade/witness_failure_cascade_b_freezes_project_and_decommissions_only_commissioned_systems
        """
        ctx = _booked_witness(client)
        _record_shortfall(client, ctx)

        decommissioned = read_auxiliary_system(client, ctx["commissioned"]["id"])
        assert decommissioned["status"] == "DECOMMISSIONED_PENDING_RETEST"
        assert decommissioned["outage_start_at"] is None
        assert decommissioned["outage_end_at"] is None
        assert_flow(decommissioned["demand_gpm"], STANDPIPE_DEMAND_GPM)

        skipped = read_auxiliary_system(client, ctx["proposed"]["id"])
        assert skipped["status"] == "PROPOSED", "a never-commissioned system is skipped"
        assert_flow(skipped["demand_gpm"], CLASS_II_DEMAND_GPM)

        # A suspended system is not a withdrawn one, so the ledger does not move.
        project = read_project(client, ctx["project_id"])
        assert_flow(
            project["auxiliary_demand_gpm"], STANDPIPE_DEMAND_GPM + CLASS_II_DEMAND_GPM
        )
        assert_flow(project["governing_demand_gpm"], HC1_TOTAL_DEMAND_GPM)
        assert_flow(
            project["total_system_demand_gpm"], PROJECT_DEMAND_WITH_BOTH_STANDPIPES
        )

    def test_06_the_freeze_is_observable_on_the_very_next_design_write(self, client):
        """the project moves `ACCEPTANCE → CORRECTIVE_ACTION` and its `design_posture`
        becomes `FROZEN`, which suspends the entire design surface listed in section 2.5.

        Design: Difficulty/transitive_cascade/witness_failure_cascade_b_freezes_project_and_decommissions_only_commissioned_systems
        """
        ctx = _booked_witness(client)
        assert read_project(client, ctx["project_id"])["status"] == "ACCEPTANCE"
        _record_shortfall(client, ctx)

        project = read_project(client, ctx["project_id"])
        assert project["status"] == "CORRECTIVE_ACTION"
        assert_posture(project, "FROZEN")

        refused = client.create_hazard_area(
            build_hazard_area_payload(
                project_id=ctx["project_id"],
                label="Mezzanine storage",
                hazard_class="ORDINARY_1",
                commodity_class="CLASS_II",
                storage_height_ft=8.0,
                ceiling_height_ft=18.0,
                area_sqft=4000.0,
                ceiling_slope_pct=None,
                room_area_sqft=None,
                enclosure_rating_hours=None,
                room_has_unprotected_opening=None,
            ),
            make_design_engineer_headers(ctx["lead_id"]),
        )
        validate_error(refused, "ERR_PROJECT_POSTURE_FROZEN", expected_status=409)

        # The frozen design itself is preserved, not unwound.
        assert read_calculation(client, ctx["calculation_id"])["state"] == "SEALED"
        assert read_project(client, ctx["project_id"])["sealed_calculation_count"] == 1

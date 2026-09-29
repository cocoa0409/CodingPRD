"""Optimistic concurrency on the application record and the immediacy of derived effects."""
from test_helpers import ApiErrorId, TEST_USERS, api_client, make_filer_headers
from test_helpers.factories import benefits_plan_payload, pro_forma_schedule_payload
from test_helpers.fixtures import (
    accept_application,
    create_acquirer,
    create_application,
    create_regulatory_schedule,
    create_target,
    designate_for_divestiture,
    granite_market_world,
    read_analysis,
    read_application,
    read_branch,
    reset_clock_to_epoch,
    submit_application,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]


class TestScheduleWriteConcurrency:
    """The schedule write is guarded against a stale view of its parent application."""

    def test_01_a_schedule_written_against_a_superseded_version_is_rejected(self):
        """PRD §2.6: "Creating a pro forma capital schedule requires `expected_application_version` as
        a non-optional field of the request body, carrying the client's last observed `version` of the
        referenced `MergerApplication`."
        PRD §2.6: "If that value does not equal the application's current `version`, the create is
        rejected with `ERR_STALE_APPLICATION_VERSION` at HTTP 412."
        PRD §3.2: "Whenever any examiner score changes the composite and the rating are recomputed by
        the same per-product rounding procedure, and the amendment increments the application's
        `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/stale_application_version_is_rejected_on_the_schedule_write
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(acquirer["id"], target["id"])
        assert application["version"] == 1
        amended = validate_success(api_client.amend_merger_application(
            application["id"], {"total_consideration_usd": 255_000_000},
            make_filer_headers(acquirer["id"])))
        assert amended["version"] == 2

        stale = api_client.create_pro_forma_schedule(
            pro_forma_schedule_payload(application["id"], 1), make_filer_headers(acquirer["id"]))

        validate_error(stale, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value, 412)
        schedules, meta = validate_paginated(api_client.list_pro_forma_schedules(
            ANALYST, params={"application_id": application["id"]}))
        assert meta["total_count"] == 0
        assert schedules == []
        assert read_application(application["id"], acquirer["id"])["version"] == 2, (
            "a failed concurrency check never bumps the counter"
        )

    def test_02_the_same_schedule_lands_once_the_client_refreshes_the_version(self):
        """PRD §2.6: "If that value does not equal the application's current `version`, the create is
        rejected with `ERR_STALE_APPLICATION_VERSION` at HTTP 412."
        PRD §3.3: "Building a new schedule on a basis moves the prior current schedule of that same
        basis to `SUPERSEDED`, and increments the application's `version` by 1."
        PRD §3.3: "When the common-equity ratio is at least 7.00 percent and the leverage ratio is at
        least 5.00 percent, the flag is `WELL_CAPITALIZED`."

        Design: Corner/cross_cutting_complexity_layers/stale_application_version_is_rejected_on_the_schedule_write
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(acquirer["id"], target["id"])
        validate_success(api_client.amend_merger_application(
            application["id"], {"total_consideration_usd": 255_000_000},
            make_filer_headers(acquirer["id"])))
        current_version = read_application(application["id"], acquirer["id"])["version"]

        schedule = validate_success(api_client.create_pro_forma_schedule(
            pro_forma_schedule_payload(application["id"], current_version),
            make_filer_headers(acquirer["id"])), 201)

        assert schedule["status"] == "CURRENT"
        assert schedule["capital_adequacy_flag"] == "WELL_CAPITALIZED"
        assert read_application(application["id"], acquirer["id"])["version"] == 3, (
            "the accepted write is the one that bumps the parent"
        )


class TestBenefitsPlanWriteConcurrency:
    """The two guarded writes share one version counter on the application."""

    def test_03_a_plan_proposed_against_a_superseded_version_is_rejected(self):
        """PRD §2.6: "Proposing a community benefits plan likewise requires
        `expected_application_version` as a non-optional field carrying the client's last observed
        `version` of the referenced `MergerApplication`, and a value that does not equal the
        application's current `version` is rejected with `ERR_STALE_APPLICATION_VERSION` at HTTP 412."
        PRD §2.6: "Two write operations hang off the merger application in a way that is legitimate on
        its own terms but destructive if the client's picture of the application is out of date, and
        both are therefore guarded by optimistic concurrency control against the application record."

        Design: Corner/cross_cutting_complexity_layers/stale_application_version_is_rejected_on_the_benefits_plan_write
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(acquirer["id"], target["id"])
        create_regulatory_schedule(application["id"], acquirer["id"], expected_version=1)
        assert read_application(application["id"], acquirer["id"])["version"] == 2, (
            "the schedule write moved the counter the plan writer was holding"
        )

        stale = api_client.create_benefits_plan(
            benefits_plan_payload(application["id"], 1), make_filer_headers(acquirer["id"]))

        validate_error(stale, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value, 412)
        plans, meta = validate_paginated(api_client.list_benefits_plans(
            ANALYST, params={"application_id": application["id"]}))
        assert meta["total_count"] == 0
        assert plans == []
        assert read_application(application["id"], acquirer["id"])["version"] == 2

    def test_04_the_plan_lands_on_the_refreshed_version(self):
        """PRD §2.6: "Proposing a community benefits plan likewise requires
        `expected_application_version` as a non-optional field carrying the client's last observed
        `version` of the referenced `MergerApplication`, and a value that does not equal the
        application's current `version` is rejected with `ERR_STALE_APPLICATION_VERSION` at HTTP 412."
        PRD §3.9: "A new plan is created with `status` `PROPOSED`, every monetary aggregate at 0 —
        `total_committed_usd`, `annual_target_total_usd`, `quarterly_target_total_usd`,
        `credited_to_date_usd` and `remaining_commitment_usd` — with `compliance_status` `COMPLIANT`,
        `consecutive_deficient_periods` at 0 and `filed_report_count` at 0."
        PRD §3.9: "Creating it moves the application's prior `PROPOSED` plan to `SUPERSEDED` and
        increments the application's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/stale_application_version_is_rejected_on_the_benefits_plan_write
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        application = create_application(acquirer["id"], target["id"])
        create_regulatory_schedule(application["id"], acquirer["id"], expected_version=1)
        current_version = read_application(application["id"], acquirer["id"])["version"]

        plan = validate_success(api_client.create_benefits_plan(
            benefits_plan_payload(application["id"], current_version),
            make_filer_headers(acquirer["id"])), 201)

        assert plan["status"] == "PROPOSED"
        assert plan["total_committed_usd"] == 0
        assert plan["filed_report_count"] == 0
        assert read_application(application["id"], acquirer["id"])["version"] == 3


class TestDerivedEffectsAreImmediate:
    """A designation's cascade is visible in its own response and in the very next read."""

    def test_05_a_divestiture_designation_moves_the_analysis_and_the_posture_at_once(self):
        """PRD §3.6: "The competitive analysis for that application and the branch's market recomputes
        `designated_divestiture_deposits_usd`, `hhi_post_mitigated` and `mitigation_satisfied`."
        PRD §3.6: "The application's `competitive_posture` is then re-rolled from all of its
        analyses."
        PRD §3.5: "Otherwise, if any analysis has a `screen_result` other than `PASS`, the posture is
        `CLEARED_WITH_DIVESTITURE` — a market that failed its screen but is fully mitigated still
        unblocks the case while recording that divestiture was needed."
        PRD §3.5: "Steps 1 through 3 look only at current ownership and the unmitigated merger; steps
        4 through 6 layer mitigation on top and never revisit the first three."

        Design: Corner/consistency_model/designation_effects_are_visible_in_the_same_response_and_the_next_read
        """
        world = granite_market_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        create_regulatory_schedule(application_id, acquirer_id)
        submit_application(application_id, acquirer_id)
        accept_application(application_id)
        assert world["analysis"]["screen_result"] == "PRESUMPTIVE_VIOLATION"
        assert read_application(application_id, acquirer_id)["competitive_posture"] == "BLOCKED"

        designated = designate_for_divestiture(
            world["branch_target"]["id"], application_id, acquirer_id)

        assert designated["status"] == "DESIGNATED_FOR_DIVESTITURE", (
            "the write is observable in its own response, with no second call"
        )
        assert designated["designation_application_id"] == application_id
        analysis = read_analysis(world["analysis"]["id"])
        assert analysis["designated_divestiture_deposits_usd"] == 200_000_000
        assert analysis["hhi_post_mitigated"] == 3800, (
            "50.0000 squared plus 30.0000 squared plus 20.0000 squared, with no polling and no retry"
        )
        assert analysis["mitigation_satisfied"] is True
        assert analysis["hhi_delta_unmitigated"] == 1200, (
            "only the mitigation fields moved"
        )
        assert analysis["required_divestiture_deposits_usd"] == 139_000_000
        assert read_application(application_id, acquirer_id)["competitive_posture"] == (
            "CLEARED_WITH_DIVESTITURE"), "the parent rollup is recomputed synchronously"
        assert read_branch(world["branch_target"]["id"])["status"] == "DESIGNATED_FOR_DIVESTITURE"

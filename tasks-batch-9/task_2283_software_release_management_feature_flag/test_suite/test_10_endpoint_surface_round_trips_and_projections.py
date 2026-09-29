"""Round trips, bulk actions, filtered projections and the narrow waiver escape."""

from test_helpers import (
    ApiErrorId,
    CanaryVerdict,
    ChangeState,
    CleanupState,
    DeliveryState,
    EnvironmentTier,
    FlagState,
    RiskClass,
    StepState,
    VerificationState,
    assert_instant,
    assert_stale_debt,
    assert_sweep_summary,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_ORIGIN
from test_helpers.factories import (
    make_complete_payload,
    make_staging_environment_payload,
)
from test_helpers.fixtures import (
    canary_deployment_in_soak,
    create_environment,
    read_deployment,
    read_environment,
    read_flag,
    read_step,
    reset_clock,
    run_canary_evaluation,
    run_cleanup_sweep,
    scenario_three_changes_across_risk_bands,
    scenario_two_soaking_flags_one_past_its_deadline,
)
from test_helpers.test_users import CHANGE_APPROVER, PLATFORM_ADMIN, SRE

#: The half-open observation window that closes before the only canary sample.
EMPTY_WINDOW_START_AT = "2026-08-11T02:00:00Z"
EMPTY_WINDOW_END_AT = "2026-08-11T02:05:00Z"


class TestEnvironmentRoundTrip:
    """An environment is written once and read back by everyone who deploys."""

    def test_the_read_returns_the_stored_window_cooldown_and_regulated_flag(self, api):
        """"``cooldown_minutes``, the mandatory quiet buffer appended after every
        occupied window on this environment, defaulting to 30", and a duplicate
        ``name`` "is reported as ``ERR_INVALID_REQUEST``".

        Design: Corner/endpoints/create_and_read_environment_round_trip
        """
        reset_clock(api)

        created = create_environment(
            api,
            cooldown_minutes=45,
            requires_compliance_evidence=True,
        )
        fetched = validate_success(api.get_environment(created["id"], SRE), 200)
        duplicate = api.create_environment(
            make_staging_environment_payload(name="prod-us"), PLATFORM_ADMIN
        )

        assert fetched["id"] == created["id"]
        assert fetched["name"] == "prod-us"
        assert fetched["tier"] == EnvironmentTier.PROD
        assert fetched["deploy_window_start_hour_utc"] == 2
        assert fetched["deploy_window_end_hour_utc"] == 6
        assert fetched["cooldown_minutes"] == 45
        assert fetched["requires_compliance_evidence"] is True
        assert fetched["version"] == 1
        validate_error(duplicate, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


class TestCleanupSweepBulkAction:
    """"The sweep does more than relabel"."""

    def test_one_sweep_pauses_the_stale_flag_and_leaves_the_compliant_one_rolling(
        self, api
    ):
        """"a flag that has newly become ``ENFORCED`` and whose ``state`` is
        ``ACTIVE_ROLLING_OUT`` is moved to ``PAUSED`` with ``kill_switch_engaged``
        set to true; on each such flag, every step whose ``state`` is ``PLANNED``
        becomes ``VOIDED``, and every step whose ``state`` is ``SOAKING`` becomes
        ``ABORTED``".

        Design: Corner/endpoints/flag_cleanup_sweep_enforces_and_reports_per_bucket_counts
        """
        built = scenario_two_soaking_flags_one_past_its_deadline(api)
        assert built["stale_flag"]["cleanup_state"] == CleanupState.COMPLIANT

        summary = run_cleanup_sweep(api)

        assert_sweep_summary(
            summary,
            evaluated_count=2,
            enforced_count=1,
            overdue_count=0,
            warning_count=1,
            paused_flag_count=1,
            aborted_step_count=1,
            voided_step_count=1,
        )
        stale = read_flag(api, built["stale_flag"]["id"])
        assert_stale_debt(stale, 60, CleanupState.ENFORCED)
        assert stale["state"] == FlagState.PAUSED
        assert stale["kill_switch_engaged"] is True
        assert float(stale["current_exposure_pct"]) == 0.0
        assert stale["applied_step_count"] == 0
        assert read_step(api, built["soaking_step"]["id"])["state"] == StepState.ABORTED
        assert read_step(api, built["planned_step"]["id"])["state"] == StepState.VOIDED
        fresh = read_flag(api, built["fresh_flag"]["id"])
        # The fresh flag is an orphan too, so it owes the fifteen orphan points
        # and sits in WARNING; only ENFORCED stops a rollout.
        assert_stale_debt(fresh, 15, CleanupState.WARNING)
        assert fresh["state"] == FlagState.ACTIVE_ROLLING_OUT
        assert read_step(api, built["fresh_step"]["id"])["state"] == StepState.SOAKING
        assert_instant(stale["last_sweep_at"], CLOCK_ORIGIN, "last_sweep_at")
        assert_instant(fresh["last_sweep_at"], CLOCK_ORIGIN, "last_sweep_at")


class TestFilteredChangeRequestProjection:
    """"Change requests of a release may be filtered by ``state``"."""

    def test_the_filtered_page_carries_each_row_s_pinned_score_and_tier(self, api):
        """"``risk_class`` is the tier of that value — so the tier a change is routed
        by is always the preliminary tier", and the final variant "happens once on
        entry into ``state`` ``APPROVED``".

        Design: Corner/endpoints/list_change_requests_reports_computed_risk_fields_per_row
        """
        built = scenario_three_changes_across_risk_bands(api)
        release_id = built["release"]["id"]

        rows, meta = validate_paginated(
            api.list_release_change_requests(
                release_id, CHANGE_APPROVER, {"state": ChangeState.RISK_CLASSIFIED}
            )
        )

        assert meta["total_count"] == 2
        assert len(rows) == 2
        by_id = {row["id"]: row for row in rows}
        assert by_id[built["medium"]["id"]]["risk_score_preliminary"] == 33
        assert by_id[built["medium"]["id"]]["risk_class"] == RiskClass.MEDIUM
        assert by_id[built["high"]["id"]]["risk_score_preliminary"] == 62
        assert by_id[built["high"]["id"]]["risk_class"] == RiskClass.HIGH
        assert built["low"]["id"] not in by_id
        assert built["low"]["risk_score_preliminary"] == 9
        assert built["low"]["risk_class"] == RiskClass.LOW
        assert all(row["risk_score_final"] is None for row in rows)
        _, unfiltered = validate_paginated(
            api.list_release_change_requests(release_id, CHANGE_APPROVER)
        )
        assert unfiltered["total_count"] == 3


class TestVerificationWaiverIsNarrow:
    """"The optional ``waive_verification`` input offers a narrow escape"."""

    def test_a_production_canary_cannot_buy_its_way_out_of_an_inconclusive_verdict(
        self, api
    ):
        """"setting it true is honoured **only** when the deployment's
        ``verification_state`` is currently ``INCONCLUSIVE`` **and** the target
        environment's ``tier`` is not ``PROD``".

        Design: Corner/endpoints/waive_verification_on_prod_canary_is_refused_returns_canary_not_passing
        """
        built = canary_deployment_in_soak(api)
        deployment_id = built["deployment"]["id"]
        assert built["prod_env"]["tier"] == EnvironmentTier.PROD
        assert built["deployment"]["verification_state"] == VerificationState.PENDING

        plain = api.complete_deployment(deployment_id, make_complete_payload(), SRE)
        evaluation = run_canary_evaluation(
            api, deployment_id, EMPTY_WINDOW_START_AT, EMPTY_WINDOW_END_AT
        )
        waived = api.complete_deployment(
            deployment_id, make_complete_payload(waive_verification=True), SRE
        )

        validate_error(plain, ApiErrorId.ERR_CANARY_NOT_PASSING.value, 409)
        assert evaluation["verdict"] == CanaryVerdict.INCONCLUSIVE
        assert evaluation["sample_count"] == 0
        assert float(evaluation["weighted_health_score"]) == 0.0
        assert evaluation["abort_triggered"] is False
        validate_error(waived, ApiErrorId.ERR_CANARY_NOT_PASSING.value, 409)
        deployment = read_deployment(api, deployment_id)
        assert deployment["verification_state"] == VerificationState.INCONCLUSIVE
        assert deployment["delivery_state"] == DeliveryState.CANARY_SOAK
        assert deployment["completed_at"] is None
        assert read_environment(api, built["prod_env"]["id"])[
            "active_deployment_count"
        ] == 1

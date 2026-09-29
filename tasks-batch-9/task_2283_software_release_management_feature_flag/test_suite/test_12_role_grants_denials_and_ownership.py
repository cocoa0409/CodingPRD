"""Who may act: role grants, cross-role denials, anonymity and flag ownership."""

from test_helpers import (
    ApiErrorId,
    CleanupState,
    EvidenceItem,
    FlagState,
    PacketState,
    ReleasePhase,
    StepState,
    TrainPhase,
    assert_instant,
    assert_missing_items,
    assert_stale_debt,
    assert_sweep_summary,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_ORIGIN, RELEASE_FREEZE_AT
from test_helpers.factories import (
    make_deployment_payload,
    make_evidence_packet_payload,
    make_rollout_step_payload,
    make_staging_environment_payload,
)
from test_helpers.fixtures import (
    create_flag,
    create_train,
    current_flag_version,
    grant_freeze_exception,
    plan_step,
    read_environment,
    read_flag,
    read_release,
    read_train,
    reset_clock,
    run_cleanup_sweep,
    scenario_cut_release_and_one_overdue_orphan_flag,
    scenario_open_release_and_environment,
    start_soak,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    ENGINEER,
    ENGINEER_USER_ID,
    OTHER_ENGINEER,
    RELEASE_MANAGER,
    SRE,
    headers_without_user_id,
)

#: The window an SRE would have reserved had the role been permitted to.
CANDIDATE_WINDOW_START_AT = "2026-08-10T02:00:00Z"
CANDIDATE_WINDOW_END_AT = "2026-08-10T04:00:00Z"


class TestComplianceOfficerExclusiveOperations:
    """The three operations no other role may reach, driven by one officer."""

    def test_one_officer_grants_the_exception_runs_the_sweep_and_assembles_the_packet(
        self, api
    ):
        """"A ``ComplianceOfficer`` grants a **freeze exception** on a specific release
        by supplying a ``justification``", "A ``ComplianceOfficer`` triggers a
        **cleanup sweep**, which re-evaluates staleness for every flag whose ``state``
        is not ``ARCHIVED``", and "A ``ComplianceOfficer`` assembles a **compliance
        evidence packet** for a release, supplying only the
        ``expected_release_version`` of §2.7".

        Design: Corner/rbac/compliance_officer_can_perform_its_exclusive_operations
        """
        built = scenario_cut_release_and_one_overdue_orphan_flag(api)
        release_id = built["release"]["id"]

        excepted = grant_freeze_exception(api, release_id)
        sweep = run_cleanup_sweep(api)
        seen_version = validate_success(
            api.get_release(release_id, COMPLIANCE_OFFICER), 200
        )["version"]
        packet = validate_success(
            api.create_evidence_packet(
                release_id,
                make_evidence_packet_payload(seen_version),
                COMPLIANCE_OFFICER,
            ),
            201,
        )

        assert excepted["freeze_exception_approved"] is True
        assert read_train(api, built["train"]["id"])["freeze_exception_count"] == 1
        assert_sweep_summary(
            sweep,
            evaluated_count=1,
            overdue_count=1,
            enforced_count=0,
            warning_count=0,
            paused_flag_count=0,
        )
        orphan = read_flag(api, built["orphan"]["id"])
        assert_stale_debt(orphan, 51, CleanupState.OVERDUE)
        assert_instant(orphan["last_sweep_at"], RELEASE_FREEZE_AT, "last_sweep_at")
        assert packet["state"] == PacketState.DRAFT
        assert packet["base_index"] == 75
        assert packet["waiver_count"] == 0
        assert_missing_items(
            packet, [EvidenceItem.CANARY_PASS, EvidenceItem.RELEASE_NOTES]
        )
        assert read_release(api, release_id)["version"] == seen_version + 1


class TestPeerRolesCannotCrossOver:
    """Every one of these operations belongs to exactly one other role."""

    def test_each_role_is_refused_the_operation_that_belongs_to_a_peer(self, api):
        """"A well-authenticated request whose role is not listed for the target
        endpoint in §4 is rejected with ``ERR_ROLE_NOT_PERMITTED`` (403)", a check
        whose rank reads "The acting role appears in the endpoint's authorized-role
        list in §4 — otherwise ``ERR_ROLE_NOT_PERMITTED`` (403). All endpoints".

        Design: Corner/rbac/engineer_cannot_create_environment_and_sre_cannot_cut_release
        """
        built = scenario_open_release_and_environment(api)
        release_id = built["release"]["id"]
        assert built["release"]["phase"] == ReleasePhase.OPEN

        environment_refusal = api.create_environment(
            make_staging_environment_payload(name="rogue-env"), ENGINEER
        )
        cut_refusal = api.cut_release(release_id, {}, SRE)
        deployment_refusal = api.create_deployment(
            release_id,
            make_deployment_payload(
                built["environment"]["id"],
                window_start_at=CANDIDATE_WINDOW_START_AT,
                window_end_at=CANDIDATE_WINDOW_END_AT,
            ),
            RELEASE_MANAGER,
        )

        for refusal in (environment_refusal, cut_refusal, deployment_refusal):
            validate_error(refusal, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        release = read_release(api, release_id)
        assert release["phase"] == ReleasePhase.OPEN
        assert release["readiness_score_attested"] is None
        assert read_train(api, built["train"]["id"])["open_release_count"] == 1
        environment = read_environment(api, built["environment"]["id"])
        assert environment["active_deployment_count"] == 0
        _, meta = validate_paginated(api.list_deployments(SRE))
        assert meta["total_count"] == 0


class TestAuthenticationPrecedesEverything:
    """An anonymous request is never told what else was wrong with it."""

    def test_the_headerless_call_is_unauthenticated_rather_than_malformed(self, api):
        """"A request missing either header, carrying a blank value in either, or naming
        a role outside those six is rejected with ``ERR_UNAUTHENTICATED`` (401)", the
        first rank of the ladder: "Both authentication headers are present and
        non-blank and the role is one of the six declared names".

        Design: Corner/rbac/missing_x_user_id_header_returns_unauthenticated
        """
        reset_clock(api)

        anonymous = api.create_release_train(
            {"name": "core-train"}, headers_without_user_id()
        )
        accepted = create_train(api)

        validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert accepted["name"] == "core-train"
        assert accepted["open_release_count"] == 0
        assert accepted["freeze_exception_count"] == 0
        assert accepted["phase"] == TrainPhase.ACTIVE


class TestFlagOwnershipBeyondTheRole:
    """The Engineer role opens the door; ownership decides who walks through."""

    def test_a_second_engineer_may_neither_plan_a_rung_nor_start_the_soak(self, api):
        """"Flag operations — planning a rollout step, starting a soak, applying a
        soaked step, resuming a paused flag, and archiving a flag — require
        ``X-User-ID`` to equal the flag's ``owner_user_id``", and both ownership
        comparisons "yield ``ERR_NOT_RESOURCE_OWNER`` (403) when they fail".

        Design: Corner/rbac/non_owner_engineer_cannot_start_soak_returns_not_resource_owner
        """
        reset_clock(api)
        flag = create_flag(api)
        step = plan_step(api, flag["id"], target_pct=5, soak_minutes=30)
        assert flag["owner_user_id"] == ENGINEER_USER_ID

        stranger_soak = api.start_soak(step["id"], {}, OTHER_ENGINEER)
        stranger_plan = api.create_rollout_step(
            flag["id"],
            make_rollout_step_payload(
                current_flag_version(api, flag["id"]), target_pct=5, soak_minutes=30
            ),
            OTHER_ENGINEER,
        )
        owner_soak = start_soak(api, step["id"])

        validate_error(stranger_soak, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
        validate_error(stranger_plan, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
        assert owner_soak["state"] == StepState.SOAKING
        assert_instant(owner_soak["soak_started_at"], CLOCK_ORIGIN, "soak_started_at")
        settled = read_flag(api, flag["id"])
        assert settled["state"] == FlagState.ACTIVE_ROLLING_OUT
        _, meta = validate_paginated(
            api.list_rollout_steps(ENGINEER, {"feature_flag_id": flag["id"]})
        )
        assert meta["total_count"] == 1

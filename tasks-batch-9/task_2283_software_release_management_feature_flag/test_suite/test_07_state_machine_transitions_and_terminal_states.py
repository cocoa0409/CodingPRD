"""Initial states, valid transitions, refused transitions and terminal lockdown."""

from test_helpers import (
    ApiErrorId,
    CanaryVerdict,
    ChangeState,
    CleanupState,
    DeliveryState,
    FlagState,
    NoteAudience,
    NoteState,
    PacketState,
    ReleasePhase,
    StepState,
    TrainPhase,
    VerificationState,
    assert_canary_numbers,
    assert_deployment_dimensions,
    assert_evidence_index,
    assert_instant,
    assert_missing_items,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import CLOCK_ORIGIN, RELEASE_FREEZE_AT
from test_helpers.factories import make_change_request_payload
from test_helpers.fixtures import (
    archive_flag,
    assemble_packet,
    complete_deployment,
    create_change,
    cut_release_with_customer_facing_change,
    cut_release_with_merged_low_change,
    freeze_train,
    generate_notes,
    pause_flag,
    plan_step,
    publish_notes,
    read_change,
    read_deployment,
    read_environment,
    read_flag,
    read_note,
    read_packet,
    read_release,
    read_step,
    released_release,
    reset_clock,
    rollback_deployment,
    run_canary_evaluation,
    scenario_staging_canary_with_one_healthy_sample,
    scenario_train_with_approved_dependent_before_freeze,
    soaking_flag,
    submit_change,
    submitted_change,
    train_with_release,
    unfreeze_train,
)
from test_helpers.test_users import (
    ENGINEER,
    ENGINEER_USER_ID,
    RELEASE_MANAGER,
    SRE,
)

#: The instant the fully shipped release's production deployment was started.
DEPLOYMENT_START_AT = "2026-08-11T02:05:00Z"

#: A MEDIUM declaration: 300 lines over two subsystems, single-tenant blast radius.
MEDIUM_CHANGE = make_change_request_payload(
    title="Retry policy rewrite",
    summary_internal="Rewrite the retry policy across two subsystems.",
    lines_changed=300,
    touched_subsystem_count=2,
    declared_blast_radius="SINGLE_TENANT",
)


class TestFreshChangeRequestShape:
    """A change "begins in ``state`` ``DRAFT``"."""

    def test_authored_change_is_draft_with_null_scores_and_zero_counters(self, api):
        """"with ``risk_score_preliminary``, ``risk_score_final`` and ``risk_class``
        all null, ``dependency_depth`` at 0, all three approval counters ... at 0,
        ``merged_at`` null, and ``deployment_verified`` false".

        Design: Corner/state_machines/new_change_request_starts_in_draft_state
        """
        reset_clock(api)
        built = train_with_release(api)

        change = create_change(
            api,
            built["release"]["id"],
            title="Draft change",
            summary_internal="Authored but not yet submitted.",
            lines_changed=40,
            touched_subsystem_count=1,
            declared_blast_radius="INTERNAL",
        )

        assert change["state"] == ChangeState.DRAFT
        assert change["author_user_id"] == ENGINEER_USER_ID
        assert change["risk_score_preliminary"] is None
        assert change["risk_score_final"] is None
        assert change["risk_class"] is None
        assert change["approval_technical_count"] == 0
        assert change["approval_compliance_count"] == 0
        assert change["approval_cab_count"] == 0
        assert change["dependency_depth"] == 0
        assert change["merged_at"] is None
        assert change["deployment_verified"] is False
        release = read_release(api, built["release"]["id"])
        assert release["committed_change_count"] == 0
        assert release["readiness_score_projected"] == 100


class TestReleaseNotePublication:
    """"generating an empty document is legal, publishing one is not"."""

    def test_publishing_a_customer_document_stamps_published_at_from_the_clock(
        self, api
    ):
        """"Publication sets ``state`` to ``PUBLISHED``, stamps ``published_at``,
        increments the document's ``version``", leaving the selected content alone.

        Design: Corner/state_machines/release_note_document_draft_to_published_sets_published_at
        """
        built = cut_release_with_customer_facing_change(api)
        note = generate_notes(api, built["release"]["id"], NoteAudience.CUSTOMER)
        assert note["state"] == NoteState.DRAFT
        assert note["published_at"] is None

        published = publish_notes(api, note["id"])

        assert published["state"] == NoteState.PUBLISHED
        assert_instant(published["published_at"], RELEASE_FREEZE_AT, "published_at")
        assert_instant(published["generated_at"], RELEASE_FREEZE_AT, "generated_at")
        assert published["entry_count"] == 1
        assert published["included_change_ids"] == [built["change"]["id"]]
        assert published["excluded_change_count"] == 0

    def test_empty_customer_document_is_refused_while_the_internal_one_publishes(
        self, api
    ):
        """"a candidate is included only when its ``customer_facing`` is true **and**
        its ``summary_customer_facing`` is both non-null and not the empty string",
        and an empty document "requires ``entry_count`` to be at least 1".

        Design: Corner/state_machines/publish_release_notes_with_zero_entries_returns_empty_release_notes
        """
        built = cut_release_with_merged_low_change(api)
        release_id = built["release"]["id"]
        customer_note = generate_notes(api, release_id, NoteAudience.CUSTOMER)
        internal_note = generate_notes(api, release_id, NoteAudience.INTERNAL)

        refused = api.publish_release_notes(customer_note["id"], {}, RELEASE_MANAGER)
        published = publish_notes(api, internal_note["id"])

        assert customer_note["entry_count"] == 0
        assert customer_note["excluded_change_count"] == 1
        validate_error(refused, ApiErrorId.ERR_EMPTY_RELEASE_NOTES.value, 422)
        stayed_draft = read_note(api, release_id, customer_note["id"])
        assert stayed_draft["state"] == NoteState.DRAFT
        assert stayed_draft["published_at"] is None
        assert internal_note["entry_count"] == 1
        assert internal_note["excluded_change_count"] == 0
        assert published["state"] == NoteState.PUBLISHED


class TestPublicationRefreshesDraftEvidence:
    """Publication "has one cross-entity effect that is easy to miss"."""

    def test_published_customer_notes_lift_the_draft_packet_index_in_place(self, api):
        """"every ``DRAFT`` evidence packet belonging to the same release recomputes
        its ``base_index``, its ``waiver_credit_points`` and its
        ``completeness_index``, because published customer notes are themselves an
        evidence item".

        Design: Corner/state_machines/publishing_customer_notes_recomputes_draft_evidence_packet_index
        """
        built = cut_release_with_customer_facing_change(api)
        release_id = built["release"]["id"]
        note = generate_notes(api, release_id, NoteAudience.CUSTOMER)
        packet = assemble_packet(api, release_id)
        assert_evidence_index(
            packet, base_index=75, waiver_credit_points=0, completeness_index=75
        )

        publish_notes(api, note["id"])

        refreshed = read_packet(api, release_id, packet["id"])
        assert_evidence_index(
            refreshed, base_index=85, waiver_credit_points=0, completeness_index=85
        )
        assert_missing_items(refreshed, ["canary_pass"])
        assert refreshed["waiver_count"] == 0
        assert refreshed["state"] == PacketState.DRAFT


class TestChangeTransitionsAreNotIdempotent:
    """Rank 8 answers with "``ERR_CHANGE_STATE_INVALID`` ... according to the type of
    the path target"."""

    def test_merging_a_change_still_awaiting_approval_reports_the_state_conflict(
        self, api
    ):
        """"Merging is the author's act, permitted only from ``state`` ``APPROVED``",
        so a change that is still collecting approvals cannot merge.

        Design: Corner/state_machines/merge_change_request_from_risk_classified_returns_change_state_invalid
        """
        reset_clock(api)
        built = train_with_release(api)
        change = submitted_change(api, built["release"]["id"], payload=MEDIUM_CHANGE)
        assert change["state"] == ChangeState.RISK_CLASSIFIED

        response = api.merge_change_request(change["id"], {}, ENGINEER)

        validate_error(response, ApiErrorId.ERR_CHANGE_STATE_INVALID.value, 409)
        stayed = read_change(api, change["id"])
        assert stayed["state"] == ChangeState.RISK_CLASSIFIED
        assert stayed["merged_at"] is None
        assert read_release(api, built["release"]["id"])["committed_change_count"] == 0

    def test_a_second_submit_is_refused_and_does_not_re_pin_the_risk_score(self, api):
        """"a submission of a non-``DRAFT`` change" is refused with
        ``ERR_CHANGE_STATE_INVALID``, so the score the first submit pinned stands.

        Design: Corner/state_machines/second_submit_on_change_request_returns_change_state_invalid
        """
        reset_clock(api)
        built = train_with_release(api)
        change = create_change(api, built["release"]["id"], payload=MEDIUM_CHANGE)
        first = submit_change(api, change["id"])
        assert first["risk_score_preliminary"] == 33

        response = api.submit_change_request(change["id"], {}, ENGINEER)

        validate_error(response, ApiErrorId.ERR_CHANGE_STATE_INVALID.value, 409)
        stayed = read_change(api, change["id"])
        assert stayed["state"] == ChangeState.RISK_CLASSIFIED
        assert stayed["risk_score_preliminary"] == 33


class TestArchivedFlagIsTerminal:
    """"Archiving is permanent removal"."""

    def test_archival_voids_the_planned_rung_and_locks_out_a_later_resume(self, api):
        """"Archival sets ``state`` to ``ARCHIVED``, stamps ``archived_at``, resets
        ``cleanup_state`` to ``COMPLIANT`` and ``stale_debt_points`` to 0, voids every
        one of the flag's steps that is still ``PLANNED``".

        Design: Corner/state_machines/archived_feature_flag_cannot_be_resumed_or_receive_steps
        """
        reset_clock(api)
        built = soaking_flag(api)
        flag_id = built["flag"]["id"]
        planned = plan_step(api, flag_id, target_pct=5, soak_minutes=30)
        paused = pause_flag(api, flag_id, reason="flag no longer needed")
        assert paused["state"] == FlagState.PAUSED
        assert paused["kill_switch_engaged"] is False

        archived = archive_flag(api, flag_id)
        refused = api.resume_flag(flag_id, {}, ENGINEER)

        assert archived["state"] == FlagState.ARCHIVED
        assert_instant(archived["archived_at"], CLOCK_ORIGIN, "archived_at")
        assert archived["cleanup_state"] == CleanupState.COMPLIANT
        assert archived["stale_debt_points"] == 0
        assert read_step(api, planned["id"])["state"] == StepState.VOIDED
        assert read_step(api, built["step"]["id"])["state"] == StepState.SOAKING
        validate_error(refused, ApiErrorId.ERR_FLAG_STATE_INVALID.value, 409)
        assert read_flag(api, flag_id)["state"] == FlagState.ARCHIVED


class TestDeploymentDimensionsAreIndependent:
    """Verification and delivery are two dimensions "on the same record"."""

    def test_two_evaluations_move_verification_while_delivery_holds_at_canary_soak(
        self, api
    ):
        """"The deployment's ``verification_state`` is then written from the verdict",
        and only completion "sets ``delivery_state`` to ``COMPLETED``".

        Design: Corner/state_machines/deployment_verification_state_moves_independently_of_delivery_state
        """
        built = scenario_staging_canary_with_one_healthy_sample(api)
        deployment_id = built["reserved"]["id"]
        assert_deployment_dimensions(
            built["reserved"], DeliveryState.SCHEDULED, VerificationState.PENDING
        )

        first = run_canary_evaluation(
            api, deployment_id, "2026-08-10T02:00:00Z", "2026-08-10T02:30:00Z"
        )
        assert first["verdict"] == CanaryVerdict.INCONCLUSIVE
        assert first["sample_count"] == 0
        assert_deployment_dimensions(
            read_deployment(api, deployment_id),
            DeliveryState.CANARY_SOAK,
            VerificationState.INCONCLUSIVE,
        )

        second = run_canary_evaluation(
            api, deployment_id, "2026-08-10T02:30:00Z", "2026-08-10T02:45:00Z"
        )

        assert_canary_numbers(
            second,
            sample_count=10,
            error_rate_pct_rounded=0.0,
            latency_p95_ms=200,
            weighted_health_score=96.0,
            verdict=CanaryVerdict.PASS,
            abort_triggered=False,
        )
        assert_deployment_dimensions(
            read_deployment(api, deployment_id),
            DeliveryState.CANARY_SOAK,
            VerificationState.PASSING,
        )
        completed = complete_deployment(api, deployment_id)
        assert_deployment_dimensions(
            completed, DeliveryState.COMPLETED, VerificationState.PASSING
        )
        _, meta = validate_paginated(api.list_canary_evaluations(deployment_id, SRE))
        assert meta["total_count"] == 2


class TestTrainUnfreezeCompensatesTheFreeze:
    """"Unfreezing compensates that cascade rather than merely flipping the gate"."""

    def test_unfreeze_restores_the_states_and_the_ledger_without_drift(self, api):
        """"every change whose ``state`` is ``DEFERRED`` returns to ``state``
        ``RISK_CLASSIFIED``" and "every change whose ``state`` is
        ``BLOCKED_BY_DEPENDENCY`` returns to ``state`` ``APPROVED``", each
        restoration "re-incrementing its release's ``committed_change_count``".

        Design: Corner/state_machines/train_unfreeze_restores_open_phase_and_reinstates_deferred_changes
        """
        built = scenario_train_with_approved_dependent_before_freeze(api)
        release_id = built["release"]["id"]
        frozen = freeze_train(api, built["train"]["id"])
        assert frozen["phase"] == TrainPhase.FROZEN

        thawed = unfreeze_train(api, built["train"]["id"])

        assert thawed["phase"] == TrainPhase.ACTIVE
        assert thawed["open_release_count"] == 1
        release = read_release(api, release_id)
        assert release["phase"] == ReleasePhase.OPEN
        assert release["committed_change_count"] == 1
        assert release["risk_budget_consumed_points"] == 38
        assert release["readiness_score_projected"] == 100
        prerequisite = read_change(api, built["prerequisite"]["id"])
        dependent = read_change(api, built["dependent"]["id"])
        assert prerequisite["state"] == ChangeState.RISK_CLASSIFIED
        assert prerequisite["risk_score_preliminary"] == 28
        assert dependent["state"] == ChangeState.APPROVED
        assert dependent["risk_score_final"] == 38


class TestDirectDeploymentRollback:
    """A rollback "may be requested directly by an ``SRE``"."""

    def test_direct_rollback_unverifies_the_deployed_change_and_sinks_the_release(
        self, api
    ):
        """"The second hop, caused by the first, rolls the release back when its
        ``phase`` is ``STABILIZING`` or ``RELEASED``", and the changes "stay
        ``DEPLOYED``, but their ``deployment_verified`` reverts to false".

        Design: Corner/state_machines/deployment_rollback_from_completed_unverifies_deployed_changes
        """
        built = released_release(api)
        assert built["ship_response"]["verified_change_count"] == 1
        assert built["change"]["deployment_verified"] is True

        rolled_back = rollback_deployment(
            api, built["deployment"]["id"], reason="customer-reported regression"
        )

        assert rolled_back["delivery_state"] == DeliveryState.ROLLED_BACK
        assert_instant(
            rolled_back["rolled_back_at"], DEPLOYMENT_START_AT, "rolled_back_at"
        )
        release = read_release(api, built["release"]["id"])
        assert release["phase"] == ReleasePhase.ROLLED_BACK
        assert_instant(
            release["rolled_back_at"], DEPLOYMENT_START_AT, "rolled_back_at"
        )
        assert release["verified_change_count"] == 0
        change = read_change(api, built["change"]["id"])
        assert change["state"] == ChangeState.DEPLOYED
        assert change["deployment_verified"] is False
        assert read_environment(api, built["prod_env"]["id"])[
            "active_deployment_count"
        ] == 0

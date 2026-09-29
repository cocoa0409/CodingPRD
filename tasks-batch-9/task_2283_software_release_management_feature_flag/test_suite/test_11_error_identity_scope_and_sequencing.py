"""Error identity: which refusal fires, in which scope, and in which order."""

from test_helpers import (
    ApiErrorId,
    ApprovalKind,
    ChangeState,
    DeliveryState,
    EvidenceItem,
    FlagState,
    IncidentDecision,
    IncidentSeverity,
    IncidentState,
    NoteAudience,
    NoteState,
    PacketState,
    ReleasePhase,
    RiskClass,
    StepState,
    assert_instant,
    assert_missing_items,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import CLOCK_ORIGIN, RELEASE_FREEZE_AT
from test_helpers.factories import (
    make_approval_payload,
    make_deployment_payload,
    make_feature_flag_payload,
    make_incident_decision_payload,
    make_release_payload,
    make_waiver_payload,
)
from test_helpers.fixtures import (
    apply_step,
    create_release,
    decide_incident,
    merge_change,
    read_change,
    read_environment,
    read_flag,
    read_incident,
    read_note,
    read_packet,
    read_release,
    read_step,
    read_train,
    record_approval,
    reserve_deployment,
    scenario_cut_release_and_production_environment,
    scenario_flag_and_two_trains_sharing_a_version_label,
    scenario_flag_with_two_planned_rungs,
    scenario_open_sev3_incident_without_linkage,
    scenario_published_internal_notes_then_clock_advance,
    scenario_stabilizing_release_with_four_deferred_mediums,
    scenario_submitted_medium_change_awaiting_technical,
    scenario_superseded_and_live_evidence_packets,
    scenario_two_low_changes_joined_by_one_edge,
    set_clock,
    start_soak,
)
from test_helpers.test_users import (
    CHANGE_APPROVER,
    COMPLIANCE_OFFICER,
    ENGINEER,
    OTHER_ENGINEER,
    OTHER_ENGINEER_USER_ID,
    RELEASE_MANAGER,
    SRE,
)

#: One second short of the first rung's thirty-minute soak.
JUST_SHORT_OF_SOAK_AT = "2026-08-01T00:29:59Z"

#: The instant the first rung's soak ends exactly.
SOAK_ELAPSED_AT = "2026-08-01T00:30:00Z"

#: The clock instant the notes document was published at, one day before the reread.
NOTES_REREAD_AT = "2026-08-09T00:00:00Z"


class TestDuplicateScopes:
    """Two duplicate refusals, two different scopes."""

    def test_the_flag_key_collides_everywhere_but_the_label_only_on_its_own_train(
        self, api
    ):
        """"a feature flag's ``key`` must be unique across the whole inventory, and a
        collision is ``ERR_FLAG_KEY_DUPLICATE`` (409); a release's ``version_label``
        must be unique within its train, and a collision is
        ``ERR_VERSION_LABEL_DUPLICATE`` (409)".

        Design: Corner/errors/duplicate_flag_key_is_global_while_version_label_is_train_scoped
        """
        built = scenario_flag_and_two_trains_sharing_a_version_label(api)

        duplicate_key = api.create_feature_flag(
            make_feature_flag_payload(
                key="checkout-v2",
                owner_user_id=OTHER_ENGINEER_USER_ID,
                expires_at="2027-01-01T00:00:00Z",
            ),
            OTHER_ENGINEER,
        )
        duplicate_label = api.create_release(
            built["first_train"]["id"],
            make_release_payload(
                version_label="2026.08.1", cut_at="2026-08-24T00:00:00Z"
            ),
            RELEASE_MANAGER,
        )
        accepted = create_release(
            api, built["second_train"]["id"], version_label="2026.08.1"
        )

        validate_error(duplicate_key, ApiErrorId.ERR_FLAG_KEY_DUPLICATE.value, 409)
        validate_error(
            duplicate_label, ApiErrorId.ERR_VERSION_LABEL_DUPLICATE.value, 409
        )
        assert accepted["version_label"] == built["release"]["version_label"]
        assert accepted["release_train_id"] == built["second_train"]["id"]
        assert accepted["phase"] == ReleasePhase.OPEN
        assert read_train(api, built["first_train"]["id"])["open_release_count"] == 1
        assert read_train(api, built["second_train"]["id"])["open_release_count"] == 1
        _, meta = validate_paginated(api.list_feature_flags(ENGINEER))
        assert meta["total_count"] == 1


class TestLadderSequencingErrors:
    """One ladder, four distinct refusals, in the ladder's own priority order."""

    def test_each_wrong_move_on_the_ladder_names_its_own_error(self, api):
        """"At most one rollout step per flag may be ``SOAKING`` — otherwise
        ``ERR_STEP_ALREADY_SOAKING`` (409)", it outranks "The step starting its soak
        must be the flag's next rung, meaning its ``step_index`` equals the flag's
        ``applied_step_count`` plus one", and application waits until "the logical
        clock has reached the end of its soak, inclusively".

        Design: Corner/errors/rollout_step_sequencing_errors_are_distinct_and_priority_ordered
        """
        built = scenario_flag_with_two_planned_rungs(api)
        first_id = built["first"]["id"]
        second_id = built["second"]["id"]
        assert built["first"]["step_index"] == 1
        assert built["second"]["step_index"] == 2

        apply_while_planned = api.apply_step(first_id, {}, ENGINEER)
        soak_out_of_order = api.start_soak(second_id, {}, ENGINEER)
        soaking = start_soak(api, first_id)
        soak_while_another_soaks = api.start_soak(second_id, {}, ENGINEER)
        set_clock(api, JUST_SHORT_OF_SOAK_AT)
        apply_one_second_early = api.apply_step(first_id, {}, ENGINEER)
        set_clock(api, SOAK_ELAPSED_AT)
        applied = apply_step(api, first_id)

        validate_error(
            apply_while_planned, ApiErrorId.ERR_STEP_STATE_INVALID.value, 409
        )
        validate_error(
            soak_out_of_order, ApiErrorId.ERR_STEP_OUT_OF_ORDER.value, 409
        )
        assert soaking["state"] == StepState.SOAKING
        assert_instant(soaking["soak_started_at"], CLOCK_ORIGIN, "soak_started_at")
        validate_error(
            soak_while_another_soaks, ApiErrorId.ERR_STEP_ALREADY_SOAKING.value, 409
        )
        validate_error(
            apply_one_second_early, ApiErrorId.ERR_SOAK_NOT_ELAPSED.value, 409
        )
        assert applied["state"] == StepState.APPLIED
        assert_instant(applied["applied_at"], SOAK_ELAPSED_AT, "applied_at")
        flag = read_flag(api, built["flag"]["id"])
        assert float(flag["current_exposure_pct"]) == 5.0
        assert flag["applied_step_count"] == 1
        assert flag["state"] == FlagState.ACTIVE_ROLLING_OUT
        assert read_step(api, second_id)["state"] == StepState.PLANNED


class TestWaiverRefusalsAreDistinct:
    """A satisfied item and a superseded packet fail for different reasons."""

    def test_the_satisfied_item_is_unprocessable_while_the_old_packet_is_a_conflict(
        self, api
    ):
        """"The packet must be in ``state`` ``DRAFT``, or the request is refused with
        ``ERR_PACKET_STATE_INVALID``", and otherwise "the named item must currently be
        unsatisfied; and it must not already have been waived".

        Design: Corner/errors/superseded_evidence_packet_locks_waivers_and_satisfied_items_cannot_be_waived
        """
        built = scenario_superseded_and_live_evidence_packets(api)
        live = built["live"]
        assert live["state"] == PacketState.DRAFT
        assert live["base_index"] == 75
        assert_missing_items(
            live, [EvidenceItem.CANARY_PASS, EvidenceItem.RELEASE_NOTES]
        )
        assert built["superseded"]["state"] == PacketState.SUPERSEDED
        assert built["superseded"]["base_index"] == 75

        already_satisfied = api.create_waiver(
            live["id"],
            make_waiver_payload(EvidenceItem.APPROVALS_COMPLETE),
            COMPLIANCE_OFFICER,
        )
        on_superseded = api.create_waiver(
            built["superseded"]["id"],
            make_waiver_payload(EvidenceItem.CANARY_PASS),
            COMPLIANCE_OFFICER,
        )

        validate_error(
            already_satisfied, ApiErrorId.ERR_WAIVER_NOT_ALLOWED.value, 422
        )
        validate_error(on_superseded, ApiErrorId.ERR_PACKET_STATE_INVALID.value, 409)
        release_id = built["release"]["id"]
        settled = read_packet(api, release_id, live["id"])
        assert settled["waiver_count"] == 0
        assert settled["waivers"] == []
        assert settled["waiver_credit_points"] == 0
        assert read_packet(api, release_id, built["superseded"]["id"])["waivers"] == []


class TestIncidentDecisionRefusals:
    """Admissibility and finality are separate refusals on the same incident."""

    def test_a_rollback_without_linkage_is_refused_and_a_decision_happens_once(
        self, api
    ):
        """"An inadmissible ``ROLLBACK`` or ``NO_ACTION`` is refused with
        ``ERR_NO_LINKED_RELEASE``", while "A second attempt on an already-decided
        incident is refused with ``ERR_INCIDENT_ALREADY_DECIDED``".

        Design: Corner/errors/incident_decision_errors_cover_missing_linkage_and_second_decision
        """
        built = scenario_open_sev3_incident_without_linkage(api)
        incident_id = built["incident"]["id"]
        assert built["incident"]["linked_release_id"] is None
        assert built["incident"]["linked_deployment_id"] is None
        assert built["incident"]["severity"] == IncidentSeverity.SEV3
        assert built["incident"]["state"] == IncidentState.OPEN

        inadmissible = api.decide_incident(
            incident_id,
            make_incident_decision_payload(IncidentDecision.ROLLBACK),
            SRE,
        )
        decided = decide_incident(api, incident_id, IncidentDecision.NO_ACTION)
        second_decision = api.decide_incident(
            incident_id,
            make_incident_decision_payload(IncidentDecision.FORWARD_FIX),
            SRE,
        )

        validate_error(inadmissible, ApiErrorId.ERR_NO_LINKED_RELEASE.value, 409)
        assert decided["state"] == IncidentState.DECIDED
        assert decided["decision"] == IncidentDecision.NO_ACTION
        assert_instant(decided["decided_at"], CLOCK_ORIGIN, "decided_at")
        validate_error(
            second_decision, ApiErrorId.ERR_INCIDENT_ALREADY_DECIDED.value, 409
        )
        settled = read_incident(api, incident_id)
        assert settled["decision"] == IncidentDecision.NO_ACTION
        assert settled["state"] == IncidentState.DECIDED
        assert settled["version"] == decided["version"]


class TestNotePublicationIsTerminal:
    """Publication happens once, and the stamp it left is not rewritten."""

    def test_the_second_publish_is_refused_and_the_first_timestamp_survives(self, api):
        """"Publication requires the document to be in ``state`` ``DRAFT``, or it is
        refused with ``ERR_NOTE_ALREADY_PUBLISHED``", and publication "sets ``state``
        to ``PUBLISHED``, stamps ``published_at``, increments the document's
        ``version``".

        Design: Corner/errors/republishing_release_notes_returns_note_already_published
        """
        built = scenario_published_internal_notes_then_clock_advance(api)
        note = built["note"]
        assert note["audience"] == NoteAudience.INTERNAL
        assert note["state"] == NoteState.PUBLISHED
        assert note["entry_count"] == 1
        assert_instant(note["generated_at"], RELEASE_FREEZE_AT, "generated_at")
        assert_instant(note["published_at"], RELEASE_FREEZE_AT, "published_at")
        assert_instant(
            built["clock_after_publication"], NOTES_REREAD_AT, "current_utc"
        )

        refused = api.publish_release_notes(note["id"], {}, RELEASE_MANAGER)

        validate_error(refused, ApiErrorId.ERR_NOTE_ALREADY_PUBLISHED.value, 409)
        settled = read_note(api, built["release"]["id"], note["id"])
        assert settled["state"] == NoteState.PUBLISHED
        assert_instant(settled["published_at"], RELEASE_FREEZE_AT, "published_at")
        assert settled["version"] == note["version"]


class TestApprovalLaneRefusalsAreDistinct:
    """A lane the class never asked for, and a lane the caller may not sign."""

    def test_the_unneeded_lane_is_unprocessable_and_the_wrong_role_is_forbidden(
        self, api
    ):
        """"Submitting a lane the change's class does not require — a ``CAB`` decision
        on a ``MEDIUM`` change, for instance — is refused with
        ``ERR_APPROVAL_KIND_NOT_REQUIRED``", and separately "``TECHNICAL`` and ``CAB``
        decisions may only be recorded by a ``ChangeApprover``".

        Design: Corner/errors/approval_kind_not_required_and_wrong_approver_role_are_distinct_errors
        """
        built = scenario_submitted_medium_change_awaiting_technical(api)
        change_id = built["change"]["id"]
        assert built["change"]["risk_score_preliminary"] == 33
        assert built["change"]["risk_class"] == RiskClass.MEDIUM
        assert built["change"]["state"] == ChangeState.RISK_CLASSIFIED

        unneeded_lane = api.create_approval(
            change_id, make_approval_payload(kind=ApprovalKind.CAB), CHANGE_APPROVER
        )
        wrong_role = api.create_approval(
            change_id,
            make_approval_payload(kind=ApprovalKind.TECHNICAL),
            COMPLIANCE_OFFICER,
        )
        accepted = record_approval(api, change_id, ApprovalKind.TECHNICAL)

        validate_error(
            unneeded_lane, ApiErrorId.ERR_APPROVAL_KIND_NOT_REQUIRED.value, 422
        )
        validate_error(wrong_role, ApiErrorId.ERR_APPROVAL_ROLE_MISMATCH.value, 403)
        assert accepted["kind"] == ApprovalKind.TECHNICAL
        assert accepted["decision"] == "APPROVE"
        assert accepted["pinned_risk_score"] == 33
        change = read_change(api, change_id)
        assert change["state"] == ChangeState.APPROVED
        assert change["approval_technical_count"] == 1
        assert change["approval_compliance_count"] == 0
        assert change["approval_cab_count"] == 0
        assert change["risk_score_final"] == 33
        _, meta = validate_paginated(api.list_approvals(change_id, CHANGE_APPROVER))
        assert meta["total_count"] == 1


class TestPrerequisiteGateReadsTheEdgeTarget:
    """Approval of the prerequisite is not landing it."""

    def test_the_dependent_merges_only_after_its_prerequisite_has_merged(self, api):
        """"Every dependency edge whose ``from_change_id`` is this change must point to
        a prerequisite whose ``state`` is ``MERGED`` or ``DEPLOYED``, or the merge is
        refused with ``ERR_PREREQUISITE_NOT_MERGED``".

        Design: Corner/errors/dependent_merge_before_prerequisite_returns_prerequisite_not_merged
        """
        built = scenario_two_low_changes_joined_by_one_edge(api)
        prerequisite_id = built["prerequisite"]["id"]
        dependent_id = built["dependent"]["id"]
        assert built["prerequisite"]["state"] == ChangeState.APPROVED
        assert built["dependent"]["state"] == ChangeState.APPROVED
        assert built["prerequisite"]["risk_score_preliminary"] == 9
        assert built["dependent"]["risk_score_preliminary"] == 9
        assert built["dependent"]["dependency_depth"] == 1

        too_early = api.merge_change_request(dependent_id, {}, ENGINEER)
        landed_prerequisite = merge_change(api, prerequisite_id)
        landed_dependent = merge_change(api, dependent_id)

        validate_error(too_early, ApiErrorId.ERR_PREREQUISITE_NOT_MERGED.value, 409)
        assert landed_prerequisite["state"] == ChangeState.MERGED
        assert_instant(landed_prerequisite["merged_at"], CLOCK_ORIGIN, "merged_at")
        assert landed_dependent["state"] == ChangeState.MERGED
        assert_instant(landed_dependent["merged_at"], CLOCK_ORIGIN, "merged_at")
        assert landed_prerequisite["risk_score_final"] == 9
        assert landed_dependent["risk_score_final"] == 14
        release = read_release(api, built["release"]["id"])
        assert release["committed_change_count"] == 2
        assert release["risk_budget_consumed_points"] == 23


class TestWindowGeometryAtReservation:
    """Three geometries the environment's hours forbid, and one it permits."""

    def test_only_the_window_inside_a_single_date_s_permitted_hours_is_reserved(
        self, api
    ):
        """"The **window geometry** rule requires the reserved span to fall on a single
        UTC date, with the ``window_start_at`` hour at or after the environment's
        ``deploy_window_start_hour_utc`` and ``window_end_at`` no later than that same
        date at ``deploy_window_end_hour_utc``; a window that straddles midnight or
        reaches outside the permitted hours is refused with
        ``ERR_DEPLOY_WINDOW_VIOLATION``".

        Design: Corner/errors/deployment_window_geometry_outside_environment_hours_is_rejected
        """
        built = scenario_cut_release_and_production_environment(api)
        release_id = built["release"]["id"]
        environment_id = built["prod_env"]["id"]
        assert built["prod_env"]["deploy_window_start_hour_utc"] == 2
        assert built["prod_env"]["deploy_window_end_hour_utc"] == 6
        assert built["release"]["phase"] == ReleasePhase.CUT

        starts_too_early = api.create_deployment(
            release_id,
            make_deployment_payload(
                environment_id,
                window_start_at="2026-08-10T01:00:00Z",
                window_end_at="2026-08-10T03:00:00Z",
            ),
            SRE,
        )
        ends_too_late = api.create_deployment(
            release_id,
            make_deployment_payload(
                environment_id,
                window_start_at="2026-08-10T02:00:00Z",
                window_end_at="2026-08-10T07:00:00Z",
            ),
            SRE,
        )
        straddles_midnight = api.create_deployment(
            release_id,
            make_deployment_payload(
                environment_id,
                window_start_at="2026-08-10T23:00:00Z",
                window_end_at="2026-08-11T01:00:00Z",
            ),
            SRE,
        )
        accepted = reserve_deployment(
            api,
            release_id,
            environment_id,
            window_start_at="2026-08-10T02:00:00Z",
            window_end_at="2026-08-10T04:00:00Z",
        )

        for refused in (starts_too_early, ends_too_late, straddles_midnight):
            validate_error(refused, ApiErrorId.ERR_DEPLOY_WINDOW_VIOLATION.value, 409)
        assert accepted["delivery_state"] == DeliveryState.SCHEDULED
        assert_instant(
            accepted["window_start_at"], "2026-08-10T02:00:00Z", "window_start_at"
        )
        assert_instant(
            accepted["window_end_at"], "2026-08-10T04:00:00Z", "window_end_at"
        )
        assert accepted["environment_id"] == environment_id
        _, meta = validate_paginated(api.list_deployments(SRE))
        assert meta["total_count"] == 1
        assert read_environment(api, environment_id)["active_deployment_count"] == 0


class TestReadinessFloorAtTheFinalGate:
    """A completed production deployment does not buy a low attested score."""

    def test_four_deferred_changes_hold_the_release_four_points_below_the_floor(
        self, api
    ):
        """"An **unlanded** change is one whose ``state`` at cut time is
        ``RISK_CLASSIFIED``, ``CAB_REVIEW``, ``APPROVED``, ``BLOCKED_BY_DEPENDENCY``
        or ``DEFERRED``", and "The release's ``readiness_score_attested`` must be at
        least 80, and its ``rollback_plan_confirmed`` must be true; a failure of
        either of those ... is refused with ``ERR_RELEASE_NOT_READY``".

        Design: Corner/errors/release_below_readiness_floor_returns_release_not_ready
        """
        built = scenario_stabilizing_release_with_four_deferred_mediums(api)
        release_id = built["release"]["id"]
        assert built["release"]["phase"] == ReleasePhase.STABILIZING
        assert built["release"]["readiness_score_attested"] == 76
        assert built["release"]["rollback_plan_confirmed"] is True
        assert built["deployment"]["delivery_state"] == DeliveryState.COMPLETED
        assert built["prod_env"]["requires_compliance_evidence"] is False

        refused = api.ship_release(release_id, {}, RELEASE_MANAGER)

        validate_error(refused, ApiErrorId.ERR_RELEASE_NOT_READY.value, 409)
        held = read_release(api, release_id)
        assert held["phase"] == ReleasePhase.STABILIZING
        assert held["released_at"] is None
        assert held["readiness_score_attested"] == 76
        assert held["verified_change_count"] == 0
        for change in built["changes"]:
            assert read_change(api, change["id"])["state"] == ChangeState.DEFERRED

"""Selection filters, ladder constants, hygiene thresholds and chronological linkage."""

from test_helpers import (
    ApiErrorId,
    ApprovalKind,
    ChangeState,
    CleanupState,
    FlagState,
    IncidentSeverity,
    IncidentState,
    NoteAudience,
    NoteState,
    RiskClass,
    StepState,
    assert_instant,
    assert_stale_debt,
    assert_sweep_summary,
    expected_ladder_ceiling,
    expected_required_soak_minutes,
    validate_error,
    validate_paginated,
)
from test_helpers.constants import CLOCK_ORIGIN, RELEASE_FREEZE_AT
from test_helpers.factories import (
    make_change_request_payload,
    make_rollout_step_payload,
)
from test_helpers.fixtures import (
    create_change,
    create_flag,
    flag_at_exposure,
    generate_notes,
    plan_step,
    read_change,
    read_flag,
    read_release,
    read_step,
    record_approval,
    report_incident,
    reset_clock,
    scenario_cut_release_with_deferred_medium_and_merged_low,
    scenario_cut_release_with_three_merged_changes,
    scenario_four_orphan_flags_across_debt_bands,
    scenario_two_cut_releases_ranked_by_cut_at,
    set_clock,
    submit_change,
    train_with_release,
)
from test_helpers.test_users import ENGINEER, SRE

#: The instant the incident inside the linkage window is detected.
INSIDE_WINDOW_AT = "2026-08-11T12:00:00Z"

#: One second past 72 hours after the later release's ``cut_at``.
OUTSIDE_WINDOW_AT = "2026-08-14T00:00:01Z"

#: A MEDIUM declaration: 300 lines over two subsystems, single-tenant blast radius.
MEDIUM_CHANGE = make_change_request_payload(
    title="Retry policy rewrite",
    summary_internal="Rewrite the retry policy across two subsystems.",
    lines_changed=300,
    touched_subsystem_count=2,
    declared_blast_radius="SINGLE_TENANT",
)


class TestCustomerAudienceSelection:
    """The two audiences read the same candidates through different filters."""

    def test_customer_notes_keep_only_the_change_whose_copy_was_actually_written(
        self, api
    ):
        """"For an ``INTERNAL`` audience, every candidate is included. For a
        ``CUSTOMER`` audience, a candidate is included only when its
        ``customer_facing`` is true **and** its ``summary_customer_facing`` is both
        non-null and not the empty string".

        Design: Corner/calculations/customer_release_notes_filter_drops_internal_and_summaryless_changes
        """
        built = scenario_cut_release_with_three_merged_changes(api)
        release_id = built["release"]["id"]

        customer = generate_notes(api, release_id, NoteAudience.CUSTOMER)
        internal = generate_notes(api, release_id, NoteAudience.INTERNAL)

        assert customer["entry_count"] == 1
        assert customer["included_change_ids"] == [built["customer_ready"]["id"]]
        assert customer["excluded_change_count"] == 2
        assert internal["entry_count"] == 3
        assert internal["included_change_ids"] == [
            built["customer_ready"]["id"],
            built["no_customer_copy"]["id"],
            built["internal_only"]["id"],
        ]
        assert internal["excluded_change_count"] == 0
        for note in (customer, internal):
            assert_instant(note["generated_at"], RELEASE_FREEZE_AT, "generated_at")
            assert note["state"] == NoteState.DRAFT

    def test_a_deferred_change_is_not_even_counted_as_excluded(self, api):
        """"The candidate set is the release's change requests whose ``state`` is
        ``MERGED`` or ``DEPLOYED``", and deferred changes "are excluded from the
        candidate set entirely, and therefore never appear in the exclusion count
        either".

        Design: Corner/calculations/release_notes_candidate_set_excludes_deferred_and_unmerged_changes
        """
        built = scenario_cut_release_with_deferred_medium_and_merged_low(api)

        note = generate_notes(api, built["release"]["id"], NoteAudience.CUSTOMER)

        assert built["deferred_medium"]["state"] == ChangeState.DEFERRED
        assert built["deferred_medium"]["customer_facing"] is True
        assert built["deferred_medium"]["summary_customer_facing"] is not None
        assert note["entry_count"] == 1
        assert note["included_change_ids"] == [built["merged_low"]["id"]]
        assert note["excluded_change_count"] == 0


class TestLadderCeilingConstants:
    """"the first rung may reach at most 5 percent"."""

    def test_a_ten_percent_first_rung_is_refused_while_five_percent_is_planned(
        self, api
    ):
        """"The highest admissible ``target_pct`` is the smaller of 100 and the larger
        of 5 and three times the current exposure", so the floor of 5 rules a fresh
        flag rather than three times zero.

        Design: Corner/calculations/rollout_ladder_first_rung_is_capped_at_five_percent
        """
        reset_clock(api)
        flag = create_flag(api)
        version = flag["version"]
        assert float(flag["current_exposure_pct"]) == 0.0
        assert expected_ladder_ceiling(0) == 5

        refused = api.create_rollout_step(
            flag["id"],
            make_rollout_step_payload(version, target_pct=10, soak_minutes=30),
            ENGINEER,
        )
        step = plan_step(api, flag["id"], target_pct=5, soak_minutes=30)

        validate_error(refused, ApiErrorId.ERR_ROLLOUT_STEP_TOO_LARGE.value, 422)
        assert step["step_index"] == 1
        assert step["state"] == StepState.PLANNED
        assert step["previous_exposure_pct"] is None
        rows, meta = validate_paginated(
            api.list_rollout_steps(ENGINEER, {"feature_flag_id": flag["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == step["id"]
        after = read_flag(api, flag["id"])
        assert float(after["current_exposure_pct"]) == 0.0
        assert after["applied_step_count"] == 0


class TestSoakBandFromTargetPercentage:
    """"The required soak scales with the rung's ambition"."""

    def test_the_fifteen_percent_rung_needs_a_full_hour_not_the_first_rung_s_half(
        self, api
    ):
        """"a ``target_pct`` of 10 or less requires at least half an hour of soak, a
        ``target_pct`` above 10 and at most 50 requires at least a full hour", and
        "supplying fewer minutes than required is refused with ``ERR_SOAK_TOO_SHORT``".

        Design: Corner/calculations/soak_minutes_band_selected_by_target_pct_rejects_short_soak
        """
        built = flag_at_exposure(api, target_pct=5, soak_minutes=30)
        flag_id = built["flag"]["id"]
        settled = read_flag(api, flag_id)
        assert float(settled["current_exposure_pct"]) == 5.0
        assert settled["applied_step_count"] == 1
        assert expected_required_soak_minutes(5) == 30
        assert expected_required_soak_minutes(15) == 60
        assert expected_ladder_ceiling(5) == 15

        refused = api.create_rollout_step(
            flag_id,
            make_rollout_step_payload(
                settled["version"], target_pct=15, soak_minutes=30
            ),
            ENGINEER,
        )
        second = plan_step(api, flag_id, target_pct=15, soak_minutes=60)

        validate_error(refused, ApiErrorId.ERR_SOAK_TOO_SHORT.value, 422)
        assert second["step_index"] == 2
        assert float(second["target_pct"]) == 15.0
        assert second["soak_minutes"] == 60
        assert second["state"] == StepState.PLANNED
        assert second["previous_exposure_pct"] is None
        assert read_step(api, built["step"]["id"])["state"] == StepState.APPLIED


class TestStaleDebtTierLadder:
    """"the ladder is evaluated in order with **inclusive** thresholds"."""

    def test_one_sweep_sorts_four_orphans_into_the_four_hygiene_tiers(self, api):
        """"three points for every whole day the flag is past its deadline" plus "a
        further **15 points** when the flag is an orphan, meaning it has no
        change-to-flag links at all", except that "a flag that is ``permanent`` ...
        has ``stale_debt_points`` of 0 and ``cleanup_state`` ``COMPLIANT``,
        unconditionally".

        Design: Corner/calculations/flag_stale_debt_thresholds_split_compliant_warning_overdue_enforced
        """
        built = scenario_four_orphan_flags_across_debt_bands(api)

        assert_sweep_summary(
            built["sweep"],
            evaluated_count=4,
            warning_count=1,
            overdue_count=1,
            enforced_count=1,
            paused_flag_count=0,
            voided_step_count=0,
            aborted_step_count=0,
        )
        assert_stale_debt(built["enforced"], 60, CleanupState.ENFORCED)
        assert_stale_debt(built["overdue"], 30, CleanupState.OVERDUE)
        assert_stale_debt(built["warning"], 27, CleanupState.WARNING)
        assert_stale_debt(built["permanent"], 0, CleanupState.COMPLIANT)
        for key in ("enforced", "overdue", "warning", "permanent"):
            assert_instant(built[key]["last_sweep_at"], CLOCK_ORIGIN, "last_sweep_at")
            assert built[key]["state"] == FlagState.DRAFT


class TestIncidentLinkageWindow:
    """"The candidates are ranked by ``cut_at`` descending"."""

    def test_the_later_cut_release_wins_and_a_late_report_links_to_nothing(self, api):
        """"whose ``cut_at`` is at or before the incident's ``detected_at``, and where
        the elapsed time from ``cut_at`` to ``detected_at`` is no more than 72
        hours", and "when no release qualifies, ``linked_release_id`` is null".

        Design: Corner/calculations/incident_links_to_most_recent_release_inside_seventy_two_hour_window
        """
        built = scenario_two_cut_releases_ranked_by_cut_at(api)
        train_id = built["train"]["id"]
        set_clock(api, INSIDE_WINDOW_AT)

        inside = report_incident(
            api,
            train_id,
            INSIDE_WINDOW_AT,
            severity=IncidentSeverity.SEV2,
            title="Elevated 500s after deploy",
        )
        set_clock(api, OUTSIDE_WINDOW_AT)
        outside = report_incident(
            api,
            train_id,
            OUTSIDE_WINDOW_AT,
            severity=IncidentSeverity.SEV3,
            title="Late report",
        )

        assert inside["linked_release_id"] == built["late_release"]["id"]
        assert inside["linked_release_id"] != built["early_release"]["id"]
        assert inside["linked_deployment_id"] is None
        assert inside["state"] == IncidentState.OPEN
        assert inside["decision"] is None
        assert outside["linked_release_id"] is None
        assert outside["linked_deployment_id"] is None
        _, meta = validate_paginated(
            api.list_incidents(
                SRE, {"linked_release_id": built["late_release"]["id"]}
            )
        )
        assert meta["total_count"] == 1


class TestRiskVariantPinningPoints:
    """"The same computation runs twice with one deliberate difference in its input"."""

    def test_approval_writes_the_final_score_and_leaves_the_preliminary_alone(self, api):
        """"The **preliminary** run happens once at submission and is never
        recomputed", while "the **final** run happens once on entry into ``state``
        ``APPROVED`` ... and is likewise never recomputed afterwards".

        Design: Corner/calculations/risk_score_variant_selected_by_lifecycle_point_not_by_recompute
        """
        reset_clock(api)
        built = train_with_release(api)
        change = create_change(api, built["release"]["id"], payload=MEDIUM_CHANGE)

        submitted = submit_change(api, change["id"])
        approval = record_approval(api, change["id"], ApprovalKind.TECHNICAL)

        assert submitted["risk_score_preliminary"] == 33
        assert submitted["risk_score_final"] is None
        assert submitted["risk_class"] == RiskClass.MEDIUM
        assert submitted["state"] == ChangeState.RISK_CLASSIFIED
        assert approval["pinned_risk_score"] == 33
        approved = read_change(api, change["id"])
        assert approved["state"] == ChangeState.APPROVED
        assert approved["risk_score_final"] == 33
        assert approved["risk_score_preliminary"] == 33
        assert approved["approval_technical_count"] == 1
        release = read_release(api, built["release"]["id"])
        assert release["risk_budget_consumed_points"] == 33
        assert release["committed_change_count"] == 1

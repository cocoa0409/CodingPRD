"""Derived posture, transitive cascades, and the dual-variant participation
score — all reconciled immediately within the triggering request."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_block,
    add_member,
    assign_captain,
    complete_bias_training,
    corroborate_report,
    create_active_agreement,
    create_alert,
    create_officer,
    create_watch_group,
    file_incident,
    hold_quorum_meeting,
    move_report_to_under_review,
    queue_alert,
    register_block,
    set_clock,
    setup_group_with_registered_block,
    setup_operational_group,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestSuspendCascade:
    def _suspended_captain_workspace(self, api):
        """OPERATIONAL group, captain m0, one QUEUED alert whose scheduled
        instant has arrived; then m0 is suspended."""
        ws = setup_operational_group(
            "Cascade Watch", "PCT7",
            member_channels=("SMS", "EMAIL"),
            train_member_indexes=(0, 1),
            badge_number="B700",
        )
        alert = create_alert(ws["group"]["id"],
                             scheduled_send_at="2026-08-09T12:00:00Z")
        queue_alert(alert["id"])
        set_clock("2026-08-09T12:00:00Z")
        return ws, alert

    def test_suspend_revokes_captain_and_degrades_posture(self, api):
        """PRD §3.2: "Suspending a member revokes any `ACTIVE` captain
        assignment they hold — the assignment's `assignment_status` becomes
        `REVOKED` and its `relieved_at` is stamped — and that vacancy recomputes
        the group's posture, which can force a group from `OPERATIONAL` down to
        `DEGRADED`."

        Design: Difficulty/transitive_cascade/member_suspend_cascades_captain_posture_alert_hold
        """
        ws, _alert = self._suspended_captain_workspace(api)
        captain = ws["members"][0]
        assignment = ws["assignments"][0]
        assert ws["group"]["posture"] == "OPERATIONAL"

        suspended = validate_success(api.suspend_member(captain["id"], COORD))
        assert suspended["membership_status"] == "SUSPENDED"  # link 1

        revoked = validate_success(api.get_captain_assignment(assignment["id"], COORD))
        assert revoked["assignment_status"] == "REVOKED", (
            "Link 2: the cascade revokes the captaincy — no direct relieve call"
        )
        assert revoked["relieved_at"] is not None

        group = validate_success(api.get_watch_group(ws["group"]["id"], COORD))
        assert group["posture"] == "DEGRADED", (
            "Link 3: the captain vacancy drags OPERATIONAL down to DEGRADED"
        )

    def test_degraded_posture_holds_queued_alert_send(self, api):
        """PRD §3.4: "Should the group slip from `OPERATIONAL` to `DEGRADED`
        while alerts sit queued, those alerts are held in place: their
        `distribution_status` stays `QUEUED`, sends are rejected with
        `ERR_POSTURE_GATED`, and they become sendable again only when coverage is
        restored and posture returns to `OPERATIONAL`."

        Design: Difficulty/transitive_cascade/member_suspend_cascades_captain_posture_alert_hold
        """
        ws, alert = self._suspended_captain_workspace(api)
        captain = ws["members"][0]
        validate_success(api.suspend_member(captain["id"], COORD))
        assert validate_success(api.get_watch_group(ws["group"]["id"], COORD))[
            "posture"
        ] == "DEGRADED"

        resp = api.send_alert(alert["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_POSTURE_GATED)  # link 4

        held = validate_success(api.get_alert(alert["id"], COORD))
        assert held["distribution_status"] == "QUEUED", (
            "The held alert stays QUEUED behind the posture gate"
        )


class TestDeregisterCascade:
    def _dereg_workspace(self, api):
        """FORMATION group: one REGISTERED block, exactly one ACTIVE member
        (not a captain). Census score 10*1 + 2*1 = 12."""
        group, block = setup_group_with_registered_block(
            "Dereg Watch", "PCT8", "20-30 Spruce St", 5,
        )
        member = add_member(group["id"], block["id"], "Solo", "SMS")
        return group, block, member

    def test_deregister_withdraws_active_members(self, api):
        """PRD §3.1: "Deregistering cascades: every `ACTIVE` member whose
        `block_id` names this block is withdrawn to `WITHDRAWN`, the group's
        participation score is recomputed, and the group's `version` increments."

        Design: Difficulty/transitive_cascade/block_deregister_cascades_member_withdrawal_score
        """
        group, block, member = self._dereg_workspace(api)
        deregistered = validate_success(api.deregister_block(block["id"], COORD))
        assert deregistered["registration_status"] == "DEREGISTERED"  # link 1

        withdrawn = validate_success(api.get_member(member["id"], COORD))
        assert withdrawn["membership_status"] == "WITHDRAWN", (
            "Link 2: the cascade withdraws the block's members — no withdraw call"
        )

    def test_deregister_recomputes_participation_score(self, api):
        """PRD §3.1: "Deregistering cascades: every `ACTIVE` member whose
        `block_id` names this block is withdrawn to `WITHDRAWN`, the group's
        participation score is recomputed, and the group's `version` increments."
        PRD §3.8: "While the group is `DORMANT` or `FORMATION`, the census
        variant counts only the forward-looking base: 10 points per `REGISTERED`
        block plus 2 points per `ACTIVE` member."

        Design: Difficulty/transitive_cascade/block_deregister_cascades_member_withdrawal_score
        """
        group, block, _member = self._dereg_workspace(api)
        before = validate_success(api.get_watch_group(group["id"], COORD))
        assert before["posture"] == "FORMATION"
        assert before["participation_score"] == 12, "CENSUS: 10*1 block + 2*1 member"

        validate_success(api.deregister_block(block["id"], COORD))
        after = validate_success(api.get_watch_group(group["id"], COORD))
        assert after["participation_score"] == 0, (
            "Link 3: the block leaves the REGISTERED set and the member leaves "
            "the ACTIVE set, so the recomputed score is 0"
        )
        assert after["version"] > before["version"], (
            "The cascade increments the group's version"
        )


class TestParticipationScoreVariants:
    def _census_workspace(self, api):
        """Group with 2 REGISTERED blocks and 5 ACTIVE members, posture
        FORMATION (no training, no captains yet)."""
        group = create_watch_group("Maple Watch", "PCT1")
        b1 = register_block(add_block(group["id"], "100-199 Maple St", 20)["id"])
        b2 = register_block(add_block(group["id"], "200-299 Maple St", 15)["id"])
        members = []
        for name, block, channel in (
            ("M1", b1, "SMS"), ("M2", b1, "EMAIL"), ("M3", b1, "SMS"),
            ("M4", b2, "EMAIL"), ("M5", b2, "SMS"),
        ):
            members.append(
                add_member(group["id"], block["id"], name, channel)
            )
        return group, b1, b2, members

    def test_census_variant_counts_only_blocks_and_members(self, api):
        """PRD §3.8: "While the group is `DORMANT` or `FORMATION`, the census
        variant counts only the forward-looking base: 10 points per `REGISTERED`
        block plus 2 points per `ACTIVE` member."

        Design: Difficulty/dual_variant_calc/participation_score_census_vs_activity_on_watch_group
        """
        group, _b1, _b2, _members = self._census_workspace(api)
        fetched = validate_success(api.get_watch_group(group["id"], COORD))
        assert fetched["posture"] == "FORMATION"
        assert fetched["participation_score"] == 30, (
            "CENSUS variant: 10*2 blocks + 2*5 members = 30"
        )

    def test_activity_variant_adds_trailing_terms_in_operational(self, api):
        """PRD §3.8: "Once the group is `OPERATIONAL`, `DEGRADED`, or `FROZEN`,
        the activity variant adds the trailing record on top of the same base:
        5 points per `HELD` meeting with quorum, 8 points per `COMPLETED` event,
        and 3 points per incident report in `CORROBORATED` or `CLEARED`."

        Design: Difficulty/dual_variant_calc/participation_score_census_vs_activity_on_watch_group
        """
        group, b1, b2, members = self._census_workspace(api)
        mid = validate_success(api.get_watch_group(group["id"], COORD))
        assert mid["posture"] == "FORMATION"
        assert mid["participation_score"] == 30

        officer = create_officer("B100", "Officer A", "PCT1")
        complete_bias_training(group["id"], officer,
                               [members[0]["id"], members[1]["id"]])
        assign_captain(b1["id"], members[0]["id"])
        assign_captain(b2["id"], members[1]["id"])
        hold_quorum_meeting(group["id"], officer,
                            "2026-08-05T18:00:00Z", "2026-08-05T19:00:00Z", 3)
        hold_quorum_meeting(group["id"], officer,
                            "2026-08-06T18:00:00Z", "2026-08-06T19:00:00Z", 3)
        create_active_agreement(group["id"], officer, scope="INCIDENT_SUMMARIES")
        report = file_incident(b1["id"], members[0], category="VANDALISM",
                               occurred_at="2026-08-04T12:00:00Z", severity=2)
        move_report_to_under_review(report["id"])
        corroborate_report(report["id"], officer)

        final = validate_success(api.get_watch_group(group["id"], COORD))
        assert final["posture"] == "OPERATIONAL"
        assert final["participation_score"] == 43, (
            "ACTIVITY variant: 30 base + 5*2 meetings + 8*0 events + 3*1 incident"
        )
        assert final["participation_score"] - mid["participation_score"] == 13, (
            "Only the activity terms enter across the posture boundary"
        )


class TestImmediateConsistency:
    def test_posture_visible_on_read_right_after_captain_assignment(self, api):
        """PRD §2.8: "the cascades described in §3 always run to completion
        within the triggering request — the consistency model is immediate, with
        no deferred settlement."
        PRD §3.6: "completion of the group's first bias-avoidance session is one
        of the two gates on the path from `FORMATION` to `OPERATIONAL`."

        Design: Corner/consistency_model/immediate_consistency_posture_visible_in_same_sequence
        """
        group, block, member = _formation_group_with_training(api)
        assign_captain(block["id"], member["id"])
        fetched = validate_success(api.get_watch_group(group["id"], COORD))
        assert fetched["posture"] == "OPERATIONAL", (
            "The very next read after the captain assignment shows OPERATIONAL — "
            "no reconciliation lag"
        )

    def test_group_summary_reflects_children_immediately(self, api):
        """PRD §3.8: "While the group is `DORMANT` or `FORMATION`, the census
        variant counts only the forward-looking base: 10 points per `REGISTERED`
        block plus 2 points per `ACTIVE` member."
        PRD §2.8: "the cascades described in §3 always run to completion within
        the triggering request — the consistency model is immediate, with no
        deferred settlement."

        Design: Corner/endpoints/computed_read_group_summary_reflects_children
        """
        group, block = setup_group_with_registered_block(
            "Summ Watch", "E03", "1-1 Summ St", 4,
        )
        add_member(group["id"], block["id"], "S1", "SMS")
        add_member(group["id"], block["id"], "S2", "EMAIL")

        fetched = validate_success(api.get_watch_group(group["id"], COORD))
        assert fetched["posture"] == "FORMATION"
        assert fetched["participation_score"] == 14, (
            "10*1 block + 2*2 members, visible in the same request sequence"
        )


def _formation_group_with_training(api):
    """FORMATION group: 1 REGISTERED block, 1 member, bias training completed,
    captain not yet assigned."""
    group, block = setup_group_with_registered_block(
        "Imm Watch", "M01", "1-1 Imm St", 4,
    )
    member = add_member(group["id"], block["id"], "Imm M", "SMS")
    officer = create_officer("BM01", "Officer Im", "M01")
    complete_bias_training(group["id"], officer, [member["id"]])
    return group, block, member

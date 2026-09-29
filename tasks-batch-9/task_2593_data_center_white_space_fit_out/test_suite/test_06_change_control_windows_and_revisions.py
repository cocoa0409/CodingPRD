"""Change control before execution: revision rounds, the buffered window on a target
resource, and the ordering between window exclusivity and tenant notification."""
from test_helpers import (
    api_client,
    assert_mop_approval,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import USER_IDS
from test_helpers.fixtures import (
    CM,
    EC,
    approve_mop,
    approve_mop_to_quorum,
    create_cage,
    create_mop,
    create_tenant,
    read_hall,
    read_mop,
    revise_mop,
    schedule_mop,
    setup_fit_out_hall,
    setup_scheduled_mop,
    submit_mop,
)

AUTHOR = USER_IDS["ELECTRICAL_CONTRACTOR"]


class TestMopRevisionCycle:
    """A revision round closes on REQUEST_REVISION, reopens on revise, and the cycle
    may run at most twice."""

    def _mop_after_two_revision_cycles(self):
        ctx = setup_fit_out_hall("HF1")
        mop = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            risk_class="LOW",
            window_start="2026-08-05T02:00:00Z",
            window_end="2026-08-05T06:00:00Z",
            author_user_id=AUTHOR,
        )
        submit_mop(mop["id"], AUTHOR)
        approve_mop(mop["id"], decision="REQUEST_REVISION", comment="tighten the plan")
        revise_mop(
            mop["id"],
            AUTHOR,
            window_start="2026-08-05T03:00:00Z",
            window_end="2026-08-05T07:00:00Z",
        )
        approve_mop(mop["id"], decision="REQUEST_REVISION", comment="still short")
        revise_mop(
            mop["id"],
            AUTHOR,
            window_start="2026-08-06T02:00:00Z",
            window_end="2026-08-06T06:00:00Z",
        )
        approve_mop(mop["id"], decision="REQUEST_REVISION", comment="one more time")
        ctx["mop_id"] = mop["id"]
        return ctx

    def test_third_revision_is_refused_and_the_mop_stays_in_revision_requested(self):
        """Two completed revision cycles exhaust the allowance, so the third revise is
        refused and the MOP keeps the window the second revision stored.

        PRD: "a MOP whose `revision_count` has already reached 2 refuses a third
        revision with `ERR_MOP_REVISION_LIMIT_REACHED` and stays in
        `REVISION_REQUESTED`."

        Design: Difficulty/non_linear_state_machine/mop_revision_cycle_returns_to_under_review
        """
        ctx = self._mop_after_two_revision_cycles()
        validate_error(
            api_client.revise_mop(
                ctx["mop_id"],
                {"backout_plan": "a third attempt at the plan"},
                {**EC, "X-User-ID": AUTHOR},
            ),
            ApiErrorId.ERR_MOP_REVISION_LIMIT_REACHED.value,
            409,
        )
        mop = read_mop(ctx["mop_id"])
        assert mop["status"] == "REVISION_REQUESTED"
        assert mop["revision_count"] == 2, "the refused revision did not count"
        assert mop["window_start"] == "2026-08-06T02:00:00Z", (
            "the window the second revision supplied is still stored"
        )
        assert mop["approval_count"] == 0, (
            "a REQUEST_REVISION closes the round, so the approve count falls to 0"
        )
        assert mop["required_approval_count"] == 1, "a LOW risk change needs one vote"

    def test_every_revision_request_appends_an_immutable_numbered_record(self):
        """The approval trail holds one record per decision in creation order, numbered
        from one, and none of them counts toward a quorum.

        PRD: "Approval records are the audit trail of change control: they are never
        modified, they carry no `updated_at` and no `version`, and the only way to read
        them is the approval-trail listing of their MOP, returned in creation order."

        Design: Difficulty/non_linear_state_machine/mop_revision_cycle_returns_to_under_review
        """
        ctx = self._mop_after_two_revision_cycles()
        rows, meta = validate_paginated(
            api_client.list_mop_approvals(ctx["mop_id"], CM)
        )
        assert meta["total_count"] == 3, "three revision requests were recorded"
        assert [row["sequence"] for row in rows] == [1, 2, 3]
        for row in rows:
            assert_mop_approval(row)
            assert row["decision"] == "REQUEST_REVISION"
            assert row["approver_user_id"] == USER_IDS["CHANGE_MANAGER"]
            assert row["mop_id"] == ctx["mop_id"]
        assert read_mop(ctx["mop_id"])["approval_count"] == 0, (
            "`REJECT` and `REQUEST_REVISION` records never count toward a quorum"
        )


class TestMopWindowBuffer:
    """Window exclusivity is per target resource, buffered by sixty minutes on both
    sides, and compared strictly."""

    def _hall_with_one_scheduled_change(self):
        ctx = setup_fit_out_hall("HQ1")
        ctx["mop_1"] = setup_scheduled_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            risk_class="MEDIUM",
            window_start="2026-08-05T02:00:00Z",
            window_end="2026-08-05T04:00:00Z",
            title="MOP-1",
        )
        return ctx

    def _approved_mop(self, ctx, busway_key, start, end, title):
        mop = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx[busway_key]["id"],
            title=title,
            risk_class="MEDIUM",
            window_start=start,
            window_end=end,
            author_user_id=AUTHOR,
        )
        submit_mop(mop["id"], AUTHOR)
        approve_mop_to_quorum(mop["id"], "MEDIUM")
        return read_mop(mop["id"])

    def test_a_gap_of_less_than_the_buffer_collides_and_exactly_the_buffer_does_not(self):
        """A change starting 59 minutes after the scheduled window ends collides on the
        same run, while one starting exactly 60 minutes after it does not.

        PRD: "Because the comparisons are strict, a gap of exactly sixty minutes between
        two windows does **not** collide."

        Design: Difficulty/resource_temporal_overlap/mop_window_buffer_collision_on_same_busway
        """
        ctx = self._hall_with_one_scheduled_change()
        near = self._approved_mop(
            ctx, "bw_a", "2026-08-05T04:59:00Z", "2026-08-05T05:30:00Z", "MOP-2"
        )
        clear = self._approved_mop(
            ctx, "bw_a", "2026-08-05T05:00:00Z", "2026-08-05T06:00:00Z", "MOP-3"
        )

        validate_error(
            api_client.schedule_mop(near["id"], {}, CM),
            ApiErrorId.ERR_MOP_WINDOW_CONFLICT.value,
            409,
        )
        scheduled = validate_success(api_client.schedule_mop(clear["id"], {}, CM), 200)
        assert scheduled["status"] == "SCHEDULED"
        assert read_mop(near["id"])["status"] == "APPROVED", (
            "the collided change keeps its approval and occupies no window"
        )

    def test_the_buffer_is_scoped_to_one_target_resource(self):
        """A change with exactly the same window as the scheduled one schedules freely
        when it names the other run, and the hall counts every open change.

        PRD: "Only MOPs on the same `target_resource_id` whose status is `SCHEDULED` or
        `IN_EXECUTION` are candidates for collision; MOPs at `DRAFT`, `UNDER_REVIEW`,
        `REVISION_REQUESTED`, `APPROVED`, `CLOSED`, `BACKED_OUT` or `REJECTED` occupy no
        window at all."

        Design: Difficulty/resource_temporal_overlap/mop_window_buffer_collision_on_same_busway
        """
        ctx = self._hall_with_one_scheduled_change()
        near = self._approved_mop(
            ctx, "bw_a", "2026-08-05T04:59:00Z", "2026-08-05T05:30:00Z", "MOP-2"
        )
        clear = self._approved_mop(
            ctx, "bw_a", "2026-08-05T05:00:00Z", "2026-08-05T06:00:00Z", "MOP-3"
        )
        other_run = self._approved_mop(
            ctx, "bw_b", "2026-08-05T02:00:00Z", "2026-08-05T04:00:00Z", "MOP-4"
        )

        validate_error(
            api_client.schedule_mop(near["id"], {}, CM),
            ApiErrorId.ERR_MOP_WINDOW_CONFLICT.value,
            409,
        )
        schedule_mop(clear["id"])
        on_other_run = schedule_mop(other_run["id"])
        assert on_other_run["status"] == "SCHEDULED"

        hall = read_hall(ctx["hall_id"])
        assert hall["open_mop_count"] == 3, (
            "three changes of this hall now stand at SCHEDULED"
        )
        assert hall["release_posture"] == "OPEN", (
            "a scheduled change does not lock the room; only an executing one does"
        )


class TestWindowConflictBeatsNotification:
    """When a schedule request breaches both the window rule and the notification rule,
    the window rule reports."""

    def _multi_tenant_hall_with_two_cages(self):
        tenant_1 = create_tenant("TN-L1", contracted_kw=100.00)
        tenant_2 = create_tenant("TN-L2", contracted_kw=100.00)
        ctx = setup_fit_out_hall("HL1", tenant_mode="MULTI_TENANT")
        ctx["tenant_1"], ctx["tenant_2"] = tenant_1, tenant_2
        create_cage(ctx["hall_id"], tenant_1["id"], "CG-1")
        create_cage(ctx["hall_id"], tenant_2["id"], "CG-2")
        ctx["mop_1"] = setup_scheduled_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            risk_class="HIGH",
            window_start="2026-08-05T02:00:00Z",
            window_end="2026-08-05T04:00:00Z",
            tenant_notified_ids=[tenant_1["id"], tenant_2["id"]],
            title="MOP-1",
        )
        ctx["mop_2"] = self._approved_high_mop(
            ctx, "bw_a", "2026-08-05T03:00:00Z", "2026-08-05T05:00:00Z", "MOP-2"
        )
        ctx["mop_3"] = self._approved_high_mop(
            ctx, "bw_b", "2026-08-07T08:00:00Z", "2026-08-07T10:00:00Z", "MOP-3"
        )
        return ctx

    def _approved_high_mop(self, ctx, busway_key, start, end, title):
        mop = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx[busway_key]["id"],
            title=title,
            risk_class="HIGH",
            window_start=start,
            window_end=end,
            author_user_id=AUTHOR,
        )
        submit_mop(mop["id"], AUTHOR)
        approve_mop_to_quorum(mop["id"], "HIGH")
        return read_mop(mop["id"])

    def test_overlapping_window_reports_before_the_incomplete_notification(self):
        """One request that both collides on the run and omits a neighbouring tenant
        reports the window conflict, while a request that only omits the neighbour
        reports the notification gap.

        PRD: "When the hall's `tenant_mode` is `MULTI_TENANT` and the MOP's `risk_class`
        is `HIGH`, that list must contain every tenant that owns at least one cage in
        the hall — a neighbour whose cage sits beside the work must be told before the
        work is scheduled."

        Design: Difficulty/priority_pair_validation_conflict/mop_schedule_window_conflict_temporal_beats_notification_constraint
        """
        ctx = self._multi_tenant_hall_with_two_cages()
        one_tenant = [ctx["tenant_1"]["id"]]

        validate_error(
            api_client.schedule_mop(
                ctx["mop_2"]["id"], {"tenant_notified_ids": one_tenant}, CM
            ),
            ApiErrorId.ERR_MOP_WINDOW_CONFLICT.value,
            409,
        )
        validate_error(
            api_client.schedule_mop(
                ctx["mop_3"]["id"], {"tenant_notified_ids": one_tenant}, CM
            ),
            ApiErrorId.ERR_TENANT_NOTIFICATION_INCOMPLETE.value,
            422,
        )

        mop_2 = read_mop(ctx["mop_2"]["id"])
        mop_3 = read_mop(ctx["mop_3"]["id"])
        assert mop_2["status"] == "APPROVED"
        assert mop_3["status"] == "APPROVED"
        assert mop_2["tenant_notified_ids"] == []
        assert mop_3["tenant_notified_ids"] == []
        assert read_mop(ctx["mop_1"]["id"])["status"] == "SCHEDULED"

    def test_a_complete_notification_list_schedules_the_non_colliding_change(self):
        """Naming both cage-owning tenants clears the notification rule for the change
        on the other run, and the quorum figures of a HIGH risk change are unaffected.

        PRD: "On success the list is stored, the hall's `open_mop_count` is re-derived,
        and the hall's release posture is re-derived."

        Design: Difficulty/priority_pair_validation_conflict/mop_schedule_window_conflict_temporal_beats_notification_constraint
        """
        ctx = self._multi_tenant_hall_with_two_cages()
        both = [ctx["tenant_1"]["id"], ctx["tenant_2"]["id"]]

        before = read_hall(ctx["hall_id"])
        assert before["open_mop_count"] == 1
        assert before["release_posture"] == "OPEN"

        scheduled = schedule_mop(ctx["mop_3"]["id"], both)
        assert scheduled["status"] == "SCHEDULED"
        assert sorted(scheduled["tenant_notified_ids"]) == sorted(both)

        mop_2 = read_mop(ctx["mop_2"]["id"])
        assert mop_2["approval_count"] == 2
        assert mop_2["required_approval_count"] == 2, (
            "a HIGH risk change carries a two-vote quorum"
        )
        after = read_hall(ctx["hall_id"])
        assert after["open_mop_count"] == 2
        assert after["release_posture"] == "OPEN"

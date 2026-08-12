"""Voting: ballot casting gates, the points budget, recast under OCC, quorum
boundary and snapshot semantics, the voting window, and the computed tally
(PRD §2.8, §2.9, §3.6, §3.7).
"""
from datetime import datetime, timedelta

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_cycle,
    allocation,
    close_voting_window,
    create_ballot_payload,
    get_success_data,
    get_tally,
    make_member_headers,
    recast_ballot_payload,
    set_clock,
    setup_voting,
    try_advance_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _raw_ballot(api, ctx, member_index, allocations):
    member = ctx["members"][member_index]
    membership = ctx["memberships"][member_index]
    return api.create_ballot(
        create_ballot_payload(ctx["cycle"]["id"], membership["id"], allocations),
        make_member_headers(member["id"]),
    )


class TestBallotMembershipGate:
    def test_cast_requires_active_membership(self, api):
        """PRD §3.6: "Casting requires the membership to belong to the acting
        member and be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`), and the logical
        clock to sit inside the inclusive window from `voting_opens_at` through
        `voting_closes_at` — a ballot attempted before the opening instant or
        after the closing instant fails with `ERR_VOTING_WINDOW_CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/ballot_cast_requires_active_membership
        """
        ctx = setup_voting("Circle CE1", num_members=2, num_finalists=1, ballot_points=[])
        # The member withdraws after VOTING opened; the window is still open.
        member2 = ctx["members"][1]
        validate_success(
            api.withdraw_membership(
                ctx["memberships"][1]["id"], make_member_headers(member2["id"])
            )
        )
        resp = _raw_ballot(
            api, ctx, 1, [allocation(ctx["finalists"][0]["id"], 100)]
        )
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)
        tally = get_tally(ctx["cycle"]["id"])
        assert tally["ballots_cast_count"] == 0

    def test_active_member_cast_succeeds_where_withdrawn_member_failed(self, api):
        """PRD §3.6: "Casting requires the membership to belong to the acting
        member and be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`)".
        PRD §3.6: "A ballot is created directly in `CAST` — its only state —
        and its arrival increments the cycle's `ballots_cast_count` and is
        reflected in the tally immediately."

        The companion half: with one member withdrawn, the still-ACTIVE member's
        cast succeeds, proving the gate is membership state, not phase or window.

        Design: Difficulty/cross_entity_state_dependency/ballot_cast_requires_active_membership
        """
        ctx = setup_voting("Circle CE1B", num_members=2, num_finalists=1, ballot_points=[])
        member2 = ctx["members"][1]
        validate_success(
            api.withdraw_membership(
                ctx["memberships"][1]["id"], make_member_headers(member2["id"])
            )
        )
        validate_error(
            _raw_ballot(api, ctx, 1, [allocation(ctx["finalists"][0]["id"], 100)]),
            ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE,
        )
        ballot = validate_success(
            _raw_ballot(api, ctx, 0, [allocation(ctx["finalists"][0]["id"], 100)]),
            expected_status=201,
        )
        assert ballot["status"] == "CAST"
        tally = get_tally(ctx["cycle"]["id"])
        assert tally["ballots_cast_count"] == 1


class TestBallotReferenceAndBudget:
    def test_voting_window_closed_beats_not_finalist(self, api):
        """PRD §2.9: "Business rules come last, in this relative order:
        segregation of duties on payout approval; the temporal windows (voting
        window, refund window); uniqueness constraints; calendar overlap rules;
        capacity and counter limits; referenced-entity state (nonprofit
        standing, completed site visits, interim-report acceptance); ballot
        reference and points-budget rules; and finally the fiscal thresholds
        (tier minimums, the vetting score gate, and the refund underfunding
        guard)."

        A cast after voting_closes_at naming a non-finalist must surface the
        temporal-window error, not the finalist-reference error.

        Design: Difficulty/priority_pair_validation_conflict/voting_window_beats_finalist_reference
        """
        ctx = setup_voting(
            "Circle PP2", num_members=2, num_finalists=1, extra_submitted=1,
            ballot_points=[],
        )
        submitted_id = ctx["nominations"][1]["id"]  # never vetted: SUBMITTED
        set_clock("2026-06-18T00:00:00Z")  # past voting_closes_at (2026-06-17T11:00)
        resp = _raw_ballot(api, ctx, 0, [allocation(submitted_id, 100)])
        assert resp.status_code == 409
        err = validate_error(resp, ApiErrorId.ERR_VOTING_WINDOW_CLOSED)
        assert err["error_id"] != ApiErrorId.ERR_NOT_FINALIST
        tally = get_tally(ctx["cycle"]["id"])
        assert tally["ballots_cast_count"] == 0

    def test_not_finalist_fires_when_window_open(self, api):
        """PRD §3.6: "Every allocation must target a nomination that is a
        `FINALIST` of this cycle; naming anything else fails with
        `ERR_NOT_FINALIST`."

        The companion half of the pair: window open, same non-finalist target,
        so the referential check is what fires.

        Design: Difficulty/priority_pair_validation_conflict/voting_window_beats_finalist_reference
        """
        ctx = setup_voting(
            "Circle PP2B", num_members=2, num_finalists=1, extra_submitted=1,
            ballot_points=[],
        )
        submitted_id = ctx["nominations"][1]["id"]
        resp = _raw_ballot(api, ctx, 0, [allocation(submitted_id, 100)])
        validate_error(resp, ApiErrorId.ERR_NOT_FINALIST)

    def test_ballot_with_non_finalist_rejected(self, api):
        """PRD §3.6: "Every allocation must target a nomination that is a
        `FINALIST` of this cycle; naming anything else fails with
        `ERR_NOT_FINALIST`."

        Design: Corner/errors/ballot_with_non_finalist_rejected
        """
        ctx = setup_voting(
            "Circle ER3", num_members=2, num_finalists=1, extra_submitted=1,
            ballot_points=[],
        )
        submitted_id = ctx["nominations"][1]["id"]
        resp = _raw_ballot(api, ctx, 0, [allocation(submitted_id, 100)])
        validate_error(resp, ApiErrorId.ERR_NOT_FINALIST)
        tally = get_tally(ctx["cycle"]["id"])
        assert tally["ballots_cast_count"] == 0

    def test_ballot_points_budget_violation_rejected(self, api):
        """PRD §3.6: "The points budget is exact: `allocations` holds from one
        to five entries, every entry carries at least 10 points, and the
        entries sum to exactly 100; any other shape fails with
        `ERR_POINTS_BUDGET`."

        A single 90-point allocation sums to 90 != 100.

        Design: Corner/errors/ballot_points_budget_violation_rejected
        """
        ctx = setup_voting("Circle ER4", num_members=1, num_finalists=1, ballot_points=[])
        resp = _raw_ballot(api, ctx, 0, [allocation(ctx["finalists"][0]["id"], 90)])
        validate_error(resp, ApiErrorId.ERR_POINTS_BUDGET)

    def test_second_ballot_same_cycle_rejected(self, api):
        """PRD §3.6: "Each membership votes once per cycle
        (`ERR_DUPLICATE_BALLOT`)."

        Design: Corner/errors/second_ballot_same_cycle_rejected
        """
        ctx = setup_voting("Circle ER2", num_members=1, num_finalists=1)
        resp = _raw_ballot(api, ctx, 0, [allocation(ctx["finalists"][0]["id"], 100)])
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_BALLOT)
        tally = get_tally(ctx["cycle"]["id"])
        assert tally["ballots_cast_count"] == 1


class TestRecast:
    def test_recast_replaces_allocations_conserves_total(self, api):
        """PRD §3.6: "A ballot is not set in stone while the window remains
        open: recasting replaces its `allocations` wholesale in a self-loop on
        `CAST`."
        PRD §3.6: "The `total_points_cast` across all finalists always equals
        one hundred times `ballots_cast_count`, because every ballot
        distributes exactly one hundred points."

        Design: Difficulty/compensating_invariant/cast_recast_points_conservation
        """
        ctx = setup_voting(
            "Circle CI2", num_members=2, num_finalists=2,
            ballot_points=[(0, [60, 40])],
        )
        ballot = ctx["ballots"][0]
        n1, n2 = ctx["finalists"][0]["id"], ctx["finalists"][1]["id"]
        before = get_tally(ctx["cycle"]["id"])
        assert before["total_points_cast"] == 100

        recast = validate_success(
            api.recast_ballot(
                ballot["id"],
                recast_ballot_payload(
                    [allocation(n1, 30), allocation(n2, 70)], ballot["version"]
                ),
                make_member_headers(ctx["members"][0]["id"]),
            )
        )
        got = sorted((a["nomination_id"], a["points"]) for a in recast["allocations"])
        assert got == sorted([(n1, 30), (n2, 70)]), (
            f"recast must replace allocations wholesale, got {got}"
        )
        after = get_tally(ctx["cycle"]["id"])
        assert after["total_points_cast"] == 100, "the points total is conserved across the recast"

    def test_recast_increments_ballot_version(self, api):
        """PRD §3.6: "A successful recast increments the ballot's `version` by
        one, and the cycle's tally reflects the replacement immediately."

        Design: Difficulty/compensating_invariant/cast_recast_points_conservation
        """
        ctx = setup_voting(
            "Circle CI2B", num_members=2, num_finalists=2,
            ballot_points=[(0, [60, 40])],
        )
        ballot = ctx["ballots"][0]
        n1, n2 = ctx["finalists"][0]["id"], ctx["finalists"][1]["id"]
        recast = validate_success(
            api.recast_ballot(
                ballot["id"],
                recast_ballot_payload(
                    [allocation(n1, 30), allocation(n2, 70)], ballot["version"]
                ),
                make_member_headers(ctx["members"][0]["id"]),
            )
        )
        assert recast["version"] == ballot["version"] + 1, (
            f"recast must bump version by one: {ballot['version']} -> {recast['version']}"
        )
        assert recast["status"] == "CAST", "recast is a self-loop on CAST"

    def test_recast_with_stale_ballot_version_rejected(self, api):
        """PRD §2.8: "Recasting a ballot works the same way with
        `expected_ballot_version` against the ballot's current `version`. When
        the ballot's version has advanced since the caller last read it, the
        recast is rejected with `ERR_STALE_VERSION` (HTTP 412), so an older
        view never silently overwrites a superseding allocation."

        Design: Corner/complexity_layers/recast_with_stale_ballot_version_rejected
        """
        ctx = setup_voting("Circle CL2", num_members=1, num_finalists=1)
        ballot = ctx["ballots"][0]
        n1 = ctx["finalists"][0]["id"]
        stale_version = ballot["version"]
        first = validate_success(
            api.recast_ballot(
                ballot["id"],
                recast_ballot_payload([allocation(n1, 100)], stale_version),
                make_member_headers(ctx["members"][0]["id"]),
            )
        )
        resp = api.recast_ballot(
            ballot["id"],
            recast_ballot_payload([allocation(n1, 100)], stale_version),
            make_member_headers(ctx["members"][0]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        current = get_success_data(api.get_ballot(ballot["id"], ADMIN))
        assert current["version"] == first["version"], (
            "the rejected replay must not move the ballot's version"
        )


class TestQuorum:
    def test_quorum_exact_count_passes(self, api):
        """PRD §3.6: "`quorum_required` is the `active_member_snapshot`
        multiplied by the cycle's `quorum_percent`, divided by one hundred, and
        rounded up to the next whole ballot. Quorum is met when
        `ballots_cast_count` is at least that requirement — exact equality
        passes."

        Snapshot 4 x quorum 50 -> required ceil(200/100) == 2; exactly 2 ballots
        meet it.

        Design: Difficulty/boundary_precision_check/quorum_exact_count_passes
        """
        ctx = setup_voting(
            "Circle BP1", num_members=4, num_finalists=1,
            ballot_points=[(0, [100]), (1, [100])],
        )
        tally = get_tally(ctx["cycle"]["id"])
        assert tally["quorum_required"] == 2
        assert tally["ballots_cast_count"] == 2
        assert tally["quorum_met"] is True, "exact equality passes the quorum boundary"

    def test_quorum_exact_advance_to_award_succeeds(self, api):
        """PRD §3.7: "Closing the vote is the heaviest operation in the system.
        The advance from `VOTING` to `AWARD` carries the usual
        `expected_cycle_version` guard, and then two gatekeepers: the logical
        clock must have moved strictly past `voting_closes_at` — an attempt at
        or before the closing instant fails with `ERR_VOTING_STILL_OPEN` — and
        quorum must be met per §3.6, failing with `ERR_QUORUM_NOT_MET` when too
        few ballots were cast."

        Design: Difficulty/boundary_precision_check/quorum_exact_count_passes
        """
        ctx = setup_voting(
            "Circle BP1B", num_members=4, num_finalists=1,
            ballot_points=[(0, [100]), (1, [100])],
        )
        close_voting_window(ctx)
        advanced = advance_cycle(ctx["cycle"]["id"])
        assert advanced["phase"] == "AWARD"

    def test_quorum_snapshot_ignores_post_entry_withdrawal(self, api):
        """PRD §3.6: "The snapshot never changes afterward — a member who
        withdraws mid-vote does not lower the quorum bar."
        PRD §3.6: "`quorum_required` is the `active_member_snapshot` multiplied
        by the cycle's `quorum_percent`, divided by one hundred, and rounded up
        to the next whole ballot."

        Snapshot 2 x quorum 100 -> required 2; after one withdrawal only one
        ballot can be cast, and the advance must still fail.

        Design: Corner/calculations/quorum_snapshot_ignores_post_entry_withdrawal
        """
        ctx = setup_voting(
            "Circle CA2", num_members=2, quorum_percent=100, num_finalists=1,
            ballot_points=[(0, [100])],
        )
        member2 = ctx["members"][1]
        validate_success(
            api.withdraw_membership(
                ctx["memberships"][1]["id"], make_member_headers(member2["id"])
            )
        )
        tally = get_tally(ctx["cycle"]["id"])
        assert tally["quorum_required"] == 2, (
            "the frozen snapshot (2) keeps the requirement at 2 despite the withdrawal"
        )
        close_voting_window(ctx)
        resp = try_advance_cycle(ctx["cycle"]["id"])
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)

    def test_advance_voting_window_still_open_rejected(self, api):
        """PRD §3.7: "the logical clock must have moved strictly past
        `voting_closes_at` — an attempt at or before the closing instant fails
        with `ERR_VOTING_STILL_OPEN`".

        Design: Corner/errors/advance_voting_window_still_open_rejected
        """
        ctx = setup_voting("Circle ER5", num_members=1, num_finalists=1)
        set_clock("2026-06-12T00:00:00Z")  # inside the window
        resp = try_advance_cycle(ctx["cycle"]["id"])
        validate_error(resp, ApiErrorId.ERR_VOTING_STILL_OPEN)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        assert cycle["phase"] == "VOTING"

    def test_advance_voting_without_quorum_rejected(self, api):
        """PRD §3.7: "quorum must be met per §3.6, failing with
        `ERR_QUORUM_NOT_MET` when too few ballots were cast."

        Snapshot 2 x quorum 100 -> required 2; only 1 ballot cast; window closed.

        Design: Corner/errors/advance_voting_without_quorum_rejected
        """
        ctx = setup_voting(
            "Circle ER6", num_members=2, quorum_percent=100, num_finalists=1,
            ballot_points=[(0, [100])],
        )
        close_voting_window(ctx)
        resp = try_advance_cycle(ctx["cycle"]["id"])
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        assert cycle["phase"] == "VOTING"


class TestTallyRead:
    def test_tally_read_reflects_cast_ballots(self, api):
        """PRD §3.6: "A read-only tally view on the cycle exposes
        `ballots_cast_count`, the computed `quorum_required`, whether
        `quorum_met` is currently true, the per-finalist `finalist_points`
        array, and `total_points_cast`."
        PRD §3.6: "A ballot is created directly in `CAST` — its only state —
        and its arrival increments the cycle's `ballots_cast_count` and is
        reflected in the tally immediately."

        Design: Corner/endpoints/tally_read_reflects_cast_ballots
        """
        ctx = setup_voting(
            "Circle EP1", num_members=2, quorum_percent=100, num_finalists=1,
            ballot_points=[(0, [100])],
        )
        tally = get_tally(ctx["cycle"]["id"])
        assert tally["ballots_cast_count"] == 1
        assert tally["total_points_cast"] == 100
        assert tally["quorum_required"] == 2
        assert tally["quorum_met"] is False

    def test_entering_voting_sets_window_and_snapshot(self, api):
        """PRD §3.6: "Moving `VETTING` → `VOTING` requires at least one
        nomination of the cycle in `FINALIST` (`ERR_NO_FINALISTS` otherwise)
        and opens the voting window: the advance stamps `voting_opens_at` from
        the logical clock, sets `voting_closes_at` exactly seven days later,
        and freezes `active_member_snapshot` as the count of the circle's
        memberships in `ACTIVE` at that instant."

        Design: Corner/state_machines/entering_voting_sets_window_and_snapshot
        """
        ctx = setup_voting("Circle SM4", num_members=2, num_finalists=1, ballot_points=[])
        cycle = ctx["cycle"]  # the VETTING -> VOTING advance response
        assert cycle["phase"] == "VOTING"
        opens = _parse(cycle["voting_opens_at"])
        closes = _parse(cycle["voting_closes_at"])
        # The clock read 2026-06-10T11:00:00Z at the advance (set during vetting).
        assert opens == _parse("2026-06-10T11:00:00Z"), (
            f"voting_opens_at must be stamped from the logical clock, got {cycle['voting_opens_at']}"
        )
        assert closes - opens == timedelta(days=7), (
            "voting_closes_at must be exactly seven days after voting_opens_at"
        )
        assert cycle["active_member_snapshot"] == 2, (
            f"snapshot must freeze the ACTIVE count at entry, got {cycle['active_member_snapshot']}"
        )

    def test_list_nominations_filter_by_status(self, api):
        """PRD §4: "List nominations, filterable by `cycle_id`, `nonprofit_id`,
        `nominated_by_membership_id`, and `status` | All four roles".

        Design: Corner/endpoints/list_nominations_filter_by_status
        """
        ctx = setup_voting(
            "Circle EP2", num_members=2, num_finalists=1, extra_submitted=1,
            ballot_points=[],
        )
        finalist_id = ctx["finalists"][0]["id"]
        submitted_id = ctx["nominations"][1]["id"]
        data, meta = validate_paginated(
            api.list_nominations(
                ADMIN, params={"cycle_id": ctx["cycle"]["id"], "status": "FINALIST"}
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in data] == [finalist_id], (
            "the FINALIST filter returns exactly the finalist, excluding SUBMITTED"
        )
        assert all(row["id"] != submitted_id for row in data)

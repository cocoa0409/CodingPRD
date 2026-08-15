"""Bid allocation: the AT_LARGE threshold boundary, pool conservation through
decline/re-offer, the appeal-overturn and disqualification cascades, and the
allocate-bids OCC guard."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    apply_safety_deduction,
    appeal_deduction,
    assert_bid_pool_invariant,
    get_success_data,
    make_performance_official,
    make_team_coach_headers,
    mark_performance_performed,
    resolve_appeal,
    set_clock,
    setup_live_event_with_checked_in_teams,
    setup_official_performance,
    submit_full_panel,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["event_director_headers"]

THREE_TEAMS = [
    {"coach_id": "coach-a", "name": "TA", "organization": "GymA",
     "athlete_name": "Ann", "athlete_dob": "2010-05-01"},
    {"coach_id": "coach-b", "name": "TB", "organization": "GymB",
     "athlete_name": "Bob", "athlete_dob": "2010-06-01"},
    {"coach_id": "coach-c", "name": "TC", "organization": "GymC",
     "athlete_name": "Cat", "athlete_dob": "2010-07-01"},
]


def _finish_all_official(api, ctx, scores, durations=(150, 149, 148)):
    """Mark every team's performance performed, submit flat panel sheets, and
    confirm each official in order. Returns the list of OFFICIAL performances
    in team order."""
    safety_id = ctx["safety"]["id"]
    head_id = ctx["head"]["id"]
    finals = []
    for item, score, duration in zip(ctx["teams"], scores, durations):
        perf = item["performance"]
        mark_performance_performed(perf["id"], safety_id, duration, 0)
        submit_full_panel(perf["id"], ctx["panel"], score)
        finals.append(make_performance_official(perf["id"], head_id))
    return finals


def _division_and_bids(api, division_id):
    division = get_success_data(api.get_division(division_id, DIRECTOR))
    bids, _ = validate_paginated(api.list_division_bids(division_id, DIRECTOR))
    return division, bids


class TestAtLargeThresholdBoundary:
    def test_at_large_bid_threshold_inclusive_boundary(self, api):
        """PRD §3.7: "`AT_LARGE` slots then go to the next eligible teams by
        rank whose `official_score` is at least 90 percent of the
        division-winning official score — the threshold computed as 0.90
        times the winner's `official_score`, rounded half-up to 2 decimal
        places, and the comparison is inclusive."
        PRD §3.7: "`PAID` slots go to the top `paid_bid_count` eligible teams
        by rank, best rank first."

        Design: Difficulty/boundary_precision_check/at_large_bid_threshold_inclusive_boundary
        """
        ctx = setup_live_event_with_checked_in_teams(
            THREE_TEAMS,
            division_overrides={"paid_bid_count": 1, "at_large_bid_count": 1})
        # Winner 85.50 -> threshold round_half_up(0.90*85.50) = 76.95; tB lands
        # exactly on it, tC one cent below.
        finals = _finish_all_official(api, ctx, [8.55, 7.695, 7.694])
        assert finals[1]["official_score"] == pytest.approx(76.95, abs=0.001)
        assert finals[2]["official_score"] == pytest.approx(76.94, abs=0.001)

        division, bids = _division_and_bids(api, ctx["division"]["id"])
        assert len(bids) == 2
        by_team = {b["team_id"]: b for b in bids}
        assert by_team[ctx["teams"][0]["team"]["id"]]["kind"] == "PAID"
        assert by_team[ctx["teams"][1]["team"]["id"]]["kind"] == "AT_LARGE"
        assert ctx["teams"][2]["team"]["id"] not in by_team
        assert division["bid_pool_available"] == 0

    def test_at_large_threshold_boundary_one_cent_below_gets_nothing(self, api):
        """PRD §3.7: "the threshold computed as 0.90 times the winner's
        `official_score`, rounded half-up to 2 decimal places, and the
        comparison is inclusive."
        PRD §2.8: "the number of bids whose status is `OFFERED` or
        `ACCEPTED`, plus `bid_pool_available`, always equals `paid_bid_count`
        plus `at_large_bid_count`."

        Design: Difficulty/boundary_precision_check/at_large_bid_threshold_inclusive_boundary
        """
        ctx = setup_live_event_with_checked_in_teams(
            THREE_TEAMS[:2],
            division_overrides={"paid_bid_count": 1, "at_large_bid_count": 1})
        # Winner 85.50; runner-up 76.94 < 76.95 threshold -> AT_LARGE slot
        # stays in the pool.
        _finish_all_official(api, ctx, [8.55, 7.694])

        division, bids = _division_and_bids(api, ctx["division"]["id"])
        assert len(bids) == 1
        assert bids[0]["team_id"] == ctx["teams"][0]["team"]["id"]
        assert bids[0]["kind"] == "PAID"
        assert division["bid_pool_available"] == 1
        assert_bid_pool_invariant(division, bids)


class TestBidPoolConservation:
    def test_bid_pool_conserved_through_decline_and_reoffer(self, api):
        """PRD §2.8: "The pool obeys a strict conservation invariant at all
        times: the number of bids whose status is `OFFERED` or `ACCEPTED`,
        plus `bid_pool_available`, always equals `paid_bid_count` plus
        `at_large_bid_count`."
        PRD §3.7: "**REOFFER** runs whenever a slot returns to
        `bid_pool_available` — a decline, an expiry, or a revocation. The
        team whose action freed the slot is excluded from that re-offer,
        having already refused or lost it. A freed `PAID` slot is offered to
        the next-ranked eligible team with no score threshold"

        Design: Difficulty/compensating_invariant/bid_pool_conserved_through_decline_and_reoffer
        """
        ctx = setup_live_event_with_checked_in_teams(
            THREE_TEAMS,
            division_overrides={"paid_bid_count": 1, "at_large_bid_count": 1})
        # 90.00 / 85.50 / 80.00; winner 90.00 -> AT_LARGE threshold 81.00, so
        # tC (80.00) is below it.
        _finish_all_official(api, ctx, [9.0, 8.55, 8.0])

        division, bids = _division_and_bids(api, ctx["division"]["id"])
        assert division["bid_pool_available"] == 0
        assert_bid_pool_invariant(division, bids)
        by_team = {b["team_id"]: b for b in bids}
        bid_a = by_team[ctx["teams"][0]["team"]["id"]]
        bid_b = by_team[ctx["teams"][1]["team"]["id"]]
        assert bid_a["kind"] == "PAID" and bid_b["kind"] == "AT_LARGE"

        # tB declines AT_LARGE: no eligible team meets the 81.00 threshold
        # (tC is 80.00), so the slot returns to the pool.
        get_success_data(api.decline_bid(
            bid_b["id"], make_team_coach_headers("coach-b")))
        division, bids = _division_and_bids(api, ctx["division"]["id"])
        assert division["bid_pool_available"] == 1
        assert_bid_pool_invariant(division, bids)

        # tA declines PAID: the re-offer carries no score threshold, so tB
        # (next rank) receives a new OFFERED PAID bid.
        get_success_data(api.decline_bid(
            bid_a["id"], make_team_coach_headers("coach-a")))
        division, bids = _division_and_bids(api, ctx["division"]["id"])
        team_b_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][1]["team"]["id"], DIRECTOR))
        new_paid = [b for b in team_b_bids
                    if b["kind"] == "PAID" and b["status"] == "OFFERED"]
        assert len(new_paid) == 1
        assert division["bid_pool_available"] == 1
        assert_bid_pool_invariant(division, bids)

        # tC never receives any bid.
        team_c_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][2]["team"]["id"], DIRECTOR))
        assert team_c_bids == []


class TestAppealOverturnCascade:
    def test_appeal_accept_cascades_deduction_score_rank_bid(self, api):
        """PRD §3.6: "if the performance is already `OFFICIAL`, its
        `official_score` is recomputed, the division ranking is recomputed,
        and the bid re-evaluation step of §3.7 runs for the division,
        revoking `OFFERED` bids whose teams no longer earn a slot and
        re-offering what is freed."
        PRD §3.7: "**REEVALUATE** runs when a deduction overturn changes
        ranks on an `OFFICIAL` performance: ranks are recomputed, every
        `OFFERED` bid in the division is revoked (pool credited accordingly),
        and INITIAL allocation runs against the new ranks."

        Design: Difficulty/transitive_cascade/appeal_accept_cascades_deduction_score_rank_bid
        """
        ctx = setup_live_event_with_checked_in_teams(
            THREE_TEAMS[:2],
            division_overrides={"paid_bid_count": 1, "at_large_bid_count": 0})
        safety_id = ctx["safety"]["id"]
        head_id = ctx["head"]["id"]
        perf_a = ctx["teams"][0]["performance"]
        perf_b = ctx["teams"][1]["performance"]

        # tA: base 84.00 minus a 2.00 SAFETY deduction -> 82.00 official.
        mark_performance_performed(perf_a["id"], safety_id, 150, 0)
        deduction = apply_safety_deduction(perf_a["id"], safety_id)
        submit_full_panel(perf_a["id"], ctx["panel"], 8.4)
        # tB: clean base 83.00.
        mark_performance_performed(perf_b["id"], safety_id, 148, 0)
        submit_full_panel(perf_b["id"], ctx["panel"], 8.3)

        make_performance_official(perf_a["id"], head_id)
        make_performance_official(perf_b["id"], head_id)

        # Division completed at tB's confirmation: tB (83.00) is rank 1 and
        # holds the OFFERED PAID bid; tA (82.00) is rank 2.
        team_b_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][1]["team"]["id"], DIRECTOR))
        assert len(team_b_bids) == 1
        bid_b = team_b_bids[0]
        assert bid_b["status"] == "OFFERED"

        # The appeal overturn restores tA to 84.00, swapping the ranks.
        appeal = appeal_deduction(deduction["id"], "coach-a",
                                  note="video shows legal", video_ref="vid-77")
        resolve_appeal(appeal["id"], head_id, "ACCEPTED")

        ded_after = get_success_data(api.get_deduction(deduction["id"], DIRECTOR))
        assert ded_after["status"] == "OVERTURNED"
        perf_a_after = get_success_data(api.get_performance(perf_a["id"], DIRECTOR))
        perf_b_after = get_success_data(api.get_performance(perf_b["id"], DIRECTOR))
        assert perf_a_after["official_score"] == pytest.approx(84.00, abs=0.001)
        assert perf_b_after["official_score"] == pytest.approx(83.00, abs=0.001)
        assert perf_a_after["rank_in_division"] == 1
        assert perf_b_after["rank_in_division"] == 2

        # tB's OFFERED bid is revoked and the slot re-offered to tA.
        bid_b_after = get_success_data(api.get_bid(bid_b["id"], DIRECTOR))
        assert bid_b_after["status"] == "REVOKED"
        team_a_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][0]["team"]["id"], DIRECTOR))
        offered_a = [b for b in team_a_bids if b["status"] == "OFFERED"]
        assert len(offered_a) == 1
        assert offered_a[0]["kind"] == "PAID"
        division = get_success_data(api.get_division(ctx["division"]["id"], DIRECTOR))
        assert division["bid_pool_available"] == 0


class TestDisqualifyCascade:
    def test_disqualify_cascades_performance_exclusion_and_bid_reoffer(self, api):
        """PRD §3.3: "Disqualification moves the team to `DISQUALIFIED`,
        moves every non-`CANCELLED` performance of the team to `EXCLUDED`
        (post-competition disqualification of a `COMPETED` team therefore
        reaches back into already-`OFFICIAL` performances), recomputes the
        division ranking excluding the excluded performances, revokes the
        team's `OFFERED` or `ACCEPTED` bids with the same pool-and-re-offer
        cascade as withdrawal, and increments the team's `version`."
        PRD §3.7: "An `ACCEPTED` bid can be revoked only by the
        withdrawal/disqualification cascade."

        Design: Difficulty/transitive_cascade/disqualify_cascades_performance_exclusion_and_bid_reoffer
        """
        ctx = setup_live_event_with_checked_in_teams(
            THREE_TEAMS,
            division_overrides={"paid_bid_count": 1, "at_large_bid_count": 0})
        _finish_all_official(api, ctx, [9.0, 8.55, 8.0])
        perf_a = ctx["teams"][0]["performance"]

        # tA (90.00) holds the PAID bid; accept it.
        team_a_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][0]["team"]["id"], DIRECTOR))
        bid_a = team_a_bids[0]
        get_success_data(api.accept_bid(bid_a["id"],
                                        make_team_coach_headers("coach-a")))

        # Disqualify tA: performance EXCLUDED, ACCEPTED bid REVOKED, the
        # division re-ranks, and the freed slot re-offers to the new rank 1.
        get_success_data(api.disqualify_team(ctx["teams"][0]["team"]["id"],
                                             DIRECTOR))

        perf_a_after = get_success_data(api.get_performance(perf_a["id"], DIRECTOR))
        assert perf_a_after["status"] == "EXCLUDED"
        bid_a_after = get_success_data(api.get_bid(bid_a["id"], DIRECTOR))
        assert bid_a_after["status"] == "REVOKED"

        perf_b_after = get_success_data(
            api.get_performance(ctx["teams"][1]["performance"]["id"], DIRECTOR))
        perf_c_after = get_success_data(
            api.get_performance(ctx["teams"][2]["performance"]["id"], DIRECTOR))
        assert perf_b_after["rank_in_division"] == 1
        assert perf_c_after["rank_in_division"] == 2

        team_b_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][1]["team"]["id"], DIRECTOR))
        offered_b = [b for b in team_b_bids
                     if b["kind"] == "PAID" and b["status"] == "OFFERED"]
        assert len(offered_b) == 1
        division = get_success_data(api.get_division(ctx["division"]["id"], DIRECTOR))
        assert division["bid_pool_available"] == 0


class TestAllocateBidsOcc:
    def test_occ_allocate_bids_stale_event_version(self, api):
        """PRD §2.5: "Re-running bid allocation for an event requires
        `expected_event_version`, compared against the `Event`'s current
        `version`. A mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412), because the event has been mutated (status transitions or
        a prior allocation) since the caller observed it, and re-running
        allocation supersedes the standing allocation."

        Design: Corner/complexity_layers/occ_allocate_bids_stale_event_version
        """
        ctx = setup_official_performance(
            sheet_score=8.0, division_overrides={"paid_bid_count": 1})
        event = get_success_data(api.get_event(ctx["event"]["id"], DIRECTOR))
        stale_version = event["version"]

        # First re-allocation succeeds and increments the event version.
        validate_success(api.allocate_bids(event["id"], stale_version, DIRECTOR))

        # The replay with the stale version is rejected.
        resp = api.allocate_bids(event["id"], stale_version, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestBidLifecycleErrors:
    def test_bid_double_accept_deadline_and_expiry_sweep(self, api):
        """PRD §3.7: "Both operations require the bid to be `OFFERED`
        (`ERR_BID_NOT_OFFERED`)."
        PRD §3.7: "Accepting an `OFFERED` bid requires the logical now to be
        no later than the bid's `acceptance_deadline` — inclusive boundary,
        else `ERR_BID_ACCEPTANCE_CLOSED`"
        PRD §3.9: "The **checkpoint** — an `EventDirector`-only sweep of a
        single event — expires every `OFFERED` bid of the event whose
        `acceptance_deadline` is earlier than the logical now, moving each to
        `EXPIRED`, crediting `bid_pool_available`, and running the re-offer
        cascade per freed slot"
        PRD §3.7: "The team whose action freed the slot is excluded from that
        re-offer, having already refused or lost it."
        PRD §3.7: "it must not already hold an `ACCEPTED` bid in any division
        of the event — one accepted bid per team per event."

        Design: Corner/errors/bid_double_accept_deadline_and_expiry_sweep
        """
        ctx = setup_live_event_with_checked_in_teams(
            THREE_TEAMS[:2],
            division_overrides={"paid_bid_count": 2, "at_large_bid_count": 0})
        _finish_all_official(api, ctx, [9.0, 8.55])

        team_a_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][0]["team"]["id"], DIRECTOR))
        team_b_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][1]["team"]["id"], DIRECTOR))
        bid_a, bid_b = team_a_bids[0], team_b_bids[0]

        # Double accept: the second accept hits the OFFERED-state gate.
        get_success_data(api.accept_bid(bid_a["id"],
                                        make_team_coach_headers("coach-a")))
        resp = api.accept_bid(bid_a["id"], make_team_coach_headers("coach-a"))
        validate_error(resp, ApiErrorId.ERR_BID_NOT_OFFERED)

        # 72 hours + 1 second after the offer: the acceptance window is shut.
        set_clock("2026-08-04T00:00:01Z")
        resp = api.accept_bid(bid_b["id"], make_team_coach_headers("coach-b"))
        validate_error(resp, ApiErrorId.ERR_BID_ACCEPTANCE_CLOSED)

        # The checkpoint sweeps tB's lapsed offer; the re-offer skips tB
        # (it lost the slot) and tA (holds an ACCEPTED bid), so the slot
        # stays in the pool.
        result = get_success_data(api.checkpoint(ctx["event"]["id"], DIRECTOR))
        assert result["expired_bid_count"] == 1
        division = get_success_data(api.get_division(ctx["division"]["id"], DIRECTOR))
        assert division["bid_pool_available"] == 1


class TestCascadeSecondAngles:
    def test_appeal_rejected_leaves_scores_ranks_and_bids_untouched(self, api):
        """PRD §3.6: "A `decision` of `REJECTED` moves the appeal to
        `REJECTED` and the deduction to `UPHELD`, where it remains counted in
        all score variants."
        PRD §3.7: "`ACCEPTED` bids are never revoked by re-evaluation — only
        a team withdrawal or disqualification touches them."

        Design: Difficulty/transitive_cascade/appeal_accept_cascades_deduction_score_rank_bid
        """
        ctx = setup_live_event_with_checked_in_teams(
            THREE_TEAMS[:2],
            division_overrides={"paid_bid_count": 1, "at_large_bid_count": 0})
        safety_id = ctx["safety"]["id"]
        head_id = ctx["head"]["id"]
        perf_a = ctx["teams"][0]["performance"]
        perf_b = ctx["teams"][1]["performance"]

        # tA 82.00 (after a 2.00 deduction) behind tB 83.00; tB takes the bid.
        mark_performance_performed(perf_a["id"], safety_id, 150, 0)
        deduction = apply_safety_deduction(perf_a["id"], safety_id)
        submit_full_panel(perf_a["id"], ctx["panel"], 8.4)
        mark_performance_performed(perf_b["id"], safety_id, 148, 0)
        submit_full_panel(perf_b["id"], ctx["panel"], 8.3)
        make_performance_official(perf_a["id"], head_id)
        make_performance_official(perf_b["id"], head_id)
        team_b_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][1]["team"]["id"], DIRECTOR))
        bid_b = team_b_bids[0]

        # A REJECTED appeal triggers no cascade: deduction UPHELD, scores,
        # ranks and the standing offer all unchanged.
        appeal = appeal_deduction(deduction["id"], "coach-a")
        resolve_appeal(appeal["id"], head_id, "REJECTED")

        ded_after = get_success_data(api.get_deduction(deduction["id"], DIRECTOR))
        assert ded_after["status"] == "UPHELD"
        perf_a_after = get_success_data(api.get_performance(perf_a["id"], DIRECTOR))
        assert perf_a_after["official_score"] == pytest.approx(82.00, abs=0.001)
        assert perf_a_after["rank_in_division"] == 2
        bid_b_after = get_success_data(api.get_bid(bid_b["id"], DIRECTOR))
        assert bid_b_after["status"] == "OFFERED"

    def test_withdraw_cancels_scheduled_performances_and_revokes_bids(self, api):
        """PRD §3.3: "Withdrawal moves the team to `WITHDRAWN`, cancels every
        `SCHEDULED` performance of the team (moving each to `CANCELLED`),
        revokes every `OFFERED` or `ACCEPTED` bid of the team to `REVOKED` —
        returning one slot to `bid_pool_available` per revoked bid and
        running the re-offer cascade of §3.7 for each freed slot — and
        increments the team's `version`."

        Design: Difficulty/transitive_cascade/disqualify_cascades_performance_exclusion_and_bid_reoffer
        """
        ctx = setup_live_event_with_checked_in_teams(
            THREE_TEAMS[:2],
            division_overrides={"paid_bid_count": 1, "at_large_bid_count": 0})
        _finish_all_official(api, ctx, [9.0, 8.55])
        team_a = ctx["teams"][0]["team"]

        team_a_bids, _ = validate_paginated(
            api.list_team_bids(team_a["id"], DIRECTOR))
        bid_a = team_a_bids[0]
        get_success_data(api.accept_bid(bid_a["id"],
                                        make_team_coach_headers("coach-a")))
        team_before = get_success_data(api.get_team(team_a["id"], DIRECTOR))

        # Withdrawal triggers the same pool-and-re-offer cascade as
        # disqualification: the ACCEPTED bid is revoked and re-offered.
        withdrawn = get_success_data(api.withdraw_team(
            team_a["id"], make_team_coach_headers("coach-a")))
        assert withdrawn["reg_status"] == "WITHDRAWN"
        assert withdrawn["version"] == team_before["version"] + 1

        bid_a_after = get_success_data(api.get_bid(bid_a["id"], DIRECTOR))
        assert bid_a_after["status"] == "REVOKED"
        # Withdrawal cancels only SCHEDULED performances; the OFFICIAL one is
        # untouched, but its team is out of bid eligibility, so the freed slot
        # re-offers to tB.
        perf_a_after = get_success_data(api.get_performance(
            ctx["teams"][0]["performance"]["id"], DIRECTOR))
        assert perf_a_after["status"] == "OFFICIAL"
        team_b_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][1]["team"]["id"], DIRECTOR))
        offered_b = [b for b in team_b_bids if b["status"] == "OFFERED"]
        assert len(offered_b) == 1

    def test_decline_frees_slot_and_pool_invariant_holds_at_each_step(self, api):
        """PRD §2.8: "Whenever a bid leaves `OFFERED` or `ACCEPTED` for a
        terminal state — declined, expired, or revoked — `bid_pool_available`
        increases by one per freed slot, and a re-offer cascade runs
        immediately to attempt to fill it (§3.7)."
        PRD §3.7: "If no eligible team exists, the slot remains in
        `bid_pool_available`."

        Design: Difficulty/compensating_invariant/bid_pool_conserved_through_decline_and_reoffer
        """
        # Two teams but only one PAID slot: tA (rank 1) is offered; tB is the
        # only re-offer candidate.
        ctx = setup_live_event_with_checked_in_teams(
            THREE_TEAMS[:2],
            division_overrides={"paid_bid_count": 1, "at_large_bid_count": 0})
        _finish_all_official(api, ctx, [9.0, 8.55])

        division, bids = _division_and_bids(api, ctx["division"]["id"])
        assert division["bid_pool_available"] == 0
        assert_bid_pool_invariant(division, bids)
        bid_a = bids[0]
        assert bid_a["team_id"] == ctx["teams"][0]["team"]["id"]

        # Decline: the slot frees and immediately re-offers to tB (PAID
        # re-offers carry no score threshold), keeping the pool at zero.
        get_success_data(api.decline_bid(
            bid_a["id"], make_team_coach_headers("coach-a")))
        division, bids = _division_and_bids(api, ctx["division"]["id"])
        assert division["bid_pool_available"] == 0
        assert_bid_pool_invariant(division, bids)
        team_b_bids, _ = validate_paginated(
            api.list_team_bids(ctx["teams"][1]["team"]["id"], DIRECTOR))
        offered_b = [b for b in team_b_bids if b["status"] == "OFFERED"]
        assert len(offered_b) == 1
        assert offered_b[0]["kind"] == "PAID"
        # The declined bid sits in its terminal state.
        bid_a_after = get_success_data(api.get_bid(bid_a["id"], DIRECTOR))
        assert bid_a_after["status"] == "DECLINED"

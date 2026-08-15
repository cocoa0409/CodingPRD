"""Post-bid interviews and room blocking, the award-recommendation pipeline
with segregation of duties, the award cascade, and terminal lockdown."""
from test_helpers import (
    DECIDER_ID,
    DRAFTER_ID,
    LEAD,
    ApiErrorId,
    add_leveling_adjustment,
    advance_clock,
    assert_award_recommendation,
    assert_bidder_feedback,
    assert_post_bid_interview,
    close_bidding,
    create_post_bid_interview_payload,
    decide_recommendation,
    draft_recommendation,
    get_bid,
    get_package,
    make_chief_estimator_headers,
    make_lead_estimator_headers,
    make_subcontractor_headers,
    setup_awarded_package,
    setup_published_with_bidders,
    setup_recommendation_pending,
    setup_tabulated_package,
    submit_bid,
    submit_recommendation,
    tabulate,
    api_client,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestInterviewRoomOverlap:

    def test_overlapping_same_room_interview_rejected(self):
        """PRD §3.9: "Interviews block rooms: the new interview's
        `interview_room` must not collide with any other `SCHEDULED` interview
        in the same room under half-open interval semantics — the new interval
        from `scheduled_start` up to but not including `scheduled_end` may not
        overlap an existing one, while pure adjacency, where one interview's
        end equals another's start, is allowed; a genuine overlap is rejected
        with `ERR_INTERVIEW_ROOM_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/interview_room_half_open_overlap
        """
        ctx = setup_tabulated_package((1_000_000, 1_100_000),
                                      name="Interview Package")
        bid_x, bid_y = ctx["bids"]
        resp = api_client.create_post_bid_interview(
            create_post_bid_interview_payload(
                bid_x["id"], interview_room="ROOM-1",
                scheduled_start="2026-08-15T10:00:00Z",
                scheduled_end="2026-08-15T11:00:00Z"), LEAD)
        first = validate_success(resp, expected_status=201)
        assert_post_bid_interview(first)
        assert first["status"] == "SCHEDULED"

        # 10:30–11:30 intersects [10:00, 11:00) non-trivially.
        resp = api_client.create_post_bid_interview(
            create_post_bid_interview_payload(
                bid_y["id"], interview_room="ROOM-1",
                scheduled_start="2026-08-15T10:30:00Z",
                scheduled_end="2026-08-15T11:30:00Z"), LEAD)
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_ROOM_OVERLAP)

    def test_adjacent_and_different_room_interviews_accepted(self):
        """PRD §3.9: "Interviews block rooms: the new interview's
        `interview_room` must not collide with any other `SCHEDULED` interview
        in the same room under half-open interval semantics — the new interval
        from `scheduled_start` up to but not including `scheduled_end` may not
        overlap an existing one, while pure adjacency, where one interview's
        end equals another's start, is allowed; a genuine overlap is rejected
        with `ERR_INTERVIEW_ROOM_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/interview_room_half_open_overlap
        """
        ctx = setup_tabulated_package((1_000_000, 1_100_000),
                                      name="Interview Package")
        bid_x, bid_y = ctx["bids"]
        api_client.create_post_bid_interview(
            create_post_bid_interview_payload(
                bid_x["id"], interview_room="ROOM-1",
                scheduled_start="2026-08-15T10:00:00Z",
                scheduled_end="2026-08-15T11:00:00Z"), LEAD)

        # Pure adjacency: existing end 11:00 == new start 11:00 — allowed.
        resp = api_client.create_post_bid_interview(
            create_post_bid_interview_payload(
                bid_y["id"], interview_room="ROOM-1",
                scheduled_start="2026-08-15T11:00:00Z",
                scheduled_end="2026-08-15T12:00:00Z"), LEAD)
        assert validate_success(resp, expected_status=201)["status"] == "SCHEDULED"

        # A different room at an overlapping time is also allowed.
        resp = api_client.create_post_bid_interview(
            create_post_bid_interview_payload(
                bid_y["id"], interview_room="ROOM-2",
                scheduled_start="2026-08-15T10:30:00Z",
                scheduled_end="2026-08-15T11:30:00Z"), LEAD)
        assert validate_success(resp, expected_status=201)["status"] == "SCHEDULED"


class TestInterviewLifecycle:

    def test_time_range_validation_and_double_complete(self):
        """PRD §3.9: "Scheduling requires the bid's package to be `TABULATED`
        or `RECOMMENDATION_PENDING` (otherwise `ERR_PACKAGE_INVALID_STATE`),
        the bid itself to be `SUBMITTED` (otherwise `ERR_BID_INVALID_STATE`),
        and a sane window: `scheduled_start` strictly before `scheduled_end`
        (otherwise `ERR_INVALID_TIME_RANGE`, HTTP 422)."
        PRD §3.9: "Completing an interview moves it `SCHEDULED → HELD` and
        records `outcome_notes`; a `HELD` interview no longer blocks its room
        in future overlap checks. Completing an interview that is not
        `SCHEDULED` is `ERR_INVALID_RESOURCE_STATE`."

        Design: Corner/state_machines/interview_lifecycle_time_range_and_double_complete
        """
        ctx = setup_tabulated_package((1_000_000,), name="IV Package")
        bid = ctx["bids"][0]

        resp = api_client.create_post_bid_interview(
            create_post_bid_interview_payload(
                bid["id"], interview_room="ROOM-2",
                scheduled_start="2026-08-15T10:00:00Z",
                scheduled_end="2026-08-15T10:00:00Z"), LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)

        resp = api_client.create_post_bid_interview(
            create_post_bid_interview_payload(
                bid["id"], interview_room="ROOM-2",
                scheduled_start="2026-08-15T10:00:00Z",
                scheduled_end="2026-08-15T11:00:00Z"), LEAD)
        interview = validate_success(resp, expected_status=201)
        assert interview["status"] == "SCHEDULED"

        resp = api_client.complete_post_bid_interview(
            interview["id"],
            {"outcome_notes": "scope confirmed; exclusions priced"}, LEAD)
        held = validate_success(resp, expected_status=200)
        assert held["status"] == "HELD"
        assert held["outcome_notes"] == "scope confirmed; exclusions priced"

        resp = api_client.complete_post_bid_interview(
            interview["id"], {"outcome_notes": "duplicate"}, LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_RESOURCE_STATE)


class TestRecommendationReturnCycle:

    def test_return_swings_package_back_to_tabulated(self):
        """PRD §3.1: "The full package lifecycle is `DRAFT → PUBLISHED →
        BIDDING_CLOSED → TABULATED → RECOMMENDATION_PENDING → AWARDED`, with a
        return edge from `RECOMMENDATION_PENDING` back to `TABULATED` when a
        recommendation is returned, and `AWARDED` as the terminal state."
        PRD §3.9: "Returning — the other decision — additionally requires
        `decision_notes` to be present (`ERR_INVALID_REQUEST` otherwise); it
        records the same decider fields, moves the recommendation `SUBMITTED →
        RETURNED`, and swings the package `RECOMMENDATION_PENDING → TABULATED`,
        which unlocks leveling and retains `apparent_low_bid_id` and
        `leveled_low_bid_id` from the last tabulation, leaving the field clear
        for a fresh draft."

        Design: Difficulty/non_linear_state_machine/bid_package_recommendation_return_cycle
        """
        ctx = setup_recommendation_pending((1_000_000,), name="Cycle Package")
        rec = ctx["recommendation"]

        returned = decide_recommendation(
            rec["id"], "RETURNED",
            decision_notes="leveling incomplete — revisit exclusions")
        assert returned["status"] == "RETURNED"
        assert returned.get("decided_by_user_id") == DECIDER_ID

        pkg = get_package(ctx["package"]["id"])
        assert pkg["status"] == "TABULATED", \
            "the return edge cycles the package back, not forward"
        assert pkg["apparent_low_bid_id"] is not None, \
            "last tabulation's rankings are retained through the cycle"

    def test_after_return_leveling_unlocks_and_new_draft_accepted(self):
        """PRD §3.9: "Returning — the other decision — additionally requires
        `decision_notes` to be present (`ERR_INVALID_REQUEST` otherwise); it
        records the same decider fields, moves the recommendation `SUBMITTED →
        RETURNED`, and swings the package `RECOMMENDATION_PENDING → TABULATED`,
        which unlocks leveling and retains `apparent_low_bid_id` and
        `leveled_low_bid_id` from the last tabulation, leaving the field clear
        for a fresh draft."
        PRD §3.7: "Adjustments may be created, edited, or deleted only while
        the package is `BIDDING_CLOSED` or `TABULATED`; a leveling write while
        the package is `RECOMMENDATION_PENDING` or `AWARDED` — or not yet
        `BIDDING_CLOSED` — is rejected with `ERR_LEVELING_LOCKED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/bid_package_recommendation_return_cycle
        """
        ctx = setup_recommendation_pending((1_000_000,), name="Cycle Package")
        bid = ctx["bids"][0]
        decide_recommendation(ctx["recommendation"]["id"], "RETURNED",
                              decision_notes="revisit exclusions")

        resp = api_client.create_leveling_adjustment(
            {"bid_id": bid["id"], "description": "post-return leveling edit",
             "treatment": "GC_ALLOWANCE", "amount_cents": 10_000}, LEAD)
        assert validate_success(resp, expected_status=201), \
            "leveling unlocks when the package returns to TABULATED"

        rec2, _ = draft_recommendation(ctx["package"]["id"], bid["id"],
                                       rationale="re-drafted after return")
        assert_award_recommendation(rec2)
        assert rec2["status"] == "DRAFT", \
            "no active recommendation blocks a fresh draft after the return"
        assert rec2["bid_package_id"] == ctx["package"]["id"]


class TestAwardCascade:

    def _setup_two_bid_pending(self):
        """X base 1.0M + 250k allowance (leveled 1.25M); Y base 1.1M."""
        ctx = setup_tabulated_package((1_000_000, 1_100_000),
                                      name="Cascade Package")
        bid_x, bid_y = ctx["bids"]
        add_leveling_adjustment(bid_x["id"], treatment="GC_ALLOWANCE",
                                amount_cents=250_000,
                                description="temp bracing allowance")
        tabulate(ctx["package"]["id"])  # re-tabulate so leveling flows in
        rec, _ = draft_recommendation(
            ctx["package"]["id"], bid_y["id"],
            rationale="leveled low bidder, scope complete")
        rec = submit_recommendation(rec["id"])
        return ctx, bid_x, bid_y, rec

    def test_approval_cascades_package_and_bids(self):
        """PRD §3.10: "Approval of a recommendation triggers the package's
        terminal cascade. The package moves `RECOMMENDATION_PENDING → AWARDED`.
        The recommended bid moves `SUBMITTED → AWARDED`; every other bid still
        `SUBMITTED` moves `SUBMITTED → NOT_AWARDED`."
        PRD §3.9: "On approval, `decided_by_user_id` and `decided_at` are
        recorded and the award cascade of §3.10 fires."

        Design: Difficulty/transitive_cascade/award_approval_three_level_cascade
        """
        ctx, bid_x, bid_y, rec = self._setup_two_bid_pending()
        decided = decide_recommendation(rec["id"], "APPROVED")
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == DECIDER_ID
        assert decided.get("decided_at"), "decided_at must be recorded"

        assert get_package(ctx["package"]["id"])["status"] == "AWARDED"
        assert get_bid(bid_y["id"])["status"] == "AWARDED"
        assert get_bid(bid_x["id"])["status"] == "NOT_AWARDED"

    def test_approval_autocreates_feedback_snapshots_for_losers(self):
        """PRD §3.10: "For each bid that became `NOT_AWARDED`, the system
        auto-creates a **bidder feedback** record in `DRAFT`, snapshotting
        three
        figures at the moment of award: the bid's `leveled_rank` from the
        latest tabulation ordering, its own `leveled_amount_cents`, and the
        `winning_leveled_amount_cents` — the leveled amount of the awarded
        bid."
        PRD §3.8: "Each bid's `leveled_rank` — its 1-based position in the
        leveled ordering under the same tie-breaks — is computed in the same
        pass; it is snapshotted onto feedback records at award time in §3.10."

        Design: Difficulty/transitive_cascade/award_approval_three_level_cascade
        """
        ctx, bid_x, bid_y, rec = self._setup_two_bid_pending()
        decide_recommendation(rec["id"], "APPROVED")

        rows, meta = validate_paginated(
            api_client.list_bidder_feedbacks(bid_x["id"], LEAD))
        assert len(rows) == 1, "exactly one feedback row for the losing bid"
        fb = rows[0]
        assert_bidder_feedback(fb)
        assert fb["status"] == "DRAFT"
        # Leveled ordering: Y 1,100,000 rank 1; X 1,250,000 rank 2.
        assert fb["leveled_rank"] == 2
        assert fb["leveled_amount_cents"] == 1_250_000
        assert fb["winning_leveled_amount_cents"] == 1_100_000

        rows_y, _ = validate_paginated(
            api_client.list_bidder_feedbacks(bid_y["id"], LEAD))
        assert rows_y == [], "the awarded bid gets no feedback record"


class TestRecommendationEligibility:

    def test_withdrawn_bid_ineligible_and_second_draft_blocked(self):
        """PRD §3.9: "The recommended bid must be a `SUBMITTED` bid of this
        very package — a bid from another package or in any other status is
        `ERR_RECOMMENDED_BID_INELIGIBLE` (HTTP 422)."
        PRD §3.9: "At most one recommendation per package may be alive in
        `DRAFT` or `SUBMITTED`; a second draft while one is active is
        `ERR_ACTIVE_RECOMMENDATION_EXISTS` (HTTP 409)."

        Design: Corner/validations/recommended_bid_ineligible_and_active_recommendation_exists
        """
        ctx = setup_published_with_two_bids_then_withdraw()
        pkg, bid_a, bid_b = ctx["package"], ctx["bid_a"], ctx["bid_b"]

        advance_clock("2026-08-10T15:00:00Z")
        close_bidding(pkg["id"])
        tabulate(pkg["id"])

        pkg_now = get_package(pkg["id"])
        resp = api_client.create_award_recommendation(
            {"bid_package_id": pkg["id"], "recommended_bid_id": bid_b["id"],
             "rationale": "withdrawn bid",
             "expected_bid_package_version": pkg_now["version"]},
            make_lead_estimator_headers(DRAFTER_ID))
        validate_error(resp, ApiErrorId.ERR_RECOMMENDED_BID_INELIGIBLE)

        # Eligible bid, fresh version, no active recommendation: succeeds.
        rec, _ = draft_recommendation(pkg["id"], bid_a["id"],
                                      rationale="sole compliant")
        assert rec["status"] == "DRAFT"

        # A second draft while the first is alive is rejected.
        pkg_now = get_package(pkg["id"])
        resp = api_client.create_award_recommendation(
            {"bid_package_id": pkg["id"], "recommended_bid_id": bid_a["id"],
             "rationale": "duplicate draft",
             "expected_bid_package_version": pkg_now["version"]},
            make_lead_estimator_headers(DRAFTER_ID))
        validate_error(resp, ApiErrorId.ERR_ACTIVE_RECOMMENDATION_EXISTS)

        rows, meta = validate_paginated(
            api_client.list_package_award_recommendations(pkg["id"], LEAD))
        assert len(rows) == 1 and meta["total_count"] == 1


def setup_published_with_two_bids_then_withdraw():
    """Two bids on a PUBLISHED package; the second is withdrawn."""
    ctx = setup_published_with_bidders(n=2, name="Rec Package")
    pkg = ctx["package"]
    sub_a = ctx["bidders"][0]["subcontractor"]
    sub_b = ctx["bidders"][1]["subcontractor"]
    bid_a = submit_bid(pkg["id"], sub_a["id"], 1_000_000)
    bid_b = submit_bid(pkg["id"], sub_b["id"], 1_100_000)
    api_client.withdraw_bid(bid_b["id"], make_subcontractor_headers(sub_b["id"]))
    return {"package": pkg, "bid_a": bid_a, "bid_b": bid_b}


class TestRecommendationCreateOcc:

    def test_stale_package_version_rejected_then_fresh_accepted(self):
        """PRD §2.7: "Drafting an award recommendation must carry
        `expected_bid_package_version` equal to the package's current `version`
        as the caller last observed it. If the package's `version` has advanced
        since that observation — for example because a re-tabulation refreshed
        the rankings, or a recommendation draft was just created against the
        same package — the create is rejected with
        `ERR_STALE_PACKAGE_VERSION` (HTTP 412), because a recommendation must
        be based on the latest tabulation state."
        PRD §3.9: "The draft is born in `DRAFT` with `created_by_user_id`
        recorded from the caller's `X-User-ID`, and creating it increments the
        package's `version` by 1 — which is precisely why the next drafter must
        carry a fresh `expected_bid_package_version`."

        Design: Corner/cross_cutting_layers/occ_recommendation_create_stale_package_version
        """
        from test_helpers import tabulate
        ctx = setup_tabulated_package((1_000_000,), name="OCC2 Package")
        pkg, bid = ctx["package"], ctx["bids"][0]
        stale_version = get_package(pkg["id"])["version"]

        # A re-tabulation advances the package version after our read.
        tabulate(pkg["id"])

        resp = api_client.create_award_recommendation(
            {"bid_package_id": pkg["id"], "recommended_bid_id": bid["id"],
             "rationale": "stale basis",
             "expected_bid_package_version": stale_version},
            LEAD)
        validate_error(resp, ApiErrorId.ERR_STALE_PACKAGE_VERSION)

        fresh_version = get_package(pkg["id"])["version"]
        assert fresh_version > stale_version
        resp = api_client.create_award_recommendation(
            {"bid_package_id": pkg["id"], "recommended_bid_id": bid["id"],
             "rationale": "fresh basis",
             "expected_bid_package_version": fresh_version},
            LEAD)
        rec = validate_success(resp, expected_status=201)
        assert rec["status"] == "DRAFT"
        assert get_package(pkg["id"])["version"] == fresh_version + 1, \
            "a successful create increments the package version by exactly 1"


class TestSegregationOfDuties:

    def test_drafter_cannot_decide_but_other_chief_can(self):
        """PRD §3.9: "The `ChiefEstimator` then decides. Approval requires only
        one precondition beyond state: the deciding caller's `X-User-ID` must
        differ from the recommendation's `created_by_user_id` — the drafter may
        not approve their own recommendation, and a violation is
        `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_same_user_cannot_approve_own_draft
        """
        ctx = setup_recommendation_pending((1_000_000,), name="SoD Package")
        rec = ctx["recommendation"]
        assert rec["created_by_user_id"] == DRAFTER_ID

        # Same operator id, ChiefEstimator capacity: still the drafter.
        resp = api_client.decide_award_recommendation(
            rec["id"], {"decision": "APPROVED"},
            make_chief_estimator_headers(DRAFTER_ID))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        current = validate_success(
            api_client.get_award_recommendation(rec["id"], LEAD))
        assert current["status"] == "SUBMITTED", \
            "a SoD-rejected decision leaves the recommendation SUBMITTED"

        decided = decide_recommendation(rec["id"], "APPROVED")
        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == DECIDER_ID


class TestAwardedTerminalLockdown:

    def test_awarded_package_lockdown_and_feedback_resend(self):
        """PRD §3.1: "The full package lifecycle is `DRAFT → PUBLISHED →
        BIDDING_CLOSED → TABULATED → RECOMMENDATION_PENDING → AWARDED`, with a
        return edge from `RECOMMENDATION_PENDING` back to `TABULATED` when a
        recommendation is returned, and `AWARDED` as the terminal state."
        PRD §3.7: "Adjustments may be created, edited, or deleted only while
        the package is `BIDDING_CLOSED` or `TABULATED`; a leveling write while
        the package is `RECOMMENDATION_PENDING` or `AWARDED` — or not yet
        `BIDDING_CLOSED` — is rejected with `ERR_LEVELING_LOCKED` (HTTP 409)."
        PRD §3.7: "Any adjustment write against a bid no longer `SUBMITTED` is
        rejected with `ERR_BID_INVALID_STATE`."
        PRD §3.10: "A `LeadEstimator` later sends a feedback record, optionally
        supplying a `notes` narrative; sending moves it `DRAFT → SENT` and
        stamps `sent_at`. Re-sending a `SENT` record is
        `ERR_INVALID_RESOURCE_STATE`."

        Design: Corner/state_machines/awarded_package_terminal_lockdown_and_feedback_resend
        """
        ctx = setup_awarded_package((1_000_000, 1_100_000), recommend_index=1,
                                    name="Lock Package")
        pkg = ctx["package"]
        bid_x = ctx["bids"][0]  # the loser
        assert pkg["status"] == "AWARDED"

        resp = api_client.publish_bid_package(pkg["id"], LEAD)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_INVALID_STATE)

        resp = api_client.create_leveling_adjustment(
            {"bid_id": bid_x["id"], "description": "post-award leveling attempt",
             "treatment": "GC_ALLOWANCE", "amount_cents": 1_000}, LEAD)
        # After the award cascade every bid of the package is terminal, so the
        # write violates both the leveling lock (package AWARDED, PRD §3.7) and
        # the bid-state gate (bid NOT_AWARDED, PRD §3.7). Both sit at the same
        # cascade tier with no stated order between them.
        assert resp.status_code == 409
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_LEVELING_LOCKED,
                   ApiErrorId.ERR_BID_INVALID_STATE])

        rows, _ = validate_paginated(
            api_client.list_bidder_feedbacks(bid_x["id"], LEAD))
        assert len(rows) == 1
        fb_id = rows[0]["id"]

        resp = api_client.send_bidder_feedback(
            fb_id, {"notes": "You ranked 2 of 2; leveled spread 100000 cents"},
            LEAD)
        sent = validate_success(resp, expected_status=200)
        assert sent["status"] == "SENT"
        assert sent.get("sent_at"), "sent_at must be stamped"
        assert sent["notes"] == "You ranked 2 of 2; leveled spread 100000 cents"

        resp = api_client.send_bidder_feedback(fb_id, {}, LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_RESOURCE_STATE)

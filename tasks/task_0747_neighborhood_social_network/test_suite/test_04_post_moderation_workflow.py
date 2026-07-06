"""Post lifecycle, moderation cascades, trust-score replay, cyclic state."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    make_resident_headers, make_moderator_headers,
    setup_flagged_post, moderate_decision, find_upheld_flag_report,
    setup_neighborhood_with_verified_residents,
    create_post, flag_post, drive_post_to_flagged,
    set_clock, api_client, ADMIN,
    MOD_UPHOLD_PENALTY, SUSPENSION_FLOOR,
)


class TestPostCyclicStateMachine:
    """Difficulty rule 3 — Post cycle PUBLISHED->FLAGGED->HIDDEN->PUBLISHED."""

    def test_post_cycles_via_uphold_then_reverse(self, api):
        """PRD §3.7: "An `UPHOLD` decision on a `Post` target requires that
        the flag report be `OPEN` and that its `target_type` name a post; on
        acceptance it moves the post's `state` from `FLAGGED` to `HIDDEN`,
        moves every open flag report against that post from `OPEN` to
        `UPHELD` (each in the same response), decrements the post author's
        `trust_score` by 25 points, and — if the resulting trust score is
        below the suspension floor of 60 — sets that resident's
        `is_suspended` to `true` as the second cascade step."
        PRD §3.7: "A `REVERSE` decision on a `Post` target requires that the
        post's `state` currently be `HIDDEN` and that a prior `UPHELD`
        moderation decision on the same post exists; on acceptance it moves
        the post's `state` from `HIDDEN` back to `PUBLISHED`, moves every
        `UPHELD` flag report against that post to `REVERSED`, restores the
        author's `trust_score` by 25 points as a compensating adjustment,
        and — if the restored score is now at or above the suspension floor
        of 60 — sets the author's `is_suspended` to `false` as the second
        cascade step."

        Design: Difficulty/non_linear_state_machine/post_cycles_published_flagged_hidden_published_via_reverse
        """
        s = setup_flagged_post(reporter_count=3)
        post = s["post"]
        # State must be FLAGGED after 3 flags.
        assert post["state"] == "FLAGGED"
        # UPHOLD -> HIDDEN.
        moderate_decision(s["mod"]["id"], s["first_fr_id"], "UPHOLD",
                          expected_target_version=s["post_version"])
        post_hidden = get_success_data(api_client.get_post(post["id"], ADMIN))
        assert post_hidden["state"] == "HIDDEN"
        # Locate the UPHELD flag report and REVERSE it.
        upheld = find_upheld_flag_report(post["id"], s["mod"]["id"])
        moderate_decision(s["mod"]["id"], upheld["id"], "REVERSE",
                          expected_target_version=post_hidden["version"])
        post_final = get_success_data(api_client.get_post(post["id"], ADMIN))
        assert post_final["state"] == "PUBLISHED", \
            f"Expected PUBLISHED after REVERSE, got {post_final['state']}"

    def test_reverse_restores_flag_reports_to_reversed(self, api):
        """PRD §3.7: "on acceptance it moves the post's `state` from `HIDDEN`
        back to `PUBLISHED`, moves every `UPHELD` flag report against that
        post to `REVERSED`, restores the author's `trust_score` by 25 points
        as a compensating adjustment, and — if the restored score is now at
        or above the suspension floor of 60 — sets the author's
        `is_suspended` to `false` as the second cascade step."

        Design: Difficulty/non_linear_state_machine/post_cycles_published_flagged_hidden_published_via_reverse
        """
        s = setup_flagged_post(reporter_count=3)
        moderate_decision(s["mod"]["id"], s["first_fr_id"], "UPHOLD",
                          expected_target_version=s["post_version"])
        post_hidden = get_success_data(api_client.get_post(s["post"]["id"], ADMIN))
        upheld = find_upheld_flag_report(s["post"]["id"], s["mod"]["id"])
        moderate_decision(s["mod"]["id"], upheld["id"], "REVERSE",
                          expected_target_version=post_hidden["version"])
        # Read back all flag reports for this post — each UPHELD must now be REVERSED.
        resp = api_client.list_flag_reports(
            make_moderator_headers(s["mod"]["id"]),
            params={"target_id": s["post"]["id"], "status": "REVERSED"},
        )
        data = get_success_data(resp)
        rows = data if isinstance(data, list) else data.get("data", data)
        if isinstance(rows, dict):
            rows = rows.get("data", [])
        assert len(rows) >= 1, "Expected at least one REVERSED FlagReport"


class TestTrustScoreReplay:
    """Difficulty rule 2 — resident_trust_score is a pinned replay."""

    def test_uphold_then_reverse_yields_net_zero_delta(self, api):
        """PRD §3.7: "The `trust_score` is not adjusted incrementally at the
        moment of the decision; it is recomputed from scratch each time it
        changes so that its evolution is deterministic under replay."
        PRD §3.7: "an `UPHOLD` decision subtracts 25; a `REVERSE` decision
        that follows an earlier `UPHOLD` on the same target adds 25 back as a
        compensating adjustment; a `DISMISS` decision contributes no delta."

        Design: Difficulty/combinatorial_formula/resident_trust_score_mode_c_pinned_replay_order_over_moderation_decisions
        """
        s = setup_flagged_post(reporter_count=3)
        author = s["author"]
        # trust before any decision: 100.
        r_before = get_success_data(api_client.get_resident(author["id"], ADMIN))
        assert r_before["trust_score"] == 100
        # UPHOLD -> 75.
        moderate_decision(s["mod"]["id"], s["first_fr_id"], "UPHOLD",
                          expected_target_version=s["post_version"])
        r_after_uphold = get_success_data(api_client.get_resident(author["id"], ADMIN))
        assert r_after_uphold["trust_score"] == 75, \
            f"Expected 75 after UPHOLD (100-25), got {r_after_uphold['trust_score']}"
        # REVERSE -> 100.
        post_hidden = get_success_data(api_client.get_post(s["post"]["id"], ADMIN))
        upheld = find_upheld_flag_report(s["post"]["id"], s["mod"]["id"])
        moderate_decision(s["mod"]["id"], upheld["id"], "REVERSE",
                          expected_target_version=post_hidden["version"])
        r_final = get_success_data(api_client.get_resident(author["id"], ADMIN))
        assert r_final["trust_score"] == 100, \
            f"Expected 100 after REVERSE (compensating), got {r_final['trust_score']}"

    def test_uphold_dock_matches_mod_uphold_penalty(self, api):
        """PRD §3.7: "decrements the post author's `trust_score` by 25
        points" (on UPHOLD).

        Design: Difficulty/combinatorial_formula/resident_trust_score_mode_c_pinned_replay_order_over_moderation_decisions
        """
        s = setup_flagged_post(reporter_count=3)
        author = s["author"]
        r_before = get_success_data(api_client.get_resident(author["id"], ADMIN))
        moderate_decision(s["mod"]["id"], s["first_fr_id"], "UPHOLD",
                          expected_target_version=s["post_version"])
        r_after = get_success_data(api_client.get_resident(author["id"], ADMIN))
        assert r_before["trust_score"] - r_after["trust_score"] == MOD_UPHOLD_PENALTY


class TestUpholdCascadeSuspension:
    """Difficulty rule 4 — depth-3 cascade: UPHOLD -> HIDDEN -> trust drop -> suspend."""

    def test_second_uphold_pushes_trust_below_floor_and_suspends(self, api):
        """PRD §3.7: "decrements the post author's `trust_score` by 25
        points, and — if the resulting trust score is below the suspension
        floor of 60 — sets that resident's `is_suspended` to `true` as the
        second cascade step."

        Design: Difficulty/transitive_cascade/moderation_uphold_cascades_post_hidden_trust_decrement_and_suspension_depth_3
        """
        # Build a scenario where two UPHOLDs occur on distinct posts by the
        # same author so trust falls from 100 -> 75 -> 50 (< 60 floor).
        n, mod, residents = setup_neighborhood_with_verified_residents(4)
        author = residents[0]
        reporters = residents[1:4]
        # Post P0 with 3 flags + UPHOLD -> trust 100 -> 75.
        p0 = create_post(author["id"], n["id"], category="GENERAL", title="p0", body="b")
        fr_p0, p0 = drive_post_to_flagged(p0["id"], [r["id"] for r in reporters])
        moderate_decision(mod["id"], fr_p0, "UPHOLD",
                          expected_target_version=p0["version"])
        r_mid = get_success_data(api_client.get_resident(author["id"], ADMIN))
        assert r_mid["trust_score"] == 75
        assert r_mid["is_suspended"] is False, "Not below floor yet"
        # Post P1 -> flag -> UPHOLD -> trust 50, suspended=true.
        p1 = create_post(author["id"], n["id"], category="GENERAL", title="p1", body="b")
        fr_p1, p1 = drive_post_to_flagged(p1["id"], [r["id"] for r in reporters])
        moderate_decision(mod["id"], fr_p1, "UPHOLD",
                          expected_target_version=p1["version"])
        r_final = get_success_data(api_client.get_resident(author["id"], ADMIN))
        assert r_final["trust_score"] == 50, \
            f"Expected 50 after two UPHOLDs, got {r_final['trust_score']}"
        assert r_final["is_suspended"] is True, \
            "Expected is_suspended=true after trust dropped below SUSPENSION_FLOOR"

    def test_second_uphold_hides_the_new_post(self, api):
        """PRD §3.7: "An `UPHOLD` decision on a `Post` target requires that
        the flag report be `OPEN` and that its `target_type` name a post; on
        acceptance it moves the post's `state` from `FLAGGED` to `HIDDEN`,
        moves every open flag report against that post from `OPEN` to
        `UPHELD` (each in the same response), decrements the post author's
        `trust_score` by 25 points, and — if the resulting trust score is
        below the suspension floor of 60 — sets that resident's
        `is_suspended` to `true` as the second cascade step."

        Design: Difficulty/transitive_cascade/moderation_uphold_cascades_post_hidden_trust_decrement_and_suspension_depth_3
        """
        n, mod, residents = setup_neighborhood_with_verified_residents(4)
        author = residents[0]
        reporters = residents[1:4]
        p0 = create_post(author["id"], n["id"], category="GENERAL", title="p0", body="b")
        fr_p0, p0 = drive_post_to_flagged(p0["id"], [r["id"] for r in reporters])
        moderate_decision(mod["id"], fr_p0, "UPHOLD",
                          expected_target_version=p0["version"])
        p1 = create_post(author["id"], n["id"], category="GENERAL", title="p1", body="b")
        fr_p1, p1 = drive_post_to_flagged(p1["id"], [r["id"] for r in reporters])
        moderate_decision(mod["id"], fr_p1, "UPHOLD",
                          expected_target_version=p1["version"])
        p1_final = get_success_data(api_client.get_post(p1["id"], ADMIN))
        assert p1_final["state"] == "HIDDEN", \
            f"Expected p1.state=HIDDEN after UPHOLD, got {p1_final['state']}"


class TestUpholdReverseConservesTrustScore:
    """Difficulty rule 9 — compensating invariant: UPHOLD+REVERSE net delta 0."""

    def test_trust_score_after_uphold_then_reverse_equals_pre(self, api):
        """PRD §3.7: "an `UPHOLD` decision subtracts 25; a `REVERSE` decision
        that follows an earlier `UPHOLD` on the same target adds 25 back as a
        compensating adjustment; a `DISMISS` decision contributes no delta."

        Design: Difficulty/compensating_invariant/uphold_then_reverse_on_post_leaves_author_trust_score_unchanged
        """
        s = setup_flagged_post(reporter_count=3)
        author = s["author"]
        r_before = get_success_data(api_client.get_resident(author["id"], ADMIN))
        trust_pre = r_before["trust_score"]
        assert trust_pre == 100
        moderate_decision(s["mod"]["id"], s["first_fr_id"], "UPHOLD",
                          expected_target_version=s["post_version"])
        post_hidden = get_success_data(api_client.get_post(s["post"]["id"], ADMIN))
        upheld = find_upheld_flag_report(s["post"]["id"], s["mod"]["id"])
        moderate_decision(s["mod"]["id"], upheld["id"], "REVERSE",
                          expected_target_version=post_hidden["version"])
        r_after = get_success_data(api_client.get_resident(author["id"], ADMIN))
        assert r_after["trust_score"] == trust_pre, \
            f"Conservation broken: pre={trust_pre}, post={r_after['trust_score']}"

    def test_is_suspended_returns_to_false_after_reverse(self, api):
        """PRD §3.7: "if the restored score is now at or above the
        suspension floor of 60 — sets the author's `is_suspended` to `false`
        as the second cascade step."

        Design: Difficulty/compensating_invariant/uphold_then_reverse_on_post_leaves_author_trust_score_unchanged
        """
        s = setup_flagged_post(reporter_count=3)
        moderate_decision(s["mod"]["id"], s["first_fr_id"], "UPHOLD",
                          expected_target_version=s["post_version"])
        post_hidden = get_success_data(api_client.get_post(s["post"]["id"], ADMIN))
        upheld = find_upheld_flag_report(s["post"]["id"], s["mod"]["id"])
        moderate_decision(s["mod"]["id"], upheld["id"], "REVERSE",
                          expected_target_version=post_hidden["version"])
        r_after = get_success_data(api_client.get_resident(s["author"]["id"], ADMIN))
        assert r_after["is_suspended"] is False, \
            "is_suspended must fall to false when trust restored above floor"


class TestSuspendedResidentCannotPost:
    """Difficulty rule 7 — cross-entity: Post creation gated by Resident.is_suspended."""

    def test_suspended_resident_post_rejected_with_err_resident_suspended(self, api):
        """PRD §2.6: "First, if the acting resident's `is_suspended` is
        `true`, new writes on `POST /neighborhood/posts`, `POST
        /neighborhood/marketplace-listings`, `POST /neighborhood/incidents`,
        and `POST /neighborhood/flag-reports` are rejected with
        `ERR_RESIDENT_SUSPENDED` (HTTP 403)."

        Design: Difficulty/cross_entity_state_dependency/post_creation_requires_resident_verified_and_not_suspended
        """
        # Reuse the two-UPHOLD scaffold to reach is_suspended=true.
        n, mod, residents = setup_neighborhood_with_verified_residents(4)
        author = residents[0]
        reporters = residents[1:4]
        for i in range(2):
            p = create_post(author["id"], n["id"], category="GENERAL",
                          title=f"p{i}", body="b")
            fr, p = drive_post_to_flagged(p["id"], [r["id"] for r in reporters])
            moderate_decision(mod["id"], fr, "UPHOLD",
                              expected_target_version=p["version"])
        author_final = get_success_data(api_client.get_resident(author["id"], ADMIN))
        assert author_final["is_suspended"] is True
        # Now attempt a new post — must reject with ERR_RESIDENT_SUSPENDED.
        from test_helpers import create_post_payload
        resp = api_client.create_post(
            create_post_payload(author["id"], n["id"], category="GENERAL",
                              title="blocked", body="b"),
            make_resident_headers(author["id"]),
        )
        validate_error(resp, "ERR_RESIDENT_SUSPENDED")

    def test_suspended_flag_indicates_trust_below_floor(self, api):
        """PRD §3.7: "If the recomputed `trust_score` falls below the
        suspension floor of 60, the resident's `is_suspended` becomes `true`;
        if it rises back to at least the suspension floor, `is_suspended`
        becomes `false`."

        Design: Difficulty/cross_entity_state_dependency/post_creation_requires_resident_verified_and_not_suspended
        """
        n, mod, residents = setup_neighborhood_with_verified_residents(4)
        author = residents[0]
        reporters = residents[1:4]
        for i in range(2):
            p = create_post(author["id"], n["id"], category="GENERAL",
                          title=f"p{i}", body="b")
            fr, p = drive_post_to_flagged(p["id"], [r["id"] for r in reporters])
            moderate_decision(mod["id"], fr, "UPHOLD",
                              expected_target_version=p["version"])
        r = get_success_data(api_client.get_resident(author["id"], ADMIN))
        assert r["trust_score"] < SUSPENSION_FLOOR
        assert r["is_suspended"] is True


class TestModerationOccStaleVersion:
    """Corner: ERR_STALE_TARGET_VERSION on moderation with mismatched version."""

    def test_moderation_with_stale_version_returns_412(self, api):
        """PRD §2.7: "A moderation-decision submission (`POST
        /neighborhood/moderation-decisions`) requires the client-supplied
        `expected_target_version` in the request body; this field is
        non-optional on that endpoint and carries the client's last observed
        `version` of the flagged target — the `Post` or `MarketplaceListing`
        addressed by the target's associated `FlagReport`. If
        `expected_target_version` does not equal the flagged target's
        current `version` on the server, the create is rejected with
        `ERR_STALE_TARGET_VERSION` (HTTP 412)."

        Design: Corner/errors/err_stale_target_version_on_moderation_decision
        """
        s = setup_flagged_post(reporter_count=3)
        # Submit with expected_target_version = current version - 1 (stale).
        stale_version = s["post_version"] - 1
        from test_helpers import create_moderation_decision_payload
        resp = api_client.create_moderation_decision(
            create_moderation_decision_payload(
                s["mod"]["id"], s["first_fr_id"], "UPHOLD",
                stale_version, rationale="stale"),
            make_moderator_headers(s["mod"]["id"]),
        )
        validate_error(resp, "ERR_STALE_TARGET_VERSION")


class TestDuplicateFlagReportRejected:
    """Corner: ERR_DUPLICATE_FLAG when same reporter re-files on OPEN flag."""

    def test_same_reporter_second_flag_on_open_returns_duplicate(self, api):
        """PRD §2.6: "flag-report creation rejects a duplicate (a same-reporter
        row against the same combination of `target_type` and `target_id`
        whose `status` is `OPEN` or `UPHELD`) with `ERR_DUPLICATE_FLAG` (HTTP
        409)."

        Design: Corner/validations/duplicate_flag_rejected_when_same_reporter_open_or_upheld
        """
        n, mod, residents = setup_neighborhood_with_verified_residents(2)
        author = residents[0]
        reporter = residents[1]
        p = create_post(author["id"], n["id"], title="T", body="b")
        flag_post(reporter["id"], p["id"])
        # Duplicate flag from same reporter -> 409.
        from test_helpers import create_flag_report_payload
        resp = api_client.create_flag_report(
            create_flag_report_payload(reporter["id"], "POST", p["id"], reason="SPAM"),
            make_resident_headers(reporter["id"]),
        )
        validate_error(resp, "ERR_DUPLICATE_FLAG")

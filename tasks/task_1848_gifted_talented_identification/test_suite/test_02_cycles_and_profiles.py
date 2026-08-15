"""Screening cycle pipeline and cut-score profile publish lifecycle."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_cycle,
    api_client,
    assert_cut_score_profile,
    assert_screening_cycle,
    create_cycle,
    create_cut_score_profile_payload,
    create_profile,
    create_screening_cycle_payload,
    get_cycle,
    publish_profile,
    setup_case_in_review,
    cast_vote,
    open_band_review,
    validate_error,
    validate_paginated,
    validate_success,
)

GC = TEST_USERS["gifted_coordinator_headers"]


class TestCycleAdvance:
    def test_cycle_advance_rejects_skip_returns_invalid_cycle_state(self, api):
        """PRD §3.2: "A coordinator advances it by naming a `target_state`, and
        the target must be the immediate successor of the current state — any
        skip, reversal, or advance from `FINALIZED` fails with
        `ERR_INVALID_CYCLE_STATE`."

        Design: Corner/state_machines/cycle_advance_rejects_skip_returns_invalid_cycle_state
        """
        cycle = create_cycle()
        resp = api.advance_cycle(cycle["id"], {"target_state": "REVIEW"}, GC)
        validate_error(resp, ApiErrorId.ERR_INVALID_CYCLE_STATE.value)
        after = get_cycle(cycle["id"])
        assert after["status"] == "DRAFT", "cycle must remain DRAFT after a rejected skip"

    def test_cycle_open_requires_published_profile(self, api):
        """PRD §3.2: "leaving `DRAFT` for `OPEN` requires that a cut-score
        profile already be published for the cycle (otherwise
        `ERR_NO_PUBLISHED_PROFILE`)".

        Design: Corner/state_machines/cycle_open_requires_published_profile
        """
        cycle = create_cycle()
        create_profile(cycle["id"])  # DRAFT profile — never published
        resp = api.advance_cycle(cycle["id"], {"target_state": "OPEN"}, GC)
        validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_PROFILE.value)
        after = get_cycle(cycle["id"])
        assert after["status"] == "DRAFT"

    def test_cycle_finalize_blocked_by_open_cases(self, api):
        """PRD §3.2: "leaving `REVIEW` for `FINALIZED` requires that no case in
        the cycle still sits in `SCREENING`, `AWAITING_COMMITTEE`, or
        `APPEAL_PENDING` (otherwise `ERR_CYCLE_HAS_OPEN_CASES`)".

        Design: Corner/state_machines/cycle_finalize_blocked_by_open_cases
        """
        ctx = setup_case_in_review(99, 90, 88)  # composite 94 -> AWAITING_COMMITTEE
        cycle_id = ctx["cycle"]["id"]
        case_id = ctx["case"]["id"]

        resp = api.advance_cycle(cycle_id, {"target_state": "FINALIZED"}, GC)
        validate_error(resp, ApiErrorId.ERR_CYCLE_HAS_OPEN_CASES.value)

        # Decide the case via BAND_REVIEW (two DENY votes), then the same
        # advance succeeds.
        review = open_band_review(case_id)
        cast_vote(review["id"], "DENY", "cm-1")
        cast_vote(review["id"], "DENY", "cm-2")
        fin = validate_success(
            api.advance_cycle(cycle_id, {"target_state": "FINALIZED"}, GC), 200)
        assert fin["status"] == "FINALIZED"


class TestCycleWindowOverlap:
    def test_overlapping_same_band_window_rejected(self, api):
        """PRD §3.2: "The screening window is a half-open interval — it
        includes the open date and excludes the close date — and within the
        same grade band, two cycles' screening windows must not overlap,
        though adjacency (one closing the day another opens) is allowed; a
        clashing create is rejected with `ERR_CYCLE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cycle_windows_overlap_half_open_adjacency
        """
        create_cycle()
        resp = api.create_screening_cycle(
            create_screening_cycle_payload(
                name="Winter ES", screening_open_on="2026-11-01",
                screening_close_on="2027-03-01", referral_close_on="2026-12-15"),
            GC)
        validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_OVERLAP.value)

    def test_adjacent_and_different_band_windows_accepted(self, api):
        """PRD §3.2: "within the same grade band, two cycles' screening
        windows must not overlap, though adjacency (one closing the day
        another opens) is allowed".

        Design: Difficulty/resource_temporal_overlap/cycle_windows_overlap_half_open_adjacency
        """
        create_cycle()
        # Adjacent same-band: opens the day the first closes -> allowed.
        adj = validate_success(
            api.create_screening_cycle(
                create_screening_cycle_payload(
                    name="Spring ES", screening_open_on="2026-12-15",
                    screening_close_on="2027-04-01",
                    referral_close_on="2027-01-31"),
                GC),
            201)
        assert adj["status"] == "DRAFT"
        # Overlapping window in a different band -> the rule is band-scoped.
        other = validate_success(
            api.create_screening_cycle(
                create_screening_cycle_payload(
                    name="Winter MS", grade_band="MIDDLE",
                    screening_open_on="2026-11-01",
                    screening_close_on="2027-03-01",
                    referral_close_on="2026-12-15"),
                GC),
            201)
        assert other["status"] == "DRAFT"


class TestProfilePublish:
    def test_profile_publish_supersedes_prior(self, api):
        """PRD §3.2: "On success, three things happen atomically: the profile
        moves `DRAFT` → `PUBLISHED`; whatever profile of the same cycle was
        previously `PUBLISHED` (if any) moves to `SUPERSEDED`; and the cycle's
        `published_profile_id` pointer is rewritten to the newly published
        profile's id while the cycle's `version` increments by one."

        Design: Corner/state_machines/profile_publish_supersedes_prior
        """
        cycle = create_cycle()
        prof_a = create_profile(cycle["id"], label="A")
        prof_b = create_profile(
            cycle["id"], label="B", ability_weight=0.35, achievement_weight=0.25,
            rating_weight=0.25, portfolio_weight=0.15, cut_score=93,
            review_band_floor=86, cut_score_2e=88, review_band_floor_2e=80)
        publish_profile(prof_a["id"], cycle["version"])
        cycle_after_a = get_cycle(cycle["id"])
        assert cycle_after_a["published_profile_id"] == prof_a["id"]

        publish_profile(prof_b["id"], cycle_after_a["version"])
        cycle_after_b = get_cycle(cycle["id"])
        assert cycle_after_b["published_profile_id"] == prof_b["id"], (
            "published_profile_id must re-point to the newly published profile")
        assert cycle_after_b["version"] == cycle_after_a["version"] + 1, (
            "each publish increments the cycle version by one")

        sup_resp = api.list_cut_score_profiles(
            cycle["id"], GC, params={"status": "SUPERSEDED"})
        superseded, meta = validate_paginated(sup_resp)
        assert [p["id"] for p in superseded] == [prof_a["id"]]
        assert superseded[0]["status"] == "SUPERSEDED"
        assert_cut_score_profile(superseded[0])

        pub_resp = api.list_cut_score_profiles(
            cycle["id"], GC, params={"status": "PUBLISHED"})
        published, _ = validate_paginated(pub_resp)
        assert [p["id"] for p in published] == [prof_b["id"]]

    def test_republish_of_published_profile_rejected(self, api):
        """PRD §3.2: "A coordinator publishes a profile that is still in
        `DRAFT` — publishing a profile in any other state fails with
        `ERR_PROFILE_NOT_DRAFT`".

        Design: Corner/state_machines/republish_of_published_profile_rejected
        """
        cycle = create_cycle()
        prof_a = create_profile(cycle["id"], label="A")
        publish_profile(prof_a["id"], cycle["version"])
        current = get_cycle(cycle["id"])
        resp = api.publish_cut_score_profile(
            prof_a["id"], {"expected_cycle_version": current["version"]}, GC)
        validate_error(resp, ApiErrorId.ERR_PROFILE_NOT_DRAFT.value)

    def test_occ_profile_publish_stale_cycle(self, api):
        """PRD §2.6: "Publishing a cut-score profile requires the request to
        carry `expected_cycle_version`, set to the `version` of the parent
        `ScreeningCycle` as the client last observed it. If another writer has
        advanced the cycle's version since that read — which happens precisely
        when a competing publish succeeded, because every publish bumps the
        cycle's `version` by one — the publish is rejected with
        `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_profile_publish_stale_cycle
        """
        cycle = create_cycle()
        stale_version = cycle["version"]
        prof_a = create_profile(cycle["id"], label="A")
        prof_b = create_profile(
            cycle["id"], label="B", ability_weight=0.35, achievement_weight=0.25,
            rating_weight=0.25, portfolio_weight=0.15, cut_score=93,
            review_band_floor=86, cut_score_2e=88, review_band_floor_2e=80)
        publish_profile(prof_a["id"], stale_version)  # bumps cycle version

        resp = api.publish_cut_score_profile(
            prof_b["id"], {"expected_cycle_version": stale_version}, GC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

        pub_resp = api.list_cut_score_profiles(
            cycle["id"], GC, params={"status": "PUBLISHED"})
        published, _ = validate_paginated(pub_resp)
        assert [p["id"] for p in published] == [prof_a["id"]], (
            "the stale publish must not supersede the already-published profile")
        draft_resp = api.list_cut_score_profiles(
            cycle["id"], GC, params={"status": "DRAFT"})
        drafts, _ = validate_paginated(draft_resp)
        assert [p["id"] for p in drafts] == [prof_b["id"]]
        assert get_cycle(cycle["id"])["published_profile_id"] == prof_a["id"]

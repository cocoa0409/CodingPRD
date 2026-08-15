"""Advancement publication, the scholarship waterfall, and mentor recognition.

Covers: the tiered allocation waterfall with its four-key ranking, OCC on the
edition at publish time, the advancement freeze on quota edits, the
unjudged-project and missing-pool preconditions, the award-precedence
waterfall with integer-cents clamping, pool conservation across
propose/revoke, and both mentor recognition variants with tier thresholds.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    add_active_judge,
    add_mentor,
    api_client,
    assert_mentor,
    current_edition_version,
    fd_headers,
    finalize_awards,
    get_award,
    get_category,
    get_edition,
    get_mentor,
    get_pool,
    get_project,
    judge_project_fully,
    create_pool,
    propose_award,
    publish_advancement,
    setup_judging,
    setup_partially_judged,
    setup_publishable,
    validate_error,
    validate_success,
)
from test_helpers import (
    add_category,
    create_edition,
    open_registration,
    register_project,
    submit_project,
    close_registration,
    schedule_booth,
    record_inspection,
    begin_judging,
)

EPS = 1e-9


def _advancement_waterfall_scenario():
    """Five projects across C1 (slots=1) and C2 (slots=2), all JUDGED+PASSED,
    published. Raws: P1 95/97, P2 60/62, P3 80/82, P4 80/82 (created after
    P3), P5 65/67. Returns the five project ids."""
    edition = create_edition(name="Adv Edition")
    c1 = add_category(edition["id"], code="C1", name="Cat1", slots=1)
    c2 = add_category(edition["id"], code="C2", name="Cat2", slots=2)
    mentor = add_mentor(full_name="Mentor A")
    open_registration(edition["id"])
    projects = [
        register_project(edition["id"], c1["id"], mentor["id"], title="P1"),
        register_project(edition["id"], c1["id"], mentor["id"], title="P2"),
        register_project(edition["id"], c2["id"], mentor["id"], title="P3"),
        register_project(edition["id"], c2["id"], mentor["id"], title="P4"),
        register_project(edition["id"], c2["id"], mentor["id"], title="P5"),
    ]
    for project in projects:
        submit_project(project["id"], mentor["id"])
    close_registration(edition["id"])
    j1 = add_active_judge(edition["id"], full_name="J1", max_assignments=20)
    j2 = add_active_judge(edition["id"], full_name="J2", max_assignments=20)
    for i, project in enumerate(projects):
        schedule_booth(project["id"], hall="A", booth_number=i + 1)
        record_inspection(project["id"], "PASS")
    begin_judging(edition["id"])
    for project, raw1, raw2 in zip(projects, (95, 60, 80, 80, 65), (97, 62, 82, 82, 67)):
        judge_project_fully(project["id"], [(j1, raw1), (j2, raw2)])
    publish_advancement(edition["id"])
    return [project["id"] for project in projects]


def _scholarship_waterfall_scenario():
    """One ADVANCED project carrying GRAND_PRIZE + CATEGORY_FIRST +
    CATEGORY_SECOND proposals (created in reverse precedence order), pool
    550000, published and finalized."""
    ctx = setup_publishable(raws=(90, 95), name="Waterfall Edition")
    edition_id = ctx["edition"]["id"]
    project_id = ctx["project"]["id"]
    aw_second = propose_award(edition_id, project_id, "CATEGORY_SECOND")
    aw_first = propose_award(edition_id, project_id, "CATEGORY_FIRST")
    aw_grand = propose_award(edition_id, project_id, "GRAND_PRIZE")
    pool = create_pool(edition_id, 550000)
    publish_advancement(edition_id)
    finalize_awards(edition_id)
    return {"grand": aw_grand["id"], "first": aw_first["id"], "second": aw_second["id"], "pool": pool["id"]}


def _mentor_variant_scenario():
    """Mentor owns P1 (raws 95/97) and P2 (raws 60/62); category slots=1 so P1
    ADVANCES and P2 lands WAITLISTED; P1 carries a CATEGORY_FIRST award;
    edition finalized. Returns (mentor_id, p1_id, p2_id)."""
    ctx = setup_judging(num_projects=2, slots=1, name="MentorVar Edition")
    p1, p2 = ctx["projects"]
    j1, j2 = ctx["judges"]
    judge_project_fully(p1["id"], [(j1, 95), (j2, 97)])
    judge_project_fully(p2["id"], [(j1, 60), (j2, 62)])
    propose_award(ctx["edition"]["id"], p1["id"], "CATEGORY_FIRST")
    create_pool(ctx["edition"]["id"], 1000000)
    publish_advancement(ctx["edition"]["id"])
    finalize_awards(ctx["edition"]["id"])
    return ctx["mentor"]["id"], p1["id"], p2["id"]


def _tier_bronze_scenario():
    """Mentor owns RP1 (raws 90/92, CATEGORY_FIRST award) and RP2 (raws
    80/78); category slots=2 so both advance; edition finalized."""
    ctx = setup_judging(num_projects=2, slots=2, name="Rec Edition")
    p1, p2 = ctx["projects"]
    j1, j2 = ctx["judges"]
    judge_project_fully(p1["id"], [(j1, 90), (j2, 92)])
    judge_project_fully(p2["id"], [(j1, 80), (j2, 78)])
    propose_award(ctx["edition"]["id"], p1["id"], "CATEGORY_FIRST")
    create_pool(ctx["edition"]["id"], 1000000)
    publish_advancement(ctx["edition"]["id"])
    finalize_awards(ctx["edition"]["id"])
    return ctx["mentor"]["id"], p1["id"], p2["id"]


def _silver_scenario():
    """Mentor owns PA (95/97) and PB (90/92), both ADVANCED, each carrying a
    GRAND_PRIZE and a CATEGORY_FIRST; pool 2000000; edition finalized."""
    ctx = setup_judging(num_projects=2, slots=2, name="Silver Edition")
    pa, pb = ctx["projects"]
    j1, j2 = ctx["judges"]
    judge_project_fully(pa["id"], [(j1, 95), (j2, 97)])
    judge_project_fully(pb["id"], [(j1, 90), (j2, 92)])
    for project in (pa, pb):
        propose_award(ctx["edition"]["id"], project["id"], "GRAND_PRIZE")
        propose_award(ctx["edition"]["id"], project["id"], "CATEGORY_FIRST")
    pool = create_pool(ctx["edition"]["id"], 2000000)
    publish_advancement(ctx["edition"]["id"])
    finalize_awards(ctx["edition"]["id"])
    return ctx["mentor"]["id"], pool["id"]


class TestAdvancementWaterfall:
    def test_single_slot_category_advances_winner_and_waitlists_runner_up(self, api):
        """PRD §3.7: "The first `advancement_slots` projects in a category are
        marked `ADVANCED`. The next tranche forms the waitlist: its depth is
        the category's slot count divided by two and rounded down, but never
        less than one, and those projects are marked `WAITLISTED`."

        Design: Difficulty/combinatorial_formula/advancement_allocation_tiered_waterfall_with_tiebreak
        """
        p1, p2, _p3, _p4, _p5 = _advancement_waterfall_scenario()

        # C1, slots=1: waitlist depth is max(1, 1//2) = 1.
        w1 = get_project(p1)
        w2 = get_project(p2)
        assert w1["final_aggregate"] == pytest.approx(1.53, abs=EPS)
        assert w1["advancement_result"] == "ADVANCED" and w1["advancement_rank"] == 1
        assert w2["final_aggregate"] == pytest.approx(-1.29, abs=EPS)
        assert w2["advancement_result"] == "WAITLISTED" and w2["advancement_rank"] == 2

    def test_tie_break_falls_through_median_and_count_to_created_at(self, api):
        """PRD §3.7: "ties break on the higher median of `raw_score` across the
        project's submitted sheets (with an even number of sheets the median is
        the mean of the two middle values — sheets of 80 and 82 yield a median
        of 81); further ties break on the greater count of submitted sheets;
        and any remaining tie breaks on the earlier project `created_at`, never
        on the project id."

        Design: Difficulty/combinatorial_formula/advancement_allocation_tiered_waterfall_with_tiebreak
        """
        _p1, _p2, p3, p4, p5 = _advancement_waterfall_scenario()

        # C2, slots=2: P3 and P4 tie on aggregate (0.32), median raw (81), and
        # sheet count (2); P3 was created earlier and takes rank 1.
        t3 = get_project(p3)
        t4 = get_project(p4)
        t5 = get_project(p5)
        assert t3["final_aggregate"] == pytest.approx(0.32, abs=EPS)
        assert t3["advancement_result"] == "ADVANCED" and t3["advancement_rank"] == 1
        assert t4["final_aggregate"] == pytest.approx(0.32, abs=EPS)
        assert t4["advancement_result"] == "ADVANCED" and t4["advancement_rank"] == 2, (
            "the created_at tie-break must seat the earlier-created project first"
        )
        # Waitlist depth is max(1, 2//2) = 1; both categories filled all slots,
        # so no at-large slot can promote P5.
        assert t5["final_aggregate"] == pytest.approx(-0.89, abs=EPS)
        assert t5["advancement_result"] == "WAITLISTED" and t5["advancement_rank"] == 3


class TestScholarshipWaterfall:
    def test_precedence_order_and_remaining_clamp(self, api):
        """PRD §3.8: "The waterfall then processes every `PROPOSED` award in
        the edition in a fixed precedence order: `GRAND_PRIZE` first, then
        `CATEGORY_FIRST`, then `CATEGORY_SECOND`, then `SPECIAL_TOPIC`. Each
        award receives the smaller of its tier cap and the pool's remaining
        balance at that moment — caps of 400000 cents for a grand prize,
        300000 for a category first, 150000 for a category second, and 100000
        for a special topic."

        Design: Difficulty/combinatorial_formula/scholarship_waterfall_nested_rounding_integer_cents
        """
        ids = _scholarship_waterfall_scenario()
        grand = get_award(ids["grand"])
        first = get_award(ids["first"])
        assert grand["scholarship_amount_cents"] == 400000, (
            "GRAND_PRIZE is processed first and takes its full 400000 cap"
        )
        assert grand["status"] == "CONFERRED"
        assert first["scholarship_amount_cents"] == 150000, (
            "CATEGORY_FIRST is clamped from its 300000 cap to the remaining 150000"
        )
        assert first["status"] == "CONFERRED"

    def test_exhausted_pool_still_confers_zero_awards(self, api):
        """PRD §3.8: "All amounts are integer cents: when the remaining pool is
        smaller than a cap, the award takes exactly the remaining amount and
        the pool drops to zero, with no fractional cents anywhere. Every
        processed award transitions `PROPOSED` → `CONFERRED` with its
        `scholarship_amount_cents` recorded — including awards that receive 0,
        which are still conferred".

        Design: Difficulty/combinatorial_formula/scholarship_waterfall_nested_rounding_integer_cents
        """
        ids = _scholarship_waterfall_scenario()
        second = get_award(ids["second"])
        pool = get_pool(ids["pool"])
        assert second["scholarship_amount_cents"] == 0
        assert second["status"] == "CONFERRED", "zero-amount awards are still conferred"
        assert pool["remaining_cents"] == 0


class TestScholarshipPoolInvariant:
    def _setup_proposed_award_with_pool(self):
        ctx = setup_judging(num_projects=1, judges_spec=[], name="Inv2 Edition", code="CHEM")
        edition_id = ctx["edition"]["id"]
        project_id = ctx["projects"][0]["id"]
        pool = create_pool(edition_id, 300000)
        award = propose_award(edition_id, project_id, "CATEGORY_FIRST")
        return award["id"], pool["id"]

    def test_revoke_proposed_award(self, api):
        """PRD §3.8: "While the edition is in `JUDGING` or
        `ADVANCEMENT_PUBLISHED`, a proposed award may be revoked (`PROPOSED` →
        `REVOKED`); both conferral and any revocation recompute the affected
        mentor's recognition totals."

        Design: Difficulty/compensating_invariant/scholarship_pool_invariant_confer_revoke
        """
        award_id, _pool_id = self._setup_proposed_award_with_pool()
        revoked = validate_success(api_client.revoke_award(award_id, fd_headers()))
        assert revoked["status"] == "REVOKED"

    def test_propose_revoke_pair_conserves_pool(self, api):
        """PRD §3.8: "The pool's `remaining_cents` starts at the total and is
        debited as awards are conferred."

        Design: Difficulty/compensating_invariant/scholarship_pool_invariant_confer_revoke
        """
        award_id, pool_id = self._setup_proposed_award_with_pool()
        validate_success(api_client.revoke_award(award_id, fd_headers()))

        pool = get_pool(pool_id)
        assert pool["total_cents"] == 300000
        assert pool["remaining_cents"] == 300000, (
            "nothing was ever conferred, so the propose/revoke pair must leave the pool untouched"
        )


class TestPublishGuards:
    def test_publish_requires_all_projects_judged(self, api):
        """PRD §3.7: "Before the edition may move `JUDGING` →
        `ADVANCEMENT_PUBLISHED`, every `CONFIRMED` project must have reached
        `judging_status` `JUDGED` — otherwise the transition is rejected with
        `ERR_UNJUDGED_PROJECTS`".

        Design: Corner/state_machines/publish_advancement_requires_all_judged
        """
        ctx = setup_partially_judged(name="UJ Edition")
        edition_id = ctx["edition"]["id"]
        version = current_edition_version(edition_id)

        resp = api_client.publish_advancement(
            edition_id, {"expected_fair_edition_version": version}, fd_headers()
        )
        validate_error(resp, ApiErrorId.ERR_UNJUDGED_PROJECTS, 409)
        assert get_edition(edition_id)["status"] == "JUDGING", (
            "a rejected publish must leave the edition in JUDGING"
        )

    def test_stale_edition_version_blocks_publish(self, api):
        """PRD §2.7: "Publishing advancement requires
        `expected_fair_edition_version` to match the fair edition's current
        `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.1: "Every category update must carry
        `expected_fair_edition_version` per §2.7, and a successful update
        increments both the category's `version` and the parent edition's
        `version`".

        Design: Corner/cross_cutting_layers/occ_publish_advancement_stale_version
        """
        ctx = setup_publishable(name="OCC Edition")
        edition_id = ctx["edition"]["id"]
        category_id = ctx["category"]["id"]

        observed = current_edition_version(edition_id)
        # A quota edit bumps the parent edition's version.
        validate_success(
            api_client.update_category(
                category_id,
                {"advancement_slots": 2, "expected_fair_edition_version": observed},
                fd_headers(),
            )
        )

        resp = api_client.publish_advancement(
            edition_id, {"expected_fair_edition_version": observed}, fd_headers()
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        fresh = current_edition_version(edition_id)
        published = validate_success(
            api_client.publish_advancement(
                edition_id, {"expected_fair_edition_version": fresh}, fd_headers()
            )
        )
        assert published["status"] == "ADVANCEMENT_PUBLISHED"
        assert get_category(category_id)["advancement_slots"] == 2, (
            "the quota edit's effect persists across the retried publish"
        )

    def test_quota_edit_blocked_once_advancement_frozen(self, api):
        """PRD §3.1: "Once advancement has been published and
        `advancement_freeze` is true, the same edit is rejected with
        `ERR_ADVANCEMENT_FROZEN` (409) rather than the generic state error,
        because freezing exists precisely to pin the quota base the waterfall
        already consumed."

        Design: Corner/endpoints/quota_edit_blocked_when_advancement_frozen
        """
        ctx = setup_publishable(name="Freeze Edition")
        edition_id = ctx["edition"]["id"]
        category_id = ctx["category"]["id"]
        publish_advancement(edition_id)

        edition = get_edition(edition_id)
        assert edition["advancement_freeze"] is True

        resp = api_client.update_category(
            category_id,
            {"advancement_slots": 3, "expected_fair_edition_version": edition["version"]},
            fd_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_ADVANCEMENT_FROZEN, 409)
        assert get_category(category_id)["advancement_slots"] == 1, (
            "the freeze gate, not OCC, blocks the write — the quota must stay unchanged"
        )


class TestFinalizeAwardsGate:
    def test_finalize_requires_scholarship_pool(self, api):
        """PRD §3.8: "Finalizing awards moves the edition
        `ADVANCEMENT_PUBLISHED` → `AWARDS_FINALIZED` and is refused outright
        when the edition has no scholarship pool —
        `ERR_SCHOLARSHIP_POOL_MISSING`."

        Design: Corner/endpoints/finalize_awards_requires_scholarship_pool
        """
        ctx = setup_publishable(name="Pool Edition")
        edition_id = ctx["edition"]["id"]
        publish_advancement(edition_id)

        resp = api_client.finalize_awards(edition_id, fd_headers())
        validate_error(resp, ApiErrorId.ERR_SCHOLARSHIP_POOL_MISSING, 422)

        create_pool(edition_id, 100000)
        finalized = validate_success(api_client.finalize_awards(edition_id, fd_headers()))
        assert finalized["status"] == "AWARDS_FINALIZED"


class TestMentorRecognition:
    def test_strict_points_exclude_waitlisted(self, api):
        """PRD §3.8: "The strict variant, `recognition_points`, drives official
        tier decisions: 5 points per project whose `advancement_result` is
        `ADVANCED`, nothing for a `WAITLISTED` project, plus 8 points for a
        conferred `GRAND_PRIZE`, 4 for a `CATEGORY_FIRST`, 2 for a
        `CATEGORY_SECOND`, and 1 for a `SPECIAL_TOPIC`."

        Design: Difficulty/dual_variant_calc/mentor_recognition_strict_vs_inclusive
        """
        mentor_id, p1, p2 = _mentor_variant_scenario()
        assert get_project(p1)["advancement_result"] == "ADVANCED"
        assert get_project(p2)["advancement_result"] == "WAITLISTED"

        mentor = get_mentor(mentor_id)
        assert_mentor(mentor)
        # STRICT: 5 (ADVANCED) + 4 (CATEGORY_FIRST) + 0 (WAITLISTED) = 9.
        assert mentor["recognition_points"] == 9, (
            f"strict points must be 9, got {mentor['recognition_points']}"
        )
        assert mentor["recognition_tier"] == "NONE", (
            "the tier derives from the strict total alone: 9 is below the BRONZE floor of 10"
        )

    def test_inclusive_leaderboard_counts_waitlisted_double(self, api):
        """PRD §3.8: "The inclusive variant, `leaderboard_points`, powers the
        public leaderboard readout: everything in the strict variant, plus 4
        points per waitlisted project — the waitlist's 2-point base counted at
        double weight."

        Design: Difficulty/dual_variant_calc/mentor_recognition_strict_vs_inclusive
        """
        mentor_id, _p1, _p2 = _mentor_variant_scenario()
        mentor = get_mentor(mentor_id)
        assert mentor["leaderboard_points"] == 13, (
            f"inclusive points must be 9 + 4 for the waitlisted project, got {mentor['leaderboard_points']}"
        )
        assert mentor["leaderboard_points"] > mentor["recognition_points"]

    def test_tier_bronze_at_fourteen_points(self, api):
        """PRD §3.8: "The `recognition_tier` derives from the strict total
        alone: below 10 points `NONE`, at least 10 `BRONZE`, at least 25
        `SILVER`, and at least 50 `GOLD`."

        Design: Corner/calculations/mentor_recognition_tier_boundary
        """
        mentor_id, p1, p2 = _tier_bronze_scenario()
        assert get_project(p1)["advancement_result"] == "ADVANCED"
        assert get_project(p2)["advancement_result"] == "ADVANCED"

        mentor = get_mentor(mentor_id)
        # 5 (ADVANCED) + 4 (CATEGORY_FIRST) + 5 (second ADVANCED) = 14.
        assert mentor["recognition_points"] == 14
        assert mentor["recognition_tier"] == "BRONZE", "14 points is at least 10 but below 25"

    def test_cumulative_points_cross_two_bands_in_one_finalize(self, api):
        """PRD §3.8: "The `recognition_tier` derives from the strict total
        alone: below 10 points `NONE`, at least 10 `BRONZE`, at least 25
        `SILVER`, and at least 50 `GOLD`."
        PRD §3.8: "Both variants start at 0 and are computed at the same
        trigger, so identical outcomes yield a leaderboard total strictly
        greater than the recognition total whenever the mentor has at least one
        `WAITLISTED` project."

        Design: Corner/cross_cutting_layers/rate_threshold_tier_crossing_silver
        """
        mentor_id, pool_id = _silver_scenario()
        mentor = get_mentor(mentor_id)
        # 2 projects x (5 ADVANCED + 8 GRAND_PRIZE + 4 CATEGORY_FIRST) = 34.
        assert mentor["recognition_points"] == 34
        assert mentor["recognition_tier"] == "SILVER", (
            "the tier evaluates the cumulative total: 34 crosses NONE and BRONZE in one finalize"
        )
        assert mentor["leaderboard_points"] == 34, (
            "with no WAITLISTED projects the two variants coincide"
        )
        pool = get_pool(pool_id)
        assert pool["remaining_cents"] == 600000, (
            "2000000 - 2x400000 GRAND_PRIZE - 2x300000 CATEGORY_FIRST = 600000"
        )

    def test_fresh_mentor_starts_at_zero_none(self, api):
        """PRD §3.8: "Both variants start at 0 and are computed at the same
        trigger, so identical outcomes yield a leaderboard total strictly
        greater than the recognition total whenever the mentor has at least one
        `WAITLISTED` project."
        PRD §3.8: "The `recognition_tier` derives from the strict total alone:
        below 10 points `NONE`, at least 10 `BRONZE`, at least 25 `SILVER`,
        and at least 50 `GOLD`."

        Design: Corner/entities/mentor_recognition_tier_computed_default_none
        """
        mentor = add_mentor(full_name="New Mentor")
        assert_mentor(mentor)
        assert mentor["recognition_points"] == 0
        assert mentor["leaderboard_points"] == 0
        assert mentor["recognition_tier"] == "NONE"

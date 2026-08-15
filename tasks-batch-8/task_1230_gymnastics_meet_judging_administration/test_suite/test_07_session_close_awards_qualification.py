"""Session close consequences: award ordering under tie-break policy,
all-around totals, qualification thresholds and rule variants, and the
score-sum invariant across scratches."""
from datetime import timedelta

import pytest

from test_helpers import (
    add_published_score,
    close_rotation,
    create_score_payload,
    fmt_ts,
    get_success_data,
    make_judge_panel_chief_headers,
    open_rotation,
    set_clock,
    setup_closed_session,
    setup_competition_ready,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["meet_director_headers"]


def _vault_awards(api, session_id):
    awards = get_success_data(api.list_session_awards(
        session_id, DIRECTOR, params={"category": "VAULT"}))
    return awards


class TestAwardTiebreak:
    def test_usag_classic_breaks_tie_on_execution_score(self, api):
        """PRD §3.7: "Under `USAG_CLASSIC`, tied totals are broken by the higher
        `execution_score`, then by the higher `difficulty_score`, then by the lower
        `neutral_deduction`; scores still tied after the full chain share a rank, and the
        next rank is skipped — two routines tied for second both receive place 2, and the
        next award given is place 4."
        PRD §3.7: "An Award whose recipient was selected through the tie-break chain rather
        than by raw score ordering is marked `was_tiebroken`."

        Design: Difficulty/combinatorial_formula/award_tiebreak_usag_classic_multi_input_chain
        """
        # Both gymnasts total 13.850 on VAULT; entry 0 wins the chain on E.
        def scores_for(index, apparatus):
            if apparatus == "VAULT":
                return (5.0, 8.85, 0.0) if index == 0 else (5.2, 8.65, 0.0)
            return (5.0, 8.0 + 0.5 * index, 0.0)

        ctx = setup_closed_session(num_athletes=2, scores_for=scores_for)
        validate_success(api.generate_awards(
            ctx["session"]["id"], {"award_depth_per_category": 2}, DIRECTOR), 201)
        awards = _vault_awards(api, ctx["session"]["id"])
        by_entry = {a["athlete_entry_id"]: a for a in awards}
        first = by_entry[ctx["entries"][0]["id"]]
        second = by_entry[ctx["entries"][1]["id"]]
        assert first["place"] == 1, (
            f"higher execution_score (8.85 vs 8.65) at equal 13.850 must win, got places "
            f"{first['place']} / {second['place']}")
        assert second["place"] == 2
        assert first["was_tiebroken"] is True
        assert second["was_tiebroken"] is True

    def test_fully_tied_scores_share_rank_and_skip_next_place(self, api):
        """PRD §3.7: "Under `USAG_CLASSIC`, tied totals are broken by the higher
        `execution_score`, then by the higher `difficulty_score`, then by the lower
        `neutral_deduction`; scores still tied after the full chain share a rank, and the
        next rank is skipped — two routines tied for second both receive place 2, and the
        next award given is place 4."

        Design: Difficulty/combinatorial_formula/award_tiebreak_usag_classic_multi_input_chain
        """
        # VAULT: 14.000 clear first; two routines identical at 13.850; one at 13.000.
        def scores_for(index, apparatus):
            if apparatus == "VAULT":
                return {0: (5.0, 9.0, 0.0), 1: (5.0, 8.85, 0.0),
                        2: (5.0, 8.85, 0.0), 3: (5.0, 8.0, 0.0)}[index]
            return (4.0, 8.0 + 0.1 * index, 0.0)

        ctx = setup_closed_session(num_athletes=4, scores_for=scores_for)
        validate_success(api.generate_awards(
            ctx["session"]["id"], {"award_depth_per_category": 4}, DIRECTOR), 201)
        awards = _vault_awards(api, ctx["session"]["id"])
        by_entry = {a["athlete_entry_id"]: a for a in awards}
        places = {idx: by_entry[ctx["entries"][idx]["id"]]["place"] for idx in range(4)}
        assert places[0] == 1
        assert places[1] == 2 and places[2] == 2, (
            f"fully tied routines must share place 2, got {places}")
        assert places[3] == 4, (
            f"the place after a shared rank must be skipped (4, not 3), got {places[3]}")
        assert all(a["place"] != 3 for a in awards), "place 3 must not be awarded"


class TestQualificationBoundary:
    def test_all_around_exactly_32000_qualifies(self, api):
        """PRD §3.8: "A gymnast at `L4` or `L5` qualifies to a `STATE` meet with an
        all-around total of at least 32.000."
        PRD §3.8: "Independently of the all-around, a single-apparatus `final_total` of at
        least 9.000 qualifies the athlete to `STATE` on the strength of that event alone; a
        score of exactly 32.000 or exactly 9.000 qualifies, because every threshold
        comparison includes its boundary."
        PRD §3.8: "A qualifying entry gains a QualificationRecord in `PROVISIONAL` state,
        naming the `target_meet_level` it qualified for (`STATE`, `REGIONAL`, or `NATIONAL`)
        and pinning both the `qualifying_score_used` — the score value that met the
        threshold — and the `threshold_applied`, the threshold constant it was compared
        against, frozen at computation time for auditability."

        Design: Difficulty/boundary_precision_check/qualification_threshold_exactly_at_32000
        """
        # Four apparatus at exactly 8.000 each -> AA 32.000 (boundary, inclusive).
        ctx = setup_closed_session(
            num_athletes=1, level_band="L4", gymnast_level="L4",
            meet_overrides={"qualifying_score_rule": "ALL_AROUND_ONLY"},
            scores_for=lambda i, a: (3.0, 5.0, 0.0))
        entry = ctx["entries"][0]
        assert entry["all_around_total"] == pytest.approx(32.0, abs=0.001)
        assert entry["qualified_for_next_meet"] is True, (
            "an all-around of exactly 32.000 meets the L4 STATE threshold (inclusive)")
        records = get_success_data(
            api.list_entry_qualification_records(entry["id"], DIRECTOR))
        assert len(records) == 1
        record = records[0]
        assert record["qualification_state"] == "PROVISIONAL"
        assert record["target_meet_level"] == "STATE"
        assert record["threshold_applied"] == pytest.approx(32.0, abs=0.001)
        assert record["qualifying_score_used"] == pytest.approx(32.0, abs=0.001)

    def test_all_around_31999_does_not_qualify(self, api):
        """PRD §3.8: "A gymnast at `L4` or `L5` qualifies to a `STATE` meet with an
        all-around total of at least 32.000."
        PRD §3.8: "The entry's `qualified_for_next_meet` flag records the outcome — false
        until the session is `CLOSED` ..."

        Design: Difficulty/boundary_precision_check/qualification_threshold_exactly_at_32000
        """
        # 8.000 + 8.000 + 8.000 + 7.999 = 31.999 — one thousandth below the line.
        def scores_for(index, apparatus):
            if apparatus == "FLOOR_EXERCISE":
                return (3.0, 4.999, 0.0)
            return (3.0, 5.0, 0.0)

        ctx = setup_closed_session(
            num_athletes=1, level_band="L4", gymnast_level="L4",
            meet_overrides={"qualifying_score_rule": "ALL_AROUND_ONLY"},
            scores_for=scores_for)
        entry = ctx["entries"][0]
        assert entry["all_around_total"] == pytest.approx(31.999, abs=0.0005)
        assert entry["qualified_for_next_meet"] is False, (
            "an all-around of 31.999 is strictly below the L4 STATE threshold")
        records = get_success_data(
            api.list_entry_qualification_records(entry["id"], DIRECTOR))
        assert len(records) == 0, "a non-qualifying entry must not gain a record"


# Identical scoring data for the rule-variant pair: AA 31.000, best event 9.100.
_VARIANT_SPEC = {
    "VAULT": (3.0, 4.4, 0.0),
    "UNEVEN_BARS": (3.0, 4.0, 0.0),
    "BALANCE_BEAM": (3.0, 4.5, 0.0),
    "FLOOR_EXERCISE": (4.0, 5.1, 0.0),
}


class TestQualificationRuleVariants:
    def test_aa_only_vs_per_event_outcome_split(self, api):
        """PRD §3.8: "Under `ALL_AROUND_ONLY`, only the all-around thresholds count and the
        per-event rule is suppressed. Under `PER_EVENT`, only the single-apparatus rule
        applies and the all-around total is ignored. Under `BOTH`, either path qualifies."
        PRD §3.8: "The entry's `qualified_for_next_meet` flag records the outcome — false
        until the session is `CLOSED` — and its `qualification_mobility_score` pins the
        specific score that drove the decision: under `PER_EVENT` the athlete's best
        single-event total; under `ALL_AROUND_ONLY` the `all_around_total`; and under
        `BOTH`, the higher of the `all_around_total` and the best event total when the event
        path fired, otherwise the `all_around_total`."

        Design: Difficulty/dual_variant_calc/qualification_aa_only_vs_per_event_path
        """
        scores_for = lambda i, a: _VARIANT_SPEC[a]
        aa_ctx = setup_closed_session(
            num_athletes=1, level_band="L4", gymnast_level="L4",
            meet_overrides={"qualifying_score_rule": "ALL_AROUND_ONLY"},
            scores_for=scores_for)
        ev_ctx = setup_closed_session(
            num_athletes=1, level_band="L4", gymnast_level="L4",
            meet_overrides={"qualifying_score_rule": "PER_EVENT"},
            scores_for=scores_for)
        entry_aa = aa_ctx["entries"][0]
        entry_ev = ev_ctx["entries"][0]
        # Same scoring data: AA 31.000 (< 32.000), best event FX 9.100 (>= 9.000).
        assert entry_aa["all_around_total"] == pytest.approx(31.0, abs=0.001)
        assert entry_ev["all_around_total"] == pytest.approx(31.0, abs=0.001)
        assert entry_aa["qualified_for_next_meet"] is False, (
            "ALL_AROUND_ONLY suppresses the per-event path; 31.000 < 32.000 must not qualify")
        assert entry_ev["qualified_for_next_meet"] is True, (
            "PER_EVENT ignores the all-around; the 9.100 event total must qualify")
        assert entry_aa["qualification_mobility_score"] == pytest.approx(31.0, abs=0.001)
        assert entry_ev["qualification_mobility_score"] == pytest.approx(9.1, abs=0.001)

    def test_per_event_record_pins_event_score_and_threshold(self, api):
        """PRD §3.8: "A qualifying entry gains a QualificationRecord in `PROVISIONAL` state,
        naming the `target_meet_level` it qualified for (`STATE`, `REGIONAL`, or `NATIONAL`)
        and pinning both the `qualifying_score_used` — the score value that met the
        threshold — and the `threshold_applied`, the threshold constant it was compared
        against, frozen at computation time for auditability."
        PRD §3.8: "Independently of the all-around, a single-apparatus `final_total` of at
        least 9.000 qualifies the athlete to `STATE` on the strength of that event alone ..."

        Design: Difficulty/dual_variant_calc/qualification_aa_only_vs_per_event_path
        """
        ctx = setup_closed_session(
            num_athletes=1, level_band="L4", gymnast_level="L4",
            meet_overrides={"qualifying_score_rule": "PER_EVENT"},
            scores_for=lambda i, a: _VARIANT_SPEC[a])
        entry = ctx["entries"][0]
        records = get_success_data(
            api.list_entry_qualification_records(entry["id"], DIRECTOR))
        assert len(records) == 1
        record = records[0]
        assert record["qualification_state"] == "PROVISIONAL"
        assert record["target_meet_level"] == "STATE"
        assert record["qualifying_score_used"] == pytest.approx(9.1, abs=0.001)
        assert record["threshold_applied"] == pytest.approx(9.0, abs=0.001)


class TestScratchScoreSumInvariant:
    def _final_sum(self, api, entry_ids):
        total = 0.0
        states = {}
        for entry_id in entry_ids:
            for score in get_success_data(api.list_entry_scores(entry_id, DIRECTOR)):
                states.setdefault(score["id"], score["score_state"])
                if score["score_state"] == "FINAL":
                    total += score["final_total"]
        return total, states

    def test_scratch_after_final_conserves_final_score_sum(self, api):
        """PRD §3.2: "Scratching cascades: every score of the entry still in `DRAFT`
        transitions to `VOID`, and the parent squad's `athlete_count` is recomputed."
        PRD §3.2: "For an entry scratched from `COMPETING`, scores already past `DRAFT` are
        retained as historical record rather than voided."
        PRD §3.7: "An entry's `all_around_total` is the sum of the `final_total` of its four
        apparatus scores that reached `FINAL`; a `VOID` apparatus — one scratched out from
        under the athlete — contributes 0.000, so a partial all-around is still well
        defined."

        Design: Difficulty/compensating_invariant/scratch_conserves_final_score_sum_invariant
        """
        ctx = setup_competition_ready(num_athletes=2)
        rotation_one = ctx["rotations"][0]
        open_rotation(rotation_one["id"])
        published_one = add_published_score(ctx, ctx["entries"][0], rotation_one,
                                            5.5, 8.0, 0.0)   # 13.500
        published_two = add_published_score(ctx, ctx["entries"][1], rotation_one,
                                            5.0, 9.0, 0.0)   # 14.000
        close_rotation(rotation_one["id"])
        # Draft scores for entry 0 on the remaining apparatus rotations.
        drafts = []
        chief_headers = {app: make_judge_panel_chief_headers(ctx["chiefs"][app])
                         for app in ("UNEVEN_BARS", "BALANCE_BEAM", "FLOOR_EXERCISE")}
        for rotation in ctx["rotations"][1:]:
            drafts.append(get_success_data(api.create_score(
                ctx["entries"][0]["id"],
                create_score_payload(rotation["id"], rotation["apparatus"], 4.0, 7.0),
                chief_headers[rotation["apparatus"]])))
        # Let the inquiry window lapse so both published scores are FINAL.
        set_clock(fmt_ts(ctx["competition_clock"]
                         + timedelta(minutes=ctx["meet"]["inquiry_window_minutes"] + 1)))
        entry_ids = [e["id"] for e in ctx["entries"]]
        sum_before, _ = self._final_sum(api, entry_ids)
        assert sum_before == pytest.approx(27.5, abs=0.001)

        validate_success(api.scratch_entry(
            ctx["entries"][0]["id"], {"scratch_reason": "INJURY"}, DIRECTOR))

        sum_after, states_after = self._final_sum(api, entry_ids)
        assert sum_after == pytest.approx(sum_before, abs=0.0001), (
            f"scratching an entry whose open scores are all DRAFT must conserve the FINAL "
            f"score sum: {sum_before} -> {sum_after}")
        for draft in drafts:
            assert states_after[draft["id"]] == "VOID", (
                "the scratched entry's DRAFT scores must cascade to VOID")
        assert states_after[published_one["id"]] == "FINAL", (
            "the scratched entry's FINAL score must be retained")
        assert states_after[published_two["id"]] == "FINAL", (
            "the other entry's FINAL score must be untouched")

    def test_scratch_while_published_keeps_score_on_finalization_path(self, api):
        """PRD §3.2: "For an entry scratched from `COMPETING`, scores already past `DRAFT`
        are retained as historical record rather than voided."
        PRD §3.6: "The quiet path is expiry: when the logical clock passes `published_at`
        plus the meet's `inquiry_window_minutes` with no inquiry in `FILED` or
        `UNDER_REVIEW`, the score finalizes itself — `PUBLISHED` → `FINAL` — setting
        `final_total` equal to `provisional_total`, stamping `finalized_at`, and prompting
        the parent rotation to re-evaluate its own path from `SCORING_CLOSED` to
        `FINALIZED`."

        Design: Difficulty/compensating_invariant/scratch_conserves_final_score_sum_invariant
        """
        ctx = setup_competition_ready(num_athletes=1)
        rotation_one = ctx["rotations"][0]
        open_rotation(rotation_one["id"])
        published = add_published_score(ctx, ctx["entries"][0], rotation_one, 5.5, 8.0, 0.0)
        # DRAFT scores on the other rotations, scratched before the window lapses.
        draft_ids = []
        for rotation in ctx["rotations"][1:]:
            chief = make_judge_panel_chief_headers(ctx["chiefs"][rotation["apparatus"]])
            draft = get_success_data(api.create_score(
                ctx["entries"][0]["id"],
                create_score_payload(rotation["id"], rotation["apparatus"], 4.0, 7.0),
                chief))
            draft_ids.append(draft["id"])
        validate_success(api.scratch_entry(
            ctx["entries"][0]["id"], {"scratch_reason": "INJURY"}, DIRECTOR))
        for draft_id in draft_ids:
            assert get_success_data(api.get_score(draft_id, DIRECTOR))["score_state"] == "VOID"
        # The retained PUBLISHED score still finalizes itself when the window lapses.
        set_clock(fmt_ts(ctx["competition_clock"]
                         + timedelta(minutes=ctx["meet"]["inquiry_window_minutes"] + 1)))
        kept = get_success_data(api.get_score(published["id"], DIRECTOR))
        assert kept["score_state"] == "FINAL", (
            f"a score past DRAFT survives the scratch and finalizes on the quiet path, "
            f"got {kept['score_state']}")
        assert kept["final_total"] == pytest.approx(13.5, abs=0.001)

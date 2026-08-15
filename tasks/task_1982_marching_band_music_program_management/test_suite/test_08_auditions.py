"""Auditions: dual scoring variants, single-judge penalty, composite/rank
assignment, chair-capacity placement boundary, publish gating, and OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_audition,
    create_audition_entry,
    create_enrolled_student,
    create_open_program,
    finalize_scores,
    list_chair_placements,
    publish_placements,
    publish_placements_payload,
    setup_scored_audition,
    submit_score,
    validate_error,
    validate_success,
)


def _entries_by_id(entries):
    return {e["id"]: e for e in entries}


# --- Difficulty: audition_raw_vs_rank_normalized_divergence ----------------------

def _setup_dual_scoring_programs(api):
    """Identical two-judge inputs under RAW_WEIGHTED and RANK_NORMALIZED."""
    per_mode = {}
    for mode in ("RAW_WEIGHTED", "RANK_NORMALIZED"):
        program, audition, entries = setup_scored_audition(
            [[("J1", 100, 100, 100), ("J2", 60, 60, 60)],
             [("J1", 80, 80, 80), ("J2", 90, 90, 90)]],
            chair_capacity=1, section="BRASS", scoring_mode=mode)
        per_mode[mode] = (program, audition, entries)
    return per_mode["RAW_WEIGHTED"], per_mode["RANK_NORMALIZED"]


def test_raw_vs_rank_composites_and_ranks_diverge(api):
    """PRD §3.8: "The two variants share inputs but routinely disagree: with two judges, an entry whose weighted scores are 100 and 60 composites to 80.0 under the raw variant, while a rival at 80 and 90 composites to 85.0, yet under rank normalization the two entries tie at one Borda point apiece and the tie falls to creation time." PRD §3.8: "Either way, each entry's `composite_score` is recorded and ranks are assigned one-based by composite descending, ties broken by the entry's `created_at` ascending; finalization moves the audition to `SCORES_FINALIZED` and increments its `version`."

    Design: Difficulty/dual_variant_calc/audition_raw_vs_rank_normalized_divergence
    """
    (_prog_raw, _aud_raw, entries_raw), (_prog_rnk, _aud_rnk, entries_rnk) = (
        _setup_dual_scoring_programs(api))

    e1_raw, e2_raw = entries_raw  # creation order = created_at order
    assert e1_raw["composite_score"] == pytest.approx(80.0, abs=0.001)
    assert e1_raw["rank"] == 2
    assert e2_raw["composite_score"] == pytest.approx(85.0, abs=0.001)
    assert e2_raw["rank"] == 1

    e1_rnk, e2_rnk = entries_rnk
    assert e1_rnk["composite_score"] == 1, "Borda: 2 entries - rank 2 under J2"
    assert e2_rnk["composite_score"] == 1
    assert e1_rnk["rank"] == 1, "Borda tie falls to creation time"
    assert e2_rnk["rank"] == 2


def test_raw_vs_rank_place_different_performers_in_chair_one(api):
    """PRD §3.8: "Publishing walks the entries in rank order: any entry whose `rank` is at most `chair_capacity` receives a `ChairPlacement` with `chair_number` equal to its rank and `is_alternate` false; any entry beyond capacity receives a placement with `is_alternate` true and `chair_number` null." PRD §3.8: "The two variants share inputs but routinely disagree: with two judges, an entry whose weighted scores are 100 and 60 composites to 80.0 under the raw variant, while a rival at 80 and 90 composites to 85.0, yet under rank normalization the two entries tie at one Borda point apiece and the tie falls to creation time."

    Design: Difficulty/dual_variant_calc/audition_raw_vs_rank_normalized_divergence
    """
    (_prog_raw, aud_raw, entries_raw), (_prog_rnk, aud_rnk, entries_rnk) = (
        _setup_dual_scoring_programs(api))
    publish_placements(aud_raw["id"], aud_raw["version"])
    publish_placements(aud_rnk["id"], aud_rnk["version"])

    placements_raw = list_chair_placements(audition_id=aud_raw["id"])
    placements_rnk = list_chair_placements(audition_id=aud_rnk["id"])
    chair1_raw = [p for p in placements_raw if p["chair_number"] == 1]
    chair1_rnk = [p for p in placements_rnk if p["chair_number"] == 1]
    assert len(chair1_raw) == 1 and len(chair1_rnk) == 1
    assert chair1_raw[0]["entry_id"] == entries_raw[1]["id"], (
        "raw variant seats the 85.0 performer")
    assert chair1_rnk[0]["entry_id"] == entries_rnk[0]["id"], (
        "rank variant seats the earlier-created Borda co-leader")
    # Identical inputs seat different rank-1 entries across the two variants:
    # the raw winner is the second-created entry, the rank winner the first.
    assert entries_raw[1]["composite_score"] == pytest.approx(85.0, abs=0.001)
    assert entries_rnk[0]["composite_score"] == 1


# --- Difficulty: audition_single_judge_penalty_branch ----------------------------

def test_single_judge_composite_takes_penalty(api):
    """PRD §3.8: "Under `RAW_WEIGHTED`: with exactly one judge, the composite is that judge's weighted score multiplied by 0.95, rounded half up to two decimals; with exactly two judges, the composite is the mean of the two weighted scores, rounded half up to two decimals; with three or more judges, the single lowest weighted score is dropped and the composite is the mean of the remainder, rounded half up to two decimals." PRD §3.8: "Each judge's weighted score for an entry is half the `musicianship` score plus three-tenths of the `marching` score plus one-fifth of the `leadership` score."

    Design: Difficulty/combinatorial_formula/audition_single_judge_penalty_branch
    """
    _program, audition, entries = setup_scored_audition(
        [[("J1", 80, 90, 70)]], chair_capacity=2, section="BRASS",
        scoring_mode="RAW_WEIGHTED")
    entry = entries[0]
    # weighted = 0.5*80 + 0.3*90 + 0.2*70 = 81; 81 * 0.95 = 76.95
    assert entry["composite_score"] == pytest.approx(76.95, abs=0.001)
    assert entry["rank"] == 1
    assert audition["status"] == "SCORES_FINALIZED"


def test_single_judge_penalty_applies_to_perfect_score(api):
    """PRD §3.8: "Under `RAW_WEIGHTED`: with exactly one judge, the composite is that judge's weighted score multiplied by 0.95, rounded half up to two decimals; with exactly two judges, the composite is the mean of the two weighted scores, rounded half up to two decimals; with three or more judges, the single lowest weighted score is dropped and the composite is the mean of the remainder, rounded half up to two decimals." PRD §3.8: "Each judge's weighted score for an entry is half the `musicianship` score plus three-tenths of the `marching` score plus one-fifth of the `leadership` score."

    Design: Difficulty/combinatorial_formula/audition_single_judge_penalty_branch
    """
    _program, _audition, entries = setup_scored_audition(
        [[("J1", 100, 100, 100)]], chair_capacity=1, section="BRASS",
        scoring_mode="RAW_WEIGHTED")
    # weighted = 100; penalized composite = 95.0 — the penalty always applies
    assert entries[0]["composite_score"] == pytest.approx(95.0, abs=0.001)
    assert entries[0]["rank"] == 1


# --- Difficulty: chair_capacity_exact_fit_then_alternate --------------------------

def _three_entry_audition(api, chair_capacity=2):
    return setup_scored_audition(
        [[("J1", 90, 90, 90)], [("J1", 80, 80, 80)], [("J1", 70, 70, 70)]],
        chair_capacity=chair_capacity, section="BRASS", scoring_mode="RAW_WEIGHTED")


def test_exact_fit_then_alternate_at_capacity(api):
    """PRD §3.8: "Publishing walks the entries in rank order: any entry whose `rank` is at most `chair_capacity` receives a `ChairPlacement` with `chair_number` equal to its rank and `is_alternate` false; any entry beyond capacity receives a placement with `is_alternate` true and `chair_number` null."

    Design: Difficulty/boundary_precision_check/chair_capacity_exact_fit_then_alternate
    """
    _program, audition, entries = _three_entry_audition(api, chair_capacity=2)
    published = publish_placements(audition["id"], audition["version"])
    assert published["status"] == "PLACEMENTS_PUBLISHED"

    placements = list_chair_placements(audition_id=audition["id"])
    assert len(placements) == 3
    by_entry = {p["entry_id"]: p for p in placements}

    first = by_entry[entries[0]["id"]]   # composite 85.5 -> rank 1
    assert first["chair_number"] == 1 and first["is_alternate"] is False
    second = by_entry[entries[1]["id"]]  # 76.0 -> rank 2 == capacity: seated
    assert second["chair_number"] == 2 and second["is_alternate"] is False
    third = by_entry[entries[2]["id"]]   # 66.5 -> rank 3 > capacity: alternate
    assert third["chair_number"] is None and third["is_alternate"] is True


def test_single_judge_penalty_scores_set_the_ranks(api):
    """PRD §3.8: "Either way, each entry's `composite_score` is recorded and ranks are assigned one-based by composite descending, ties broken by the entry's `created_at` ascending; finalization moves the audition to `SCORES_FINALIZED` and increments its `version`." PRD §3.8: "Under `RAW_WEIGHTED`: with exactly one judge, the composite is that judge's weighted score multiplied by 0.95, rounded half up to two decimals; with exactly two judges, the composite is the mean of the two weighted scores, rounded half up to two decimals; with three or more judges, the single lowest weighted score is dropped and the composite is the mean of the remainder, rounded half up to two decimals."

    Design: Difficulty/boundary_precision_check/chair_capacity_exact_fit_then_alternate
    """
    _program, audition, entries = _three_entry_audition(api, chair_capacity=2)
    by_id = _entries_by_id(entries)
    assert by_id[entries[0]["id"]]["composite_score"] == pytest.approx(85.5)
    assert by_id[entries[0]["id"]]["rank"] == 1
    assert by_id[entries[1]["id"]]["composite_score"] == pytest.approx(76.0)
    assert by_id[entries[1]["id"]]["rank"] == 2
    assert by_id[entries[2]["id"]]["composite_score"] == pytest.approx(66.5)
    assert by_id[entries[2]["id"]]["rank"] == 3
    assert audition["status"] == "SCORES_FINALIZED"


# --- Difficulty: placements_publish_requires_finalized_scores ---------------------

def test_publish_while_scoring_open_rejected(api, director_headers,
                                             reader_headers):
    """PRD §3.8: "A `BandDirector` publishes an audition in `SCORES_FINALIZED` (else `ERR_AUDITION_SCORES_NOT_FINAL`) with `expected_audition_version` matching the audition's current `version`, else `ERR_STALE_VERSION`."

    Design: Difficulty/cross_entity_state_dependency/placements_publish_requires_finalized_scores
    """
    program = create_open_program(season_name="XA")
    student = create_enrolled_student(program["id"], full_name="AP")
    audition = create_audition(program["id"], section="BRASS", chair_capacity=1)
    create_audition_entry(audition["id"], student["id"])

    # Publish against the audition's current version while still SCORING_OPEN,
    # so the state gate — not the OCC gate — is what fires.
    current = validate_success(api.get_audition(audition["id"], reader_headers))
    assert current["status"] == "SCORING_OPEN"
    resp = api.publish_audition_placements(
        audition["id"], publish_placements_payload(current["version"]),
        director_headers)
    validate_error(resp, ApiErrorId.ERR_AUDITION_SCORES_NOT_FINAL)

    audition = validate_success(api.get_audition(audition["id"], reader_headers))
    assert audition["status"] == "SCORING_OPEN"
    assert list_chair_placements(audition_id=audition["id"]) == []


def test_publish_after_finalize_creates_placements(api, reader_headers):
    """PRD §3.8: "Publishing walks the entries in rank order: any entry whose `rank` is at most `chair_capacity` receives a `ChairPlacement` with `chair_number` equal to its rank and `is_alternate` false; any entry beyond capacity receives a placement with `is_alternate` true and `chair_number` null. Any previously published placements for the same audition move from `PUBLISHED` to `SUPERSEDED`, so a re-publish after a challenge cleanly replaces the old set. Publishing stamps `published_at` from the logical clock and increments the audition's `version` as it moves to `PLACEMENTS_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/placements_publish_requires_finalized_scores
    """
    _program, audition, entries = setup_scored_audition(
        [[("J1", 80, 80, 80)]], chair_capacity=1, section="BRASS",
        scoring_mode="RAW_WEIGHTED")
    published = publish_placements(audition["id"], audition["version"])
    assert published["status"] == "PLACEMENTS_PUBLISHED"

    placements = list_chair_placements(audition_id=audition["id"])
    assert len(placements) == 1
    assert placements[0]["entry_id"] == entries[0]["id"]
    assert placements[0]["chair_number"] == 1
    assert placements[0]["is_alternate"] is False
    assert placements[0]["status"] == "PUBLISHED"
    _ = reader_headers


# --- Corner: score validation and publish OCC -------------------------------------

def test_duplicate_judge_score_rejected(api, director_headers, reader_headers):
    """PRD §3.8: "each of the three rubric fields must lie between 0 and 100 inclusive, else `ERR_SCORE_OUT_OF_RANGE` (HTTP 422), and one judge may score an entry only once — a repeat `judge_id` on the same entry is rejected with `ERR_DUPLICATE_SCORE`. Each score row is appended to the entry's `judge_scores` list."

    Design: Corner/validations/duplicate_judge_score_rejected
    """
    program = create_open_program(season_name="DS")
    student = create_enrolled_student(program["id"], full_name="DS")
    audition = create_audition(program["id"], section="BRASS", chair_capacity=1)
    entry = create_audition_entry(audition["id"], student["id"])
    submit_score(entry["id"], "J1", 80, 80, 80)

    dup = api.submit_judge_scores(
        entry["id"], {"judge_id": "J1", "musicianship": 90, "marching": 90,
                      "leadership": 90}, director_headers)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_SCORE)

    submit_score(entry["id"], "J2", 90, 90, 90)
    entry = validate_success(api.get_audition_entry(entry["id"], reader_headers))
    assert len(entry["judge_scores"]) == 2
    assert {row["judge_id"] for row in entry["judge_scores"]} == {"J1", "J2"}


def test_score_above_range_rejected(api, director_headers, reader_headers):
    """PRD §3.8: "each of the three rubric fields must lie between 0 and 100 inclusive, else `ERR_SCORE_OUT_OF_RANGE` (HTTP 422), and one judge may score an entry only once — a repeat `judge_id` on the same entry is rejected with `ERR_DUPLICATE_SCORE`."

    Design: Corner/validations/score_out_of_range_rejected
    """
    program = create_open_program(season_name="SR")
    student = create_enrolled_student(program["id"], full_name="SR")
    audition = create_audition(program["id"], section="BRASS", chair_capacity=1)
    entry = create_audition_entry(audition["id"], student["id"])

    resp = api.submit_judge_scores(
        entry["id"], {"judge_id": "J1", "musicianship": 101, "marching": 50,
                      "leadership": 50}, director_headers)
    validate_error(resp, ApiErrorId.ERR_SCORE_OUT_OF_RANGE)

    entry = validate_success(api.get_audition_entry(entry["id"], reader_headers))
    assert entry["judge_scores"] == [], "a rejected submission appends nothing"


def test_publish_with_stale_audition_version_rejected(api, director_headers):
    """PRD §2.10: "Publishing chair placements for an audition requires the request to carry `expected_audition_version` holding the `version` of the `Audition` the client last observed. Because a publish legitimately supersedes the audition's prior published placement set, a stale writer is refused: a mismatch with the audition's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/placements_publish_occ_stale_audition_version
    """
    program = create_open_program(season_name="OC3")
    student = create_enrolled_student(program["id"], full_name="OC3")
    audition = create_audition(program["id"], section="BRASS", chair_capacity=1)
    stale_version = audition["version"]
    entry = create_audition_entry(audition["id"], student["id"])
    submit_score(entry["id"], "J1", 80, 80, 80)
    finalized = finalize_scores(audition["id"])
    assert finalized["version"] > stale_version, (
        "finalization increments the audition's version")

    stale = api.publish_audition_placements(
        audition["id"], publish_placements_payload(stale_version),
        director_headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    published = publish_placements(audition["id"], finalized["version"])
    assert published["status"] == "PLACEMENTS_PUBLISHED"

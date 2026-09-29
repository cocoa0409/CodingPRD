"""Composite scores, the non-expert cap, and the two divergent round means."""

import pytest

from test_helpers import fixtures

PAINTING_ONLY = ["PAINTING"]
SCULPTURE_ONLY = ["SCULPTURE"]

WORK_RIDGE_LINE = {
    "title": "Ridge Line", "medium_category": "PAINTING",
    "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
}
WORK_SECOND_RIDGE = {
    "title": "Second Ridge", "medium_category": "PAINTING",
    "width_cm": 80.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 5.0,
}
WORK_THIRD_RIDGE = {
    "title": "Third Ridge", "medium_category": "PAINTING",
    "width_cm": 70.0, "height_cm": 50.0, "depth_cm": 4.0, "weight_kg": 4.0,
}


def _open_round_with_jurors(works, quorum, juror_expertise_lists,
                            exhibition_overrides=None):
    """Carry a call to an `OPEN` round with one booked session per juror.

    Returns the exhibition, the entry, the works, the jurors and the round.
    """
    overrides = {"jury_quorum": quorum}
    overrides.update(exhibition_overrides or {})
    exhibition = fixtures.open_call(**overrides)
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_submitted_entry(
        exhibition["id"], artist, works
    )
    fixtures.enter_jurying(exhibition["id"])

    jurors = [
        fixtures.invite_and_confirm_juror(
            display_name=name, expertise_categories=list(expertise),
            honorarium_cents=50000,
        )
        for name, expertise in juror_expertise_lists
    ]
    jury_round = fixtures.create_jury_round(
        exhibition["id"], quorum_required=quorum
    )
    for juror in jurors:
        fixtures.book_session(jury_round["id"], juror)
    jury_round = fixtures.set_round_status(jury_round["id"], "OPEN")
    fixtures.set_clock(fixtures.CLOCK_SCORING)
    return exhibition, entry, artworks, jurors, jury_round


# ─── Provisional versus certified round means ─────────

FOUR_CARDS = [(8, 7, 6), (7, 7, 7), (6, 6, 6), (10, 10, 10)]


def _four_juror_single_work_round():
    exhibition, entry, artworks, jurors, jury_round = _open_round_with_jurors(
        [WORK_RIDGE_LINE],
        quorum=3,
        juror_expertise_lists=[
            ("Iris Vega", ["PAINTING", "PHOTOGRAPHY"]),
            ("Omar Diaz", ["PAINTING", "PHOTOGRAPHY"]),
            ("Lena Park", ["PAINTING", "PHOTOGRAPHY"]),
            ("Tomas Reyes", ["PAINTING", "PHOTOGRAPHY"]),
        ],
    )
    artwork = artworks[0]
    for juror, card in zip(jurors, FOUR_CARDS):
        fixtures.submit_score(jury_round["id"], juror, artwork["id"], *card)
    return exhibition, entry, artwork, jury_round


def test_provisional_mean_averages_every_valid_score_in_the_round(api):
    """PRD §3.5: "The **provisional** figure, `provisional_mean_score`, is the
    arithmetic mean of `composite_score` over *every* score in that ordering,
    rounded half up to two decimal places, and it is refreshed on every
    submission while the round is `OPEN`; it is the live figure a chair watches,
    and a late high score raises it."

    Design: Difficulty/dual_variant_calc/artwork_round_mean_provisional_versus_quorum_certified
    """
    _, _, artwork, _ = _four_juror_single_work_round()

    live = fixtures.read_artwork(artwork["id"])
    assert live["valid_score_count"] == 4
    assert live["provisional_mean_score"] == pytest.approx(7.54, abs=0.01)
    assert live["certified_mean_score"] is None, (
        "the certified figure is written once, at the moment the round completes"
    )
    assert live["status"] == "SUBMITTED"


def test_certified_mean_averages_only_the_first_quorum_required_scores(api):
    """PRD §3.5: "The divergence is real and intended: four valid scores of 7.15,
    7.00, 6.00 and 10.00 in that order give a provisional mean of 7.54, while a
    `quorum_required` of 3 gives a certified mean of 6.72, which falls below a
    `advance_score_threshold` of 7.00 and declines the work."

    Design: Difficulty/dual_variant_calc/artwork_round_mean_provisional_versus_quorum_certified
    """
    exhibition, _, artwork, jury_round = _four_juror_single_work_round()

    fixtures.set_round_status(jury_round["id"], "SCORING_COMPLETE")

    certified = fixtures.read_artwork(artwork["id"])
    assert certified["certified_mean_score"] == pytest.approx(6.72, abs=0.01)
    assert certified["provisional_mean_score"] == pytest.approx(7.54, abs=0.01)
    assert certified["certified_mean_score"] != certified["provisional_mean_score"]
    assert certified["status"] == "DECLINED"
    assert certified["valid_score_count"] == 4


def test_only_the_certified_figure_decides_the_shortlist(api):
    """PRD §3.5: "Only the certified figure decides anything."

    Design: Difficulty/dual_variant_calc/artwork_round_mean_provisional_versus_quorum_certified
    """
    exhibition, entry, artwork, jury_round = _four_juror_single_work_round()

    fixtures.set_round_status(jury_round["id"], "SCORING_COMPLETE")

    after = fixtures.read_exhibition(exhibition["id"])
    assert after["shortlisted_count"] == 0, (
        "a provisional mean of 7.54 clears the 7.00 bar but does not decide "
        "the fork"
    )
    assert fixtures.read_entry(entry["id"])["shortlisted_count"] == 0


# ─── The non-expert cap, applied before rounding ──────

def _expert_and_outsider_round():
    return _open_round_with_jurors(
        [WORK_RIDGE_LINE, WORK_SECOND_RIDGE],
        quorum=2,
        juror_expertise_lists=[
            ("Iris Vega", PAINTING_ONLY),
            ("Nils Berg", SCULPTURE_ONLY),
        ],
    )


def test_composite_score_kept_in_full_when_expertise_matches(api):
    """PRD §3.5: "When `expertise_match` is true the raw value is kept in full,
    so a perfect card of ten, ten and ten yields a `composite_score` of 10.00."

    Design: Difficulty/combinatorial_formula/composite_score_non_expert_cap_before_rounding
    """
    _, _, artworks, jurors, jury_round = _expert_and_outsider_round()
    expert = jurors[0]

    score = fixtures.submit_score(
        jury_round["id"], expert, artworks[0]["id"], 10, 10, 10
    )

    assert score["expertise_match"] is True
    assert score["composite_score"] == pytest.approx(10.00, abs=0.01)


def test_composite_score_capped_at_eight_when_expertise_does_not_match(api):
    """PRD §3.5: "When `expertise_match` is false the value is capped: the lesser
    of the raw value and 8.00 is taken, so the same perfect card from a juror
    outside their credentialled medium yields 8.00. Either way, exactly one
    rounding is applied — half up to two decimal places, after the cap, never
    before it."

    Design: Difficulty/combinatorial_formula/composite_score_non_expert_cap_before_rounding
    """
    _, _, artworks, jurors, jury_round = _expert_and_outsider_round()
    expert, outsider = jurors

    fixtures.submit_score(jury_round["id"], expert, artworks[0]["id"], 10, 10, 10)
    capped = fixtures.submit_score(
        jury_round["id"], outsider, artworks[0]["id"], 10, 10, 10
    )

    assert capped["expertise_match"] is False
    assert capped["composite_score"] == pytest.approx(8.00, abs=0.01)

    live = fixtures.read_artwork(artworks[0]["id"])
    assert live["provisional_mean_score"] == pytest.approx(9.00, abs=0.01)


def test_composite_score_below_the_cap_is_left_alone_by_it(api):
    """PRD §3.5: "The raw value is `technique` multiplied by the exhibition's
    `score_weight_technique`, plus `originality` multiplied by
    `score_weight_originality`, plus `relevance` multiplied by
    `score_weight_relevance`."

    Design: Difficulty/combinatorial_formula/composite_score_non_expert_cap_before_rounding
    """
    _, _, artworks, jurors, jury_round = _expert_and_outsider_round()
    outsider = jurors[1]

    score = fixtures.submit_score(
        jury_round["id"], outsider, artworks[1]["id"], 6, 7, 7
    )

    assert score["expertise_match"] is False
    assert score["composite_score"] == pytest.approx(6.60, abs=0.01)


# ─── The inclusive advance threshold ──────────────────

def _three_work_two_juror_completed_round():
    exhibition, entry, artworks, jurors, jury_round = _open_round_with_jurors(
        [WORK_RIDGE_LINE, WORK_SECOND_RIDGE, WORK_THIRD_RIDGE],
        quorum=2,
        juror_expertise_lists=[
            ("Iris Vega", PAINTING_ONLY),
            ("Omar Diaz", PAINTING_ONLY),
        ],
        exhibition_overrides={"advance_score_threshold": 7.0},
    )
    first, second = jurors
    for artwork in artworks:
        fixtures.submit_score(jury_round["id"], first, artwork["id"], 8, 8, 8)
    for artwork, card in zip(artworks, [(6, 6, 6), (6, 6, 5), (5, 7, 6)]):
        fixtures.submit_score(jury_round["id"], second, artwork["id"], *card)
    fixtures.set_round_status(jury_round["id"], "SCORING_COMPLETE")
    return exhibition, entry, artworks, jury_round


def test_certified_mean_exactly_at_the_threshold_shortlists_the_work(api):
    """PRD §3.5: "As the round moves `OPEN → SCORING_COMPLETE`, every work of that
    exhibition whose `status` is `SUBMITTED` has its `certified_mean_score`
    written by the certified variant above, and then forks on the inclusive
    threshold: a work whose `valid_score_count` has reached the round's
    `quorum_required` and whose `certified_mean_score` is greater than or equal
    to the exhibition's `advance_score_threshold` advances `SUBMITTED →
    SHORTLISTED`, while one whose certified mean falls strictly below the
    threshold moves `SUBMITTED → DECLINED`."

    Design: Difficulty/boundary_precision_check/certified_mean_exactly_at_advance_threshold_shortlists
    """
    exhibition, entry, artworks, _ = _three_work_two_juror_completed_round()

    at_the_bar = fixtures.read_artwork(artworks[0]["id"])
    assert at_the_bar["certified_mean_score"] == pytest.approx(7.00, abs=0.01)
    assert at_the_bar["status"] == "SHORTLISTED"
    assert at_the_bar["valid_score_count"] == 2

    assert fixtures.read_exhibition(exhibition["id"])["shortlisted_count"] == 1
    assert fixtures.read_entry(entry["id"])["shortlisted_count"] == 1


def test_certified_mean_a_hundredth_below_the_threshold_declines_the_work(api):
    """PRD §3.1: "`advance_score_threshold` is the inclusive bar a work's
    certified mean must reach to be shortlisted."

    Design: Difficulty/boundary_precision_check/certified_mean_exactly_at_advance_threshold_shortlists
    """
    _, _, artworks, jury_round = _three_work_two_juror_completed_round()

    just_under = fixtures.read_artwork(artworks[1]["id"])
    assert just_under["certified_mean_score"] == pytest.approx(6.88, abs=0.01)
    assert just_under["status"] == "DECLINED"

    also_under = fixtures.read_artwork(artworks[2]["id"])
    assert also_under["certified_mean_score"] == pytest.approx(6.98, abs=0.01)
    assert also_under["status"] == "DECLINED"

    completed = fixtures.read_jury_round(jury_round["id"])
    assert completed["status"] == "SCORING_COMPLETE"
    assert completed["quorum_shortfall_count"] == 0

"""The acceptance-list fork, the per-medium cap, and hand-worked promotion."""

from test_helpers import (
    JURY_CHAIR_A,
    ApiErrorId,
    fixtures,
    validate_error,
)


def _painting(title, weight_kg):
    return {
        "title": title, "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0,
        "weight_kg": weight_kg,
    }


def _photograph(title, weight_kg):
    return {
        "title": title, "medium_category": "PHOTOGRAPHY",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0,
        "weight_kg": weight_kg,
    }


# Cards chosen so the five certified means rank 9.00, 8.50, 8.00, 7.50, 7.00 —
# every one of them clear of the 7.0 advance threshold.
CARD_900 = (9, 9, 9)
CARD_850 = (9, 9, 7)
CARD_800 = (8, 8, 8)
CARD_750 = (8, 8, 6)
CARD_700 = (7, 7, 7)


def _run_selection(works, cards, exhibition_overrides):
    """Score every work, complete and close round 1, then publish results."""
    exhibition = fixtures.open_call(**exhibition_overrides)
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_submitted_entry(
        exhibition["id"], artist, works
    )
    jury_round, juror = fixtures.setup_open_round(
        exhibition["id"], round_overrides={"quorum_required": 1}
    )
    for artwork, card in zip(artworks, cards):
        fixtures.submit_score(jury_round["id"], juror, artwork["id"], *card)
    fixtures.set_round_status(jury_round["id"], "SCORING_COMPLETE")
    fixtures.set_round_status(jury_round["id"], "CLOSED")
    result = fixtures.run_acceptance_list(exhibition["id"])
    return exhibition, artist, entry, artworks, result


# ─── The fork: capacity, the medium cap and the waitlist ──

FIVE_WORKS = [
    _painting("First Ridge", 6.0),
    _painting("Second Ridge", 5.0),
    _painting("Third Ridge", 4.0),
    _photograph("Salt Flat", 5.0),
    _photograph("Dry Lake", 4.0),
]
FIVE_CARDS = [CARD_900, CARD_850, CARD_800, CARD_750, CARD_700]


def test_medium_cap_waitlists_a_work_while_global_capacity_is_still_open(api):
    """PRD §3.6: "The global capacity test is evaluated before the medium cap for
    each candidate in rank order, which has a visible consequence: once a medium
    has filled its cap, that medium's next-ranked work falls to the waitlist even
    though global capacity remains open, and a lower-ranked work in a different
    medium takes the seat."

    Design: Difficulty/non_linear_state_machine/artwork_shortlist_fork_and_waitlist_rejoin
    """
    exhibition, _, _, artworks, result = _run_selection(
        FIVE_WORKS, FIVE_CARDS,
        {"acceptance_capacity": 5, "waitlist_capacity": 1},
    )
    third_painting = artworks[2]

    statuses = {
        artwork["title"]: fixtures.read_artwork(artwork["id"])["status"]
        for artwork in artworks
    }
    assert statuses["First Ridge"] == "ACCEPTED"
    assert statuses["Second Ridge"] == "ACCEPTED"
    assert statuses["Third Ridge"] == "WAITLISTED"
    assert statuses["Salt Flat"] == "ACCEPTED"
    assert statuses["Dry Lake"] == "ACCEPTED"

    assert result["accepted_count"] == 4
    assert result["waitlisted_count"] == 1
    assert third_painting["id"] in result["waitlisted_artwork_ids"]
    assert result["exhibition_status"] == "RESULTS_PUBLISHED"

    published = fixtures.read_exhibition(exhibition["id"])
    assert published["accepted_count"] == 4
    assert published["waitlisted_count"] == 1
    assert published["accepted_count"] < published["acceptance_capacity"], (
        "the third painting was displaced by its medium's cap, not by capacity"
    )


def test_promotion_rejoins_a_waitlisted_work_ignoring_the_medium_cap(api):
    """PRD §3.6: "A successful promotion raises `accepted_count` by one and lowers
    `waitlisted_count` by one, and increments both the exhibition's `version` and
    the artwork's `version` by 1. Note that promotion is not bound by the
    per-medium cap — that cap governs the automated run only."

    Design: Difficulty/non_linear_state_machine/artwork_shortlist_fork_and_waitlist_rejoin
    """
    exhibition, _, _, artworks, _ = _run_selection(
        FIVE_WORKS, FIVE_CARDS,
        {"acceptance_capacity": 5, "waitlist_capacity": 1},
    )
    third_painting = artworks[2]

    promoted = fixtures.promote_artwork(third_painting["id"], exhibition["id"])
    assert promoted["status"] == "ACCEPTED"

    after = fixtures.read_exhibition(exhibition["id"])
    assert after["accepted_count"] == 5
    assert after["waitlisted_count"] == 0


# ─── Promotion depends on the exhibition's phase ──────

FOUR_PAINTINGS = [
    _painting("First Ridge", 6.0),
    _painting("Second Ridge", 5.0),
    _painting("Third Ridge", 4.0),
    _painting("Fourth Ridge", 3.0),
]
FOUR_CARDS = [CARD_900, CARD_850, CARD_800, CARD_750]


def _four_painting_selection():
    return _run_selection(
        FOUR_PAINTINGS, FOUR_CARDS,
        {"acceptance_capacity": 5, "waitlist_capacity": 2},
    )


def test_promotion_is_permitted_while_the_exhibition_is_results_published(api):
    """PRD §3.6: "A `JuryChair` may promote an individual `WAITLISTED` work
    `WAITLISTED → ACCEPTED` while the exhibition is either `RESULTS_PUBLISHED` or
    `INSTALLATION` — a promotion attempted in any other phase is refused with
    `ERR_EXHIBITION_PHASE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/promotion_requires_exhibition_before_on_view
    """
    exhibition, _, _, artworks, result = _four_painting_selection()

    assert result["accepted_count"] == 2
    assert result["waitlisted_count"] == 2

    promoted = fixtures.promote_artwork(artworks[2]["id"], exhibition["id"])
    assert promoted["status"] == "ACCEPTED"

    after = fixtures.read_exhibition(exhibition["id"])
    assert after["status"] == "RESULTS_PUBLISHED"
    assert after["accepted_count"] == 3
    assert after["waitlisted_count"] == 1


def test_promotion_after_the_show_goes_on_view_is_refused_on_phase(api):
    """PRD §2.10: "**Exhibition phase guard** — the exhibition's `status` permits
    the operation and the requested target phase is reachable from it, else
    `ERR_EXHIBITION_PHASE_INVALID` (409). Applies to phase advance, the
    acceptance-list run, every entry operation, driving a jury round's status,
    waitlist promotion, filing a condition report, filing an installation plan,
    marking a work installed, confirming an award, recording a sale, and
    advancing settlement."

    Design: Difficulty/cross_entity_state_dependency/promotion_requires_exhibition_before_on_view
    """
    exhibition, _, _, artworks, _ = _four_painting_selection()
    fixtures.promote_artwork(artworks[2]["id"], exhibition["id"])

    wall = fixtures.register_wall(exhibition["id"])
    fixtures.enter_installation(exhibition["id"])
    for index, artwork in enumerate(artworks[:3]):
        fixtures.file_condition_report(artwork["id"], "INTAKE", "A")
        start = index * 130.0
        fixtures.plan_span(artwork["id"], wall, start, start + 100.0)
        fixtures.install_artwork(artwork["id"])
    fixtures.go_on_view(exhibition["id"])

    version = fixtures.exhibition_version(exhibition["id"])
    response = api.promote_artwork(
        artworks[3]["id"], {"expected_exhibition_version": version}, JURY_CHAIR_A
    )
    validate_error(response, ApiErrorId.ERR_EXHIBITION_PHASE_INVALID.value)

    refused = fixtures.read_artwork(artworks[3]["id"])
    assert refused["status"] == "WAITLISTED"
    assert refused["placement_status"] == "UNPLACED"

    after = fixtures.read_exhibition(exhibition["id"])
    assert after["accepted_count"] == 3
    assert after["accepted_count"] < after["acceptance_capacity"], (
        "capacity was still open, so the phase guard is what refused the promotion"
    )
    assert after["waitlisted_count"] == 1

"""Localization tracks, the accessibility index and its conformance bands."""
from test_helpers import (
    mint_version,
    new_document,
    new_jurisdiction,
    track_at_a11y_review,
)


def test_a11y_index_rounds_each_section_before_summing_four_sections():
    """PRD §3.5: "Step one: for each section in order, multiply that section's
    score by 100 and round the product half up to two decimal places, producing
    a per-section percentage. Step two: add those already-rounded per-section
    percentages together exactly, with no further rounding of the running total.
    Step three: divide that sum by the section count and round the quotient half
    up to two decimal places ... for a version with four sections and scores of
    0.90125, 0.90375, 0.90625 and 0.90875, the pinned order yields per-section
    percentages of 90.13, 90.38, 90.63 and 90.88, summing to 362.02, which
    divided by four is 90.505 and rounds to **90.51** — whereas summing the raw
    scores first and rounding only once yields 362.00 divided by four, or
    90.50."

    Design: Difficulty/combinatorial_formula/a11y_index_round_per_section_before_summing
    """
    jurisdiction = new_jurisdiction()
    document = new_document()
    version = mint_version(document, [jurisdiction["id"]], section_count=4)
    assert version["section_count"] == 4

    track = track_at_a11y_review(
        version["id"], section_scores=[0.90125, 0.90375, 0.90625, 0.90875]
    )

    assert track["status"] == "A11Y_REVIEW", (
        f"submitting scores must move the track to A11Y_REVIEW, got {track['status']}"
    )
    assert float(track["a11y_index"]) == 90.51, (
        "per-section rounding before the sum yields 90.13+90.38+90.63+90.88 = 362.02, "
        f"362.02/4 = 90.505 -> 90.51; the raw-sum order would give 90.50, got "
        f"{track['a11y_index']}"
    )
    assert track["conformance_level"] == "AA", (
        "an index of 90.51 sits at or above 90.00 and below 96.00, so the band is AA, "
        f"got {track['conformance_level']}"
    )


def test_a11y_index_per_section_rounding_shifts_a_two_section_quotient():
    """PRD §3.5: "The per-section rounding happens strictly before the
    summation, and this is not interchangeable with rounding only at the end."
    ... "Step three: divide that sum by the section count and round the quotient
    half up to two decimal places; the result is `a11y_index`, a number in the
    inclusive range from 0 to 100."

    Design: Difficulty/combinatorial_formula/a11y_index_round_per_section_before_summing
    """
    jurisdiction = new_jurisdiction()
    document = new_document()
    version = mint_version(document, [jurisdiction["id"]], section_count=2)
    assert version["section_count"] == 2

    track = track_at_a11y_review(version["id"], section_scores=[0.90125, 0.90375])

    assert float(track["a11y_index"]) == 90.26, (
        "90.13 + 90.38 = 180.51, divided by 2 is 90.255 which rounds half up to "
        f"90.26; the raw-sum order would give 90.25, got {track['a11y_index']}"
    )
    assert track["conformance_level"] == "AA", (
        f"90.26 falls in the AA band, got {track['conformance_level']}"
    )
    assert track["section_scores"] is not None and len(track["section_scores"]) == 2, (
        "the submission must replace section_scores with exactly section_count entries"
    )

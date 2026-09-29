"""Integrity-screening verdict bands, the current-round rollup and its cascades."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx


def _setup_round_one_after_revision():
    """A manuscript screened `FLAG` in round 0 and re-screened `PASS` in round 1.

    Round 0 carries a 25.0 similarity scan (FLAG); two `MAJOR_REVISION` reviews
    give a consensus index of (2 + 2) / 2 = 2.00, which bands to `MAJOR_REVISION`
    and returns the paper to the author; the revision opens round 1, where a
    single 5.0 similarity scan is the only screening in scope.
    """
    world = fx.setup_decision_pending(
        recommendations=("MAJOR_REVISION", "MAJOR_REVISION"), similarity_pct=25.0
    )
    manuscript_id = world["manuscript"]["id"]
    world["round_zero_screening"] = fx.list_integrity_screenings(manuscript_id)[0]
    world["decision"] = fx.issue_decision(
        manuscript_id, world["handling_headers"], editorial_note="Major revision required"
    )
    fx.submit_revision(
        manuscript_id, world["author_headers"], page_count=18, figure_count=2
    )
    world["round_one_screening"] = fx.file_plagiarism_screening(manuscript_id, 5.0)
    world["manuscript"] = fx.get_manuscript(manuscript_id)
    return world


def test_similarity_at_exactly_twenty_percent_yields_a_flag_verdict():
    """The FLAG band is closed at its lower edge, so 20.0 is FLAG and not PASS.

    PRD: "A plagiarism scan whose `similarity_pct` is at least 40.0 yields `BLOCK`; one at least 20.0 but below 40.0 yields `FLAG`; anything below 20.0 yields `PASS`."

    Design: Corner/calculations/plagiarism_similarity_at_twenty_flags_but_still_advances
    """
    world = fx.setup_submitted_manuscript()

    screening = fx.file_plagiarism_screening(world["manuscript"]["id"], 20.0)

    a.assert_fields(screening, verdict="FLAG", round=0, scan_type="PLAGIARISM")
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(manuscript, integrity_status="FLAG", status="SUBMITTED")


def test_similarity_just_below_twenty_percent_yields_a_pass_verdict():
    """A hair under the FLAG floor stays in the PASS band.

    PRD: "A plagiarism scan whose `similarity_pct` is at least 40.0 yields `BLOCK`; one at least 20.0 but below 40.0 yields `FLAG`; anything below 20.0 yields `PASS`."

    Design: Corner/calculations/plagiarism_similarity_at_twenty_flags_but_still_advances
    """
    world = fx.setup_submitted_manuscript()

    screening = fx.file_plagiarism_screening(world["manuscript"]["id"], 19.99)

    a.assert_fields(screening, verdict="PASS", round=0)
    assert fx.get_manuscript(world["manuscript"]["id"])["integrity_status"] == "PASS"


def test_flag_rollup_does_not_bar_advancing_to_review():
    """A FLAG rollup is one of the two verdicts the desk call accepts.

    PRD: "It additionally requires that the manuscript's `integrity_status` is either `PASS` or `FLAG` — a `BLOCK` rollup is refused with `ERR_INTEGRITY_BLOCK`, and the only ways forward from there are a desk rejection or an ethics case resolved in the manuscript's favour; that the manuscript's `formatting_status` is `COMPLIANT`, a `NON_COMPLIANT` manuscript being refused with `ERR_FORMATTING_NON_COMPLIANT`; and that the manuscript's `subject_area` is a member of the journal's `subject_areas`, an out-of-scope paper being refused with `ERR_SUBJECT_AREA_OUT_OF_SCOPE`."

    Design: Corner/calculations/plagiarism_similarity_at_twenty_flags_but_still_advances
    """
    world = fx.setup_under_review_manuscript(similarity_pct=20.0)

    a.assert_fields(
        world["manuscript"], status="UNDER_REVIEW", integrity_status="FLAG"
    )


def test_two_manipulated_figures_yield_a_block_verdict():
    """The image-forensics band reads the figure count, not the similarity scale.

    PRD: "An image-forensics scan whose `manipulated_figure_count` is at least 2 yields `BLOCK`; exactly 1 manipulated figure yields `FLAG`; zero yields `PASS`."

    Design: Corner/calculations/image_forensics_block_opens_high_severity_integrity_case
    """
    world = fx.setup_submitted_manuscript(manuscript_overrides={"figure_count": 4})

    screening = fx.file_image_forensics_screening(world["manuscript"]["id"], 2)

    a.assert_fields(screening, verdict="BLOCK", scan_type="IMAGE_FORENSICS", round=0)
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(manuscript, integrity_status="BLOCK", status="SUBMITTED")


def test_image_block_auto_opens_one_high_severity_image_integrity_case():
    """The block cascade files exactly one case, and it is an image-integrity one.

    PRD: "It automatically opens a publication-ethics case against the manuscript with `opened_by` set to `SCREENING_CASCADE` and `severity` set to `HIGH`, its `case_type` being `PLAGIARISM` for a text-similarity block and `IMAGE_INTEGRITY` for an image-manipulation block."

    Design: Corner/calculations/image_forensics_block_opens_high_severity_integrity_case
    """
    world = fx.setup_submitted_manuscript(manuscript_overrides={"figure_count": 4})

    fx.file_image_forensics_screening(world["manuscript"]["id"], 2)

    cases = fx.list_ethics_cases(world["manuscript"]["id"])
    assert len(cases) == 1, f"Expected exactly one auto-opened case, got {len(cases)}"
    a.assert_fields(
        cases[0],
        case_type="IMAGE_INTEGRITY",
        severity="HIGH",
        opened_by="SCREENING_CASCADE",
    )


def test_integrity_rollup_reads_only_the_current_revision_round():
    """A round-0 FLAG is retained as evidence but never re-enters the round-1 rollup.

    PRD: "The manuscript's `integrity_status` is then rolled up across **only the screenings of its current `revision_round`** — earlier rounds' screenings are retained for audit and never re-enter the rollup."

    Design: Corner/calculations/integrity_rollup_ignores_prior_revision_round_screenings
    """
    world = _setup_round_one_after_revision()

    a.assert_fields(world["round_zero_screening"], round=0, verdict="FLAG")
    a.assert_fields(world["round_one_screening"], round=1, verdict="PASS")

    screenings = fx.list_integrity_screenings(world["manuscript"]["id"])
    assert len(screenings) == 2, f"Expected both rounds retained, got {len(screenings)}"
    assert world["manuscript"]["integrity_status"] == "PASS", (
        "the historical FLAG belongs to round 0 and must not win the round-1 rollup"
    )


def test_round_one_pass_screening_reopens_review_after_a_revision():
    """The round-1 screening is the gate that carries the revision back into review.

    PRD: "When the manuscript sits at `REVISION_SUBMITTED` and a newly filed screening for the current round yields `PASS` or `FLAG` while the manuscript's `formatting_status` is `COMPLIANT`, the manuscript automatically advances `REVISION_SUBMITTED → UNDER_REVIEW` within the same request, and its `review_shortfall_flag` is cleared to false."

    Design: Corner/calculations/integrity_rollup_ignores_prior_revision_round_screenings
    """
    world = _setup_round_one_after_revision()

    a.assert_fields(
        world["manuscript"],
        status="UNDER_REVIEW",
        revision_round=1,
        page_count=18,
        review_shortfall_flag=False,
    )

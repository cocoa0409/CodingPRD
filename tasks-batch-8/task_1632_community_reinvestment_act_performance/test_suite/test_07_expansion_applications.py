"""Expansion applications: the rating gate on submission and the choice of
the latest FINALIZED exam."""
from test_helpers import (
    ApiErrorId,
    create_active_area,
    create_complete_public_file,
    create_draft_application,
    create_finalized_exam,
    get_application,
    submit_application,
    validate_error,
)


# ---------------------------------------------------------------------------
# Queue A — Difficulty/cross_entity_state_dependency/expansion_submit_gated_by_latest_exam_rating
# ---------------------------------------------------------------------------

def test_expansion_submit_gated_by_latest_exam_rating(api, bank_executive_headers):
    """PRD §3.8: "When any exam cycle has reached `FINALIZED`, the latest of
    them — the one with the maximum `evaluation_window_end`, with ties broken by
    the latest `created_at` — must carry a `composite_rating` of `OUTSTANDING`
    or `SATISFACTORY`; a latest finalized rating of `NEEDS_TO_IMPROVE` or
    `SUBSTANTIAL_NONCOMPLIANCE` rejects the submission with
    `ERR_RATING_BLOCKS_EXPANSION`."

    Design: Difficulty/cross_entity_state_dependency/expansion_submit_gated_by_latest_exam_rating
    """
    area = create_active_area(
        area_code="AA-XD2", msa_code="19100", state_code="TX", census_tracts=["T1"],
        annual_cd_budget_cents=1000000,
    )
    create_complete_public_file("Rating Gate Bank")
    exam = create_finalized_exam(
        "NEEDS_TO_IMPROVE", "SATISFACTORY", "SATISFACTORY",
        "2024-01-01", "2024-12-31",
    )
    assert exam["composite_rating"] == "NEEDS_TO_IMPROVE"

    app = create_draft_application(area["id"], "MERGER")
    resp = api.submit_expansion_application(app["id"], bank_executive_headers)
    validate_error(resp, ApiErrorId.ERR_RATING_BLOCKS_EXPANSION)
    assert get_application(app["id"])["status"] == "DRAFT"


def test_expansion_submit_uses_latest_finalized_exam(api, bank_executive_headers):
    """PRD §3.8: "When any exam cycle has reached `FINALIZED`, the latest of
    them — the one with the maximum `evaluation_window_end`, with ties broken by
    the latest `created_at` — must carry a `composite_rating` of `OUTSTANDING`
    or `SATISFACTORY`; a latest finalized rating of `NEEDS_TO_IMPROVE` or
    `SUBSTANTIAL_NONCOMPLIANCE` rejects the submission with
    `ERR_RATING_BLOCKS_EXPANSION`."

    Design: Difficulty/cross_entity_state_dependency/expansion_submit_gated_by_latest_exam_rating
    """
    area = create_active_area(
        area_code="AA-XD2B", msa_code="19100", state_code="TX", census_tracts=["T1"],
        annual_cd_budget_cents=1000000,
    )
    create_complete_public_file("Rating Gate Bank Two")
    # Older finalized exam is adverse; the later-window exam is favorable.
    older = create_finalized_exam(
        "NEEDS_TO_IMPROVE", "SATISFACTORY", "SATISFACTORY",
        "2022-01-01", "2022-12-31",
    )
    assert older["composite_rating"] == "NEEDS_TO_IMPROVE"
    newer = create_finalized_exam(
        "SATISFACTORY", "SATISFACTORY", "SATISFACTORY",
        "2024-01-01", "2024-12-31",
    )
    assert newer["composite_rating"] == "SATISFACTORY"

    # The guard reads the latest FINALIZED exam (maximum evaluation_window_end):
    # SATISFACTORY, so submission proceeds.
    app = create_draft_application(area["id"], "MERGER")
    submitted = submit_application(app["id"])
    assert submitted["status"] == "SUBMITTED"

"""The scoring run under its two variants.

The two variants read different input sets over the same stored rows, so the
same insured scores very differently depending on which run the underwriter asks
for.
"""

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    THREE_EVENT_HISTORY,
    THREE_PACKAGE_HISTORY,
    UNDERWRITER,
    assert_risk_band_matches_score,
    open_submission,
    read_submission,
    score_submission_payload,
    setup_insured_with_history,
)


def _insured_with_three_years_of_history():
    """An insured whose three packages put the financial maximum and the
    governance maximum on different fiscal years, and whose litigation history
    spans the full-weight band, the half-weight band and one open matter."""
    return setup_insured_with_history(
        package_overrides=THREE_PACKAGE_HISTORY,
        litigation_overrides=THREE_EVENT_HISTORY,
    )


def test_indicative_run_reads_one_package_and_only_securities_and_regulatory_matters(api):
    """PRD 3.2: "Under `INDICATIVE` — the broker's pre-underwriting indication —
    the run reads exactly one disclosure package: the one with the greatest
    `fiscal_year` for that insured, and where two packages share the greatest
    `fiscal_year`, the one created most recently. It reads only those litigation
    events whose `case_type` is `SECURITIES_CLASS_ACTION` or
    `REGULATORY_ENFORCEMENT`." The count consumed is recorded as
    `disclosure_packages_considered`: "exactly 1 under `INDICATIVE`".

    Design: Difficulty/dual_variant_calc/risk_score_indicative_vs_underwritten_diverge
    """
    scenario = _insured_with_three_years_of_history()
    submission = open_submission(scenario["insured"]["id"])

    response = api.score_submission(
        submission["id"], score_submission_payload("INDICATIVE"), UNDERWRITER
    )

    data = validate_success(response, 200)
    assert data["status"] == "SCORED"
    assert data["score_variant"] == "INDICATIVE"
    assert data["disclosure_packages_considered"] == 1
    # Only the securities class action is selected, at 20 units under the binary
    # recency factor; the merger objection and the employment matter are ignored,
    # and PRD 3.2: "under `INDICATIVE` the surcharge is never applied."
    assert data["litigation_units"] == pytest.approx(20.0, abs=0.01)
    assert data["risk_score"] == pytest.approx(85.80, abs=0.01)
    assert data["risk_band"] == "ELEVATED"
    assert_risk_band_matches_score(data)


def test_underwritten_run_takes_the_two_subscore_maxima_independently(api):
    """PRD 3.2: "Under `UNDERWRITTEN` the financial component is the greatest
    `financial_subscore` among the packages consumed and the governance component
    is the greatest `governance_subscore` among them, each maximum taken on its
    own — the two maxima may well come from different packages." The run "reads
    the three packages with the greatest `fiscal_year`" and "every litigation
    event of the insured whatever its `case_type`", and the open-litigation
    surcharge "is added only when the `UNDERWRITTEN` variant is running and at
    least one selected event has a null `resolved_date`".

    Design: Difficulty/dual_variant_calc/risk_score_indicative_vs_underwritten_diverge
    """
    scenario = _insured_with_three_years_of_history()
    submission = open_submission(scenario["insured"]["id"])

    response = api.score_submission(
        submission["id"], score_submission_payload("UNDERWRITTEN"), UNDERWRITER
    )

    data = validate_success(response, 200)
    assert data["status"] == "SCORED"
    assert data["score_variant"] == "UNDERWRITTEN"
    assert data["disclosure_packages_considered"] == 3
    # 20 (securities class action, factor 1.0) + 2.5 (merger objection, factor
    # 0.5) + 3 (employment practices, factor 1.0) + 10 (open-litigation surcharge).
    assert data["litigation_units"] == pytest.approx(35.5, abs=0.01)
    # The financial maximum 48 and the governance maximum 26 come from the same
    # fiscal year here only by coincidence of the fixture; what the composite
    # proves is that each maximum is taken on its own: (48 + 26 + 35.5) * 1.30.
    assert data["risk_score"] == pytest.approx(142.35, abs=0.01)
    assert data["risk_band"] == "SEVERE"
    assert_risk_band_matches_score(data)

    packages, _ = validate_paginated(
        api.list_disclosure_packages(scenario["insured"]["id"], UNDERWRITER)
    )
    by_year = {p["fiscal_year"]: p for p in packages}
    assert by_year[2025]["financial_subscore"] == pytest.approx(24.0, abs=0.01)
    assert by_year[2025]["governance_subscore"] == pytest.approx(22.0, abs=0.01)
    assert by_year[2024]["financial_subscore"] == pytest.approx(48.0, abs=0.01)
    assert by_year[2024]["governance_subscore"] == pytest.approx(26.0, abs=0.01)
    assert by_year[2023]["financial_subscore"] == pytest.approx(0.0, abs=0.01)
    assert by_year[2023]["governance_subscore"] == pytest.approx(6.0, abs=0.01)


def test_rescoring_under_the_other_variant_diverges_on_identical_stored_rows(api):
    """PRD 3.2: "Scoring a submission moves it `DRAFT → SCORED`, and running it
    again on an already-scored submission is a legitimate self-loop that leaves it
    `SCORED → SCORED`." "Every accepted run overwrites `risk_score`, `risk_band`,
    `litigation_units` and `disclosure_packages_considered`, sets `score_variant`
    to the requested variant ... and increments the submission's `version` by 1."

    Design: Difficulty/dual_variant_calc/risk_score_indicative_vs_underwritten_diverge
    """
    scenario = _insured_with_three_years_of_history()
    submission = open_submission(scenario["insured"]["id"])

    indicative = validate_success(
        api.score_submission(
            submission["id"], score_submission_payload("INDICATIVE"), UNDERWRITER
        ),
        200,
    )
    underwritten = validate_success(
        api.score_submission(
            submission["id"], score_submission_payload("UNDERWRITTEN"), UNDERWRITER
        ),
        200,
    )

    assert indicative["risk_score"] == pytest.approx(85.80, abs=0.01)
    assert underwritten["risk_score"] == pytest.approx(142.35, abs=0.01)
    assert underwritten["risk_score"] - indicative["risk_score"] == pytest.approx(
        56.55, abs=0.01
    ), "the UNDERWRITTEN variant is strictly the more severe of the two"
    assert indicative["risk_band"] == "ELEVATED"
    assert underwritten["risk_band"] == "SEVERE"
    assert underwritten["disclosure_packages_considered"] == 3
    assert underwritten["status"] == "SCORED"

    # Created at 1, one increment per score call.
    assert read_submission(submission["id"])["version"] == 3

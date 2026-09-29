"""The annual evaluation: six pinned steps, and a row nobody may edit.

Covers the double use of the banding function, the penalty multiplier read off
the raw band, the cap and the floor, and the immutability of the child row that
still drives its mutable parent.
"""
from test_helpers import (
    ApiErrorId,
    OFFICER_USER_ID,
    OFFICER_USER_ID_ALT,
    issue_noncompliance_action,
    performance_evaluation_payload,
    read_permit,
    setup_issued_permit,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
    make_authorized_officer_headers,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]


def _evaluate(permit_id, evaluation_year, officer_user_id, **scores):
    return validate_success(
        api_client.create_performance_evaluation(
            permit_id,
            performance_evaluation_payload(evaluation_year, **scores),
            make_authorized_officer_headers(officer_user_id),
        ),
        201,
    )


def _cite(permit_id, provision, **overrides):
    return issue_noncompliance_action(
        permit_id, cited_provision=provision, **overrides
    )


def test_the_multiplier_is_read_from_the_raw_band_and_the_rating_from_the_adjusted_score():
    """PRD §3.8: "**Step one** computes `raw_score` as 0.35 times `resource_protection_score`,
    plus 0.25 times `client_safety_score`, plus 0.20 times `reporting_timeliness_score`, plus
    0.20 times `fee_compliance_score`, rounded half-up to two decimals."
    PRD §3.8: "**Step three** reads the penalty multiplier off that provisional band: 0.5 for
    `SUPERIOR`, 1.0 for `SATISFACTORY`, 1.5 for `MARGINAL`, 2.0 for `UNSATISFACTORY` — a strong
    operator is penalised at half rate for the same open points, and a weak one at double."
    PRD §3.8: "**Step five** computes `weighted_score` as `raw_score` minus
    `penalty_points_applied`, floored at 0.0, rounded half-up to two decimals."
    PRD §3.8: "Banding is one function used twice: a score at or above 90.0 is `SUPERIOR`, at or
    above 75.0 is `SATISFACTORY`, at or above 60.0 is `MARGINAL`, and anything lower is
    `UNSATISFACTORY`."
    PRD §3.8: "`provisional_band` is banded from the raw score and is never recomputed from the
    adjusted score, and deriving the multiplier from the adjusted score instead would publish a
    different rating for the same inputs."
    PRD §3.8: "After the row is written, the permit's `latest_performance_rating` is set to the
    `rating` of the evaluation with the highest `evaluation_year`, tie-broken by `created_at`
    descending, and the permit's `version` advances."
    PRD §3.8: "The acting `X-User-ID` is stamped onto `evaluator_user_id`."

    Design: Difficulty/combinatorial_formula/performance_band_before_penalty_pinned_order
    """
    context = setup_issued_permit()
    permit_id = context["permit"]["id"]

    for index in range(1, 5):
        _cite(permit_id, f"36 CFR 251.56(a) clause {index}")
    before = read_permit(permit_id)
    assert before["open_noncompliance_points"] == 8, "four MINOR warnings at 2 points each"
    version_before = before["version"]

    evaluation = _evaluate(
        permit_id, 2027, OFFICER_USER_ID_ALT,
        resource_protection_score=96,
        client_safety_score=92,
        reporting_timeliness_score=86,
        fee_compliance_score=86,
    )
    assert evaluation["raw_score"] == 91.00, "33.6 + 23.0 + 17.2 + 17.2"
    assert evaluation["provisional_band"] == "SUPERIOR", (
        "banded from the raw 91.00, which clears the 90.0 line"
    )
    assert evaluation["penalty_points_applied"] == 4.00, (
        "8 open points at the SUPERIOR multiplier of 0.5, far under the 30.0 cap"
    )
    assert evaluation["weighted_score"] == 87.00, (
        "reading the multiplier off the adjusted score would charge the full 8 and publish 83.00"
    )
    assert evaluation["rating"] == "SATISFACTORY", (
        "step six bands the adjusted 87.00, so the published rating differs from the "
        "provisional_band on the same row"
    )
    assert evaluation["provisional_band"] != evaluation["rating"]
    assert evaluation["evaluator_user_id"] == OFFICER_USER_ID_ALT
    assert evaluation["evaluation_year"] == 2027

    after = read_permit(permit_id)
    assert after["latest_performance_rating"] == "SATISFACTORY"
    assert after["version"] == version_before + 1
    assert after["open_noncompliance_points"] == 8, "an evaluation does not disturb the points"


def test_the_penalty_stops_at_thirty_and_the_adjusted_score_stops_at_zero():
    """PRD §3.8: "**Step two** computes `provisional_band` by banding `raw_score`."
    PRD §3.8: "**Step four** computes `penalty_points_applied` as the permit's
    `open_noncompliance_points` multiplied by that multiplier, capped at 30.0, rounded half-up to
    two decimals."
    PRD §3.8: "**Step five** computes `weighted_score` as `raw_score` minus
    `penalty_points_applied`, floored at 0.0, rounded half-up to two decimals."
    PRD §3.8: "**Step six** computes the published `rating` by banding `weighted_score`."
    PRD §3.8: "`points` is derived from severity: 2 for `MINOR`, 5 for `MODERATE`, 10 for `MAJOR`"
    PRD §3.8: "An `action_type` of `SUSPENSION`, by contrast, does not suspend anything by itself;
    suspension arrives only through the point threshold or an officer's explicit order."
    PRD §3.8: "If `open_noncompliance_points` is at or above **12**, the permit is
    `NONCOMPLIANT`."

    Design: Difficulty/combinatorial_formula/performance_band_before_penalty_pinned_order
    """
    context = setup_issued_permit()
    permit_id = context["permit"]["id"]

    _cite(permit_id, "36 CFR 251.60(a)", severity="MAJOR", action_type="SUSPENSION")
    _cite(permit_id, "36 CFR 251.60(b)", severity="MAJOR", action_type="SUSPENSION")
    loaded = read_permit(permit_id)
    assert loaded["open_noncompliance_points"] == 20
    assert loaded["compliance_status"] == "NONCOMPLIANT"
    assert loaded["administrative_status"] == "ISSUED", (
        "the point threshold only reaches an ACTIVE permit, and a SUSPENSION citation "
        "suspends nothing by itself"
    )

    marginal = _evaluate(
        permit_id, 2027, OFFICER_USER_ID,
        resource_protection_score=60, client_safety_score=60,
        reporting_timeliness_score=60, fee_compliance_score=60,
    )
    assert marginal["raw_score"] == 60.00
    assert marginal["provisional_band"] == "MARGINAL", "60.0 is at the MARGINAL line, not below it"
    assert marginal["penalty_points_applied"] == 30.00, (
        "20 points at 1.5 lands exactly on the cap, which the cap admits"
    )
    assert marginal["weighted_score"] == 30.00
    assert marginal["rating"] == "UNSATISFACTORY"

    capped = _evaluate(
        permit_id, 2028, OFFICER_USER_ID,
        resource_protection_score=40, client_safety_score=40,
        reporting_timeliness_score=40, fee_compliance_score=40,
    )
    assert capped["raw_score"] == 40.00
    assert capped["provisional_band"] == "UNSATISFACTORY"
    assert capped["penalty_points_applied"] == 30.00, (
        "20 points at the doubled multiplier is 40.0, and the cap cuts it to 30.0"
    )
    assert capped["weighted_score"] == 10.00

    floored = _evaluate(
        permit_id, 2029, OFFICER_USER_ID,
        resource_protection_score=20, client_safety_score=20,
        reporting_timeliness_score=20, fee_compliance_score=20,
    )
    assert floored["raw_score"] == 20.00
    assert floored["penalty_points_applied"] == 30.00
    assert floored["weighted_score"] == 0.00, "20.00 minus 30.00 is floored at zero, never negative"
    assert floored["rating"] == "UNSATISFACTORY"

    final = read_permit(permit_id)
    assert final["latest_performance_rating"] == "UNSATISFACTORY"
    assert final["open_noncompliance_points"] == 20, "three evaluations changed no points"


def test_an_evaluation_row_carries_no_version_and_the_next_year_leaves_it_alone():
    """PRD §2.4: "`PerformanceEvaluation` is the one exception. An evaluation is an immutable
    record of an officer's findings: there is no endpoint that edits one, and the record carries
    only `id` and `created_at`. It has no `updated_at` field and no `version` field at all."
    PRD §3.8: "At most one evaluation may exist per permit and `evaluation_year`; a second filing
    for the same pair is a uniqueness breach and is rejected as an invalid request."
    PRD §3.8: "Evaluations are listable per permit ordered by `evaluation_year` ascending then
    `created_at` ascending, with an optional `evaluation_year` filter."
    PRD §3.8: "After the row is written, the permit's `latest_performance_rating` is set to the
    `rating` of the evaluation with the highest `evaluation_year`, tie-broken by `created_at`
    descending, and the permit's `version` advances."

    Design: Corner/entities/performance_evaluation_row_is_immutable_and_carries_no_version
    """
    context = setup_issued_permit()
    permit_id = context["permit"]["id"]
    opening_version = read_permit(permit_id)["version"]

    first = _evaluate(
        permit_id, 2027, "officer-eval-1",
        resource_protection_score=80, client_safety_score=80,
        reporting_timeliness_score=80, fee_compliance_score=80,
    )
    assert first["raw_score"] == 80.00
    assert first["provisional_band"] == "SATISFACTORY"
    assert first["penalty_points_applied"] == 0.00, "no open points, so nothing to multiply"
    assert first["weighted_score"] == 80.00
    assert first["rating"] == "SATISFACTORY"
    assert first["evaluator_user_id"] == "officer-eval-1"
    assert "version" not in first
    assert "updated_at" not in first
    assert first["created_at"].startswith("2027-01-05")
    assert read_permit(permit_id)["version"] == opening_version + 1

    validate_error(
        api_client.create_performance_evaluation(
            permit_id,
            performance_evaluation_payload(
                2027, resource_protection_score=10, client_safety_score=10,
                reporting_timeliness_score=10, fee_compliance_score=10,
            ),
            make_authorized_officer_headers("officer-eval-1"),
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    second = _evaluate(
        permit_id, 2028, "officer-eval-2",
        resource_protection_score=60, client_safety_score=60,
        reporting_timeliness_score=60, fee_compliance_score=60,
    )
    assert second["raw_score"] == 60.00
    assert second["provisional_band"] == "MARGINAL"
    assert second["rating"] == "MARGINAL"
    assert second["evaluator_user_id"] == "officer-eval-2"
    assert "version" not in second

    rows, meta = validate_paginated(
        api_client.list_performance_evaluations(permit_id, SPECIALIST)
    )
    assert meta["total_count"] == 2
    assert [row["evaluation_year"] for row in rows] == [2027, 2028]
    assert rows[0] == first, (
        "the 2027 row is byte-identical after the 2028 filing: no rewrite, no stamp refresh"
    )

    only_2027, filtered_meta = validate_paginated(
        api_client.list_performance_evaluations(
            permit_id, SPECIALIST, params={"evaluation_year": 2027}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert only_2027[0]["id"] == first["id"]

    permit = read_permit(permit_id)
    assert permit["latest_performance_rating"] == "MARGINAL", (
        "the highest evaluation_year wins even though it is the worse rating"
    )
    assert permit["version"] == opening_version + 2, (
        "one increment per accepted filing, and none for the rejected duplicate year"
    )
    assert permit["compliance_status"] == "COMPLIANT"

"""Satisfaction surveys, the community satisfaction roll-up, and the advisor
caseload report.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    assert_survey,
    create_survey_payload, set_clock,
    build_scenario, setup_advisor_with_caseload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_satisfaction_composite_and_community_average_rollup(api):
    """PRD §3.14: "The **composite score** normalizes the three answers to a 0-to-100
    scale — `nps_score` times 10, `care_rating` times 20, `value_rating` times 20 —
    and weights them 0.40 on the normalized NPS, 0.35 on the normalized care rating
    and 0.25 on the normalized value rating, rounding the weighted sum half up once
    to 2 decimals."

    Design: Corner/calculations/satisfaction_composite_and_community_average_rollup
    """
    sc = build_scenario(api, "moved_in")
    set_clock(api, "2026-07-20T09:00:00Z")  # exactly 30 days after move-in
    survey = validate_success(api.create_survey(
        create_survey_payload(sc["placement"]["id"], nps_score=9, care_rating=4, value_rating=3),
        sc["family_headers"]), 201)
    assert_survey(survey)
    assert survey["composite_score"] == 79.00
    assert survey["days_after_move_in"] == 30
    assert survey["respondent_family_id"] == sc["family"]["id"]
    assert survey["community_id"] == sc["community"]["id"]
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["satisfaction_survey_count"] == 1
    assert community["avg_satisfaction_score"] == 79.00


def test_survey_before_eligibility_window_rejected(api):
    """PRD §3.14: "A survey may be submitted only once the current date is at least
    the `actual_move_in_date` plus 30 days (the survey-eligibility window), else
    `ERR_SURVEY_TOO_EARLY`".

    Design: Corner/validations/survey_twenty_days_after_move_in_returns_survey_too_early
    """
    sc = build_scenario(api, "moved_in")
    set_clock(api, "2026-07-10T09:00:00Z")  # only 20 days after move-in
    resp = api.create_survey(
        create_survey_payload(sc["placement"]["id"], nps_score=9, care_rating=4, value_rating=3),
        sc["family_headers"])
    validate_error(resp, ApiErrorId.ERR_SURVEY_TOO_EARLY)
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["satisfaction_survey_count"] == 0
    assert community["avg_satisfaction_score"] == 0
    rows, _ = validate_paginated(api.list_surveys(ADMIN, params={"placement_id": sc["placement"]["id"]}))
    assert rows == []


def test_second_survey_for_same_placement_rejected(api):
    """PRD §3.14: "and only one survey may exist per placement, a duplicate yielding
    `ERR_DUPLICATE_SURVEY`."

    Design: Corner/validations/second_survey_for_the_same_placement_returns_duplicate_survey
    """
    sc = build_scenario(api, "moved_in")
    set_clock(api, "2026-07-20T09:00:00Z")
    first = validate_success(api.create_survey(
        create_survey_payload(sc["placement"]["id"], nps_score=9, care_rating=4, value_rating=3),
        sc["family_headers"]), 201)
    resp = api.create_survey(
        create_survey_payload(sc["placement"]["id"], nps_score=2, care_rating=1, value_rating=1),
        sc["family_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SURVEY)
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["satisfaction_survey_count"] == 1
    assert community["avg_satisfaction_score"] == 79.00
    assert validate_success(api.get_survey(first["id"], ADMIN))["composite_score"] == 79.00
    rows, _ = validate_paginated(api.list_surveys(ADMIN, params={"placement_id": sc["placement"]["id"]}))
    assert len(rows) == 1


def test_advisor_caseload_report_returns_both_load_index_variants(api):
    """PRD §3.14: "The **advisor-caseload report** returns, for one advisor or a
    whole region, the `advisor_id`, `active_caseload_count`, `caseload_capacity`,
    both `headcount_load_index` and `weighted_load_index` (freshly evaluated at read
    time), and a `total_active_assignments` count."

    Design: Corner/endpoints/advisor_caseload_report_returns_both_load_index_variants
    """
    s = setup_advisor_with_caseload(api, count=2, capacity=3)
    report = validate_success(api.report_advisor_caseload(ADMIN, params={"advisor_id": s["advisor"]["id"]}))
    assert report["advisor_id"] == s["advisor"]["id"]
    assert report["active_caseload_count"] == 2
    assert report["caseload_capacity"] == 3
    assert report["headcount_load_index"] == 0.6667
    assert report["weighted_load_index"] == 0.4087
    assert report["total_active_assignments"] == 2

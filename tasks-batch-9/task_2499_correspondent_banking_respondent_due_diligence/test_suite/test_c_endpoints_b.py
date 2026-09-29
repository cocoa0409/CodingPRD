"""Corner queue - section endpoints, part B: the declared non-default list orders."""
from test_helpers import (
    calibrate,
    corridor,
    draft_plan,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    post_observation,
    score_respondent,
    validate_paginated,
)
from test_helpers.fixtures import ANALYST, OFFICER, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_activity_observation_list_orders_by_period_month_then_created_at(api):
    """The rows are posted out of calendar order, so creation order and the declared order
    disagree, and the chronological reading the wind-down basis depends on has to win.

    Design: Corner/endpoints/activity_observation_list_orders_by_period_month_then_created_at
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    assert score_respondent(respondent["id"], "ONBOARDING_PROVISIONAL")["risk_rating"] == "LOW"
    profile = open_profile(respondent["id"], [corridor("DE", 400000.00, 80)])
    calibrate(profile["id"])

    july = post_observation(profile["id"], "2026-07", "DE", aggregate_usd=1000.00, txn_count=3)
    may = post_observation(profile["id"], "2026-05", "DE", aggregate_usd=1000.00, txn_count=3)
    june = post_observation(profile["id"], "2026-06", "DE", aggregate_usd=1000.00, txn_count=3)

    rows, meta = validate_paginated(
        api.list_activity_observations(
            OFFICER, params={"monitoring_profile_id": profile["id"]}
        )
    )
    assert [row["id"] for row in rows] == [may["id"], june["id"], july["id"]]
    assert [row["period_month"] for row in rows] == ["2026-05", "2026-06", "2026-07"]
    assert meta["total_count"] == 3

    filtered, filtered_meta = validate_paginated(
        api.list_activity_observations(
            OFFICER,
            params={"monitoring_profile_id": profile["id"], "period_month": "2026-06"},
        )
    )
    assert [row["id"] for row in filtered] == [june["id"]]
    assert filtered_meta["total_count"] == 1


def test_closure_plan_list_is_ordered_newest_first(api):
    """This is the only collection declared descending, so the later plan has to come first;
    two respondents are needed because one respondent may hold only one open plan.

    Design: Corner/endpoints/closure_plan_list_is_ordered_newest_first
    """
    _de()
    first = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    second = licensed_respondent(
        "DE", legal_name="Sudbank AG", swift_bic="SUEDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )

    plan_one = draft_plan(
        first["id"], RM, termination_reason="COMMERCIAL", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=0,
    )
    plan_two = draft_plan(
        second["id"], RM, termination_reason="RISK_APPETITE", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=0,
    )

    rows, meta = validate_paginated(api.list_closure_plans(ANALYST))
    assert [row["id"] for row in rows] == [plan_two["id"], plan_one["id"]]
    assert meta["total_count"] == 2

    filtered, filtered_meta = validate_paginated(
        api.list_closure_plans(ANALYST, params={"termination_reason": "RISK_APPETITE"})
    )
    assert [row["id"] for row in filtered] == [plan_two["id"]]
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["notice_period_days"] == 60

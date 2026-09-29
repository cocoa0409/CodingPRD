"""Corner queue - section calculations, part C: inherent components and adverse-media uplift."""
from test_helpers import (
    add_verified_owner,
    assert_instant_equals,
    confirmed_media,
    licensed_respondent,
    new_jurisdiction,
    restricted_jurisdiction,
    score_respondent,
)


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _clean_fixture():
    """DE respondent with one verified 80.00 domestic owner, so inherent is 10.00."""
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    add_verified_owner(respondent["id"], "DE", owner_name="Anna Weber", ownership_pct=80.00)
    return respondent["id"]


def test_inherent_risk_score_sums_the_four_components_on_a_clean_file(api):
    """The floor case: only the jurisdiction term and the lowest activity tier contribute, and
    with no control score on file the credit is zero so the residual equals the inherent.

    Design: Corner/calculations/inherent_risk_score_sums_the_four_components_on_a_clean_file
    """
    rid = _clean_fixture()

    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")

    assert scored["inherent_risk_score"] == 10.00
    assert scored["control_credit"] == 0.0000
    assert scored["adverse_media_uplift"] == 0.00
    assert scored["residual_risk_score"] == 10.00
    assert scored["risk_rating"] == "LOW"
    assert scored["risk_assessment_variant"] == "ONBOARDING_PROVISIONAL"
    assert_instant_equals(scored["last_risk_assessed_at"], "2026-08-01T00:00:00Z")
    assert scored["dd_state"] == "DD_IN_PROGRESS"


def test_inherent_risk_score_activity_tier_inclusive_at_one_million(api):
    """Two files identical but for their declared volume straddle a tier edge, and both carry
    the same verified-ownership shortfall so the activity tier is the only moving part.

    Design: Corner/calculations/inherent_risk_score_activity_tier_inclusive_at_one_million
    """
    _de()
    at_edge = licensed_respondent(
        "DE", legal_name="Edge Bank AG", swift_bic="EDGEDEFF",
        expected_monthly_volume_usd=1000000.00, expected_monthly_count=200,
    )
    below = licensed_respondent(
        "DE", legal_name="Under Bank AG", swift_bic="UNDRDEFF",
        expected_monthly_volume_usd=999999.99, expected_monthly_count=200,
    )

    at_scored = score_respondent(at_edge["id"], "ONBOARDING_PROVISIONAL")
    below_scored = score_respondent(below["id"], "ONBOARDING_PROVISIONAL")

    assert at_scored["inherent_risk_score"] == 20.00
    assert below_scored["inherent_risk_score"] == 16.00
    assert at_scored["dd_state"] == "DD_IN_PROGRESS"
    assert below_scored["dd_state"] == "DD_IN_PROGRESS"


def test_inherent_risk_score_ownership_component_clamped_at_ownership_cap(api):
    """Four ownership signals fire at once and their raw sum is well past the component
    ceiling, so the clamp - not the raw 36 - is what enters the inherent total.

    Design: Corner/calculations/inherent_risk_score_ownership_component_clamped_at_ownership_cap
    """
    _de()
    for code, name in (("RU", "Russia"), ("KY", "Cayman Islands"), ("PA", "Panama")):
        restricted_jurisdiction(
            jurisdiction_code=code, name=name, basel_aml_index=6.0, corridor_risk_weight=1.5
        )
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    add_verified_owner(
        rid, "RU", owner_name="Ivan Petrov", ownership_pct=30.00, is_pep=True
    )
    add_verified_owner(
        rid, "KY", owner_name="Sovereign Fund", owner_type="STATE", ownership_pct=20.00
    )
    add_verified_owner(rid, "PA", owner_name="Maria Diaz", ownership_pct=10.00)

    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")

    assert scored["verified_ownership_pct"] == 60.00
    assert scored["ownership_verified"] is False
    assert scored["inherent_risk_score"] == 34.00
    assert scored["residual_risk_score"] == 34.00
    assert scored["risk_rating"] == "MEDIUM"
    assert scored["dd_state"] == "DD_IN_PROGRESS"


def test_adverse_media_uplift_rounds_per_event_then_clamps_at_cap(api):
    """Each item is rounded before it joins the running total, the total is clamped, and the
    resulting residual lands exactly on the inclusive medium boundary.

    Design: Corner/calculations/adverse_media_uplift_rounds_per_event_then_clamps_at_cap
    """
    rid = _clean_fixture()
    grades = (("TIER_2", "A", 7.00), ("TIER_2", "B", 5.25), ("TIER_2", "C", 3.50),
              ("TIER_3", "A", 3.00), ("TIER_3", "C", 1.50))
    for tier, reliability, expected in grades:
        event = confirmed_media(
            rid, headline="Regulator opens probe", category="REGULATORY_ACTION",
            severity_tier=tier, source_reliability=reliability,
            event_date="2026-07-01T00:00:00Z",
        )
        assert event["uplift_points"] == expected

    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")

    assert scored["adverse_media_uplift"] == 20.00
    assert scored["residual_risk_score"] == 30.00
    assert scored["risk_rating"] == "MEDIUM"


def test_risk_rating_stays_low_one_notch_under_the_medium_threshold(api):
    """Dropping the lightest item leaves the total below the medium threshold, exercising the
    exclusive side of the boundary its capped sibling tests inclusively.

    Design: Corner/calculations/risk_rating_stays_low_one_notch_under_the_medium_threshold
    """
    rid = _clean_fixture()
    for tier, reliability in (("TIER_2", "A"), ("TIER_2", "B"), ("TIER_2", "C"),
                              ("TIER_3", "A")):
        confirmed_media(
            rid, headline="Regulator opens probe", category="REGULATORY_ACTION",
            severity_tier=tier, source_reliability=reliability,
            event_date="2026-07-01T00:00:00Z",
        )

    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")

    assert scored["adverse_media_uplift"] == 18.75
    assert scored["residual_risk_score"] == 28.75
    assert scored["risk_rating"] == "LOW"


def test_adverse_media_uplift_lookback_window_is_half_open(api):
    """Three identical items sit at and around the two window edges: the lower edge counts,
    the day before it does not, and the upper edge is excluded by the open bound.

    Design: Corner/calculations/adverse_media_uplift_lookback_window_is_half_open
    """
    rid = _clean_fixture()
    for stamp in ("2024-07-31T00:00:00Z", "2024-08-01T00:00:00Z", "2026-08-01T00:00:00Z"):
        confirmed_media(
            rid, headline="Regulator opens probe", category="REGULATORY_ACTION",
            severity_tier="TIER_2", source_reliability="A", event_date=stamp,
        )

    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")

    assert scored["adverse_media_uplift"] == 7.00
    assert scored["residual_risk_score"] == 17.00
    assert scored["risk_rating"] == "LOW"

"""Corner queue - section calculations, part E: alert generation from observations."""
from test_helpers import (
    add_nested,
    alerts_for,
    calibrate,
    corridor,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    post_observation,
    restricted_jurisdiction,
    score_respondent,
)


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _calibrated(**respondent_overrides):
    """DE respondent with a CALIBRATED single-corridor profile: 598000.00 USD over 120 payments."""
    _de()
    overrides = {
        "legal_name": "Nordbank AG", "swift_bic": "NORDDEFF",
        "expected_monthly_volume_usd": 500000.00, "expected_monthly_count": 100,
    }
    overrides.update(respondent_overrides)
    respondent = licensed_respondent("DE", **overrides)
    assert score_respondent(respondent["id"], "ONBOARDING_PROVISIONAL")["risk_rating"] == "LOW"
    profile = open_profile(respondent["id"], [corridor("DE", 400000.00, 80)])
    calibrate(profile["id"])
    return respondent["id"], profile


def test_alert_generation_volume_breach_is_inclusive_at_the_threshold(api):
    """The observed dollars land exactly on the threshold, so only an inclusive comparison
    raises the breach, and a ratio of exactly one sits under every severity step.

    Design: Corner/calculations/alert_generation_volume_breach_is_inclusive_at_the_threshold
    """
    rid, profile = _calibrated()

    observation = post_observation(
        profile["id"], "2026-07", "DE", aggregate_usd=598000.00, txn_count=10
    )

    assert observation["usd_threshold_applied"] == 598000.00
    assert observation["count_threshold_applied"] == 120
    assert observation["breach_ratio"] == 1.0000
    assert observation["alerts_created_count"] == 1
    alerts = alerts_for(rid)
    assert [a["alert_type"] for a in alerts] == ["VOLUME_BREACH"]
    assert alerts[0]["severity"] == "LOW"
    assert alerts[0]["breach_ratio"] == 1.0000
    assert alerts[0]["state"] == "OPEN"


def test_alert_generation_unexpected_corridor_severity_from_sanctions_status(api):
    """With no matching corridor there is no threshold to breach, so the sentinel triple is
    recorded, the severity comes from the sanctions status, and the breach tests never run.

    Design: Corner/calculations/alert_generation_unexpected_corridor_severity_from_sanctions_status
    """
    rid, profile = _calibrated()
    restricted_jurisdiction(
        jurisdiction_code="RU", name="Russia", basel_aml_index=6.0, corridor_risk_weight=1.5
    )

    observation = post_observation(
        profile["id"], "2026-07", "RU", aggregate_usd=900000.00, txn_count=400
    )

    assert observation["alerts_created_count"] == 1
    assert observation["usd_threshold_applied"] == 0.00
    assert observation["count_threshold_applied"] == 0
    assert observation["breach_ratio"] == 0.0000
    alerts = alerts_for(rid)
    assert [a["alert_type"] for a in alerts] == ["CORRIDOR_UNEXPECTED"]
    assert alerts[0]["severity"] == "HIGH"
    assert alerts[0]["breach_ratio"] is None


def test_alert_generation_nested_signal_uses_strict_greater_than(api):
    """Two observations straddle the one comparison in the calculation that is strict, and the
    respondent's nesting ban is what lifts the raised alert to the top severity.

    Design: Corner/calculations/alert_generation_nested_signal_uses_strict_greater_than
    """
    rid, profile = _calibrated(nested_activity_permitted=False)
    new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=1.2
    )
    add_nested(
        rid, "FR", downstream_institution_name="Petit Banque SA",
        discovery_source="QUESTIONNAIRE",
    )

    equal = post_observation(
        profile["id"], "2026-06", "DE", aggregate_usd=1000.00, txn_count=5,
        distinct_downstream_count=1,
    )
    over = post_observation(
        profile["id"], "2026-07", "DE", aggregate_usd=1000.00, txn_count=5,
        distinct_downstream_count=2,
    )

    assert equal["alerts_created_count"] == 0
    assert equal["breach_ratio"] == 0.0017
    assert over["alerts_created_count"] == 1
    alerts = alerts_for(rid)
    assert [a["alert_type"] for a in alerts] == ["NESTED_ACTIVITY_UNDISCLOSED"]
    assert alerts[0]["severity"] == "CRITICAL"

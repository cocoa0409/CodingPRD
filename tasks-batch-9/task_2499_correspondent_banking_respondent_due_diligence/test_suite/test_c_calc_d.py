"""Corner queue - section calculations, part D: rating override, nested rollups, calibration."""
from test_helpers import (
    add_nested,
    adjudicate_nested,
    calibrate,
    corridor,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    read_nested,
    read_respondent,
    score_respondent,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _fr(weight=1.2):
    return new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=weight
    )


def test_risk_rating_prohibited_override_beats_the_numeric_thresholds(api):
    """The residual lands in the medium band, so only the hard sanctions override can explain
    a prohibited rating, and the cascade's blocked posture survives the scoring run.

    Design: Corner/calculations/risk_rating_prohibited_override_beats_the_numeric_thresholds
    """
    profile = _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    validate_success(
        api.amend_jurisdiction_profile(
            profile["id"], {"sanctions_status": "COMPREHENSIVELY_SANCTIONED"}, ADMIN
        )
    )

    scored = score_respondent(respondent["id"], "REFRESH_FINAL")

    assert scored["inherent_risk_score"] == 36.00
    assert scored["residual_risk_score"] == 36.00
    assert scored["risk_rating"] == "PROHIBITED"
    assert scored["payment_posture"] == "BLOCKED"


def test_nested_chain_depth_walks_transitively_through_a_known_respondent(api):
    """The downstream institution is itself a respondent with a live edge, so the chain walk
    must extend past the naive depth of one while the far respondent's own row is unmoved.

    Design: Corner/calculations/nested_chain_depth_walks_transitively_through_a_known_respondent
    """
    _de()
    _fr()
    first = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    second = licensed_respondent(
        "DE", legal_name="Sudbank AG", swift_bic="SUEDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    leaf = add_nested(
        second["id"], "FR", downstream_institution_name="Petit Banque SA",
        discovery_source="QUESTIONNAIRE",
    )

    hop = validate_success(
        api.create_nested_relationship(
            first["id"],
            {"downstream_institution_name": "Sudbank AG", "downstream_jurisdiction_code": "DE",
             "relationship_type": "DOWNSTREAM_CORRESPONDENT",
             "discovery_source": "QUESTIONNAIRE",
             "downstream_respondent_bank_id": second["id"]},
            ANALYST,
        ),
        expected_status=201,
    )

    assert hop["depth"] == 2
    assert hop["state"] == "DISCLOSED"
    assert read_nested(leaf["id"])["depth"] == 1
    upstream = read_respondent(first["id"])
    assert upstream["max_nested_depth"] == 2
    assert upstream["nested_exposure_units"] == 2
    assert read_respondent(second["id"])["max_nested_depth"] == 1


def test_nested_prohibition_ladder_sanctioned_jurisdiction_wins_over_nesting_ban(api):
    """Two ladder rungs match at once, and first-match means only the earlier reason is ever
    written; the detected row is recorded rather than refused and contributes nothing.

    Design: Corner/calculations/nested_prohibition_ladder_sanctioned_jurisdiction_wins_over_nesting_ban
    """
    _de()
    new_jurisdiction(
        jurisdiction_code="SY", name="Syria", basel_aml_index=8.0, corridor_risk_weight=2.0,
        sanctions_status="COMPREHENSIVELY_SANCTIONED", nested_correspondent_prohibited=True,
    )
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )

    created = validate_success(
        api.create_nested_relationship(
            respondent["id"],
            {"downstream_institution_name": "Damascus Exchange House",
             "downstream_jurisdiction_code": "SY", "relationship_type": "NESTED_PSP",
             "discovery_source": "TRANSACTION_MONITORING"},
            ANALYST,
        ),
        expected_status=201,
    )

    assert created["state"] == "PROHIBITED"
    assert created["prohibition_reason"] == "SANCTIONED_JURISDICTION"
    stored = read_respondent(respondent["id"])
    assert stored["nested_exposure_units"] == 0
    assert stored["disclosed_nested_count"] == 0
    assert stored["undisclosed_nested_count"] == 0
    assert stored["max_nested_depth"] == 0


def test_nested_exposure_rollup_applies_one_weight_per_state(api):
    """Three depth-one rows sit in three different states at once, so the three distinct
    weights and the two differently-scoped counters are all exercised by one rollup.

    Design: Corner/calculations/nested_exposure_rollup_applies_one_weight_per_state
    """
    _de()
    _fr()
    new_jurisdiction(
        jurisdiction_code="IT", name="Italy", basel_aml_index=4.5, corridor_risk_weight=1.1
    )
    new_jurisdiction(
        jurisdiction_code="ES", name="Spain", basel_aml_index=4.2, corridor_risk_weight=1.05
    )
    rid = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        nested_activity_permitted=True,
    )["id"]
    disclosed = add_nested(
        rid, "FR", downstream_institution_name="Petit Banque SA",
        discovery_source="QUESTIONNAIRE",
    )
    undisclosed = add_nested(
        rid, "IT", downstream_institution_name="Banca Piccola SpA",
        discovery_source="TRANSACTION_MONITORING",
    )
    pending = add_nested(
        rid, "ES", downstream_institution_name="Banco Pequeno SA",
        discovery_source="QUESTIONNAIRE",
    )

    adjudicate_nested(pending["id"], "CONFIRM")

    assert read_nested(disclosed["id"])["state"] == "DISCLOSED"
    assert read_nested(undisclosed["id"])["state"] == "UNDISCLOSED_DETECTED"
    assert read_nested(pending["id"])["state"] == "CONFIRMED"
    stored = read_respondent(rid)
    assert stored["nested_exposure_units"] == 9
    assert stored["disclosed_nested_count"] == 2
    assert stored["undisclosed_nested_count"] == 1
    assert stored["max_nested_depth"] == 1


def test_monitoring_threshold_calibration_rounds_each_corridor_before_the_buffer(api):
    """Two corridors with different risk weights are each rounded on their own, and only the
    already-rounded sum is buffered, so the count that lands on .6 still rounds up.

    Design: Corner/calculations/monitoring_threshold_calibration_rounds_each_corridor_before_the_buffer
    """
    _de()
    _fr(weight=1.2)
    rid = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )["id"]
    assert score_respondent(rid, "ONBOARDING_PROVISIONAL")["risk_rating"] == "LOW"
    profile = open_profile(
        rid, [corridor("DE", 400000.00, 80), corridor("FR", 300000.00, 60)]
    )

    calibrated = calibrate(profile["id"])

    assert calibrated["calibration_state"] == "CALIBRATED"
    assert calibrated["tolerance_pct"] == 0.15
    thresholds = {row["jurisdiction_code"]: row for row in calibrated["corridor_thresholds"]}
    assert thresholds["DE"]["usd_threshold"] == 598000.00
    assert thresholds["DE"]["count_threshold"] == 120
    assert thresholds["FR"]["usd_threshold"] == 373750.00
    assert thresholds["FR"]["count_threshold"] == 75
    assert calibrated["aggregate_usd_threshold"] == 1068925.00
    assert calibrated["hold_threshold_usd"] == 106892.50


def test_monitoring_threshold_calibration_applies_usd_and_count_floors(api):
    """A corridor small enough to fall under both floors proves the aggregate is built from
    the floored dollar figure rather than the raw one.

    Design: Corner/calculations/monitoring_threshold_calibration_applies_usd_and_count_floors
    """
    _de()
    rid = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )["id"]
    assert score_respondent(rid, "ONBOARDING_PROVISIONAL")["risk_rating"] == "LOW"
    profile = open_profile(rid, [corridor("DE", 1000.00, 1)])

    calibrated = calibrate(profile["id"])

    thresholds = {row["jurisdiction_code"]: row for row in calibrated["corridor_thresholds"]}
    assert thresholds["DE"]["usd_threshold"] == 10000.00
    assert thresholds["DE"]["count_threshold"] == 5
    assert calibrated["aggregate_usd_threshold"] == 11000.00
    assert calibrated["hold_threshold_usd"] == 1100.00

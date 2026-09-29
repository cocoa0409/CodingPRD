"""Corner queue - section consistency_model: derived state is readable on the very next call."""
from test_helpers import (
    ANALYST_ID,
    ApiErrorId,
    assert_instant_equals,
    corridor,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    read_respondent,
    respondent_version,
    score_respondent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, OFFICER, RM

_DERIVED = (
    "calibration_state",
    "corridor_thresholds",
    "aggregate_usd_threshold",
    "hold_threshold_usd",
    "calibrated_at",
    "calibrated_by_user_id",
)


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_the_calibration_response_already_carries_every_derived_threshold(api):
    """A profile is born with an empty threshold array, so the before-picture is unambiguous: the
    200 body is already complete and a read issued by a different role in the very next request
    returns the same six fields, with the JP corridor proving the divisor is the corridor weight.

    Design: Corner/consistency_model/the_calibration_response_already_carries_every_derived_threshold
    """
    _de()
    new_jurisdiction(
        jurisdiction_code="JP", name="Japan", basel_aml_index=4.0, corridor_risk_weight=2.0
    )
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=100000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    assert score_respondent(rid, "ONBOARDING_PROVISIONAL")["risk_rating"] == "LOW"
    profile = open_profile(
        rid,
        [corridor("DE", 100000.00, 100), corridor("JP", 100000.00, 100)],
        tolerance_pct=0.15,
    )

    before = validate_success(api.get_monitoring_profile(profile["id"], RM))
    assert before["calibration_state"] == "PROVISIONAL"
    assert before["corridor_thresholds"] == []
    assert before["aggregate_usd_threshold"] is None
    assert before["hold_threshold_usd"] is None
    assert before["calibrated_at"] is None
    assert before["calibrated_by_user_id"] is None

    written = validate_success(
        api.calibrate_profile(profile["id"], {"action": "CALIBRATE"}, ANALYST)
    )
    assert written["calibration_state"] == "CALIBRATED"
    assert [row["jurisdiction_code"] for row in written["corridor_thresholds"]] == ["DE", "JP"]
    assert written["corridor_thresholds"][0]["usd_threshold"] == 149500.00
    assert written["corridor_thresholds"][0]["count_threshold"] == 150
    assert written["corridor_thresholds"][1]["usd_threshold"] == 74750.00
    assert written["corridor_thresholds"][1]["count_threshold"] == 75
    assert written["aggregate_usd_threshold"] == 246675.00
    assert written["hold_threshold_usd"] == 24667.50
    assert_instant_equals(written["calibrated_at"], "2026-08-01T00:00:00Z")
    assert written["calibrated_by_user_id"] == ANALYST_ID

    observed = validate_success(api.get_monitoring_profile(profile["id"], RM))
    for field in _DERIVED:
        assert observed[field] == written[field]


def test_an_observation_and_the_alerts_it_raises_are_visible_in_the_same_breath(api):
    """One write fans out into a different entity, so the counter in the 201 body must already
    equal the number of alert rows a differently-roled reader sees on the next request - with the
    strict nested test staying silent because the declared downstream count is not above zero.

    Design: Corner/consistency_model/an_observation_and_the_alerts_it_raises_are_visible_in_the_same_breath
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=100000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    assert score_respondent(rid, "ONBOARDING_PROVISIONAL")["risk_rating"] == "LOW"
    profile = open_profile(rid, [corridor("DE", 100000.00, 100)], tolerance_pct=0.15)
    calibrated = validate_success(
        api.calibrate_profile(profile["id"], {"action": "CALIBRATE"}, ANALYST)
    )
    assert calibrated["calibration_state"] == "CALIBRATED"
    assert calibrated["corridor_thresholds"][0]["usd_threshold"] == 149500.00
    assert calibrated["corridor_thresholds"][0]["count_threshold"] == 150

    _empty, empty_meta = validate_paginated(
        api.list_monitoring_alerts(OFFICER, params={"respondent_bank_id": rid})
    )
    assert empty_meta["total_count"] == 0

    observation = validate_success(
        api.create_observation(
            profile["id"],
            {"period_month": "2026-07", "corridor_jurisdiction_code": "DE",
             "aggregate_usd": 300000.00, "txn_count": 300, "distinct_downstream_count": 0},
            ANALYST,
        ),
        expected_status=201,
    )
    assert observation["usd_threshold_applied"] == 149500.00
    assert observation["count_threshold_applied"] == 150
    assert observation["breach_ratio"] == 2.0067
    assert observation["alerts_created_count"] == 2

    rows, meta = validate_paginated(
        api.list_monitoring_alerts(
            OFFICER, params={"activity_observation_id": observation["id"]}
        )
    )
    assert meta["total_count"] == 2
    by_type = {row["alert_type"]: row for row in rows}
    assert sorted(by_type) == ["COUNT_BREACH", "VOLUME_BREACH"]
    assert by_type["VOLUME_BREACH"]["severity"] == "HIGH"
    assert by_type["VOLUME_BREACH"]["breach_ratio"] == 2.0067
    assert by_type["COUNT_BREACH"]["severity"] == "HIGH"
    assert by_type["COUNT_BREACH"]["breach_ratio"] is None
    for row in rows:
        assert row["state"] == "OPEN"
        assert row["respondent_bank_id"] == rid
        assert row["activity_observation_id"] == observation["id"]

    _all_rows, all_meta = validate_paginated(
        api.list_monitoring_alerts(
            OFFICER,
            params={"respondent_bank_id": rid, "alert_type": "NESTED_ACTIVITY_UNDISCLOSED"},
        )
    )
    assert all_meta["total_count"] == 0


def test_the_parent_version_bump_is_visible_to_the_very_next_writer(api):
    """The concurrency token is only sound if the increment lands before the next request is
    served, so a token that was valid one call earlier must be refused at once and the refreshed
    token must succeed at once - one write, exactly one increment, no settling period.

    Design: Corner/consistency_model/the_parent_version_bump_is_visible_to_the_very_next_writer
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=100000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    assert respondent["license_status"] == "ACTIVE"
    v0 = respondent_version(rid)

    profile = validate_success(
        api.create_monitoring_profile(
            rid,
            {"effective_from": "2026-01-01T00:00:00Z",
             "effective_to": "2026-12-31T00:00:00Z",
             "tolerance_pct": 0.15,
             "expected_corridors": [corridor("DE", 100000.00, 100)],
             "expected_respondent_version": v0},
            ANALYST,
        ),
        expected_status=201,
    )
    assert profile["calibration_state"] == "PROVISIONAL"
    v1 = respondent_version(rid)
    assert v1 == v0 + 1

    replayed = api.create_questionnaire(
        rid, {"questionnaire_version": "2026.1", "expected_respondent_version": v0}, ANALYST
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_RESPONDENT_VERSION, expected_status=412)
    _rows, empty = validate_paginated(
        api.list_questionnaires(ANALYST, params={"respondent_bank_id": rid})
    )
    assert empty["total_count"] == 0

    accepted = validate_success(
        api.create_questionnaire(
            rid, {"questionnaire_version": "2026.1", "expected_respondent_version": v1}, ANALYST
        ),
        expected_status=201,
    )
    assert accepted["state"] == "DRAFT"
    assert accepted["clarification_rounds"] == 0
    assert read_respondent(rid)["version"] == v0 + 2

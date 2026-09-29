"""Corner queue - section cross_cutting_complexity_layers, part A: optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    corridor,
    licensed_respondent,
    new_jurisdiction,
    read_respondent,
    respondent_version,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _questionnaire(expected_version):
    return {"questionnaire_version": "2026.1", "expected_respondent_version": expected_version}


def test_occ_questionnaire_create_rejects_a_stale_respondent_version(api):
    """The concurrency token is a strict per-write monotone, so the create that succeeds also
    invalidates the very token it consumed and a second create must re-read in between.

    Design: Corner/cross_cutting_complexity_layers/occ_questionnaire_create_rejects_a_stale_respondent_version
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    version_held = respondent_version(rid)

    validate_success(api.amend_respondent(rid, {"legal_name": "Nordbank AG (Frankfurt)"}, RM))
    version_fresh = respondent_version(rid)
    assert version_fresh == version_held + 1

    stale = api.create_questionnaire(rid, _questionnaire(version_held), ANALYST)
    validate_error(stale, ApiErrorId.ERR_STALE_RESPONDENT_VERSION, expected_status=412)
    _rows, empty = validate_paginated(
        api.list_questionnaires(ANALYST, params={"respondent_bank_id": rid})
    )
    assert empty["total_count"] == 0

    first = validate_success(
        api.create_questionnaire(rid, _questionnaire(version_fresh), ANALYST),
        expected_status=201,
    )
    assert first["state"] == "DRAFT"
    version_after = respondent_version(rid)
    assert version_after == version_fresh + 1

    reused = api.create_questionnaire(rid, _questionnaire(version_fresh), ANALYST)
    validate_error(reused, ApiErrorId.ERR_STALE_RESPONDENT_VERSION, expected_status=412)
    _rows, single = validate_paginated(
        api.list_questionnaires(ANALYST, params={"respondent_bank_id": rid})
    )
    assert single["total_count"] == 1

    second = validate_success(
        api.create_questionnaire(rid, _questionnaire(version_after), ANALYST),
        expected_status=201,
    )
    assert second["state"] == "DRAFT"
    assert validate_success(
        api.get_questionnaire(first["id"], ANALYST)
    )["state"] == "SUPERSEDED"


def _profile(effective_from, effective_to, expected_version):
    return {
        "effective_from": effective_from,
        "effective_to": effective_to,
        "expected_corridors": [corridor("DE", 500000.00, 100)],
        "expected_respondent_version": expected_version,
    }


def test_occ_monitoring_profile_create_beats_the_interval_overlap_check(api):
    """A writer that is both out of date and proposing a taken interval is told its view is
    stale, because the profile calibrates against the live rating - and once the token is fresh
    the identical interval fails on the interval rule instead.

    Design: Corner/cross_cutting_complexity_layers/occ_monitoring_profile_create_beats_the_interval_overlap_check
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    version_one = respondent_version(rid)
    existing = validate_success(
        api.create_monitoring_profile(
            rid,
            _profile("2026-01-01T00:00:00Z", "2026-06-30T23:59:59Z", version_one),
            ANALYST,
        ),
        expected_status=201,
    )
    assert existing["calibration_state"] == "PROVISIONAL"
    version_two = respondent_version(rid)
    assert version_two == version_one + 1

    stale_and_overlapping = api.create_monitoring_profile(
        rid, _profile("2026-03-01T00:00:00Z", "2026-09-30T23:59:59Z", version_one), ANALYST
    )
    validate_error(
        stale_and_overlapping, ApiErrorId.ERR_STALE_RESPONDENT_VERSION, expected_status=412
    )

    fresh_but_overlapping = api.create_monitoring_profile(
        rid, _profile("2026-03-01T00:00:00Z", "2026-09-30T23:59:59Z", version_two), ANALYST
    )
    validate_error(
        fresh_but_overlapping, ApiErrorId.ERR_MONITORING_INTERVAL_OVERLAP, expected_status=409
    )
    assert respondent_version(rid) == version_two

    disjoint = validate_success(
        api.create_monitoring_profile(
            rid,
            _profile("2026-07-01T00:00:00Z", "2026-12-31T23:59:59Z", version_two),
            ANALYST,
        ),
        expected_status=201,
    )
    assert disjoint["calibration_state"] == "PROVISIONAL"

    rows, meta = validate_paginated(
        api.list_monitoring_profiles(ANALYST, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [existing["id"], disjoint["id"]]
    assert read_respondent(rid)["version"] == version_two + 1

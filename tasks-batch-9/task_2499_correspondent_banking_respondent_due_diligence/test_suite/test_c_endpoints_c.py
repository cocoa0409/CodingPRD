"""Corner queue - section endpoints, part C: the computed chain read and two action endpoints."""
from test_helpers import (
    ANALYST_ID,
    add_nested,
    assert_instant_equals,
    calibrate,
    corridor,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    read_nested,
    read_respondent,
    respondent_version,
    score_respondent,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, OFFICER, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_nested_chain_computed_read_expands_through_a_known_respondent(api):
    """The chain read is the only place the edges of another respondent are surfaced, and its
    filter and window apply to the expanded result rather than to the directly owned rows.

    Design: Corner/endpoints/nested_chain_computed_read_expands_through_a_known_respondent
    """
    _de()
    new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=1.2
    )
    upstream = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    downstream = licensed_respondent(
        "DE", legal_name="Sudbank AG", swift_bic="SUEDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    leaf = add_nested(
        downstream["id"], "FR", downstream_institution_name="Banque Leaf",
        discovery_source="QUESTIONNAIRE",
    )
    hop = add_nested(
        upstream["id"], "DE", downstream_institution_name="Sudbank AG",
        discovery_source="QUESTIONNAIRE", downstream_respondent_bank_id=downstream["id"],
    )
    assert leaf["depth"] == 1
    assert hop["depth"] == 2
    version_before = respondent_version(upstream["id"])

    rows, meta = validate_paginated(api.get_nested_chain(upstream["id"], ANALYST))
    assert [row["id"] for row in rows] == [leaf["id"], hop["id"]]
    assert [row["depth"] for row in rows] == [1, 2]
    assert meta["total_count"] == 2

    filtered, filtered_meta = validate_paginated(
        api.get_nested_chain(
            upstream["id"], RM, params={"state": "DISCLOSED", "limit": 1, "offset": 0}
        )
    )
    assert [row["id"] for row in filtered] == [leaf["id"]]
    assert filtered_meta["total_count"] == 2
    assert filtered_meta["has_more"] is True

    own_rows, own_meta = validate_paginated(api.get_nested_chain(downstream["id"], ANALYST))
    assert [row["id"] for row in own_rows] == [leaf["id"]]
    assert own_rows[0]["depth"] == 1
    assert own_meta["total_count"] == 1

    assert read_nested(hop["id"])["depth"] == 2
    assert respondent_version(upstream["id"]) == version_before


def test_calibration_require_recalibration_keeps_the_existing_thresholds(api):
    """Marking the thresholds stale is not the same as erasing them: the whole calibrated
    triple and its audit stamp survive the state change untouched.

    Design: Corner/endpoints/calibration_require_recalibration_keeps_the_existing_thresholds
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    assert score_respondent(respondent["id"], "ONBOARDING_PROVISIONAL")["risk_rating"] == "LOW"
    profile = open_profile(respondent["id"], [corridor("DE", 400000.00, 80)])
    calibrated = calibrate(profile["id"])
    assert calibrated["aggregate_usd_threshold"] == 657800.00

    validate_success(
        api.calibrate_profile(
            profile["id"],
            {"action": "REQUIRE_RECALIBRATION", "recalibration_reason": "OFFICER_ACTION"},
            ANALYST,
        )
    )

    stored = validate_success(api.get_monitoring_profile(profile["id"], OFFICER))
    assert stored["calibration_state"] == "RECALIBRATION_REQUIRED"
    assert stored["recalibration_reason"] == "OFFICER_ACTION"
    thresholds = {row["jurisdiction_code"]: row for row in stored["corridor_thresholds"]}
    assert thresholds["DE"]["usd_threshold"] == 598000.00
    assert thresholds["DE"]["count_threshold"] == 120
    assert stored["aggregate_usd_threshold"] == 657800.00
    assert stored["hold_threshold_usd"] == 65780.00
    assert_instant_equals(stored["calibrated_at"], "2026-08-01T00:00:00Z")
    assert stored["calibrated_by_user_id"] == ANALYST_ID


def test_beneficial_owner_verification_updates_the_respondent_rollup(api):
    """One verification is enough to cross the ownership threshold, and the paired rejection
    proves a rejected stake contributes nothing to the verified percentage.

    Design: Corner/endpoints/beneficial_owner_verification_updates_the_respondent_rollup
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    main = validate_success(
        api.create_beneficial_owner(
            rid,
            {"owner_name": "Anna Weber", "owner_type": "NATURAL_PERSON",
             "ownership_pct": 80.00, "country_of_residence": "DE"},
            ANALYST,
        ),
        expected_status=201,
    )
    side = validate_success(
        api.create_beneficial_owner(
            rid,
            {"owner_name": "Boris Klein", "owner_type": "NATURAL_PERSON",
             "ownership_pct": 15.00, "country_of_residence": "DE"},
            ANALYST,
        ),
        expected_status=201,
    )

    verified = validate_success(api.verify_owner(main["id"], {"action": "VERIFY"}, ANALYST))
    rejected = validate_success(
        api.verify_owner(
            side["id"], {"action": "REJECT", "rejection_reason": "DOCUMENT_MISSING"}, ANALYST
        )
    )

    assert verified["verification_status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == ANALYST_ID
    assert rejected["verification_status"] == "REJECTED"
    assert rejected["rejection_reason"] == "DOCUMENT_MISSING"

    rolled_up = read_respondent(rid)
    assert rolled_up["verified_ownership_pct"] == 80.00
    assert rolled_up["ownership_verified"] is True

    rows, meta = validate_paginated(
        api.list_beneficial_owners(
            ANALYST, params={"respondent_bank_id": rid, "verification_status": "VERIFIED"}
        )
    )
    assert [row["id"] for row in rows] == [main["id"]]
    assert meta["total_count"] == 1

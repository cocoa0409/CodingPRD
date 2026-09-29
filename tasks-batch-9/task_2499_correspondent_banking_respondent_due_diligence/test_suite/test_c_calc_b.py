"""Corner queue - section calculations, part B: rollup boundary and control-score caps."""
from test_helpers import (
    CONTROL_DOMAIN_ORDER,
    add_control_rows,
    add_owner,
    licensed_respondent,
    new_jurisdiction,
    new_respondent,
    open_questionnaire,
    overlay_row,
    read_respondent,
    submit_questionnaire,
    validate_success,
    verify_owner,
)
from test_helpers.fixtures import ANALYST, ANALYST_ID


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _respondent():
    _de()
    return new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def _submitted(self_rating=5):
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    questionnaire = open_questionnaire(rid)
    rows = add_control_rows(
        questionnaire["id"], rid, {d: self_rating for d in CONTROL_DOMAIN_ORDER}
    )
    submit_questionnaire(questionnaire["id"], rid)
    return rid, questionnaire, rows


def test_ownership_rollup_stays_unverified_at_seventy_four_point_nine_nine(api):
    """One hundredth of a percent below the threshold is still below it, so the exclusive
    side of the same boundary leaves the respondent unverified.

    Design: Corner/calculations/ownership_rollup_stays_unverified_at_seventy_four_point_nine_nine
    """
    rid = _respondent()["id"]
    first = add_owner(rid, "DE", owner_name="Anna Weber", ownership_pct=40.00)
    second = add_owner(rid, "DE", owner_name="Bernd Klein", ownership_pct=34.99)
    verify_owner(first["id"])

    validate_success(api.verify_owner(second["id"], {"action": "VERIFY"}, ANALYST))

    respondent = read_respondent(rid)
    assert respondent["verified_ownership_pct"] == 74.99
    assert respondent["ownership_verified"] is False


def test_ownership_rollup_incomplete_control_chain_blocks_verification(api):
    """The percentage test alone is not sufficient: a verified corporate holder of a
    controlling stake with no verified layer beneath it leaves the chain incomplete.

    Design: Corner/calculations/ownership_rollup_incomplete_control_chain_blocks_verification
    """
    rid = _respondent()["id"]
    root = add_owner(
        rid, "DE", owner_name="Holdco GmbH", owner_type="LEGAL_ENTITY", ownership_pct=80.00
    )
    child = add_owner(
        rid, "DE", owner_name="Anna Weber", ownership_pct=30.00, parent_owner_id=root["id"]
    )

    validate_success(api.verify_owner(root["id"], {"action": "VERIFY"}, ANALYST))

    assert validate_success(
        api.get_beneficial_owner(root["id"], ANALYST)
    )["verification_status"] == "VERIFIED"
    assert validate_success(
        api.get_beneficial_owner(child["id"], ANALYST)
    )["verification_status"] == "PENDING"
    respondent = read_respondent(rid)
    assert respondent["verified_ownership_pct"] == 80.00
    assert respondent["ownership_verified"] is False


def test_control_score_uniform_ratings_prove_weights_sum_to_one(api):
    """The eight weights sum to exactly one, so a uniform rating scales straight to the
    score, and the assessment mirrors that value onto the respondent.

    Design: Corner/calculations/control_score_uniform_ratings_prove_weights_sum_to_one
    """
    rid, questionnaire, _rows = _submitted(self_rating=4)

    assessed = validate_success(
        api.decide_assessment(
            questionnaire["id"],
            {"action": "ASSESS", "variant": "ONBOARDING_PROVISIONAL"},
            ANALYST,
        )
    )

    assert assessed["state"] == "ASSESSED"
    assert assessed["computed_control_score"] == 80.00
    assert assessed["control_score_variant"] == "ONBOARDING_PROVISIONAL"
    assert assessed["assessed_by_user_id"] == ANALYST_ID
    assert read_respondent(rid)["control_score"] == 80.00


def test_control_score_critical_gap_cap_applied_after_rounding(api):
    """A single critical gap clamps a perfect raw score, and the critical branch of the
    ladder wins outright even with no major rows anywhere.

    Design: Corner/calculations/control_score_critical_gap_cap_applied_after_rounding
    """
    rid, questionnaire, rows = _submitted(self_rating=5)
    governance = overlay_row(rows["GOVERNANCE"]["id"], gap_severity="CRITICAL")
    assert governance["remediation_required"] is True

    assessed = validate_success(
        api.decide_assessment(
            questionnaire["id"],
            {"action": "ASSESS", "variant": "ONBOARDING_PROVISIONAL"},
            ANALYST,
        )
    )

    assert assessed["computed_control_score"] == 40.00
    assert read_respondent(rid)["control_score"] == 40.00


def test_control_score_single_major_gap_caps_at_seventy_five(api):
    """With exactly one major gap and no critical one the ladder's third branch applies, so
    the perfect raw score is clamped to the looser of the three ceilings.

    Design: Corner/calculations/control_score_single_major_gap_caps_at_seventy_five
    """
    _rid, questionnaire, rows = _submitted(self_rating=5)
    overlay_row(rows["GOVERNANCE"]["id"], gap_severity="MAJOR")

    assessed = validate_success(
        api.decide_assessment(
            questionnaire["id"],
            {"action": "ASSESS", "variant": "ONBOARDING_PROVISIONAL"},
            ANALYST,
        )
    )

    assert assessed["computed_control_score"] == 75.00


def test_control_score_provisional_variant_credits_analyst_rating_over_self_rating(api):
    """Under the onboarding variant a present analyst rating displaces the self rating on
    that domain alone, so the lightest-weighted domain moves the score by three of its weight.

    Design: Corner/calculations/control_score_provisional_variant_credits_analyst_rating_over_self_rating
    """
    _rid, questionnaire, rows = _submitted(self_rating=5)
    governance = overlay_row(rows["GOVERNANCE"]["id"], assessed_rating=2)
    assert governance["gap_severity"] == "NONE"

    assessed = validate_success(
        api.decide_assessment(
            questionnaire["id"],
            {"action": "ASSESS", "variant": "ONBOARDING_PROVISIONAL"},
            ANALYST,
        )
    )

    assert assessed["state"] == "ASSESSED"
    assert assessed["computed_control_score"] == 94.00

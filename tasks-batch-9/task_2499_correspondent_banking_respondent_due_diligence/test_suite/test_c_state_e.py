"""Corner queue - section state_machines, part E: rollups, compensation and approval effects."""
from test_helpers import (
    CONTROL_DOMAIN_ORDER,
    add_nested,
    add_owner,
    adjudicate_nested,
    assert_instant_equals,
    assessed_questionnaire,
    committee_decision,
    licensed_respondent,
    new_jurisdiction,
    new_respondent,
    read_nested,
    read_respondent,
    score_respondent,
    validate_success,
    verify_owner,
)
from test_helpers.fixtures import ANALYST, COMMITTEE_ID, OFFICER


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _nesting_respondent():
    _de()
    new_jurisdiction(
        jurisdiction_code="FR", name="France", basel_aml_index=5.0, corridor_risk_weight=1.2
    )
    return new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
        nested_activity_permitted=True,
    )


def test_bubble_up_owner_verification_flips_ownership_verified_true(api):
    """Two direct stakes of 40.00 and 35.00 land exactly on the inclusive 75.00 threshold,
    so the second verification is the request that flips the parent respondent's flag.

    Design: Corner/state_machines/bubble_up_owner_verification_flips_ownership_verified_true
    """
    _de()
    respondent = new_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    first = add_owner(rid, "DE", owner_name="Anna Weber", ownership_pct=40.00)
    second = add_owner(rid, "DE", owner_name="Bernd Klein", ownership_pct=35.00)
    verify_owner(first["id"])

    before = read_respondent(rid)
    assert before["verified_ownership_pct"] == 40.00
    assert before["ownership_verified"] is False

    validate_success(api.verify_owner(second["id"], {"action": "VERIFY"}, ANALYST))

    after = read_respondent(rid)
    assert after["verified_ownership_pct"] == 75.00
    assert after["control_chain_complete"] is True
    assert after["ownership_verified"] is True


def test_ledger_sync_nested_exposure_units_rise_on_confirm(api):
    """The one depth-1 row's state weight moves from 1 to 3, so the ancestor's exposure
    reconciles to exactly 3 while the disclosed count and the depth are unmoved.

    Design: Corner/state_machines/ledger_sync_nested_exposure_units_rise_on_confirm
    """
    rid = _nesting_respondent()["id"]
    row = add_nested(
        rid, "FR", downstream_institution_name="Petit Banque SA",
        relationship_type="DOWNSTREAM_CORRESPONDENT", discovery_source="QUESTIONNAIRE",
    )

    before = read_respondent(rid)
    assert before["nested_exposure_units"] == 1

    validate_success(api.adjudicate_nested(row["id"], {"action": "CONFIRM"}, OFFICER))

    after = read_respondent(rid)
    assert after["nested_exposure_units"] == 3
    assert after["disclosed_nested_count"] == 1
    assert after["max_nested_depth"] == 1


def test_compensation_nested_revert_restores_exposure_units_exactly(api):
    """Reverting is the exact inverse of confirming: the exposure returns to 1 with no
    residue, and the row is back in the disclosed population rather than a third state.

    Design: Corner/state_machines/compensation_nested_revert_restores_exposure_units_exactly
    """
    rid = _nesting_respondent()["id"]
    row = add_nested(
        rid, "FR", downstream_institution_name="Petit Banque SA",
        relationship_type="DOWNSTREAM_CORRESPONDENT", discovery_source="QUESTIONNAIRE",
    )
    adjudicate_nested(row["id"], "CONFIRM")
    assert read_respondent(rid)["nested_exposure_units"] == 3

    validate_success(api.adjudicate_nested(row["id"], {"action": "REVERT"}, ANALYST))

    assert read_nested(row["id"])["state"] == "DISCLOSED"
    after = read_respondent(rid)
    assert after["nested_exposure_units"] == 1
    assert after["disclosed_nested_count"] == 1
    assert after["undisclosed_nested_count"] == 0


def test_side_effect_execution_approval_writes_refresh_date_and_opens_posture(api):
    """Every declared side effect of the committee approval fires in one request: the frozen
    rating, the approver, the approval stamp, the 36-month LOW cadence and the open posture.

    Design: Corner/state_machines/side_effect_execution_approval_writes_refresh_date_and_opens_posture
    """
    _de()
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    owner = add_owner(rid, "DE", owner_name="Anna Weber", ownership_pct=80.00)
    verify_owner(owner["id"])
    assessed_questionnaire(
        rid, "ONBOARDING_PROVISIONAL", self_ratings={d: 4 for d in CONTROL_DOMAIN_ORDER}
    )
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["control_score"] == 80.00
    assert scored["control_credit"] == 0.3375
    assert scored["inherent_risk_score"] == 10.00
    assert scored["residual_risk_score"] == 6.63
    assert scored["dd_state"] == "PENDING_COMMITTEE"

    approved = committee_decision(rid, "APPROVE", decision_note="Committee approved")

    assert approved["dd_state"] == "APPROVED"
    assert approved["risk_rating"] == "LOW"
    assert approved["approved_risk_rating"] == "LOW"
    assert approved["approved_by_user_id"] == COMMITTEE_ID
    assert_instant_equals(approved["last_approved_at"], "2026-08-01T00:00:00Z")
    assert_instant_equals(approved["refresh_due_date"], "2029-08-01T00:00:00Z")
    assert approved["payment_posture"] == "OPEN"

"""Corner queue - section calculations, part G: payment screening ladder branches."""
from test_helpers import (
    calibrate,
    corridor,
    new_jurisdiction,
    open_profile,
    read_respondent,
    setup_approved_respondent,
    submit_payment,
    verify_licensing,
)


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def test_payment_screening_without_a_calibrated_profile_stops_at_received(api):
    """With no covering calibrated profile the ladder short-circuits before the posture branch
    that would otherwise have held the instruction, and no threshold is ever consulted.

    Design: Corner/calculations/payment_screening_without_a_calibrated_profile_stops_at_received
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    verify_licensing(rid, license_status="SUSPENDED", regulator_standing="GOOD_STANDING")
    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "RESTRICTED"
    assert respondent["restriction_reason"] == "LICENSE_LAPSE"
    assert respondent["payment_posture"] == "SCREEN_ONLY"

    instruction = submit_payment(
        rid, "DE", "DE", amount_usd=900000.00, purpose_code="TRADE_SETTLEMENT"
    )

    assert instruction["screening_state"] == "RECEIVED"
    assert instruction["hold_reason"] is None


def test_payment_screening_hold_threshold_is_inclusive_to_the_cent(api):
    """A cent either side of the derived hold threshold separates a hold from a clear, and only
    the holding branch and the clearing branch differ in what they write.

    Design: Corner/calculations/payment_screening_hold_threshold_is_inclusive_to_the_cent
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "APPROVED"
    assert respondent["payment_posture"] == "OPEN"
    profile = open_profile(rid, [corridor("DE", 400000.00, 80)])
    calibrated = calibrate(profile["id"])
    assert calibrated["hold_threshold_usd"] == 65780.00

    at_threshold = submit_payment(
        rid, "DE", "DE", amount_usd=65780.00, purpose_code="TRADE_SETTLEMENT"
    )
    under_threshold = submit_payment(
        rid, "DE", "DE", amount_usd=65779.99, purpose_code="TRADE_SETTLEMENT"
    )

    assert at_threshold["screening_state"] == "HELD_FOR_REVIEW"
    assert at_threshold["hold_reason"] == "AMOUNT_THRESHOLD"
    assert at_threshold["hold_threshold_applied"] == 65780.00
    assert under_threshold["screening_state"] == "SCREENED_CLEAR"
    assert under_threshold["hold_reason"] is None

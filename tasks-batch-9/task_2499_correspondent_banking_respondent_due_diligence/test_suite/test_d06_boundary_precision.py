"""Difficulty queue - rule boundary_precision_check.

Two inclusive boundaries on two different metrics: the monetary hold threshold of the
screening ladder and the temporal `due_at` instant of overdue marking, each probed at
the exact edge and one unit below it.
"""
from test_helpers import (
    ApiErrorId,
    add_control_rows,
    add_owner,
    add_verified_owner,
    assert_instant_equals,
    calibrate,
    committee_decision,
    corridor,
    dispatch_request,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    open_questionnaire,
    raise_request,
    read_request,
    read_profile,
    read_respondent,
    score_respondent,
    set_clock,
    submit_questionnaire,
    validate_error,
    validate_success,
    verify_owner,
)
from test_helpers.fixtures import ANALYST, assess_questionnaire


DOMAINS = [
    "GOVERNANCE", "KYC_ONBOARDING", "TRANSACTION_MONITORING", "SANCTIONS_SCREENING",
    "PEP_HANDLING", "TRAINING", "AUDIT", "NESTED_CONTROLS",
]


def _flat_score(rid, rating):
    questionnaire = open_questionnaire(rid, version="V1")
    add_control_rows(questionnaire["id"], rid, {d: rating for d in DOMAINS})
    submit_questionnaire(questionnaire["id"], rid)
    assess_questionnaire(questionnaire["id"], "ONBOARDING_PROVISIONAL")
    return score_respondent(rid, "ONBOARDING_PROVISIONAL")


def _hold_threshold_scenario():
    """Approved LOW respondent whose single calibrated profile derives a
    hold_threshold_usd of exactly 786500.00."""
    code = new_jurisdiction(
        name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.00,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    respondent = licensed_respondent(
        code, legal_name="Koeln Handelsbank AG", expected_monthly_volume_usd=5000000.00,
        expected_monthly_count=200,
    )
    rid = respondent["id"]
    add_verified_owner(rid, code, owner_name="Koeln Holding", ownership_pct=80.00)
    scored = _flat_score(rid, 4)
    assert scored["residual_risk_score"] == 9.28
    assert scored["risk_rating"] == "LOW"
    committee_decision(rid, "APPROVE")
    assert read_respondent(rid)["payment_posture"] == "OPEN"

    profile = open_profile(
        rid, [corridor(code, 5000000.00, 200)], tolerance_pct=0.10,
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z",
    )
    calibrate(profile["id"])
    return code, rid, profile


def _submission(code, amount):
    return {
        "ordering_jurisdiction_code": code,
        "beneficiary_jurisdiction_code": code,
        "amount_usd": amount,
        "purpose_code": "TRADE_SETTLEMENT",
        "involves_nested_party": False,
    }


def test_payment_hold_threshold_is_inclusive_at_the_exact_cent(api, rm_headers):
    """The three-step derivation - per-corridor rounding, the 1.10 aggregate buffer, then
    a divide by ten - lands on exactly 786500.00, and an instruction for that same figure
    is held because the comparison is `>=`, not `>`.

    Design: Difficulty/boundary_precision_check/payment_hold_threshold_is_inclusive_at_the_exact_cent_and_one_cent_below_screens_clear
    """
    code, rid, profile = _hold_threshold_scenario()
    calibrated = read_profile(profile["id"])
    assert calibrated["aggregate_usd_threshold"] == 7865000.00
    assert calibrated["hold_threshold_usd"] == 786500.00

    payment = validate_success(
        api.create_payment_instruction(rid, _submission(code, 786500.00), rm_headers),
        expected_status=201,
    )

    assert payment["screening_state"] == "HELD_FOR_REVIEW"
    assert payment["hold_reason"] == "AMOUNT_THRESHOLD"
    assert payment["hold_threshold_applied"] == 786500.00


def test_one_cent_below_the_hold_threshold_screens_clear(api, rm_headers):
    """786499.99 takes the final else branch of the ladder: SCREENED_CLEAR with a null
    hold_reason, and the create does not narrow the posture, so the posture branch never
    shadowed the amount branch on either instruction.

    Design: Difficulty/boundary_precision_check/payment_hold_threshold_is_inclusive_at_the_exact_cent_and_one_cent_below_screens_clear
    """
    code, rid, profile = _hold_threshold_scenario()

    payment = validate_success(
        api.create_payment_instruction(rid, _submission(code, 786499.99), rm_headers),
        expected_status=201,
    )

    assert payment["screening_state"] == "SCREENED_CLEAR"
    assert payment["hold_reason"] is None
    assert payment["amount_usd"] == 786499.99
    assert read_respondent(rid)["payment_posture"] == "OPEN"


def _risk_compressed_request():
    """HIGH-rated respondent with one MEDIUM information request dispatched at the
    default clock, so the single RISK_COMPRESSION gives sla_hours 84."""
    code = new_jurisdiction(
        name="Panama", basel_aml_index=8.0, sanctions_status="PERMITTED",
        fatf_listing="CALL_FOR_ACTION", secrecy_flag=True, corridor_risk_weight=1.50,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    respondent = licensed_respondent(
        code, legal_name="Panama Trade Bank SA", expected_monthly_volume_usd=50000000.00,
        expected_monthly_count=400,
    )
    rid = respondent["id"]
    owner = add_owner(rid, code, owner_name="Pep Majority Holder", ownership_pct=80.00,
                      is_pep=True)
    verify_owner(owner["id"])
    scored = _flat_score(rid, 1)
    assert scored["control_score"] == 20.00
    assert scored["control_credit"] == 0.0000  # the credit is 0 at or below 20.00
    assert scored["inherent_risk_score"] == 51.00  # 31.00 + min(24, 10) + 0 + min(16, 10)
    assert scored["residual_risk_score"] == 51.00
    assert scored["risk_rating"] == "HIGH"
    committee_decision(rid, "APPROVE")

    request = raise_request(rid, request_topic="ACTIVITY_EXPLANATION", severity="MEDIUM")
    dispatch_request(request["id"])
    return rid, request


def test_overdue_marking_one_second_before_due_at_is_refused(api):
    """168 base hours for MEDIUM are halved once by the HIGH rating and not twice - zero
    strikes disarm the second compression and the 12-hour floor is inert - so due_at is
    2026-08-04T12:00:00Z and a clock one second short writes no strike.

    Design: Difficulty/boundary_precision_check/rfi_overdue_marking_is_inclusive_at_the_risk_compressed_due_at_instant
    """
    rid, request = _risk_compressed_request()
    sent = read_request(request["id"])
    assert sent["state"] == "SENT"
    assert sent["sla_hours"] == 84  # a double compression would give 42, none 168
    assert_instant_equals(sent["dispatched_at"], "2026-08-01T00:00:00Z")
    assert_instant_equals(sent["due_at"], "2026-08-04T12:00:00Z")

    set_clock("2026-08-04T11:59:59Z")
    response = api.mark_overdue(request["id"], {"action": "MARK_OVERDUE"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_RFI_NOT_YET_OVERDUE)

    assert read_request(request["id"])["state"] == "SENT"
    assert read_respondent(rid)["unresponsive_strikes"] == 0


def test_overdue_marking_at_exactly_due_at_succeeds_and_adds_one_strike(api):
    """The comparison is clock >= due_at, so the instant itself is overdue; the marking
    adds exactly one strike, which stays below the inclusive restriction threshold of 3.

    Design: Difficulty/boundary_precision_check/rfi_overdue_marking_is_inclusive_at_the_risk_compressed_due_at_instant
    """
    rid, request = _risk_compressed_request()
    set_clock("2026-08-04T11:59:59Z")
    validate_error(
        api.mark_overdue(request["id"], {"action": "MARK_OVERDUE"}, ANALYST),
        ApiErrorId.ERR_RFI_NOT_YET_OVERDUE,
    )

    set_clock("2026-08-04T12:00:00Z")
    marked = validate_success(
        api.mark_overdue(request["id"], {"action": "MARK_OVERDUE"}, ANALYST)
    )

    assert marked["state"] == "OVERDUE"
    respondent = read_respondent(rid)
    assert respondent["unresponsive_strikes"] == 1  # only the successful marking counted
    assert respondent["dd_state"] == "APPROVED"  # 1 is below the inclusive threshold of 3

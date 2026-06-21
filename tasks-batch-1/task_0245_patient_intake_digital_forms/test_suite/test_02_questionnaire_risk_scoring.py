"""Medical-history questionnaire risk scoring and lifecycle (PRD §3.8).

Covers provisional-vs-final score divergence, the FLAGGED branch on high risk,
the revise cycle that clears the final score, the incompleteness guard, and the
high-risk waive block.
"""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    fixtures,
)

FRONT = TEST_USERS["front_desk_headers"]
PATIENT = TEST_USERS["patient_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def test_provisional_sum_then_weighted_final_flags(api):
    """PRD §3.8: "On submit, the `provisional_risk_score` is computed as the plain
    sum of the `risk_weight` values across all `answered_sections`."
    PRD §3.8: "each answered section contributes its `risk_weight` multiplied by a
    factor of 2 when its `section_key` is one of the provider's
    `questionnaire_required_sections`, and multiplied by 1 otherwise; the weighted
    sum is rounded half up to an integer."

    Design: Difficulty/dual_variant_calc/questionnaire_provisional_vs_final_diverge
    """
    clinic = fixtures.create_clinic(name="C2", form_expiration_hours=72)
    provider = fixtures.create_provider(
        clinic["id"], questionnaire_required_sections=["ALLERGIES", "MEDICATIONS", "HISTORY"]
    )
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])

    qr = fixtures.create_questionnaire(session["id"], answered_sections=[
        {"section_key": "ALLERGIES", "risk_weight": 4},
        {"section_key": "MEDICATIONS", "risk_weight": 3},
        {"section_key": "HISTORY", "risk_weight": 5},
    ])
    submitted = validate_success(api.submit_questionnaire(qr["id"], PATIENT))
    assert submitted["provisional_risk_score"] == 12, "plain sum 4+3+5"

    accepted = validate_success(api.accept_questionnaire(qr["id"], FRONT))
    assert accepted["final_risk_score"] == 24, "weighted (4+3+5)*2"
    assert accepted["high_risk_flag"] is True
    assert accepted["status"] == "FLAGGED", "high-risk acceptance lands in FLAGGED"


def test_high_risk_acceptance_lands_flagged(api):
    """PRD §3.8: "The `high_risk_flag` is set true when the `final_risk_score` is at
    least 20, and false otherwise."
    PRD §3.8: "if the final score is at least 20 (the flag is true) it lands in
    `FLAGGED` instead."

    Design: Difficulty/non_linear_state_machine/questionnaire_revise_cycle
    """
    clinic, provider, patient, appt, session, qr = fixtures.setup_questionnaire_flagged(
        clinic_name="C6", required_sections=["ALLERGIES"], risk_weight=10
    )
    # weight 10 on required ALLERGIES -> final 20 >= 20 -> FLAGGED
    assert qr["status"] == "FLAGGED"
    assert qr["final_risk_score"] == 20
    assert qr["high_risk_flag"] is True


def test_revise_flagged_clears_final_score(api):
    """PRD §3.8: "A `Patient` may revise a questionnaire that is `SUBMITTED` or
    `FLAGGED`, moving it back to `DRAFT`"
    PRD §3.8: "Revising clears `final_risk_score` back to null and `high_risk_flag`
    back to false"

    Design: Difficulty/non_linear_state_machine/questionnaire_revise_cycle
    """
    clinic, provider, patient, appt, session, qr = fixtures.setup_questionnaire_flagged(
        clinic_name="C6b", required_sections=["ALLERGIES"], risk_weight=10
    )
    revised = validate_success(api.revise_questionnaire(qr["id"], PATIENT))
    assert revised["status"] == "DRAFT"
    assert revised["final_risk_score"] is None, "final score cleared to null"
    assert revised["high_risk_flag"] is False


def test_provisional_final_diverge_second_view(api):
    """PRD §3.8: "On submit, the `provisional_risk_score` is computed as the plain
    sum of the `risk_weight` values across all `answered_sections`."

    Design: Difficulty/dual_variant_calc/questionnaire_provisional_vs_final_diverge
    """
    clinic = fixtures.create_clinic(name="C2b", form_expiration_hours=72)
    provider = fixtures.create_provider(
        clinic["id"], questionnaire_required_sections=["ALLERGIES", "MEDICATIONS", "HISTORY"]
    )
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    qr = fixtures.create_questionnaire(session["id"], answered_sections=[
        {"section_key": "ALLERGIES", "risk_weight": 4},
        {"section_key": "MEDICATIONS", "risk_weight": 3},
        {"section_key": "HISTORY", "risk_weight": 5},
    ])
    fixtures.submit_questionnaire(qr["id"])
    fixtures.accept_questionnaire(qr["id"])
    fetched = validate_success(api.get_questionnaire(qr["id"], FRONT))
    assert fetched["provisional_risk_score"] == 12
    assert fetched["final_risk_score"] == 24
    assert fetched["provisional_risk_score"] != fetched["final_risk_score"]


def test_revise_submitted_back_to_draft(api):
    """PRD §3.8: "A `Patient` may revise a questionnaire that is `SUBMITTED` or
    `FLAGGED`, moving it back to `DRAFT`"

    Design: Difficulty/non_linear_state_machine/questionnaire_revise_cycle
    """
    clinic = fixtures.create_clinic(name="C6c", form_expiration_hours=72)
    provider = fixtures.create_provider(clinic["id"], questionnaire_required_sections=["ALLERGIES"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    qr = fixtures.create_questionnaire(session["id"], answered_sections=[
        {"section_key": "ALLERGIES", "risk_weight": 2},
    ])
    fixtures.submit_questionnaire(qr["id"])
    revised = validate_success(api.revise_questionnaire(qr["id"], PATIENT))
    assert revised["status"] == "DRAFT"
    assert revised["final_risk_score"] is None


def test_accept_incomplete_questionnaire_rejected(api):
    """PRD §3.8: "Acceptance requires the `SUBMITTED` status (otherwise
    `ERR_QUESTIONNAIRE_NOT_SUBMITTED`) and requires that `answered_sections` cover
    every key in the provider's `questionnaire_required_sections` (otherwise
    `ERR_QUESTIONNAIRE_INCOMPLETE`)."

    Design: Corner/validations/questionnaire_accept_incomplete_rejected
    """
    clinic = fixtures.create_clinic(name="CE11", form_expiration_hours=72)
    provider = fixtures.create_provider(
        clinic["id"], questionnaire_required_sections=["ALLERGIES", "MEDICATIONS"]
    )
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    qr = fixtures.create_questionnaire(session["id"], answered_sections=[
        {"section_key": "ALLERGIES", "risk_weight": 2},
    ])
    fixtures.submit_questionnaire(qr["id"])

    resp = api.accept_questionnaire(qr["id"], FRONT)
    validate_error(resp, "ERR_QUESTIONNAIRE_INCOMPLETE")

    after = validate_success(api.get_questionnaire(qr["id"], FRONT))
    assert after["status"] == "SUBMITTED", "rejected accept leaves it SUBMITTED"


def test_waive_copay_blocked_when_high_risk(api):
    """PRD §3.10: "Waiving requires the financial dimension to be `COPAY_DUE`
    (otherwise `ERR_COPAY_NOT_DUE`) and is blocked when the session's questionnaire
    response has `high_risk_flag` set true — in that case the waive is rejected
    with `ERR_WAIVE_BLOCKED_HIGH_RISK`."

    Design: Corner/validations/waive_blocked_high_risk
    """
    clinic = fixtures.create_clinic(name="CE12", copay_rounding="PER_LINE_THEN_SUM", facility_fee_cents=0)
    provider = fixtures.create_provider(clinic["id"], questionnaire_required_sections=["ALLERGIES"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])

    qr = fixtures.create_questionnaire(session["id"], answered_sections=[
        {"section_key": "ALLERGIES", "risk_weight": 10},
    ])
    fixtures.submit_questionnaire(qr["id"])
    fixtures.accept_questionnaire(qr["id"])

    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=2500, plan_coinsurance_pct=0, facility_coinsurance_pct=0,
        remaining_deductible_cents=0, visit_allowed_amount_cents=5000,
    )
    pre = validate_success(api.get_intake_session(session["id"], FRONT))
    assert pre["financial_status"] == "COPAY_DUE"

    resp = api.waive_copay(session["id"], BILLING)
    validate_error(resp, "ERR_WAIVE_BLOCKED_HIGH_RISK")

    after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert after["financial_status"] == "COPAY_DUE", "blocked waive leaves COPAY_DUE"

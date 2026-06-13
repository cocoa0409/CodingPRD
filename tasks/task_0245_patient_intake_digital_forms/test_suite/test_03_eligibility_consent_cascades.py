"""Eligibility resolution, consent lifecycle, and the readiness cascade
(PRD §3.4, §3.5, §3.7).

Covers the depth-3 sign->forms_complete->READY->enqueue cascade, the INELIGIBLE
self-pay cascade, the empty-required-sections readiness path, the consent
revoke/reissue and questionnaire revise cycles, the NEEDS_REVIEW re-verify loop,
and the immediate visibility of eligibility resolution.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    fixtures,
)

FRONT = TEST_USERS["front_desk_headers"]
PATIENT = TEST_USERS["patient_headers"]


def _queue_entries_for(api, session_id):
    resp = api.list_queue_entries(FRONT, params={"intake_session_id": session_id})
    data, _meta = validate_paginated(resp)
    return data


def test_sign_last_consent_readies_and_enqueues(api):
    """PRD §3.7: "if it flips true and the financial gate is met the session advances to `READY_FOR_VISIT`, which itself enqueues a queue entry as in §3.4."
    PRD §3.4: "the system automatically enqueues the session by creating one `KioskQueueEntry` with `status` `WAITING` for the session, increments the clinic's `active_queue_count` by one, and increments the clinic's `version`."

    Design: Difficulty/transitive_cascade/sign_last_consent_ready_enqueues_queue
    """
    clinic = fixtures.create_clinic(name="C7", form_expiration_hours=72, facility_fee_cents=0)
    provider = fixtures.create_provider(clinic["id"], required_consent_codes=["HIPAA_NPP"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=0, plan_coinsurance_pct=0, facility_coinsurance_pct=0,
        remaining_deductible_cents=0, visit_allowed_amount_cents=0,
    )
    consent = fixtures.create_consent(session["id"], "HIPAA_NPP")

    validate_success(api.sign_consent(consent["id"], {"signer_name": "Pat G"}, PATIENT))

    data = validate_success(api.get_intake_session(session["id"], FRONT))
    assert data["forms_complete"] is True
    assert data["workflow_status"] == "READY_FOR_VISIT"
    assert data["financial_status"] == "INSURED"

    entries = [e for e in _queue_entries_for(api, session["id"]) if e["status"] == "WAITING"]
    assert len(entries) == 1, "exactly one WAITING queue entry auto-created"

    clinic_after = validate_success(api.get_clinic(clinic["id"], FRONT))
    assert clinic_after["active_queue_count"] == 1


def test_sign_last_consent_enqueues_exactly_one_entry(api):
    """PRD §3.4: "the system automatically enqueues the session by creating one `KioskQueueEntry` with `status` `WAITING` for the session, increments the clinic's `active_queue_count` by one, and increments the clinic's `version`."

    Design: Difficulty/transitive_cascade/sign_last_consent_ready_enqueues_queue
    """
    clinic = fixtures.create_clinic(name="C7b", form_expiration_hours=72, facility_fee_cents=0)
    provider = fixtures.create_provider(clinic["id"], required_consent_codes=["HIPAA_NPP"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(session["id"], outcome="ELIGIBLE")
    consent = fixtures.create_consent(session["id"], "HIPAA_NPP")

    before = validate_success(api.get_clinic(clinic["id"], FRONT))
    assert before["active_queue_count"] == 0

    fixtures.sign_consent(consent["id"], "Pat G")

    entries = _queue_entries_for(api, session["id"])
    waiting = [e for e in entries if e["status"] == "WAITING"]
    assert len(waiting) == 1
    after = validate_success(api.get_clinic(clinic["id"], FRONT))
    assert after["active_queue_count"] == 1


def test_empty_required_sections_questionnaire_trivially_complete(api):
    """PRD §3.4: "the questionnaire is complete: either the provider's `questionnaire_required_sections` is empty, or the session has a questionnaire response whose `status` is `ACCEPTED`"
    PRD §3.4: "a provider with an empty `questionnaire_required_sections` makes the questionnaire condition trivially true."

    Design: Difficulty/boundary_precision_check/empty_required_sections_questionnaire_trivially_complete
    """
    clinic = fixtures.create_clinic(name="C12", form_expiration_hours=72, facility_fee_cents=0)
    provider = fixtures.create_provider(
        clinic["id"], required_consent_codes=["HIPAA_NPP"], questionnaire_required_sections=[]
    )
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=0, plan_coinsurance_pct=0, facility_coinsurance_pct=0,
        remaining_deductible_cents=0, visit_allowed_amount_cents=0,
    )
    consent = fixtures.create_consent(session["id"], "HIPAA_NPP")

    validate_success(api.sign_consent(consent["id"], {"signer_name": "Pat L"}, PATIENT))

    data = validate_success(api.get_intake_session(session["id"], FRONT))
    assert data["forms_complete"] is True, "no questionnaire needed when sections empty"
    assert data["workflow_status"] == "READY_FOR_VISIT"


def test_empty_required_sections_no_questionnaire_entity_needed(api):
    """PRD §3.4: "the questionnaire is complete: either the provider's `questionnaire_required_sections` is empty, or the session has a questionnaire response whose `status` is `ACCEPTED`"

    Design: Difficulty/boundary_precision_check/empty_required_sections_questionnaire_trivially_complete
    """
    clinic = fixtures.create_clinic(name="C12b", form_expiration_hours=72, facility_fee_cents=0)
    provider = fixtures.create_provider(
        clinic["id"], required_consent_codes=["HIPAA_NPP"], questionnaire_required_sections=[]
    )
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(session["id"], outcome="ELIGIBLE")
    consent = fixtures.create_consent(session["id"], "HIPAA_NPP")

    # No questionnaire response created at all; signing the consent alone is enough.
    signed = validate_success(api.sign_consent(consent["id"], {"signer_name": "Pat L"}, PATIENT))
    assert signed["status"] == "SIGNED"

    data = validate_success(api.get_intake_session(session["id"], FRONT))
    assert data["forms_complete"] is True
    assert data["workflow_status"] == "READY_FOR_VISIT"


def test_ineligible_outcome_cascades_to_self_pay(api):
    """PRD §3.5: "An `INELIGIBLE` outcome moves the card to `INELIGIBLE`, then runs a cascade chain: the session's `final_patient_responsibility_cents` is recomputed at the self-pay rate (the full allowed amount plus the facility fee, with no plan offset and no coinsurance), and the session's `financial_status` becomes `SELF_PAY`."

    Design: Difficulty/transitive_cascade/eligibility_ineligible_self_pay_cascade
    """
    clinic = fixtures.create_clinic(name="C8", facility_fee_cents=500)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    card, resolved = fixtures.capture_verify_resolve(
        session["id"], outcome="INELIGIBLE",
        plan_copay_cents=3000, plan_coinsurance_pct=20, facility_coinsurance_pct=0,
        remaining_deductible_cents=5000, visit_allowed_amount_cents=8000,
    )
    assert resolved["eligibility_status"] == "INELIGIBLE"

    data = validate_success(api.get_intake_session(session["id"], FRONT))
    # self-pay = allowed 8000 + facility 500 = 8500
    assert data["final_patient_responsibility_cents"] == 8500
    assert data["financial_status"] == "SELF_PAY"


def test_self_pay_cascade_visible_on_card(api):
    """PRD §3.5: "An `INELIGIBLE` outcome moves the card to `INELIGIBLE"

    Design: Difficulty/transitive_cascade/eligibility_ineligible_self_pay_cascade
    """
    clinic = fixtures.create_clinic(name="C8b", facility_fee_cents=500)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    card, _ = fixtures.capture_verify_resolve(
        session["id"], outcome="INELIGIBLE",
        remaining_deductible_cents=5000, visit_allowed_amount_cents=8000,
    )
    fetched = validate_success(api.get_insurance_card(card["id"], FRONT))
    assert fetched["eligibility_status"] == "INELIGIBLE"
    session_after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert session_after["financial_status"] == "SELF_PAY"


def test_consent_revoke_reissue_cycle_bumps_revision(api):
    """PRD §3.7: "Re-issue moves the document back to `PENDING` and increments its
    `revision`, closing the"

    Design: Difficulty/non_linear_state_machine/consent_revoke_reissue_cycle
    """
    clinic, provider, patient, appt, session, consent = fixtures.setup_consent_signed_then_revoked(
        clinic_name="C5", consent_code="HIPAA_NPP"
    )
    reissued = validate_success(api.reissue_consent(consent["id"], FRONT))
    assert reissued["status"] == "PENDING"
    assert reissued["revision"] == 2, "revision incremented on re-issue"


def test_consent_cycle_returns_to_pending(api):
    """PRD §3.7: "re-issue requires the document to be `REVOKED` (otherwise `ERR_CONSENT_NOT_REVOKED`)"

    Design: Difficulty/non_linear_state_machine/consent_revoke_reissue_cycle
    """
    clinic, provider, patient, appt, session, consent = fixtures.setup_consent_signed_then_revoked(
        clinic_name="C5b", consent_code="HIPAA_NPP"
    )
    fixtures.api_client.reissue_consent(consent["id"], FRONT)
    fetched = validate_success(api.get_consent_document(consent["id"], FRONT))
    assert fetched["status"] == "PENDING"
    assert fetched["revision"] == 2


def test_sign_already_signed_consent_rejected(api):
    """PRD §3.7: "Signing requires the document to be `PENDING` (otherwise `ERR_CONSENT_NOT_PENDING`)"

    Design: Corner/state_machines/sign_already_signed_consent_invalid
    """
    clinic = fixtures.create_clinic(name="CE3", form_expiration_hours=72)
    provider = fixtures.create_provider(clinic["id"], required_consent_codes=["HIPAA_NPP"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    consent = fixtures.create_consent(session["id"], "HIPAA_NPP")
    fixtures.sign_consent(consent["id"], "Pat X")

    resp = api.sign_consent(consent["id"], {"signer_name": "Pat X"}, PATIENT)
    validate_error(resp, "ERR_CONSENT_NOT_PENDING")


def test_consent_code_not_required_rejected(api):
    """PRD §3.7: "The code must be one that the provider actually requires: if the `consent_code` is not present in the provider's `required_consent_codes`, the issuance is rejected with `ERR_CONSENT_CODE_NOT_REQUIRED`."

    Design: Corner/state_machines/consent_code_not_required_by_provider
    """
    clinic = fixtures.create_clinic(name="CE4", form_expiration_hours=72)
    provider = fixtures.create_provider(clinic["id"], required_consent_codes=["HIPAA_NPP"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])

    resp = api.create_consent_document(
        {"intake_session_id": session["id"], "consent_code": "FINANCIAL_POLICY"}, FRONT
    )
    validate_error(resp, "ERR_CONSENT_CODE_NOT_REQUIRED")


def test_needs_review_reverify_cycle(api):
    """PRD §3.5: "A `NEEDS_REVIEW` outcome moves the card to `NEEDS_REVIEW` and records the check, but does not resolve eligibility; from `NEEDS_REVIEW` the clerk may begin verification again, forming the re-verification cycle."

    Design: Corner/state_machines/eligibility_needs_review_reverify_cycle
    """
    clinic = fixtures.create_clinic(name="CE6", facility_fee_cents=0)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    card = fixtures.capture_card(
        session["id"], plan_copay_cents=0, plan_coinsurance_pct=0, facility_coinsurance_pct=0,
        remaining_deductible_cents=0, visit_allowed_amount_cents=0,
    )
    fixtures.verify_card(card["id"])
    fixtures.resolve_card(card["id"], "NEEDS_REVIEW")
    fixtures.verify_card(card["id"])  # re-verify from NEEDS_REVIEW

    resolved = validate_success(api.resolve_eligibility(card["id"], {"outcome": "ELIGIBLE"}, FRONT))
    assert resolved["eligibility_status"] == "ELIGIBLE"
    session_after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert session_after["financial_status"] == "INSURED"


def test_invalid_eligibility_outcome_rejected(api):
    """PRD §3.5: "The clerk then resolves the verification by supplying an `outcome`, which must be one of `ELIGIBLE`, `INELIGIBLE`, or `NEEDS_REVIEW`; any other value is rejected with `ERR_INVALID_OUTCOME`."

    Design: Corner/errors/invalid_eligibility_outcome_rejected
    """
    clinic = fixtures.create_clinic(name="CE17", facility_fee_cents=0)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    card = fixtures.capture_card(session["id"])
    fixtures.verify_card(card["id"])

    resp = api.resolve_eligibility(card["id"], {"outcome": "MAYBE"}, FRONT)
    validate_error(resp, "ERR_INVALID_OUTCOME")


def test_eligibility_resolution_immediately_visible(api):
    """PRD §3.5: "An `ELIGIBLE` outcome moves the card to `ELIGIBLE`, computes the session's `final_patient_responsibility_cents` via the four-leg split in §3.6, and cascades the session's `financial_status`: to `INSURED` if the finalized responsibility is exactly 0, or to `COPAY_DUE` if it is greater than 0."

    Design: Corner/consistency_model/eligibility_resolution_immediately_visible
    """
    clinic = fixtures.create_clinic(name="CE23", copay_rounding="PER_LINE_THEN_SUM", facility_fee_cents=500)
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=3000, plan_coinsurance_pct=20, facility_coinsurance_pct=0,
        remaining_deductible_cents=5000, visit_allowed_amount_cents=8000,
    )

    data = validate_success(api.get_intake_session(session["id"], FRONT))
    assert data["financial_status"] == "COPAY_DUE"
    assert data["final_patient_responsibility_cents"] == 9100
